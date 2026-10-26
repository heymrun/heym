"""Agent Suite metrics: reading an agent's trace rows, aggregating them and scoring runs."""

import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.agent_suite_metrics import (
    AgentBaseline,
    AgentRun,
    AgentThresholds,
    AgentToolCall,
    ConfiguredTool,
    ToolExpectation,
    _run_from_row,
    baseline_from_json,
    baseline_to_json,
    build_report,
    configured_tools,
    evaluate_run,
    find_agent_node,
    suggest_thresholds,
    summarize_runs,
    summarize_tool_usage,
    tool_call_from_entry,
)


def make_run(
    *,
    latency_ms: float = 1000.0,
    cost_usd: float | None = 0.01,
    total_tokens: int = 1000,
    tools: list[str] | None = None,
    error: str | None = None,
    model: str | None = "gpt-test",
) -> AgentRun:
    calls = [
        AgentToolCall(kind="tool", name=name, label=name, status="success", elapsed_ms=100.0)
        for name in tools or []
    ]
    return AgentRun(
        trace_id=uuid.uuid4(),
        created_at=datetime.now(timezone.utc),
        model=model,
        latency_ms=latency_ms,
        model_ms=latency_ms,
        tool_ms=0.0,
        cost_usd=cost_usd,
        total_tokens=total_tokens,
        tool_count=len(calls),
        tool_calls=calls,
        error=error,
    )


