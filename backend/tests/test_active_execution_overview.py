import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import ActiveExecutionItem
from app.services import active_execution_overview as overview_module
from app.services.active_execution_overview import (
    build_active_execution_overview,
    collect_active_executions_for_user,
    format_duration,
)

MODULE = "app.services.active_execution_overview"


def _rows(items):
    result = MagicMock()
    result.all.return_value = items
    return result


def _active_record(**kwargs):
    defaults = {
        "execution_id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "workflow_name": "Nightly report",
        "started_at": datetime.now(timezone.utc) - timedelta(seconds=95),
        "inputs": {},
        "running_node_ids": [],
        "node_results": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestFormatDuration(unittest.TestCase):
    def test_seconds_only(self):
        self.assertEqual(format_duration(42), "42s")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_duration(95), "1m 35s")

    def test_hours_and_minutes(self):
        self.assertEqual(format_duration(3 * 3600 + 25 * 60 + 9), "3h 25m")

    def test_negative_clamps_to_zero(self):
        self.assertEqual(format_duration(-10), "0s")


class TestCollectActiveExecutions(unittest.IsolatedAsyncioTestCase):
    async def test_merges_persisted_and_pending_newest_first(self):
        older = _active_record(
            workflow_name="Older run",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        pending = _active_record(
            workflow_name="Awaiting review",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        pending.pending_kind = "hitl"
        db = AsyncMock()

        with (
            patch(
                f"{MODULE}.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[older]),
            ),
            patch(f"{MODULE}.list_active_executions", return_value=[]),
            patch(
                f"{MODULE}.list_pending_review_executions_for_user",
                AsyncMock(return_value=[pending]),
            ),
        ):
            items = await collect_active_executions_for_user(db, uuid.uuid4())

        self.assertEqual([item.workflow_name for item in items], ["Awaiting review", "Older run"])
        self.assertEqual(items[0].status, "pending")
        self.assertEqual(items[0].pending_kind, "hitl")
        self.assertEqual(items[1].status, "running")

    async def test_local_handle_not_duplicated_when_already_persisted(self):
        shared_execution_id = uuid.uuid4()
        record = _active_record(execution_id=shared_execution_id)
        handle = SimpleNamespace(
            execution_id=shared_execution_id,
            workflow_id=record.workflow_id,
            started_at=record.started_at,
            inputs={},
            event=SimpleNamespace(is_set=lambda: False),
        )
        db = AsyncMock()

        with (
            patch(
                f"{MODULE}.list_persisted_active_executions_for_user",
                AsyncMock(return_value=[record]),
            ),
            patch(f"{MODULE}.list_active_executions", return_value=[handle]),
            patch(
                f"{MODULE}.list_pending_review_executions_for_user",
                AsyncMock(return_value=[]),
            ),
        ):
            items = await collect_active_executions_for_user(db, uuid.uuid4())

        self.assertEqual(len(items), 1)
        db.execute.assert_not_awaited()

    async def test_degrades_when_persisted_lookup_fails(self):
        from sqlalchemy.exc import SQLAlchemyError

        pending = _active_record(workflow_name="Awaiting review")
        pending.pending_kind = "codex"
        db = AsyncMock()

        with (
            patch(
                f"{MODULE}.list_persisted_active_executions_for_user",
                AsyncMock(side_effect=SQLAlchemyError("boom")),
            ),
            patch(f"{MODULE}.list_active_executions", return_value=[]),
            patch(
                f"{MODULE}.list_pending_review_executions_for_user",
                AsyncMock(return_value=[pending]),
            ),
        ):
            items = await collect_active_executions_for_user(db, uuid.uuid4())

        self.assertEqual(len(items), 1)
        db.rollback.assert_awaited()


class TestBuildActiveExecutionOverview(unittest.IsolatedAsyncioTestCase):
    async def test_empty_when_nothing_is_running(self):
        db = AsyncMock()
        with patch(f"{MODULE}.collect_active_executions_for_user", AsyncMock(return_value=[])):
            result = await build_active_execution_overview(db, uuid.uuid4(), "https://app.heym.run")

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["executions"], [])
        db.execute.assert_not_awaited()

    async def test_reports_name_duration_current_node_and_url(self):
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        item = ActiveExecutionItem(
            execution_id=str(execution_id),
            workflow_id=str(workflow_id),
            workflow_name="Nightly report",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=95),
            running_node_ids=["node-2"],
            node_results=[
                {
                    "node_id": "node-1",
                    "node_label": "Fetch rows",
                    "node_type": "http",
                    "status": "success",
                }
            ],
            status="running",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_rows(
                [
                    SimpleNamespace(
                        id=workflow_id,
                        nodes=[
                            {"id": "node-1", "type": "http", "data": {"label": "Fetch rows"}},
                            {"id": "node-2", "type": "llm", "data": {"label": "Summarize"}},
                        ],
                    )
                ]
            )
        )

        with patch(f"{MODULE}.collect_active_executions_for_user", AsyncMock(return_value=[item])):
            result = await build_active_execution_overview(
                db, uuid.uuid4(), "https://app.heym.run/"
            )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["running_count"], 1)
        self.assertEqual(result["pending_count"], 0)
        entry = result["executions"][0]
        self.assertEqual(entry["workflow_name"], "Nightly report")
        self.assertEqual(entry["running_for"], "1m 35s")
        self.assertGreaterEqual(entry["running_for_seconds"], 95)
        self.assertEqual(
            entry["current_nodes"],
            [{"node_id": "node-2", "node_label": "Summarize", "node_type": "llm"}],
        )
        self.assertEqual(entry["last_completed_node"]["node_label"], "Fetch rows")
        self.assertEqual(entry["completed_node_count"], 1)
        self.assertEqual(
            entry["url"],
            f"https://app.heym.run/workflows/{workflow_id}/{execution_id}",
        )
        self.assertEqual(entry["workflow_url"], f"https://app.heym.run/workflows/{workflow_id}")

    async def test_falls_back_to_relative_url_without_public_base(self):
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        item = ActiveExecutionItem(
            execution_id=str(execution_id),
            workflow_id=str(workflow_id),
            workflow_name="Nightly report",
            started_at=datetime.now(timezone.utc),
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows([]))

        with patch(f"{MODULE}.collect_active_executions_for_user", AsyncMock(return_value=[item])):
            result = await build_active_execution_overview(db, uuid.uuid4())

        self.assertEqual(
            result["executions"][0]["url"],
            f"/workflows/{workflow_id}/{execution_id}",
        )

    async def test_unfinished_node_result_counts_as_current_node(self):
        workflow_id = uuid.uuid4()
        item = ActiveExecutionItem(
            execution_id=str(uuid.uuid4()),
            workflow_id=str(workflow_id),
            workflow_name="Approval flow",
            started_at=datetime.now(timezone.utc) - timedelta(minutes=4),
            running_node_ids=[],
            node_results=[
                {
                    "node_id": "node-1",
                    "node_label": "Fetch rows",
                    "node_type": "http",
                    "status": "success",
                },
                {
                    "node_id": "node-2",
                    "node_label": "Human review",
                    "node_type": "hitl",
                    "status": "pending",
                },
            ],
            status="pending",
            pending_kind="hitl",
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows([]))

        with patch(f"{MODULE}.collect_active_executions_for_user", AsyncMock(return_value=[item])):
            result = await build_active_execution_overview(db, uuid.uuid4(), "")

        entry = result["executions"][0]
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(result["running_count"], 0)
        self.assertEqual(entry["pending_kind"], "hitl")
        self.assertEqual([n["node_id"] for n in entry["current_nodes"]], ["node-2"])
        self.assertEqual(entry["current_nodes"][0]["node_label"], "Human review")

    async def test_naive_started_at_is_treated_as_utc(self):
        item = ActiveExecutionItem(
            execution_id=str(uuid.uuid4()),
            workflow_id=str(uuid.uuid4()),
            workflow_name="Naive clock",
            started_at=datetime.utcnow() - timedelta(seconds=30),
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_rows([]))

        with patch(f"{MODULE}.collect_active_executions_for_user", AsyncMock(return_value=[item])):
            result = await build_active_execution_overview(db, uuid.uuid4(), "")

        self.assertGreaterEqual(result["executions"][0]["running_for_seconds"], 29)
        self.assertLess(result["executions"][0]["running_for_seconds"], 90)

    async def test_node_label_lookup_failure_does_not_break_overview(self):
        from sqlalchemy.exc import SQLAlchemyError

        item = ActiveExecutionItem(
            execution_id=str(uuid.uuid4()),
            workflow_id=str(uuid.uuid4()),
            workflow_name="Nightly report",
            started_at=datetime.now(timezone.utc),
            running_node_ids=["node-2"],
        )
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=SQLAlchemyError("boom"))

        with patch(f"{MODULE}.collect_active_executions_for_user", AsyncMock(return_value=[item])):
            result = await build_active_execution_overview(db, uuid.uuid4(), "")

        entry = result["executions"][0]
        self.assertEqual(entry["current_nodes"][0]["node_label"], "node-2")
        db.rollback.assert_awaited()


class TestNodeLabelIndex(unittest.TestCase):
    def test_ignores_malformed_nodes(self):
        index = overview_module._node_label_index(
            [{"id": "a", "data": {"label": "Start"}}, "junk", {"data": {"label": "No id"}}]
        )
        self.assertEqual(index, {"a": {"label": "Start", "type": ""}})

    def test_non_list_returns_empty(self):
        self.assertEqual(overview_module._node_label_index(None), {})


if __name__ == "__main__":
    unittest.main()
