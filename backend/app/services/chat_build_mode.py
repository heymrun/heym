"""Chat build mode: the rules of one build turn, without database or model access.

In build mode the dashboard chat saves a workflow with `save_workflow`, runs it with
`run_workflow_test`, fixes it and ends with `finish` (Spec 2, 8.1). This module holds what
those tools share: the test budget, the progress of the turn, the bounded run report and
the instructions added to the system prompt. `app/api/chat_build.py` runs the tools.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

# The same budget as the editor's YOLO loop (MAX_YOLO_ATTEMPTS in yoloProtocol.ts).
MAX_BUILD_TEST_RUNS = 5

SAVE_WORKFLOW_TOOL = "save_workflow"
RUN_WORKFLOW_TEST_TOOL = "run_workflow_test"
FINISH_TOOL = "finish"
BUILD_TOOL_NAMES = frozenset({SAVE_WORKFLOW_TOOL, RUN_WORKFLOW_TEST_TOOL, FINISH_TOOL})

# The AI Builder tools build with a second model call; build mode builds with the DSL itself.
AI_BUILDER_TOOL_NAMES = frozenset({"create_workflow", "edit_workflow"})

REPORT_INPUTS_MAX_CHARS = 2000
REPORT_OUTPUTS_MAX_CHARS = 4000
REPORT_NODE_OUTPUT_MAX_CHARS = 1500
REPORT_MAX_NODES = 40

BUDGET_SPENT_MESSAGE = (
    f"The test run budget for this turn is spent ({MAX_BUILD_TEST_RUNS} of "
    f"{MAX_BUILD_TEST_RUNS}). Do not call build tools again. Tell the user what the last run "
    "showed, what still fails and what you would change next."
)


@dataclass(frozen=True)
class BuildRequest:
    """A turn that may build. `target_workflow_id` is the workflow an AI edit changes."""

    target_workflow_id: uuid.UUID | None = None


@dataclass
class BuildProgress:
    """What one build turn has done so far."""

    workflow_id: uuid.UUID | None = None
    revision: int = 0
    runs_used: int = 0
    passed_revision: int | None = None
    run_statuses: list[str] = field(default_factory=list)

    @property
    def budget_spent(self) -> bool:
        return self.runs_used >= MAX_BUILD_TEST_RUNS

    def record_save(self, workflow_id: uuid.UUID) -> None:
        """A save changes what was tested: the next finish needs a new passing run."""
        self.workflow_id = workflow_id
        self.revision += 1
        self.passed_revision = None

    def record_run(self, status: str) -> int:
        """Count a test run and return its attempt number."""
        self.runs_used += 1
        self.run_statuses.append(status)
        if status == "success":
            self.passed_revision = self.revision
        return self.runs_used

    def finish_refusal(self) -> str | None:
        """Why `finish` cannot end the turn yet, or None when it can."""
        if self.workflow_id is None:
            return "There is no workflow to finish. Save one with save_workflow first."
        if self.passed_revision != self.revision:
            return (
                "finish needs a successful run_workflow_test of the latest save. Run it, "
                "or fix the workflow and save it again."
            )
        return None


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    suffix = "...[truncated]"
    return text[: max(0, max_chars - len(suffix))] + suffix


def _bounded_json(value: Any, max_chars: int) -> Any:
    """The value itself when it is small, a truncated JSON string otherwise."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= max_chars:
        return value
    return _truncate(text, max_chars)


def build_run_report(
    result: dict[str, Any],
    *,
    attempt: int,
    inputs: dict[str, Any],
    expect: str,
) -> dict[str, Any]:
    """A bounded report of one test run, shaped like the editor's `[YOLO run report]`."""
    node_results = result.get("node_results")
    nodes: list[dict[str, Any]] = []
    for node in node_results if isinstance(node_results, list) else []:
        if not isinstance(node, dict) or node.get("status") == "skipped":
            continue
        entry: dict[str, Any] = {
            "label": node.get("node_label"),
            "type": node.get("node_type"),
            "status": node.get("status"),
        }
        if node.get("error"):
            entry["error"] = _truncate(str(node["error"]), REPORT_NODE_OUTPUT_MAX_CHARS)
        if node.get("output") not in (None, {}, []):
            entry["output"] = _bounded_json(node["output"], REPORT_NODE_OUTPUT_MAX_CHARS)
        nodes.append(entry)
    report: dict[str, Any] = {
        "attempt": attempt,
        "max_attempts": MAX_BUILD_TEST_RUNS,
        "status": result.get("status") or "error",
        "execution_time_ms": result.get("execution_time_ms"),
        "inputs": _bounded_json(inputs, REPORT_INPUTS_MAX_CHARS),
        "expect": expect,
        "nodes": nodes[:REPORT_MAX_NODES],
        "outputs": _bounded_json(result.get("outputs"), REPORT_OUTPUTS_MAX_CHARS),
    }
    if len(nodes) > REPORT_MAX_NODES:
        report["nodes_omitted"] = len(nodes) - REPORT_MAX_NODES
    if result.get("error"):
        report["error"] = _truncate(str(result["error"]), REPORT_NODE_OUTPUT_MAX_CHARS)
    if result.get("pending_review"):
        report["pending_review"] = result["pending_review"]
    if result.get("execution_history_id"):
        report["execution_history_id"] = result["execution_history_id"]
    return report


def build_mode_instructions(target_name: str | None, target_id: uuid.UUID | None) -> str:
    """The build mode section of the system prompt; the DSL reference follows it."""
    lines = [
        "",
        "## Build mode",
        "",
        "Build mode is on. You can build a new workflow or change the target workflow, test it "
        "with real runs, fix it and finish. You still answer questions and run existing "
        "workflows as usual; a turn that does neither needs no build tools.",
        "",
        "Tools:",
        "- save_workflow: pass the complete workflow (name, description, every node and edge) "
        "in the format of the Workflow DSL reference below. It creates a workflow, or updates "
        "the target workflow when the turn has one. That format is the tool's `workflow` "
        "argument: never paste workflow JSON in your reply. To change a workflow saved earlier "
        "in this conversation, pass its workflow_id instead of creating a second one.",
        "- run_workflow_test: run the saved workflow with realistic sample inputs keyed by its "
        "input field keys, and one `expect` sentence describing a successful run. Runs are "
        "real, so their side effects happen. The result is a run report with the status, each "
        f"node's result and the outputs. At most {MAX_BUILD_TEST_RUNS} test runs per turn.",
        "- finish: when the latest run of the latest save shows the request is fully done, end "
        "the turn with one sentence on what the workflow now does. It is refused until a test "
        "run of the latest save succeeds.",
        "",
        "Rules:",
        "- Compare every run report with the user's request. Never finish after a failed or "
        "wrong run, unless that outcome is exactly what the user asked for.",
        "- To fix the workflow, change only what the report shows is wrong and save the "
        "complete workflow again.",
        "- When you need the user (missing information, a credential to create or pick, a data "
        "table to pick or create, a decision), ask with a heym-clarify block and stop. The "
        "turn resumes after the answers.",
        "- When the test budget is spent, stop and tell the user what still fails and what you "
        "would change.",
    ]
    if target_id is not None:
        lines += [
            "",
            f'The target workflow for this turn is "{target_name or "Untitled"}" ({target_id}). '
            "save_workflow updates it; never create a second workflow for this request. Its "
            "current definition is under Current Workflow Context in the reference below.",
        ]
    return "\n".join(lines) + "\n"
