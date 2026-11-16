"""An agent whose model fails after a tool ran continues on its fallback model.

The fallback used to restart from the original prompt, so every tool the first model had
already run (send an email, create a ticket, charge a card) ran a second time. The fallback
now continues from the first model's history on the same transport; on another transport it
starts from the prompt as before.
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import CredentialType
from app.services.encryption import encrypt_config
from app.services.llm_service import LLMService, ToolLoopProgress, tool_loop_progress
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
