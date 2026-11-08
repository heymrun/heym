"""SSO hand-off to Heym Work: fixed redirect target, single-use code, no Heym cookies."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.sso_auth import (
    _TX_COOKIE,
    _decode_transaction,
    _encode_transaction,
    sso_callback,
    sso_login,
)

WORK_URL = "https://work.acme.example"
STATE = "w" * 24


class _Request:
    def __init__(self, cookies: dict[str, str] | None = None) -> None:
        self.headers: dict[str, str] = {}
        self.cookies = cookies or {}
        self.client = SimpleNamespace(host="203.0.113.7")
        self.url = SimpleNamespace(scheme="https")


def _work_row(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = dict(enabled=True, work_url=WORK_URL)
    base.update(overrides)
    return SimpleNamespace(**base)


def _sso_row() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        issuer="https://idp.acme.example",
        client_id="heym",
        encrypted_client_secret="enc",
        scopes="openid email profile",
    )


def _cookie_value(response: object, name: str) -> str:
    for header in response.headers.getlist("set-cookie"):
        if header.startswith(f"{name}="):
            return header.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"cookie {name} not set")


class WorkSsoLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_work_state_is_refused(self) -> None:
        response = await sso_login(_Request(), client="work", work_state="short", db=AsyncMock())

        self.assertEqual(response.status_code, 302)
        self.assertIn("sso_error=invalid_request", response.headers["location"])

    async def test_disabled_integration_is_refused(self) -> None:
        with patch(
            "app.api.sso_auth.get_work_integration",
            AsyncMock(return_value=_work_row(enabled=False)),
        ):
            response = await sso_login(_Request(), client="work", work_state=STATE, db=AsyncMock())

        self.assertTrue(response.headers["location"].startswith("/login?"))
        self.assertIn("sso_error=sso_disabled", response.headers["location"])

    async def test_work_transaction_carries_client_and_state(self) -> None:
        with (
            patch("app.api.sso_auth.login_limiter") as limiter,
            patch("app.api.sso_auth.get_work_integration", AsyncMock(return_value=_work_row())),
            patch("app.api.sso_auth.get_sso_settings", AsyncMock(return_value=_sso_row())),
            patch("app.api.sso_auth.decrypt_client_secret", MagicMock(return_value="secret")),
            patch("app.api.sso_auth.fetch_discovery", AsyncMock(return_value=SimpleNamespace())),
            patch(
                "app.api.sso_auth.build_authorization_url",
                MagicMock(return_value="https://idp/auth"),
            ),
            patch(
                "app.api.sso_auth.make_pkce_pair",
                MagicMock(return_value=("verifier", "challenge")),
            ),
            patch("app.api.sso_auth.callback_url", MagicMock(return_value="https://heym/cb")),
        ):
            limiter.is_allowed.return_value = (True, 0)
            response = await sso_login(_Request(), client="work", work_state=STATE, db=AsyncMock())

        transaction = _decode_transaction(_cookie_value(response, _TX_COOKIE))
        self.assertEqual(transaction["client"], "work")
        self.assertEqual(transaction["work_state"], STATE)
        self.assertEqual(response.headers["location"], "https://idp/auth")


class WorkSsoCallbackTests(unittest.IsolatedAsyncioTestCase):
    def _transaction(self) -> str:
        return _encode_transaction("st", "nonce", "verifier", "/", client="work", work_state=STATE)

    async def test_work_sign_in_redirects_to_the_registered_url_with_a_code(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), email="ada@acme.example", is_active=True)
        db = AsyncMock()
        request = _Request(cookies={_TX_COOKIE: self._transaction()})
        discovery = SimpleNamespace(issuer="https://idp.acme.example")
        with (
            patch("app.api.sso_auth.get_work_integration", AsyncMock(return_value=_work_row())),
            patch("app.api.sso_auth.get_sso_settings", AsyncMock(return_value=_sso_row())),
            patch("app.api.sso_auth.fetch_discovery", AsyncMock(return_value=discovery)),
            patch("app.api.sso_auth.exchange_code", AsyncMock(return_value={"id_token": "t"})),
            patch("app.api.sso_auth.get_signing_key", MagicMock(return_value="key")),
            patch(
                "app.api.sso_auth.verify_id_token",
                MagicMock(return_value={"email": "ada@acme.example"}),
            ),
            patch("app.api.sso_auth.decrypt_client_secret", MagicMock(return_value="secret")),
            patch("app.api.sso_auth.callback_url", MagicMock(return_value="https://heym/cb")),
            patch("app.api.sso_auth.resolve_sso_user", AsyncMock(return_value=user)),
            patch(
                "app.api.sso_auth.create_sso_code", AsyncMock(return_value="c" * 43)
            ) as create_code,
        ):
            response = await sso_callback(request, code="provider-code", state="st", db=db)

        location = response.headers["location"]
        self.assertTrue(location.startswith(f"{WORK_URL}/auth/callback?"))
        self.assertIn(f"code={'c' * 43}", location)
        self.assertIn(f"state={STATE}", location)
        cookies = " ".join(response.headers.getlist("set-cookie"))
        self.assertNotIn("access_token=", cookies)
        self.assertNotIn("refresh_token=", cookies)
        create_code.assert_awaited_once()
        db.commit.assert_awaited()

    async def test_work_failure_returns_to_the_work_login(self) -> None:
        request = _Request(cookies={_TX_COOKIE: self._transaction()})
        with patch("app.api.sso_auth.get_work_integration", AsyncMock(return_value=_work_row())):
            response = await sso_callback(request, code="x", state="wrong-state", db=AsyncMock())

        self.assertTrue(
            response.headers["location"].startswith(f"{WORK_URL}/login?sso_error=state_mismatch")
        )
