"""Regression tests for issue #643: credential update silently wiped config for
bearer, smtp, redis, cohere, and opencode credentials.

merge_credential_config_for_update and validate_credential_config had no branch
for any of these five types, so a PUT with a blank or partial config replaced the
whole stored config with no error (merge fell through to `return incoming_config`,
and validation fell through with no check at all).

Live-verified against a running instance before this fix: a blank PUT to each of
these five types returned HTTP 200 and the stored config decrypted to all-blank
values. See heymrun/heym#643.
"""

import unittest

from fastapi import HTTPException

from app.api.credentials import (
    get_public_credential_fields,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType


class TestBearerCredentialMerge(unittest.TestCase):
    def test_blank_token_keeps_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.bearer,
            {"bearer_token": "original-token"},
            {"bearer_token": ""},
        )
        self.assertEqual(merged["bearer_token"], "original-token")

    def test_non_blank_token_overwrites_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.bearer,
            {"bearer_token": "original-token"},
            {"bearer_token": "rotated-token"},
        )
        self.assertEqual(merged["bearer_token"], "rotated-token")


class TestBearerCredentialValidation(unittest.TestCase):
    def test_rejects_missing_token(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.bearer, {})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_accepts_present_token(self) -> None:
        validate_credential_config(CredentialType.bearer, {"bearer_token": "x"})


class TestSmtpCredentialMerge(unittest.TestCase):
    def _full_config(self) -> dict:
        return {
            "smtp_server": "smtp.corp.example.com",
            "smtp_port": "587",
            "smtp_email": "alerts@corp.example.com",
            "smtp_password": "original-password",
        }

    def test_partial_update_keeps_everything_not_sent(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.smtp,
            self._full_config(),
            {"smtp_server": "smtp2.corp.example.com"},
        )
        self.assertEqual(merged["smtp_server"], "smtp2.corp.example.com")
        self.assertEqual(merged["smtp_port"], "587")
        self.assertEqual(merged["smtp_email"], "alerts@corp.example.com")
        self.assertEqual(merged["smtp_password"], "original-password")

    def test_blank_fields_keep_the_stored_values(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.smtp,
            self._full_config(),
            {
                "smtp_server": "",
                "smtp_port": "",
                "smtp_email": "",
                "smtp_password": "",
            },
        )
        self.assertEqual(merged, self._full_config())

    def test_non_blank_password_overwrites_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.smtp,
            self._full_config(),
            {"smtp_password": "new-password"},
        )
        self.assertEqual(merged["smtp_password"], "new-password")

    def test_blank_smtp_from_clears_the_stored_sender(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.smtp,
            {**self._full_config(), "smtp_from": "team@corp.example.com"},
            {"smtp_from": "  "},
        )
        self.assertEqual(merged["smtp_from"], "")
        self.assertEqual(merged["smtp_email"], "alerts@corp.example.com")

    def test_omitted_smtp_from_keeps_the_stored_sender(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.smtp,
            {**self._full_config(), "smtp_from": "team@corp.example.com"},
            {"smtp_server": "smtp2.corp.example.com", "smtp_password": ""},
        )
        self.assertEqual(merged["smtp_from"], "team@corp.example.com")

    def test_sent_smtp_from_is_stored_stripped(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.smtp,
            self._full_config(),
            {"smtp_from": " team@corp.example.com "},
        )
        self.assertEqual(merged["smtp_from"], "team@corp.example.com")
        self.assertEqual(merged["smtp_email"], "alerts@corp.example.com")


class TestSmtpCredentialValidation(unittest.TestCase):
    def test_accepts_config_without_smtp_from(self) -> None:
        validate_credential_config(
            CredentialType.smtp,
            {
                "smtp_server": "smtp.corp.example.com",
                "smtp_port": "587",
                "smtp_email": "alerts@corp.example.com",
                "smtp_password": "secret",
            },
        )

    def test_rejects_missing_required_field(self) -> None:
        for missing in ("smtp_server", "smtp_port", "smtp_email", "smtp_password"):
            config = {
                "smtp_server": "smtp.corp.example.com",
                "smtp_port": "587",
                "smtp_email": "alerts@corp.example.com",
                "smtp_password": "secret",
            }
            config.pop(missing)
            with self.assertRaises(HTTPException):
                validate_credential_config(CredentialType.smtp, config)


class TestSmtpCredentialPublicFields(unittest.TestCase):
    def test_returns_non_secret_fields_only(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.smtp,
            {
                "smtp_server": "smtp.corp.example.com",
                "smtp_port": "587",
                "smtp_email": "alerts@corp.example.com",
                "smtp_password": "secret",
                "smtp_from": "team@corp.example.com",
            },
        )
        self.assertEqual(
            fields,
            {
                "smtp_server": "smtp.corp.example.com",
                "smtp_port": "587",
                "smtp_email": "alerts@corp.example.com",
                "smtp_from": "team@corp.example.com",
            },
        )
        self.assertNotIn("smtp_password", fields)

    def test_missing_smtp_from_is_returned_as_none(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.smtp,
            {
                "smtp_server": "smtp.corp.example.com",
                "smtp_port": "587",
                "smtp_email": "alerts@corp.example.com",
                "smtp_password": "secret",
            },
        )
        self.assertIn("smtp_from", fields)
        self.assertIsNone(fields["smtp_from"])


