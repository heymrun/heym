"""Tests for OpenCode Go disable_reasoning compatibility fallback in LLMService.execute().

Covers HTTP 400 and HTTP 422 field-specific rejection retries, trace accuracy,
argument preservation, non-retry on unrelated errors, and bounded retry behavior.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.llm_service import LLMService
from app.services.llm_trace import LLMTraceContext
from app.services.llm_transport import (
    is_disable_reasoning_error,
    rejects_disable_reasoning,
)


class DisableReasoningHelperTests(unittest.TestCase):
    """Unit tests for rejection detection helpers."""

    def test_status_code_400_with_field_name(self) -> None:
        exc = Exception("Error code: 400 - Unsupported parameter: disable_reasoning")
        exc.status_code = 400
        self.assertTrue(is_disable_reasoning_error(exc))
        self.assertTrue(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_status_code_422_with_field_name(self) -> None:
        exc = Exception("Error code: 422 - Extra inputs are not permitted: disable_reasoning")
        exc.status_code = 422
        self.assertTrue(is_disable_reasoning_error(exc))
        self.assertTrue(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_status_code_400_with_disabling_reasoning_phrase(self) -> None:
        exc = Exception("Error code: 400 - Model does not support disabling reasoning")
        exc.status_code = 400
        self.assertTrue(is_disable_reasoning_error(exc))
        self.assertTrue(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_status_code_400_with_disable_reasoning_space(self) -> None:
        exc = Exception("Error code: 400 - Cannot disable reasoning for this model")
        exc.status_code = 400
        self.assertTrue(is_disable_reasoning_error(exc))
        self.assertTrue(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_status_code_400_unrelated_message(self) -> None:
        exc = Exception("Error code: 400 - Invalid model name: claude-3")
        exc.status_code = 400
        self.assertFalse(is_disable_reasoning_error(exc))
        self.assertFalse(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_status_code_422_unrelated_message(self) -> None:
        exc = Exception("Error code: 422 - Invalid response format schema")
        exc.status_code = 422
        self.assertFalse(is_disable_reasoning_error(exc))
        self.assertFalse(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_status_code_500_with_disable_reasoning_in_text(self) -> None:
        exc = Exception("Error code: 500 - Internal server error while checking disable_reasoning")
        exc.status_code = 500
        self.assertFalse(is_disable_reasoning_error(exc))
        self.assertFalse(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_string_error_without_status_code_attribute(self) -> None:
        exc = Exception("400 Bad Request: disable_reasoning is not supported")
        self.assertTrue(is_disable_reasoning_error(exc))
        self.assertTrue(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_string_error_404_not_accepted(self) -> None:
        exc = Exception("404 Not Found: endpoint does not support disable_reasoning")
        self.assertFalse(is_disable_reasoning_error(exc))
        self.assertFalse(rejects_disable_reasoning(exc, {"disable_reasoning": True}))

    def test_missing_extra_body_returns_false(self) -> None:
        exc = Exception("Error code: 400 - Unsupported parameter: disable_reasoning")
        exc.status_code = 400
        self.assertFalse(rejects_disable_reasoning(exc, None))

    def test_extra_body_without_disable_reasoning_returns_false(self) -> None:
        exc = Exception("Error code: 400 - Unsupported parameter: disable_reasoning")
        exc.status_code = 400
        self.assertFalse(rejects_disable_reasoning(exc, {"max_tokens": 100}))


class LLMServiceDisableReasoningFallbackTests(unittest.IsolatedAsyncioTestCase):
    """Tests for LLMService.execute() disable_reasoning compatibility retry."""

    @staticmethod
    def _success_response(content: str = "ok") -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def _setup_service(
        self,
        trace_context: LLMTraceContext | None = None,
    ) -> tuple[LLMService, list[dict]]:
        captured: list[dict] = []
        service = LLMService(
            CredentialType.openai,
            "test-key",
            trace_context=trace_context,
        )
        return service, captured

    async def test_http_400_disable_reasoning_retries_without_extra_body_and_succeeds(self) -> None:
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            source="test",
            node_label="test_node",
        )
        service, captured = self._setup_service(trace_context=trace_context)

        exc_400 = Exception("Error code: 400 - Unsupported parameter: disable_reasoning")
        exc_400.status_code = 400

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            if len(captured) == 1:
                raise exc_400
            return self._success_response("recovered text")

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        with (
            patch.object(service, "_get_client", return_value=(client, "TestProvider")),
            patch("app.services.llm_service.record_llm_trace") as mock_record_trace,
        ):
            result = await service.execute(
                model="claude-3-5-sonnet",
                system_instruction="Be concise",
                user_message="Hello",
                temperature=0.3,
                response_format={"type": "json_object"},
                extra_body={"disable_reasoning": True},
            )

        self.assertEqual(result["text"], "recovered text")
        self.assertEqual(len(captured), 2)

        # First attempt sent extra_body with disable_reasoning
        self.assertEqual(captured[0]["extra_body"], {"disable_reasoning": True})
        self.assertEqual(captured[0]["temperature"], 0.3)
        self.assertEqual(captured[0]["response_format"], {"type": "json_object"})
        self.assertEqual(captured[0]["model"], "claude-3-5-sonnet")

        # Second attempt has NO extra_body
        self.assertNotIn("extra_body", captured[1])

        # All other request options remain intact on second attempt
        self.assertEqual(captured[1]["temperature"], 0.3)
        self.assertEqual(captured[1]["response_format"], {"type": "json_object"})
        self.assertEqual(captured[1]["model"], "claude-3-5-sonnet")
        self.assertEqual(captured[1]["messages"], captured[0]["messages"])

        # Exactly one successful terminal trace recorded
        self.assertEqual(mock_record_trace.call_count, 1)
        trace_kwargs = mock_record_trace.call_args.kwargs
        self.assertIsNone(trace_kwargs["error"])
        self.assertEqual(trace_kwargs["model"], "claude-3-5-sonnet")
        # Terminal trace request accurately reflects retried request without extra_body
        self.assertNotIn("extra_body", trace_kwargs["request"])

    async def test_http_422_disable_reasoning_retries_without_extra_body(self) -> None:
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            source="test",
        )
        service, captured = self._setup_service(trace_context=trace_context)

        exc_422 = Exception("Error code: 422 - Extra inputs are not permitted: disable_reasoning")
        exc_422.status_code = 422

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            if len(captured) == 1:
                raise exc_422
            return self._success_response("422 recovered")

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        with (
            patch.object(service, "_get_client", return_value=(client, "TestProvider")),
            patch("app.services.llm_service.record_llm_trace") as mock_record_trace,
        ):
            result = await service.execute(
                model="test-model",
                system_instruction=None,
                user_message="Hi",
                extra_body={"disable_reasoning": True},
            )

        self.assertEqual(result["text"], "422 recovered")
        self.assertEqual(len(captured), 2)
        self.assertNotIn("extra_body", captured[1])
        self.assertEqual(mock_record_trace.call_count, 1)
        self.assertNotIn("extra_body", mock_record_trace.call_args.kwargs["request"])

    async def test_http_400_unrelated_does_not_retry(self) -> None:
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            source="test",
        )
        service, captured = self._setup_service(trace_context=trace_context)

        exc_unrelated = Exception("Error code: 400 - Invalid model: non-existent")
        exc_unrelated.status_code = 400

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            raise exc_unrelated

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        with (
            patch.object(service, "_get_client", return_value=(client, "TestProvider")),
            patch("app.services.llm_service.record_llm_trace") as mock_record_trace,
        ):
            with self.assertRaises(Exception) as raised_ctx:
                await service.execute(
                    model="test-model",
                    system_instruction=None,
                    user_message="Hi",
                    extra_body={"disable_reasoning": True},
                )

        self.assertIs(raised_ctx.exception, exc_unrelated)
        self.assertEqual(len(captured), 1)
        self.assertEqual(mock_record_trace.call_count, 1)
        self.assertIn("Invalid model", mock_record_trace.call_args.kwargs["error"])
        # Unsuccessful unretried trace retains the original request
        self.assertEqual(
            mock_record_trace.call_args.kwargs["request"]["extra_body"],
            {"disable_reasoning": True},
        )

    async def test_http_422_unrelated_does_not_retry(self) -> None:
        service, captured = self._setup_service()

        exc_unrelated = Exception("Error code: 422 - Unprocessable content: invalid json schema")
        exc_unrelated.status_code = 422

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            raise exc_unrelated

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        with patch.object(service, "_get_client", return_value=(client, "TestProvider")):
            with self.assertRaises(Exception) as raised_ctx:
                await service.execute(
                    model="test-model",
                    system_instruction=None,
                    user_message="Hi",
                    extra_body={"disable_reasoning": True},
                )

        self.assertIs(raised_ctx.exception, exc_unrelated)
        self.assertEqual(len(captured), 1)

    async def test_missing_or_non_disable_reasoning_extra_body_does_not_retry(self) -> None:
        exc_400 = Exception("Error code: 400 - disable_reasoning unsupported")
        exc_400.status_code = 400

        # Scenario A: extra_body is None
        service_a, captured_a = self._setup_service()
        client_a = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=MagicMock(side_effect=exc_400),
                )
            ),
        )
        with patch.object(service_a, "_get_client", return_value=(client_a, "TestProvider")):
            with self.assertRaises(Exception):
                await service_a.execute(
                    model="test-model",
                    system_instruction=None,
                    user_message="Hi",
                    extra_body=None,
                )
        self.assertEqual(client_a.chat.completions.create.call_count, 1)

        # Scenario B: extra_body without disable_reasoning
        service_b, captured_b = self._setup_service()
        client_b = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=MagicMock(side_effect=exc_400),
                )
            ),
        )
        with patch.object(service_b, "_get_client", return_value=(client_b, "TestProvider")):
            with self.assertRaises(Exception):
                await service_b.execute(
                    model="test-model",
                    system_instruction=None,
                    user_message="Hi",
                    extra_body={"other_field": 123},
                )
        self.assertEqual(client_b.chat.completions.create.call_count, 1)

    async def test_retry_itself_fails_does_not_loop_and_records_trace(self) -> None:
        trace_context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            source="test",
        )
        service, captured = self._setup_service(trace_context=trace_context)

        exc_400 = Exception("Error code: 400 - Unsupported parameter: disable_reasoning")
        exc_400.status_code = 400
        exc_retry = Exception("Error code: 500 - Internal server error on retry")
        exc_retry.status_code = 500

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            if len(captured) == 1:
                raise exc_400
            raise exc_retry

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        with (
            patch.object(service, "_get_client", return_value=(client, "TestProvider")),
            patch("app.services.llm_service.record_llm_trace") as mock_record_trace,
        ):
            with self.assertRaises(Exception) as raised_ctx:
                await service.execute(
                    model="test-model",
                    system_instruction=None,
                    user_message="Hi",
                    extra_body={"disable_reasoning": True},
                )

        # Exception from retry is propagated
        self.assertIs(raised_ctx.exception, exc_retry)
        # Exactly 2 attempts (no third attempt)
        self.assertEqual(len(captured), 2)
        # Trace was recorded exactly once with the final retry failure
        self.assertEqual(mock_record_trace.call_count, 1)
        trace_kwargs = mock_record_trace.call_args.kwargs
        self.assertIn("Internal server error on retry", trace_kwargs["error"])
        # The trace request reflects the retried request (without extra_body)
        self.assertNotIn("extra_body", trace_kwargs["request"])

    async def test_only_extra_body_removed_all_other_request_options_preserved(self) -> None:
        service, captured = self._setup_service()

        exc_400 = Exception("Error code: 400 - disable_reasoning unsupported")
        exc_400.status_code = 400

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            if len(captured) == 1:
                raise exc_400
            return self._success_response("done")

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )

        with patch.object(service, "_get_client", return_value=(client, "TestProvider")):
            await service.execute(
                model="custom-model-v1",
                system_instruction="You are an analyst",
                user_message="Analyze data",
                temperature=0.7,
                max_tokens=2048,
                response_format={"type": "json_object"},
                extra_body={"disable_reasoning": True},
            )

        self.assertEqual(len(captured), 2)
        first, second = captured[0], captured[1]

        # extra_body was removed
        self.assertEqual(first["extra_body"], {"disable_reasoning": True})
        self.assertNotIn("extra_body", second)

        # Every other parameter matches exactly
        self.assertEqual(second["model"], first["model"])
        self.assertEqual(second["messages"], first["messages"])
        self.assertEqual(second["temperature"], first["temperature"])
        self.assertEqual(second["max_tokens"], first["max_tokens"])
        self.assertEqual(second["response_format"], first["response_format"])


if __name__ == "__main__":
    unittest.main()
