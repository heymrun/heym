import unittest

from fastapi import HTTPException

from app.api.credentials import get_masked_value, validate_credential_config
from app.db.models import CredentialType


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


if __name__ == "__main__":
    unittest.main()
