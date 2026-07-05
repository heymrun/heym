import base64
import json
import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.api import codex_oauth
from app.api.credentials import merge_credential_config_for_update, validate_credential_config
from app.db.models import CredentialType
from app.services.codex_oauth_service import (
    CodexOAuthError,
    CodexOAuthService,
    _account_id_from_id_token,
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
