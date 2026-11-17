"""Outlook Calendar OAuth state stays secret-free and callbacks stay with the owner's credential."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
from fastapi import HTTPException
from starlette.requests import Request

from app.api import outlook_calendar_oauth as oauth
from app.config import settings
from app.services.outlook_calendar_service import OUTLOOK_CALENDAR_SCOPES

CALLBACK = "https://app.test/api/credentials/outlook-calendar/oauth/callback"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _response(
    method: str, url: str, status: int = 200, json: object | None = None
) -> httpx.Response:
    return httpx.Response(status, json=json, request=httpx.Request(method, url))


class TestOutlookCalendarOAuthState(unittest.TestCase):
    def test_masked_value_shows_the_account_and_public_fields_hide_secrets(self) -> None:
        from app.api.credentials import get_masked_value, get_public_credential_fields
        from app.db.models import CredentialType

        config = {
            "client_id": "client",
            "client_secret": "dummy-secret",
            "tenant": "contoso.com",
            "refresh_token": "dummy-refresh",
            "access_token": "dummy-access",
            "email_address": "me@contoso.com",
        }
        self.assertEqual(
            get_masked_value(CredentialType.outlook_calendar, config), "connected (me@contoso.com)"
        )
        public = get_public_credential_fields(CredentialType.outlook_calendar, config)
        self.assertEqual(public, {"tenant": "contoso.com"})
        for secret in ("client_secret", "access_token", "refresh_token"):
            self.assertNotIn(secret, public)

    def test_state_and_auth_url_contain_no_client_secret(self) -> None:
        state = oauth.create_oauth_state(
            str(uuid.uuid4()), str(uuid.uuid4()), "client", "contoso.com", CALLBACK
        )
        payload = oauth.handle_callback_state(state)
        self.assertIsNotNone(payload)
        self.assertNotIn("client_secret", payload)
        url = oauth.build_auth_url("client", "contoso.com", CALLBACK, state)
        self.assertTrue(
            url.startswith("https://login.microsoftonline.com/contoso.com/oauth2/v2.0/authorize?")
        )
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["scope"], [" ".join(OUTLOOK_CALENDAR_SCOPES)])
        self.assertNotIn("client_secret", query)

    def test_the_scopes_ask_for_a_refresh_token_and_no_more_than_calendar_read_write(self) -> None:
        self.assertEqual(
            set(OUTLOOK_CALENDAR_SCOPES), {"offline_access", "User.Read", "Calendars.ReadWrite"}
        )

    def test_expired_foreign_malformed_and_bad_tenant_states_are_rejected(self) -> None:
        good = {
            "type": "outlook_calendar_oauth_state",
            "user_id": str(uuid.uuid4()),
            "credential_id": str(uuid.uuid4()),
            "client_id": "client",
            "redirect_uri": CALLBACK,
        }
        for payload in (
            {**good, "type": "outlook_oauth_state", "tenant": "common"},
            {**good, "tenant": "common", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
            {**good, "tenant": "common", "user_id": "bad"},
            {**good, "tenant": "evil.example/x"},
        ):
            with self.subTest(payload=payload):
                state = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
                self.assertIsNone(oauth.handle_callback_state(state))
        self.assertIsNone(oauth.handle_callback_state("encrypted-stored-config"))

    def test_saving_a_credential_with_a_bad_tenant_is_refused(self) -> None:
        from app.api.credentials import validate_credential_config
        from app.db.models import CredentialType

        with self.assertRaises(HTTPException) as caught:
            validate_credential_config(
                CredentialType.outlook_calendar,
                {"client_id": "c", "client_secret": "s", "tenant": "evil.example/x"},
            )
        self.assertEqual(caught.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.outlook_calendar, {"client_id": "c"})
        validate_credential_config(
            CredentialType.outlook_calendar, {"client_id": "c", "client_secret": "s"}
        )


class TestOutlookCalendarOAuthRoutes(unittest.IsolatedAsyncioTestCase):
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
            str(self.user_id), str(self.credential_id), "client", "common", CALLBACK
        )

    def _microsoft(self, token: httpx.Response, profile: httpx.Response | None = None) -> MagicMock:
        client = AsyncMock()
        client.post.return_value = token
        client.get.return_value = profile or _response(
            "GET",
            "https://graph.microsoft.com/v1.0/me",
            json={"mail": None, "userPrincipalName": "me@outlook.com"},
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
        self.assertTrue(response.auth_url.startswith("https://login.microsoftonline.com/common/"))
        statement = self.db.execute.call_args.args[0]
        self.assertIn("credentials.owner_id", str(statement))
        self.assertIn("credentials.type", str(statement))
        self.assertIn(self.user_id, statement.compile().params.values())

    async def test_an_outlook_mail_credential_is_never_selected(self) -> None:
        from app.db.models import CredentialType

        with patch.object(oauth, "resolve_public_origin", return_value="https://app.test"):
            await oauth.authorize(
                oauth.AuthorizeRequest(credential_id=self.credential_id),
                MagicMock(),
                MagicMock(id=self.user_id),
                self.db,
            )
        params = list(self.db.execute.call_args.args[0].compile().params.values())
        self.assertIn(CredentialType.outlook_calendar, params)
        self.assertNotIn(CredentialType.outlook, params)

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
            TOKEN_URL,
            json={
                "access_token": "dummy-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "scope": "Calendars.ReadWrite User.Read",
            },
        )
        with (
            patch.object(oauth.httpx, "AsyncClient", return_value=self._microsoft(token)),
            patch.object(oauth, "encrypt_config", return_value="new-encrypted") as encrypt,
        ):
            result = await oauth.callback("code", self.state, None, self.db)
        saved = encrypt.call_args.args[0]
        self.assertEqual(saved["refresh_token"], "new-refresh")
        self.assertEqual(saved["access_token"], "dummy-access")
        self.assertEqual(saved["email_address"], "me@outlook.com")
        self.assertEqual(self.credential.encrypted_config, "new-encrypted")
        html = result.body.decode()
        self.assertIn("google-oauth-success", html)
        for secret in ("dummy-access", "dummy-secret", "old-refresh", "new-refresh"):
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

    async def test_callback_rejects_a_changed_client_or_tenant(self) -> None:
        for change in ({"client_id": "different-client"}, {"tenant": "contoso.com"}):
            with self.subTest(change=change):
                self.config.update(change)
                with patch.object(oauth.httpx, "AsyncClient") as client:
                    result = await oauth.callback("code", self.state, None, self.db)
                self.assertIn("Credential changed", result.body.decode())
                client.assert_not_called()
                self.config.update({"client_id": "client", "tenant": "common"})

    async def test_declined_calendar_permission_does_not_persist(self) -> None:
        token = _response(
            "POST",
            TOKEN_URL,
            json={"access_token": "dummy-access", "scope": "User.Read Calendars.Read"},
        )
        with patch.object(oauth.httpx, "AsyncClient", return_value=self._microsoft(token)):
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("read and edit your Outlook calendar", result.body.decode())
        self.assertEqual(self.credential.encrypted_config, "stored-encrypted")
        self.db.commit.assert_not_awaited()

    async def test_a_failing_graph_profile_does_not_persist(self) -> None:
        token = _response(
            "POST",
            TOKEN_URL,
            json={"access_token": "dummy-access", "scope": "Calendars.ReadWrite"},
        )
        profile = _response("GET", "https://graph.microsoft.com/v1.0/me", 403, {})
        with patch.object(oauth.httpx, "AsyncClient", return_value=self._microsoft(token, profile)):
            result = await oauth.callback("code", self.state, None, self.db)
        self.assertIn("check the app permissions", result.body.decode())
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
