"""Fetch the live OpenCode Go (zen) model list with a hardcoded fallback."""

from __future__ import annotations

import time

import httpx

from app.services.opencode_catalog import (
    OPENCODE_MODEL_FALLBACK,
    OPENCODE_ZEN_BASE_URL,
    normalize_opencode_models,
)

_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_TTL_SECONDS = 600


async def _get_json(url: str) -> object:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def fetch_opencode_models(*, base_url: str | None = None) -> tuple[list[dict[str, str]], str]:
    """Return (models, source) where source is "live" or "fallback"."""
    base = (base_url or OPENCODE_ZEN_BASE_URL).rstrip("/")
    cached = _CACHE.get(base)
    if cached and (time.time() - cached[0]) < _TTL_SECONDS:
        return cached[1], "live"
    try:
        payload = await _get_json(f"{base}/models")
        models = normalize_opencode_models(payload)
        if models:
            _CACHE[base] = (time.time(), models)
            return models, "live"
    except Exception:
        pass
    return [dict(m) for m in OPENCODE_MODEL_FALLBACK], "fallback"
