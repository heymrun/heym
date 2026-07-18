"""Fetch Codex (ChatGPT-account) rate-limit usage via a minimal /responses probe.

The usage data is only exposed as ``x-codex-*`` response headers on a 200 from
``POST https://chatgpt.com/backend-api/codex/responses``. The Codex CLI subprocess
does not surface these headers, so we make a direct minimal request here. Results
are cached for 60s per credential id. Model support is plan-dependent, so we try
candidate models until one is accepted.
"""

from __future__ import annotations

import time
import uuid

import httpx

from app.http_identity import merge_outbound_headers
from app.models.schemas import (
    CodexUsageCredits,
    CodexUsageResponse,
    CodexUsageWindow,
)
from app.services.codex_catalog import CODEX_MODEL_SUGGESTIONS

_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, CodexUsageResponse]] = {}
_working_model: dict[str, str] = {}

_KNOWN_LABELS = {300: "5 hours", 10080: "Weekly"}


def window_label(minutes: int) -> str:
    """Human label for a rate-limit window given its length in minutes."""
    if minutes in _KNOWN_LABELS:
        return _KNOWN_LABELS[minutes]
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _to_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: str | None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_codex_usage_headers(headers: dict[str, str]) -> CodexUsageResponse:
    """Parse ``x-codex-*`` response headers into a structured usage response."""
    lower = {k.lower(): v for k, v in headers.items()}
    if "x-codex-plan-type" not in lower and "x-codex-primary-window-minutes" not in lower:
        return CodexUsageResponse(available=False, error="no usage headers")

    windows: list[CodexUsageWindow] = []
    for key in ("primary", "secondary"):
        minutes = _to_int(lower.get(f"x-codex-{key}-window-minutes"))
        percent = _to_float(lower.get(f"x-codex-{key}-used-percent"))
        if not minutes or minutes <= 0 or percent is None:
            continue
        windows.append(
            CodexUsageWindow(
                key=key,
                label=window_label(minutes),
                used_percent=percent,
                window_minutes=minutes,
                reset_after_seconds=_to_int(lower.get(f"x-codex-{key}-reset-after-seconds")),
                reset_at=_to_int(lower.get(f"x-codex-{key}-reset-at")),
            )
        )

    credits = CodexUsageCredits(
        has_credits=str(lower.get("x-codex-credits-has-credits", "")).strip().lower() == "true",
        balance=lower.get("x-codex-credits-balance") or None,
        unlimited=str(lower.get("x-codex-credits-unlimited", "")).strip().lower() == "true",
    )
    return CodexUsageResponse(
        available=True,
        plan_type=lower.get("x-codex-plan-type") or None,
        active_limit=lower.get("x-codex-active-limit") or None,
        windows=windows,
        credits=credits,
    )


async def fetch_codex_usage(
    *, credential_id: str, access_token: str, account_id: str | None
) -> CodexUsageResponse:
    """Probe the Codex backend and return parsed usage. Never raises."""
    cached = _cache.get(credential_id)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    result = await _probe(credential_id, access_token, account_id)
    _cache[credential_id] = (time.time(), result)
    return result


async def _probe(
    credential_id: str, access_token: str, account_id: str | None
) -> CodexUsageResponse:
    if not access_token:
        return CodexUsageResponse(available=False, error="no access token")

    headers = merge_outbound_headers(
        {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "session_id": str(uuid.uuid4()),
        }
    )
    if account_id:
        headers["chatgpt-account-id"] = account_id

    candidates: list[str] = []
    if credential_id in _working_model:
        candidates.append(_working_model[credential_id])
    candidates.extend(m for m in CODEX_MODEL_SUGGESTIONS if m not in candidates)

    last_error = "no candidate model accepted"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for model in candidates:
                body = {
                    "model": model,
                    "instructions": "ping",
                    "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
                    "stream": True,
                    "store": False,
                }
                async with client.stream(
                    "POST", _RESPONSES_URL, headers=headers, json=body
                ) as resp:
                    if resp.status_code == 200:
                        _working_model[credential_id] = model
                        usage = parse_codex_usage_headers(dict(resp.headers))
                        await resp.aclose()
                        return usage
                    text = (await resp.aread()).decode("utf-8", "replace")
                    last_error = f"HTTP {resp.status_code}: {text[:120]}"
                    if "model is not supported" not in text:
                        # Auth/other error — stop trying more models.
                        break
    except Exception as exc:  # noqa: BLE001 — usage must never break the request
        last_error = f"{type(exc).__name__}: {exc}"

    return CodexUsageResponse(available=False, error=last_error)
