"""In-memory configs of Secret-backed credentials, and the pointers rows hold instead.

A Secret-backed credential's row stores `k8s:<namespace>/<name>` in both
`encrypted_config` and `source`, never a value. Each process watches the Secrets
itself and keeps their decoded configs here, so values never reach the database or
its backups.

Reads come from worker threads as well as the event loop (`decrypt_config` is called
from both), so every change swaps in a new dict rather than mutating the one a reader
may be iterating.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

POINTER_PREFIX = "k8s:"

# Fixed for the life of the feature: changing it would change every credential id and
# break every workflow that references one.
_ID_NAMESPACE = uuid.UUID("5f0c6d3e-8a31-4f4e-9b7a-2d1c0e6b9a47")


class CredentialUnavailableError(Exception):
    """A Secret-backed credential has no value in this process right now."""


def is_pointer(stored: str | None) -> bool:
    """Whether a stored `encrypted_config` is a Secret pointer rather than a ciphertext."""
    return bool(stored) and str(stored).startswith(POINTER_PREFIX)


def pointer_for(namespace: str, name: str) -> str:
    """The value stored in `encrypted_config` and `source` for one Secret."""
    return f"{POINTER_PREFIX}{namespace}/{name}"


def credential_id_for(namespace: str, name: str) -> uuid.UUID:
    """Deterministic, so a Secret that is deleted and recreated keeps its credential id."""
    return uuid.uuid5(_ID_NAMESPACE, f"{namespace}/{name}")


@dataclass(frozen=True)
class SecretCredential:
    """One labelled Secret, decoded. `problem` says why it can't become a credential."""

    namespace: str
    secret_name: str
    name: str
    type: str
    owner_email: str
    share_users: tuple[str, ...] = ()
    share_teams: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict, repr=False)
    problem: str | None = None

    @property
    def pointer(self) -> str:
        return pointer_for(self.namespace, self.secret_name)

    @property
    def credential_id(self) -> uuid.UUID:
        return credential_id_for(self.namespace, self.secret_name)


class SecretCredentialStore:
    """What this process currently knows about labelled Secrets."""

    def __init__(self) -> None:
        self.enabled = False
        self._items: dict[str, SecretCredential] = {}
        self._synced_at: datetime | None = None
        self._synced_monotonic: float | None = None
        self.last_error: str | None = None

    @property
    def synced(self) -> bool:
        """True once a full list has completed. Never goes back to False in a process."""
        return self._synced_at is not None

    @property
    def synced_at(self) -> datetime | None:
        return self._synced_at

    def ready(self) -> bool:
        """Whether this process may run work that could need a Secret-backed credential."""
        return not self.enabled or self.synced

    def seconds_since_sync(self) -> float | None:
        if self._synced_monotonic is None:
            return None
        return time.monotonic() - self._synced_monotonic

    def replace_all(self, items: list[SecretCredential]) -> None:
        """Install the result of a full list."""
        self._items = {item.pointer: item for item in items}
        self._synced_at = datetime.now(timezone.utc)
        self._synced_monotonic = time.monotonic()
        self.last_error = None

    def upsert(self, item: SecretCredential) -> None:
        items = dict(self._items)
        items[item.pointer] = item
        self._items = items

    def remove(self, pointer: str) -> None:
        if pointer in self._items:
            items = dict(self._items)
            items.pop(pointer, None)
            self._items = items

    def items(self) -> list[SecretCredential]:
        return list(self._items.values())

    def get(self, pointer: str) -> SecretCredential | None:
        return self._items.get(pointer)

    def unavailable_reason(self, pointer: str) -> str | None:
        """Why `config_for` would fail for this pointer, or None when it has a value."""
        if not self.synced:
            return "it is not synced from Kubernetes yet"
        item = self._items.get(pointer)
        if item is None:
            return f"Secret {pointer[len(POINTER_PREFIX) :]} not found"
        if item.problem:
            return f"Secret {pointer[len(POINTER_PREFIX) :]} is invalid: {item.problem}"
        return None

    def config_for(self, pointer: str) -> dict[str, Any]:
        """A copy of the config, or CredentialUnavailableError saying why there is none."""
        reason = self.unavailable_reason(pointer)
        if reason is not None:
            raise CredentialUnavailableError(f"Kubernetes credential unavailable: {reason}")
        return dict(self._items[pointer].config)


store = SecretCredentialStore()
