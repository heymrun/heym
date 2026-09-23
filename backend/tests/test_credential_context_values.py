"""What `$credentials.<name>` resolves to, per credential type."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.credential_context import credential_context_value


def _google_config(*, expired: bool) -> dict:
    delta = timedelta(minutes=-5) if expired else timedelta(hours=1)
    return {
        "client_id": "client-id",
        "client_secret": "client-secret",
        "access_token": "ya29.stored-token",
        "refresh_token": "1//refresh-token",
        "token_expiry": (datetime.now(timezone.utc) + delta).isoformat(),
    }


def _credential(credential_type: CredentialType) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), name="sheet", type=credential_type)


def _token_response(token: str) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"access_token": token, "expires_in": 3600}
    return response


class GoogleOAuthCredentialValueTests(unittest.IsolatedAsyncioTestCase):
    """Google OAuth tokens expire hourly, so the value must be a fresh access token."""

    def setUp(self) -> None:
        self.db = MagicMock()
        self.db.query.return_value.filter.return_value.first.return_value = MagicMock()
        session_local = MagicMock()
        session_local.return_value.__enter__.return_value = self.db
        patcher = patch("app.db.session.SessionLocal", session_local)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_unexpired_sheets_token_is_used_as_is(self) -> None:
        with patch("httpx.post") as token_request:
            value = await credential_context_value(
                _credential(CredentialType.google_sheets), _google_config(expired=False)
            )

        token_request.assert_not_called()
        self.assertEqual(value, "ya29.stored-token")

    async def test_expired_sheets_token_is_refreshed_and_persisted(self) -> None:
        with patch("httpx.post", return_value=_token_response("ya29.fresh-token")):
            value = await credential_context_value(
                _credential(CredentialType.google_sheets), _google_config(expired=True)
            )

        self.assertEqual(value, "ya29.fresh-token")
        self.db.commit.assert_called_once()

    async def test_expired_drive_token_is_refreshed(self) -> None:
        with patch("httpx.post", return_value=_token_response("ya29.drive-token")):
            value = await credential_context_value(
                _credential(CredentialType.google_drive), _google_config(expired=True)
            )

        self.assertEqual(value, "ya29.drive-token")

    async def test_failed_refresh_resolves_to_empty_string(self) -> None:
        with patch("httpx.post", side_effect=httpx.ConnectError("token endpoint down")):
            value = await credential_context_value(
                _credential(CredentialType.google_sheets), _google_config(expired=True)
            )

        self.assertEqual(value, "")


class CredentialValueShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bearer_value_carries_the_prefix(self) -> None:
        value = await credential_context_value(
            _credential(CredentialType.bearer), {"bearer_token": "tok"}
        )

        self.assertEqual(value, "Bearer tok")

    async def test_header_value_is_the_whole_line(self) -> None:
        value = await credential_context_value(
            _credential(CredentialType.header), {"header_key": "X-Api-Key", "header_value": "v"}
        )

        self.assertEqual(value, "X-Api-Key: v")

    async def test_api_key_types_resolve_to_the_raw_key(self) -> None:
        value = await credential_context_value(
            _credential(CredentialType.google), {"api_key": "AIza-key"}
        )

        self.assertEqual(value, "AIza-key")

    async def test_codex_is_left_out(self) -> None:
        value = await credential_context_value(
            _credential(CredentialType.codex), {"access_token": "chatgpt-token"}
        )

        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
