"""Trace context survives the real PostgreSQL enqueue/claim boundary.

Like the execution-registry resilience tests, this suite requires a migrated
PostgreSQL test database. Each test owns and removes only its random fixture rows.
"""

import asyncio
import threading
import unittest
import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from asyncpg import CannotConnectNowError, PostgresConnectionError
from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.db.models import User, Workflow, WorkflowRunQueue
from app.db.session import async_session_maker, engine
from app.observability import tracing
from app.services.cluster import run_queue
from app.services.cluster.dispatch import RunQueueWorker, dispatch_workflow


class QueueTraceContextPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        # Only connection failures are optional; a reachable database with an
        # outdated schema or a failing queue operation must fail the test.
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
        self.target = f"trace-test-{uuid.uuid4().hex}"
        self.nodes = [
            {
                "id": "seed",
                "type": "set",
                "data": {"label": "seed", "mappings": [{"key": "answer", "value": "42"}]},
            }
        ]
        self.addAsyncCleanup(self._remove_fixture)
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"trace-{self.user_id.hex}@example.com",
                    hashed_password="test-only",
                    name="Trace fixture",
                )
            )
            db.add(
                Workflow(
                    id=self.workflow_id,
                    owner_id=self.user_id,
                    name="Queue tracing fixture",
                    nodes=self.nodes,
                    edges=[],
                )
            )
            await db.commit()
        self.exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.addCleanup(provider.shutdown)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(trace, "_TRACER_PROVIDER", provider))
        self.stack.enter_context(patch.object(tracing, "_provider", provider))
        self.tracer = provider.get_tracer("queue-postgres-test")
        self.stack.enter_context(
            patch.object(run_queue, "async_session_maker", async_session_maker)
        )
        self.stack.enter_context(
            patch.object(run_queue, "choose_target", new=AsyncMock(return_value=self.target))
        )
        self.stack.enter_context(patch.object(run_queue, "notify_queue", new=AsyncMock()))
        self.stack.enter_context(patch.object(run_queue, "notify_done", new=AsyncMock()))
        for target in (
            "app.api.workflows.get_credentials_context",
            "app.api.workflows.collect_referenced_workflows",
            "app.services.global_variables_service.get_global_variables_context",
        ):
            self.stack.enter_context(patch(target, new=AsyncMock(return_value={})))
        self.stack.enter_context(
            patch(
                "app.services.cluster.dispatch.register_execution",
                side_effect=lambda **_kwargs: threading.Event(),
            )
        )
        self.stack.enter_context(
            patch("app.services.cluster.dispatch.get_active_execution_handle", return_value=None)
        )
        self.stack.enter_context(patch("app.services.cluster.dispatch.relinquish_execution"))
        self.stack.enter_context(patch("app.services.cluster.dispatch.complete_execution"))
        self.stack.enter_context(
            patch("app.services.hitl_service.build_default_public_base_url", return_value="")
        )
        self.stack.enter_context(
            patch("app.services.cluster.dispatch.persist_run_history", new=AsyncMock())
        )

    async def _remove_fixture(self) -> None:
        try:
            async with async_session_maker() as db:
                await db.execute(
                    delete(WorkflowRunQueue).where(WorkflowRunQueue.workflow_id == self.workflow_id)
                )
                await db.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
                await db.execute(delete(User).where(User.id == self.user_id))
                await db.commit()
        finally:
            await engine.dispose()

    async def test_dispatch_commit_claim_and_execute_preserve_parent_and_support_legacy_rows(
        self,
    ) -> None:
        execution_id = uuid.uuid4()
        inputs = {"business": "unchanged"}
        with (
            self.tracer.start_as_current_span(
                "producer", context=otel_context.Context()
            ) as producer,
            patch("app.services.cluster.dispatch.settings.cluster_enabled", True),
            patch("app.services.cluster.dispatch.identity.is_main", return_value=False),
        ):
            await dispatch_workflow(
                workflow_id=self.workflow_id,
                execution_id=execution_id,
                nodes=self.nodes,
                edges=[],
                inputs=inputs,
                wait_for_completion=False,
            )
        parent = producer.get_span_context()
        expected_carrier = {
            "traceparent": f"00-{parent.trace_id:032x}-{parent.span_id:016x}-{parent.trace_flags:02x}"
        }
        # This is a new session, after enqueue's commit, not the producer's object.
        async with async_session_maker() as db:
            stored = (
                await db.execute(
                    select(WorkflowRunQueue).where(WorkflowRunQueue.execution_id == execution_id)
                )
            ).scalar_one()
            self.assertEqual(stored.trace_context, expected_carrier)
            self.assertEqual(stored.inputs, inputs)
            self.assertEqual(stored.status, run_queue.STATUS_QUEUED)
        claimed = await run_queue.claim_next(self.target)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.execution_id, execution_id)
        self.assertEqual(claimed.trace_context, expected_carrier)
        self.assertEqual(claimed.status, run_queue.STATUS_CLAIMED)
        with self.tracer.start_as_current_span(
            "consumer", context=otel_context.Context()
        ) as sentinel:
            await RunQueueWorker()._execute_claimed(claimed)
            self.assertEqual(
                trace.get_current_span().get_span_context(), sentinel.get_span_context()
            )
        async with async_session_maker() as db:
            completed = await db.get(WorkflowRunQueue, claimed.id)
            self.assertEqual(completed.status, run_queue.STATUS_DONE)
            self.assertEqual(completed.result["status"], "success")
            self.assertEqual(completed.inputs, inputs)
            self.assertEqual(completed.trace_context, expected_carrier)
        workflow_span = next(
            span
            for span in self.exporter.get_finished_spans()
            if span.name == "heym.workflow.execute"
        )
        self.assertEqual(workflow_span.context.trace_id, parent.trace_id)
        self.assertEqual(workflow_span.parent.span_id, parent.span_id)
        self.assertTrue(workflow_span.parent.is_remote)
        node_span = next(
            span for span in self.exporter.get_finished_spans() if span.name == "heym.node.execute"
        )
        self.assertEqual(node_span.parent.span_id, workflow_span.context.span_id)

        # An old writer omits the column altogether after the schema upgrade.
        legacy_run = run_queue.QueuedRun(
            workflow_id=self.workflow_id,
            execution_id=uuid.uuid4(),
            placement="anywhere",
            inputs={"legacy": True},
            trigger_source="api",
            actor_user_id=None,
            credentials_owner_id=None,
            test_run=False,
            timeout_seconds=None,
            return_on_chart_output=False,
        )
        values = run_queue.build_queue_values(
            legacy_run, target_instance_id=self.target, grace_seconds=60
        )
        values.pop("trace_context")
        async with async_session_maker() as db:
            await db.execute(WorkflowRunQueue.__table__.insert().values(**values))
            await db.commit()
        legacy = await run_queue.claim_next(self.target)
        self.assertIsNone(legacy.trace_context)
        self.exporter.clear()
        with self.tracer.start_as_current_span(
            "unrelated", context=otel_context.Context()
        ) as unrelated:
            await RunQueueWorker()._execute_claimed(legacy)
            self.assertEqual(
                trace.get_current_span().get_span_context(), unrelated.get_span_context()
            )
        root = next(
            span
            for span in self.exporter.get_finished_spans()
            if span.name == "heym.workflow.execute"
        )
        self.assertIsNone(root.parent)
        self.assertNotEqual(root.context.trace_id, parent.trace_id)
        self.assertNotEqual(root.context.trace_id, unrelated.get_span_context().trace_id)
        async with async_session_maker() as db:
            completed = await db.get(WorkflowRunQueue, legacy.id)
            self.assertEqual(completed.result["status"], "success")
            self.assertEqual(completed.inputs, {"legacy": True})
