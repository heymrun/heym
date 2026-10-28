"""Chat's get_analytics_breakdown: where runs fail and why they are slow, for Chat, MCP and A2A."""

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.api import ai_assistant
from app.api.analytics import compute_analytics_breakdown
from app.services.analytics_breakdown import NODE_DATA_NOTE, build_analytics_breakdown
from app.services.analytics_metrics import WorkflowBreakdownRow
from app.services.heym_agent import profile
from app.services.node_analytics_metrics import NodeTypeTotals, compute_node_type_totals

BASE = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)


def _workflow(name: str, runs: int, errors: int = 0, latency: float = 0.0) -> WorkflowBreakdownRow:
    return WorkflowBreakdownRow(
        workflow_id=uuid.uuid5(uuid.NAMESPACE_DNS, name),
        workflow_name=name,
        execution_count=runs,
        success_count=runs - errors,
        error_count=errors,
        success_rate=(runs - errors) / runs * 100 if runs else 0.0,
        error_rate=errors / runs * 100 if runs else 0.0,
        avg_latency_ms=latency,
        time_saved_minutes=None,
    )


def _node(node_type: str, calls: int, errors: int = 0, duration: float = 0.0) -> NodeTypeTotals:
    return NodeTypeTotals(
        node_type=node_type, call_count=calls, error_count=errors, total_duration_ms=duration
    )


class BuildAnalyticsBreakdownTests(unittest.TestCase):
    def test_ranks_workflows_by_runs_failures_and_latency(self) -> None:
        breakdown = build_analytics_breakdown(
            "7d",
            [
                _workflow("Invoices", 40, errors=1, latency=900.0),
                _workflow("Leads", 12, errors=6, latency=8_000.0),
                _workflow("Digest", 3, latency=150.0),
            ],
            [],
            limit=5,
        )

        self.assertEqual(breakdown.workflows_run, 3)
        self.assertEqual(breakdown.executions, 55)
        self.assertEqual(
            [w.workflow_name for w in breakdown.most_run_workflows], ["Invoices", "Leads", "Digest"]
        )
        self.assertEqual(
            [w.workflow_name for w in breakdown.most_failed_workflows], ["Leads", "Invoices"]
        )
        self.assertEqual(breakdown.most_failed_workflows[0].error_rate, 50.0)
        self.assertEqual(
            [w.workflow_name for w in breakdown.slowest_workflows], ["Leads", "Invoices", "Digest"]
        )

    def test_explains_slowness_by_node_type_with_the_average_per_call(self) -> None:
        breakdown = build_analytics_breakdown(
            "7d",
            [_workflow("Invoices", 4)],
            [
                _node("agent", 10, errors=1, duration=81_000.0),
                _node("httpRequest", 40, errors=4, duration=12_000.0),
                _node("set", 90, duration=900.0),
                _node("output", 4),
            ],
            limit=5,
        )

        by_time = breakdown.node_types_by_time
        self.assertEqual([n.node_type for n in by_time], ["agent", "httpRequest", "set"])
        self.assertEqual(by_time[0].avg_duration_ms, 8_100.0)
        self.assertEqual(
            [n.node_type for n in breakdown.node_types_by_errors], ["httpRequest", "agent"]
        )
        self.assertEqual(breakdown.node_types_by_errors[0].error_rate, 10.0)
        self.assertEqual(breakdown.node_types_by_calls[0].node_type, "set")
        self.assertIsNone(breakdown.note)

    def test_each_list_keeps_the_limit(self) -> None:
        breakdown = build_analytics_breakdown(
            "24h",
            [_workflow(f"W{i}", 10 + i, errors=1, latency=float(i)) for i in range(8)],
            [_node(f"type{i}", 10 + i, errors=1, duration=float(i + 1)) for i in range(8)],
            limit=3,
        )

        for ranking in (
            breakdown.most_run_workflows,
            breakdown.most_failed_workflows,
            breakdown.slowest_workflows,
            breakdown.node_types_by_time,
            breakdown.node_types_by_errors,
            breakdown.node_types_by_calls,
        ):
            self.assertEqual(len(ranking), 3)
        self.assertEqual(breakdown.workflows_run, 8)

    def test_says_when_the_window_has_no_node_data_yet(self) -> None:
        breakdown = build_analytics_breakdown("30d", [_workflow("Invoices", 4)], [], limit=5)

        self.assertEqual(breakdown.note, NODE_DATA_NOTE)
        self.assertEqual(breakdown.node_types_by_time, [])


class ComputeNodeTypeTotalsTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_query_grouped_by_node_type(self) -> None:
        rows = MagicMock()
        rows.all.return_value = [
            SimpleNamespace(node_type="agent", call_count=3, error_count=1, total_duration_ms=30.0)
        ]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=rows)
        workflow_id = uuid.uuid4()

        totals = await compute_node_type_totals(
            db,
            accessible_workflow_ids=[workflow_id, uuid.uuid4()],
            workflow_id=None,
            since=BASE,
            until=BASE + timedelta(days=1),
        )

        sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("node_analytics_snapshots.workflow_id IN", sql)
        self.assertIn("GROUP BY node_analytics_snapshots.node_type", sql)
        self.assertEqual(totals, [_node("agent", 3, errors=1, duration=30.0)])

    async def test_an_inaccessible_workflow_reads_nothing(self) -> None:
        db = AsyncMock()

        totals = await compute_node_type_totals(
            db,
            accessible_workflow_ids=[uuid.uuid4()],
            workflow_id=uuid.uuid4(),
            since=BASE,
            until=BASE + timedelta(days=1),
        )

        self.assertEqual(totals, [])
        db.execute.assert_not_awaited()


class ComputeAnalyticsBreakdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_inaccessible_workflow_gets_an_empty_breakdown(self) -> None:
        with patch(
            "app.api.analytics.get_accessible_workflow_ids",
            AsyncMock(return_value=[uuid.uuid4()]),
        ):
            breakdown = await compute_analytics_breakdown(
                AsyncMock(), uuid.uuid4(), uuid.uuid4(), "7d"
            )

        self.assertEqual(breakdown.workflows_run, 0)
        self.assertEqual(breakdown.most_run_workflows, [])

    async def test_one_workflow_keeps_only_its_own_rows(self) -> None:
        invoices = _workflow("Invoices", 4, errors=2, latency=50.0)
        leads = _workflow("Leads", 9)
        node_totals = AsyncMock(return_value=[_node("agent", 4, errors=2, duration=40.0)])
        with (
            patch(
                "app.api.analytics.get_accessible_workflow_ids",
                AsyncMock(return_value=[invoices.workflow_id, leads.workflow_id]),
            ),
            patch(
                "app.api.analytics.analytics_metrics.compute_workflow_breakdown",
                AsyncMock(return_value=[leads, invoices]),
            ),
            patch("app.api.analytics.node_analytics_metrics.compute_node_type_totals", node_totals),
        ):
            breakdown = await compute_analytics_breakdown(
                AsyncMock(), uuid.uuid4(), invoices.workflow_id, "24h"
            )

        self.assertEqual([w.workflow_name for w in breakdown.most_run_workflows], ["Invoices"])
        self.assertEqual(breakdown.time_range, "24h")
        self.assertEqual(node_totals.await_args.kwargs["workflow_id"], invoices.workflow_id)
        self.assertEqual(breakdown.node_types_by_errors[0].node_type, "agent")


class AnalyticsBreakdownChatToolTests(unittest.TestCase):
    def _tool(self) -> dict:
        return next(
            item
            for item in ai_assistant.DASHBOARD_CHAT_TOOLS
            if item["function"]["name"] == "get_analytics_breakdown"
        )

    def test_the_tool_is_declared_with_an_optional_workflow_and_window(self) -> None:
        parameters = self._tool()["function"]["parameters"]
        self.assertEqual(parameters["required"], [])
        self.assertEqual(
            parameters["properties"]["time_range"]["enum"], ["24h", "7d", "30d", "all"]
        )
        self.assertIn("workflow_id", parameters["properties"])

    def test_the_prompt_routes_failure_and_slowness_questions_to_it(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertIn("get_analytics_breakdown", prompt)
        self.assertIn("why workflows are slow", prompt)
        self.assertIn("avg_duration_ms", prompt)

    def test_mcp_and_a2a_advertise_the_capability(self) -> None:
        self.assertIn("why they are slow", profile.MCP_TOOL_DESCRIPTION)
        self.assertIn("why they are slow", profile.A2A_DESCRIPTION)
        observability = next(skill for skill in profile.AGENT_SKILLS if skill.id == "observability")
        self.assertIn("why they are slow", observability.description)

    def test_the_step_summary_names_the_slowest_node_type(self) -> None:
        payload = {
            "workflows_run": 3,
            "most_failed_workflows": [{"workflow_name": "Leads"}],
            "node_types_by_time": [{"node_type": "agent"}],
        }

        self.assertEqual(
            ai_assistant._summarize_tool_result("get_analytics_breakdown", json.dumps(payload)),
            "Breakdown: 3 workflow(s) ran, 1 with errors, most time in agent nodes",
        )

    def test_the_step_summary_without_node_data(self) -> None:
        payload = {"workflows_run": 0, "most_failed_workflows": [], "node_types_by_time": []}

        self.assertEqual(
            ai_assistant._summarize_tool_result("get_analytics_breakdown", json.dumps(payload)),
            "Breakdown: 0 workflow(s) ran, 0 with errors",
        )
