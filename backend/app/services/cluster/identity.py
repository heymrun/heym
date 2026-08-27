"""Who this instance is, from the environment only.

Identity must not come from the process: the release image runs 8 uvicorn
workers (docker/release-entrypoint.sh) that share one instance row, and
distributed_lock.py's pid-based worker id is a different concept entirely.
"""

from __future__ import annotations

import hashlib
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
    """
    enc = hashlib.sha256(settings.encryption_key.encode()).hexdigest()[:16]
    sec = hashlib.sha256(settings.secret_key.encode()).hexdigest()[:16]
    return f"{enc}{sec}"
