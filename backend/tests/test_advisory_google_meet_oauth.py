"""OAuth state stays secret-free and callbacks cannot change another owner's credential."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
from fastapi import HTTPException
from starlette.requests import Request

from app.api import google_meet_oauth as oauth
from app.config import settings
from app.services.google_meet_service import GOOGLE_MEET_SCOPE


class TestGoogleMeetOAuthState(unittest.TestCase):
    def test_public_credential_fields_do_not_return_oauth_secrets(self) -> None:
        from app.api.credentials import get_masked_value, get_public_credential_fields
        from app.db.models import CredentialType

        config = {
            "client_id": "client",
            "client_secret": "dummy-secret",
            "refresh_token": "dummy-refresh",
            "access_token": "dummy-access",
        }
        self.assertEqual(get_masked_value(CredentialType.google_meet, config), "connected")
        public = get_public_credential_fields(CredentialType.google_meet, config)
        self.assertNotIn("client_secret", public)
        self.assertNotIn("access_token", public)
        self.assertNotIn("refresh_token", public)

    def test_state_and_auth_url_contain_no_client_secret(self) -> None:
        state = oauth.create_oauth_state(
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            "client",
            "https://app.test/api/credentials/google-meet/oauth/callback",
        )
        payload = oauth.handle_callback_state(state)
        self.assertIsNotNone(payload)
        self.assertNotIn("client_secret", payload)
        query = parse_qs(
            urlparse(oauth.build_auth_url("client", payload["redirect_uri"], state)).query
        )
        self.assertEqual(query["scope"], [GOOGLE_MEET_SCOPE])
        self.assertEqual(query["access_type"], ["offline"])
        self.assertNotIn("client_secret", query)

    def test_expired_foreign_and_malformed_states_are_rejected(self) -> None:
        for payload in (
            {"type": "gd_oauth_state"},
            {
                "type": "google_meet_oauth_state",
                "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
            },
            {"type": "google_meet_oauth_state", "user_id": "bad", "credential_id": "bad"},
        ):
            with self.subTest(payload=payload):
                state = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
                self.assertIsNone(oauth.handle_callback_state(state))
        self.assertIsNone(oauth.handle_callback_state("encrypted-stored-config"))


class TestGoogleMeetOAuthRoutes(unittest.IsolatedAsyncioTestCase):
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
            str(self.user_id),
            str(self.credential_id),
            "client",
            "https://app.test/api/credentials/google-meet/oauth/callback",
        )

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
        self.assertIn("accounts.google.com", response.auth_url)
        query = self.db.execute.call_args.args[0]
        sql = str(query)
        self.assertIn("credentials.owner_id", sql)
        self.assertIn("credentials.type", sql)
        self.assertIn(self.user_id, query.compile().params.values())

    async def test_authorize_rejects_inaccessible_credential(self) -> None:
        self.db.execute.return_value.scalar_one_or_none.return_value = None
        with self.assertRaises(HTTPException) as caught:
            await oauth.authorize(
                oauth.AuthorizeRequest(credential_id=self.credential_id),
                MagicMock(),
                MagicMock(id=self.user_id),
                self.db,
            )
        self.assertEqual(caught.exception.status_code, 404)

    async def test_callback_preserves_refresh_token_and_only_returns_credential_id(self) -> None:
        response = httpx.Response(
            200,
            json={"access_token": "dummy-access", "expires_in": 3600, "scope": GOOGLE_MEET_SCOPE},
            request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
        )
        client = AsyncMock()
        client.post.return_value = response
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(oauth.httpx, "AsyncClient", return_value=manager),
            patch.object(oauth, "encrypt_config", return_value="new-encrypted") as encrypt,
        ):
            result = await oauth.callback("code", self.state, None, self.db)
        saved = encrypt.call_args.args[0]
        self.assertEqual(saved["refresh_token"], "old-refresh")
        self.assertEqual(saved["access_token"], "dummy-access")
        self.assertEqual(self.credential.encrypted_config, "new-encrypted")
        html = result.body.decode()
        self.assertIn("google-oauth-success", html)
        self.assertNotIn("dummy-access", html)
        self.assertNotIn("dummy-secret", html)
        self.assertNotIn("old-refresh", html)
        query = self.db.execute.call_args.args[0]
        self.assertIn("credentials.owner_id", str(query))
        self.assertIn("credentials.type", str(query))
        self.db.commit.assert_awaited_once()

    async def test_callback_rejects_deleted_or_transferred_credential_before_token_exchange(
        self,
    ) -> None:
        self.db.execute.return_value.scalar_one_or_none.return_value = None
        with patch.object(oauth.httpx, "AsyncClient") as client:
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("not found", result.body.decode())
        client.assert_not_called()
        self.db.commit.assert_not_awaited()

    async def test_callback_rejects_changed_client(self) -> None:
        self.config["client_id"] = "different-client"
        with patch.object(oauth.httpx, "AsyncClient") as client:
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("Credential changed", result.body.decode())
        client.assert_not_called()

    async def test_partial_consent_does_not_persist_a_connected_credential(self) -> None:
        response = httpx.Response(
            200,
            json={
                "access_token": "dummy-access",
                "scope": "https://www.googleapis.com/auth/calendar.events",
            },
            request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
        )
        client = AsyncMock()
        client.post.return_value = response
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)
        with patch.object(oauth.httpx, "AsyncClient", return_value=manager):
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("Allow both", result.body.decode())
        self.assertEqual(self.credential.encrypted_config, "stored-encrypted")
        self.db.commit.assert_not_awaited()

    async def test_cancelled_callback_and_stored_config_cannot_authorize(self) -> None:
        for code, state, error in ((None, None, "cancelled"), ("code", "stored-encrypted", None)):
            with self.subTest(state=state):
                result = await oauth.callback(code, state, error, self.db)
                self.assertIn("google-oauth-error", result.body.decode())
        self.db.execute.assert_not_awaited()
        self.db.commit.assert_not_awaited()
