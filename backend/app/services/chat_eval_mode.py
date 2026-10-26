"""Eval tools in chat: names, limits, argument parsing, result shapes and the prompt section,
without database or model access.

`app/api/chat_evals.py` runs the tools. Build turns of the dashboard chat (Chat tab, MCP
`heym_chat`, Heym Work Chat) offer them; skill-only turns and the canvas assistant do not,
and MCP clients never see them in `tools/list`.
"""

import uuid
from collections import Counter
from statistics import mean
from typing import Any

from pydantic import ValidationError

from app.models.agent_suite_schemas import (
    AgentBaselineResponse,
    AgentSuiteReportResponse,
    AgentSuiteRunResponse,
)
from app.models.eval_schemas import EvalRunResponse, EvalRunResultResponse
from app.services.agent_suite_inputs import MAX_SUITE_RUNS
from app.services.chat_build_mode import truncate_text
from app.services.prompt_suite_service import is_passing

LIST_EVAL_SUITES_TOOL = "list_eval_suites"
GET_EVAL_SUITE_TOOL = "get_eval_suite"
LIST_EVAL_AGENTS_TOOL = "list_eval_agents"
GET_AGENT_BASELINE_TOOL = "get_agent_baseline"
LIST_LLM_MODELS_TOOL = "list_llm_models"
SAVE_PROMPT_SUITE_TOOL = "save_prompt_suite"
SAVE_AGENT_SUITE_TOOL = "save_agent_suite"
RUN_EVAL_SUITE_TOOL = "run_eval_suite"
GET_EVAL_RUN_TOOL = "get_eval_run"

STEP_LABELS: dict[str, str] = {
    LIST_EVAL_SUITES_TOOL: "Listing eval suites...",
    GET_EVAL_SUITE_TOOL: "Reading the eval suite...",
    LIST_EVAL_AGENTS_TOOL: "Listing agents...",
    GET_AGENT_BASELINE_TOOL: "Reading the agent's baseline...",
    LIST_LLM_MODELS_TOOL: "Listing models...",
    SAVE_PROMPT_SUITE_TOOL: "Saving the prompt suite...",
    SAVE_AGENT_SUITE_TOOL: "Saving the agent suite...",
    RUN_EVAL_SUITE_TOOL: "Running the eval suite...",
    GET_EVAL_RUN_TOOL: "Checking the eval run...",
}
EVAL_TOOL_NAMES = frozenset(STEP_LABELS)
SAVE_SUITE_TOOLS = frozenset({SAVE_PROMPT_SUITE_TOOL, SAVE_AGENT_SUITE_TOOL})

# Sent when a suite is created or changed, like `workflow_created` for a saved workflow.
EVAL_SUITE_SAVED_EVENT = "eval_suite_saved"

RUN_WAIT_SECONDS = 60.0
GET_RUN_DEFAULT_WAIT_SECONDS = 30.0
GET_RUN_MAX_WAIT_SECONDS = 120.0
RUN_POLL_SECONDS = 2.0
MAX_FAILURES_SHOWN = 5
MAX_TEST_CASES_SHOWN = 50
MAX_MODELS_SHOWN = 100
TEXT_MAX_CHARS = 400


def parse_uuid(raw: object, key: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise ValueError(f"{key} must be an id") from None


def uuid_arg(args: dict[str, Any], key: str) -> uuid.UUID:
    raw = args.get(key)
    if raw is None or raw == "":
        raise ValueError(f"{key} is required")
    return parse_uuid(raw, key)


def optional_uuid_arg(args: dict[str, Any], key: str) -> uuid.UUID | None:
    raw = args.get(key)
    if raw is None or raw == "":
        return None
    return parse_uuid(raw, key)


def list_arg(args: dict[str, Any], key: str) -> list[Any]:
    value = args.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def number_arg(args: dict[str, Any], key: str, *, default: float, low: float, high: float) -> float:
    raw = args.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be a number") from None
    return max(low, min(high, value))


def error_text(exc: Exception) -> str:
    """A short message for the model: pydantic's field errors without the boilerplate."""
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"])
            message = str(error["msg"]).removeprefix("Value error, ")
            parts.append(f"{location}: {message}" if location else message)
        return "; ".join(parts)
    return str(exc)


def suite_url(public_base_url: str, suite_id: object) -> str:
    """The suite on the Evals page, on the public origin so MCP clients can open it."""
    return f"{public_base_url.rstrip('/')}/evals?suite={suite_id}"


def suite_saved_event(suite: dict[str, Any]) -> dict[str, Any]:
    """The stream event for a saved suite: the chat shows a link card, MCP lists the link."""
    return {
        "type": EVAL_SUITE_SAVED_EVENT,
        "suite_id": suite["id"],
        "suite_name": suite["name"],
        "suite_type": suite["suite_type"],
        "suite_url": f"/evals?suite={suite['id']}",
    }


def without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def without_empty(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, [], {})}


