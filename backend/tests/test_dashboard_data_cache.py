import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import dashboard_data


def _widget(cached_payload=None, cached_at=None, version="v1", ttl=300):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.workflow_id = uuid.uuid4()
    w.cache_ttl_seconds = ttl
    w.cached_payload = cached_payload
    w.cached_at = cached_at
    w.cached_workflow_version = version
    w.chart_type = "bar"
    return w


class _User:
    def __init__(self):
        self.id = uuid.uuid4()


def _db_returning_workflow(wf):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=wf)))
    db.commit = AsyncMock()
    return db


class TestExtractChartPayload(unittest.TestCase):
    def test_unwraps_single_chart_payload_from_final_outputs(self):
        chart = {
            "type": "bar",
            "labels": ["2026-06-10"],
            "series": [{"name": "n8n", "data": [1]}],
        }
        result = SimpleNamespace(node_results=[], outputs={"commitChart": chart})

        self.assertEqual(dashboard_data._extract_chart_payload(result), chart)

    def test_empty_chart_node_output_falls_back_to_final_outputs(self):
        chart = {
            "type": "bar",
            "labels": ["2026-06-10"],
            "series": [{"name": "dify", "data": [2]}],
        }
        result = SimpleNamespace(
            node_results=[{"node_type": "chartOutput", "output": {}}],
            outputs={"commitChart": chart},
        )

        self.assertEqual(dashboard_data._extract_chart_payload(result), chart)

    def test_empty_chart_node_output_without_valid_final_output_is_none(self):
        result = SimpleNamespace(
            node_results=[{"node_type": "chartOutput", "output": {}}],
            outputs={},
        )

        self.assertIsNone(dashboard_data._extract_chart_payload(result))


