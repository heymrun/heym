"""Who this instance is, from the environment only.

Identity must not come from the process: the release image runs 8 uvicorn
workers (docker/release-entrypoint.sh) that share one instance row, and
distributed_lock.py's pid-based worker id is a different concept entirely.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from app.config import settings

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.strip().lower()).strip("-")


def instance_id() -> str:
    """This instance's stable id, identical in every one of its processes."""
    if settings.instance_id.strip():
        return settings.instance_id.strip()
    if settings.instance_name.strip():
        return _slugify(settings.instance_name)
    return _slugify(settings.instance_role) or "main"


def instance_name() -> str:
    """The label first shown for this instance; the admin UI may rename it."""
    return settings.instance_name.strip() or instance_id()


def is_main() -> bool:
    """Whether this instance owns file storage, plugins, and ingress."""
    return settings.instance_role.strip().lower() == "main"


def keys_fingerprint() -> str:
    """A comparable digest of the two keys every instance must share.

    Instances with different ENCRYPTION_KEY values cannot decrypt each other's
    credentials, and the resulting run failures name nothing useful. Comparing
    digests turns that into a visible incompatibility. The keys themselves are
    never stored or returned.

    Each half is an HMAC keyed by the key it stands for, not a plain hash of it:
    the Fernet key is ``sha256(ENCRYPTION_KEY)`` itself (services/encryption.py),
    so a prefix of that digest would store part of the signing key.
    """
    return f"{_key_digest(settings.encryption_key)}{_key_digest(settings.secret_key)}"


def primary_fingerprint() -> str:
    """The ENCRYPTION_KEY half of keys_fingerprint: the key this instance encrypts with."""
    return _key_digest(settings.encryption_key)


def decrypt_fingerprints() -> list[str]:
    """Fingerprints of every key this instance decrypts with, ENCRYPTION_KEY first."""
    return [_key_digest(key) for key in settings.encryption_keys]


_FINGERPRINT_LABEL = b"heym-keys-fingerprint"


def _key_digest(key: str) -> str:
    return hmac.new(key.encode(), _FINGERPRINT_LABEL, hashlib.sha256).hexdigest()[:16]