def compact_baseline(baseline: AgentBaselineResponse) -> dict[str, Any]:
    return without_empty(baseline.model_dump(mode="json"))


def _short(text: str | None) -> str | None:
    return truncate_text(text, TEXT_MAX_CHARS) if text else None


def summarize_prompt_run(run: EvalRunResponse) -> dict[str, Any]:
    """Pass counts per model and the first failed cases of a finished prompt run."""
    by_model: dict[str, list[EvalRunResultResponse]] = {}
    for result in run.results:
        by_model.setdefault(result.model_id, []).append(result)
    order = [*run.models, *(model for model in by_model if model not in run.models)]
    models = []
    for model in order:
        results = by_model.get(model, [])
        latencies = [r.latency_ms for r in results if r.latency_ms is not None]
        tokens = [r.tokens_used for r in results if r.tokens_used is not None]
        models.append(
            without_empty(
                {
                    "model": model,
                    "passed": sum(1 for r in results if is_passing(r.score)),
                    "total": len(results),
                    "avg_latency_ms": round(mean(latencies)) if latencies else None,
                    "avg_tokens": round(mean(tokens)) if tokens else None,
                }
            )
        )
    failed = [r for r in run.results if not is_passing(r.score)]
    failures = [
        without_empty(
            {
                "model": r.model_id,
                "input": _short(r.input_snapshot),
                "expected": _short(r.expected_output_snapshot),
                "actual": _short(r.actual_output),
                "score": r.score,
                "explanation": _short(r.explanation),
                "error": _short(r.error),
            }
        )
        for r in failed[:MAX_FAILURES_SHOWN]
    ]
    return without_empty(
        {
            "run_id": str(run.id),
            "suite_type": "prompt",
            "name": run.name,
            "status": run.status,
            "scoring_method": run.scoring_method,
            "judge_model": run.judge_model,
            "models": models,
            "failed_count": len(failed),
            "failures": failures,
        }
    )


def summarize_agent_run(
    suite_run: AgentSuiteRunResponse, report: AgentSuiteReportResponse | None
) -> dict[str, Any]:
    """How a suite run's executions ended and, once it is over, how its agent runs scored."""
    payload: dict[str, Any] = {
        "run_id": str(suite_run.id),
        "suite_type": "agent",
        "status": suite_run.status,
        "requested_runs": suite_run.requested_count,
        "finished_runs": len(suite_run.results),
        "execution_statuses": dict(Counter(result.status for result in suite_run.results)),
    }
    if suite_run.error:
        payload["error"] = _short(suite_run.error)
    if report is None:
        return payload
    failed_runs = [run for run in report.runs if not run.passed]
    payload["report"] = {
        "run_count": report.run_count,
        "passed_count": report.passed_count,
        "pass_rate": report.pass_rate,
        "checks": [
            {"label": c.label, "passed": c.passed, "failed": c.failed, "skipped": c.skipped}
            for c in report.checks
        ],
        "deltas": [
            without_empty(
                {
                    "metric": d.metric,
                    "baseline": d.baseline,
                    "current": d.current,
                    "delta_pct": d.delta_pct,
                }
            )
            for d in report.deltas
        ],
        "failed_runs": [
            {
                "trace_id": str(run.trace_id),
                "failed_checks": [
                    without_empty({"label": c.label, "detail": c.detail})
                    for c in run.checks
                    if c.status == "fail"
                ],
            }
            for run in failed_runs[:MAX_FAILURES_SHOWN]
        ],
    }
    return payload


