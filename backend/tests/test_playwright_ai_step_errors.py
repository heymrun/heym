"""Playwright AI step should surface provider/API error bodies, not bare 502 text."""

import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from app.api.playwright import llm_exception_message
from app.services.playwright_code_generator import (
    _heym_urlopen_json,
    generate_playwright_code,
    http_error_message,
)


class HttpErrorMessageTests(unittest.TestCase):
    def test_prefers_fastapi_detail_over_reason_phrase(self) -> None:
        body = json.dumps({"detail": "LLM call failed: context length exceeded"})
        message = http_error_message(502, "Bad Gateway", body)
        self.assertIn("context length exceeded", message)
        self.assertNotIn("Bad Gateway", message)

    def test_prefers_nested_provider_error_message(self) -> None:
        body = json.dumps({"error": {"message": "model does not exist", "type": "invalid_request"}})
        message = http_error_message(502, "Bad Gateway", body)
        self.assertEqual(message, "HTTP 502: model does not exist")

    def test_empty_body_falls_back_to_reason(self) -> None:
        self.assertEqual(http_error_message(502, "Bad Gateway", ""), "HTTP 502: Bad Gateway")

    def test_plain_text_body_is_returned(self) -> None:
        self.assertEqual(
            http_error_message(502, "Bad Gateway", "upstream timeout"),
            "HTTP 502: upstream timeout",
        )


class UrlopenJsonWrapperTests(unittest.TestCase):
    def test_raises_runtime_error_with_response_body(self) -> None:
        fp = BytesIO(b'{"detail": "LLM call failed: quota exceeded"}')
        err = HTTPError("http://example/ai-step", 502, "Bad Gateway", hdrs=None, fp=fp)
        with patch("app.services.playwright_code_generator.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                _heym_urlopen_json(object(), 30)
        self.assertIn("quota exceeded", str(ctx.exception))
        self.assertNotIn("Bad Gateway", str(ctx.exception))


class GeneratedAiStepCodeTests(unittest.TestCase):
    def test_ai_step_code_calls_urlopen_wrapper(self) -> None:
        code = generate_playwright_code(
            [{"action": "aiStep", "instructions": "click login", "model": "gpt-test"}]
        )
        compile(code, "<generated>", "exec")
        self.assertIn("_heym_urlopen_json", code)
        self.assertNotIn("with urlopen(_req", code)
        self.assertNotIn("with urlopen(_heal_req", code)


class LlmExceptionMessageTests(unittest.TestCase):
    def test_extracts_openai_style_error_message(self) -> None:
        exc = Exception("Bad Gateway")
        exc.body = {"error": {"message": "This model does not support images"}}  # type: ignore[attr-defined]
        self.assertEqual(llm_exception_message(exc), "This model does not support images")

    def test_falls_back_to_response_text(self) -> None:
        exc = Exception("Bad Gateway")

        class _Response:
            text = "provider overloaded"

        exc.body = None  # type: ignore[attr-defined]
        exc.response = _Response()  # type: ignore[attr-defined]
        self.assertEqual(llm_exception_message(exc), "provider overloaded")

    def test_falls_back_to_str_when_no_body(self) -> None:
        self.assertEqual(llm_exception_message(Exception("connection reset")), "connection reset")
