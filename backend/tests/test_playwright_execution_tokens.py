"""Unit tests for playwright_execution_tokens (signed JWTs for subprocess callbacks)."""

import unittest
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.services.playwright_execution_tokens import (
    PlaywrightExecutionClaims,
    create_token,
    validate_token,
)


class CreateAndValidateTokenTests(unittest.TestCase):
    def test_round_trip_returns_the_same_user_id(self) -> None:
        token = create_token("user-123")
        self.assertEqual(validate_token(token), PlaywrightExecutionClaims(user_id="user-123"))

    def test_round_trip_carries_the_run_context(self) -> None:
        token = create_token(
            "user-123",
            workflow_id="wf-1",
            node_id="pw1",
            node_label="Browser",
            session_id="exec-1",
        )
        self.assertEqual(
            validate_token(token),
            PlaywrightExecutionClaims(
                user_id="user-123",
                workflow_id="wf-1",
                node_id="pw1",
                node_label="Browser",
                session_id="exec-1",
            ),
        )

    def test_token_without_subject_is_invalid(self) -> None:
        payload = {
            "exp": datetime.now(timezone.utc) + timedelta(seconds=600),
            "type": "playwright_execution",
        }
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        self.assertIsNone(validate_token(token))

    def test_none_token_is_invalid(self) -> None:
        self.assertIsNone(validate_token(None))

    def test_empty_string_token_is_invalid(self) -> None:
        self.assertIsNone(validate_token(""))

    def test_garbage_token_is_invalid(self) -> None:
        self.assertIsNone(validate_token("not-a-real-jwt"))

    def test_expired_token_is_invalid(self) -> None:
        payload = {
            "sub": "user-123",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            "type": "playwright_execution",
        }
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        self.assertIsNone(validate_token(token))

    def test_wrong_token_type_is_rejected(self) -> None:
        payload = {
            "sub": "user-123",
            "exp": datetime.now(timezone.utc) + timedelta(seconds=600),
            "type": "something_else",
        }
        token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        self.assertIsNone(validate_token(token))

    def test_token_signed_with_wrong_secret_is_rejected(self) -> None:
        payload = {
            "sub": "user-123",
            "exp": datetime.now(timezone.utc) + timedelta(seconds=600),
            "type": "playwright_execution",
        }
        wrong_secret = "wrong-secret-but-still-32-bytes-"
        token = jwt.encode(payload, wrong_secret, algorithm=settings.jwt_algorithm)
        self.assertIsNone(validate_token(token))


if __name__ == "__main__":
    unittest.main()
