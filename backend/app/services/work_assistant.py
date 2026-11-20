"""Heym Work's tools in a chat turn: the manifest Work publishes and the calls Heym relays.

Heym holds no Work logic. Work lists the tools the signed-in user may use; Heym offers them
under a ``work_`` prefix and relays each call with a short-lived Work-bound token. No
redirect is followed, so a token never reaches a host other than the registered Work URL.
Auditing happens in the API layer (``app/api/chat_work.py``).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WORK_INTEGRATION_ID, User, WorkIntegration
from app.http_identity import HEYM_USER_AGENT
from app.services.work_integration import key_version, mint_assistant_token

logger = logging.getLogger(__name__)

WORK_TOOL_PREFIX = "work_"
TOOLS_PATH = "/api/assistant/tools"
ASSISTANT_TOKEN_HEADER = "X-Heym-Assistant-Token"
MANIFEST_TIMEOUT_SECONDS = 3.0
CALL_TIMEOUT_SECONDS = 20.0
MANIFEST_CACHE_SECONDS = 60.0
WARNING_INTERVAL_SECONDS = 60.0
MAX_TOOLS = 16
MAX_DESCRIPTION_CHARS = 1000
MAX_INSTRUCTIONS_CHARS = 4000
MAX_SCHEMA_BYTES = 8192
MAX_RESULT_CHARS = 60_000
DID_NOT_ANSWER = "Heym Work did not answer."
_NAME = re.compile(r"[a-z][a-z0-9_]{2,40}")
# Work answered and turned the user away (signed out, not allowed, or a Work release
# without the assistant API): no tools, and nothing to report to the model.
_ANSWERED = {401, 403, 404}
# Tests replace this with an httpx.MockTransport.
_TRANSPORT: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class WorkLink:
    """An enabled integration with a key and an address."""

    work_url: str
    key_hash: str


@dataclass(frozen=True)
class WorkTool:
    """One tool as Work published it; `name` carries no prefix."""

    name: str
    description: str
    parameters: dict[str, Any]
    long_running: bool = False


@dataclass(frozen=True)
class WorkManifest:
    """The tools Work offers one user, and Work's guidance for the model."""

    instructions: str
    tools: tuple[WorkTool, ...]


@dataclass(frozen=True)
class ManifestState:
    """What Work offered this user; `unreachable` when it did not answer usefully."""

    manifest: WorkManifest | None
    unreachable: bool


async def load_work_link(db: AsyncSession) -> WorkLink | None:
    """The integration when it is enabled and complete; reads only, never creates the row."""
    result = await db.execute(
        select(WorkIntegration.enabled, WorkIntegration.work_url, WorkIntegration.key_hash).where(
            WorkIntegration.id == WORK_INTEGRATION_ID
        )
    )
    row = result.one_or_none()
    if row is None or not row.enabled or not row.work_url or not row.key_hash:
        return None
    return WorkLink(work_url=row.work_url, key_hash=row.key_hash)


def _parse_tool(item: object) -> WorkTool | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    description = item.get("description")
    parameters = item.get("parameters")
    long_running = item.get("long_running", False)
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        return None
    if not isinstance(description, str) or not description.strip():
        return None
    if len(description) > MAX_DESCRIPTION_CHARS:
        return None
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        return None
    if len(json.dumps(parameters)) > MAX_SCHEMA_BYTES:
        return None
    if not isinstance(long_running, bool):
        return None
    return WorkTool(name, description.strip(), parameters, long_running)


def parse_manifest(data: object) -> WorkManifest | None:
    """Validate what Work sent, dropping each tool that breaks a limit."""
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    raw_tools = data.get("tools")
    if not isinstance(raw_tools, list):
        return None
    instructions = data.get("instructions")
    if not isinstance(instructions, str) or len(instructions) > MAX_INSTRUCTIONS_CHARS:
        instructions = ""
    tools: list[WorkTool] = []
    seen: set[str] = set()
    for item in raw_tools:
        tool = _parse_tool(item)
        if tool is None or tool.name in seen:
            continue
        seen.add(tool.name)
        tools.append(tool)
        if len(tools) == MAX_TOOLS:
            break
    return WorkManifest(instructions=instructions.strip(), tools=tuple(tools))


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=_TRANSPORT)


