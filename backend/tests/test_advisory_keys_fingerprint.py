"""Security regression tests: the cluster keys fingerprint holds no Fernet key material.

Reported with GHSA-hmfh-wpg2-vff4. ``cluster_instances.keys_fingerprint`` stored
``sha256(ENCRYPTION_KEY).hexdigest()[:16]``, and the Fernet key is that same digest, so
the stored value was the first 8 of the 16 signing-key bytes. Each half of the
fingerprint is now an HMAC keyed by the key it stands for.
"""

import hashlib
import unittest
from unittest.mock import patch

from app.services import encryption
from app.services.cluster import identity

_ENCRYPTION_KEY = "advisory-encryption-key"
_SECRET_KEY = "advisory-secret-key"


def _keys():  # noqa: ANN202 - context manager helper
    return patch.multiple(identity.settings, encryption_key=_ENCRYPTION_KEY, secret_key=_SECRET_KEY)


class KeysFingerprintMaterialTests(unittest.TestCase):
    def test_fingerprint_shares_nothing_with_the_fernet_key(self) -> None:
        with _keys():
            fingerprint = identity.keys_fingerprint()
        with patch.object(encryption.settings, "encryption_key", _ENCRYPTION_KEY):
            fernet = encryption.get_fernet()
        # The 32 Fernet key bytes: signing key, then encryption key.
        fernet_key = fernet._signing_key + fernet._encryption_key
        self.assertEqual(fernet_key, hashlib.sha256(_ENCRYPTION_KEY.encode()).digest())
        self.assertEqual(len(fingerprint), 32)
        stored = bytes.fromhex(fingerprint)
        for size in (4, 8):
            for start in range(0, len(stored) - size + 1):
                with self.subTest(start=start, size=size):
                    self.assertNotIn(stored[start : start + size], fernet_key)

    def test_fingerprint_is_not_a_plain_hash_of_either_key(self) -> None:
        with _keys():
            fingerprint = identity.keys_fingerprint()
        for key in (_ENCRYPTION_KEY, _SECRET_KEY):
            with self.subTest(key=key):
                self.assertNotIn(hashlib.sha256(key.encode()).hexdigest()[:16], fingerprint)

    def test_the_fernet_key_still_comes_from_the_encryption_key(self) -> None:
        """The fix changes the fingerprint only; stored credentials still decrypt."""
        with patch.object(encryption.settings, "encryption_key", _ENCRYPTION_KEY):
            token = encryption.encrypt_config({"api_key": "x"})
            self.assertEqual(encryption.decrypt_config(token), {"api_key": "x"})

    def test_matching_keys_still_match_and_different_keys_differ(self) -> None:
        with _keys():
            first = identity.keys_fingerprint()
            self.assertEqual(identity.keys_fingerprint(), first)
        with patch.multiple(identity.settings, encryption_key="other", secret_key=_SECRET_KEY):
            self.assertNotEqual(identity.keys_fingerprint(), first)
        with patch.multiple(identity.settings, encryption_key=_ENCRYPTION_KEY, secret_key="other"):
            self.assertNotEqual(identity.keys_fingerprint(), first)


if __name__ == "__main__":
    unittest.main()
