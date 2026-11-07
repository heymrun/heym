"""ENCRYPTION_KEY plus ENCRYPTION_KEYS_EXTRA: encrypt with the first, decrypt with any (#862)."""

import base64
import hashlib
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError

from app.config import _ENCRYPTION_KEY_PLACEHOLDER, Settings
from app.services import encryption

OLD = "old-encryption-key-for-tests"
NEW = "new-encryption-key-for-tests"


def _settings(extra: str) -> Settings:
    return Settings(
        _env_file=None,
        secret_key="s" * 32,
        encryption_key=NEW,
        encryption_keys_extra=extra,
    )


def _keys(primary: str, extra: str = ""):  # noqa: ANN202 - context manager helper
    return patch.multiple(encryption.settings, encryption_key=primary, encryption_keys_extra=extra)


class ExtraKeysSettingTests(unittest.TestCase):
    def test_entries_are_trimmed_and_empty_ones_dropped(self) -> None:
        settings = _settings(f" {OLD} ,, ,other-key,")

        self.assertEqual(settings.encryption_keys_extra, f"{OLD},other-key")
        self.assertEqual(settings.encryption_keys, [NEW, OLD, "other-key"])

    def test_a_trailing_comma_adds_no_empty_key(self) -> None:
        self.assertEqual(_settings(f"{OLD},").encryption_keys, [NEW, OLD])
        self.assertNotIn("", _settings(",").encryption_keys)

    def test_unset_means_only_the_primary(self) -> None:
        self.assertEqual(_settings("").encryption_keys, [NEW])

    def test_the_primary_or_a_repeat_is_listed_once(self) -> None:
        self.assertEqual(_settings(f"{NEW},{OLD},{OLD}").encryption_keys, [NEW, OLD])

    def test_the_placeholder_is_refused(self) -> None:
        with self.assertRaisesRegex(ValidationError, "ENCRYPTION_KEYS_EXTRA"):
            _settings(f"{OLD},{_ENCRYPTION_KEY_PLACEHOLDER}")


class KeyListTests(unittest.TestCase):
    def test_existing_ciphertext_decrypts_unchanged(self) -> None:
        # What every install stores today: Fernet(sha256(ENCRYPTION_KEY)).
        legacy = Fernet(base64.urlsafe_b64encode(hashlib.sha256(NEW.encode()).digest()))
        token = legacy.encrypt(b'{"api_key": "sk-1"}').decode()

        with _keys(NEW):
            self.assertEqual(encryption.decrypt_config(token), {"api_key": "sk-1"})

    def test_phase_1_encrypts_with_the_old_key_and_reads_the_new(self) -> None:
        with _keys(NEW):
            written_under_new = encryption.encrypt_config({"k": "new"})
        with _keys(OLD, NEW):
            written = encryption.encrypt_config({"k": "old"})
            self.assertEqual(encryption.decrypt_config(written_under_new), {"k": "new"})
        with _keys(OLD):
            self.assertEqual(encryption.decrypt_config(written), {"k": "old"})

    def test_phase_2_encrypts_with_the_new_key_and_reads_the_old(self) -> None:
        with _keys(OLD):
            old_token = encryption.encrypt_config({"k": "v"})
        with _keys(NEW, OLD):
            self.assertEqual(encryption.decrypt_config(old_token), {"k": "v"})
            new_token = encryption.encrypt_config({"k": "v2"})
        with _keys(NEW):
            self.assertEqual(encryption.decrypt_config(new_token), {"k": "v2"})
            with self.assertRaises(InvalidToken):
                encryption.decrypt_config(old_token)

    def test_rotate_moves_a_token_to_the_primary_and_keeps_its_timestamp(self) -> None:
        with _keys(OLD):
            old_token = encryption.encrypt_config({"k": "v"})
        with _keys(NEW, OLD):
            self.assertFalse(encryption.readable_by_primary(old_token))
            rotated = encryption.rotate_token(old_token)
            self.assertTrue(encryption.readable_by_primary(rotated))
        timestamp = Fernet.extract_timestamp
        old_fernet = encryption.fernet_for(OLD)
        new_fernet = encryption.fernet_for(NEW)
        self.assertEqual(timestamp(new_fernet, rotated), timestamp(old_fernet, old_token))
        with _keys(NEW):
            self.assertEqual(encryption.decrypt_config(rotated), {"k": "v"})

    def test_rotate_refuses_a_token_no_key_reads(self) -> None:
        with _keys("lost-key"):
            lost = encryption.encrypt_config({"k": "v"})
        with _keys(NEW, OLD), self.assertRaises(InvalidToken):
            encryption.rotate_token(lost)


if __name__ == "__main__":
    unittest.main()
