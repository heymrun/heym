"""Unit tests for IMAP trigger polling and execution history."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import ExecutionHistory
from app.services.imap_trigger_service import ImapCursor, ImapTriggerManager
from app.services.workflow_executor import ExecutionResult, SubWorkflowExecution


class ImapTriggerManagerPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_should_poll_respects_interval_minutes(self) -> None:
        manager = ImapTriggerManager()
        now = datetime.now(timezone.utc)
        key = "wf_node"
        node = {"data": {"pollIntervalMinutes": 5}}

        manager._last_poll_at[key] = now - timedelta(minutes=4)
        self.assertFalse(manager._should_poll_node(key, now, node))

        manager._last_poll_at[key] = now - timedelta(minutes=5, seconds=1)
        self.assertTrue(manager._should_poll_node(key, now, node))

    async def test_poll_workflow_node_executes_each_new_email(self) -> None:
        manager = ImapTriggerManager()
        workflow = SimpleNamespace(id=uuid.uuid4())
        node = {
            "id": "imap-node",
            "type": "imapTrigger",
            "data": {"credentialId": str(uuid.uuid4()), "pollIntervalMinutes": 5},
        }
        emails = [
            {"uid": "101", "subject": "First"},
            {"uid": "102", "subject": "Second"},
        ]

        with (
            patch.object(
                manager,
                "_load_credential_config",
                AsyncMock(return_value={"imap_host": "imap.example.com"}),
            ),
            patch.object(
                manager,
                "_fetch_node_messages",
                AsyncMock(return_value=(ImapCursor(uidvalidity="1", last_uid=102), emails)),
            ),
            patch.object(manager, "_execute_workflow_for_email", AsyncMock()) as mock_execute,
        ):
            await manager._poll_workflow_node(workflow, node)

        self.assertEqual(
            manager._cursors[manager._get_node_key(workflow.id, "imap-node")].last_uid,
            102,
        )
        self.assertEqual(mock_execute.await_count, 2)
        mock_execute.assert_any_await(workflow, "imap-node", emails[0])
        mock_execute.assert_any_await(workflow, "imap-node", emails[1])


class ImapTriggerExecutionHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_workflow_persists_imap_trigger_source(self) -> None:
        manager = ImapTriggerManager()
        owner_id = uuid.uuid4()
        workflow_id = uuid.uuid4()
        sub_workflow_id = uuid.uuid4()
        workflow = SimpleNamespace(
            id=workflow_id,
            owner_id=owner_id,
            name="Inbox workflow",
            nodes=[],
            edges=[],
        )

        added_rows: list[object] = []

        def add_row(row: object) -> None:
            added_rows.append(row)

        db = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: workflow)),
            add=add_row,
            commit=AsyncMock(),
        )
        execution_result = ExecutionResult(
            workflow_id=workflow_id,
            status="success",
            outputs={"ok": True},
            execution_time_ms=14.2,
            node_results=[],
            sub_workflow_executions=[
                SubWorkflowExecution(
                    workflow_id=str(sub_workflow_id),
                    inputs={"source": "imap"},
                    outputs={"done": True},
                    status="success",
                    execution_time_ms=4.1,
                    node_results=[],
                    workflow_name="Child workflow",
                )
            ],
        )

        email_payload = {
            "uid": "123",
            "subject": "New ticket",
            "from": "customer@example.com",
            "text": "Please help",
        }

        with (
            patch("app.services.imap_trigger_service.async_session_maker") as mock_session_maker,
            patch(
                "app.services.imap_trigger_service.collect_referenced_workflows",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.imap_trigger_service.get_credentials_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.imap_trigger_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "app.services.imap_trigger_service.execute_workflow",
                return_value=execution_result,
            ),
            patch(
                "app.services.imap_trigger_service.upsert_workflow_analytics_snapshot",
                AsyncMock(),
            ),
            patch(
                "app.services.imap_trigger_service._persist_global_variables_from_execution",
                AsyncMock(),
            ),
        ):
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = db
            mock_session.__aexit__.return_value = None
            mock_session_maker.return_value = mock_session

            await manager._execute_workflow_for_email(workflow, "imap-node", email_payload)

        history_rows = [row for row in added_rows if isinstance(row, ExecutionHistory)]
        self.assertEqual(len(history_rows), 2)
        parent = next(r for r in history_rows if r.workflow_id == workflow_id)
        child = next(r for r in history_rows if r.workflow_id == sub_workflow_id)
        self.assertEqual(parent.trigger_source, "imap")
        self.assertEqual(child.trigger_source, "SUB_WORKFLOW")
        self.assertEqual(parent.inputs["triggered_by"], "imap")
        self.assertEqual(parent.inputs["email"]["subject"], "New ticket")


if __name__ == "__main__":
    unittest.main()
