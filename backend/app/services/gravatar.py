"""Fetch and cache Gravatar images for user avatars.

Gravatar is asked from the server, never from the browser, so viewers' IP addresses stay
private and the frontend never needs another user's email. ``d=404`` makes Gravatar answer
404 for an address without a picture; that miss is cached as well, so an install whose users
have no Gravatar account does not ask again on every page load.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass

import httpx

from app.http_identity import merge_outbound_headers

GRAVATAR_AVATAR_URL = "https://www.gravatar.com/avatar"
AVATAR_PIXEL_SIZE = 128
MAX_IMAGE_BYTES = 1_000_000
MAX_CACHE_ENTRIES = 1024

# A picture changed on Gravatar shows up within a few hours; misses expire just as fast.
_TTL_SECONDS = 6 * 60 * 60
_ERROR_TTL_SECONDS = 5 * 60
_TIMEOUT = httpx.Timeout(3.0)
# Raster only: an SVG served from our own origin could run script when opened directly.
_ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})


@dataclass(frozen=True)
class GravatarImage:
    """A Gravatar picture ready to be served as-is."""

    content: bytes
    content_type: str
    etag: str


@dataclass(frozen=True)
class _CacheEntry:
    expires_at: float
    image: GravatarImage | None


_cache: OrderedDict[str, _CacheEntry] = OrderedDict()


def gravatar_hash(email: str) -> str:
    """Return the SHA-256 Gravatar identifier for an email address."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def clear_gravatar_cache() -> None:
    """Drop every cached picture and miss."""
    _cache.clear()


async def get_gravatar(email: str) -> GravatarImage | None:
    """Return the Gravatar picture for ``email``, or ``None`` when there is none or it failed."""
    key = gravatar_hash(email)
    entry = _cache.get(key)
    if entry is not None and entry.expires_at > time.monotonic():
        _cache.move_to_end(key)
        return entry.image

    image, ttl = await _fetch(key)
    _cache[key] = _CacheEntry(expires_at=time.monotonic() + ttl, image=image)
    _cache.move_to_end(key)
    while len(_cache) > MAX_CACHE_ENTRIES:
        _cache.popitem(last=False)
    return image


async def _fetch(key: str) -> tuple[GravatarImage | None, int]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=merge_outbound_headers()) as client:
            response = await client.get(
                f"{GRAVATAR_AVATAR_URL}/{key}",
                params={"s": str(AVATAR_PIXEL_SIZE), "d": "404"},
            )
    except httpx.HTTPError:
        return None, _ERROR_TTL_SECONDS

    if response.status_code == 404:
        return None, _TTL_SECONDS
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    content = response.content
    if (
        response.status_code != 200
        or content_type not in _ALLOWED_CONTENT_TYPES
        or len(content) > MAX_IMAGE_BYTES
    ):
        return None, _ERROR_TTL_SECONDS

    etag = f'"{hashlib.sha256(content).hexdigest()[:32]}"'
    return GravatarImage(content=content, content_type=content_type, etag=etag), _TTL_SECONDS
