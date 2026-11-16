"""An agent whose model fails after a tool ran continues on its fallback model.

The fallback used to restart from the original prompt, so every tool the first model had
already run (send an email, create a ticket, charge a card) ran a second time. The fallback
now continues from the first model's history on the same transport; on another transport it
starts from the prompt as before. Reasoning the provider binds to the first model and key
(Responses `reasoning` items, Gemini thought signatures) does not reach the fallback.
"""

from __future__ import annotations

import copy
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.encryption import encrypt_config
from app.services.llm_service import LLMService, ToolLoopProgress, tool_loop_progress
from app.services.llm_transport_gemini import GEMINI_SKIP_SIGNATURE, without_thought_signatures
from app.services.workflow_executor import WorkflowExecutor


def _response(*, content: str | None, tool_calls: list[object]) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
    )


SEND_EMAIL_CALL = SimpleNamespace(
    id="call-1",
    type="function",
    function=SimpleNamespace(name="send_email", arguments='{"to":"ops@acme.test"}'),
)


class ToolLoopProgressTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self, replies: list[object], continue_from: ToolLoopProgress | None = None
    ) -> tuple[dict, list[str], list[list[dict]]]:
        requests: list[list[dict]] = []

        def create(**kwargs: object) -> SimpleNamespace:
            requests.append(list(kwargs["messages"]))
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")
        sent: list[str] = []

        def send_email(_tool: dict, _name: str, args: dict, _timeout: float) -> dict:
            sent.append(args["to"])
            return {"sent": True}

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            result = await service.execute_with_tools(
                model="gpt-4o",
                system_instruction="Notify ops.",
                user_message="Tell ops the order shipped.",
                tools=[{"name": "send_email", "parameters": {"type": "object"}}],
                tool_executor=send_email,
                continue_from=continue_from,
            )
        return result, sent, requests

    async def _interrupted(self) -> RuntimeError:
        with self.assertRaises(RuntimeError) as caught:
            await self._run(
                [
                    _response(content=None, tool_calls=[SEND_EMAIL_CALL]),
                    RuntimeError("Error code: 500 - server_error"),
                ]
            )
        return caught.exception

    async def test_an_error_after_a_tool_ran_carries_the_history(self) -> None:
        error = await self._interrupted()

        self.assertIn("server_error", str(error))
        progress = tool_loop_progress(error)
        assert progress is not None
        self.assertEqual(progress.transport, "chat.completions")
        self.assertEqual([m["role"] for m in progress.messages][-2:], ["assistant", "tool"])
        self.assertEqual([tc["name"] for tc in progress.tool_calls], ["send_email"])
        self.assertEqual(progress.prompt_tokens, 10)

    async def test_an_error_before_any_tool_raises_as_before(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            await self._run([RuntimeError("Error code: 500 - server_error")])

        self.assertIsNone(tool_loop_progress(caught.exception))

    async def test_the_fallback_continues_without_running_the_tool_again(self) -> None:
        progress = tool_loop_progress(await self._interrupted())

        result, sent, requests = await self._run(
            [_response(content="Email sent.", tool_calls=[])], continue_from=progress
        )

        self.assertEqual(sent, [])
        self.assertEqual(result["text"], "Email sent.")
        self.assertEqual([tc["name"] for tc in result["tool_calls"]], ["send_email"])
        self.assertEqual([m["role"] for m in requests[0]][-2:], ["assistant", "tool"])
        self.assertEqual(result["usage"]["prompt_tokens"], 20)

    async def test_another_transport_starts_from_the_prompt(self) -> None:
        progress = tool_loop_progress(await self._interrupted())
        other = ToolLoopProgress(
            transport="responses",
            messages=progress.messages,
            tool_calls=progress.tool_calls,
            elapsed_ms=progress.elapsed_ms,
            prompt_tokens=progress.prompt_tokens,
            completion_tokens=progress.completion_tokens,
        )

        _result, _sent, requests = await self._run(
            [_response(content="Email sent.", tool_calls=[])], continue_from=other
        )

        self.assertEqual([m["role"] for m in requests[0]], ["system", "user"])


class _ProviderBoundReasoningCase(unittest.IsolatedAsyncioTestCase):
    """The first model runs a tool and fails with a 500; the fallback continues its history."""

    async def _loop(
        self, service: LLMService, client: object, model: str, continue_from: object = None
    ) -> tuple[dict, list[str]]:
        sent: list[str] = []

        def send_email(_tool: dict, _name: str, _args: dict, _timeout: float) -> dict:
            sent.append("ops")
            return {"sent": True}

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace"),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            result = await service.execute_with_tools(
                model=model,
                system_instruction="Notify ops.",
                user_message="Tell ops the order shipped.",
                tools=[{"name": "send_email", "parameters": {"type": "object"}}],
                tool_executor=send_email,
                continue_from=continue_from,
            )
        return result, sent

    async def _interrupted(self, service: LLMService, client: object, model: str) -> object:
        with self.assertRaises(RuntimeError) as caught:
            await self._loop(service, client, model)
        progress = tool_loop_progress(caught.exception)
        assert progress is not None
        return progress


