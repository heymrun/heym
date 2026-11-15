"""Regression tests for expressions that shape the parsed curl command.

Expressions may supply a whole header line (`-H "$credentials.Name"` with a
header-type credential resolving to `key: value`) or a whole URL. Those spans
have to be resolved before the curl tokens are interpreted, otherwise the
header is dropped and the URL is not recognised.
"""

import unittest
from unittest.mock import patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor


def _run_curl(
    curl: str,
    *,
    inputs: dict | None = None,
    credentials: dict[str, str] | None = None,
) -> httpx.Request:
    """Execute an http node against a mock transport and return the sent request."""
    received: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"ok": True}, request=request)

    context = NodeExecutionContext(
        executor=WorkflowExecutor(nodes=[], edges=[], credentials_context=credentials),
        node_id="http1",
        inputs=inputs or {},
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
            http_node.execute(context)

    assert len(received) == 1
    return received[0]


class HttpNodeCurlExpressionTests(unittest.TestCase):
    """Expressions that contribute curl syntax must survive parsing."""

    def test_header_credential_supplies_whole_header_line(self) -> None:
        """A header-type credential resolves to `key: value` and must be sent."""
        curl = (
            'curl -X GET "https://api.search.brave.com/res/v1/web/search'
            '?q=$searchQuery.body.text.urlEncode()" '
            '-H "Accept: application/json" -H "$credentials.brave"'
        )
        request = _run_curl(
            curl,
            inputs={"searchQuery": {"body": {"text": "ai agent audit log"}}},
            credentials={"brave": "x-subscription-token: BSA-secret"},
        )

        self.assertEqual(request.headers["x-subscription-token"], "BSA-secret")
        self.assertEqual(request.headers["accept"], "application/json")
        self.assertEqual(
            str(request.url),
            "https://api.search.brave.com/res/v1/web/search?q=ai%20agent%20audit%20log",
        )

    def test_header_value_expression_still_resolves(self) -> None:
        """The common `Key: $credentials.Name` form keeps working."""
        request = _run_curl(
            'curl -X GET https://api.example.com/data -H "Authorization: $credentials.token"',
            credentials={"token": "Bearer abc123"},
        )

        self.assertEqual(request.headers["authorization"], "Bearer abc123")

    def test_url_from_expression_is_recognised(self) -> None:
        """A URL supplied entirely by an expression is not lost during parsing."""
        request = _run_curl(
            "curl -X GET $api.base/data",
            inputs={"api": {"base": "https://api.example.com"}},
        )

        self.assertEqual(str(request.url), "https://api.example.com/data")

    def test_body_expression_is_resolved_once(self) -> None:
        """A resolved body value containing a `$` is not resolved a second time."""
        request = _run_curl(
            "curl -X POST https://api.example.com/data "
            "-H 'Content-Type: text/plain' -d '$payload.text'",
            inputs={"payload": {"text": "price is $total.amount"}},
        )

        self.assertEqual(request.content.decode("utf-8"), "price is $total.amount")

    def test_expression_arguments_keep_their_quotes(self) -> None:
        """Quotes inside an expression are its syntax, not shell quoting."""
        request = _run_curl(
            'curl "https://r.jina.ai/$url.text.replaceAll("\\n", "").strip()" '
            '-H "Authorization: $credentials.jina"',
            inputs={"url": {"text": " https://heym.run\n"}},
            credentials={"jina": "Bearer jina-secret"},
        )

        self.assertEqual(str(request.url), "https://r.jina.ai/https://heym.run")
        self.assertEqual(request.headers["authorization"], "Bearer jina-secret")

    def test_expression_argument_containing_a_space_is_one_token(self) -> None:
        """A space inside an expression argument must not split the curl token."""
        request = _run_curl(
            'curl "https://api.example.com/?q=$q.text.replaceAll(", ", "+")"',
            inputs={"q": {"text": "a, b, c"}},
        )

        self.assertEqual(str(request.url), "https://api.example.com/?q=a+b+c")

    def test_json_body_expression_with_quoted_arguments(self) -> None:
        """A quoted-argument expression in a JSON body still renders JSON-safely."""
        request = _run_curl(
            "curl -X POST https://api.example.com/data "
            '-H "Content-Type: application/json" '
            '-d \'{"text": $payload.text.replaceAll("\\n", " ")}\'',
            inputs={"payload": {"text": "line1\nline2"}},
        )

        self.assertEqual(request.content.decode("utf-8"), '{"text": "line1 line2"}')


if __name__ == "__main__":
    unittest.main()


class HttpNodeCurlUserTests(unittest.TestCase):
    """`curl -u user:password`, as Stripe, Twilio and Mailgun document their APIs."""

    @staticmethod
    def _basic(user_pass: str) -> str:
        import base64

        return "Basic " + base64.b64encode(user_pass.encode()).decode()

    def test_user_option_sends_basic_auth(self) -> None:
        for curl, user_pass in (
            ("curl https://api.example.com/v1/customers -u sk_test_123:", "sk_test_123:"),
            ("curl --user 'AC123:auth token' https://api.example.com/x", "AC123:auth token"),
            ("curl -u api https://api.example.com/x", "api:"),
        ):
            with self.subTest(curl=curl):
                request = _run_curl(curl)
                self.assertEqual(request.headers["authorization"], self._basic(user_pass))

    def test_user_option_resolves_expressions(self) -> None:
        request = _run_curl(
            "curl -u '$credentials.stripe:' https://api.example.com/v1/charges",
            credentials={"stripe": "sk_live_abcdef123456"},
        )
        self.assertEqual(request.headers["authorization"], self._basic("sk_live_abcdef123456:"))

    def test_an_explicit_authorization_header_wins(self) -> None:
        for curl in (
            "curl -u a:b -H 'Authorization: Bearer t1' https://api.example.com/x",
            "curl -H 'authorization: Bearer t1' -u a:b https://api.example.com/x",
        ):
            with self.subTest(curl=curl):
                self.assertEqual(_run_curl(curl).headers["authorization"], "Bearer t1")
