"""Advisory tests for URL secret redaction in logging (issue #1046).

Guards against capability secrets, API keys, bot tokens, and webhook tokens leaking into
backend stdout, Docker logs, and uvicorn access logs.
"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

import httpx

from app.services.llm_provider import fetch_google_models
from app.services.url_redaction import (
    URLRedactionFilter,
    install_url_redaction_filters,
    redact_url,
)
from app.services.workflow_executor import close_http_client, get_http_client


class _LogCaptureHandler(logging.Handler):
    """In-memory log handler to inspect emitted records."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.messages.append(record.getMessage())


class RedactUrlTests(unittest.TestCase):
    """Verify redact_url across all expected secret shapes and ensure safe URLs are unchanged."""

    def test_query_params_sensitive_keys_redacted(self) -> None:
        cases = [
            (
                "https://generativelanguage.googleapis.com/v1beta/models?key=AIzaFAKE-GEMINI-KEY",
                "https://generativelanguage.googleapis.com/v1beta/models?key=[REDACTED]",
            ),
            (
                "/api/mcp/message?session=secret-session-token-123",
                "/api/mcp/message?session=[REDACTED]",
            ),
            (
                "?session=secret-token",
                "?session=[REDACTED]",
            ),
            (
                "https://example.com/callback?sig=sig123&signature=signature456",
                "https://example.com/callback?sig=[REDACTED]&signature=[REDACTED]",
            ),
            (
                "https://example.com/api?api_key=secret-api-key",
                "https://example.com/api?api_key=[REDACTED]",
            ),
            (
                "https://example.com/api?apiKey=secret-api-key",
                "https://example.com/api?apiKey=[REDACTED]",
            ),
            (
                "https://example.com/api?token=secret-token",
                "https://example.com/api?token=[REDACTED]",
            ),
            (
                "https://example.com/api?access_token=secret-access-token",
                "https://example.com/api?access_token=[REDACTED]",
            ),
            (
                "https://example.com/api?client_secret=secret-client-secret",
                "https://example.com/api?client_secret=[REDACTED]",
            ),
            (
                "https://example.com/api?password=secret-pass",
                "https://example.com/api?password=[REDACTED]",
            ),
            (
                "https://mcp.example.com/sse?auth=secret-auth-token",
                "https://mcp.example.com/sse?auth=[REDACTED]",
            ),
            (
                "https://example.com/api?auth=secret",
                "https://example.com/api?auth=[REDACTED]",
            ),
            (
                "https://mybucket.s3.amazonaws.com/file.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=d41d8cd98f00b204e9800998ecf8427e",
                "https://mybucket.s3.amazonaws.com/file.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=[REDACTED]",
            ),
            (
                "https://storage.googleapis.com/mybucket/file.png?GoogleAccessId=service@app.com&X-Goog-Signature=abcdef123456",
                "https://storage.googleapis.com/mybucket/file.png?GoogleAccessId=service@app.com&X-Goog-Signature=[REDACTED]",
            ),
            (
                "https://example.com/webhook?timestamp=123&client_signature=secret_sig_value",
                "https://example.com/webhook?timestamp=123&client_signature=[REDACTED]",
            ),
            (
                "https://example.com/webhook?req_sig=secret_sig_value",
                "https://example.com/webhook?req_sig=[REDACTED]",
            ),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(redact_url(url), expected)

    def test_harmless_query_params_preserved(self) -> None:
        url = "https://example.com/v1/models?pageSize=20&pageToken=next_page_abc123&limit=50&offset=0&wait=true&author=john"
        self.assertEqual(redact_url(url), url)

    def test_mixed_query_params_redacts_only_sensitive(self) -> None:
        url = "https://example.com/items?pageSize=10&key=my-secret-key&pageToken=abc"
        expected = "https://example.com/items?pageSize=10&key=[REDACTED]&pageToken=abc"
        self.assertEqual(redact_url(url), expected)

    def test_user_info_redacted(self) -> None:
        cases = [
            (
                "https://user:pass@example.com/path",
                "https://[REDACTED]@example.com/path",
            ),
            (
                "https://token@example.com/path",
                "https://[REDACTED]@example.com/path",
            ),
            (
                "https://user:pass@example.com:8080/path?key=secret",
                "https://[REDACTED]@example.com:8080/path?key=[REDACTED]",
            ),
            (
                "http://user:pass@localhost:5432/db",
                "http://[REDACTED]@localhost:5432/db",
            ),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(redact_url(url), expected)

    def test_telegram_bot_token_redacted(self) -> None:
        cases = [
            (
                "https://api.telegram.org/bot123456:FAKE-BOT-TOKEN/sendMessage",
                "https://api.telegram.org/bot[REDACTED]/sendMessage",
            ),
            (
                "https://api.telegram.org/bot123456:FAKE-BOT-TOKEN",
                "https://api.telegram.org/bot[REDACTED]",
            ),
            (
                "/bot123456:FAKE-BOT-TOKEN/sendMessage",
                "/bot[REDACTED]/sendMessage",
            ),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(redact_url(url), expected)

    def test_telegram_non_bot_path_not_redacted(self) -> None:
        url = "https://example.com/bottom/path"
        self.assertEqual(redact_url(url), url)

    def test_slack_webhook_redacted(self) -> None:
        cases = [
            (
                "https://hooks.slack.com/services/T000/B000/dummy-slack-token",
                "https://hooks.slack.com/services/[REDACTED]",
            ),
            (
                "https://hooks.slack.com/services/T000/B000/xxx",
                "https://hooks.slack.com/services/[REDACTED]",
            ),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(redact_url(url), expected)

    def test_slack_non_webhook_url_preserved(self) -> None:
        url = "https://slack.com/api/chat.postMessage"
        self.assertEqual(redact_url(url), url)

    def test_discord_webhook_redacted(self) -> None:
        cases = [
            (
                "https://discord.com/api/webhooks/1234567890/token",
                "https://discord.com/api/webhooks/1234567890/[REDACTED]",
            ),
            (
                "https://discord.com/api/v10/webhooks/1234567890/interaction-token",
                "https://discord.com/api/v10/webhooks/1234567890/[REDACTED]",
            ),
            (
                "https://discord.com/api/v10/webhooks/1234567890/interaction-token/messages/@original",
                "https://discord.com/api/v10/webhooks/1234567890/[REDACTED]/messages/@original",
            ),
            (
                "https://discord.com/api/webhooks/1234567890/token?wait=true",
                "https://discord.com/api/webhooks/1234567890/[REDACTED]?wait=true",
            ),
            (
                "/api/webhooks/123/token",
                "/api/webhooks/123/[REDACTED]",
            ),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(redact_url(url), expected)

    def test_heym_capability_routes_redacted(self) -> None:
        cases = [
            (
                "/api/files/dl/file_access_token_123",
                "/api/files/dl/[REDACTED]",
            ),
            (
                "https://heym.example.com/api/files/dl/file_access_token_123",
                "https://heym.example.com/api/files/dl/[REDACTED]",
            ),
            (
                "/api/hitl/hitl_token_123",
                "/api/hitl/[REDACTED]",
            ),
            (
                "/api/hitl/hitl_token_123/decision",
                "/api/hitl/[REDACTED]/decision",
            ),
            (
                "/api/codex/followups/codex_token_123",
                "/api/codex/followups/[REDACTED]",
            ),
            (
                "/api/codex/followups/codex_token_123/answer",
                "/api/codex/followups/[REDACTED]/answer",
            ),
            (
                "/api/file-intake/u/intake_token_123",
                "/api/file-intake/u/[REDACTED]",
            ),
            (
                "/review/hitl_token_123",
                "/review/[REDACTED]",
            ),
            (
                "https://heym.example.com/review/hitl_token_123",
                "https://heym.example.com/review/[REDACTED]",
            ),
            (
                "/review/hitl_token_123/decision",
                "/review/[REDACTED]/decision",
            ),
            (
                "/api/review/hitl_token_123",
                "/api/review/[REDACTED]",
            ),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(redact_url(url), expected)

    def test_heym_non_token_routes_preserved(self) -> None:
        cases = [
            "/api/hitl/inbox",
            "/api/hitl/sources",
            "/api/health",
            "/api/workflows",
            "/api/auth/me",
            "/review",
            "/reviews",
            "/api/reviews",
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertEqual(redact_url(url), url)

    def test_redaction_is_idempotent(self) -> None:
        urls = [
            "https://api.telegram.org/bot123:abc/sendMessage",
            "https://hooks.slack.com/services/T00/B00/xxx",
            "https://discord.com/api/webhooks/123/tok",
            "/api/files/dl/secret",
            "/api/hitl/secret/decision",
            "/review/secret",
            "/api/mcp/message?session=tok",
            "https://mcp.example.com/sse?auth=tok",
            "https://s3.amazonaws.com/b/k?X-Amz-Signature=sig",
        ]
        for url in urls:
            with self.subTest(url=url):
                redacted = redact_url(url)
                self.assertEqual(redact_url(redacted), redacted)


class UvicornAccessFilterTests(unittest.TestCase):
    """Test the URLRedactionFilter against uvicorn.access shaped records."""

    def setUp(self) -> None:
        self.filter = URLRedactionFilter()

    def test_redacts_files_dl_token(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="uvicorn/protocols/http",
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/api/files/dl/sensitive-access-token-999", "1.1", 200),
            exc_info=None,
        )

        self.filter.filter(record)

        self.assertEqual(
            record.args,
            ("127.0.0.1", "GET", "/api/files/dl/[REDACTED]", "1.1", 200),
        )
        self.assertNotIn("sensitive-access-token-999", record.args[2])

    def test_redacts_mcp_session_query_token(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="uvicorn/protocols/http",
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/api/mcp/message?session=secret-session-abc", "1.1", 200),
            exc_info=None,
        )

        self.filter.filter(record)

        self.assertEqual(
            record.args,
            ("127.0.0.1", "GET", "/api/mcp/message?session=[REDACTED]", "1.1", 200),
        )
        self.assertNotIn("secret-session-abc", record.args[2])

    def test_preserves_harmless_access_line(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="uvicorn/protocols/http",
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/api/health?check=ready", "1.1", 200),
            exc_info=None,
        )

        self.filter.filter(record)

        self.assertEqual(
            record.args,
            ("127.0.0.1", "GET", "/api/health?check=ready", "1.1", 200),
        )

    def test_redacts_review_token(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="uvicorn/protocols/http",
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("127.0.0.1", "GET", "/review/hitl-review-token-456", "1.1", 307),
            exc_info=None,
        )

        self.filter.filter(record)

        self.assertEqual(
            record.args,
            ("127.0.0.1", "GET", "/review/[REDACTED]", "1.1", 307),
        )
        self.assertNotIn("hitl-review-token-456", record.args[2])

    def test_redacts_auth_and_presigned_signature(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="uvicorn/protocols/http",
            lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=(
                "127.0.0.1",
                "GET",
                "/api/mcp/sse?auth=secret-sse-auth&X-Amz-Signature=secret-sig-789",
                "1.1",
                200,
            ),
            exc_info=None,
        )

        self.filter.filter(record)

        self.assertEqual(
            record.args,
            (
                "127.0.0.1",
                "GET",
                "/api/mcp/sse?auth=[REDACTED]&X-Amz-Signature=[REDACTED]",
                "1.1",
                200,
            ),
        )
        self.assertNotIn("secret-sse-auth", record.args[2])
        self.assertNotIn("secret-sig-789", record.args[2])


class HttpClientAndLlmProviderLoggingTests(unittest.IsolatedAsyncioTestCase):
    """Verify that get_http_client() and fetch_google_models leave no secret in captured logs."""

    def setUp(self) -> None:
        install_url_redaction_filters()
        self.httpx_logger = logging.getLogger("httpx")
        self.original_level = self.httpx_logger.level
        self.httpx_logger.setLevel(logging.INFO)
        self.capture = _LogCaptureHandler()
        self.httpx_logger.addHandler(self.capture)

    def tearDown(self) -> None:
        self.httpx_logger.removeHandler(self.capture)
        self.httpx_logger.setLevel(self.original_level)
        close_http_client()

    def test_get_http_client_redacts_telegram_secret_in_logs(self) -> None:
        secret_token = "123456:REAL-LOOKING-TELEGRAM-BOT-TOKEN"
        url = f"https://api.telegram.org/bot{secret_token}/sendMessage"

        mock_transport = httpx.MockTransport(lambda req: httpx.Response(200, text="ok"))
        client = httpx.Client(
            transport=mock_transport,
            headers={"User-Agent": "heym"},
        )
        with patch("app.services.workflow_executor._HTTP_CLIENT", client):
            http_client = get_http_client()
            response = http_client.get(url)
            self.assertEqual(response.status_code, 200)

        all_logs = " ".join(self.capture.messages)
        self.assertIn("bot[REDACTED]/sendMessage", all_logs)
        self.assertNotIn(secret_token, all_logs)

    async def test_fetch_google_models_leaves_no_secret_in_logs(self) -> None:
        secret_key = "AIzaSyD-FAKE-GOOGLE-KEY-123456789"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers.get("x-goog-api-key"), secret_key)
            self.assertNotIn("key=", str(request.url))
            return httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash"}]})

        mock_transport = httpx.MockTransport(mock_handler)
        client = httpx.AsyncClient(
            transport=mock_transport,
            headers={"User-Agent": "heym", "x-goog-api-key": secret_key},
        )
        with patch("app.services.llm_provider.httpx.AsyncClient", return_value=client):
            models = await fetch_google_models(secret_key)
            self.assertEqual([m.id for m in models], ["gemini-2.5-flash"])

        all_logs = " ".join(self.capture.messages)
        self.assertNotIn(secret_key, all_logs)
        self.assertNotIn("key=", all_logs)


class WinstonLoggingMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    """Verify WinstonLoggingMiddleware redacts secrets in request and response paths."""

    async def test_middleware_redacts_capability_routes(self) -> None:
        from starlette.requests import Request
        from starlette.responses import Response

        from app.main import WinstonLoggingMiddleware

        middleware = WinstonLoggingMiddleware(app=None)  # type: ignore[arg-type]
        winston_logger = logging.getLogger("winston")
        original_level = winston_logger.level
        winston_logger.setLevel(logging.INFO)
        capture = _LogCaptureHandler()
        winston_logger.addHandler(capture)
        try:
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/api/files/dl/secret-token-xyz",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            }
            request = Request(scope)

            async def call_next(req: Request) -> Response:
                return Response("ok", status_code=200)

            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 200)

            all_logs = " ".join(capture.messages)
            self.assertIn("/api/files/dl/[REDACTED]", all_logs)
            self.assertNotIn("secret-token-xyz", all_logs)
        finally:
            winston_logger.removeHandler(capture)
            winston_logger.setLevel(original_level)

    async def test_middleware_redacts_review_route(self) -> None:
        from starlette.requests import Request
        from starlette.responses import Response

        from app.main import WinstonLoggingMiddleware

        middleware = WinstonLoggingMiddleware(app=None)  # type: ignore[arg-type]
        winston_logger = logging.getLogger("winston")
        original_level = winston_logger.level
        winston_logger.setLevel(logging.INFO)
        capture = _LogCaptureHandler()
        winston_logger.addHandler(capture)
        try:
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/review/hitl-review-token-789",
                "headers": [],
                "client": ("127.0.0.1", 12345),
            }
            request = Request(scope)

            async def call_next(req: Request) -> Response:
                return Response("ok", status_code=307)

            response = await middleware.dispatch(request, call_next)
            self.assertEqual(response.status_code, 307)

            all_logs = " ".join(capture.messages)
            self.assertIn("/review/[REDACTED]", all_logs)
            self.assertNotIn("hitl-review-token-789", all_logs)
        finally:
            winston_logger.removeHandler(capture)
            winston_logger.setLevel(original_level)


if __name__ == "__main__":
    unittest.main()
