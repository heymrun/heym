"""SSO security invariants: credentials at rest, and both password surfaces."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.auth import login, register
from app.models.schemas import UserCreate, UserLogin
from app.services.auth import hash_password, verify_password
from app.services.sso_settings import encrypt_client_secret, password_login_blocked

_ADMINS = "app.services.instance_admin.settings.admin_emails"


class NullPasswordHashTests(unittest.TestCase):
    def test_none_hash_returns_false_instead_of_raising(self) -> None:
        """SSO-provisioned users have no password; bcrypt raises on an empty salt."""
        self.assertFalse(verify_password("anything", None))

    def test_empty_hash_returns_false_instead_of_raising(self) -> None:
        self.assertFalse(verify_password("anything", ""))

    def test_real_hash_still_verifies(self) -> None:
        self.assertTrue(verify_password("hunter2", hash_password("hunter2")))
        self.assertFalse(verify_password("hunter3", hash_password("hunter2")))


def _row(**overrides: object) -> SimpleNamespace:
    base = dict(
        enabled=True,
        issuer="https://idp.example",
        client_id="heym",
        password_login_disabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class PasswordLoginGateTests(unittest.TestCase):
    def test_blocked_when_disabled_and_sso_is_live(self) -> None:
        with patch(_ADMINS, "grace@heym.local"):
            self.assertTrue(password_login_blocked(_row(), "ada@heym.local"))

    def test_break_glass_admin_is_never_blocked(self) -> None:
        """Whoever can edit the env file can already recover the instance; say so in code."""
        with patch(_ADMINS, "grace@heym.local"):
            self.assertFalse(password_login_blocked(_row(), "GRACE@heym.local"))

    def test_not_blocked_when_the_toggle_is_off(self) -> None:
        with patch(_ADMINS, ""):
            self.assertFalse(password_login_blocked(_row(password_login_disabled=False), "ada@x"))

    def test_not_blocked_when_sso_is_disabled(self) -> None:
        """A stale toggle on a disabled provider must not lock everyone out."""
        with patch(_ADMINS, ""):
            self.assertFalse(password_login_blocked(_row(enabled=False), "ada@heym.local"))

    def test_not_blocked_when_the_issuer_is_blank(self) -> None:
        with patch(_ADMINS, ""):
            self.assertFalse(password_login_blocked(_row(issuer=""), "ada@heym.local"))


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Request:
    client = SimpleNamespace(host="203.0.113.7")
    headers: dict[str, str] = {}


class LoginEndpointGateTests(unittest.IsolatedAsyncioTestCase):
    """The gate is only worth having if the endpoint actually consults it."""

    async def _login(self, email: str, sso_row: SimpleNamespace) -> object:
        user = SimpleNamespace(
            id=uuid.uuid4(), email=email, name="Test", hashed_password=hash_password("hunter2")
        )
        db = AsyncMock()
        db.execute.return_value = _ScalarResult(user)
        with (
            patch("app.api.auth.get_sso_settings", AsyncMock(return_value=sso_row)),
            patch("app.api.auth.login_limiter") as limiter,
            patch("app.api.auth.store_refresh_token", AsyncMock()),
        ):
            limiter.is_allowed.return_value = (True, 0)
            return await login(
                UserLogin(email=email, password="hunter2"),
                _Request(),
                SimpleNamespace(set_cookie=lambda **_: None),
                db=db,
            )

    async def test_password_login_is_refused_when_disabled(self) -> None:
        with patch(_ADMINS, "grace@heym.example"):
            with self.assertRaises(HTTPException) as ctx:
                await self._login("ada@heym.example", _row())

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_break_glass_admin_still_gets_a_token(self) -> None:
        with patch(_ADMINS, "grace@heym.example"):
            result = await self._login("grace@heym.example", _row())

        self.assertTrue(result.access_token)

    async def test_normal_user_still_gets_a_token_when_the_toggle_is_off(self) -> None:
        with patch(_ADMINS, ""):
            result = await self._login("ada@heym.example", _row(password_login_disabled=False))

        self.assertTrue(result.access_token)


class ClientSecretAtRestTests(unittest.TestCase):
    def test_the_stored_column_never_holds_the_plaintext(self) -> None:
        """A database reader must not walk away with a working client secret."""
        stored = encrypt_client_secret("heym-local-secret-change-me")

        self.assertNotIn("heym-local-secret-change-me", stored)
        self.assertNotIn("heym-local-secret", stored)


class RegisterEndpointGateTests(unittest.IsolatedAsyncioTestCase):
    """Registration mints a password, so the same gate has to cover it."""

    async def _register(self, email: str, sso_row: SimpleNamespace) -> object:
        db = AsyncMock()
        db.execute.return_value = _ScalarResult(None)
        with (
            patch("app.api.auth.get_sso_settings", AsyncMock(return_value=sso_row)),
            patch("app.api.auth.register_limiter") as limiter,
            patch("app.api.auth.store_refresh_token", AsyncMock()),
        ):
            limiter.is_allowed.return_value = (True, 0)
            return await register(
                UserCreate(email=email, password="Passw0rd!x", name="Test"),
                _Request(),
                SimpleNamespace(set_cookie=lambda **_: None),
                db=db,
            )

    async def test_registration_is_refused_when_password_login_is_disabled(self) -> None:
        with patch(_ADMINS, "grace@heym.example"):
            with self.assertRaises(HTTPException) as ctx:
                await self._register("newcomer@heym.example", _row())

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_an_admin_may_still_bootstrap_a_break_glass_account(self) -> None:
        with patch(_ADMINS, "grace@heym.example"):
            result = await self._register("grace@heym.example", _row())

        self.assertTrue(result.access_token)

    async def test_registration_is_open_when_the_toggle_is_off(self) -> None:
        with patch(_ADMINS, ""):
            result = await self._register(
                "newcomer@heym.example", _row(password_login_disabled=False)
            )

        self.assertTrue(result.access_token)
