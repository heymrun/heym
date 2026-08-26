"""Singleton config access, secret round-trip, and the domain allowlist."""

import unittest

from app.services.sso_settings import (
    decrypt_client_secret,
    email_domain_allowed,
    encrypt_client_secret,
)


class ClientSecretStorageTests(unittest.TestCase):
    def test_secret_round_trips_through_encryption(self) -> None:
        stored = encrypt_client_secret("heym-local-secret")
        self.assertEqual(decrypt_client_secret(stored), "heym-local-secret")

    def test_stored_form_is_not_the_plaintext(self) -> None:
        stored = encrypt_client_secret("heym-local-secret")
        self.assertNotIn("heym-local-secret", stored)

    def test_missing_secret_decrypts_to_empty(self) -> None:
        self.assertEqual(decrypt_client_secret(None), "")


class EmailDomainAllowlistTests(unittest.TestCase):
    def test_empty_allowlist_permits_any_domain(self) -> None:
        self.assertTrue(email_domain_allowed("ada@anywhere.example", ""))

    def test_listed_domain_is_permitted(self) -> None:
        self.assertTrue(email_domain_allowed("ada@heym.local", "heym.local, other.example"))

    def test_comparison_ignores_case_and_whitespace(self) -> None:
        self.assertTrue(email_domain_allowed("Ada@HEYM.Local", "  heym.local  "))

    def test_unlisted_domain_is_rejected(self) -> None:
        self.assertFalse(email_domain_allowed("mallory@evil.example", "heym.local"))

    def test_suffix_lookalike_is_rejected(self) -> None:
        """notheym.local must not pass an allowlist of heym.local."""
        self.assertFalse(email_domain_allowed("mallory@notheym.local", "heym.local"))

    def test_address_without_a_domain_is_rejected(self) -> None:
        self.assertFalse(email_domain_allowed("nodomain", "heym.local"))
