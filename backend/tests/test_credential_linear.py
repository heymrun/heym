import unittest

from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType


class LinearCredentialTests(unittest.TestCase):
    def test_validate_requires_api_key(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(CredentialType.linear, {})
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("api_key", context.exception.detail)

    def test_masked_value_hides_api_key(self) -> None:
        masked = get_masked_value(CredentialType.linear, {"api_key": "lin_api_secret"})
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, "lin_api_secret")

    def test_update_preserves_existing_api_key_when_form_is_blank(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.linear,
            {"api_key": "lin_api_old"},
            {"api_key": ""},
        )
        self.assertEqual(merged["api_key"], "lin_api_old")
