import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    get_public_credential_fields,
    merge_credential_config_for_update,
    update_credential,
    validate_credential_config,
)
from app.db.models import CredentialType
from app.models.schemas import CredentialUpdate


class CalTriggerCredentialTests(unittest.TestCase):
    def test_validate_requires_webhook_secret(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(CredentialType.cal_trigger, {})
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("webhook_secret", context.exception.detail)

    def test_validate_accepts_webhook_secret(self) -> None:
        validate_credential_config(
            CredentialType.cal_trigger,
            {"webhook_secret": "strong-shared-secret"},
        )

    def test_masked_value_hides_webhook_secret(self) -> None:
        secret = "strong-shared-secret"
        masked = get_masked_value(
            CredentialType.cal_trigger,
            {"webhook_secret": secret},
        )
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, secret)


class CalApiCredentialTests(unittest.TestCase):
    def test_validate_requires_api_key_and_http_base_url(self) -> None:
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.cal_api, {})
        with self.assertRaises(HTTPException):
            validate_credential_config(
                CredentialType.cal_api,
                {"api_key": "key", "base_url": "file:///tmp/cal"},
            )

    def test_public_fields_expose_base_url_but_not_api_key(self) -> None:
        config = {"api_key": "secret", "base_url": "https://cal.example.test"}
        validate_credential_config(CredentialType.cal_api, config)

        public_fields = get_public_credential_fields(CredentialType.cal_api, config)

        self.assertEqual(public_fields, {"base_url": "https://cal.example.test"})
        self.assertNotIn("secret", get_masked_value(CredentialType.cal_api, config) or "")

    def test_update_preserves_api_key_when_secret_field_is_blank(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.cal_api,
            {"api_key": "existing", "base_url": "https://api.cal.com"},
            {"api_key": "", "base_url": "https://cal.example.test"},
        )

        self.assertEqual(
            merged,
            {"api_key": "existing", "base_url": "https://cal.example.test"},
        )


class CalApiCredentialUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_changes_are_allowed_without_trigger_subscriptions(self) -> None:
        credential_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        credential = SimpleNamespace(
            id=credential_id,
            owner_id=uuid.uuid4(),
            name="Cal API",
            type=CredentialType.cal_api,
            encrypted_config="encrypted",
            created_at=now,
            updated_at=now,
        )
        credential_result = MagicMock()
        credential_result.scalar_one_or_none.return_value = credential
        db = MagicMock()
        db.execute = AsyncMock(return_value=credential_result)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch(
            "app.api.credentials.decrypt_config",
            return_value={"api_key": "old-key", "base_url": "https://api.cal.com"},
        ):
            result = await update_credential(
                credential_id,
                CredentialUpdate(config={"api_key": "new-key", "base_url": "https://api.cal.com"}),
                current_user=SimpleNamespace(id=credential.owner_id),
                db=db,
            )

        self.assertEqual(result.id, credential_id)
        db.flush.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
