"""Agent suite runs: the inputs they start from, and scoring exactly the runs they started.

The PostgreSQL tests stub the workflow execution itself and check what the suite does
around it: which inputs each run gets, which agent traces it records, and that the
report for a run reads only those traces.
"""

import asyncio
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import delete

from app.api.agent_suite_runs import (
    cancel_agent_suite_run,
    delete_agent_suite_run,
    execute_agent_suite_run,
    get_agent_suite_run,
    get_latest_agent_suite_run,
    get_run_inputs,
    list_agent_suite_runs,
    start_agent_suite_run,
)
from app.api.agent_suites import get_agent_suite_report
from app.db.models import AgentSuite, AgentSuiteRun, ExecutionHistory, LLMTrace, User, Workflow
from app.db.session import async_session_maker, engine
from app.models.agent_suite_schemas import AgentSuiteRunCreate
from app.services.agent_suite_inputs import (
    agent_trace_ids,
    build_generation_prompt,
    parse_generated_inputs,
    unwrap_run_inputs,
)
from app.services.agent_suite_service import INTERRUPTED_ERROR

AGENT_NODE = "agent-1"


class InputParsingTests(unittest.TestCase):
    def test_unwrap_reads_the_body_of_a_webhook_style_run(self) -> None:
        self.assertEqual(
            unwrap_run_inputs({"headers": {"a": 1}, "query": {}, "body": {"text": "hi"}}),
            {"text": "hi"},
        )
        self.assertEqual(unwrap_run_inputs({"text": "hi", "headers": {}}), {"text": "hi"})
        self.assertEqual(unwrap_run_inputs(None), {})

    def test_generated_inputs_keep_only_the_workflow_fields(self) -> None:
        text = 'Sure: {"inputs": [{"text": "a", "extra": 1}, {"lang": "de"}, "bad"]}'
        parsed = parse_generated_inputs(text, ["text", "lang"], {"lang": "en"}, 3)
        self.assertEqual(
            parsed,
            [
                {"text": "a", "lang": "en"},
                {"text": "", "lang": "de"},
                {"text": "a", "lang": "en"},
            ],
        )

    def test_no_usable_inputs_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_generated_inputs("no json here", ["text"], {}, 2)
        with self.assertRaises(ValueError):
            parse_generated_inputs('{"inputs": []}', ["text"], {}, 2)

    def test_generation_prompt_carries_the_agent_and_the_example(self) -> None:
        prompt = build_generation_prompt(
            workflow_name="Weather",
            fields=["city"],
            example={"city": "Frankfurt"},
            count=3,
            agent_label="Forecaster",
            agent_instructions="Report the weather for the given city.",
            agent_message="$input.city",
        )
        self.assertIn("Report the weather for the given city.", prompt)
        self.assertIn('{"city": "Frankfurt"}', prompt)
        self.assertIn("$input.city", prompt)
        self.assertIn("'Forecaster'", prompt)
        self.assertIn("exactly these keys: city", prompt)

    def test_generation_prompt_without_instructions_still_names_the_example(self) -> None:
        prompt = build_generation_prompt(
            workflow_name="Weather", fields=[], example={"city": "Paris"}, count=2
        )
        self.assertNotIn("system instructions", prompt)
        self.assertIn('{"city": "Paris"}', prompt)

    def test_agent_trace_ids_read_the_agent_node_only(self) -> None:
        node_results = [
            {"node_id": "start", "metadata": {"trace_id": "x"}},
            {"node_id": AGENT_NODE, "metadata": {"trace_id": "t1"}},
            {"node_id": AGENT_NODE, "metadata": {}},
            {"node_id": AGENT_NODE, "metadata": {"trace_id": "t2"}},
        ]
        self.assertEqual(agent_trace_ids(node_results, AGENT_NODE), ["t1", "t2"])
        self.assertEqual(agent_trace_ids(None, AGENT_NODE), [])


