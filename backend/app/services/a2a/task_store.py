"""A2A tasks in `a2a_tasks`, always read and written within one user's surface.

A surface is the global MCP server (`server_id` None) or one named server. Every
statement filters on both, so a task from another user or another server looks exactly
like one that does not exist.

Each call opens and commits its own session: a task row must be visible to the next
request (GetTask, SubscribeToTask) as soon as it is written, not when the request that
wrote it finishes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import and_, func, select, update
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import A2ATask, DashboardConversation, DashboardMessage
from app.db.session import async_session_maker
from app.services.a2a.models import TaskState

STARTABLE_STATES = frozenset(
    {TaskState.SUBMITTED, TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED}
)
CANCELABLE_STATES = frozenset(
    {TaskState.SUBMITTED, TaskState.WORKING, TaskState.INPUT_REQUIRED, TaskState.AUTH_REQUIRED}
)


@dataclass(frozen=True)
class TaskScope:
    user_id: uuid.UUID
    server_id: uuid.UUID | None


@dataclass(frozen=True)
class TaskRecord:
    id: uuid.UUID
    context_id: uuid.UUID
    state: TaskState
    status_message: str | None
    artifacts: dict[str, Any] | None
    updated_at: datetime


@dataclass(frozen=True)
class HistoryEntry:
    id: uuid.UUID
    role: str
    content: str


@dataclass(frozen=True)
class TaskQuery:
    context_id: uuid.UUID | None
    state: TaskState | None
    updated_after: datetime | None
    offset: int
    limit: int


@dataclass(frozen=True)
class TaskPage:
    tasks: list[TaskRecord]
    total: int


class TaskStore(Protocol):
    async def create(self, scope: TaskScope, context_id: uuid.UUID) -> TaskRecord: ...

    async def get(self, scope: TaskScope, task_id: uuid.UUID) -> TaskRecord | None: ...

    async def start(self, scope: TaskScope, task_id: uuid.UUID) -> bool: ...

    async def finish(
        self,
        task_id: uuid.UUID,
        state: TaskState,
        status_message: str | None,
        artifacts: dict[str, Any] | None,
    ) -> bool: ...

    async def cancel(self, scope: TaskScope, task_id: uuid.UUID) -> TaskRecord | None: ...

    async def list(self, scope: TaskScope, query: TaskQuery) -> TaskPage: ...

    async def history(self, task_id: uuid.UUID, limit: int) -> list[HistoryEntry]: ...

    async def owns_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool: ...


def scope_clause(scope: TaskScope) -> ColumnElement[bool]:
    """The user and the surface, both, in every statement."""
    server_match = (
        A2ATask.mcp_server_id.is_(None)
        if scope.server_id is None
        else A2ATask.mcp_server_id == scope.server_id
    )
    return and_(A2ATask.user_id == scope.user_id, server_match)


def _states(states: frozenset[TaskState]) -> list[str]:
    return sorted(state.value for state in states)


def _record(row: A2ATask) -> TaskRecord:
    return TaskRecord(
        id=row.id,
        context_id=row.context_id,
        state=TaskState(row.state),
        status_message=row.status_message,
        artifacts=row.artifacts,
        updated_at=row.updated_at,
    )


class SqlTaskStore:
    """`TaskStore` on PostgreSQL."""

    def __init__(self, session_factory: Callable[[], Any] = async_session_maker) -> None:
        self._sessions = session_factory

    async def create(self, scope: TaskScope, context_id: uuid.UUID) -> TaskRecord:
        row = A2ATask(
            id=uuid.uuid4(),
            user_id=scope.user_id,
            mcp_server_id=scope.server_id,
            context_id=context_id,
            state=TaskState.SUBMITTED.value,
        )
        async with self._sessions() as db:
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return _record(row)

    async def get(self, scope: TaskScope, task_id: uuid.UUID) -> TaskRecord | None:
        async with self._sessions() as db:
            result = await db.execute(
                select(A2ATask).where(A2ATask.id == task_id, scope_clause(scope))
            )
            row = result.scalar_one_or_none()
            return _record(row) if row is not None else None

    async def start(self, scope: TaskScope, task_id: uuid.UUID) -> bool:
        async with self._sessions() as db:
            result = await db.execute(
                update(A2ATask)
                .where(
                    A2ATask.id == task_id,
                    scope_clause(scope),
                    A2ATask.state.in_(_states(STARTABLE_STATES)),
                )
                .values(state=TaskState.WORKING.value, status_message=None)
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            return result.rowcount == 1

    async def finish(
        self,
        task_id: uuid.UUID,
        state: TaskState,
        status_message: str | None,
        artifacts: dict[str, Any] | None,
    ) -> bool:
        async with self._sessions() as db:
            result = await db.execute(
                update(A2ATask)
                .where(A2ATask.id == task_id, A2ATask.state == TaskState.WORKING.value)
                .values(state=state.value, status_message=status_message, artifacts=artifacts)
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            return result.rowcount == 1

    async def cancel(self, scope: TaskScope, task_id: uuid.UUID) -> TaskRecord | None:
        async with self._sessions() as db:
            result = await db.execute(
                update(A2ATask)
                .where(
                    A2ATask.id == task_id,
                    scope_clause(scope),
                    A2ATask.state.in_(_states(CANCELABLE_STATES)),
                )
                .values(state=TaskState.CANCELED.value, status_message="Canceled.")
                .returning(A2ATask)
                .execution_options(synchronize_session=False)
            )
            row = result.scalar_one_or_none()
            record = _record(row) if row is not None else None
            await db.commit()
            return record

    async def list(self, scope: TaskScope, query: TaskQuery) -> TaskPage:
        conditions = [scope_clause(scope)]
        if query.context_id is not None:
            conditions.append(A2ATask.context_id == query.context_id)
        if query.state is not None:
            conditions.append(A2ATask.state == query.state.value)
        if query.updated_after is not None:
            conditions.append(A2ATask.updated_at > query.updated_after)
        async with self._sessions() as db:
            total = await db.scalar(select(func.count()).select_from(A2ATask).where(*conditions))
            result = await db.execute(
                select(A2ATask)
                .where(*conditions)
                .order_by(A2ATask.updated_at.desc(), A2ATask.id.desc())
                .offset(query.offset)
                .limit(query.limit)
            )
            return TaskPage([_record(row) for row in result.scalars().all()], int(total or 0))

    async def history(self, task_id: uuid.UUID, limit: int) -> list[HistoryEntry]:
        async with self._sessions() as db:
            result = await db.execute(
                select(DashboardMessage.id, DashboardMessage.role, DashboardMessage.content)
                .where(DashboardMessage.a2a_task_id == task_id)
                .order_by(DashboardMessage.created_at.desc())
                .limit(limit)
            )
            rows = list(result.all())
        return [HistoryEntry(row.id, row.role, row.content) for row in reversed(rows)]

    async def owns_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        async with self._sessions() as db:
            found = await db.scalar(
                select(DashboardConversation.id).where(
                    DashboardConversation.id == conversation_id,
                    DashboardConversation.user_id == user_id,
                )
            )
            return found is not None
