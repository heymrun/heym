"""Composite credential values must not leak their secret part into persisted output.

`$credentials.<name>` resolves to a whole `Name: secret` line for header credentials
and to `Bearer <token>` for bearer credentials. Masking only searched for that full
string, so an http node that sent the header echoed the bare secret back in
`request.headers` and it reached node results and history in plaintext.
"""

import json
import unittest
from unittest.mock import patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor, mask_sensitive_output

_HEADER_SECRET = "header-secret-value-123"
_BEARER_TOKEN = "tok-abcdef123456"
_API_KEY = "AIzaSyExampleKey123"
_CREDENTIALS = {
    "vendor": f"X-Api-Key: {_HEADER_SECRET}",
    "api": f"Bearer {_BEARER_TOKEN}",
    "google": _API_KEY,
}


def _http_output(curl: str) -> dict:
    """Run an http node against a mock transport and return its raw output."""

    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True}, request=request)

    context = NodeExecutionContext(
        executor=WorkflowExecutor(nodes=[], edges=[], credentials_context=_CREDENTIALS),
        node_id="http1",
        inputs={},
        allow_branch_skip=True,
        start_time=0.0,
        node={},
        node_type="http",
        node_data={"curl": curl},
        node_label="request",
    )
    with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
        with (
            patch("app.services.ssrf_guard.guard_http_url"),
            patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
        ):
            return http_node.execute(context)


class HeaderCredentialMaskingTests(unittest.TestCase):
    def test_header_credential_secret_is_masked_in_http_output(self) -> None:
        output = _http_output("curl -X GET https://api.example.com -H '$credentials.vendor'")
        self.assertIn(_HEADER_SECRET, json.dumps(output))

        masked = mask_sensitive_output(output, _CREDENTIALS)

        self.assertNotIn(_HEADER_SECRET, json.dumps(masked))

    def test_header_name_is_kept(self) -> None:
        output = _http_output("curl -X GET https://api.example.com -H '$credentials.vendor'")

        masked = mask_sensitive_output(output, _CREDENTIALS)

        self.assertIn("x-api-key", masked["request"]["headers"])

    def test_bare_bearer_token_is_masked(self) -> None:
        """An API can echo the token without the `Bearer ` prefix it was sent with."""
        output = {"body": {"received_token": _BEARER_TOKEN}}

        masked = mask_sensitive_output(output, _CREDENTIALS)

        self.assertNotIn(_BEARER_TOKEN, json.dumps(masked))

    def test_raw_api_key_is_still_masked(self) -> None:
        output = _http_output(
            "curl -X GET https://api.example.com -H 'x-goog-api-key: $credentials.google'"
        )

        masked = mask_sensitive_output(output, _CREDENTIALS)

        self.assertNotIn(_API_KEY, json.dumps(masked))

    def test_short_secret_part_does_not_mask_unrelated_text(self) -> None:
        output = {"message": "feature turned on"}

        masked = mask_sensitive_output(output, {"flag": "X-Mode: on"})

        self.assertEqual(masked, output)


if __name__ == "__main__":
    unittest.main()