class TestComputeWidgetData(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.collect_referenced_workflows = AsyncMock(return_value={})
        self.get_credentials_context = AsyncMock(return_value={})
        self.get_global_variables_context = AsyncMock(return_value={})
        self.persist_global_variables = AsyncMock()

        self.patchers = [
            patch(
                "app.api.workflows.collect_referenced_workflows",
                new=self.collect_referenced_workflows,
            ),
            patch("app.api.workflows.get_credentials_context", new=self.get_credentials_context),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                new=self.get_global_variables_context,
            ),
            patch(
                "app.api.workflows._persist_global_variables_from_execution",
                new=self.persist_global_variables,
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_returns_cache_when_fresh(self):
        now = datetime.now(timezone.utc)
        widget = _widget(
            cached_payload={"type": "bar", "labels": ["x"]},
            cached_at=now - timedelta(seconds=10),
            version="2026-01-01T00:00:00+00:00",
        )
        wf = MagicMock()
        wf.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        wf.nodes = []
        wf.edges = []
        db = _db_returning_workflow(wf)

        resp = await dashboard_data.compute_widget_data(db, widget, _User(), force=False)

        self.assertTrue(resp.cached)
        self.assertEqual(resp.payload, {"type": "bar", "labels": ["x"]})

    async def test_rejects_blocked_trigger_nodes_even_when_cache_is_fresh(self):
        now = datetime.now(timezone.utc)
        widget = _widget(
            cached_payload={"type": "bar", "labels": ["x"]},
            cached_at=now - timedelta(seconds=10),
            version="2026-01-01T00:00:00+00:00",
        )
        wf = MagicMock()
        wf.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        wf.nodes = [
            {"id": "input", "type": "textInput", "data": {"label": "input"}},
            {"id": "chart", "type": "chartOutput", "data": {}},
        ]
        wf.edges = []
        db = _db_returning_workflow(wf)

        with patch.object(dashboard_data, "execute_workflow") as execute:
            resp = await dashboard_data.compute_widget_data(db, widget, _User(), force=False)

        execute.assert_not_called()
        self.assertFalse(resp.cached)
        self.assertIsNone(resp.payload)
        self.assertIn("input (textInput)", resp.error)

    async def test_recomputes_when_forced(self):
        now = datetime.now(timezone.utc)
        widget = _widget(
            cached_payload={"type": "bar"},
            cached_at=now,
            version="2026-01-01T00:00:00+00:00",
        )
        wf = MagicMock()
        wf.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        wf.nodes = [{"id": "c", "type": "chartOutput", "data": {}}]
        wf.edges = []
        db = _db_returning_workflow(wf)

        fake_result = MagicMock()
        fake_result.node_results = [
            {"node_type": "chartOutput", "output": {"type": "bar", "labels": ["new"]}}
        ]
        fake_result.allow_downstream_pending = False
        with patch.object(dashboard_data, "execute_workflow", return_value=fake_result):
            resp = await dashboard_data.compute_widget_data(db, widget, _User(), force=True)

        self.assertFalse(resp.cached)
        self.assertEqual(resp.payload, {"type": "bar", "labels": ["new"]})
        self.assertEqual(widget.cached_payload, {"type": "bar", "labels": ["new"]})

    async def test_recomputes_from_final_outputs_when_chart_node_result_is_empty(self):
        widget = _widget(cached_payload=None, cached_at=None, version="v")
        wf = MagicMock()
        wf.id = uuid.uuid4()
        wf.owner_id = uuid.uuid4()
        wf.name = "widget"
        wf.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        wf.nodes = [{"id": "c", "type": "chartOutput", "data": {}}]
        wf.edges = []
        db = _db_returning_workflow(wf)

        chart = {
            "type": "bar",
            "labels": ["2026-06-10"],
            "series": [{"name": "dify", "data": [2]}],
        }
        fake_result = MagicMock()
        fake_result.node_results = [{"node_type": "chartOutput", "output": {}}]
        fake_result.outputs = {"commitChart": chart}
        fake_result.status = "success"
        fake_result.execution_time_ms = 12.0
        fake_result.allow_downstream_pending = False

        with (
            patch.object(dashboard_data, "execute_workflow", return_value=fake_result),
            patch(
                "app.api.analytics.upsert_workflow_analytics_snapshot",
                new=AsyncMock(),
            ),
        ):
            resp = await dashboard_data.compute_widget_data(db, widget, _User(), force=True)

        self.assertFalse(resp.cached)
        self.assertIsNone(resp.error)
        self.assertEqual(resp.payload, chart)
        self.assertEqual(widget.cached_payload, chart)

    async def test_recomputes_when_version_changed(self):
        now = datetime.now(timezone.utc)
        widget = _widget(
            cached_payload={"type": "bar", "old": True},
            cached_at=now,
            version="OLD",
        )
        wf = MagicMock()
        wf.updated_at = datetime(2026, 2, 2, tzinfo=timezone.utc)
        wf.nodes = [{"id": "c", "type": "chartOutput", "data": {}}]
        wf.edges = []
        db = _db_returning_workflow(wf)

        fake_result = MagicMock()
        fake_result.node_results = [
            {"node_type": "chartOutput", "output": {"type": "bar", "fresh": True}}
        ]
        fake_result.allow_downstream_pending = False
        with patch.object(dashboard_data, "execute_workflow", return_value=fake_result):
            resp = await dashboard_data.compute_widget_data(db, widget, _User(), force=False)

        self.assertFalse(resp.cached)
        self.assertEqual(resp.payload, {"type": "bar", "fresh": True})

    async def test_recompute_uses_runtime_context_and_persists_global_variables(self):
        widget = _widget(cached_payload=None, cached_at=None, version="v")
        workflow_id = uuid.uuid4()
        wf = MagicMock()
        wf.id = workflow_id
        wf.owner_id = uuid.uuid4()
        wf.name = "widget"
        wf.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        wf.nodes = [
            {
                "id": "v",
                "type": "variable",
                "data": {"isGlobal": True, "variableName": "exchangeAuth"},
            },
            {"id": "c", "type": "chartOutput", "data": {}},
        ]
        wf.edges = [{"source": "v", "target": "c"}]
        db = _db_returning_workflow(wf)

        workflow_cache = {"child": {"nodes": [], "edges": []}}
        credentials_context = {"Slack": "masked-secret"}
        global_variables_context = {"exchangeAuth": [{"name": "token", "value": "abc"}]}
        self.collect_referenced_workflows.return_value = workflow_cache
        self.get_credentials_context.return_value = credentials_context
        self.get_global_variables_context.return_value = global_variables_context

        fake_result = MagicMock()
        fake_result.node_results = [
            {
                "node_id": "v",
                "node_type": "variable",
                "output": {"name": "exchangeAuth", "value": [{"name": "token"}], "type": "array"},
            },
            {"node_id": "c", "node_type": "chartOutput", "output": {"type": "text", "text": "ok"}},
        ]
        fake_result.outputs = {"metricsDisplay": {"type": "text", "text": "ok"}}
        fake_result.status = "success"
        fake_result.execution_time_ms = 12.0
        fake_result.sub_workflow_executions = []
        fake_result.allow_downstream_pending = False

        with (
            patch.object(dashboard_data, "execute_workflow", return_value=fake_result) as execute,
            patch(
                "app.api.analytics.upsert_workflow_analytics_snapshot",
                new=AsyncMock(),
            ),
        ):
            resp = await dashboard_data.compute_widget_data(db, widget, _User(), force=True)

        self.assertIsNone(resp.error)
        self.assertEqual(resp.payload, {"type": "text", "text": "ok"})
        execute.assert_called_once()
        execute_kwargs = execute.call_args.kwargs
        self.assertEqual(execute_kwargs["workflow_cache"], workflow_cache)
        self.assertEqual(execute_kwargs["credentials_context"], credentials_context)
        self.assertEqual(execute_kwargs["global_variables_context"], global_variables_context)
        self.persist_global_variables.assert_awaited_once_with(
            db,
            execute_kwargs["actor_user_id"],
            wf.nodes,
            workflow_cache,
            fake_result.node_results,
            [],
        )

    async def test_recompute_returns_chart_before_side_branch_finishes(self):
        widget = _widget(cached_payload=None, cached_at=None, version="v")
        wf = MagicMock()
        wf.id = uuid.uuid4()
        wf.owner_id = uuid.uuid4()
        wf.name = "widget"
        wf.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        wf.nodes = [
            {"id": "chart", "type": "chartOutput", "data": {}},
            {
                "id": "variable",
                "type": "variable",
                "data": {"isGlobal": True, "variableName": "exchangeAuth"},
            },
        ]
        wf.edges = []
        db = _db_returning_workflow(wf)

        fake_result = MagicMock()
        fake_result.node_results = [
            {
                "node_id": "chart",
                "node_type": "chartOutput",
                "output": {"type": "text", "text": "ok"},
            }
        ]
        fake_result.outputs = {"metricsDisplay": {"type": "text", "text": "ok"}}
        fake_result.status = "success"
        fake_result.execution_time_ms = 12.0
        fake_result.allow_downstream_pending = True

        scheduled = []

        def create_task(coro):
            scheduled.append(coro)
            coro.close()
            return MagicMock()

        with (
            patch.object(dashboard_data, "execute_workflow", return_value=fake_result) as execute,
            patch("asyncio.create_task", side_effect=create_task),
            patch(
                "app.api.analytics.upsert_workflow_analytics_snapshot",
                new=AsyncMock(),
            ),
        ):
            resp = await dashboard_data.compute_widget_data(db, widget, _User(), force=True)

        self.assertIsNone(resp.error)
        self.assertEqual(resp.payload, {"type": "text", "text": "ok"})
        self.assertTrue(scheduled)
        self.persist_global_variables.assert_not_awaited()
        self.assertTrue(execute.call_args.kwargs["return_on_chart_output"])

    async def test_cache_miss_records_execution_history(self):
        from app.db.models import ExecutionHistory

        widget = _widget(cached_payload=None, cached_at=None, version="v")
        wf = MagicMock()
        wf.id = uuid.uuid4()
        wf.owner_id = uuid.uuid4()
        wf.name = "widget"
        wf.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        wf.nodes = [{"id": "c", "type": "chartOutput", "data": {}}]
        wf.edges = []
        db = _db_returning_workflow(wf)
        db.add = MagicMock()

        fake_result = MagicMock()
        fake_result.node_results = [{"node_type": "chartOutput", "output": {"type": "bar"}}]
        fake_result.outputs = {}
        fake_result.status = "success"
        fake_result.execution_time_ms = 12.0
        fake_result.allow_downstream_pending = False

        with (
            patch.object(dashboard_data, "execute_workflow", return_value=fake_result),
            patch(
                "app.api.analytics.upsert_workflow_analytics_snapshot",
                new=AsyncMock(),
            ),
        ):
            await dashboard_data.compute_widget_data(db, widget, _User(), force=True)

        added_types = [type(c.args[0]).__name__ for c in db.add.call_args_list]
        self.assertIn(ExecutionHistory.__name__, added_types)
