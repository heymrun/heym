"""Instance admin identity and the /api/admin/sso surface."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.deps import require_instance_admin
from app.models.schemas import UserResponse
from app.services.instance_admin import is_instance_admin

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
