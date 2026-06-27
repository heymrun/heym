"""Tests for the Notion OAuth popup flow."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import jwt
from fastapi import HTTPException
from starlette.datastructures import Headers

_TEST_SECRET = "test-secret-key-for-tests-only-32-bytes"
_ALGORITHM = "HS256"


def _make_db_result(credential: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = credential
    return result


class NotionOAuthTests(unittest.TestCase):
    def test_auth_url_contains_notion_parameters(self) -> None:
        from app.api.notion_oauth import build_auth_url

        url = build_auth_url("client-id", "https://heym.test/callback", "state-token")
        self.assertIn("api.notion.com/v1/oauth/authorize", url)
        self.assertIn("owner=user", url)
        self.assertIn("client_id=client-id", url)
        self.assertIn("state=state-token", url)

    def test_state_round_trip(self) -> None:
        from app.api.notion_oauth import create_oauth_state, handle_callback_state

        with patch("app.api.notion_oauth.settings") as settings:
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            state = create_oauth_state(
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "https://heym.test/callback",
            )
            payload = handle_callback_state(state)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "notion_oauth_state")
        self.assertNotIn("client_id", payload)
        self.assertNotIn("client_secret", payload)

    def test_expired_state_is_rejected(self) -> None:
        from app.api.notion_oauth import handle_callback_state

        state = jwt.encode(
            {
                "type": "notion_oauth_state",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            _TEST_SECRET,
            algorithm=_ALGORITHM,
        )
        with patch("app.api.notion_oauth.settings") as settings:
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            self.assertIsNone(handle_callback_state(state))

    def test_popup_posts_only_to_current_origin(self) -> None:
        from app.api.notion_oauth import _popup_html

        html = _popup_html(True, credential_id="cred-1")
        self.assertIn("notion-oauth-success", html)
        self.assertIn("window.location.origin", html)
        self.assertNotIn("postMessage(message, '*')", html)

    def test_popup_escapes_script_payload(self) -> None:
        from app.api.notion_oauth import _popup_html

        html = _popup_html(False, message="</script><script>alert(1)</script>")
        self.assertNotIn("</script><script>", html)
        self.assertIn("\\u003c/script\\u003e", html)


class NotionOAuthEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _make_credential(self) -> Mock:
        from app.db.models import Credential, CredentialType
        from app.services.encryption import encrypt_config

        credential = Mock(spec=Credential)
        credential.id = uuid.uuid4()
        credential.owner_id = uuid.uuid4()
        credential.type = CredentialType.notion
        credential.encrypted_config = encrypt_config(
            {
                "auth_mode": "oauth",
                "client_id": "client-id",
                "client_secret": "client-secret",
            }
        )
        return credential

    async def test_authorize_returns_auth_url_for_valid_credential(self) -> None:
        from app.api.notion_oauth import AuthorizeRequest, AuthorizeResponse, authorize

        credential = self._make_credential()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(credential))

        user = Mock()
        user.id = credential.owner_id

        request = Mock()
        request.base_url = "http://testserver/"
        request.headers = Headers({})

        body = AuthorizeRequest(credential_id=credential.id)

        with patch("app.api.notion_oauth.settings") as settings:
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            result = await authorize(body=body, request=request, current_user=user, db=db)

        self.assertIsInstance(result, AuthorizeResponse)
        self.assertIn("api.notion.com/v1/oauth/authorize", result.auth_url)
        self.assertIn("client_id=client-id", result.auth_url)

    async def test_authorize_returns_404_when_credential_missing(self) -> None:
        from app.api.notion_oauth import AuthorizeRequest, authorize

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(None))

        user = Mock()
        user.id = uuid.uuid4()

        request = Mock()
        request.base_url = "http://testserver/"
        request.headers = Headers({})

        body = AuthorizeRequest(credential_id=uuid.uuid4())

        with self.assertRaises(HTTPException) as context:
            await authorize(body=body, request=request, current_user=user, db=db)

        self.assertEqual(context.exception.status_code, 404)

    async def test_authorize_returns_400_when_oauth_client_missing(self) -> None:
        from app.api.notion_oauth import AuthorizeRequest, authorize

        credential = self._make_credential()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(credential))

        user = Mock()
        user.id = credential.owner_id

        request = Mock()
        request.base_url = "http://testserver/"
        request.headers = Headers({})

        body = AuthorizeRequest(credential_id=credential.id)

        from app.services.encryption import encrypt_config

        credential.encrypted_config = encrypt_config({"auth_mode": "oauth"})
        with patch("app.api.notion_oauth.settings") as settings:
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            with self.assertRaises(HTTPException) as context:
                await authorize(body=body, request=request, current_user=user, db=db)

        self.assertEqual(context.exception.status_code, 400)

    async def test_callback_persists_oauth_token_and_clears_api_token(self) -> None:
        from app.api.notion_oauth import callback, create_oauth_state
        from app.services.encryption import decrypt_config, encrypt_config

        credential = self._make_credential()
        credential.encrypted_config = encrypt_config(
            {
                "auth_mode": "token",
                "api_token": "ntn_old_token",
                "client_id": "client-id",
                "client_secret": "client-secret",
            }
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(credential))
        db.commit = AsyncMock()

        redirect_uri = "http://testserver/api/credentials/notion/oauth/callback"
        with patch("app.api.notion_oauth.settings") as settings:
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            state = create_oauth_state(
                str(credential.owner_id),
                str(credential.id),
                redirect_uri,
            )

        token_response = MagicMock()
        token_response.raise_for_status = Mock()
        token_response.json.return_value = {
            "access_token": "oauth-access-token",
            "workspace_id": "workspace-1",
            "workspace_name": "Acme HQ",
            "bot_id": "bot-1",
        }

        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=token_response)
        http_client.__aenter__ = AsyncMock(return_value=http_client)
        http_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.api.notion_oauth.settings") as settings,
            patch("app.api.notion_oauth.httpx.AsyncClient", return_value=http_client),
        ):
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            response = await callback(code="auth-code", state=state, db=db)

        self.assertIn("notion-oauth-success", response.body.decode())
        stored = decrypt_config(credential.encrypted_config)
        self.assertEqual(stored["access_token"], "oauth-access-token")
        self.assertEqual(stored["auth_mode"], "oauth")
        self.assertEqual(stored["workspace_name"], "Acme HQ")
        self.assertNotIn("api_token", stored)
        http_client.post.assert_awaited_once()
        self.assertEqual(http_client.post.call_args.kwargs["auth"], ("client-id", "client-secret"))
        db.commit.assert_awaited_once()

    async def test_callback_returns_error_popup_for_invalid_state(self) -> None:
        from app.api.notion_oauth import callback

        db = AsyncMock()
        response = await callback(code="auth-code", state="invalid-state", db=db)
        self.assertIn("notion-oauth-error", response.body.decode())
        db.commit.assert_not_called()

    async def test_callback_hides_token_exchange_error_details(self) -> None:
        from app.api.notion_oauth import callback, create_oauth_state

        credential = self._make_credential()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_make_db_result(credential))

        with patch("app.api.notion_oauth.settings") as settings:
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            state = create_oauth_state(
                str(credential.owner_id),
                str(credential.id),
                "http://testserver/api/credentials/notion/oauth/callback",
            )

        request = httpx.Request("POST", "https://api.notion.com/v1/oauth/token")
        token_response = httpx.Response(
            401,
            request=request,
            text="client_secret=super-secret-value",
        )
        http_client = AsyncMock()
        http_client.post = AsyncMock(return_value=token_response)
        http_client.__aenter__ = AsyncMock(return_value=http_client)
        http_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("app.api.notion_oauth.settings") as settings,
            patch("app.api.notion_oauth.httpx.AsyncClient", return_value=http_client),
        ):
            settings.secret_key = _TEST_SECRET
            settings.jwt_algorithm = _ALGORITHM
            response = await callback(code="auth-code", state=state, db=db)

        html = response.body.decode()
        self.assertIn("Token exchange failed", html)
        self.assertNotIn("super-secret-value", html)
        db.commit.assert_not_called()
