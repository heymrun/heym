import base64
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api import codex_oauth
from app.api.credentials import merge_credential_config_for_update, validate_credential_config
from app.db.models import CredentialType
from app.services.codex_oauth_service import (
    DEVICE_CODE_TTL_SECONDS,
    CodexDeviceCode,
    CodexDeviceGrant,
    CodexOAuthError,
    CodexOAuthService,
    CodexTokenBundle,
    _account_id_from_id_token,
    _poll_interval_from,
    bundle_is_expired,
    generate_pkce_pair,
)


def _make_id_token(payload: dict) -> str:
    def _seg(data: dict) -> str:
        raw = json.dumps(data).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{_seg({'alg': 'none'})}.{_seg(payload)}.sig"


class TestPkce(unittest.TestCase):
    def test_pkce_pair_is_urlsafe_and_distinct(self) -> None:
        verifier, challenge = generate_pkce_pair()
        self.assertNotEqual(verifier, challenge)
        self.assertNotIn("=", verifier)
        self.assertNotIn("=", challenge)
        self.assertGreaterEqual(len(verifier), 43)

    def test_authorize_url_contains_pkce_and_client(self) -> None:
        auth = CodexOAuthService().create_authorization()
        self.assertIn("code_challenge_method=S256", auth.authorize_url)
        self.assertIn("response_type=code", auth.authorize_url)
        self.assertIn(f"state={auth.state}", auth.authorize_url)


class TestExtractCode(unittest.TestCase):
    def setUp(self) -> None:
        self.service = CodexOAuthService()

    def test_extracts_code_and_validates_state(self) -> None:
        url = "http://localhost:1455/auth/callback?code=the-code&state=st-1"
        self.assertEqual(self.service.extract_code(url, "st-1"), "the-code")

    def test_rejects_state_mismatch(self) -> None:
        url = "http://localhost:1455/auth/callback?code=the-code&state=other"
        with self.assertRaises(CodexOAuthError):
            self.service.extract_code(url, "expected")

    def test_surfaces_provider_error(self) -> None:
        url = "http://localhost:1455/auth/callback?error=access_denied&error_description=nope"
        with self.assertRaises(CodexOAuthError) as ctx:
            self.service.extract_code(url, "st")
        self.assertIn("nope", str(ctx.exception))

    def test_accepts_bare_code(self) -> None:
        self.assertEqual(self.service.extract_code("bare-code-value", ""), "bare-code-value")

    def test_empty_redirect_raises(self) -> None:
        with self.assertRaises(CodexOAuthError):
            self.service.extract_code("", "st")