def _responses_reply(items: list[dict]) -> MagicMock:
    reply = MagicMock()
    reply.output = items
    reply.usage.input_tokens, reply.usage.output_tokens, reply.usage.total_tokens = 10, 2, 12
    return reply


class ResponsesFallbackReasoningTests(_ProviderBoundReasoningCase):
    """Encrypted reasoning belongs to the first model's organization and model."""

    REASONING = {"type": "reasoning", "id": "rs_1", "encrypted_content": "org-a-blob"}
    CALL = {"type": "function_call", "call_id": "fc_1", "name": "send_email", "arguments": "{}"}

    def _client(self, replies: list[object]) -> MagicMock:
        client = MagicMock()
        client.base_url = "https://api.openai.com/v1"
        client.responses.create.side_effect = replies
        return client

    async def test_no_reasoning_item_reaches_the_fallbacks_request(self) -> None:
        primary = self._client(
            [
                _responses_reply([self.REASONING, self.CALL]),
                RuntimeError("Error code: 500 - server_error"),
            ]
        )
        progress = await self._interrupted(
            LLMService(CredentialType.openai, "sk-a", use_responses_api=True), primary, "o4-mini"
        )
        done = {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Email sent."}],
        }
        fallback = self._client([_responses_reply([done])])

        result, sent = await self._loop(
            LLMService(CredentialType.openai, "sk-b", use_responses_api=True),
            fallback,
            "gpt-4o",
            progress,
        )

        sent_input = fallback.responses.create.call_args_list[0].kwargs["input"]
        self.assertNotIn("reasoning", [item.get("type") for item in sent_input])
        self.assertEqual(
            [item.get("type") for item in sent_input][-2:],
            ["function_call", "function_call_output"],
        )
        self.assertEqual(sent, [])
        self.assertEqual(result["text"], "Email sent.")

    async def test_the_first_models_own_next_turn_keeps_its_reasoning(self) -> None:
        primary = self._client(
            [
                _responses_reply([self.REASONING, self.CALL]),
                RuntimeError("Error code: 500 - server_error"),
            ]
        )
        await self._interrupted(
            LLMService(CredentialType.openai, "sk-a", use_responses_api=True), primary, "o4-mini"
        )

        self.assertIn(self.REASONING, primary.responses.create.call_args_list[1].kwargs["input"])


