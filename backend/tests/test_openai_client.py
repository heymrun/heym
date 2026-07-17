"""Tests for the shared OpenAI SDK client factory."""

import unittest

import httpx

from app.http_identity import HEYM_USER_AGENT
from app.services.openai_client import create_openai_client


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


if __name__ == "__main__":
    unittest.main()
