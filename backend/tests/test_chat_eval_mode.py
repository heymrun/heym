"""Eval tools in chat: argument parsing, result shapes and the prompt section."""

import unittest
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

from app.models.agent_suite_schemas import (
    AgentBaselineResponse,
    AgentBaselineSource,
    AgentCheckResultResponse,
    AgentCheckSummaryResponse,
    AgentMetricDeltaResponse,
    AgentRunEvaluationResponse,
    AgentSuiteReportResponse,
    AgentSuiteRunResponse,
    AgentSuiteRunResult,
)
from app.models.eval_schemas import EvalRunResponse, EvalRunResultResponse
from app.services import chat_eval_mode as mode
from app.services.agent_suite_inputs import MAX_SUITE_RUNS

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


def _result(model: str, score: str, actual: str, **extra: object) -> EvalRunResultResponse:
    return EvalRunResultResponse(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        test_case_id=None,
        model_id=model,
        input_snapshot="question",
        expected_output_snapshot="answer",
        actual_output=actual,
        score=score,
        latency_ms=extra.get("latency_ms"),
        tokens_used=extra.get("tokens_used"),
        error=extra.get("error"),
        explanation=extra.get("explanation"),
        created_at=NOW,
    )


def _run(results: list[EvalRunResultResponse], status: str = "completed") -> EvalRunResponse:
    return EvalRunResponse(
        id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
        name="Run #1",
        system_prompt_snapshot="",
        models=["gpt-4o", "gpt-4.1-mini"],
        scoring_method="exact_match",
        temperature=0.7,
        max_tokens=None,
        status=status,
        created_at=NOW,
        completed_at=NOW,
        results=results,
    )


def _evaluation(passed: bool) -> AgentRunEvaluationResponse:
    status = "pass" if passed else "fail"
    return AgentRunEvaluationResponse(
        trace_id=uuid.uuid4(),
        created_at=NOW,
        model="m",
        latency_ms=1.0,
        model_ms=1.0,
        tool_ms=0.0,
        cost_usd=None,
        total_tokens=1,
        tool_count=0,
        tool_calls=[],
        error=None,
        passed=passed,
        checks=[
            AgentCheckResultResponse(
                key="tool:tool:search", label="search", kind="assertion", status=status
            )
        ],
    )