class TestTokenExchange(unittest.TestCase):
    def _client(self, status_code: int, body: dict) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = body
        client = MagicMock()
        client.post.return_value = response
        return client

    def test_exchange_code_builds_bundle(self) -> None:
        id_token = _make_id_token({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-9"}})
        client = self._client(
            200,
            {
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "id_token": id_token,
                "expires_in": 3600,
            },
        )
        bundle = CodexOAuthService(client=client).exchange_code("code", "verifier")
        self.assertEqual(bundle.access_token, "at-1")
        self.assertEqual(bundle.refresh_token, "rt-1")
        self.assertEqual(bundle.account_id, "acct-9")
        self.assertIsNotNone(bundle.expires_at)
        self.assertEqual(bundle.to_config()["auth_mode"], "chatgpt")

    def test_error_response_raises(self) -> None:
        client = self._client(400, {"error_description": "bad code"})
        with self.assertRaises(CodexOAuthError) as ctx:
            CodexOAuthService(client=client).exchange_code("code", "verifier")
        self.assertIn("bad code", str(ctx.exception))

    def test_refresh_preserves_existing_refresh_token(self) -> None:
        client = self._client(200, {"access_token": "at-2", "id_token": ""})
        bundle = CodexOAuthService(client=client).refresh_tokens("rt-keep")
        self.assertEqual(bundle.access_token, "at-2")
        self.assertEqual(bundle.refresh_token, "rt-keep")

    def test_refresh_requires_token(self) -> None:
        with self.assertRaises(CodexOAuthError):
            CodexOAuthService().refresh_tokens("")


def _response(status_code: int, body: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    return response


class TestDeviceCode(unittest.TestCase):
    def _service(self, *responses: MagicMock) -> tuple[CodexOAuthService, MagicMock]:
        client = MagicMock()
        client.post.side_effect = list(responses)
        return CodexOAuthService(client=client), client

    def test_request_device_code_posts_client_id_as_json(self) -> None:
        service, client = self._service(
            _response(
                200,
                {
                    "device_auth_id": "deviceauth_1",
                    "user_code": "ABCD-1234",
                    "interval": "5",
                    "expires_at": "2999-01-01T00:00:00+00:00",
                },
            )
        )
        device_code = service.request_device_code()
        url = client.post.call_args.args[0]
        self.assertTrue(url.endswith("/api/accounts/deviceauth/usercode"))
        self.assertEqual(client.post.call_args.kwargs["json"], {"client_id": service._client_id})
        self.assertEqual(device_code.device_auth_id, "deviceauth_1")
        self.assertEqual(device_code.user_code, "ABCD-1234")
        self.assertEqual(device_code.interval, 5)

    def test_device_code_expiry_is_capped_at_fifteen_minutes(self) -> None:
        service, _ = self._service(
            _response(
                200,
                {
                    "device_auth_id": "deviceauth_1",
                    "usercode": "ABCD-1234",
                    "expires_at": "2999-01-01T00:00:00+00:00",
                },
            )
        )
        device_code = service.request_device_code()
        expires_at = datetime.fromisoformat(device_code.expires_at)
        self.assertLessEqual(
            expires_at - datetime.now(timezone.utc),
            timedelta(seconds=DEVICE_CODE_TTL_SECONDS),
        )
        self.assertEqual(device_code.user_code, "ABCD-1234")
        self.assertEqual(device_code.interval, 5)

    def test_interval_is_clamped_and_defaults(self) -> None:
        self.assertEqual(_poll_interval_from("2"), 2)
        self.assertEqual(_poll_interval_from(0), 1)
        self.assertEqual(_poll_interval_from("600"), 30)
        self.assertEqual(_poll_interval_from(None), 5)

    def test_request_device_code_404_reads_as_unavailable(self) -> None:
        service, _ = self._service(_response(404, {}))
        with self.assertRaises(CodexOAuthError) as ctx:
            service.request_device_code()
        self.assertIn("redirect URL", str(ctx.exception))

    def test_poll_pending_returns_none(self) -> None:
        pending = {"error": {"code": "deviceauth_authorization_pending", "message": "pending"}}
        service, client = self._service(_response(403, pending), _response(404, {}))
        self.assertIsNone(service.poll_device_authorization("deviceauth_1", "ABCD-1234"))
        self.assertIsNone(service.poll_device_authorization("deviceauth_1", "ABCD-1234"))
        self.assertEqual(
            client.post.call_args.kwargs["json"],
            {"device_auth_id": "deviceauth_1", "user_code": "ABCD-1234"},
        )

    def test_poll_error_surfaces_nested_message(self) -> None:
        mismatch = {
            "error": {
                "code": "deviceauth_user_code_mismatch",
                "message": "Failed to process device authorization.",
            }
        }
        service, _ = self._service(_response(400, mismatch))
        with self.assertRaises(CodexOAuthError) as ctx:
            service.poll_device_authorization("deviceauth_1", "WRONG")
        self.assertIn("Failed to process device authorization", str(ctx.exception))

    def test_poll_approved_returns_grant(self) -> None:
        service, _ = self._service(
            _response(
                200,
                {
                    "authorization_code": "auth-code",
                    "code_challenge": "challenge",
                    "code_verifier": "verifier",
                },
            )
        )
        grant = service.poll_device_authorization("deviceauth_1", "ABCD-1234")
        self.assertEqual(grant, CodexDeviceGrant("auth-code", "verifier"))

    def test_exchange_device_code_uses_device_callback(self) -> None:
        id_token = _make_id_token({"https://api.openai.com/auth": {"chatgpt_account_id": "acct-d"}})
        service, client = self._service(
            _response(200, {"access_token": "at", "refresh_token": "rt", "id_token": id_token})
        )
        bundle = service.exchange_device_code(CodexDeviceGrant("auth-code", "verifier"))
        form = client.post.call_args.kwargs["data"]
        self.assertEqual(form["code"], "auth-code")
        self.assertEqual(form["code_verifier"], "verifier")
        self.assertEqual(form["redirect_uri"], service.device_redirect_uri)
        self.assertTrue(form["redirect_uri"].endswith("/deviceauth/callback"))
        self.assertEqual(bundle.account_id, "acct-d")

    def test_verification_url_is_codex_device_page(self) -> None:
        self.assertTrue(CodexOAuthService().device_verification_url.endswith("/codex/device"))


class TestDeviceEndpoints(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = MagicMock()
        self.user.id = "user-1"

    def _patched_service(self) -> tuple[object, MagicMock]:
        service = MagicMock()
        service.device_verification_url = "https://auth.openai.com/codex/device"
        service.request_device_code.return_value = CodexDeviceCode(
            device_auth_id="deviceauth_secret",
            user_code="ABCD-1234",
            interval=5,
            expires_at="2999-01-01T00:00:00+00:00",
        )
        return patch.object(codex_oauth, "CodexOAuthService", return_value=service), service

    async def test_start_then_pending_then_complete(self) -> None:
        patcher, service = self._patched_service()
        with patcher:
            started = await codex_oauth.device_start(current_user=self.user)
            self.assertEqual(started.user_code, "ABCD-1234")
            self.assertEqual(started.interval, 5)
            self.assertEqual(started.verification_url, "https://auth.openai.com/codex/device")

            service.poll_device_authorization.return_value = None
            pending = await codex_oauth.device_poll(
                codex_oauth.DevicePollRequest(state=started.state), current_user=self.user
            )
            self.assertEqual(pending.status, "pending")
            self.assertIsNone(pending.config)
            service.poll_device_authorization.assert_called_with("deviceauth_secret", "ABCD-1234")

            grant = CodexDeviceGrant("auth-code", "verifier")
            service.poll_device_authorization.return_value = grant
            service.exchange_device_code.return_value = CodexTokenBundle(
                access_token="at",
                refresh_token="rt",
                id_token="idt",
                account_id="acct-1",
                expires_at=None,
            )
            done = await codex_oauth.device_poll(
                codex_oauth.DevicePollRequest(state=started.state), current_user=self.user
            )
        self.assertEqual(done.status, "complete")
        self.assertEqual(done.account_id, "acct-1")
        self.assertEqual(done.config["auth_mode"], "chatgpt")
        self.assertEqual(done.config["refresh_token"], "rt")
        service.exchange_device_code.assert_called_once_with(grant)

    async def test_start_unavailable_is_bad_gateway(self) -> None:
        patcher, service = self._patched_service()
        service.request_device_code.side_effect = CodexOAuthError("not offered")
        with patcher, self.assertRaises(HTTPException) as ctx:
            await codex_oauth.device_start(current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_poll_provider_error_is_bad_request(self) -> None:
        patcher, service = self._patched_service()
        service.poll_device_authorization.side_effect = CodexOAuthError("denied")
        with patcher:
            started = await codex_oauth.device_start(current_user=self.user)
            with self.assertRaises(HTTPException) as ctx:
                await codex_oauth.device_poll(
                    codex_oauth.DevicePollRequest(state=started.state), current_user=self.user
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "denied")


class TestBundleHelpers(unittest.TestCase):
    def test_account_id_falls_back_to_top_level(self) -> None:
        token = _make_id_token({"account_id": "acct-top"})
        self.assertEqual(_account_id_from_id_token(token), "acct-top")

    def test_account_id_handles_garbage(self) -> None:
        self.assertEqual(_account_id_from_id_token("not-a-jwt"), "")

    def test_bundle_is_expired_true_for_past(self) -> None:
        self.assertTrue(bundle_is_expired("2000-01-01T00:00:00+00:00"))

    def test_bundle_is_expired_false_for_missing(self) -> None:
        self.assertFalse(bundle_is_expired(None))


class TestOAuthState(unittest.TestCase):
    def test_seal_open_roundtrip(self) -> None:
        state = codex_oauth._seal_state("user-1", "verifier-1")
        self.assertEqual(codex_oauth._open_state(state, "user-1"), "verifier-1")

    def test_open_rejects_wrong_user(self) -> None:
        state = codex_oauth._seal_state("user-1", "verifier-1")
        with self.assertRaises(HTTPException) as ctx:
            codex_oauth._open_state(state, "user-2")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_open_rejects_garbage(self) -> None:
        with self.assertRaises(HTTPException):
            codex_oauth._open_state("not-a-real-state", "user-1")


class TestCodexChatGptCredential(unittest.TestCase):
    def test_chatgpt_mode_requires_refresh_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.codex,
                {"auth_mode": "chatgpt", "access_token": "at"},
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("refresh_token", str(ctx.exception.detail))

    def test_chatgpt_mode_valid(self) -> None:
        validate_credential_config(
            CredentialType.codex,
            {"auth_mode": "chatgpt", "access_token": "at", "refresh_token": "rt"},
        )

    def test_merge_replaces_token_with_chatgpt_bundle(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.codex,
            {"access_token": "old-token", "auth_mode": "access_token"},
            {
                "auth_mode": "chatgpt",
                "access_token": "at",
                "refresh_token": "rt",
                "id_token": "idt",
                "account_id": "acct",
                "expires_at": "2999-01-01T00:00:00+00:00",
            },
        )
        self.assertEqual(merged["auth_mode"], "chatgpt")
        self.assertEqual(merged["refresh_token"], "rt")

    def test_merge_access_token_clears_chatgpt_fields(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.codex,
            {"auth_mode": "chatgpt", "access_token": "at", "refresh_token": "rt"},
            {"access_token": "new-token"},
        )
        self.assertEqual(merged["auth_mode"], "access_token")
        self.assertEqual(merged["access_token"], "new-token")
        self.assertNotIn("refresh_token", merged)


if __name__ == "__main__":
    unittest.main()
