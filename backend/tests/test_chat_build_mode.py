"""The rules of a chat build turn: budget, finish, run report, instructions."""

import unittest
import uuid

from app.services.chat_build_mode import (
    MAX_BUILD_TEST_RUNS,
    REPORT_MAX_NODES,
    REPORT_OUTPUTS_MAX_CHARS,
    BuildProgress,
    build_mode_instructions,
    build_run_report,
)


class BuildProgressTests(unittest.TestCase):
    def test_finish_needs_a_saved_or_targeted_workflow(self) -> None:
        self.assertIn("no workflow", BuildProgress().finish_refusal() or "")

    def test_finish_needs_a_passing_run_of_the_latest_save(self) -> None:
        progress = BuildProgress()
        progress.record_save(uuid.uuid4())
        self.assertIsNotNone(progress.finish_refusal())

        progress.record_run("error")
        self.assertIsNotNone(progress.finish_refusal())

        progress.record_run("success")
        self.assertIsNone(progress.finish_refusal())

        progress.record_save(progress.workflow_id)
        self.assertIsNotNone(progress.finish_refusal())

    def test_an_existing_target_can_be_verified_without_a_save(self) -> None:
        progress = BuildProgress(workflow_id=uuid.uuid4())
        progress.record_run("success")
        self.assertIsNone(progress.finish_refusal())

    def test_budget_is_spent_after_the_last_allowed_run(self) -> None:
        progress = BuildProgress(workflow_id=uuid.uuid4())
        attempts = [progress.record_run("error") for _ in range(MAX_BUILD_TEST_RUNS)]

        self.assertEqual(attempts, list(range(1, MAX_BUILD_TEST_RUNS + 1)))
        self.assertTrue(progress.budget_spent)


class BuildRunReportTests(unittest.TestCase):
    def test_reports_status_nodes_and_error(self) -> None:
        result = {
            "status": "error",
            "execution_time_ms": 812,
            "outputs": {"Result": {"text": "partial"}},
            "node_results": [
                {
                    "node_label": "start",
                    "node_type": "textInput",
                    "status": "success",
                    "output": {"text": "hi"},
                },
                {"node_label": "skipped", "node_type": "llm", "status": "skipped", "output": {}},
                {
                    "node_label": "Call API",
                    "node_type": "http",
                    "status": "error",
                    "error": "401 Unauthorized",
                    "output": {},
                },
            ],
            "error": "Node Call API failed",
            "execution_history_id": "hist-1",
        }

        report = build_run_report(
            result, attempt=2, inputs={"text": "hi"}, expect="Returns the lead id"
        )

        self.assertEqual(report["attempt"], 2)
        self.assertEqual(report["max_attempts"], MAX_BUILD_TEST_RUNS)
        self.assertEqual(report["status"], "error")
        self.assertEqual([n["label"] for n in report["nodes"]], ["start", "Call API"])
        self.assertEqual(report["nodes"][1]["error"], "401 Unauthorized")
        self.assertNotIn("output", report["nodes"][1])
        self.assertEqual(report["error"], "Node Call API failed")
        self.assertEqual(report["execution_history_id"], "hist-1")

    def test_bounds_large_outputs_and_many_nodes(self) -> None:
        nodes = [
            {"node_label": f"n{i}", "node_type": "set", "status": "success", "output": {"i": i}}
            for i in range(REPORT_MAX_NODES + 5)
        ]
        result = {
            "status": "success",
            "outputs": {"blob": "x" * (REPORT_OUTPUTS_MAX_CHARS * 2)},
            "node_results": nodes,
        }

        report = build_run_report(result, attempt=1, inputs={}, expect="")

        self.assertIsInstance(report["outputs"], str)
        self.assertTrue(report["outputs"].endswith("...[truncated]"))
        self.assertLessEqual(len(report["outputs"]), REPORT_OUTPUTS_MAX_CHARS)
        self.assertEqual(len(report["nodes"]), REPORT_MAX_NODES)
        self.assertEqual(report["nodes_omitted"], 5)


class BuildModeInstructionsTests(unittest.TestCase):
    def test_names_the_tools_and_the_budget(self) -> None:
        text = build_mode_instructions(None, None)

        for name in ("save_workflow", "run_workflow_test", "finish"):
            self.assertIn(name, text)
        self.assertIn(f"At most {MAX_BUILD_TEST_RUNS} test runs", text)
        self.assertNotIn("target workflow for this turn", text)

    def test_names_the_target_workflow(self) -> None:
        target = uuid.uuid4()

        text = build_mode_instructions("Lead intake", target)

        self.assertIn(f'"Lead intake" ({target})', text)
        self.assertIn("never create a second workflow", text)


if __name__ == "__main__":
    unittest.main()
