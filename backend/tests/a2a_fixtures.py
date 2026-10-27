"""Shared A2A test helpers: an in-memory task store and a real PostgreSQL case."""

from __future__ import annotations

import asyncio
import secrets
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from asyncpg import CannotConnectNowError, PostgresConnectionError
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError

from app.db.models import DashboardConversation, MCPServer, User
from app.db.session import async_session_maker, engine
from app.services.a2a.models import TaskState
from app.services.a2a.task_store import (
    CANCELABLE_STATES,
    STARTABLE_STATES,
    HistoryEntry,
    TaskPage,
    TaskQuery,
    TaskRecord,
    TaskScope,
)
from app.services.secret_tokens import hash_secret


class MemoryTaskStore:
    """`TaskStore` in memory, with the same scoping and conditional transitions."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, tuple[TaskScope, TaskRecord]] = {}
        self.conversations: dict[uuid.UUID, uuid.UUID] = {}
        self.messages: dict[uuid.UUID, list[HistoryEntry]] = {}
        self._clock = datetime(2026, 10, 27, tzinfo=timezone.utc)

    def _tick(self) -> datetime:
        self._clock += timedelta(seconds=1)
        return self._clock

    def _visible(self, scope: TaskScope, task_id: uuid.UUID) -> TaskRecord | None:
        row = self.rows.get(task_id)
        if row is None or row[0] != scope:
            return None
        return row[1]

    def _put(self, scope: TaskScope, record: TaskRecord) -> TaskRecord:
        self.rows[record.id] = (scope, record)
        return record

    async def create(self, scope: TaskScope, context_id: uuid.UUID) -> TaskRecord:
        record = TaskRecord(uuid.uuid4(), context_id, TaskState.SUBMITTED, None, None, self._tick())
        return self._put(scope, record)

    async def get(self, scope: TaskScope, task_id: uuid.UUID) -> TaskRecord | None:
        return self._visible(scope, task_id)

    async def start(self, scope: TaskScope, task_id: uuid.UUID) -> bool:
        record = self._visible(scope, task_id)
        if record is None or record.state not in STARTABLE_STATES:
            return False
        self._put(
            scope,
            replace(record, state=TaskState.WORKING, status_message=None, updated_at=self._tick()),
        )
        return True

    async def finish(
        self,
        task_id: uuid.UUID,
        state: TaskState,
        status_message: str | None,
        artifacts: dict[str, Any] | None,
    ) -> bool:
        scope, record = self.rows[task_id]
        if record.state is not TaskState.WORKING:
            return False
        self._put(
            scope,
            replace(
                record,
                state=state,
                status_message=status_message,
                artifacts=artifacts,
                updated_at=self._tick(),
            ),
        )
        return True

    async def cancel(self, scope: TaskScope, task_id: uuid.UUID) -> TaskRecord | None:
        record = self._visible(scope, task_id)
        if record is None or record.state not in CANCELABLE_STATES:
            return None
        return self._put(
            scope,
            replace(
                record,
                state=TaskState.CANCELED,
                status_message="Canceled.",
                updated_at=self._tick(),
            ),
        )

    async def list(self, scope: TaskScope, query: TaskQuery) -> TaskPage:
        records = [record for owner, record in self.rows.values() if owner == scope]
        if query.context_id is not None:
            records = [r for r in records if r.context_id == query.context_id]
        if query.state is not None:
            records = [r for r in records if r.state is query.state]
        if query.updated_after is not None:
            records = [r for r in records if r.updated_at > query.updated_after]
        records.sort(key=lambda r: r.updated_at, reverse=True)
        return TaskPage(records[query.offset : query.offset + query.limit], len(records))

    async def history(self, task_id: uuid.UUID, limit: int) -> list[HistoryEntry]:
        return self.messages.get(task_id, [])[-limit:]

    async def owns_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        return self.conversations.get(conversation_id) == user_id


async def _postgres_unavailable() -> str | None:
    """None when PostgreSQL answers, else why it does not. Only connection failures skip."""
    await engine.dispose()
    try:
        async with asyncio.timeout(10):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except (OSError, TimeoutError, PostgresConnectionError, CannotConnectNowError) as exc:
        await engine.dispose()
        return f"PostgreSQL is unavailable ({type(exc).__name__})"
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", "") or ""
        if not exc.connection_invalidated and not sqlstate.startswith("08") and sqlstate != "57P03":
            raise
        await engine.dispose()
        return "PostgreSQL connection is unavailable"
    return None


class A2APostgresCase(unittest.IsolatedAsyncioTestCase):
    """Two users, each with a conversation; the first also has a named server and a key."""

    async def asyncSetUp(self) -> None:
        reason = await _postgres_unavailable()
        if reason is not None:
            self.skipTest(reason)
        self.user_id, self.other_user_id = uuid.uuid4(), uuid.uuid4()
        self.server_id = uuid.uuid4()
        self.conversation_id, self.other_conversation_id = uuid.uuid4(), uuid.uuid4()
        self.global_key = secrets.token_hex(32)
        self.server_key = secrets.token_urlsafe(48)
        self.addAsyncCleanup(self._remove_fixture)
        async with async_session_maker() as db:
            for user_id in (self.user_id, self.other_user_id):
                db.add(
                    User(
                        id=user_id,
                        email=f"a2a-{user_id.hex}@example.com",
                        hashed_password="test-only",
                        name="A2A fixture",
                        mcp_api_key=(
                            hash_secret(self.global_key) if user_id == self.user_id else None
                        ),
                    )
                )
            await db.flush()
            db.add(
                MCPServer(
                    id=self.server_id,
                    user_id=self.user_id,
                    name="Acme payroll",
                    api_key=hash_secret(self.server_key),
                )
            )
            db.add(DashboardConversation(id=self.conversation_id, user_id=self.user_id, title="t"))
            db.add(
                DashboardConversation(
                    id=self.other_conversation_id, user_id=self.other_user_id, title="t"
                )
            )
            await db.commit()

    async def _remove_fixture(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(User).where(User.id.in_([self.user_id, self.other_user_id])))
            await db.commit()
        await engine.dispose()
