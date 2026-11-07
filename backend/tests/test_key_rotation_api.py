"""Unreadable credentials for their owners, and the admin key-rotation endpoints (#862)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api import admin_key_rotation
from app.api.credentials import display_config
from app.db.models import CredentialType
from app.services import encryption, key_rotation


def _keys(primary: str, extra: str = ""):  # noqa: ANN202 - context manager helper
    return patch.multiple(encryption.settings, encryption_key=primary, encryption_keys_extra=extra)


def _credential(token: str, source: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(type=CredentialType.openai, encrypted_config=token, source=source)


class DisplayConfigTests(TestCase):
    def test_a_readable_row_is_masked_as_before(self) -> None:
        with _keys("k1"):
            token = encryption.encrypt_config({"api_key": "sk-abcdefghij"})
            config, masked, unreadable = display_config(_credential(token))
        self.assertEqual(config, {"api_key": "sk-abcdefghij"})
        self.assertTrue(masked.startswith("sk-abcd"))
        self.assertFalse(unreadable)

    def test_a_row_under_an_extra_key_is_readable(self) -> None:
        with _keys("old"):
            token = encryption.encrypt_config({"api_key": "sk-abcdefghij"})
        with _keys("new", "old"):
            self.assertFalse(display_config(_credential(token))[2])

    def test_a_row_no_key_reads_lists_as_unreadable_instead_of_failing(self) -> None:
        with _keys("lost"):
            token = encryption.encrypt_config({"api_key": "sk-abcdefghij"})
        with _keys("new", "old"):
            self.assertEqual(display_config(_credential(token)), ({}, None, True))


class AdminEndpointTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.admin = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")

    async def test_non_admins_are_refused(self) -> None:
        denied = HTTPException(status_code=403, detail="Admin only")
        with (
            patch.object(admin_key_rotation, "require_instance_admin", side_effect=denied),
            self.assertRaises(HTTPException) as caught,
        ):
            await admin_key_rotation.start_key_rotation(current_user=self.admin, db=AsyncMock())
        self.assertEqual(caught.exception.status_code, 403)

    async def test_a_refused_start_is_a_409_with_the_reason_and_is_audited(self) -> None:
        refused = key_rotation.RotationRefusedError("w1 still encrypt with another key")
        with (
            patch.object(admin_key_rotation, "require_instance_admin"),
            patch.object(admin_key_rotation.registry, "list_instances", AsyncMock(return_value=[])),
            patch.object(
                admin_key_rotation.key_rotation, "start_rotation", AsyncMock(side_effect=refused)
            ),
            patch.object(admin_key_rotation, "audit") as audit,
            self.assertRaises(HTTPException) as caught,
        ):
            await admin_key_rotation.start_key_rotation(current_user=self.admin, db=AsyncMock())
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("w1", caught.exception.detail)
        self.assertEqual(audit.call_args.kwargs["outcome"], "denied")

    async def test_a_start_is_audited_with_the_keys_by_fingerprint(self) -> None:
        rotation = SimpleNamespace(
            id=uuid.uuid4(), target_fingerprint="n" * 16, retired_fingerprints=["o" * 16]
        )
        with (
            patch.object(admin_key_rotation, "require_instance_admin"),
            patch.object(admin_key_rotation.registry, "list_instances", AsyncMock(return_value=[])),
            patch.object(
                admin_key_rotation.key_rotation,
                "start_rotation",
                AsyncMock(return_value=rotation),
            ),
            patch.object(admin_key_rotation, "_status", AsyncMock(return_value="status")),
            patch.object(admin_key_rotation, "audit") as audit,
        ):
            result = await admin_key_rotation.start_key_rotation(
                current_user=self.admin, db=AsyncMock()
            )
        self.assertEqual(result, "status")
        kwargs = audit.call_args.kwargs
        self.assertEqual(kwargs["action"], "encryption_key.rotation_start")
        self.assertEqual(kwargs["target_fingerprint"], "n" * 16)
        self.assertEqual(kwargs["retired_fingerprints"], ["o" * 16])