def _headers(token: str) -> dict[str, str]:
    return {ASSISTANT_TOKEN_HEADER: token, "User-Agent": HEYM_USER_AGENT}


_cache: dict[tuple[uuid.UUID, str, str], tuple[float, ManifestState]] = {}
_last_warning: float | None = None


def clear_manifest_cache() -> None:
    """Forget every cached manifest."""
    _cache.clear()


def _warn(reason: str) -> None:
    global _last_warning
    now = time.monotonic()
    if _last_warning is None or now - _last_warning >= WARNING_INTERVAL_SECONDS:
        _last_warning = now
        logger.warning("Heym Work's assistant tools are unavailable: %s", reason)


async def _fetch_manifest(link: WorkLink, user: User) -> ManifestState:
    token = mint_assistant_token(user, link.key_hash)
    if token is None:
        return ManifestState(None, unreachable=False)
    try:
        async with _client(MANIFEST_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{link.work_url}{TOOLS_PATH}", headers=_headers(token))
    except httpx.HTTPError as exc:
        _warn(type(exc).__name__)
        return ManifestState(None, unreachable=True)
    if response.status_code in _ANSWERED:
        return ManifestState(None, unreachable=False)
    if response.status_code != 200:
        _warn(f"status {response.status_code}")
        return ManifestState(None, unreachable=True)
    try:
        manifest = parse_manifest(response.json())
    except ValueError:
        manifest = None
    if manifest is None:
        _warn("unreadable manifest")
        return ManifestState(None, unreachable=True)
    return ManifestState(manifest, unreachable=False)


async def manifest_for(link: WorkLink, user: User) -> ManifestState:
    """Work's manifest for the user, cached per user, key version and address.

    A rotated key or a new address misses the cache; a disabled integration never gets
    here, because its row is read first (`load_work_link`).
    """
    if not user.is_active:
        return ManifestState(None, unreachable=False)
    key = (user.id, key_version(link.key_hash), link.work_url)
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and now - cached[0] < MANIFEST_CACHE_SECONDS:
        return cached[1]
    state = await _fetch_manifest(link, user)
    _cache[key] = (now, state)
    return state


def _error_detail(response: httpx.Response) -> str:
    if 300 <= response.status_code < 400:
        return "Heym Work answered with a redirect, which Heym does not follow."
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()[:500]
    return f"Heym Work refused the call ({response.status_code})."


async def call_tool(
    link: WorkLink, user: User, tool: WorkTool, args: dict[str, Any]
) -> dict[str, Any]:
    """Relay one call; Work's refusals and failures come back as `{"error": ...}`."""
    token = mint_assistant_token(user, link.key_hash, long_running=tool.long_running)
    if token is None:
        return {"error": "Heym Work is not available for this account."}
    try:
        async with _client(CALL_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{link.work_url}{TOOLS_PATH}/{tool.name}", json=args, headers=_headers(token)
            )
    except httpx.HTTPError:
        return {"error": DID_NOT_ANSWER}
    if not 200 <= response.status_code < 300:
        return {"error": _error_detail(response), "status": response.status_code}
    try:
        data = response.json()
    except ValueError:
        return {"error": "Heym Work sent an answer Heym could not read."}
    return data if isinstance(data, dict) else {"result": data}


def cap_result(result: dict[str, Any]) -> str:
    """The result as JSON for the model, cut to a bounded size."""
    text = json.dumps(result, default=str, ensure_ascii=False)
    if len(text) <= MAX_RESULT_CHARS:
        return text
    return json.dumps({"truncated": True, "partial": text[:MAX_RESULT_CHARS]}, ensure_ascii=False)
