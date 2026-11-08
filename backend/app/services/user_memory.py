"""User Rules as the user's memory: read, append and replace from Chat and MCP.

The text is ``users.user_rules``, the field the Settings form edits, so every session the user
starts sees the same memory in its system prompt. These are the writes a model makes. An append
adds one line and cannot disturb what is there. A replace rewrites the text and lands only when
the caller read the current revision, so two sessions cannot silently undo each other. Neither
stores text that looks like a credential, and each commits at once, so the row lock is never held
across a chat turn.
"""

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.services.user_memory_secrets import find_secret_like

MAX_USER_MEMORY_LENGTH = 4000

STATUS_ADDED = "added"
STATUS_REPLACED = "replaced"
STATUS_UNCHANGED = "unchanged"
STATUS_CONFLICT = "conflict"
STATUS_REFUSED = "refused"

SECRET_REFUSAL = (
    "This looks like an API key or credential. Heym does not save secrets to memory. "
    "Store it in Credentials instead."
)
EMPTY_APPEND = "Nothing to save: content is empty."
APPEND_TOO_LONG = (
    f"User Rules would exceed {MAX_USER_MEMORY_LENGTH} characters. Read them with "
    "get_user_memory and condense them with set_user_memory mode=replace."
)
REPLACE_TOO_LONG = f"User Rules can hold at most {MAX_USER_MEMORY_LENGTH} characters."
CONFLICT_NEXT_STEP = (
    "User Rules changed since you read them. Merge your change into this content and call "
    "set_user_memory mode=replace again with this revision."
)


def revision_of(text: str | None) -> str:
    """A short digest of the stored text; it detects concurrent changes and is not a secret."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class UserMemorySnapshot:
    """The memory as stored, with the revision a replace must quote."""

    content: str
    revision: str
    length: int
    max_length: int = MAX_USER_MEMORY_LENGTH

    def as_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "revision": self.revision,
            "length": self.length,
            "max_length": self.max_length,
        }


@dataclass(frozen=True)
class UserMemoryWriteResult:
    """What a write did, and the memory as it stands afterwards."""

    status: str
    snapshot: UserMemorySnapshot
    error: str | None = None
    reason: str | None = None
    next_step: str | None = None

    @property
    def changed(self) -> bool:
        return self.status in (STATUS_ADDED, STATUS_REPLACED)

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"status": self.status, **self.snapshot.as_dict()}
        for key, value in (
            ("error", self.error),
            ("reason", self.reason),
            ("next_step", self.next_step),
        ):
            if value:
                body[key] = value
        return body


@dataclass(frozen=True)
class WritePlan:
    """The text to store (None leaves the row alone) and what to tell the caller."""

    text: str | None
    result: UserMemoryWriteResult


def snapshot_of(text: str | None) -> UserMemorySnapshot:
    """A snapshot of stored text; None and the empty string are the same memory."""
    content = text or ""
    return UserMemorySnapshot(content=content, revision=revision_of(content), length=len(content))


def _lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if line.strip()}


def _refuse(before: UserMemorySnapshot, error: str, reason: str | None = None) -> WritePlan:
    return WritePlan(
        None, UserMemoryWriteResult(STATUS_REFUSED, before, error=error, reason=reason)
    )


def plan_append(current: str | None, line: str) -> WritePlan:
    """Add one entry at the end, unless it is empty, secret-like, already there or too long."""
    before = snapshot_of(current)
    entry = line.strip()
    if not entry:
        return _refuse(before, EMPTY_APPEND)
    reason = find_secret_like(entry)
    if reason is not None:
        return _refuse(before, SECRET_REFUSAL, reason)
    if _lines(entry) <= _lines(before.content):
        return WritePlan(None, UserMemoryWriteResult(STATUS_UNCHANGED, before))
    base = before.content.rstrip()
    text = f"{base}\n{entry}" if base else entry
    if len(text) > MAX_USER_MEMORY_LENGTH:
        return _refuse(before, APPEND_TOO_LONG)
    return WritePlan(text, UserMemoryWriteResult(STATUS_ADDED, snapshot_of(text)))


def plan_replace(current: str | None, content: str, revision: str) -> WritePlan:
    """Rewrite the text if the caller read the current revision; only new lines are checked."""
    before = snapshot_of(current)
    if revision != before.revision:
        return WritePlan(
            None,
            UserMemoryWriteResult(STATUS_CONFLICT, before, next_step=CONFLICT_NEXT_STEP),
        )
    text = content.strip()
    if len(text) > MAX_USER_MEMORY_LENGTH:
        return _refuse(before, REPLACE_TOO_LONG)
    added = "\n".join(sorted(_lines(text) - _lines(before.content)))
    reason = find_secret_like(added) if added else None
    if reason is not None:
        return _refuse(before, SECRET_REFUSAL, reason)
    if text == before.content.strip():
        return WritePlan(None, UserMemoryWriteResult(STATUS_UNCHANGED, before))
    return WritePlan(text, UserMemoryWriteResult(STATUS_REPLACED, snapshot_of(text)))


async def read_user_memory(db: AsyncSession, user_id: uuid.UUID) -> UserMemorySnapshot:
    """The stored text as it is now, not as the caller's loaded User object last saw it."""
    result = await db.execute(select(User.user_rules).where(User.id == user_id))
    return snapshot_of(result.scalar_one_or_none())


async def _apply(
    db: AsyncSession, user_id: uuid.UUID, plan_for: Callable[[str | None], WritePlan]
) -> UserMemoryWriteResult:
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    user = result.scalar_one()
    plan = plan_for(user.user_rules)
    if plan.text is not None:
        user.user_rules = plan.text or None
    # Commit refusals too: the lock must not outlive this call.
    await db.commit()
    return plan.result


async def append_user_memory(
    db: AsyncSession, user_id: uuid.UUID, line: str
) -> UserMemoryWriteResult:
    """Append one line to the user's memory and commit."""
    return await _apply(db, user_id, lambda current: plan_append(current, line))


async def replace_user_memory(
    db: AsyncSession, user_id: uuid.UUID, content: str, revision: str
) -> UserMemoryWriteResult:
    """Replace the user's memory if `revision` is current, and commit."""
    return await _apply(db, user_id, lambda current: plan_replace(current, content, revision))
