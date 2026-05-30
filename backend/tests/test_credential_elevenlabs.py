import unittest

from fastapi import HTTPException

from app.api.credentials import get_masked_value, validate_credential_config
from app.db.models import CredentialType


class ElevenLabsCredentialTests(unittest.TestCase):
    def test_validate_requires_api_key(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.elevenlabs, {})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_passes_with_api_key(self) -> None:
        validate_credential_config(CredentialType.elevenlabs, {"api_key": "sk_test_123"})

    def test_masked_value_hides_api_key(self) -> None:
        masked = get_masked_value(CredentialType.elevenlabs, {"api_key": "sk_test_1234567890"})
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, "sk_test_1234567890")
