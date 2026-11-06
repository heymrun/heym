"""Secret-backed credentials: pointers, ids, the in-memory store and decrypt_config."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from app.services.encryption import decrypt_config, encrypt_config
from app.services.k8s_credentials.store import (
    CredentialUnavailableError,
    SecretCredential,
    SecretCredentialStore,
    credential_id_for,
    is_pointer,
    pointer_for,
)


def _item(name: str = "llm", **over: object) -> SecretCredential:
    fields: dict = dict(
        namespace="heym",
        secret_name=f"heym-cred-{name}",
        name=name,
        type="custom",
        owner_email="admin@example.com",
        config={"api_key": "sk-test"},
    )
    fields.update(over)
    return SecretCredential(**fields)


class PointerTests(unittest.TestCase):
    def test_pointer_names_namespace_and_secret(self) -> None:
        self.assertEqual(pointer_for("heym", "heym-cred-llm"), "k8s:heym/heym-cred-llm")

    def test_a_fernet_token_is_not_a_pointer(self) -> None:
        self.assertFalse(is_pointer(encrypt_config({"api_key": "x"})))
        self.assertTrue(is_pointer("k8s:heym/a"))

    def test_id_is_stable_for_the_same_secret(self) -> None:
        """A Secret recreated by a GitOps prune keeps its id, so workflows keep working."""
        self.assertEqual(credential_id_for("heym", "a"), credential_id_for("heym", "a"))
        self.assertNotEqual(credential_id_for("heym", "a"), credential_id_for("other", "a"))
        self.assertIsInstance(credential_id_for("heym", "a"), uuid.UUID)


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SecretCredentialStore()
        self.store.enabled = True

    def test_nothing_resolves_before_the_first_sync(self) -> None:
        self.assertFalse(self.store.ready())
        with self.assertRaisesRegex(CredentialUnavailableError, "not synced from Kubernetes yet"):
            self.store.config_for("k8s:heym/heym-cred-llm")

    def test_a_disabled_store_is_always_ready(self) -> None:
        self.assertTrue(SecretCredentialStore().ready())

    def test_synced_value_resolves_as_a_copy(self) -> None:
        item = _item()
        self.store.replace_all([item])

        config = self.store.config_for(item.pointer)
        config["api_key"] = "changed"

        self.assertEqual(self.store.config_for(item.pointer), {"api_key": "sk-test"})
        self.assertTrue(self.store.ready())

    def test_a_deleted_secret_says_which_secret_is_missing(self) -> None:
        item = _item()
        self.store.replace_all([item])
        self.store.remove(item.pointer)

        with self.assertRaisesRegex(
            CredentialUnavailableError, "Secret heym/heym-cred-llm not found"
        ):
            self.store.config_for(item.pointer)

    def test_an_invalid_secret_says_why(self) -> None:
        item = _item(problem="missing annotation heym.run/owner")
        self.store.replace_all([item])

        with self.assertRaisesRegex(CredentialUnavailableError, "missing annotation"):
            self.store.config_for(item.pointer)

    def test_upsert_replaces_the_value(self) -> None:
        self.store.replace_all([_item()])
        self.store.upsert(_item(config={"api_key": "sk-rotated"}))

        self.assertEqual(self.store.config_for(_item().pointer), {"api_key": "sk-rotated"})


class DecryptConfigTests(unittest.TestCase):
    def test_a_pointer_resolves_from_the_store_not_from_fernet(self) -> None:
        store = SecretCredentialStore()
        store.enabled = True
        item = _item()
        store.replace_all([item])

        with patch("app.services.encryption.k8s_credential_store", store):
            self.assertEqual(decrypt_config(item.pointer), {"api_key": "sk-test"})

    def test_a_ciphertext_still_decrypts(self) -> None:
        self.assertEqual(decrypt_config(encrypt_config({"api_key": "x"})), {"api_key": "x"})


if __name__ == "__main__":
    unittest.main()
