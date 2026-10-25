"""A migrated PostgreSQL database with one throwaway user and workflow per test.

Like test_cluster_trace_context_postgres.py, only connection failures skip; a
reachable database with an outdated schema must fail.
"""

import asyncio
import unittest
import uuid

from asyncpg import CannotConnectNowError, PostgresConnectionError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError

from app.db.models import (
    ExecutionHistory,
    User,
    Workflow,
    WorkflowAnalyticsSnapshot,
    WorkflowConcurrencySlot,
    WorkflowRunQueue,
)
from app.db.session import async_session_maker, engine
from app.services.workflow_concurrency import HeldRun


class ConcurrencyPostgresCase(unittest.IsolatedAsyncioTestCase):
    limit: int | None = 1
    max_queue: int | None = None
    max_wait_seconds: int | None = None

    async def asyncSetUp(self) -> None:
        await engine.dispose()
        try:
            async with asyncio.timeout(10):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except (OSError, TimeoutError, PostgresConnectionError, CannotConnectNowError) as exc:
            await engine.dispose()
            self.skipTest(f"PostgreSQL is unavailable ({type(exc).__name__})")
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", "") or ""
            if (
                not exc.connection_invalidated
                and not sqlstate.startswith("08")
                and sqlstate != "57P03"
            ):
                raise
            await engine.dispose()
            self.skipTest("PostgreSQL connection is unavailable")
        self.user_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.addAsyncCleanup(self._remove_fixture)
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"concurrency-{self.user_id.hex}@example.com",
                    hashed_password="test-only",
                    name="Concurrency fixture",
                )
            )
            await db.flush()
            db.add(
                Workflow(
                    id=self.workflow_id,
                    owner_id=self.user_id,
                    name="Concurrency fixture",
                    nodes=[],
                    edges=[],
                    concurrency_limit=self.limit,
                    concurrency_max_queue=self.max_queue,
                    concurrency_max_wait_seconds=self.max_wait_seconds,
                )
            )
            await db.commit()

    async def _remove_fixture(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(WorkflowConcurrencySlot).where(
                    WorkflowConcurrencySlot.workflow_id == self.workflow_id
                )
            )
            await db.execute(
                delete(WorkflowRunQueue).where(WorkflowRunQueue.workflow_id == self.workflow_id)
            )
            await db.execute(
                delete(ExecutionHistory).where(ExecutionHistory.workflow_id == self.workflow_id)
            )
            await db.execute(
                delete(WorkflowAnalyticsSnapshot).where(
                    WorkflowAnalyticsSnapshot.workflow_id == self.workflow_id
                )
            )
            await db.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await db.execute(delete(User).where(User.id == self.user_id))
            await db.commit()
        await engine.dispose()

    def held_run(self, **overrides: object) -> HeldRun:
        values: dict[str, object] = {
            "workflow_id": self.workflow_id,
            "execution_id": uuid.uuid4(),
            "placement": "anywhere",
            "inputs": {"body": {}},
            "trigger_source": "API",
            "actor_user_id": self.user_id,
            "credentials_owner_id": self.user_id,
        }
        values.update(overrides)
        return HeldRun(**values)  # type: ignore[arg-type]

    async def set_limit(self, limit: int | None) -> None:
        async with async_session_maker() as db:
            workflow = await db.get(Workflow, self.workflow_id)
            assert workflow is not None
            workflow.concurrency_limit = limit
            await db.commit()

    async def queue_row(self, execution_id: uuid.UUID) -> WorkflowRunQueue | None:
        async with async_session_maker() as db:
            return (
                await db.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == execution_id)
                )
            ).scalar_one_or_none()

    async def slot_count(self) -> int:
        async with async_session_maker() as db:
            return int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(WorkflowConcurrencySlot)
                        .where(WorkflowConcurrencySlot.workflow_id == self.workflow_id)
                    )
                ).scalar_one()
            )
