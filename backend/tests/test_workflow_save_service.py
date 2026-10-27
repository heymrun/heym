"""workflow_save stores versions and announces saves the way the editor always has."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import WorkflowVersion
from app.services.heym_event_service import EVENT_WORKFLOW_CREATED, EVENT_WORKFLOW_UPDATED
from app.services.workflow_save import (
    WorkflowSnapshot,
    add_workflow_version,
    announce_workflow_saved,
    sync_dashboard_widget,
)


def _workflow(kind: str = "workflow") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Lead intake",
        description="Saves website leads",
        kind=kind,
        nodes=[{"id": "n1", "type": "textInput", "data": {"label": "start"}}],
        edges=[],
        auth_type="anonymous",
        auth_header_key=None,
        auth_header_value=None,
        webhook_body_mode="legacy",
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        updated_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        folder_id=None,
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


class WorkflowSnapshotTests(unittest.TestCase):
    def test_capture_copies_the_graph(self) -> None:
        workflow = _workflow()
        snapshot = WorkflowSnapshot.capture(workflow)

        workflow.nodes[0]["data"]["label"] = "changed"

        self.assertEqual(snapshot.nodes[0]["data"]["label"], "start")


class AddWorkflowVersionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_the_replaced_graph_as_the_next_version(self) -> None:
        workflow = _workflow()
        before = WorkflowSnapshot.capture(workflow)
        workflow.nodes = []
        actor_id = uuid.uuid4()
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=3)))

        number = await add_workflow_version(db, workflow, before, actor_id)

        self.assertEqual(number, 4)
        version = db.add.call_args.args[0]
        self.assertIsInstance(version, WorkflowVersion)
        self.assertEqual(version.version_number, 4)
        self.assertEqual(version.nodes, before.nodes)
        self.assertEqual(version.name, "Lead intake")
        self.assertEqual(version.created_by_id, actor_id)

    async def test_first_version_is_one(self) -> None:
        workflow = _workflow()
        db = MagicMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=None)))

        number = await add_workflow_version(
            db, workflow, WorkflowSnapshot.capture(workflow), uuid.uuid4()
        )

        self.assertEqual(number, 1)


class AnnounceWorkflowSavedTests(unittest.IsolatedAsyncioTestCase):
    async def _announce(
        self, workflow: SimpleNamespace, *, created: bool
    ) -> tuple[AsyncMock, MagicMock]:
        publish = AsyncMock()
        with patch(
            "app.services.websocket_trigger_service.websocket_trigger_manager.request_sync"
        ) as request_sync:
            await announce_workflow_saved(workflow, uuid.uuid4(), created=created, publish=publish)
        return publish, request_sync

    async def test_update_resyncs_triggers_and_publishes_updated(self) -> None:
        workflow = _workflow()

        publish, request_sync = await self._announce(workflow, created=False)

        request_sync.assert_called_once()
        kwargs = publish.call_args.kwargs
        self.assertEqual(kwargs["name"], EVENT_WORKFLOW_UPDATED)
        self.assertTrue(kwargs["dedupe_key"].startswith(f"{EVENT_WORKFLOW_UPDATED}:{workflow.id}:"))

    async def test_create_publishes_created(self) -> None:
        workflow = _workflow()

        publish, _ = await self._announce(workflow, created=True)

        self.assertEqual(publish.call_args.kwargs["name"], EVENT_WORKFLOW_CREATED)
        self.assertEqual(
            publish.call_args.kwargs["dedupe_key"], f"{EVENT_WORKFLOW_CREATED}:{workflow.id}"
        )

    async def test_dashboard_widget_resyncs_without_an_event(self) -> None:
        publish, request_sync = await self._announce(_workflow("dashboard_widget"), created=False)

        request_sync.assert_called_once()
        publish.assert_not_called()


class SyncDashboardWidgetTests(unittest.IsolatedAsyncioTestCase):
    def _widget(self) -> SimpleNamespace:
        return SimpleNamespace(
            title="Widget",
            description=None,
            chart_type="bar",
            cached_payload={"rows": []},
            cached_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
            cached_workflow_version="v1",
        )

    def _db(self, widget: SimpleNamespace | None) -> MagicMock:
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=widget))
        )
        return db

    async def test_a_widget_follows_its_saved_workflow(self) -> None:
        workflow = _workflow(kind="dashboard_widget")
        workflow.nodes = [
            {"id": "c1", "type": "chartOutput", "data": {"chartType": "line"}},
            {"id": "c2", "type": "chartOutput", "data": {"chartType": "table"}},
        ]
        widget = self._widget()

        await sync_dashboard_widget(
            self._db(widget), workflow, renamed=True, described=True, graph_changed=True
        )

        self.assertEqual(widget.title, "Lead intake")
        self.assertEqual(widget.description, "Saves website leads")
        self.assertEqual(widget.chart_type, "table")
        self.assertIsNone(widget.cached_payload)
        self.assertIsNone(widget.cached_at)
        self.assertIsNone(widget.cached_workflow_version)

    async def test_a_rename_alone_keeps_the_chart_and_its_cache(self) -> None:
        workflow = _workflow(kind="dashboard_widget")
        widget = self._widget()

        await sync_dashboard_widget(
            self._db(widget), workflow, renamed=True, described=False, graph_changed=False
        )

        self.assertEqual(widget.title, "Lead intake")
        self.assertIsNone(widget.description)
        self.assertEqual(widget.chart_type, "bar")
        self.assertEqual(widget.cached_workflow_version, "v1")

    async def test_an_ordinary_workflow_has_no_widget_to_sync(self) -> None:
        db = self._db(self._widget())

        await sync_dashboard_widget(
            db, _workflow(), renamed=True, described=True, graph_changed=True
        )

        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
