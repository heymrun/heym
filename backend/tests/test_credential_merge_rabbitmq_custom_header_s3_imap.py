"""Regression tests for credential update, public fields, and masked values for
custom, header, rabbitmq, and imap credentials.

Extends the pattern from issue #631 (PR #636) and issue #643 (PR #654).
Previously, merge_credential_config_for_update had no branch for custom, header,
rabbitmq, or imap, so updating a credential from the UI (where secret fields
are kept blank) wiped out the stored secret keys and caused HTTP 400 validation failures.
"""

import unittest

from app.api.credentials import (
    get_masked_value,
    get_public_credential_fields,
    merge_credential_config_for_update,
)
from app.db.models import CredentialType


class TestCustomCredentialMerge(unittest.TestCase):
    def test_editing_base_url_only_keeps_the_stored_api_key(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.custom,
            {"api_key": "original-secret-key", "base_url": "https://api.example.com/v1"},
            {"api_key": "", "base_url": "https://newapi.example.com/v1"},
        )
        self.assertEqual(merged["api_key"], "original-secret-key")
        self.assertEqual(merged["base_url"], "https://newapi.example.com/v1")

    def test_editing_api_key_only_keeps_the_stored_base_url(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.custom,
            {"api_key": "original-secret-key", "base_url": "https://api.example.com/v1"},
            {"api_key": "new-secret-key"},
        )
        self.assertEqual(merged["api_key"], "new-secret-key")
        self.assertEqual(merged["base_url"], "https://api.example.com/v1")

    def test_blank_base_url_sent_explicitly_keeps_stored_base_url(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.custom,
            {"api_key": "original-secret-key", "base_url": "https://api.example.com/v1"},
            {"api_key": "new-secret-key", "base_url": ""},
        )
        self.assertEqual(merged["base_url"], "https://api.example.com/v1")


class TestCustomCredentialPublicFieldsAndMasking(unittest.TestCase):
    def test_public_fields_returns_base_url_only(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.custom,
            {"api_key": "secret-12345", "base_url": "https://api.example.com/v1"},
        )
        self.assertEqual(fields, {"base_url": "https://api.example.com/v1"})
        self.assertNotIn("api_key", fields)

    def test_masked_value_masks_api_key(self) -> None:
        masked = get_masked_value(
            CredentialType.custom,
            {"api_key": "sk-1234567890abcdef", "base_url": "https://api.example.com"},
        )
        self.assertEqual(masked, "sk-1234**")


class TestHeaderCredentialMerge(unittest.TestCase):
    def test_blank_header_value_keeps_stored_value(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.header,
            {"header_key": "X-API-Key", "header_value": "super-secret-token"},
            {"header_key": "X-Auth-Token", "header_value": ""},
        )
        self.assertEqual(merged["header_key"], "X-Auth-Token")
        self.assertEqual(merged["header_value"], "super-secret-token")

    def test_non_blank_header_value_overwrites(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.header,
            {"header_key": "X-API-Key", "header_value": "super-secret-token"},
            {"header_value": "rotated-secret-token"},
        )
        self.assertEqual(merged["header_key"], "X-API-Key")
        self.assertEqual(merged["header_value"], "rotated-secret-token")


class TestHeaderCredentialPublicFieldsAndMasking(unittest.TestCase):
    def test_public_fields_returns_header_key_only(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.header,
            {"header_key": "Authorization", "header_value": "Bearer secret"},
        )
        self.assertEqual(fields, {"header_key": "Authorization"})
        self.assertNotIn("header_value", fields)

    def test_masked_value_masks_header_value(self) -> None:
        masked = get_masked_value(
            CredentialType.header,
            {"header_key": "Authorization", "header_value": "my-secret-key-12345"},
        )
        self.assertEqual(masked, "my-secr**")


