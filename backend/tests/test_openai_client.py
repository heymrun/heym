"""Tests for the shared OpenAI SDK client factory."""

import json
import unittest
import uuid
from unittest.mock import patch

import httpx

from app.http_identity import HEYM_USER_AGENT
from app.services.llm_chat_bridge import completion_caller
from app.services.openai_client import create_guarded_openai_client, create_openai_client
from app.services.opencode_catalog import OPENCODE_MODEL_FALLBACK


class OpenAIClientIdentityTests(unittest.TestCase):
    def test_heym_user_agent_is_sent_on_the_wire(self) -> None:
        captured_headers: list[httpx.Headers] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            captured_headers.append(request.headers)
            return httpx.Response(
                200,
                request=request,
                json={"object": "list", "data": []},
            )

        http_client = httpx.Client(
            transport=httpx.MockTransport(handle_request),
            trust_env=False,
        )
        client = create_openai_client(
            api_key="sk-test",
            base_url="https://openai.example.test/v1",
            http_client=http_client,
        )

        try:
            client.models.list()
        finally:
            client.close()

        self.assertEqual(len(captured_headers), 1)
        self.assertEqual(captured_headers[0]["User-Agent"], HEYM_USER_AGENT)

    def test_additional_default_headers_are_preserved(self) -> None:
        client = create_openai_client(
            api_key="sk-test",
            default_headers={"X-Custom": "custom-value"},
        )

        try:
            self.assertEqual(client.default_headers["User-Agent"], HEYM_USER_AGENT)
            self.assertEqual(client.default_headers["X-Custom"], "custom-value")
        finally:
            client.close()


class OpenCodeSessionTests(unittest.TestCase):
    def test_session_survives_retries_and_streaming_on_the_wire(self) -> None:
        captured: list[httpx.Headers] = []

        def respond(request: httpx.Request) -> httpx.Response:
            captured.append(request.headers)
            if len(captured) == 1:
                return httpx.Response(500, json={}, headers={"retry-after-ms": "1"})
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='data: {"id":"test","object":"chat.completion.chunk",'
                '"created":0,"model":"test","choices":[{"index":0,'
                '"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
                "data: [DONE]\n\n",
            )

        with create_openai_client(
            api_key="test-key",
            base_url="https://opencode.ai/zen/go/v1",
            session_id="conversation-1",
            default_headers={"X-Custom": "kept"},
            http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        ) as client:
            for _ in range(2):
                chunks = list(
                    client.chat.completions.create(
                        model="test", messages=[{"role": "user", "content": "hi"}], stream=True
                    )
                )
                self.assertEqual(chunks[0].choices[0].delta.content, "hello")

        self.assertEqual(len(captured), 3)
        for headers in captured:
            self.assertEqual(headers["x-opencode-session"], "conversation-1")
            self.assertEqual(headers["User-Agent"], HEYM_USER_AGENT)
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            self.assertEqual(headers["X-Custom"], "kept")

    def test_m31_flash_uses_real_sdk_chat_http_boundary(self) -> None:
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                request=request,
                json={
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "minimax-m3.1-flash-free",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "ping"},
                    {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}},
                ],
            }
        ]
        models = [
            m["id"].split("/", 1)[1] for m in OPENCODE_MODEL_FALLBACK if "/minimax-" in m["id"]
        ]
        self.assertEqual(models, ["minimax-m3.1-flash-free", "minimax-m3"])
        # Chat/assistant use this application bridge to choose the protocol before
        # the real SDK serializes a request. Explicit custom models remain accepted.
        for model in [*models, "my-custom-model"]:
            with create_openai_client(
                api_key="test-key",
                base_url="https://opencode.ai/zen/go/v1",
                session_id="m31-flash-boundary",
                http_client=httpx.Client(transport=httpx.MockTransport(respond)),
            ) as client:
                completion = completion_caller(client, model)(model=model, messages=messages)
            self.assertEqual(completion.choices[0].message.content, "ok")
            request = requests[-1]
            self.assertEqual(request.url.path, "/zen/go/v1/chat/completions")
            self.assertEqual(request.headers["x-opencode-session"], "m31-flash-boundary")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], model)
            self.assertEqual(payload["messages"], messages)
            for field in ("thinking", "reasoning_effort", "service_tier", "reasoning_split"):
                self.assertNotIn(field, payload)
        self.assertEqual(len(requests), 3)

    def test_missing_or_blank_session_gets_a_distinct_nonempty_id(self) -> None:
        sessions = []
        for session_id in (None, "", "   "):
            with create_openai_client(
                api_key="test", base_url="https://opencode.ai/zen/go/v1", session_id=session_id
            ) as client:
                value = client.default_headers["x-opencode-session"]
                self.assertEqual(str(uuid.UUID(value)), value)
                sessions.append(value)
        self.assertEqual(len(set(sessions)), 3)

    def test_followups_reuse_explicit_id_across_clients(self) -> None:
        for _ in range(2):
            with create_openai_client(
                api_key="test", base_url="https://opencode.ai/zen/v1", session_id="conversation"
            ) as client:
                self.assertEqual(client.default_headers["x-opencode-session"], "conversation")

    def test_only_exact_opencode_host_receives_automatic_header(self) -> None:
        for base_url, expected in (
            ("https://opencode.ai/zen/go/v1", True),
            ("https://OPENCODE.AI.:443/zen/v1", True),
            ("https://opencode.ai/v1", True),
            ("https://api.openai.com/v1", False),
            ("https://opencode.ai.example.test/v1", False),
            ("https://opencode.ai@other.example.test/v1", False),
        ):
            with self.subTest(base_url=base_url):
                with create_openai_client(
                    api_key="test", base_url=base_url, session_id="conversation"
                ) as client:
                    self.assertEqual("x-opencode-session" in client.default_headers, expected)

    def test_omitted_base_url_does_not_add_opencode_header(self) -> None:
        with create_openai_client(api_key="test", session_id="conversation") as client:
            self.assertNotIn("x-opencode-session", client.default_headers)

    def test_existing_header_is_normalized_without_mutating_caller(self) -> None:
        headers = {"X-OpenCode-Session": "existing", "X-Custom": "kept"}
        for session_id, expected in ((None, "existing"), ("explicit", "explicit")):
            with create_openai_client(
                api_key="test",
                base_url="https://opencode.ai/zen/go/v1",
                session_id=session_id,
                default_headers=headers,
            ) as client:
                self.assertEqual(client.default_headers["x-opencode-session"], expected)
                self.assertNotIn("X-OpenCode-Session", client.default_headers)
        self.assertEqual(headers, {"X-OpenCode-Session": "existing", "X-Custom": "kept"})

    def test_guarded_client_preserves_session_and_url_guard(self) -> None:
        with (
            patch("app.services.openai_client.guard_http_url") as guard,
            patch("app.services.openai_client.build_guarded_http_client") as transport,
        ):
            transport.return_value = httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"data": [], "object": "list"})
                )
            )
            with create_guarded_openai_client(
                api_key="test",
                base_url="https://opencode.ai/zen/go/v1",
                subject="Test credential",
                session_id="conversation",
            ) as client:
                self.assertEqual(client.default_headers["x-opencode-session"], "conversation")
                client.models.list()
            guard.assert_called_once_with("https://opencode.ai/zen/go/v1", "Test credential")
            transport.assert_called_once()


if __name__ == "__main__":
    unittest.main()