class GeminiFallbackSignatureTests(_ProviderBoundReasoningCase):
    """A thought signature can only be validated by the Gemini model that wrote it."""

    MODEL = "gemini-4-argon-contributor"
    GATEWAY = "https://opencode.ai/inference/go/v1"

    def _client(self, replies: list[object]) -> MagicMock:
        client = MagicMock()
        client.base_url = httpx.URL(self.GATEWAY + "/")
        client.bodies = []

        def post(_url: str, *, cast_to: object, body: dict) -> object:
            client.bodies.append(copy.deepcopy(body))
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return SimpleNamespace(json=lambda: reply)

        client.post.side_effect = post
        return client

    @staticmethod
    def _payload(parts: list[dict]) -> dict:
        return {
            "candidates": [{"index": 0, "content": {"role": "model", "parts": parts}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
        }

    @staticmethod
    def _signatures(body: dict) -> list[str]:
        return [
            part["thoughtSignature"]
            for content in body["contents"]
            for part in content.get("parts") or []
            if "thoughtSignature" in part
        ]

    async def test_the_fallback_sends_the_opt_out_instead_of_the_first_models_signature(
        self,
    ) -> None:
        call = {
            "thoughtSignature": "sig-model-a",
            "functionCall": {"id": "c1", "name": "send_email", "args": {}},
        }
        primary = self._client(
            [self._payload([call]), RuntimeError("Error code: 500 - server_error")]
        )
        progress = await self._interrupted(
            LLMService(CredentialType.custom, "key-a", self.GATEWAY), primary, self.MODEL
        )
        fallback = self._client([self._payload([{"text": "Email sent."}])])

        result, sent = await self._loop(
            LLMService(CredentialType.custom, "key-b", self.GATEWAY), fallback, self.MODEL, progress
        )

        self.assertEqual(self._signatures(primary.bodies[1]), ["sig-model-a"])
        self.assertEqual(self._signatures(fallback.bodies[0]), [GEMINI_SKIP_SIGNATURE])
        self.assertEqual(sent, [])
        self.assertEqual(result["text"], "Email sent.")

    def test_a_signature_on_a_text_part_is_dropped(self) -> None:
        contents = [{"role": "model", "parts": [{"text": "ok", "thoughtSignature": "sig"}]}]

        self.assertEqual(without_thought_signatures(contents)[0]["parts"], [{"text": "ok"}])
        self.assertEqual(contents[0]["parts"][0]["thoughtSignature"], "sig")


class AgentFallbackTests(unittest.TestCase):
    PRIMARY, FALLBACK = str(uuid.uuid4()), str(uuid.uuid4())
    NODE = {
        "label": "Notifier",
        "credentialId": PRIMARY,
        "model": "gpt-4o",
        "fallbackCredentialId": FALLBACK,
        "fallbackModel": "gpt-4o-mini",
        "userMessage": "Tell ops the order shipped.",
        "tools": [
            {
                "name": "send_email",
                "description": "Send an email",
                "parameters": {"type": "object", "properties": {"to": {"type": "string"}}},
                "code": "def send_email(to: str) -> dict:\n    return {'sent': True}\n",
            }
        ],
    }
    PROGRESS = ToolLoopProgress(
        transport="chat.completions",
        messages=[{"role": "user", "content": "Tell ops the order shipped."}],
        tool_calls=[{"name": "send_email", "status": "success"}],
        elapsed_ms=5.0,
        prompt_tokens=10,
        completion_tokens=2,
    )

    def _run(self, first_error: Exception) -> tuple[dict, AsyncMock]:
        credentials = {
            cid: SimpleNamespace(
                id=uuid.UUID(cid),
                type=CredentialType.openai,
                name=cid,
                encrypted_config=encrypt_config({"api_key": f"sk-{cid}"}),
            )
            for cid in (self.PRIMARY, self.FALLBACK)
        }
        wf = WorkflowExecutor(
            nodes=[{"id": "agent-1", "type": "agent", "data": self.NODE}], edges=[]
        )
        wf._get_accessible_credential = lambda _db, cid: credentials[str(cid)]
        done = {"text": "Email sent.", "model": "gpt-4o-mini", "tool_calls": []}
        with patch(
            "app.services.llm_service.execute_llm_with_tools",
            AsyncMock(side_effect=[first_error, done]),
        ) as call:
            result = wf._execute_agent_node("agent-1", {}, self.NODE)
        return result, call

    def test_the_fallback_gets_the_progress_of_an_interrupted_loop(self) -> None:
        error = RuntimeError("Error code: 500")
        error.heym_tool_loop_progress = self.PROGRESS

        result, call = self._run(error)

        models = [c.kwargs["model"] for c in call.await_args_list]
        self.assertEqual(models, ["gpt-4o", "gpt-4o-mini"])
        self.assertIsNone(call.await_args_list[0].kwargs["continue_from"])
        self.assertIs(call.await_args_list[1].kwargs["continue_from"], self.PROGRESS)
        self.assertTrue(result["fallbackUsed"])

    def test_a_plain_provider_error_starts_the_fallback_from_the_prompt(self) -> None:
        result, call = self._run(RuntimeError("Error code: 500"))

        self.assertIsNone(call.await_args_list[1].kwargs["continue_from"])
        self.assertTrue(result["fallbackUsed"])


if __name__ == "__main__":
    unittest.main()