class TestRabbitMQCredentialMerge(unittest.TestCase):
    def _full_config(self) -> dict:
        return {
            "rabbitmq_host": "amqp.example.com",
            "rabbitmq_port": "5672",
            "rabbitmq_username": "app_user",
            "rabbitmq_password": "stored_rabbitmq_password",
            "rabbitmq_vhost": "/production",
        }

    def test_partial_update_keeps_all_other_fields(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.rabbitmq,
            self._full_config(),
            {"rabbitmq_host": "amqp2.example.com", "rabbitmq_password": ""},
        )
        self.assertEqual(merged["rabbitmq_host"], "amqp2.example.com")
        self.assertEqual(merged["rabbitmq_port"], "5672")
        self.assertEqual(merged["rabbitmq_username"], "app_user")
        self.assertEqual(merged["rabbitmq_password"], "stored_rabbitmq_password")
        self.assertEqual(merged["rabbitmq_vhost"], "/production")

    def test_non_blank_password_overwrites(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.rabbitmq,
            self._full_config(),
            {"rabbitmq_password": "new_rabbitmq_password"},
        )
        self.assertEqual(merged["rabbitmq_password"], "new_rabbitmq_password")
        self.assertEqual(merged["rabbitmq_host"], "amqp.example.com")


class TestRabbitMQCredentialPublicFieldsAndMasking(unittest.TestCase):
    def test_public_fields_excludes_password(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.rabbitmq,
            {
                "rabbitmq_host": "amqp.example.com",
                "rabbitmq_port": "5672",
                "rabbitmq_username": "guest",
                "rabbitmq_password": "secret_password",
                "rabbitmq_vhost": "/",
            },
        )
        self.assertEqual(
            fields,
            {
                "rabbitmq_host": "amqp.example.com",
                "rabbitmq_port": "5672",
                "rabbitmq_username": "guest",
                "rabbitmq_vhost": "/",
            },
        )
        self.assertNotIn("rabbitmq_password", fields)

    def test_masked_value_formats_user_and_host(self) -> None:
        masked = get_masked_value(
            CredentialType.rabbitmq,
            {
                "rabbitmq_host": "amqp.example.com",
                "rabbitmq_username": "heym_worker",
                "rabbitmq_password": "secret",
            },
        )
        self.assertEqual(masked, "heym_worker@amqp.example.com")


class TestImapCredentialMerge(unittest.TestCase):
    def _full_config(self) -> dict:
        return {
            "imap_host": "imap.example.com",
            "imap_port": "993",
            "imap_username": "user@example.com",
            "imap_password": "original_imap_password",
            "imap_mailbox": "INBOX",
            "imap_use_ssl": True,
        }

    def test_editing_mailbox_keeps_password_and_other_fields(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.imap,
            self._full_config(),
            {"imap_mailbox": "Archived", "imap_password": ""},
        )
        self.assertEqual(merged["imap_mailbox"], "Archived")
        self.assertEqual(merged["imap_password"], "original_imap_password")
        self.assertEqual(merged["imap_host"], "imap.example.com")
        self.assertEqual(merged["imap_port"], "993")
        self.assertEqual(merged["imap_username"], "user@example.com")
        self.assertEqual(merged["imap_use_ssl"], True)

    def test_rotating_password_overwrites(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.imap,
            self._full_config(),
            {"imap_password": "new_imap_password"},
        )
        self.assertEqual(merged["imap_password"], "new_imap_password")


class TestImapCredentialPublicFieldsAndMasking(unittest.TestCase):
    def test_public_fields_excludes_password(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.imap,
            {
                "imap_host": "imap.example.com",
                "imap_port": "993",
                "imap_username": "user@example.com",
                "imap_password": "secret_password",
                "imap_mailbox": "Archive",
                "imap_use_ssl": True,
            },
        )
        self.assertEqual(
            fields,
            {
                "imap_host": "imap.example.com",
                "imap_port": "993",
                "imap_username": "user@example.com",
                "imap_mailbox": "Archive",
                "imap_use_ssl": "true",
            },
        )
        self.assertNotIn("imap_password", fields)

    def test_masked_value_formats_user_and_host(self) -> None:
        masked = get_masked_value(
            CredentialType.imap,
            {
                "imap_host": "imap.mail.corp",
                "imap_username": "support",
                "imap_password": "secret",
            },
        )
        self.assertEqual(masked, "support@imap.mail.corp (INBOX)")


if __name__ == "__main__":
    unittest.main()
