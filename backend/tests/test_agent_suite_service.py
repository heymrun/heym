"""Agent suites through the service the Evals routes and the chat tools share.

The baseline can come from the agent's latest runs, from one finished suite run, or from
numbers the user states. Requires a reachable PostgreSQL instance with migrations applied.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy import delete

from app.db.models import AgentSuite, AgentSuiteRun, LLMTrace, User, Workflow
from app.db.session import async_session_maker, engine
from app.models.agent_suite_schemas import (
    AgentBaselineSource,
    AgentBaselineValues,
    AgentSuiteCreate,
    AgentSuiteRunCreate,
    AgentSuiteUpdate,
)
from app.services import agent_suite_service as agent_suites
from app.services.eval_common import EvalNotFoundError

AGENT_NODE = "agent-1"


class AgentBaselineSchemaTests(unittest.TestCase):
    def test_each_source_needs_its_input(self) -> None:
        with self.assertRaises(ValidationError):
            AgentBaselineSource(source="suite_run")
        with self.assertRaises(ValidationError):
            AgentBaselineSource(source="manual")
        with self.assertRaises(ValidationError):
            AgentBaselineValues()
        self.assertEqual(AgentBaselineSource().source, "latest_runs")

    def test_create_refuses_a_suite_run_baseline(self) -> None:
        with self.assertRaises(ValidationError):
            AgentSuiteCreate(
                name="x",
                workflow_id=uuid.uuid4(),
                node_id="a",
                baseline={"source": "suite_run", "run_id": str(uuid.uuid4())},
            )

    def test_update_takes_refresh_or_baseline_not_both(self) -> None:
        with self.assertRaises(ValidationError):
            AgentSuiteUpdate(refresh_baseline=True, baseline={"source": "latest_runs"})

    def test_an_inputs_list_holds_1_to_20_runs_and_excludes_generation(self) -> None:
        with self.assertRaises(ValidationError):
            AgentSuiteRunCreate(
                inputs_list=[{"text": "a"}],
                generate_inputs=True,
                credential_id=uuid.uuid4(),
                model="m",
            )
        with self.assertRaises(ValidationError):
            AgentSuiteRunCreate(inputs_list=[{"text": str(i)} for i in range(21)])
        with self.assertRaises(ValidationError):
            AgentSuiteRunCreate(inputs_list=[])


class RealPostgresAgentSuiteServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.suite_id = uuid.uuid4()
        self.other_suite_id = uuid.uuid4()
        self.finished_run_id = uuid.uuid4()
        self.running_run_id = uuid.uuid4()
        self.empty_run_id = uuid.uuid4()
        self.other_suite_run_id = uuid.uuid4()
        self.suite_run_traces = [uuid.uuid4(), uuid.uuid4()]
        now = datetime.now(timezone.utc)

        def trace(trace_id: uuid.UUID, minutes_ago: int, elapsed_ms: float) -> LLMTrace:
            return LLMTrace(
                id=trace_id,
                user_id=self.owner_id,
                workflow_id=self.workflow_id,
                node_id=AGENT_NODE,
                source="workflow",
                request_type="chat.completions",
                model="agent-suite-service-test-model",
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

        def suite(suite_id: uuid.UUID, name: str) -> AgentSuite:
            return AgentSuite(
                id=suite_id,
                owner_id=self.owner_id,
                name=name,
                workflow_id=self.workflow_id,
                node_id=AGENT_NODE,
                node_label="Support",
                tool_assertions=[],
                thresholds={},
                baseline={},
            )

        def suite_run(
            run_id: uuid.UUID, suite_id: uuid.UUID, status: str, traces: list[uuid.UUID]
        ) -> AgentSuiteRun:
            return AgentSuiteRun(
                id=run_id,
                suite_id=suite_id,
                status=status,
                requested_count=max(1, len(traces)),
                generate_inputs=False,
                inputs=[],
                results=[
                    {
                        "execution_id": None,
                        "status": "success",
                        "trace_ids": [str(t)],
                        "error": None,
                    }
                    for t in traces
                ],
            )

        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"agent_suite_service_{user_id.hex[:8]}@example.com",
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
                    nodes=[{"id": AGENT_NODE, "type": "agent", "data": {"label": "Support"}}],
                    edges=[],
                )
            )
            await session.flush()
            session.add_all(
                [suite(self.suite_id, "Support checks"), suite(self.other_suite_id, "Other")]
            )
            await session.flush()
            session.add_all(
                [
                    suite_run(
                        self.finished_run_id, self.suite_id, "completed", self.suite_run_traces
                    ),
                    suite_run(self.running_run_id, self.suite_id, "running", []),
                    suite_run(self.empty_run_id, self.suite_id, "completed", []),
                    suite_run(
                        self.other_suite_run_id,
                        self.other_suite_id,
                        "completed",
                        self.suite_run_traces,
                    ),
                    trace(self.suite_run_traces[0], 3, 3000.0),
                    trace(self.suite_run_traces[1], 2, 3000.0),
                    trace(uuid.uuid4(), 1, 1000.0),
                    trace(uuid.uuid4(), 1, 1000.0),
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

    async def test_latest_runs_baseline_is_the_default(self) -> None:
        async with async_session_maker() as db:
            response = await agent_suites.create_agent_suite(
                db,
                self.owner_id,
                AgentSuiteCreate(name="New", workflow_id=self.workflow_id, node_id=AGENT_NODE),
            )
        self.assertEqual(response.baseline.source, "latest_runs")
        self.assertIsNone(response.baseline.suite_run_id)
        self.assertEqual(response.baseline.run_count, 4)

    async def test_a_finished_suite_run_becomes_the_baseline(self) -> None:
        source = AgentBaselineSource(source="suite_run", run_id=self.finished_run_id)
        async with async_session_maker() as db:
            response = await agent_suites.update_agent_suite(
                db, self.owner_id, self.suite_id, AgentSuiteUpdate(baseline=source)
            )
        self.assertEqual(response.baseline.source, "suite_run")
        self.assertEqual(response.baseline.suite_run_id, self.finished_run_id)
        self.assertEqual(response.baseline.run_count, 2)
        self.assertEqual(response.baseline.latency_p95_ms, 3000)

    async def test_a_run_that_cannot_be_a_baseline_changes_nothing(self) -> None:
        refusals = {
            self.running_run_id: ValueError,
            self.empty_run_id: ValueError,
            self.other_suite_run_id: EvalNotFoundError,
            uuid.uuid4(): EvalNotFoundError,
        }
        for run_id, error in refusals.items():
            with self.subTest(run_id=run_id):
                async with async_session_maker() as db:
                    with self.assertRaises(error):
                        await agent_suites.update_agent_suite(
                            db,
                            self.owner_id,
                            self.suite_id,
                            AgentSuiteUpdate(
                                name="changed",
                                baseline=AgentBaselineSource(source="suite_run", run_id=run_id),
                            ),
                        )
        async with async_session_maker() as db:
            suite = await agent_suites.get_agent_suite(db, self.owner_id, self.suite_id)
        self.assertEqual(suite.name, "Support checks")

    async def test_manual_values_are_stored_as_given(self) -> None:
        values = AgentBaselineValues(latency_p95_ms=2500, cost_avg_usd=0.01)
        async with async_session_maker() as db:
            response = await agent_suites.update_agent_suite(
                db,
                self.owner_id,
                self.suite_id,
                AgentSuiteUpdate(baseline=AgentBaselineSource(source="manual", values=values)),
            )
            report = await agent_suites.agent_suite_report(
                db, self.owner_id, self.suite_id, 10, None
            )
        baseline = response.baseline
        self.assertEqual(
            (baseline.source, baseline.latency_p95_ms, baseline.cost_avg_usd, baseline.run_count),
            ("manual", 2500, 0.01, 0),
        )
        deltas = {delta.metric: delta.baseline for delta in report.deltas}
        self.assertEqual(deltas["latency_p95_ms"], 2500)

    async def test_an_old_baseline_reads_as_latest_runs(self) -> None:
        async with async_session_maker() as db:
            suite = await agent_suites.get_agent_suite(db, self.owner_id, self.suite_id)
        self.assertEqual(suite.baseline.source, "latest_runs")
        self.assertIsNone(suite.baseline.suite_run_id)

    async def test_run_inputs_and_latest_run(self) -> None:
        async with async_session_maker() as db:
            inputs = await agent_suites.agent_run_inputs(db, self.owner_id, self.suite_id)
            latest = await agent_suites.latest_agent_suite_run(db, self.suite_id)
        self.assertEqual(inputs.fields, [])
        self.assertIsNone(inputs.previous_inputs)
        self.assertIn(latest.id, {self.finished_run_id, self.running_run_id, self.empty_run_id})

    async def test_another_user_reaches_nothing(self) -> None:
        async with async_session_maker() as db:
            for call in (
                agent_suites.get_agent_suite(db, self.outsider_id, self.suite_id),
                agent_suites.update_agent_suite(
                    db, self.outsider_id, self.suite_id, AgentSuiteUpdate(name="x")
                ),
                agent_suites.agent_suite_report(db, self.outsider_id, self.suite_id, 10, None),
                agent_suites.agent_run_inputs(db, self.outsider_id, self.suite_id),
                agent_suites.load_owned_agent_suite_run(db, self.finished_run_id, self.outsider_id),
                agent_suites.agent_metrics(db, self.outsider_id, self.workflow_id, AGENT_NODE, 10),
            ):
                with self.assertRaises(EvalNotFoundError):
                    await call


if __name__ == "__main__":
    unittest.main()
