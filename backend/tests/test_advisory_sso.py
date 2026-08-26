"""SSO security invariants: credentials at rest, and both password surfaces."""

import unittest

from app.services.auth import hash_password, verify_password


class NullPasswordHashTests(unittest.TestCase):
    def test_none_hash_returns_false_instead_of_raising(self) -> None:
        """SSO-provisioned users have no password; bcrypt raises on an empty salt."""
        self.assertFalse(verify_password("anything", None))

    def test_empty_hash_returns_false_instead_of_raising(self) -> None:
        self.assertFalse(verify_password("anything", ""))

    def test_real_hash_still_verifies(self) -> None:
        self.assertTrue(verify_password("hunter2", hash_password("hunter2")))
        self.assertFalse(verify_password("hunter3", hash_password("hunter2")))
