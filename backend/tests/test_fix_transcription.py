"""Tests for fix_transcription endpoint disable_reasoning compatibility fallback."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.ai_assistant import (
    FixTranscriptionRequest,
    fix_transcription,
)
from app.db.models import CredentialType


class FixTranscriptionFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.credential_id = uuid.uuid4()
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.credential = SimpleNamespace(
            id=self.credential_id,
            type=CredentialType.openai,
            encrypted_config="enc",
        )
        self.request = FixTranscriptionRequest(
            credential_id=self.credential_id,
            model="claude-3-5-sonnet",
            text="um hello world",
        )

    @staticmethod
    def _model_response(content: str | None) -> SimpleNamespace:
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    async def test_http_400_disable_reasoning_retries_without_extra_body(self) -> None:
        captured_calls: list[dict] = []
        exc_400 = Exception("Error code: 400 - Unsupported parameter: disable_reasoning")
        exc_400.status_code = 400

        def fake_caller(**kwargs: object) -> SimpleNamespace:
            captured_calls.append(dict(kwargs))
            if len(captured_calls) == 1:
                raise exc_400
            return self._model_response("Hello, world.")

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self.credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test-key"}),
            patch(
                "app.api.ai_assistant.resolve_model_binding",
                return_value=(object(), "openai", "claude-3-5-sonnet", None),
            ),
            patch("app.api.ai_assistant.completion_caller", return_value=fake_caller),
        ):
            response = await fix_transcription(
                request=self.request,
                current_user=self.user,
                db=AsyncMock(),
            )

        self.assertEqual(response.fixed_text, "Hello, world.")
        self.assertEqual(len(captured_calls), 2)
        # First call has extra_body
        self.assertEqual(captured_calls[0]["extra_body"], {"disable_reasoning": True})
        # Second call does not have extra_body
        self.assertNotIn("extra_body", captured_calls[1])
        # Model and messages preserved
        self.assertEqual(captured_calls[1]["model"], captured_calls[0]["model"])
        self.assertEqual(captured_calls[1]["messages"], captured_calls[0]["messages"])

    async def test_http_422_disable_reasoning_retries_once(self) -> None:
        captured_calls: list[dict] = []
        exc_422 = Exception("Error code: 422 - Extra inputs are not permitted: disable_reasoning")
        exc_422.status_code = 422

        def fake_caller(**kwargs: object) -> SimpleNamespace:
            captured_calls.append(dict(kwargs))
            if len(captured_calls) == 1:
                raise exc_422
            return self._model_response("Fixed text from 422 retry.")

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self.credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test-key"}),
            patch(
                "app.api.ai_assistant.resolve_model_binding",
                return_value=(object(), "openai", "claude-3-5-sonnet", None),
            ),
            patch("app.api.ai_assistant.completion_caller", return_value=fake_caller),
        ):
            response = await fix_transcription(
                request=self.request,
                current_user=self.user,
                db=AsyncMock(),
            )

        self.assertEqual(response.fixed_text, "Fixed text from 422 retry.")
        self.assertEqual(len(captured_calls), 2)
        self.assertNotIn("extra_body", captured_calls[1])

    async def test_unrelated_http_400_propagates_without_retry(self) -> None:
        captured_calls: list[dict] = []
        exc_unrelated = Exception("Error code: 400 - Invalid request prompt")
        exc_unrelated.status_code = 400

        def fake_caller(**kwargs: object) -> SimpleNamespace:
            captured_calls.append(dict(kwargs))
            raise exc_unrelated

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self.credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test-key"}),
            patch(
                "app.api.ai_assistant.resolve_model_binding",
                return_value=(object(), "openai", "claude-3-5-sonnet", None),
            ),
            patch("app.api.ai_assistant.completion_caller", return_value=fake_caller),
        ):
            with self.assertRaises(Exception) as raised_ctx:
                await fix_transcription(
                    request=self.request,
                    current_user=self.user,
                    db=AsyncMock(),
                )

        self.assertIs(raised_ctx.exception, exc_unrelated)
        self.assertEqual(len(captured_calls), 1)

    async def test_retry_failure_propagates_without_repeated_retries(self) -> None:
        captured_calls: list[dict] = []
        exc_400 = Exception("Error code: 400 - disable_reasoning unsupported")
        exc_400.status_code = 400
        exc_retry = Exception("Error code: 503 - Service Unavailable")
        exc_retry.status_code = 503

        def fake_caller(**kwargs: object) -> SimpleNamespace:
            captured_calls.append(dict(kwargs))
            if len(captured_calls) == 1:
                raise exc_400
            raise exc_retry

        with (
            patch(
                "app.api.ai_assistant.get_credential_for_user",
                AsyncMock(return_value=self.credential),
            ),
            patch("app.api.ai_assistant.decrypt_config", return_value={"api_key": "test-key"}),
            patch(
                "app.api.ai_assistant.resolve_model_binding",
                return_value=(object(), "openai", "claude-3-5-sonnet", None),
            ),
            patch("app.api.ai_assistant.completion_caller", return_value=fake_caller),
        ):
            with self.assertRaises(Exception) as raised_ctx:
                await fix_transcription(
                    request=self.request,
                    current_user=self.user,
                    db=AsyncMock(),
                )

        self.assertIs(raised_ctx.exception, exc_retry)
        self.assertEqual(len(captured_calls), 2)

    async def test_empty_model_response_content_falls_back_to_original_text(self) -> None:
        for empty_val in ("", None):
            with self.subTest(empty_val=empty_val):

                def fake_caller(**kwargs: object) -> SimpleNamespace:
                    return self._model_response(empty_val)

                with (
                    patch(
                        "app.api.ai_assistant.get_credential_for_user",
                        AsyncMock(return_value=self.credential),
                    ),
                    patch(
                        "app.api.ai_assistant.decrypt_config",
                        return_value={"api_key": "test-key"},
                    ),
                    patch(
                        "app.api.ai_assistant.resolve_model_binding",
                        return_value=(object(), "openai", "claude-3-5-sonnet", None),
                    ),
                    patch("app.api.ai_assistant.completion_caller", return_value=fake_caller),
                ):
                    response = await fix_transcription(
                        request=self.request,
                        current_user=self.user,
                        db=AsyncMock(),
                    )

                self.assertEqual(response.fixed_text, self.request.text.strip())


if __name__ == "__main__":
    unittest.main()