class _AgentSuiteRunFixture(unittest.IsolatedAsyncioTestCase):
    """A suite on a workflow with traces, shared by the PostgreSQL test classes below."""

    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.suite_id = uuid.uuid4()
        self.run_trace_ids = [uuid.uuid4(), uuid.uuid4()]
        self.other_trace_id = uuid.uuid4()
        self.owner = SimpleNamespace(id=self.owner_id)
        self.outsider = SimpleNamespace(id=self.outsider_id)
        now = datetime.now(timezone.utc)

        def trace(trace_id: uuid.UUID, minutes_ago: int, tools: list[str]) -> LLMTrace:
            return LLMTrace(
                id=trace_id,
                user_id=self.owner_id,
                workflow_id=self.workflow_id,
                node_id=AGENT_NODE,
                source="workflow",
                request_type="chat.completions",
                model="agent-suite-run-test-model",
                request={},
                response={
                    "tool_calls": [{"name": name, "status": "success"} for name in tools],
                    "tool_metrics": {"count": len(tools), "total_duration_ms": 0},
                },
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                elapsed_ms=100.0,
                created_at=now - timedelta(minutes=minutes_ago),
            )

        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"agent_suite_run_{user_id.hex[:8]}@example.com",
                        hashed_password="x",
                        name="User",
                    )
                    for user_id in (self.owner_id, self.outsider_id)
                ]
            )
            await session.flush()
            session.add(
                Workflow(
                    id=self.workflow_id,
                    name="Support flow",
                    owner_id=self.owner_id,
                    nodes=[
                        {
                            "id": AGENT_NODE,
                            "type": "agent",
                            "data": {
                                "label": "Support",
                                "systemInstruction": "Answer order questions.",
                                "userMessage": "$input.text",
                            },
                        }
                    ],
                    edges=[],
                )
            )
            await session.flush()
            session.add(
                AgentSuite(
                    id=self.suite_id,
                    owner_id=self.owner_id,
                    name="Support checks",
                    workflow_id=self.workflow_id,
                    node_id=AGENT_NODE,
                    node_label="Support",
                    tool_assertions=[{"kind": "tool", "name": "search", "expect": "called"}],
                    thresholds={},
                    baseline={},
                )
            )
            session.add(
                ExecutionHistory(
                    workflow_id=self.workflow_id,
                    inputs={"headers": {}, "query": {}, "body": {"text": "Where is my order?"}},
                    outputs={},
                    node_results=[],
                    status="success",
                    execution_time_ms=10.0,
                )
            )
            session.add_all(
                [
                    trace(self.run_trace_ids[0], 3, ["search"]),
                    trace(self.run_trace_ids[1], 2, []),
                    # A production run in between; a suite run's report must leave it out.
                    trace(self.other_trace_id, 1, ["search"]),
                ]
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as session:
            await session.execute(delete(Workflow).where(Workflow.id == self.workflow_id))
            await session.execute(
                delete(User).where(User.id.in_([self.owner_id, self.outsider_id]))
            )
            await session.commit()
        await engine.dispose()

    def _execution_result(self, trace_id: uuid.UUID) -> str:
        return json.dumps(
            {
                "status": "success",
                "execution_history_id": str(uuid.uuid4()),
                "node_results": [
                    {"node_id": "start", "metadata": {}},
                    {"node_id": AGENT_NODE, "metadata": {"trace_id": str(trace_id)}},
                ],
            }
        )

    async def _start(self, body: AgentSuiteRunCreate) -> uuid.UUID:
        tasks = SimpleNamespace(add_task=lambda *args, **kwargs: None)
        request = SimpleNamespace(headers={}, base_url="http://test/")
        async with async_session_maker() as session:
            with patch(
                "app.api.agent_suite_runs.build_public_base_url", return_value="http://test"
            ):
                started = await start_agent_suite_run(
                    self.suite_id, body, request, tasks, self.owner, session
                )
        return started.id


class RealPostgresAgentSuiteRunTests(_AgentSuiteRunFixture):
    async def test_run_inputs_come_from_the_previous_run(self) -> None:
        async with async_session_maker() as session:
            inputs = await get_run_inputs(self.suite_id, self.owner, session)
        self.assertEqual(inputs.previous_inputs, {"text": "Where is my order?"})
        self.assertIsNotNone(inputs.previous_run_at)

    async def test_a_run_scores_only_the_traces_it_started(self) -> None:
        run_id = await self._start(AgentSuiteRunCreate(count=2, inputs={"text": "hello"}))
        executor = AsyncMock(side_effect=[self._execution_result(t) for t in self.run_trace_ids])
        with patch("app.api.agent_suite_runs.run_execute_workflow_tool", executor):
            await execute_agent_suite_run(run_id, self.owner_id, "http://test", None, None)

        self.assertEqual(executor.await_count, 2)
        first_call = executor.await_args_list[0]
        self.assertEqual(first_call.args[3], {"text": "hello"})
        self.assertEqual(first_call.kwargs["trigger_source"], "agent_suite")
        # Every run is its own OpenCode session.
        sessions = {call.kwargs["llm_session_id"] for call in executor.await_args_list}
        self.assertEqual(len(sessions), 2)

        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(run_id, self.owner, session)
            latest = await get_latest_agent_suite_run(self.suite_id, self.owner, session)
            report = await get_agent_suite_report(self.suite_id, 10, run_id, self.owner, session)
        self.assertEqual(suite_run.status, "completed")
        self.assertEqual(
            sorted(result.trace_ids[0] for result in suite_run.results),
            sorted(str(trace_id) for trace_id in self.run_trace_ids),
        )
        self.assertEqual(latest.id, run_id)
        self.assertEqual(sorted(run.trace_id for run in report.runs), sorted(self.run_trace_ids))
        self.assertEqual((report.run_count, report.passed_count), (2, 1))

    async def test_an_inputs_list_runs_each_input_once(self) -> None:
        run_id = await self._start(
            AgentSuiteRunCreate(inputs_list=[{"text": "one"}, {"text": "two"}])
        )
        executor = AsyncMock(side_effect=[self._execution_result(t) for t in self.run_trace_ids])
        with patch("app.api.agent_suite_runs.run_execute_workflow_tool", executor):
            await execute_agent_suite_run(run_id, self.owner_id, "http://test", None, None)
        self.assertEqual(
            sorted(call.args[3]["text"] for call in executor.await_args_list), ["one", "two"]
        )
        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(run_id, self.owner, session)
        self.assertEqual((suite_run.requested_count, suite_run.status), (2, "completed"))

    async def test_the_route_queues_the_launch_job(self) -> None:
        queued: list[tuple] = []
        tasks = SimpleNamespace(add_task=lambda func, **kwargs: queued.append((func, kwargs)))
        request = SimpleNamespace(headers={}, base_url="http://test/")
        async with async_session_maker() as session:
            with patch(
                "app.api.agent_suite_runs.build_public_base_url", return_value="http://test"
            ):
                started = await start_agent_suite_run(
                    self.suite_id, AgentSuiteRunCreate(count=1), request, tasks, self.owner, session
                )
        self.assertIs(queued[0][0], execute_agent_suite_run)
        self.assertEqual(queued[0][1]["run_id"], started.id)
        self.assertEqual(queued[0][1]["public_base_url"], "http://test")

    async def test_generated_inputs_replace_the_form_values(self) -> None:
        run_id = await self._start(
            AgentSuiteRunCreate(
                count=2,
                inputs={"text": "example"},
                generate_inputs=True,
                credential_id=uuid.uuid4(),
                model="test-model",
            )
        )
        generator = AsyncMock(return_value=[{"text": "one"}, {"text": "two"}])
        executor = AsyncMock(side_effect=[self._execution_result(t) for t in self.run_trace_ids])
        with (
            patch("app.api.agent_suite_runs.generate_run_inputs", generator),
            patch("app.api.agent_suite_runs.run_execute_workflow_tool", executor),
        ):
            await execute_agent_suite_run(
                run_id, self.owner_id, "http://test", uuid.uuid4(), "test-model"
            )
        self.assertEqual(generator.await_args.kwargs["example"], {"text": "example"})
        self.assertEqual(generator.await_args.kwargs["session_id"], str(run_id))
        # The model is told what the agent does, not only shown the example.
        self.assertEqual(
            generator.await_args.kwargs["agent_instructions"], "Answer order questions."
        )
        self.assertEqual(generator.await_args.kwargs["agent_message"], "$input.text")
        self.assertEqual(
            sorted(call.args[3]["text"] for call in executor.await_args_list), ["one", "two"]
        )

    async def test_a_failed_generation_fails_the_run(self) -> None:
        run_id = await self._start(
            AgentSuiteRunCreate(
                count=1, generate_inputs=True, credential_id=uuid.uuid4(), model="m"
            )
        )
        generator = AsyncMock(side_effect=ValueError("The model returned no usable inputs."))
        with patch("app.api.agent_suite_runs.generate_run_inputs", generator):
            await execute_agent_suite_run(run_id, self.owner_id, "http://test", uuid.uuid4(), "m")
        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(run_id, self.owner, session)
        self.assertEqual(suite_run.status, "failed")
        self.assertIn("no usable inputs", suite_run.error or "")

    async def test_a_second_run_waits_for_the_first(self) -> None:
        await self._start(AgentSuiteRunCreate(count=1))
        with self.assertRaises(HTTPException) as ctx:
            await self._start(AgentSuiteRunCreate(count=1))
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_generation_needs_a_credential_and_model(self) -> None:
        with self.assertRaises(ValueError):
            AgentSuiteRunCreate(count=1, generate_inputs=True)

    async def test_another_user_cannot_run_or_read_the_suite(self) -> None:
        run_id = await self._start(AgentSuiteRunCreate(count=1))
        tasks = SimpleNamespace(add_task=lambda *args, **kwargs: None)
        async with async_session_maker() as session:
            for call in (
                get_run_inputs(self.suite_id, self.outsider, session),
                start_agent_suite_run(
                    self.suite_id,
                    AgentSuiteRunCreate(),
                    SimpleNamespace(),
                    tasks,
                    self.outsider,
                    session,
                ),
                get_agent_suite_run(run_id, self.outsider, session),
                get_latest_agent_suite_run(self.suite_id, self.outsider, session),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await call
                self.assertEqual(ctx.exception.status_code, 404)
        # Nothing ran for the outsider, and the owner's run row is untouched.
        async with async_session_maker() as session:
            suite_run = await session.get(AgentSuiteRun, run_id)
        self.assertEqual(suite_run.status, "running")


class RealPostgresAgentSuiteRunControlTests(_AgentSuiteRunFixture):
    """Parallelism, Stop, interrupted runs and the run history."""

    async def test_runs_go_four_at_a_time(self) -> None:
        run_id = await self._start(AgentSuiteRunCreate(count=7, inputs={"text": "hi"}))
        running = 0
        peak = 0

        async def run(*_args: object, **_kwargs: object) -> str:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1
            return self._execution_result(uuid.uuid4())

        with patch(
            "app.api.agent_suite_runs.run_execute_workflow_tool", AsyncMock(side_effect=run)
        ):
            await execute_agent_suite_run(run_id, self.owner_id, "http://test", None, None)
        self.assertEqual(peak, 4)
        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(run_id, self.owner, session)
        self.assertEqual((suite_run.status, len(suite_run.results)), ("completed", 7))

    async def test_stop_cancels_the_runs_in_flight_and_starts_no_more(self) -> None:
        run_id = await self._start(AgentSuiteRunCreate(count=6, inputs={"text": "hi"}))
        seen_events = []

        async def run(*args: object, **_kwargs: object) -> str:
            cancel_event = args[5]
            seen_events.append(cancel_event)
            for _ in range(250):
                if cancel_event.is_set():
                    return json.dumps({"status": "cancelled", "error": "Execution cancelled"})
                await asyncio.sleep(0.02)
            return self._execution_result(uuid.uuid4())

        executor = AsyncMock(side_effect=run)
        with (
            patch("app.api.agent_suite_runs.WATCH_SECONDS", 0.05),
            patch("app.api.agent_suite_runs.run_execute_workflow_tool", executor),
        ):
            runner = asyncio.create_task(
                execute_agent_suite_run(run_id, self.owner_id, "http://test", None, None)
            )
            await asyncio.sleep(0.3)
            async with async_session_maker() as session:
                stopped = await cancel_agent_suite_run(run_id, self.owner, session)
            self.assertEqual(stopped.status, "cancelled")
            await asyncio.wait_for(runner, timeout=5)

        self.assertEqual(executor.await_count, 4)
        self.assertTrue(all(event.is_set() for event in seen_events))
        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(run_id, self.owner, session)
        self.assertEqual(suite_run.status, "cancelled")
        self.assertEqual({result.status for result in suite_run.results}, {"cancelled"})

    async def test_a_run_whose_heartbeat_went_quiet_is_closed_as_interrupted(self) -> None:
        stale_id = uuid.uuid4()
        async with async_session_maker() as session:
            session.add(
                AgentSuiteRun(
                    id=stale_id,
                    suite_id=self.suite_id,
                    status="running",
                    requested_count=3,
                    generate_inputs=False,
                    inputs=[],
                    results=[],
                    heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                )
            )
            await session.commit()
        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(stale_id, self.owner, session)
        self.assertEqual((suite_run.status, suite_run.error), ("failed", INTERRUPTED_ERROR))
        # It no longer blocks a new run of the suite.
        self.assertIsNotNone(await self._start(AgentSuiteRunCreate(count=1)))

    async def test_a_live_heartbeat_keeps_the_run_running(self) -> None:
        run_id = await self._start(AgentSuiteRunCreate(count=1))
        async with async_session_maker() as session:
            row = await session.get(AgentSuiteRun, run_id)
            row.heartbeat_at = datetime.now(timezone.utc)
            await session.commit()
        async with async_session_maker() as session:
            suite_run = await get_agent_suite_run(run_id, self.owner, session)
        self.assertEqual(suite_run.status, "running")

    async def test_runs_are_listed_newest_first_and_deleted_once_stopped(self) -> None:
        first = await self._start(AgentSuiteRunCreate(count=2))
        async with async_session_maker() as session:
            await cancel_agent_suite_run(first, self.owner, session)
        second = await self._start(AgentSuiteRunCreate(count=1))
        async with async_session_maker() as session:
            listed = await list_agent_suite_runs(self.suite_id, self.owner, session)
            with self.assertRaises(HTTPException) as busy:
                await delete_agent_suite_run(second, self.owner, session)
        self.assertEqual([item.id for item in listed], [second, first])
        self.assertEqual([item.status for item in listed], ["running", "cancelled"])
        self.assertEqual(busy.exception.status_code, 409)
        async with async_session_maker() as session:
            await delete_agent_suite_run(first, self.owner, session)
            listed = await list_agent_suite_runs(self.suite_id, self.owner, session)
        self.assertEqual([item.id for item in listed], [second])

    async def test_another_user_cannot_list_stop_or_delete_runs(self) -> None:
        run_id = await self._start(AgentSuiteRunCreate(count=1))
        async with async_session_maker() as session:
            for call in (
                list_agent_suite_runs(self.suite_id, self.outsider, session),
                cancel_agent_suite_run(run_id, self.outsider, session),
                delete_agent_suite_run(run_id, self.outsider, session),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await call
                self.assertEqual(ctx.exception.status_code, 404)
        async with async_session_maker() as session:
            suite_run = await session.get(AgentSuiteRun, run_id)
        self.assertEqual(suite_run.status, "running")


if __name__ == "__main__":
    unittest.main()