class RunFromRowTests(unittest.TestCase):
    def _row(self, **overrides: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "id": uuid.uuid4(),
            "created_at": datetime.now(timezone.utc),
            "model": "gpt-test",
            "total_tokens": 1500,
            "elapsed_ms": 1200.0,
            "error": None,
            "tool_calls": [],
            "tool_metrics": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_latency_adds_tool_time_to_model_time(self) -> None:
        row = self._row(
            tool_calls=[{"name": "search", "status": "success", "elapsed_ms": 300.0}],
            tool_metrics={"count": 1, "total_duration_ms": 300.0},
        )
        run = _run_from_row(row, Decimal("0.0042"))
        self.assertEqual(run.model_ms, 1200.0)
        self.assertEqual(run.tool_ms, 300.0)
        self.assertEqual(run.latency_ms, 1500.0)
        self.assertEqual(run.cost_usd, 0.0042)
        self.assertEqual([call.name for call in run.tool_calls], ["search"])

    def test_tool_count_comes_from_metrics_when_records_were_truncated(self) -> None:
        records = [{"name": "search", "status": "success"} for _ in range(100)]
        row = self._row(
            tool_calls=[*records, "[truncated]"],
            tool_metrics={"count": 140, "total_duration_ms": 0.0},
        )
        run = _run_from_row(row, None)
        self.assertEqual(run.tool_count, 140)
        self.assertEqual(len(run.tool_calls), 100)
        self.assertIsNone(run.cost_usd)

    def test_context_compression_is_not_a_tool_call(self) -> None:
        row = self._row(
            tool_calls=[
                {"name": "_context_compression", "status": "success"},
                {"name": "lookup", "status": "error"},
            ],
        )
        run = _run_from_row(row, None)
        self.assertEqual(run.tool_count, 1)
        self.assertEqual([(c.name, c.status) for c in run.tool_calls], [("lookup", "error")])

    def test_missing_numbers_read_as_zero(self) -> None:
        run = _run_from_row(self._row(total_tokens=None, elapsed_ms=None), None)
        self.assertEqual(run.total_tokens, 0)
        self.assertEqual(run.latency_ms, 0.0)
        self.assertEqual(run.tool_count, 0)


class AgentNodeTests(unittest.TestCase):
    def test_find_agent_node_ignores_other_types(self) -> None:
        nodes = [
            {"id": "n1", "type": "llm", "data": {}},
            {"id": "n2", "type": "agent", "data": {"label": "Support"}},
        ]
        self.assertIsNone(find_agent_node(nodes, "n1"))
        self.assertEqual(find_agent_node(nodes, "n2"), nodes[1])
        self.assertIsNone(find_agent_node(None, "n2"))

    def test_configured_tools_cover_every_kind(self) -> None:
        node = {
            "id": "a",
            "type": "agent",
            "data": {
                "tools": [{"name": "search"}, {"name": " search "}, {"name": ""}, "bad"],
                "skills": [{"name": "PDF Extract"}],
                "isOrchestrator": True,
                "subAgentLabels": ["Writer", "Critic"],
                "subWorkflowIds": ["wf-1", "wf-2"],
                "subWorkflowNames": {"wf-1": "Billing"},
            },
        }
        tools = configured_tools(node, {"wf-2": "Refunds"})
        self.assertEqual(
            [(t.kind, t.name, t.label) for t in tools],
            [
                ("tool", "search", "search"),
                ("skill", "pdf_extract", "PDF Extract"),
                ("sub_agent", "Writer", "Writer"),
                ("sub_agent", "Critic", "Critic"),
                ("sub_workflow", "wf-1", "Billing"),
                ("sub_workflow", "wf-2", "Refunds"),
            ],
        )

    def test_sub_agents_need_an_orchestrator(self) -> None:
        node = {"id": "a", "type": "agent", "data": {"subAgentLabels": ["Writer"]}}
        self.assertEqual(configured_tools(node), [])

    def test_each_call_is_identified_by_what_it_reached(self) -> None:
        entries = [
            {"name": "search", "status": "success", "elapsed_ms": 10},
            {"name": "list_files", "source": "mcp", "mcp_server": "Drive", "status": "success"},
            {
                "name": "call_sub_agent",
                "source": "sub_agent",
                "arguments": {"sub_agent_label": "Writer", "prompt": "draft"},
                "status": "success",
            },
            {
                "name": "call_sub_workflow",
                "source": "sub_workflow",
                "arguments": {"workflow_id": "wf-1", "inputs": {}},
                "workflow_name": "Billing",
                "status": "error",
            },
            {"name": "skill_pdf_extract", "source": "skill", "status": "success"},
            {"name": "summarize_node", "source": "node_tool", "status": "success"},
        ]
        calls = [tool_call_from_entry(entry) for entry in entries]
        self.assertEqual(
            [(c.kind, c.name, c.label, c.status) for c in calls],
            [
                ("tool", "search", "search", "success"),
                ("mcp", "list_files", "list_files", "success"),
                ("sub_agent", "Writer", "Writer", "success"),
                ("sub_workflow", "wf-1", "Billing", "error"),
                ("skill", "pdf_extract", "pdf_extract", "success"),
                ("node", "summarize_node", "summarize_node", "success"),
            ],
        )
        self.assertEqual(calls[1].server, "Drive")

    def test_sub_agent_call_without_a_label_keeps_the_tool_name(self) -> None:
        call = tool_call_from_entry({"name": "call_sub_agent", "source": "sub_agent"})
        self.assertEqual((call.kind, call.name), ("sub_agent", "call_sub_agent"))


class SummaryTests(unittest.TestCase):
    def test_baseline_skips_errored_runs(self) -> None:
        runs = [
            make_run(latency_ms=1000, total_tokens=100, tools=["a"]),
            make_run(latency_ms=3000, total_tokens=300, tools=["a", "b"]),
            make_run(latency_ms=99999, error="provider down"),
        ]
        baseline = summarize_runs(runs)
        self.assertEqual(baseline.run_count, 2)
        self.assertEqual(baseline.error_count, 1)
        self.assertEqual(baseline.latency_p95_ms, 3000.0)
        self.assertEqual(baseline.tokens_avg, 200.0)
        self.assertEqual(baseline.tool_calls_avg, 1.5)
        self.assertEqual(baseline.tool_calls_max, 2)
        self.assertEqual(baseline.cost_avg_usd, 0.01)

    def test_unpriced_model_is_left_out_of_cost(self) -> None:
        runs = [make_run(cost_usd=0.02), make_run(cost_usd=None, model="local-model")]
        baseline = summarize_runs(runs)
        self.assertEqual(baseline.cost_avg_usd, 0.02)
        self.assertEqual(baseline.unpriced_models, ["local-model"])

    def test_no_runs_gives_an_empty_baseline_and_no_thresholds(self) -> None:
        baseline = summarize_runs([])
        self.assertEqual(baseline.run_count, 0)
        self.assertIsNone(baseline.latency_p95_ms)
        self.assertEqual(suggest_thresholds(baseline), AgentThresholds())

    def test_suggested_thresholds_leave_headroom(self) -> None:
        baseline = AgentBaseline(
            run_count=5,
            latency_p95_ms=4120.0,
            cost_p95_usd=0.01,
            tokens_p95=1000.0,
            tool_calls_max=4,
        )
        self.assertEqual(
            suggest_thresholds(baseline),
            AgentThresholds(latency_ms=5000.0, cost_usd=0.012, total_tokens=1200, tool_calls=4),
        )

    def test_tool_usage_lists_observed_then_unused_configured(self) -> None:
        runs = [
            make_run(tools=["search", "search", "lookup"]),
            make_run(tools=["search"]),
        ]
        runs.append(
            AgentRun(
                **{
                    **runs[1].__dict__,
                    "trace_id": uuid.uuid4(),
                    "tool_calls": [AgentToolCall("tool", "lookup", "lookup", "timeout", 50.0)],
                }
            )
        )
        usage = summarize_tool_usage(
            runs,
            [
                ConfiguredTool("tool", "lookup", "lookup"),
                ConfiguredTool("tool", "send_email", "send_email"),
            ],
        )
        self.assertEqual([u.name for u in usage], ["search", "lookup", "send_email"])
        search, lookup, send_email = usage
        self.assertEqual((search.runs_called, search.call_count), (2, 3))
        self.assertFalse(search.configured)
        self.assertEqual((lookup.call_count, lookup.error_count, lookup.avg_ms), (2, 1, 75.0))
        self.assertTrue(lookup.configured)
        self.assertEqual((send_email.call_count, send_email.avg_ms), (0, None))

    def test_baseline_round_trips_through_json(self) -> None:
        baseline = AgentBaseline(run_count=3, latency_p95_ms=10.0, unpriced_models=["m"])
        stored = baseline_to_json(baseline, datetime(2026, 10, 26, tzinfo=timezone.utc))
        self.assertEqual(stored["captured_at"], "2026-10-26T00:00:00+00:00")
        self.assertEqual(baseline_from_json(stored), baseline)
        self.assertEqual(baseline_from_json(None), AgentBaseline())


class EvaluationTests(unittest.TestCase):
    def _statuses(self, run: AgentRun, **kwargs: object) -> dict[str, str]:
        evaluation = evaluate_run(
            run,
            kwargs.get("assertions", []),  # type: ignore[arg-type]
            kwargs.get("thresholds", AgentThresholds()),  # type: ignore[arg-type]
        )
        return {check.key: check.status for check in evaluation.checks}

    def test_called_and_not_called_assertions(self) -> None:
        run = make_run(tools=["search"])
        assertions = [
            ToolExpectation("search", "called"),
            ToolExpectation("send_email", "not_called"),
            ToolExpectation("lookup", "called"),
        ]
        evaluation = evaluate_run(run, assertions, AgentThresholds())
        statuses = {check.key: check.status for check in evaluation.checks}
        self.assertEqual(
            statuses,
            {
                "run": "pass",
                "tool:tool:search": "pass",
                "tool:tool:send_email": "pass",
                "tool:tool:lookup": "fail",
            },
        )
        self.assertFalse(evaluation.passed)

    def test_forbidden_tool_that_ran_fails(self) -> None:
        run = make_run(tools=["send_email", "send_email"])
        evaluation = evaluate_run(
            run, [ToolExpectation("send_email", "not_called")], AgentThresholds()
        )
        check = evaluation.checks[1]
        self.assertEqual((check.status, check.detail), ("fail", "called 2×"))
        self.assertFalse(evaluation.passed)

    def test_thresholds_are_inclusive_upper_bounds(self) -> None:
        run = make_run(latency_ms=2000, cost_usd=0.05, total_tokens=500, tools=["a", "b"])
        statuses = self._statuses(
            run,
            thresholds=AgentThresholds(
                latency_ms=2000, cost_usd=0.04, total_tokens=600, tool_calls=1
            ),
        )
        self.assertEqual(statuses["latency_ms"], "pass")
        self.assertEqual(statuses["cost_usd"], "fail")
        self.assertEqual(statuses["total_tokens"], "pass")
        self.assertEqual(statuses["tool_calls"], "fail")

    def test_unpriced_cost_is_skipped_and_does_not_fail(self) -> None:
        run = make_run(cost_usd=None)
        evaluation = evaluate_run(run, [], AgentThresholds(cost_usd=0.01))
        self.assertEqual(evaluation.checks[-1].status, "skip")
        self.assertEqual(evaluation.checks[-1].detail, "unpriced model")
        self.assertTrue(evaluation.passed)

    def test_disabled_thresholds_add_no_checks(self) -> None:
        self.assertEqual(self._statuses(make_run()), {"run": "pass"})

    def test_errored_run_fails(self) -> None:
        evaluation = evaluate_run(make_run(error="boom"), [], AgentThresholds())
        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.checks[0].detail, "boom")


