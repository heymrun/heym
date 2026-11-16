"""After a Human review approval, a fallback model resumes without the primary's reasoning (#1008).

The review pause stores the primary's tool loop history, provider-bound reasoning included, and
every attempt of the resumed run loads it. OpenAI refuses another organization's encrypted
`reasoning` items (`invalid_encrypted_content`), so a primary that failed after the approval
took its fallback down with it and the approved action never happened. The fallback's attempt
now loads the history the way #1006 hands one to a fallback; the primary's own resume is
unchanged.

The Responses flow runs the real `WorkflowExecutor._execute_agent_node` to the pause and again
with the `continue_agent` resume context, as `test_agent_hitl_resume_providers.py` does.
Mocked: the credential lookup, DNS for api.openai.com, and OpenAI at the httpx transport.
"""

from __future__ import annotations

import json
import socket
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.encryption import encrypt_config
from app.services.llm_service import LLMService
from app.services.llm_transport_gemini import GEMINI_SKIP_SIGNATURE
from app.services.workflow_executor import WorkflowExecutor

PRIMARY, FALLBACK = str(uuid.uuid4()), str(uuid.uuid4())
REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "org-a"}
REVIEW_ARGS = {
    "summary": "Send shipping email",
    "review_markdown": "Order shipped.",
    "reason": "Email",
}

_real_getaddrinfo = socket.getaddrinfo


def fake_getaddrinfo(host, *args, **kwargs):  # resolver seam, no network
    if host == "api.openai.com":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("162.159.140.245", 443))]
    return _real_getaddrinfo(host, *args, **kwargs)


def _reply(request: httpx.Request, output: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "resp_1",
            "object": "response",
            "created_at": 0,
            "model": "x",
            "status": "completed",
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        },
        request=request,
    )


def _error(request: httpx.Request, code: str, message: str) -> httpx.Response:
    return httpx.Response(
        400,
        json={"error": {"message": message, "type": "invalid_request_error", "code": code}},
        request=request,
    )


def _call(call_id: str, name: str, args: dict) -> dict:
    return {
        "type": "function_call",
        "id": f"fc_{call_id}",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(args),
        "status": "completed",
    }


class OpenAIStub:
    """The primary looks the order up (with reasoning), then asks for review.

    After the approval the primary fails or answers, as the test sets. The fallback's key
    refuses any reasoning item, as OpenAI does for another organization's.
    """

    def __init__(self, *, primary_resume_fails: bool) -> None:
        self.primary_resume_fails = primary_resume_fails
        self.requests: list[dict] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        key = request.headers["authorization"].removeprefix("Bearer ")
        self.requests.append({"key": key, "input": body["input"]})
        looked_up = any(i.get("type") == "function_call_output" for i in body["input"])
        resumed = "Human review decision received" in json.dumps(body["input"])
        if key == f"sk-{PRIMARY}":
            if not looked_up:
                return _reply(
                    request, [REASONING, _call("call_1", "lookup_order", {"order": "42"})]
                )
            if not resumed:
                return _reply(request, [_call("call_2", "request_human_review", REVIEW_ARGS)])
            if self.primary_resume_fails:
                return _error(request, "context_length_exceeded", "Input is too long.")
        elif any(i.get("type") == "reasoning" for i in body["input"]):
            return _error(request, "invalid_encrypted_content", "rs_1 could not be verified.")
        text = {"type": "output_text", "text": "DONE", "annotations": []}
        return _reply(
            request,
            [
                {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [text],
                }
            ],
        )

    def requests_by(self, credential_id: str) -> list[list[dict]]:
        return [r["input"] for r in self.requests if r["key"] == f"sk-{credential_id}"]


CREDENTIALS = {
    cid: SimpleNamespace(
        id=uuid.UUID(cid),
        type=CredentialType.openai,
        name=cid,
        encrypted_config=encrypt_config({"api_key": f"sk-{cid}"}),
    )
    for cid in (PRIMARY, FALLBACK)
}
NODE = {
    "label": "Mailer",
    "credentialId": PRIMARY,
    "model": "o4-mini",
    "fallbackCredentialId": FALLBACK,
    "fallbackModel": "gpt-4o",
    "responsesApiEnabled": True,
    "userMessage": "Tell ACME their order shipped.",
    "hitlEnabled": True,
    "hitlSummary": "Ask for approval before sending any email.",
    "tools": [
        {
            "name": "lookup_order",
            "description": "Look an order up",
            "parameters": {"type": "object", "properties": {"order": {"type": "string"}}},
            "code": "def lookup_order(order: str) -> dict:\n    return {'status': 'shipped'}\n",
        }
    ],
}


def _executor() -> WorkflowExecutor:
    wf = WorkflowExecutor(
        nodes=[{"id": "agent-1", "type": "agent", "data": NODE}], edges=[], execution_id="exec-1"
    )
    wf._get_accessible_credential = lambda _db, cid: CREDENTIALS[str(cid)]  # credential seam
    return wf


