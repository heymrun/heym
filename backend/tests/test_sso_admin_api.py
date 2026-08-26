"""Instance admin identity and the /api/admin/sso surface."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.deps import require_instance_admin
from app.api.sso_admin import apply_settings_update
from app.models.schemas import SsoSettingsResponse, SsoSettingsUpdate, UserResponse
from app.services.instance_admin import is_instance_admin
from app.services.sso_settings import decrypt_client_secret, encrypt_client_secret

_ADMINS = "app.services.instance_admin.settings.admin_emails"


def _user(email: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), email=email, name="Test")


class InstanceAdminTests(unittest.TestCase):
    def test_listed_email_is_admin_case_insensitively(self) -> None:
        with patch(_ADMINS, " Ada@Heym.local , grace@heym.local "):
            self.assertTrue(is_instance_admin(_user("ada@heym.local")))
            self.assertTrue(is_instance_admin(_user("GRACE@HEYM.LOCAL")))

    def test_unlisted_email_is_not_admin(self) -> None:
        with patch(_ADMINS, "ada@heym.local"):
            self.assertFalse(is_instance_admin(_user("mallory@heym.local")))

    def test_empty_allowlist_grants_nobody(self) -> None:
        """An unset allowlist must not mean 'everyone', which would open the config to all."""
        with patch(_ADMINS, ""):
            self.assertFalse(is_instance_admin(_user("ada@heym.local")))

    def test_require_instance_admin_raises_403_for_non_admin(self) -> None:
        with patch(_ADMINS, "ada@heym.local"):
            with self.assertRaises(HTTPException) as ctx:
                require_instance_admin(_user("mallory@heym.local"))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_require_instance_admin_passes_for_admin(self) -> None:
        with patch(_ADMINS, "ada@heym.local"):
            self.assertIsNone(require_instance_admin(_user("ada@heym.local")))


class UserResponseAdminFlagTests(unittest.TestCase):
    def test_flag_is_derived_from_the_allowlist(self) -> None:
        """A computed field cannot be forgotten by a serializer that builds the payload."""
        row = SimpleNamespace(
            id=uuid.uuid4(),
            email="ada@heym.local",
            name="Ada",
            user_rules=None,
            tts_credential_id=None,
            tts_voice_id=None,
            preferred_credential_id=None,
            preferred_model=None,
            created_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )

        with patch(_ADMINS, "ada@heym.local"):
            self.assertTrue(UserResponse.model_validate(row).is_admin)
        with patch(_ADMINS, "grace@heym.local"):
            self.assertFalse(UserResponse.model_validate(row).is_admin)

    def test_flag_is_present_in_the_serialized_payload(self) -> None:
        row = SimpleNamespace(
            id=uuid.uuid4(),
            email="ada@heym.local",
            name="Ada",
            user_rules=None,
            tts_credential_id=None,
            tts_voice_id=None,
            preferred_credential_id=None,
            preferred_model=None,
            created_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )

        with patch(_ADMINS, "ada@heym.local"):
            self.assertIs(UserResponse.model_validate(row).model_dump()["is_admin"], True)


class _Row(SimpleNamespace):
    pass


def _row(**overrides: object) -> _Row:
    base = dict(
        enabled=False,
        issuer="",
        client_id="",
        encrypted_client_secret=None,
        scopes="openid email profile",
        button_label="Sign in with SSO",
        auto_provision_users=True,
        allowed_email_domains="",
        password_login_disabled=False,
        last_test_ok=False,
        last_test_at=None,
        updated_by_id=None,
    )
    base.update(overrides)
    return _Row(**base)


class SettingsUpdateTests(unittest.TestCase):
    def test_a_supplied_secret_is_stored_encrypted(self) -> None:
        row = _row()

        apply_settings_update(row, SsoSettingsUpdate(client_secret="top-secret"))

        self.assertNotIn("top-secret", row.encrypted_client_secret)
        self.assertEqual(decrypt_client_secret(row.encrypted_client_secret), "top-secret")

    def test_an_empty_secret_preserves_the_stored_one(self) -> None:
        """The masked editor field posts back empty; it must not erase the real secret."""
        row = _row(encrypted_client_secret=encrypt_client_secret("original"))

        apply_settings_update(row, SsoSettingsUpdate(client_secret=""))

        self.assertEqual(decrypt_client_secret(row.encrypted_client_secret), "original")

    def test_changing_the_issuer_invalidates_the_recorded_test(self) -> None:
        """A passing test result must not license the new issuer."""
        row = _row(issuer="https://old.example", last_test_ok=True)

        apply_settings_update(row, SsoSettingsUpdate(issuer="https://new.example"))

        self.assertFalse(row.last_test_ok)

    def test_password_login_cannot_be_disabled_before_a_passing_test(self) -> None:
        row = _row(enabled=True, last_test_ok=False)

        with self.assertRaises(HTTPException) as ctx:
            apply_settings_update(row, SsoSettingsUpdate(password_login_disabled=True))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_password_login_cannot_be_disabled_while_sso_is_off(self) -> None:
        row = _row(enabled=False, last_test_ok=True)

        with self.assertRaises(HTTPException):
            apply_settings_update(row, SsoSettingsUpdate(password_login_disabled=True))

    def test_password_login_may_be_disabled_once_sso_is_enabled_and_tested(self) -> None:
        row = _row(enabled=True, last_test_ok=True)

        apply_settings_update(row, SsoSettingsUpdate(password_login_disabled=True))

        self.assertTrue(row.password_login_disabled)


class SettingsResponseTests(unittest.TestCase):
    def test_response_reports_the_secret_without_revealing_it(self) -> None:
        row = _row(issuer="https://idp.example", encrypted_client_secret=encrypt_client_secret("s"))

        payload = SsoSettingsResponse.from_row(row, redirect_uri="http://localhost:4017/cb")

        self.assertTrue(payload.client_secret_set)
        self.assertNotIn("client_secret", payload.model_dump())
        self.assertEqual(payload.redirect_uri, "http://localhost:4017/cb")

    def test_absent_secret_reports_false(self) -> None:
        payload = SsoSettingsResponse.from_row(_row(), redirect_uri="http://localhost:4017/cb")

        self.assertFalse(payload.client_secret_set)


class BreakGlassGuardTests(unittest.TestCase):
    """An exemption nobody can use is not an exemption."""

    def test_disabling_is_refused_when_no_admin_has_a_password(self) -> None:
        row = _row(enabled=True, last_test_ok=True)

        with self.assertRaises(HTTPException) as ctx:
            apply_settings_update(
                row, SsoSettingsUpdate(password_login_disabled=True), break_glass_ready=False
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("HEYM_ADMIN_EMAILS", ctx.exception.detail)
        self.assertFalse(row.password_login_disabled)

    def test_disabling_is_allowed_once_an_admin_has_a_password(self) -> None:
        row = _row(enabled=True, last_test_ok=True)

        apply_settings_update(
            row, SsoSettingsUpdate(password_login_disabled=True), break_glass_ready=True
        )

        self.assertTrue(row.password_login_disabled)

    def test_re_enabling_password_login_is_never_blocked(self) -> None:
        """Recovering must not need the very thing that is missing."""
        row = _row(enabled=True, last_test_ok=True, password_login_disabled=True)

        apply_settings_update(
            row, SsoSettingsUpdate(password_login_disabled=False), break_glass_ready=False
        )

        self.assertFalse(row.password_login_disabled)


class TestConnectionRecordingTests(unittest.TestCase):
    def test_response_reports_break_glass_readiness(self) -> None:
        ready = SsoSettingsResponse.from_row(
            _row(), redirect_uri="http://localhost:4017/cb", break_glass_ready=True
        )
        blocked = SsoSettingsResponse.from_row(
            _row(), redirect_uri="http://localhost:4017/cb", break_glass_ready=False
        )

        self.assertTrue(ready.break_glass_ready)
        self.assertFalse(blocked.break_glass_ready)
