"""Keyed fingerprints for Google trigger snapshots."""

import unittest

from app.services.google_triggers.fingerprint import (
    CELL_DIGEST_CHARS,
    ITEM_DIGEST_CHARS,
    Fingerprinter,
)

SECRET = "test-secret-key-for-tests-only-32-bytes"


class FingerprinterTests(unittest.TestCase):
    def test_same_value_on_the_same_node_matches(self) -> None:
        fingerprinter = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        self.assertEqual(fingerprinter.cell("Paid"), fingerprinter.cell("Paid"))

    def test_digests_have_fixed_lengths(self) -> None:
        fingerprinter = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        self.assertEqual(len(fingerprinter.cell("Paid")), CELL_DIGEST_CHARS)
        self.assertEqual(len(fingerprinter.item("Paid")), ITEM_DIGEST_CHARS)

    def test_another_node_fingerprints_the_same_value_differently(self) -> None:
        first = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        second = Fingerprinter.for_node(SECRET, "wf-1", "node-2")
        self.assertNotEqual(first.item("ada@example.com"), second.item("ada@example.com"))

    def test_rotating_the_secret_changes_key_id_and_digests(self) -> None:
        before = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        after = Fingerprinter.for_node(SECRET + "-rotated", "wf-1", "node-1")
        self.assertNotEqual(before.key_id, after.key_id)
        self.assertNotEqual(before.cell("yes"), after.cell("yes"))

    def test_key_id_is_the_same_for_every_node(self) -> None:
        first = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        second = Fingerprinter.for_node(SECRET, "wf-2", "node-9")
        self.assertEqual(first.key_id, second.key_id)

    def test_repr_does_not_expose_the_key(self) -> None:
        fingerprinter = Fingerprinter.for_node(SECRET, "wf-1", "node-1")
        self.assertNotIn(repr(fingerprinter.key), repr(fingerprinter))


if __name__ == "__main__":
    unittest.main()
