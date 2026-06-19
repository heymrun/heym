import unittest

from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType


class GitHubCredentialTests(unittest.TestCase):
    def test_validate_requires_api_key(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.github, {})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("api_key", ctx.exception.detail)

    def test_validate_passes_with_api_key(self) -> None:
        validate_credential_config(CredentialType.github, {"api_key": "github_pat_123"})

    def test_validate_accepts_ghe_base_url(self) -> None:
        validate_credential_config(
            CredentialType.github,
            {
                "api_key": "github_pat_123",
                "base_url": "https://github.example.com/api/v3",
            },
        )

    def test_validate_rejects_invalid_ghe_base_url(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.github,
                {
                    "api_key": "github_pat_123",
                    "base_url": "github.example.com/api/v3",
                },
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("base_url", ctx.exception.detail)

    def test_masked_value_hides_api_key(self) -> None:
        masked = get_masked_value(CredentialType.github, {"api_key": "github_pat_1234567890"})
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, "github_pat_1234567890")

    def test_update_merge_preserves_existing_ghe_base_url_when_omitted(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.github,
            {
                "api_key": "github_pat_old",
                "base_url": "https://github.example.com/api/v3",
            },
            {
                "api_key": "github_pat_new",
            },
        )

        self.assertEqual(merged["api_key"], "github_pat_new")
        self.assertEqual(merged["base_url"], "https://github.example.com/api/v3")

    def test_update_merge_preserves_existing_api_key_when_only_base_url_changes(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.github,
            {
                "api_key": "github_pat_old",
                "base_url": "https://github.example.com/api/v3",
            },
            {
                "api_key": "",
                "base_url": "https://github2.example.com/api/v3",
            },
        )

        self.assertEqual(merged["api_key"], "github_pat_old")
        self.assertEqual(merged["base_url"], "https://github2.example.com/api/v3")
