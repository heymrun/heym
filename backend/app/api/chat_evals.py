"""Eval suite tools in the dashboard chat: create, change and run prompt and agent suites.

`ChatBuildSession` offers these tools on build turns (Chat tab, MCP `heym_chat`, Heym Work
Chat) and hands their calls here; MCP clients never see them in `tools/list`. Every
operation goes through the same functions as the Evals routes, so a suite made in chat is
the suite the Evals tab shows. Each call opens its own database session: a refused change
is dropped with it and never reaches the rest of the turn.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from threading import Event
from typing import Any, get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agent_suite_runs import AgentSuiteBusyError, launch_agent_suite_run
from app.api.credentials import list_credential_models
from app.api.workflows import _spawn_detached_task
from app.db.models import CredentialType, User
from app.db.session import async_session_maker
from app.models.agent_suite_schemas import (
    AgentBaselineValues,
    AgentSuiteCreate,
    AgentSuiteRunCreate,
    AgentSuiteRunResponse,
    AgentSuiteUpdate,
    ToolKind,
)
from app.models.eval_schemas import (
    EvalSuiteCreate,
    EvalSuiteUpdate,
    EvalTestCaseUpsert,
    RunEvalsRequest,
)
from app.services import agent_suite_service as agent_suites
from app.services import prompt_suite_service as prompt_suites
from app.services.agent_suite_inputs import MAX_SUITE_RUNS
from app.services.agent_suite_metrics import (
    DEFAULT_RUN_LIMIT,
    MAX_RUN_LIMIT,
    baseline_from_json,
    list_agent_nodes,
    suggest_thresholds,
)
from app.services.chat_build_mode import BuildToolOutcome, tool_error, truncate_text
from app.services.chat_eval_mode import (
    EVAL_TOOL_NAMES,
    GET_AGENT_BASELINE_TOOL,
    GET_EVAL_RUN_TOOL,
    GET_EVAL_SUITE_TOOL,
    GET_RUN_DEFAULT_WAIT_SECONDS,
    GET_RUN_MAX_WAIT_SECONDS,
    LIST_EVAL_AGENTS_TOOL,
    LIST_EVAL_SUITES_TOOL,
    LIST_LLM_MODELS_TOOL,
    MAX_MODELS_SHOWN,
    MAX_TEST_CASES_SHOWN,
    RUN_EVAL_SUITE_TOOL,
    RUN_POLL_SECONDS,
    RUN_WAIT_SECONDS,
    SAVE_AGENT_SUITE_TOOL,
    SAVE_PROMPT_SUITE_TOOL,
    SAVE_SUITE_TOOLS,
    STEP_LABELS,
    compact_baseline,
    error_text,
    list_arg,
    number_arg,
    optional_uuid_arg,
    parse_uuid,
    step_summary,
    suite_saved_event,
    suite_url,
    summarize_agent_run,
    summarize_prompt_run,
    uuid_arg,
    without_none,
)
from app.services.credential_access import get_accessible_credential
from app.services.eval_common import EvalNotFoundError
from app.services.eval_service import DECISION_CANNOT_RUN_MESSAGE
from app.services.prompt_suite_service import SCORING_METHODS, SuiteType

# The prompt run settings the chat may pass through to RunEvalsRequest.
RUN_FIELDS = (
    "credential_id",
    "models",
    "temperature",
    "reasoning_effort",
    "max_tokens",
    "runs_per_test",
    "judge_credential_id",
    "judge_model",
)

_ID: dict[str, Any] = {"type": "string"}
_SCORING: dict[str, Any] = {
    "type": "string",
    "enum": list(SCORING_METHODS),
    "description": "exact_match for fixed labels, contains for key facts, llm_judge for free text.",
}


def _function(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


EVAL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    _function(
        LIST_EVAL_SUITES_TOOL,
        "List the user's eval suites, prompt and agent, most recently updated first, with "
        "their links.",
        {},
    ),
    _function(
        GET_EVAL_SUITE_TOOL,
        "Read one eval suite. A prompt suite returns its system prompt, scoring method, test "
        "cases with their ids and its latest runs. An agent suite returns its agent, "
        "assertions, thresholds, stored baseline, the workflow's input_fields with the last "
        "run's previous_inputs, and its latest run.",
        {"suite_id": {**_ID, "description": "Id from list_eval_suites or a save result."}},
        ["suite_id"],
    ),
    _function(
        LIST_EVAL_AGENTS_TOOL,
        "List the agent nodes in the user's workflows with how many runs each has, to choose "
        "the agent of an agent suite.",
        {},
    ),
    _function(
        GET_AGENT_BASELINE_TOOL,
        "Read an agent's baseline from its latest runs: latency, cost, tokens and tool calls, "
        "how often each tool was called, and thresholds suggested 20% above the baseline.",
        {
            "workflow_id": {**_ID},
            "node_id": {"type": "string", "description": "The agent node's id."},
            "limit": {
                "type": "integer",
                "description": f"How many latest runs to read, 1 to {MAX_RUN_LIMIT}. "
                f"Default {DEFAULT_RUN_LIMIT}.",
            },
        },
        ["workflow_id", "node_id"],
    ),
    _function(
        LIST_LLM_MODELS_TOOL,
        "List the models an LLM credential offers, to choose the models a prompt suite compares. "
        "A Decision Model credential has no list: ask the user to type its model name.",
        {
            "credential_id": {
                **_ID,
                "description": "An OpenAI, Google or OpenAI compatible credential.",
            }
        },
        ["credential_id"],
    ),
    _function(
        SAVE_PROMPT_SUITE_TOOL,
        "Create a prompt eval suite, or change one when suite_id is given. When changing, pass "
        "only what changes.",
        {
            "suite_id": {**_ID, "description": "The suite to change. Omit it to create one."},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "system_prompt": {
                "type": "string",
                "description": "The prompt every test case runs against.",
            },
            "scoring_method": _SCORING,
            "test_cases": {
                "type": "array",
                "description": "Cases to add (no id) or change (id from get_eval_suite).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "input": {"type": "string"},
                        "expected_output": {"type": "string"},
                    },
                },
            },
            "delete_test_case_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ids of cases to remove.",
            },
        },
    ),
    _function(
        SAVE_AGENT_SUITE_TOOL,
        "Create an agent eval suite for one agent node, or change one when suite_id is given. "
        "When changing, pass only what changes. The result has the stored baseline and the "
        "thresholds suggested from it.",
        {
            "suite_id": {**_ID, "description": "The suite to change. Omit it to create one."},
            "name": {"type": "string"},
            "workflow_id": {**_ID, "description": "The agent's workflow, when creating."},
            "node_id": {"type": "string", "description": "The agent node, when creating."},
            "tool_assertions": {
                "type": "array",
                "description": "Every tool check; it replaces the stored list.",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(get_args(ToolKind))},
                        "name": {
                            "type": "string",
                            "description": "A tool's name, a sub-agent's label or a "
                            "sub-workflow's id.",
                        },
                        "label": {"type": "string"},
                        "expect": {"type": "string", "enum": ["called", "not_called"]},
                    },
                    "required": ["name", "expect"],
                },
            },
            "thresholds": {
                "type": "object",
                "description": "Upper bounds per run; leave one out to turn that check off. "
                "It replaces the stored thresholds.",
                "properties": {
                    "latency_ms": {"type": "number"},
                    "cost_usd": {"type": "number"},
                    "total_tokens": {"type": "integer"},
                    "tool_calls": {"type": "integer"},
                },
            },
            "baseline": {
                "type": "object",
                "description": "Where the baseline comes from: latest_runs (the agent's last "
                "runs), suite_run (one finished run of this suite, by run_id) or manual "
                "(values the user stated).",
                "properties": {
                    "source": {"type": "string", "enum": ["latest_runs", "suite_run", "manual"]},
                    "run_id": {**_ID},
                    "values": {
                        "type": "object",
                        "properties": {
                            key: {"type": "number"} for key in AgentBaselineValues.model_fields
                        },
                    },
                },
                "required": ["source"],
            },
        },
    ),
    _function(
        RUN_EVAL_SUITE_TOOL,
        f"Run an eval suite and wait up to {int(RUN_WAIT_SECONDS)} seconds for the result. A "
        "prompt suite needs credential_id and models. An agent suite needs inputs, one object "
        "per run, and runs the real workflow.",
        {
            "suite_id": {**_ID},
            "credential_id": {
                **_ID,
                "description": "Prompt suites: the OpenAI, Google or OpenAI compatible "
                "credential the models run on. A Decision Model credential cannot run a suite; "
                "it can only judge.",
            },
            "models": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Prompt suites: the models to compare.",
            },
            "scoring_method": {
                **_SCORING,
                "description": "Prompt suites: defaults to the suite's.",
            },
            "judge_credential_id": {
                **_ID,
                "description": "llm_judge: a separate judge's credential, an OpenAI, Google, "
                "OpenAI compatible or Decision Model one. Omit it to let each model score its "
                "own answer.",
            },
            "judge_model": {
                "type": "string",
                "description": "llm_judge: the judge's model. For a Decision Model judge, ask the "
                "user to type the model name (for example jev-latest); it cannot be listed.",
            },
            "runs_per_test": {"type": "integer", "description": "Prompt suites: 1 to 20."},
            "temperature": {"type": "number"},
            "inputs": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Agent suites: one input object per run, keyed by input_fields, "
                f"at most {MAX_SUITE_RUNS}.",
            },
        },
        ["suite_id"],
    ),
    _function(
        GET_EVAL_RUN_TOOL,
        "Check a run that run_eval_suite started, waiting up to wait_seconds (at most "
        f"{int(GET_RUN_MAX_WAIT_SECONDS)}) for it to finish.",
        {"run_id": {**_ID}, "wait_seconds": {"type": "integer"}},
        ["run_id"],
    ),
]

ToolHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]


class ChatEvalTools:
    """The eval tools of one chat turn."""

    def __init__(self, *, user: User, public_base_url: str, cancel_event: Event | None) -> None:
        self.user = user
        self.public_base_url = public_base_url
        self.cancel_event = cancel_event
        self.run_wait_seconds = RUN_WAIT_SECONDS
        self.poll_seconds = RUN_POLL_SECONDS
        self._handlers: dict[str, ToolHandler] = {
            LIST_EVAL_SUITES_TOOL: self._list_suites,
            GET_EVAL_SUITE_TOOL: self._get_suite,
            LIST_EVAL_AGENTS_TOOL: self._list_agents,
            GET_AGENT_BASELINE_TOOL: self._agent_baseline,
            LIST_LLM_MODELS_TOOL: self._list_models,
            SAVE_PROMPT_SUITE_TOOL: self._save_prompt_suite,
            SAVE_AGENT_SUITE_TOOL: self._save_agent_suite,
            RUN_EVAL_SUITE_TOOL: self._run_suite,
            GET_EVAL_RUN_TOOL: self._get_run,
        }

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return list(EVAL_TOOL_SCHEMAS)

    def handles(self, name: str) -> bool:
        return name in EVAL_TOOL_NAMES

    def step_label(self, name: str) -> str:
        return STEP_LABELS[name]

    def display_args(self, _name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Arguments for the step row and the trace, with long lists counted, not copied."""
        shown = dict(args)
        for key in ("test_cases", "delete_test_case_ids", "inputs"):
            if isinstance(shown.get(key), list):
                shown[key] = len(shown[key])
        if isinstance(shown.get("system_prompt"), str):
            shown["system_prompt"] = truncate_text(shown["system_prompt"], 200)
        return shown

    async def call(self, name: str, args: dict[str, Any]) -> BuildToolOutcome:
        try:
            async with async_session_maker() as db:
                payload = await self._handlers[name](db, args)
        except (EvalNotFoundError, AgentSuiteBusyError, ValueError) as exc:
            return tool_error(error_text(exc))
        return BuildToolOutcome(
            result=json.dumps(payload, default=str),
            summary=step_summary(name, payload),
            status="success",
            events=[suite_saved_event(payload["suite"])] if name in SAVE_SUITE_TOOLS else [],
        )

    def _url(self, suite_id: object) -> str:
        return suite_url(self.public_base_url, suite_id)

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    async def _list_suites(self, db: AsyncSession, _args: dict[str, Any]) -> dict[str, Any]:
        suites = await prompt_suites.list_all_suites(db, self.user.id)
        return {
            "count": len(suites),
            "suites": [
                {
                    "id": str(suite.id),
                    "name": suite.name,
                    "suite_type": suite.suite_type,
                    "url": self._url(suite.id),
                }
                for suite in suites
            ],
        }

    async def _get_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = uuid_arg(args, "suite_id")
        if await prompt_suites.owned_suite_type(db, suite_id, self.user.id) == "prompt":
            return await self._prompt_suite_payload(db, suite_id, include_runs=True)
        return await self._agent_suite_payload(db, suite_id)

    async def _prompt_suite_payload(
        self, db: AsyncSession, suite_id: uuid.UUID, *, include_runs: bool
    ) -> dict[str, Any]:
        suite = await prompt_suites.load_owned_prompt_suite(
            db, suite_id, self.user.id, with_test_cases=True
        )
        cases = suite.test_cases
        described: dict[str, Any] = {
            "id": str(suite.id),
            "name": suite.name,
            "suite_type": "prompt",
            "description": suite.description,
            "system_prompt": suite.system_prompt,
            "scoring_method": suite.scoring_method,
            "test_cases": [
                {"id": str(tc.id), "input": tc.input, "expected_output": tc.expected_output}
                for tc in cases[:MAX_TEST_CASES_SHOWN]
            ],
        }
        if len(cases) > MAX_TEST_CASES_SHOWN:
            described["test_cases_omitted"] = len(cases) - MAX_TEST_CASES_SHOWN
        payload: dict[str, Any] = {"suite": described, "url": self._url(suite.id)}
        if include_runs:
            runs = await prompt_suites.list_prompt_runs(db, suite.id, self.user.id)
            payload["latest_runs"] = [
                {
                    "run_id": str(run.id),
                    "name": run.name,
                    "status": run.status,
                    "models": run.models,
                    "passed": run.pass_count,
                    "total": run.total_count,
                }
                for run in runs[:3]
            ]
        return payload

    async def _agent_suite_payload(self, db: AsyncSession, suite_id: uuid.UUID) -> dict[str, Any]:
        suite = await agent_suites.get_agent_suite(db, self.user.id, suite_id)
        inputs = await agent_suites.agent_run_inputs(db, self.user.id, suite_id)
        latest = await agent_suites.latest_agent_suite_run(db, suite_id)
        payload: dict[str, Any] = {
            "suite": {
                "id": str(suite.id),
                "name": suite.name,
                "suite_type": "agent",
                "workflow_id": str(suite.workflow_id),
                "workflow_name": suite.workflow_name,
                "node_id": suite.node_id,
                "node_label": suite.node_label,
                "tool_assertions": [
                    without_none(assertion.model_dump()) for assertion in suite.tool_assertions
                ],
                "thresholds": without_none(suite.thresholds.model_dump()),
            },
            "baseline": compact_baseline(suite.baseline),
            "input_fields": inputs.fields,
            "previous_inputs": inputs.previous_inputs,
            "url": self._url(suite.id),
        }
        if latest is not None:
            payload["latest_run"] = {
                "run_id": str(latest.id),
                "status": latest.status,
                "runs": latest.requested_count,
            }
        return payload

    async def _list_agents(self, db: AsyncSession, _args: dict[str, Any]) -> dict[str, Any]:
        agents = await list_agent_nodes(db, user_id=self.user.id)
        return {
            "count": len(agents),
            "agents": [
                {
                    "workflow_id": str(agent.workflow_id),
                    "workflow_name": agent.workflow_name,
                    "node_id": agent.node_id,
                    "node_label": agent.node_label,
                    "run_count": agent.run_count,
                    "last_run_at": agent.last_run_at.isoformat() if agent.last_run_at else None,
                }
                for agent in agents
            ],
        }

    async def _agent_baseline(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        limit = int(number_arg(args, "limit", default=DEFAULT_RUN_LIMIT, low=1, high=MAX_RUN_LIMIT))
        metrics = await agent_suites.agent_metrics(
            db, self.user.id, uuid_arg(args, "workflow_id"), str(args.get("node_id") or ""), limit
        )
        return {
            "workflow_name": metrics.workflow_name,
            "node_label": metrics.node_label,
            "run_count": len(metrics.runs),
            "baseline": compact_baseline(metrics.baseline),
            "tools": [without_none(tool.model_dump()) for tool in metrics.tools],
            "suggested_thresholds": without_none(metrics.suggested_thresholds.model_dump()),
        }

    async def _list_models(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        credential = await get_accessible_credential(
            db, uuid_arg(args, "credential_id"), self.user.id
        )
        if credential is None:
            raise EvalNotFoundError("Credential not found")
        if credential.type == CredentialType.decision:
            raise ValueError(DECISION_CANNOT_RUN_MESSAGE)
        models = await list_credential_models(credential)
        return {
            "credential": credential.name,
            "models": [model.id for model in models][:MAX_MODELS_SHOWN],
        }

    async def _save_prompt_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = optional_uuid_arg(args, "suite_id")
        upserts = [EvalTestCaseUpsert.model_validate(item) for item in list_arg(args, "test_cases")]
        delete_ids = [
            parse_uuid(item, "delete_test_case_ids")
            for item in list_arg(args, "delete_test_case_ids")
        ]
        fields = {
            key: args.get(key) for key in ("name", "description", "system_prompt", "scoring_method")
        }
        if suite_id is None:
            if delete_ids or any(upsert.id is not None for upsert in upserts):
                raise ValueError("A new suite has no test cases to change or delete yet")
            suite = await prompt_suites.create_prompt_suite(
                db, self.user.id, EvalSuiteCreate.model_validate(without_none(fields))
            )
            if upserts:
                await prompt_suites.apply_test_case_changes(db, suite, upserts, [])
            return await self._prompt_suite_payload(db, suite.id, include_runs=False)
        update = EvalSuiteUpdate.model_validate(fields)
        # Check everything before the first commit, so a refused edit changes nothing.
        prompt_suites.check_scoring_method(update.scoring_method)
        suite = await prompt_suites.load_owned_prompt_suite(
            db, suite_id, self.user.id, with_test_cases=True
        )
        if upserts or delete_ids:
            suite = await prompt_suites.apply_test_case_changes(db, suite, upserts, delete_ids)
        await prompt_suites.update_prompt_suite(db, suite, update)
        return await self._prompt_suite_payload(db, suite.id, include_runs=False)

    async def _save_agent_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = optional_uuid_arg(args, "suite_id")
        fields = without_none(
            {key: args.get(key) for key in ("name", "tool_assertions", "thresholds", "baseline")}
        )
        if suite_id is None:
            body = AgentSuiteCreate.model_validate(
                {**fields, "workflow_id": args.get("workflow_id"), "node_id": args.get("node_id")}
            )
            suite = await agent_suites.create_agent_suite(db, self.user.id, body)
        else:
            suite = await agent_suites.update_agent_suite(
                db, self.user.id, suite_id, AgentSuiteUpdate.model_validate(fields)
            )
        payload = await self._agent_suite_payload(db, suite.id)
        suggested = suggest_thresholds(baseline_from_json(suite.baseline.model_dump()))
        payload["suggested_thresholds"] = without_none(asdict(suggested))
        return payload

    async def _run_suite(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        suite_id = uuid_arg(args, "suite_id")
        suite_type = await prompt_suites.owned_suite_type(db, suite_id, self.user.id)
        if suite_type == "prompt":
            suite = await prompt_suites.load_owned_prompt_suite(db, suite_id, self.user.id)
            body = RunEvalsRequest.model_validate(
                {
                    **without_none({key: args.get(key) for key in RUN_FIELDS}),
                    "scoring_method": args.get("scoring_method") or suite.scoring_method,
                }
            )
            launch = await prompt_suites.launch_prompt_run(db, self.user, suite_id, body)
            run_id, job = launch.run.id, launch.job
        else:
            inputs = list_arg(args, "inputs")
            if not inputs:
                raise ValueError(
                    f"Write one input object per run in inputs, at most {MAX_SUITE_RUNS}."
                )
            agent_suite = await agent_suites.load_owned_agent_suite(db, suite_id, self.user.id)
            agent_launch = await launch_agent_suite_run(
                db,
                self.user.id,
                agent_suite,
                AgentSuiteRunCreate.model_validate({"inputs_list": inputs}),
                self.public_base_url,
            )
            run_id, job = agent_launch.suite_run.id, agent_launch.job
        _spawn_detached_task(job.coroutine())
        return await self._wait(suite_type, run_id, self.run_wait_seconds)

    async def _get_run(self, db: AsyncSession, args: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid_arg(args, "run_id")
        wait = number_arg(
            args,
            "wait_seconds",
            default=GET_RUN_DEFAULT_WAIT_SECONDS,
            low=0,
            high=GET_RUN_MAX_WAIT_SECONDS,
        )
        return await self._wait(await self._owned_run_type(db, run_id), run_id, wait)

    async def _owned_run_type(self, db: AsyncSession, run_id: uuid.UUID) -> SuiteType:
        try:
            await prompt_suites.load_owned_prompt_run(db, run_id, self.user.id)
            return "prompt"
        except EvalNotFoundError:
            await agent_suites.load_owned_agent_suite_run(db, run_id, self.user.id)
            return "agent"

    async def _wait(
        self, suite_type: SuiteType, run_id: uuid.UUID, seconds: float
    ) -> dict[str, Any]:
        """Poll the run with a fresh session until it ends, the time is up or the turn stops."""
        deadline = time.monotonic() + seconds
        while True:
            async with async_session_maker() as db:
                payload = await self._run_state(db, suite_type, run_id)
            if payload["status"] != "running" or time.monotonic() >= deadline or self._cancelled():
                return payload
            await asyncio.sleep(self.poll_seconds)

    async def _run_state(
        self, db: AsyncSession, suite_type: SuiteType, run_id: uuid.UUID
    ) -> dict[str, Any]:
        if suite_type == "prompt":
            run = await prompt_suites.load_owned_prompt_run(db, run_id, self.user.id)
            url = self._url(run.suite_id)
            if run.status == "running":
                return {
                    "run_id": str(run.id),
                    "suite_type": "prompt",
                    "status": "running",
                    "results_so_far": len(run.results),
                    "url": url,
                }
            response = prompt_suites.prompt_run_response(run, run.results)
            return {**summarize_prompt_run(response), "url": url}
        suite_run = await agent_suites.load_owned_agent_suite_run(db, run_id, self.user.id)
        report = None
        if suite_run.status != "running":
            report = await agent_suites.agent_suite_report(
                db, self.user.id, suite_run.suite_id, MAX_RUN_LIMIT, suite_run.id
            )
        response = AgentSuiteRunResponse.model_validate(suite_run)
        return {**summarize_agent_run(response, report), "url": self._url(suite_run.suite_id)}