class ResponsesReviewResumeFallbackTests(unittest.TestCase):
    def _pause_then_resume(self, stub: OpenAIStub) -> dict:
        with (
            patch("socket.getaddrinfo", fake_getaddrinfo),
            patch("httpx.HTTPTransport.handle_request", lambda _t, req: stub.handle(req)),
            patch("app.services.llm_service.record_llm_trace"),
        ):
            paused = _executor()._execute_agent_node("agent-1", {}, NODE)
            resumed = _executor()
            resumed.hitl_resume_context["agent-1"] = {
                "decision": "accepted",
                "summary": REVIEW_ARGS["summary"],
                "originalDraft": REVIEW_ARGS["review_markdown"],
                "reviewText": REVIEW_ARGS["review_markdown"],
                "requestId": "req-1",
                "_agent_state": paused["_hitl_pending"]["agent_state"],
            }
            return resumed._execute_agent_node("agent-1", {}, NODE)

    def test_the_fallback_finishes_the_approved_run_without_the_primarys_reasoning(self) -> None:
        stub = OpenAIStub(primary_resume_fails=True)

        result = self._pause_then_resume(stub)

        self.assertIsNone(result.get("error"))
        self.assertEqual(result["text"], "DONE")
        self.assertTrue(result["fallbackUsed"])
        first = stub.requests_by(FALLBACK)[0]
        self.assertNotIn("reasoning", [item.get("type") for item in first])
        self.assertIn("function_call", [item.get("type") for item in first])
        self.assertIn("function_call_output", [item.get("type") for item in first])

    def test_the_primarys_own_resume_keeps_its_reasoning(self) -> None:
        stub = OpenAIStub(primary_resume_fails=False)

        result = self._pause_then_resume(stub)

        self.assertEqual(result["text"], "DONE")
        self.assertIn(REASONING, stub.requests_by(PRIMARY)[-1])
        self.assertEqual(stub.requests_by(FALLBACK), [])


class GeminiReviewResumeFallbackTests(unittest.IsolatedAsyncioTestCase):
    """A resumed Gemini history: the fallback sends Google's opt-out, the primary its signature."""

    MODEL = "gemini-4-argon-contributor"
    GATEWAY = "https://opencode.ai/inference/go/v1"
    HISTORY = [
        {"role": "user", "parts": [{"text": "Tell ACME their order shipped."}]},
        {
            "role": "model",
            "parts": [
                {
                    "thoughtSignature": "sig-primary",
                    "functionCall": {"id": "c1", "name": "lookup_order", "args": {}},
                }
            ],
        },
        {
            "role": "user",
            "parts": [{"functionResponse": {"id": "c1", "name": "lookup_order", "response": {}}}],
        },
        {"role": "user", "content": "Human review decision received: accepted."},
    ]

    async def _first_request_signatures(self, *, from_another_model: bool) -> list[str]:
        client = MagicMock()
        client.base_url = httpx.URL(self.GATEWAY + "/")
        bodies: list[dict] = []

        def post(_url: str, *, cast_to: object, body: dict) -> object:
            bodies.append(body)
            payload = {
                "candidates": [
                    {"index": 0, "content": {"role": "model", "parts": [{"text": "DONE"}]}}
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2},
            }
            return SimpleNamespace(json=lambda: payload)

        client.post.side_effect = post
        service = LLMService(CredentialType.custom, "key", self.GATEWAY)
        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch("app.services.llm_service.record_llm_trace"),
            patch("app.services.context_compressor.get_context_limit", return_value=100000),
        ):
            result = await service.execute_with_tools(
                model=self.MODEL,
                system_instruction="Notify ACME.",
                user_message="Tell ACME their order shipped.",
                tools=[{"name": "lookup_order", "parameters": {"type": "object"}}],
                tool_executor=lambda *_args: {"status": "shipped"},
                initial_messages=self.HISTORY,
                initial_messages_from_another_model=from_another_model,
            )
        self.assertEqual(result["text"], "DONE")
        return [
            part["thoughtSignature"]
            for content in bodies[0]["contents"]
            for part in content.get("parts") or []
            if "thoughtSignature" in part
        ]

    async def test_the_fallback_sends_the_opt_out_instead_of_the_primarys_signature(self) -> None:
        signatures = await self._first_request_signatures(from_another_model=True)

        self.assertEqual(signatures, [GEMINI_SKIP_SIGNATURE])

    async def test_the_primarys_own_resume_keeps_its_signature(self) -> None:
        signatures = await self._first_request_signatures(from_another_model=False)

        self.assertEqual(signatures, ["sig-primary"])
        self.assertEqual(self.HISTORY[1]["parts"][0]["thoughtSignature"], "sig-primary")


if __name__ == "__main__":
    unittest.main()
