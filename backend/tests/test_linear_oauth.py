"""Tests for the Linear OAuth popup flow."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.db.models import CredentialType
from app.services.encryption import decrypt_config, encrypt_config


class LinearOAuthTests(unittest.TestCase):
    def test_build_auth_url_includes_linear_scope_and_actor(self) -> None:
        from app.api.linear_oauth import build_auth_url

        url = build_auth_url("client-id", "http://test/callback", "state-token")

        self.assertIn("linear.app/oauth/authorize", url)
        self.assertIn("scope=read%2Cwrite%2Cissues%3Acreate%2Ccomments%3Acreate", url)
        self.assertIn("actor=user", url)

    def test_state_roundtrip(self) -> None:
        from app.api.linear_oauth import create_oauth_state, handle_callback_state

        with patch("app.api.linear_oauth.settings") as settings:
            settings.secret_key = "secret"
            settings.jwt_algorithm = "HS256"
            state = create_oauth_state(
                "user-id",
                "credential-id",
                "http://test/callback",
            )
            payload = handle_callback_state(state)

        self.assertEqual(payload["type"], "linear_oauth_state")
        self.assertEqual(payload["credential_id"], "credential-id")


class LinearOAuthEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorize_returns_linear_auth_url(self) -> None:
        from app.api.linear_oauth import AuthorizeRequest, authorize

        credential_id = uuid.uuid4()
        credential = MagicMock(
            id=credential_id,
            owner_id=uuid.uuid4(),
            type=CredentialType.linear,
            encrypted_config=encrypt_config(
                {
                    "auth_mode": "oauth",
                    "client_id": "linear-client",
                    "client_secret": "linear-secret",
                }
            ),
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = credential
        db.execute.return_value = result
        request = MagicMock()
        request.url.scheme = "http"
        request.headers = {"host": "testserver"}
        request.client = MagicMock(host="testclient")

        with patch("app.api.linear_oauth.settings") as settings:
            settings.frontend_url = "http://testserver"
            settings.secret_key = "secret"
            settings.jwt_algorithm = "HS256"
            result = await authorize(
                AuthorizeRequest(credential_id=credential_id),
                request,
                current_user=MagicMock(id=credential.owner_id),
                db=db,
            )

        self.assertIn("linear.app/oauth/authorize", result.auth_url)
        self.assertIn("client_id=linear-client", result.auth_url)

    async def test_callback_persists_oauth_token_and_clears_api_key(self) -> None:
        from app.api.linear_oauth import callback, create_oauth_state

        credential_id = uuid.uuid4()
        user_id = uuid.uuid4()
        credential = MagicMock(
            id=credential_id,
            owner_id=user_id,
            type=CredentialType.linear,
            encrypted_config=encrypt_config(
                {
                    "auth_mode": "oauth",
                    "api_key": "lin_api_old",
                    "client_id": "linear-client",
                    "client_secret": "linear-secret",
                }
            ),
        )
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = credential
        db.execute.return_value = result
        redirect_uri = "http://testserver/api/credentials/linear/oauth/callback"
        with patch("app.api.linear_oauth.settings") as settings:
            settings.secret_key = "secret"
            settings.jwt_algorithm = "HS256"
            state = create_oauth_state(str(user_id), str(credential_id), redirect_uri)

        token_response = httpx.Response(
            200,
            json={
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", "https://api.linear.app/oauth/token"),
        )
        http_client = AsyncMock()
        http_client.__aenter__.return_value.post.return_value = token_response
        http_client.__aexit__.return_value = False

        with (
            patch("app.api.linear_oauth.settings") as settings,
            patch("app.api.linear_oauth.httpx.AsyncClient", return_value=http_client),
        ):
            settings.secret_key = "secret"
            settings.jwt_algorithm = "HS256"
            response = await callback(code="code", state=state, db=db)

        self.assertIn("linear-oauth-success", response.body.decode())
        stored = decrypt_config(credential.encrypted_config)
        self.assertNotIn("api_key", stored)
        self.assertEqual(stored["access_token"], "oauth-access-token")
        self.assertEqual(stored["refresh_token"], "oauth-refresh-token")
        self.assertEqual(stored["auth_mode"], "oauth")
        post_kwargs = http_client.__aenter__.return_value.post.call_args.kwargs
        self.assertNotIn("json", post_kwargs)
        self.assertEqual(
            post_kwargs["data"],
            {
                "grant_type": "authorization_code",
                "code": "code",
                "redirect_uri": redirect_uri,
                "client_id": "linear-client",
                "client_secret": "linear-secret",
            },
        )
        self.assertEqual(
            post_kwargs["headers"]["Content-Type"],
            "application/x-www-form-urlencoded",
        )
        db.commit.assert_awaited_once()