class ReportTests(unittest.TestCase):
    def test_report_counts_checks_and_compares_with_baseline(self) -> None:
        runs = [
            make_run(latency_ms=1000, tools=["search"]),
            make_run(latency_ms=3000, tools=["search", "send_email"]),
            make_run(latency_ms=500, tools=[], error="boom"),
        ]
        report = build_report(
            runs,
            [ToolExpectation("search", "called"), ToolExpectation("send_email", "not_called")],
            AgentThresholds(latency_ms=2500),
            AgentBaseline(run_count=4, latency_p95_ms=2000.0, tokens_avg=0.0),
        )
        self.assertEqual(report.run_count, 3)
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.pass_rate, 33.3)
        summary = {check.key: (check.passed, check.failed) for check in report.checks}
        self.assertEqual(
            summary,
            {
                "run": (2, 1),
                "tool:tool:search": (2, 1),
                "tool:tool:send_email": (2, 1),
                "latency_ms": (2, 1),
            },
        )
        deltas = {delta.metric: delta for delta in report.deltas}
        self.assertEqual(deltas["latency_p95_ms"].current, 3000.0)
        self.assertEqual(deltas["latency_p95_ms"].delta_pct, 50.0)
        # A zero or missing baseline gives no percentage rather than a division error.
        self.assertIsNone(deltas["tokens_avg"].delta_pct)
        self.assertIsNone(deltas["cost_avg_usd"].delta_pct)

    def test_empty_report(self) -> None:
        report = build_report([], [], AgentThresholds(), AgentBaseline())
        self.assertEqual((report.run_count, report.pass_rate, report.checks), (0, None, []))


class KindAssertionTests(unittest.TestCase):
    def test_assertion_matches_kind_and_name(self) -> None:
        base = make_run()
        run = AgentRun(
            **{
                **base.__dict__,
                "tool_calls": [
                    AgentToolCall("sub_agent", "Writer", "Writer", "success", 10.0),
                    AgentToolCall("tool", "Critic", "Critic", "success", 10.0),
                ],
            }
        )
        evaluation = evaluate_run(
            run,
            [
                ToolExpectation("Writer", "called", "sub_agent"),
                ToolExpectation("Critic", "called", "sub_agent"),
                ToolExpectation("wf-1", "not_called", "sub_workflow", "Billing"),
            ],
            AgentThresholds(),
        )
        checks = {check.key: (check.status, check.label) for check in evaluation.checks}
        self.assertEqual(checks["tool:sub_agent:Writer"], ("pass", "Calls sub-agent Writer"))
        # A plain tool with the same name is not the sub-agent.
        self.assertEqual(checks["tool:sub_agent:Critic"], ("fail", "Calls sub-agent Critic"))
        self.assertEqual(
            checks["tool:sub_workflow:wf-1"], ("pass", "Never calls sub-workflow Billing")
        )


if __name__ == "__main__":
    unittest.main()
