"""Instance identity, role, and the compatibility fingerprint."""

import unittest
from unittest.mock import patch

from app.services.cluster import identity


class InstanceIdentityTests(unittest.TestCase):
    def test_explicit_id_is_used_verbatim(self) -> None:
        with patch.object(identity.settings, "instance_id", "eu-worker-1"):
            self.assertEqual(identity.instance_id(), "eu-worker-1")

    def test_id_falls_back_to_a_slug_of_the_name(self) -> None:
        with (
            patch.object(identity.settings, "instance_id", ""),
            patch.object(identity.settings, "instance_name", "EU Worker 1"),
        ):
            self.assertEqual(identity.instance_id(), "eu-worker-1")

    def test_id_falls_back_to_the_role_when_nothing_is_set(self) -> None:
        with (
            patch.object(identity.settings, "instance_id", ""),
            patch.object(identity.settings, "instance_name", ""),
            patch.object(identity.settings, "instance_role", "main"),
        ):
            self.assertEqual(identity.instance_id(), "main")

    def test_identity_does_not_depend_on_the_process(self) -> None:
        """Eight uvicorn processes must resolve to one identity."""
        with patch.object(identity.settings, "instance_id", "worker-a"):
            self.assertEqual(identity.instance_id(), identity.instance_id())

    def test_is_main_follows_the_role(self) -> None:
        with patch.object(identity.settings, "instance_role", "main"):
            self.assertTrue(identity.is_main())
        with patch.object(identity.settings, "instance_role", "worker"):
            self.assertFalse(identity.is_main())

    def test_an_unrecognised_role_is_not_main(self) -> None:
        with patch.object(identity.settings, "instance_role", "MAIN "):
            self.assertTrue(identity.is_main())
        with patch.object(identity.settings, "instance_role", "nonsense"):
            self.assertFalse(identity.is_main())


class KeysFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable_for_the_same_keys(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            self.assertEqual(identity.keys_fingerprint(), identity.keys_fingerprint())

    def test_a_different_encryption_key_changes_the_fingerprint(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            first = identity.keys_fingerprint()
        with (
            patch.object(identity.settings, "encryption_key", "different"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            self.assertNotEqual(identity.keys_fingerprint(), first)

    def test_a_different_secret_key_changes_the_fingerprint(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "k2"),
        ):
            first = identity.keys_fingerprint()
        with (
            patch.object(identity.settings, "encryption_key", "k1"),
            patch.object(identity.settings, "secret_key", "different"),
        ):
            self.assertNotEqual(identity.keys_fingerprint(), first)

    def test_fingerprint_never_contains_a_key(self) -> None:
        with (
            patch.object(identity.settings, "encryption_key", "super-secret-value"),
            patch.object(identity.settings, "secret_key", "another-secret-value"),
        ):
            printed = identity.keys_fingerprint()
        self.assertNotIn("super-secret-value", printed)
        self.assertNotIn("another-secret-value", printed)
