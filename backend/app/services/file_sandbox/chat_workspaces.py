"""Conversation workspaces: deleted with the chat, on request, or after 30 idle days.

A chat's workspace survives across turns so follow-up requests (fine-tuning a
workflow that was just built) find their mounted files and cached results. The
idle sweep covers conversations nobody deletes, such as MCP ``heym_chat`` ones.
It runs only on the main instance, which is where chat turns and their
workspaces live.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from app.services.file_sandbox.limits import (
    CHAT_WORKSPACE_IDLE_DAYS,
    CHAT_WORKSPACE_SWEEP_INTERVAL_SECONDS,
)
from app.services.file_sandbox.workspace import FileWorkspace, sandbox_root

logger = logging.getLogger(__name__)


def delete_chat_workspace(user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
    """Remove one conversation's workspace, if it has one."""
    FileWorkspace.for_chat(user_id, conversation_id).delete()


def delete_chat_workspaces(user_id: uuid.UUID, conversation_ids: Iterable[uuid.UUID]) -> None:
    """Remove the workspaces of several of the user's conversations."""
    for conversation_id in conversation_ids:
        delete_chat_workspace(user_id, conversation_id)


def delete_all_chat_workspaces(user_id: uuid.UUID) -> None:
    """Remove every conversation workspace of one user."""
    shutil.rmtree(sandbox_root() / "chats" / user_id.hex, ignore_errors=True)


def sweep_idle_chat_workspaces(now: datetime | None = None) -> int:
    """Delete conversation workspaces unused for ``CHAT_WORKSPACE_IDLE_DAYS``; return the count."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=CHAT_WORKSPACE_IDLE_DAYS)
    chats = sandbox_root() / "chats"
    removed = 0
    if not chats.is_dir():
        return 0
    for user_dir in chats.iterdir():
        if not user_dir.is_dir() or user_dir.is_symlink():
            continue
        for conversation_dir in user_dir.iterdir():
            if not conversation_dir.is_dir() or conversation_dir.is_symlink():
                continue
            try:
                owner = uuid.UUID(user_dir.name)
            except ValueError:
                continue
            workspace = FileWorkspace(conversation_dir, owner_id=owner)
            last_used = workspace.last_used_at()
            if last_used is None:
                last_used = datetime.fromtimestamp(conversation_dir.stat().st_mtime, timezone.utc)
            if last_used < cutoff:
                workspace.delete()
                removed += 1
        try:
            user_dir.rmdir()
        except OSError:
            pass
    return removed


async def run_idle_sweeper() -> None:
    """Sweep idle conversation workspaces on the main instance, forever."""
    from app.services.cluster.identity import is_main

    while True:
        try:
            if is_main():
                removed = await asyncio.to_thread(sweep_idle_chat_workspaces)
                if removed:
                    logger.info("Removed %d idle chat file workspaces", removed)
        except Exception:
            logger.exception("Chat file workspace sweep failed")
        await asyncio.sleep(CHAT_WORKSPACE_SWEEP_INTERVAL_SECONDS)
