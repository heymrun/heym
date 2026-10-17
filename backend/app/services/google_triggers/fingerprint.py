"""Keyed fingerprints for polling-trigger snapshots.

A Google Sheets Trigger has to tell that a row or a cell changed without keeping what it
said, so the snapshot stores fingerprints instead of values.

This is deliberately not ``secret_tokens.hash_secret``. That helper is a plain SHA-256 for
high-entropy capability secrets, where there is nothing to guess. Cell values have low
entropy ("yes", "100", a status name), so an unkeyed hash of them could be reversed by
hashing likely values and comparing. An HMAC keyed with a value derived from SECRET_KEY
means a reader of the database or a backup cannot run that guess loop.

Each fingerprint is also salted with the workflow and node, so the same value watched by
two triggers does not produce the same fingerprint.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

_DERIVATION_LABEL = b"heym:trigger-fingerprint:v1"

#: Cell fingerprints only detect change; a collision hides one edit, nothing more.
CELL_DIGEST_CHARS = 8
#: Row keys and header rows identify items, so they get more bits.
ITEM_DIGEST_CHARS = 16


@dataclass(frozen=True)
class Fingerprinter:
    """Fingerprints values for one trigger node."""

    key: bytes = field(repr=False)
    salt: str

    @classmethod
    def for_node(cls, secret: str, workflow_id: str, node_id: str) -> Fingerprinter:
        """Derive the fingerprint key from ``secret`` and salt it with the node's identity."""
        key = hmac.new(secret.encode("utf-8"), _DERIVATION_LABEL, hashlib.sha256).digest()
        return cls(key=key, salt=f"{workflow_id}:{node_id}:")

    @property
    def key_id(self) -> str:
        """Short identifier of the key; a change means stored fingerprints no longer compare."""
        return hashlib.sha256(self.key).hexdigest()[:16]

    def cell(self, value: str) -> str:
        """Fingerprint of one cell value."""
        return self._digest(value, CELL_DIGEST_CHARS)

    def item(self, value: str) -> str:
        """Fingerprint of a row key or a header row."""
        return self._digest(value, ITEM_DIGEST_CHARS)

    def _digest(self, value: str, length: int) -> str:
        message = (self.salt + value).encode("utf-8")
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()[:length]
