"""Eval tools in the dashboard chat, against real PostgreSQL.

Covers what a Chat tab or `heym_chat` turn can do with eval suites: create and change
prompt and agent suites, run them and wait for the result, build an agent's baseline from
a chat run, and never reach another user's suites, runs or credentials. The workflow and
model calls are stubbed; everything the tools read and write is real.
"""

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete

from app.api import chat_evals
from app.db.models import (
    Credential,
    CredentialType,
    EvalRun,
    EvalRunResult,
    LLMTrace,
    User,
    Workflow,
)
from app.db.session import async_session_maker, engine
from app.models.schemas import LLMModel
from app.services import eval_service

AGENT_NODE = "agent-1"
BASE_URL = "https://heym.example"


class RealPostgresChatEvalToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.credential_id = uuid.uuid4()
        self.outsider_credential_id = uuid.uuid4()
        self.run_trace_ids = [uuid.uuid4(), uuid.uuid4()]
        now = datetime.now(timezone.utc)

        def trace(trace_id: uuid.UUID, minutes_ago: int, elapsed_ms: float) -> LLMTrace:
            return LLMTrace(
                id=trace_id,
                user_id=self.owner_id,
                workflow_id=self.workflow_id,
                node_id=AGENT_NODE,
                source="workflow",
                request_type="chat.completions",
                model="chat-evals-test-model",
                request={},
                response={
                    "tool_calls": [{"name": "search", "status": "success"}],
                    "tool_metrics": {"count": 1, "total_duration_ms": 0},
                },
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                elapsed_ms=elapsed_ms,
                created_at=now - timedelta(minutes=minutes_ago),
            )

        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"chat_evals_{user_id.hex[:8]}@example.com",
                        hashed_password="x",
                        name="User",
                    )
                    for user_id in (self.owner_id, self.outsider_id)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Credential(
                        id=self.credential_id,
                        owner_id=self.owner_id,
                        name=f"openai-{self.credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                    Credential(
                        id=self.outsider_credential_id,
                        owner_id=self.outsider_id,
                        name=f"theirs-{self.outsider_credential_id.hex[:6]}",
                        type=CredentialType.openai,
                        encrypted_config="x",
                    ),
                    Workflow(
                        id=self.workflow_id,
                        name="Support flow",
                        owner_id=self.owner_id,
                        nodes=[
                            {
                                "id": "start",
                                "type": "textInput",
                                "data": {"label": "start", "inputFields": [{"key": "text"}]},
                            },
                            {
                                "id": AGENT_NODE,
                                "type": "agent",
                                "data": {"label": "Support Agent"},
                            },
                        ],
                        edges=[{"id": "e1", "source": "start", "target": AGENT_NODE}],
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    trace(self.run_trace_ids[0], 2, 3000.0),
                    trace(self.run_trace_ids[1], 1, 3000.0),
                    trace(uuid.uuid4(), 30, 1000.0),
                ]
            )
            await session.commit()
        self.owner = SimpleNamespace(id=self.owner_id)
        self.tools = self._tools(self.owner)

    async def asyncTearDown(self) -> None:
        user_ids = [self.owner_id, self.outsider_id]
        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await session.execute(delete(Credential).where(Credential.owner_id.in_(user_ids)))
            await session.execute(delete(User).where(User.id.in_(user_ids)))
            await session.commit()
        await engine.dispose()

    def _tools(self, user: Any, cancel_event: Event | None = None) -> chat_evals.ChatEvalTools:
        tools = chat_evals.ChatEvalTools(
            user=user, public_base_url=BASE_URL + "/", cancel_event=cancel_event
        )
        tools.poll_seconds = 0.01
        return tools

    async def _ok(self, name: str, args: dict, tools: Any = None) -> dict:
        outcome = await (tools or self.tools).call(name, args)
        self.assertEqual(outcome.status, "success", outcome.result)
        return json.loads(outcome.result)

    async def _error(self, name: str, args: dict, tools: Any = None) -> str:
        outcome = await (tools or self.tools).call(name, args)
        self.assertEqual(outcome.status, "error", outcome.result)
        return json.loads(outcome.result)["error"]

    def _execution_result(self, trace_id: uuid.UUID) -> str:
        return json.dumps(
            {
                "status": "success",
                "execution_history_id": str(uuid.uuid4()),
                "node_results": [
                    {"node_id": AGENT_NODE, "metadata": {"trace_id": str(trace_id)}},
                ],
            }
        )

    async def _prompt_suite(self, cases: int = 2) -> dict:
        return await self._ok(
            "save_prompt_suite",
            {
                "name": "Math",
                "test_cases": [
                    {"input": f"{i}+{i}", "expected_output": str(2 * i)}
                    for i in range(1, cases + 1)
                ],
            },
        )

    async def _agent_suite(self) -> dict:
        return await self._ok(
            "save_agent_suite",
            {
                "name": "Support checks",
                "workflow_id": str(self.workflow_id),
                "node_id": AGENT_NODE,
                "tool_assertions": [{"kind": "tool", "name": "search", "expect": "called"}],
            },
        )

    async def _completes(self, *, run_id: uuid.UUID, **_kwargs: Any) -> None:
        async with async_session_maker() as session:
            run = await session.get(EvalRun, run_id)
            run.status = "completed"
            await session.commit()

    async def test_a_prompt_suite_is_created_listed_and_read(self) -> None:
        saved = await self._ok(
            "save_prompt_suite",
            {
                "name": "Support replies",
                "system_prompt": "Answer in one sentence.",
                "scoring_method": "contains",
                "test_cases": [
                    {"input": "Where is my order?", "expected_output": "tracking"},
                    {"input": "Can I return it?", "expected_output": "30 days"},
                ],
            },
        )
        suite_id = saved["suite"]["id"]
        self.assertEqual(saved["url"], f"{BASE_URL}/evals?suite={suite_id}")
        self.assertEqual(
            [case["input"] for case in saved["suite"]["test_cases"]],
            ["Where is my order?", "Can I return it?"],
        )
        listed = await self._ok("list_eval_suites", {})
        self.assertIn(
            {
                "id": suite_id,
                "name": "Support replies",
                "suite_type": "prompt",
                "url": saved["url"],
            },
            listed["suites"],
        )
        read = await self._ok("get_eval_suite", {"suite_id": suite_id})
        self.assertEqual(read["suite"]["scoring_method"], "contains")
        self.assertEqual(read["latest_runs"], [])

    async def test_an_edit_changes_adds_and_removes_cases_together(self) -> None:
        saved = await self._prompt_suite()
        first, second = saved["suite"]["test_cases"]
        edited = await self._ok(
            "save_prompt_suite",
            {
                "suite_id": saved["suite"]["id"],
                "name": "Math v2",
                "test_cases": [
                    {"id": first["id"], "expected_output": "two"},
                    {"input": "3+3", "expected_output": "6"},
                ],
                "delete_test_case_ids": [second["id"]],
            },
        )
        self.assertEqual(edited["suite"]["name"], "Math v2")
        self.assertEqual(
            [(c["input"], c["expected_output"]) for c in edited["suite"]["test_cases"]],
            [("1+1", "two"), ("3+3", "6")],
        )

    async def test_a_refused_edit_changes_nothing(self) -> None:
        saved = await self._prompt_suite(cases=1)
        suite_id = saved["suite"]["id"]
        error = await self._error(
            "save_prompt_suite",
            {"suite_id": suite_id, "name": "Renamed", "delete_test_case_ids": [str(uuid.uuid4())]},
        )
        self.assertIn("Not a test case of this suite", error)
        error = await self._error(
            "save_prompt_suite", {"suite_id": suite_id, "scoring_method": "regex"}
        )
        self.assertIn("Scoring method must be one of", error)
        error = await self._error(
            "save_prompt_suite",
            {"name": "New", "test_cases": [{"id": saved["suite"]["test_cases"][0]["id"]}]},
        )
        self.assertIn("A new suite has no test cases", error)
        read = await self._ok("get_eval_suite", {"suite_id": suite_id})
        self.assertEqual(read["suite"]["name"], "Math")
        self.assertEqual(len(read["suite"]["test_cases"]), 1)

    async def test_a_prompt_run_waits_for_its_result(self) -> None:
        saved = await self._prompt_suite()

        async def finish(*, run_id: uuid.UUID, **_kwargs: Any) -> None:
            async with async_session_maker() as session:
                run = await session.get(EvalRun, run_id)
                session.add_all(
                    [
                        EvalRunResult(
                            run_id=run_id,
                            model_id="gpt-4o",
                            input_snapshot="1+1",
                            expected_output_snapshot="2",
                            actual_output="2",
                            score="pass",
                            latency_ms=120,
                            tokens_used=30,
                            run_order=0,
                        ),
                        EvalRunResult(
                            run_id=run_id,
                            model_id="gpt-4o",
                            input_snapshot="2+2",
                            expected_output_snapshot="4",
                            actual_output="5",
                            score="fail",
                            latency_ms=80,
                            tokens_used=20,
                            run_order=1,
                        ),
                    ]
                )
                run.status = "completed"
                await session.commit()

        with patch.object(
            eval_service, "execute_evals_for_run", AsyncMock(side_effect=finish)
        ) as execute:
            result = await self._ok(
                "run_eval_suite",
                {
                    "suite_id": saved["suite"]["id"],
                    "credential_id": str(self.credential_id),
                    "models": ["gpt-4o"],
                },
            )
        self.assertEqual(execute.await_args.kwargs["scoring_method"], "exact_match")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["models"],
            [
                {
                    "model": "gpt-4o",
                    "passed": 1,
                    "total": 2,
                    "avg_latency_ms": 100,
                    "avg_tokens": 25,
                }
            ],
        )
        self.assertEqual([failure["actual"] for failure in result["failures"]], ["5"])
        self.assertEqual(result["url"], f"{BASE_URL}/evals?suite={saved['suite']['id']}")
        outsider = self._tools(SimpleNamespace(id=self.outsider_id))
        error = await self._error("get_eval_run", {"run_id": result["run_id"]}, outsider)
        self.assertEqual(error, "Run not found")

    async def test_a_run_on_another_users_credential_is_refused(self) -> None:
        saved = await self._prompt_suite()
        error = await self._error(
            "run_eval_suite",
            {
                "suite_id": saved["suite"]["id"],
                "credential_id": str(self.outsider_credential_id),
                "models": ["gpt-4o"],
            },
        )
        self.assertEqual(error, "Credential not found")

    async def test_a_long_run_returns_running_and_can_be_checked_later(self) -> None:
        saved = await self._prompt_suite()
        release = asyncio.Event()

        async def slow(**kwargs: Any) -> None:
            await release.wait()
            await self._completes(**kwargs)

        self.tools.run_wait_seconds = 0.05
        args = {
            "suite_id": saved["suite"]["id"],
            "credential_id": str(self.credential_id),
            "models": ["gpt-4o"],
        }
        with patch.object(eval_service, "execute_evals_for_run", AsyncMock(side_effect=slow)):
            started = await self._ok("run_eval_suite", args)
            self.assertEqual(started["status"], "running")
            self.assertTrue(started["url"].startswith(BASE_URL))
            release.set()
            finished = await self._ok(
                "get_eval_run", {"run_id": started["run_id"], "wait_seconds": 5}
            )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["models"], [{"model": "gpt-4o", "passed": 0, "total": 0}])

    async def test_a_cancelled_turn_stops_waiting(self) -> None:
        saved = await self._prompt_suite()
        cancel = Event()
        cancel.set()
        cancelled_tools = self._tools(self.owner, cancel)
        release = asyncio.Event()

        async def slow(**kwargs: Any) -> None:
            await release.wait()
            await self._completes(**kwargs)

        args = {
            "suite_id": saved["suite"]["id"],
            "credential_id": str(self.credential_id),
            "models": ["gpt-4o"],
        }
        with patch.object(eval_service, "execute_evals_for_run", AsyncMock(side_effect=slow)):
            started = await self._ok("run_eval_suite", args, cancelled_tools)
            self.assertEqual(started["status"], "running")
            release.set()
            # The run keeps going without the turn; let it finish before teardown.
            finished = await self._ok(
                "get_eval_run", {"run_id": started["run_id"], "wait_seconds": 5}
            )
        self.assertEqual(finished["status"], "completed")

    async def test_an_agent_baseline_from_a_chat_run(self) -> None:
        created = await self._agent_suite()
        suite_id = created["suite"]["id"]
        self.assertEqual(created["baseline"]["source"], "latest_runs")
        self.assertEqual(created["baseline"]["run_count"], 3)
        self.assertEqual(created["input_fields"], ["text"])

        executor = AsyncMock(side_effect=[self._execution_result(t) for t in self.run_trace_ids])
        inputs = [{"text": "Where is my order?"}, {"text": "Cancel my plan"}]
        with patch("app.api.agent_suite_runs.run_execute_workflow_tool", executor):
            run = await self._ok("run_eval_suite", {"suite_id": suite_id, "inputs": inputs})
        self.assertEqual([call.args[3] for call in executor.await_args_list], inputs)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["execution_statuses"], {"success": 2})
        self.assertEqual((run["report"]["run_count"], run["report"]["passed_count"]), (2, 2))

        rebased = await self._ok(
            "save_agent_suite",
            {"suite_id": suite_id, "baseline": {"source": "suite_run", "run_id": run["run_id"]}},
        )
        self.assertEqual(rebased["baseline"]["source"], "suite_run")
        self.assertEqual(rebased["baseline"]["run_count"], 2)
        self.assertEqual(rebased["baseline"]["latency_p95_ms"], 3000)
        self.assertEqual(rebased["suggested_thresholds"]["latency_ms"], 3600)

    async def test_a_manual_baseline_and_the_baseline_report(self) -> None:
        created = await self._agent_suite()
        suite_id = created["suite"]["id"]
        manual = await self._ok(
            "save_agent_suite",
            {
                "suite_id": suite_id,
                "baseline": {
                    "source": "manual",
                    "values": {"latency_p95_ms": 2500, "cost_avg_usd": 0.01},
                },
            },
        )
        baseline = manual["baseline"]
        self.assertEqual(
            (baseline["source"], baseline["latency_p95_ms"], baseline["cost_avg_usd"]),
            ("manual", 2500, 0.01),
        )
        report = await self._ok(
            "get_agent_baseline", {"workflow_id": str(self.workflow_id), "node_id": AGENT_NODE}
        )
        self.assertEqual(report["run_count"], 3)
        self.assertEqual(report["suggested_thresholds"]["tool_calls"], 1)
        agents = await self._ok("list_eval_agents", {})
        self.assertEqual(
            [(agent["node_id"], agent["run_count"]) for agent in agents["agents"]],
            [(AGENT_NODE, 3)],
        )
        error = await self._error(
            "save_agent_suite",
            {"suite_id": suite_id, "baseline": {"source": "manual", "values": {}}},
        )
        self.assertIn("at least one baseline value", error)

    async def test_an_agent_run_needs_inputs(self) -> None:
        created = await self._agent_suite()
        error = await self._error("run_eval_suite", {"suite_id": created["suite"]["id"]})
        self.assertIn("one input object per run", error)

    async def test_models_are_listed_for_reachable_credentials_only(self) -> None:
        listed = AsyncMock(return_value=[LLMModel(id="gpt-4o", name="GPT-4o")])
        with patch.object(chat_evals, "list_credential_models", listed):
            models = await self._ok("list_llm_models", {"credential_id": str(self.credential_id)})
            error = await self._error(
                "list_llm_models", {"credential_id": str(self.outsider_credential_id)}
            )
        self.assertEqual(models["models"], ["gpt-4o"])
        self.assertEqual(error, "Credential not found")

    async def test_another_user_reaches_nothing(self) -> None:
        prompt = await self._prompt_suite()
        agent = await self._agent_suite()
        outsider = self._tools(SimpleNamespace(id=self.outsider_id))
        calls = (
            ("get_eval_suite", {"suite_id": prompt["suite"]["id"]}),
            ("save_prompt_suite", {"suite_id": prompt["suite"]["id"], "name": "mine"}),
            ("run_eval_suite", {"suite_id": agent["suite"]["id"], "inputs": [{"text": "x"}]}),
            ("save_agent_suite", {"suite_id": agent["suite"]["id"], "name": "mine"}),
            (
                "get_agent_baseline",
                {"workflow_id": str(self.workflow_id), "node_id": AGENT_NODE},
            ),
        )
        for name, args in calls:
            with self.subTest(tool=name):
                error = await self._error(name, args, outsider)
                self.assertIn("not found", error)
        listed = await self._ok("list_eval_suites", {}, outsider)
        self.assertEqual(listed["count"], 0)

    async def test_a_saved_suite_announces_its_link_like_a_saved_workflow(self) -> None:
        outcome = await self.tools.call("save_prompt_suite", {"name": "Math"})
        suite_id = json.loads(outcome.result)["suite"]["id"]
        self.assertEqual(
            outcome.events,
            [
                {
                    "type": "eval_suite_saved",
                    "suite_id": suite_id,
                    "suite_name": "Math",
                    "suite_type": "prompt",
                    "suite_url": f"/evals?suite={suite_id}",
                }
            ],
        )
        agent = await self.tools.call(
            "save_agent_suite",
            {"name": "Checks", "workflow_id": str(self.workflow_id), "node_id": AGENT_NODE},
        )
        self.assertEqual(agent.events[0]["suite_type"], "agent")
        listed = await self.tools.call("list_eval_suites", {})
        self.assertEqual(listed.events, [])

    def test_display_args_count_long_lists(self) -> None:
        shown = self.tools.display_args(
            "save_prompt_suite", {"name": "x", "test_cases": [{}, {}], "system_prompt": "p" * 500}
        )
        self.assertEqual(shown["test_cases"], 2)
        self.assertLessEqual(len(shown["system_prompt"]), 200)


if __name__ == "__main__":
    unittest.main()
