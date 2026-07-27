"""Tests for the Google Drive OAuth2 state helpers and URL builder."""

import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt

from app.api.google_drive_oauth import (
    _DRIVE_SCOPE,
    build_auth_url,
    create_oauth_state,
    handle_callback_state,
)
from app.config import settings


class TestGoogleDriveOAuthState(unittest.TestCase):
    def test_round_trip_state_preserves_payload(self) -> None:
        state = create_oauth_state(
            user_id="11111111-1111-1111-1111-111111111111",
            credential_id="22222222-2222-2222-2222-222222222222",
            client_id="client-abc",
            client_secret="secret-xyz",
            redirect_uri="https://app.example.com/api/credentials/google-drive/oauth/callback",
        )
        payload = handle_callback_state(state)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["user_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(payload["credential_id"], "22222222-2222-2222-2222-222222222222")
        self.assertEqual(payload["client_id"], "client-abc")
        self.assertEqual(payload["client_secret"], "secret-xyz")
        self.assertEqual(payload["type"], "gd_oauth_state")

    def test_rejects_state_from_a_different_flow(self) -> None:
        """A Google Sheets state token must not authorize a Drive credential."""
        foreign = jwt.encode(
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "type": "gs_oauth_state",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            settings.secret_key,
            algorithm=settings.jwt_algorithm,
        )
        self.assertIsNone(handle_callback_state(foreign))

    def test_rejects_expired_state(self) -> None:
        expired = jwt.encode(
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "type": "gd_oauth_state",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            settings.secret_key,
            algorithm=settings.jwt_algorithm,
        )
        self.assertIsNone(handle_callback_state(expired))

    def test_rejects_tampered_state(self) -> None:
        forged = jwt.encode(
            {
                "user_id": "11111111-1111-1111-1111-111111111111",
                "type": "gd_oauth_state",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            },
            "not-the-real-secret-key-at-all-32b",
            algorithm=settings.jwt_algorithm,
        )
        self.assertIsNone(handle_callback_state(forged))


class TestGoogleDriveAuthUrl(unittest.TestCase):
    def test_requests_full_drive_scope_offline(self) -> None:
        url = build_auth_url(
            "client-abc",
            "https://app.example.com/api/credentials/google-drive/oauth/callback",
            "state-token",
        )
        query = parse_qs(urlparse(url).query)

        self.assertEqual(query["scope"], [_DRIVE_SCOPE])
        self.assertEqual(_DRIVE_SCOPE, "https://www.googleapis.com/auth/drive")
        # offline + consent guarantee a refresh_token is issued every time.
        self.assertEqual(query["access_type"], ["offline"])
        self.assertEqual(query["prompt"], ["consent"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["state"], ["state-token"])


if __name__ == "__main__":
    unittest.main()
