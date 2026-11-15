"""An agent paused on a human review resumes on every provider's message format.

The approval text is appended to the saved history through the provider's transport.
A hand-built Chat-style ``{"role", "content"}`` dict worked for Chat Completions and
Messages, but a Gemini history is generateContent ``contents`` (role + parts), and Google
refuses the unknown ``content`` field with 400 INVALID_ARGUMENT.

Real ``WorkflowExecutor._execute_agent_node``, run to the pause and again with the
``continue_agent`` resume context. Mocked: the credential lookup, DNS for opencode.ai
(SSRF guard), and the provider at the httpx transport with Gemini / Messages JSON.
"""

from __future__ import annotations

import json
import socket
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.db.models import CredentialType
from app.services.encryption import encrypt_config
from app.services.workflow_executor import WorkflowExecutor

requests_seen: list[dict] = []

_real_getaddrinfo = socket.getaddrinfo


def fake_getaddrinfo(host, *args, **kwargs):  # resolver seam, no network
    if host == "opencode.ai":
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("104.18.2.161", 443))]
    return _real_getaddrinfo(host, *args, **kwargs)


REVIEW_ARGS = {
    "summary": "Send shipping email to ACME",
    "review_markdown": "Send ACME: 'Your order #42 shipped today.'",
    "reason": "Sending an email",
}


def gemini(request: httpx.Request, body: dict) -> httpx.Response:
    for index, content in enumerate(body["contents"]):
        unknown = sorted(set(content) - {"role", "parts"})
        if unknown:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "message": (
                            f'Invalid JSON payload received. Unknown name "{unknown[0]}" at '
                            f"'contents[{index}]': Cannot find field."
                        ),
                        "status": "INVALID_ARGUMENT",
                    }
                },
                request=request,
            )
    texts = [p.get("text", "") for c in body["contents"] for p in c.get("parts", [])]
    if any("Human review decision received" in t for t in texts):
        parts = [{"text": "Approved email sent to ACME."}]
    else:
        parts = [{"functionCall": {"name": "request_human_review", "args": REVIEW_ARGS}}]
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}
            ],
            "usageMetadata": {
                "promptTokenCount": 120,
                "candidatesTokenCount": 15,
                "totalTokenCount": 135,
            },
            "modelVersion": "gemini-3-flash",
        },
        request=request,
    )


def anthropic(request: httpx.Request, body: dict) -> httpx.Response:
    for index, message in enumerate(body["messages"]):
        if message.get("role") not in ("user", "assistant") or not isinstance(
            message.get("content"), (str, list)
        ):
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": f"messages.{index}: invalid message",
                    },
                },
                request=request,
            )
    flat = json.dumps(body["messages"])
    if "Human review decision received" in flat:
        content = [{"type": "text", "text": "Approved email sent to ACME."}]
        stop = "end_turn"
    else:
        content = [
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "request_human_review",
                "input": REVIEW_ARGS,
            }
        ]
        stop = "tool_use"
    return httpx.Response(
        200,
        json={
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 120, "output_tokens": 15},
        },
        request=request,
    )


def handle(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    requests_seen.append({"url": str(request.url), "body": body})
    if ":generateContent" in request.url.path:
        return gemini(request, body)
    if request.url.path.endswith("/messages"):
        return anthropic(request, body)
    return httpx.Response(404, json={"error": {"message": "not found"}}, request=request)


CREDENTIAL_ID = str(uuid.uuid4())
FAKE_CREDENTIAL = SimpleNamespace(
    id=uuid.UUID(CREDENTIAL_ID),
    type=CredentialType.custom,
    name="OpenCode Go",
    encrypted_config=encrypt_config(
        {"api_key": "oc-test-key", "base_url": "https://opencode.ai/zen/go/v1"}
    ),
)


def node_data(model: str) -> dict:
    return {
        "label": "Mailer",
        "credentialId": CREDENTIAL_ID,
        "model": model,
        "systemInstruction": "You write and send customer emails.",
        "userMessage": "Tell ACME that order #42 shipped today.",
        "temperature": 0.7,
        "hitlEnabled": True,
        "hitlSummary": "Always ask for human approval before sending any email.",
        "tools": [],
    }


def executor(model: str) -> WorkflowExecutor:
    wf = WorkflowExecutor(
        nodes=[{"id": "agent-1", "type": "agent", "data": node_data(model)}],
        edges=[],
        execution_id="exec-1",
    )
    wf._get_accessible_credential = lambda _db, _cid: FAKE_CREDENTIAL  # credential seam
    return wf


def pause_then_resume(model: str) -> dict:
    first = executor(model)
    paused = first._execute_agent_node("agent-1", {}, node_data(model))
    pending = paused.get("_hitl_pending")
    if not isinstance(pending, dict):
        return {"stage": "pause", "error": paused.get("error"), "text": paused.get("text")}
    # What resume_workflow_after_hitl puts in hitl_resume_context for continue_agent.
    second = executor(model)
    second.hitl_resume_context["agent-1"] = {
        "decision": "accepted",
        "summary": REVIEW_ARGS["summary"],
        "originalDraft": REVIEW_ARGS["review_markdown"],
        "reviewText": REVIEW_ARGS["review_markdown"],
        "requestId": "req-1",
        "_agent_state": pending["agent_state"],
    }
    resumed = second._execute_agent_node("agent-1", {}, node_data(model))
    return {"stage": "resume", "error": resumed.get("error"), "text": resumed.get("text")}


class AgentReviewResumeProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        requests_seen.clear()
        for target, value in (
            ("socket.getaddrinfo", fake_getaddrinfo),
            ("httpx.HTTPTransport.handle_request", handle),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_messages_api_model_resumes(self) -> None:
        self.assertEqual(
            pause_then_resume("claude-haiku-4-5"),
            {"stage": "resume", "error": None, "text": "Approved email sent to ACME."},
        )

    def test_a_gemini_model_resumes_with_a_parts_shaped_message(self) -> None:
        result = pause_then_resume("gemini-3-flash")

        self.assertEqual(
            result, {"stage": "resume", "error": None, "text": "Approved email sent to ACME."}
        )
        resumed = requests_seen[-1]["body"]["contents"]
        self.assertTrue(all(set(content) <= {"role", "parts"} for content in resumed))