class ArgumentTests(unittest.TestCase):
    def test_ids_are_parsed_or_refused(self) -> None:
        value = uuid.uuid4()
        self.assertEqual(mode.uuid_arg({"suite_id": str(value)}, "suite_id"), value)
        self.assertIsNone(mode.optional_uuid_arg({}, "suite_id"))
        with self.assertRaises(ValueError):
            mode.uuid_arg({}, "suite_id")
        with self.assertRaises(ValueError):
            mode.uuid_arg({"suite_id": "nope"}, "suite_id")

    def test_lists_and_numbers(self) -> None:
        self.assertEqual(mode.list_arg({}, "inputs"), [])
        with self.assertRaises(ValueError):
            mode.list_arg({"inputs": "x"}, "inputs")
        self.assertEqual(mode.number_arg({"w": 500}, "w", default=30, low=0, high=120), 120)
        self.assertEqual(mode.number_arg({}, "w", default=30, low=0, high=120), 30)

    def test_validation_errors_read_short(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            AgentBaselineSource(source="manual")
        self.assertEqual(mode.error_text(ctx.exception), "A manual baseline needs values")
        self.assertEqual(mode.error_text(ValueError("plain")), "plain")

    def test_suite_url_is_absolute(self) -> None:
        self.assertEqual(
            mode.suite_url("https://heym.example/", "abc"), "https://heym.example/evals?suite=abc"
        )


class SummaryTests(unittest.TestCase):
    def test_prompt_run_counts_per_model_and_keeps_five_failures(self) -> None:
        results = [
            _result("gpt-4o", "pass", "answer", latency_ms=100, tokens_used=10),
            _result("gpt-4o", "fail", "x" * 1000, latency_ms=300, tokens_used=30),
            *[_result("gpt-4.1-mini", "0", "wrong", explanation="off") for _ in range(6)],
        ]
        summary = mode.summarize_prompt_run(_run(results))
        self.assertEqual(
            summary["models"],
            [
                {
                    "model": "gpt-4o",
                    "passed": 1,
                    "total": 2,
                    "avg_latency_ms": 200,
                    "avg_tokens": 20,
                },
                {"model": "gpt-4.1-mini", "passed": 0, "total": 6},
            ],
        )
        self.assertEqual(summary["failed_count"], 7)
        self.assertEqual(len(summary["failures"]), mode.MAX_FAILURES_SHOWN)
        self.assertLessEqual(len(summary["failures"][0]["actual"]), mode.TEXT_MAX_CHARS)

    def test_agent_run_keeps_failed_runs_and_their_failed_checks(self) -> None:
        report = AgentSuiteReportResponse(
            suite_id=uuid.uuid4(),
            run_count=2,
            passed_count=1,
            pass_rate=50.0,
            checks=[
                AgentCheckSummaryResponse(
                    key="tool:tool:search",
                    label="search",
                    kind="assertion",
                    passed=1,
                    failed=1,
                    skipped=0,
                )
            ],
            current=AgentBaselineResponse(),
            baseline=AgentBaselineResponse(),
            deltas=[
                AgentMetricDeltaResponse(
                    metric="latency_p95_ms", baseline=None, current=1.0, delta_pct=None
                )
            ],
            runs=[_evaluation(True), _evaluation(False)],
        )
        suite_run = AgentSuiteRunResponse(
            id=uuid.uuid4(),
            suite_id=report.suite_id,
            status="completed",
            requested_count=2,
            generate_inputs=False,
            inputs=[{}, {}],
            results=[AgentSuiteRunResult(status="success"), AgentSuiteRunResult(status="error")],
            error=None,
            created_at=NOW,
            completed_at=NOW,
        )
        summary = mode.summarize_agent_run(suite_run, report)
        self.assertEqual(summary["execution_statuses"], {"success": 1, "error": 1})
        self.assertEqual(summary["report"]["pass_rate"], 50.0)
        self.assertEqual(
            summary["report"]["failed_runs"][0]["failed_checks"], [{"label": "search"}]
        )
        self.assertEqual(
            summary["report"]["deltas"], [{"metric": "latency_p95_ms", "current": 1.0}]
        )

    def test_step_summaries(self) -> None:
        self.assertEqual(mode.step_summary(mode.LIST_EVAL_SUITES_TOOL, {"count": 2}), "2 suites")
        running = {"status": "running", "suite_type": "prompt"}
        self.assertEqual(mode.step_summary(mode.RUN_EVAL_SUITE_TOOL, running), "Still running")
        done = {
            "status": "completed",
            "suite_type": "prompt",
            "models": [{"model": "gpt-4o", "passed": 4, "total": 5}],
        }
        self.assertEqual(mode.step_summary(mode.GET_EVAL_RUN_TOOL, done), "gpt-4o: 4/5 passed")


class InstructionTests(unittest.TestCase):
    def test_the_prompt_section_states_the_rules(self) -> None:
        text = mode.eval_instructions()
        self.assertIn("## Eval suites", text)
        self.assertIn("When exactly one fits, use it without asking", text)
        self.assertIn('"source": "suite_run"', text)
        self.assertIn('"source": "manual"', text)
        self.assertIn(f"At most {MAX_SUITE_RUNS} per call", text)

    def test_every_tool_has_a_step_label(self) -> None:
        self.assertEqual(len(mode.EVAL_TOOL_NAMES), 9)
        for name in mode.EVAL_TOOL_NAMES:
            self.assertTrue(mode.STEP_LABELS[name].endswith("..."))


if __name__ == "__main__":
    unittest.main()
