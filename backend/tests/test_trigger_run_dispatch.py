"""Shared dispatch for background triggers: start the run, then persist its history."""

import logging
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import ExecutionHistory
from app.services.trigger_run_dispatch import (
    TriggerDispatchNotStartedError,
    run_trigger_workflow,
)
from app.services.workflow_executor import ExecutionResult, SubWorkflowExecution

_MODULE = "app.services.trigger_run_dispatch"
_LOG = logging.getLogger("test_trigger_run_dispatch")


def _patched(execution_result: ExecutionResult, session_maker: object) -> tuple:
    return (
        patch(f"{_MODULE}.async_session_maker", session_maker),
        patch(f"{_MODULE}.collect_referenced_workflows", AsyncMock(return_value={})),
        patch(f"{_MODULE}.get_credentials_context", AsyncMock(return_value={})),
        patch(f"{_MODULE}.get_global_variables_context", AsyncMock(return_value={})),
        patch(f"{_MODULE}.dispatch_workflow", AsyncMock(return_value=execution_result)),
        patch(f"{_MODULE}.upsert_workflow_analytics_snapshot", AsyncMock()),
        patch(f"{_MODULE}._persist_global_variables_from_execution", AsyncMock()),
    )


class RunTriggerWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def _session(self, workflow: object, added_rows: list) -> AsyncMock:
        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow)),
            add=added_rows.append,
            commit=AsyncMock(),
        )
        session = AsyncMock()
        session.__aenter__.return_value = db
        session.__aexit__.return_value = None
        return session

    async def _run(self, trigger_source: str, inputs: dict, sub_runs: list) -> list:
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id, owner_id=owner_id, name="wf", nodes=[], edges=[], concurrency_limit=None
        )
        result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=14.2,
            node_results=[],
            sub_workflow_executions=sub_runs,
        )
        added: list = []

        def session_maker() -> AsyncMock:
            return self._session(workflow, added)

        for active in _patched(result, session_maker):
            active.start()
            self.addCleanup(active.stop)
        await run_trigger_workflow(
            workflow_id=workflow_id,
            inputs=inputs,
            trigger_source=trigger_source,
            trigger_label="Test trigger",
            log=_LOG,
        )
        self.workflow_id = workflow_id
        return [row for row in added if isinstance(row, ExecutionHistory)]

    async def test_persists_the_trigger_source_and_sub_workflow_history(self) -> None:
        sub_id = uuid.uuid4()
        rows = await self._run(
            "imap",
            {"triggered_by": "imap", "trigger_node_id": "imap-node", "email": {"subject": "Hi"}},
            [
                SubWorkflowExecution(
                    workflow_id=str(sub_id),
                    inputs={"source": "imap"},
                    outputs={"done": True},
                    status="success",
                    execution_time_ms=4.1,
                    node_results=[],
                    workflow_name="Child workflow",
                )
            ],
        )
        self.assertEqual(len(rows), 2)
        parent = next(row for row in rows if row.workflow_id == self.workflow_id)
        child = next(row for row in rows if row.workflow_id == sub_id)
        self.assertEqual(parent.trigger_source, "imap")
        self.assertEqual(child.trigger_source, "SUB_WORKFLOW")
        self.assertEqual(parent.inputs["email"]["subject"], "Hi")

    async def test_google_sheets_runs_record_their_source(self) -> None:
        rows = await self._run(
            "google_sheets", {"triggered_by": "google_sheets", "change": {"event": "created"}}, []
        )
        self.assertEqual(rows[0].trigger_source, "google_sheets")
        self.assertEqual(rows[0].inputs["change"]["event"], "created")

    async def test_failure_before_dispatch_is_retriable(self) -> None:
        db = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("db unreachable")))
        session = AsyncMock()
        session.__aenter__.return_value = db
        session.__aexit__.return_value = None
        with (
            patch(f"{_MODULE}.async_session_maker", return_value=session),
            patch(f"{_MODULE}.dispatch_workflow", AsyncMock()) as dispatch,
        ):
            with self.assertRaises(TriggerDispatchNotStartedError):
                await run_trigger_workflow(
                    workflow_id=uuid.uuid4(),
                    inputs={},
                    trigger_source="imap",
                    trigger_label="IMAP trigger",
                    log=_LOG,
                )
        dispatch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