class TestRedisCredentialMerge(unittest.TestCase):
    def _full_config(self) -> dict:
        return {
            "redis_host": "redis.corp.example.com",
            "redis_port": "6379",
            "redis_password": "original-password",
            "redis_db": "0",
        }

    def test_partial_update_keeps_everything_not_sent(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.redis,
            self._full_config(),
            {"redis_host": "redis2.corp.example.com"},
        )
        self.assertEqual(merged["redis_host"], "redis2.corp.example.com")
        self.assertEqual(merged["redis_port"], "6379")
        self.assertEqual(merged["redis_password"], "original-password")
        self.assertEqual(merged["redis_db"], "0")

    def test_blank_fields_keep_the_stored_values(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.redis,
            self._full_config(),
            {"redis_host": "", "redis_port": "", "redis_password": "", "redis_db": ""},
        )
        self.assertEqual(merged, self._full_config())

    def test_non_blank_password_overwrites_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.redis,
            self._full_config(),
            {"redis_password": "new-password"},
        )
        self.assertEqual(merged["redis_password"], "new-password")

    def test_db_zero_is_applied_not_treated_as_blank(self) -> None:
        """redis_db is sent as a string in this codebase ("0" is non-empty), so a
        plain blank-string check is correct here, unlike ClickHouse's raw int port."""
        merged = merge_credential_config_for_update(
            CredentialType.redis,
            {**self._full_config(), "redis_db": "3"},
            {"redis_db": "0"},
        )
        self.assertEqual(merged["redis_db"], "0")


class TestRedisCredentialValidation(unittest.TestCase):
    def test_rejects_missing_host_or_port(self) -> None:
        for missing in ("redis_host", "redis_port"):
            config = {"redis_host": "redis.corp.example.com", "redis_port": "6379"}
            config.pop(missing)
            with self.assertRaises(HTTPException):
                validate_credential_config(CredentialType.redis, config)

    def test_password_and_db_are_not_required(self) -> None:
        validate_credential_config(
            CredentialType.redis, {"redis_host": "redis.corp.example.com", "redis_port": "6379"}
        )


class TestRedisCredentialPublicFields(unittest.TestCase):
    def test_returns_non_secret_fields_only(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.redis,
            {
                "redis_host": "redis.corp.example.com",
                "redis_port": "6379",
                "redis_password": "secret",
                "redis_db": "2",
            },
        )
        self.assertEqual(
            fields,
            {"redis_host": "redis.corp.example.com", "redis_port": "6379", "redis_db": "2"},
        )
        self.assertNotIn("redis_password", fields)


class TestCohereCredentialMerge(unittest.TestCase):
    def test_blank_key_keeps_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.cohere, {"api_key": "original-key"}, {"api_key": ""}
        )
        self.assertEqual(merged["api_key"], "original-key")

    def test_non_blank_key_overwrites_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.cohere, {"api_key": "original-key"}, {"api_key": "new-key"}
        )
        self.assertEqual(merged["api_key"], "new-key")


class TestCohereCredentialValidation(unittest.TestCase):
    def test_rejects_missing_api_key(self) -> None:
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.cohere, {})


class TestOpenCodeCredentialMerge(unittest.TestCase):
    def test_editing_base_url_only_keeps_the_stored_api_key(self) -> None:
        """Regression for the exact bug the maintainer reported: changing only the
        gateway URL used to blank the stored API key, because there was no merge
        branch at all and the whole config was replaced by the incoming payload."""
        merged = merge_credential_config_for_update(
            CredentialType.opencode,
            {"api_key": "original-key", "base_url": "https://opencode.ai"},
            {"api_key": "", "base_url": "https://gateway.example.com"},
        )
        self.assertEqual(merged["api_key"], "original-key")
        self.assertEqual(merged["base_url"], "https://gateway.example.com")

    def test_editing_api_key_only_keeps_the_stored_base_url(self) -> None:
        """The other half of the maintainer's report: editing only the API key used
        to drop the stored base_url entirely, since it was omitted from the request
        body (the frontend only sends base_url when the field is non-blank)."""
        merged = merge_credential_config_for_update(
            CredentialType.opencode,
            {"api_key": "original-key", "base_url": "https://gateway.example.com"},
            {"api_key": "new-key"},
        )
        self.assertEqual(merged["api_key"], "new-key")
        self.assertEqual(merged["base_url"], "https://gateway.example.com")

    def test_blank_base_url_sent_explicitly_keeps_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.opencode,
            {"api_key": "original-key", "base_url": "https://gateway.example.com"},
            {"api_key": "original-key", "base_url": ""},
        )
        self.assertEqual(merged["base_url"], "https://gateway.example.com")


class TestOpenCodeCredentialValidation(unittest.TestCase):
    def test_rejects_missing_api_key(self) -> None:
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.opencode, {"base_url": "https://x"})

    def test_base_url_is_not_required(self) -> None:
        validate_credential_config(CredentialType.opencode, {"api_key": "k"})


class TestOpenCodeCredentialPublicFields(unittest.TestCase):
    def test_returns_base_url_only(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.opencode,
            {"api_key": "secret", "base_url": "https://gateway.example.com"},
        )
        self.assertEqual(fields, {"base_url": "https://gateway.example.com"})
        self.assertNotIn("api_key", fields)


if __name__ == "__main__":
    unittest.main()
