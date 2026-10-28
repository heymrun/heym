"""Dashboard widget runs hold the node analytics marker back until allowDownstream finishes."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.models import ExecutionHistory
from app.services import dashboard_data


def _result(*, allow_downstream_pending: bool) -> SimpleNamespace:
    return SimpleNamespace(
        status="success",
        outputs={},
        node_results=[{"node_type": "set", "status": "success"}],
        execution_time_ms=1.0,
        allow_downstream_pending=allow_downstream_pending,
        join_allow_downstream=lambda: None,
    )


class WidgetFirstWriteTests(unittest.IsolatedAsyncioTestCase):
    async def _record(self, result: SimpleNamespace) -> ExecutionHistory:
        db = MagicMock()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="Widget WF")
        with (
            patch(
                "app.services.pending_execution.needs_local_pending_persist",
                return_value=False,
            ),
            patch("app.api.analytics.upsert_workflow_analytics_snapshot", AsyncMock()),
        ):
            entry = await dashboard_data._record_widget_execution(db, workflow, result, {})
        self.assertIsNotNone(entry)
        return entry

    async def test_a_widget_run_with_downstream_work_is_held_back(self) -> None:
        entry = await self._record(_result(allow_downstream_pending=True))

        self.assertIs(entry.node_analytics_pending, False)

    async def test_a_plain_widget_run_is_pending_right_away(self) -> None:
        entry = await self._record(_result(allow_downstream_pending=False))

        self.assertIs(entry.node_analytics_pending, True)


class WidgetFinalizerTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_finalizer_releases_the_marker(self) -> None:
        history = ExecutionHistory(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            inputs={},
            outputs={},
            node_results=[],
            status="success",
            execution_time_ms=1.0,
            node_analytics_pending=False,
        )
        lookup = MagicMock()
        lookup.scalar_one_or_none.return_value = history
        bg_db = MagicMock()
        bg_db.execute = AsyncMock(return_value=lookup)
        bg_db.commit = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=bg_db)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(dashboard_data, "async_session_maker", factory),
            patch.object(dashboard_data, "_persist_widget_global_variables", AsyncMock()),
            patch("app.api.analytics.upsert_workflow_analytics_snapshot", AsyncMock()),
        ):
            await dashboard_data._finalize_widget_allow_downstream(
                history_entry_id=history.id,
                workflow_id=history.workflow_id,
                workflow_name="Widget WF",
                owner_id=uuid.uuid4(),
                workflow_nodes=[],
                workflow_cache={},
                result=_result(allow_downstream_pending=True),
            )

        self.assertIs(history.node_analytics_pending, True)
        bg_db.commit.assert_awaited_once()
