"""Gmail OAuth state stays secret-free and callbacks cannot change another owner's credential."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
from fastapi import HTTPException
from starlette.requests import Request

from app.api import gmail_oauth as oauth
from app.config import settings
from app.services.gmail_service import GMAIL_SCOPE

CALLBACK = "https://app.test/api/credentials/gmail/oauth/callback"


def _response(
    method: str, url: str, status: int = 200, json: object | None = None
) -> httpx.Response:
    return httpx.Response(status, json=json, request=httpx.Request(method, url))


class TestGmailOAuthState(unittest.TestCase):
    def test_masked_value_shows_the_account_and_public_fields_hide_secrets(self) -> None:
        from app.api.credentials import get_masked_value, get_public_credential_fields
        from app.db.models import CredentialType

        config = {
            "client_id": "client",
            "client_secret": "dummy-secret",
            "refresh_token": "dummy-refresh",
            "access_token": "dummy-access",
            "email_address": "me@example.com",
        }
        self.assertEqual(
            get_masked_value(CredentialType.gmail, config), "connected (me@example.com)"
        )
        public = get_public_credential_fields(CredentialType.gmail, config)
        for secret in ("client_secret", "access_token", "refresh_token"):
            self.assertNotIn(secret, public)

    def test_state_and_auth_url_contain_no_client_secret(self) -> None:
        state = oauth.create_oauth_state(str(uuid.uuid4()), str(uuid.uuid4()), "client", CALLBACK)
        payload = oauth.handle_callback_state(state)
        self.assertIsNotNone(payload)
        self.assertNotIn("client_secret", payload)
        query = parse_qs(urlparse(oauth.build_auth_url("client", CALLBACK, state)).query)
        self.assertEqual(query["scope"], [GMAIL_SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertNotIn("client_secret", query)

    def test_the_scope_never_allows_permanent_deletion(self) -> None:
        self.assertEqual(GMAIL_SCOPE, "https://www.googleapis.com/auth/gmail.modify")

    def test_expired_foreign_and_malformed_states_are_rejected(self) -> None:
        for payload in (
            {"type": "google_meet_oauth_state"},
            {"type": "gmail_oauth_state", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            {"type": "gmail_oauth_state", "user_id": "bad", "credential_id": "bad"},
        ):
            with self.subTest(payload=payload):
                state = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
                self.assertIsNone(oauth.handle_callback_state(state))
        self.assertIsNone(oauth.handle_callback_state("encrypted-stored-config"))


class TestGmailOAuthRoutes(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id, self.credential_id = uuid.uuid4(), uuid.uuid4()
        self.db = AsyncMock()
        self.credential = MagicMock(id=self.credential_id, encrypted_config="stored-encrypted")
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.credential
        self.db.execute.return_value = result
        self.config = {
            "client_id": "client",
            "client_secret": "dummy-secret",
            "refresh_token": "old-refresh",
        }
        patcher = patch.object(oauth, "decrypt_config", return_value=self.config)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state = oauth.create_oauth_state(
            str(self.user_id), str(self.credential_id), "client", CALLBACK
        )

    def _google(self, token: httpx.Response, profile: httpx.Response | None = None) -> MagicMock:
        client = AsyncMock()
        client.post.return_value = token
        client.get.return_value = profile or _response(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            json={"emailAddress": "me@example.com", "historyId": "1"},
        )
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        return manager

    async def test_authorize_is_owner_and_type_scoped(self) -> None:
        request = Request(
            {"type": "http", "scheme": "https", "server": ("app.test", 443), "headers": []}
        )
        with patch.object(oauth, "resolve_public_origin", return_value="https://app.test"):
            response = await oauth.authorize(
                oauth.AuthorizeRequest(credential_id=self.credential_id),
                request,
                MagicMock(id=self.user_id),
                self.db,
            )
        query = parse_qs(urlparse(response.auth_url).query)
        self.assertEqual(query["redirect_uri"], [CALLBACK])
        statement = self.db.execute.call_args.args[0]
        self.assertIn("credentials.owner_id", str(statement))
        self.assertIn("credentials.type", str(statement))
        self.assertIn(self.user_id, statement.compile().params.values())

    async def test_authorize_rejects_an_inaccessible_credential(self) -> None:
        self.db.execute.return_value.scalar_one_or_none.return_value = None
        with self.assertRaises(HTTPException) as caught:
            await oauth.authorize(
                oauth.AuthorizeRequest(credential_id=self.credential_id),
                MagicMock(),
                MagicMock(id=self.user_id),
                self.db,
            )
        self.assertEqual(caught.exception.status_code, 404)

    async def test_callback_saves_tokens_and_the_account_and_returns_only_the_id(self) -> None:
        token = _response(
            "POST",
            "https://oauth2.googleapis.com/token",
            json={"access_token": "dummy-access", "expires_in": 3600, "scope": GMAIL_SCOPE},
        )
        with (
            patch.object(oauth.httpx, "AsyncClient", return_value=self._google(token)),
            patch.object(oauth, "encrypt_config", return_value="new-encrypted") as encrypt,
        ):
            result = await oauth.callback("code", self.state, None, self.db)
        saved = encrypt.call_args.args[0]
        self.assertEqual(saved["refresh_token"], "old-refresh")
        self.assertEqual(saved["access_token"], "dummy-access")
        self.assertEqual(saved["email_address"], "me@example.com")
        self.assertEqual(self.credential.encrypted_config, "new-encrypted")
        html = result.body.decode()
        self.assertIn("google-oauth-success", html)
        for secret in ("dummy-access", "dummy-secret", "old-refresh"):
            self.assertNotIn(secret, html)
        statement = self.db.execute.call_args.args[0]
        self.assertIn("credentials.owner_id", str(statement))
        self.assertIn("credentials.type", str(statement))
        self.db.commit.assert_awaited_once()

    async def test_callback_rejects_a_missing_credential_before_token_exchange(self) -> None:
        self.db.execute.return_value.scalar_one_or_none.return_value = None
        with patch.object(oauth.httpx, "AsyncClient") as client:
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("not found", result.body.decode())
        client.assert_not_called()
        self.db.commit.assert_not_awaited()

    async def test_callback_rejects_a_changed_client(self) -> None:
        self.config["client_id"] = "different-client"
        with patch.object(oauth.httpx, "AsyncClient") as client:
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("Credential changed", result.body.decode())
        client.assert_not_called()

    async def test_declined_gmail_permission_does_not_persist(self) -> None:
        token = _response(
            "POST",
            "https://oauth2.googleapis.com/token",
            json={"access_token": "dummy-access", "scope": "openid email"},
        )
        with patch.object(oauth.httpx, "AsyncClient", return_value=self._google(token)):
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("read and organize your Gmail", result.body.decode())
        self.assertEqual(self.credential.encrypted_config, "stored-encrypted")
        self.db.commit.assert_not_awaited()

    async def test_a_disabled_gmail_api_is_named_and_does_not_persist(self) -> None:
        token = _response(
            "POST",
            "https://oauth2.googleapis.com/token",
            json={"access_token": "dummy-access", "scope": GMAIL_SCOPE},
        )
        profile = _response(
            "GET", "https://gmail.googleapis.com/gmail/v1/users/me/profile", 403, {}
        )
        with patch.object(oauth.httpx, "AsyncClient", return_value=self._google(token, profile)):
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("enable the Gmail API", result.body.decode())
        self.db.commit.assert_not_awaited()

    async def test_cancelled_callback_and_stored_config_cannot_authorize(self) -> None:
        for code, state, error in ((None, None, "cancelled"), ("code", "stored-encrypted", None)):
            with self.subTest(state=state):
                result = await oauth.callback(code, state, error, self.db)
                self.assertIn("google-oauth-error", result.body.decode())
        self.db.execute.assert_not_awaited()
        self.db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