def step_summary(name: str, payload: dict[str, Any]) -> str:
    """The one-line step row the chat shows for a finished tool call."""
    if name == LIST_EVAL_SUITES_TOOL:
        return f"{payload['count']} suites"
    if name == LIST_EVAL_AGENTS_TOOL:
        return f"{payload['count']} agents"
    if name == LIST_LLM_MODELS_TOOL:
        return f"{len(payload['models'])} models"
    if name == GET_AGENT_BASELINE_TOOL:
        return f"Baseline from {payload['run_count']} runs"
    if name in (GET_EVAL_SUITE_TOOL, SAVE_PROMPT_SUITE_TOOL, SAVE_AGENT_SUITE_TOOL):
        suite = payload["suite"]
        verb = "Read" if name == GET_EVAL_SUITE_TOOL else "Saved"
        return f'{verb} {suite["suite_type"]} suite "{suite["name"]}"'
    if payload.get("status") == "running":
        return "Still running"
    if payload.get("suite_type") == "prompt":
        counts = [
            f"{m['model']}: {m.get('passed', 0)}/{m.get('total', 0)} passed"
            for m in payload.get("models", [])
        ]
        return ", ".join(counts) or str(payload.get("status"))
    report = payload.get("report") or {}
    return f"{report.get('passed_count', 0)}/{report.get('run_count', 0)} runs passed"


def eval_instructions() -> str:
    """The eval section of the build-mode system prompt."""
    lines = [
        "",
        "## Eval suites",
        "",
        "You can create, change and run the user's eval suites in Evals. A prompt suite scores "
        "a system prompt's answers to test cases on one or more models. An agent suite checks "
        "one agent node's runs against tool-call assertions and thresholds and compares them "
        "with a baseline.",
        "",
        "Prompt suites:",
        "- Before you create a prompt suite, or run one when this conversation has not settled "
        "it, settle the run settings. The LLM credential: the user's credentials of type "
        "openai, google, custom or model_router in the Credentials list. When exactly one "
        "fits, use it without asking and name it in your reply. Otherwise ask with one "
        "heym-clarify single question listing them, following the Credentials rules. The "
        "models: call list_llm_models for that credential and ask which to compare, unless "
        "the user named them. For llm_judge scoring, also ask whether a separate judge "
        "credential and model should score the answers, or each model scores its own.",
        "- Write the test cases yourself, each with an input and its expected output, from the "
        "system prompt and the user's goal: 5 unless the user asks for another number. Choose "
        "the scoring method that fits: exact_match for fixed labels, contains for key facts, "
        "llm_judge for free text.",
        "- To change a suite, read it with get_eval_suite, then pass case ids to change cases, "
        "delete_test_case_ids to remove them, and new cases without an id.",
        "",
        "Agent suites:",
        "- Find the agent with list_eval_agents. When several match the user's words, ask which.",
        "- Runs execute the real workflow, so its side effects happen. Run an agent suite only "
        "when the user asked for runs or for a baseline built from runs, and say how many runs "
        f"you start. At most {MAX_SUITE_RUNS} per call.",
        "- Write the run inputs yourself: one object per run, keyed by input_fields from "
        "get_eval_suite, shaped like previous_inputs when there is one, realistic and varied.",
        "- Report the baseline with get_agent_baseline, or the stored baseline from "
        "get_eval_suite. When the agent has no runs, or the user wants a baseline from fresh "
        "runs, run the suite, wait until the run has completed, then call save_agent_suite "
        'with baseline {"source": "suite_run", "run_id": "<run id>"} and offer the suggested '
        "thresholds it returns. When the user states numbers, save "
        '{"source": "manual", "values": {...}}.',
        "",
        "Runs and replies:",
        f"- run_eval_suite waits up to {int(RUN_WAIT_SECONDS)} seconds. When it returns status "
        "running, say the run continues in Evals, or call get_eval_run to wait longer.",
        "- Link every suite you mention with its url as a markdown link. Never ask again what "
        "this conversation already answered.",
        "",
    ]
    return "\n".join(lines)
