"""SSO login initiation, callback state handling, and account resolution."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.sso_auth import SsoLoginError, resolve_sso_user, safe_next_path


class NextPathTests(unittest.TestCase):
    def test_a_relative_path_is_kept(self) -> None:
        self.assertEqual(safe_next_path("/workflows/42"), "/workflows/42")

    def test_an_absolute_url_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path("https://evil.example/phish"), "/")

    def test_a_protocol_relative_url_falls_back_to_root(self) -> None:
        """//evil.example is a URL, not a path; browsers follow it off-site."""
        self.assertEqual(safe_next_path("//evil.example"), "/")

    def test_a_backslash_variant_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path("/\\evil.example"), "/")

    def test_a_path_without_a_leading_slash_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path("workflows"), "/")

    def test_none_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path(None), "/")


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _settings_row(**overrides: object) -> SimpleNamespace:
    base = dict(auto_provision_users=True, allowed_email_domains="")
    base.update(overrides)
    return SimpleNamespace(**base)


def _db(*results: object) -> AsyncMock:
    db = AsyncMock()
    db.execute.side_effect = [_ScalarResult(r) for r in results]
    return db


_CLAIMS = {
    "sub": "ada-subject",
    "email": "ada@heym.local",
    "email_verified": True,
    "name": "Ada",
}
_ISSUER = "https://idp.example/realms/heym"


class AccountResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_subject_match_wins_and_skips_the_email_lookup(self) -> None:
        existing = SimpleNamespace(
            id=uuid.uuid4(),
            email="renamed@heym.local",
            sso_issuer=_ISSUER,
            sso_subject="ada-subject",
        )
        db = _db(existing)

        user = await resolve_sso_user(db, _settings_row(), _ISSUER, _CLAIMS)

        self.assertIs(user, existing)
        self.assertEqual(db.execute.await_count, 1)

    async def test_verified_email_claims_an_existing_account(self) -> None:
        existing = SimpleNamespace(
            id=uuid.uuid4(), email="ada@heym.local", sso_issuer=None, sso_subject=None
        )
        db = _db(None, existing)

        user = await resolve_sso_user(db, _settings_row(), _ISSUER, _CLAIMS)

        self.assertIs(user, existing)
        self.assertEqual(user.sso_issuer, _ISSUER)
        self.assertEqual(user.sso_subject, "ada-subject")

    async def test_unverified_email_is_rejected(self) -> None:
        db = _db(None)

        with self.assertRaises(SsoLoginError) as ctx:
            await resolve_sso_user(
                db, _settings_row(), _ISSUER, dict(_CLAIMS, email_verified=False)
            )

        self.assertEqual(ctx.exception.code, "email_not_verified")

    async def test_absent_email_verified_claim_is_rejected(self) -> None:
        db = _db(None)
        claims = {k: v for k, v in _CLAIMS.items() if k != "email_verified"}

        with self.assertRaises(SsoLoginError) as ctx:
            await resolve_sso_user(db, _settings_row(), _ISSUER, claims)

        self.assertEqual(ctx.exception.code, "email_not_verified")

    async def test_missing_email_is_rejected(self) -> None:
        db = _db(None)

        with self.assertRaises(SsoLoginError) as ctx:
            await resolve_sso_user(db, _settings_row(), _ISSUER, dict(_CLAIMS, email=""))

        self.assertEqual(ctx.exception.code, "email_missing")

    async def test_disallowed_domain_is_rejected(self) -> None:
        db = _db(None)
        row = _settings_row(allowed_email_domains="corp.example")

        with self.assertRaises(SsoLoginError) as ctx:
            await resolve_sso_user(db, row, _ISSUER, _CLAIMS)

        self.assertEqual(ctx.exception.code, "domain_not_allowed")

    async def test_unknown_email_is_provisioned_when_enabled(self) -> None:
        db = _db(None, None)

        user = await resolve_sso_user(db, _settings_row(), _ISSUER, _CLAIMS)

        self.assertEqual(user.email, "ada@heym.local")
        self.assertEqual(user.name, "Ada")
        self.assertIsNone(user.hashed_password)
        self.assertEqual(user.sso_subject, "ada-subject")
        db.add.assert_called_once()

    async def test_unknown_email_is_rejected_when_provisioning_is_off(self) -> None:
        db = _db(None, None)

        with self.assertRaises(SsoLoginError) as ctx:
            await resolve_sso_user(db, _settings_row(auto_provision_users=False), _ISSUER, _CLAIMS)

        self.assertEqual(ctx.exception.code, "provisioning_disabled")
        db.add.assert_not_called()
