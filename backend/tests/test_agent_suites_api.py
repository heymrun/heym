"""Real-PostgreSQL coverage for the Agent Suite endpoints.

The metrics come from ``llm_traces``, so these tests write real trace rows and check
that the endpoints read only the caller's own runs of the chosen agent node, leave out
the auxiliary rows an agent writes, and refuse workflows and suites the caller cannot
reach. Requires a reachable PostgreSQL instance with migrations applied.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import delete

from app.api.agent_suites import (
    create_agent_suite,
    delete_agent_suite,
    get_agent_metrics,
    get_agent_suite,
    get_agent_suite_report,
    list_agents,
    update_agent_suite,
)
from app.api.evals import list_suites
from app.db.models import EvalSuite, LLMPricingOverride, LLMTrace, User, Workflow
from app.db.session import async_session_maker, engine
from app.models.agent_suite_schemas import (
    AgentSuiteCreate,
    AgentSuiteUpdate,
    AgentThresholdsModel,
    ToolAssertion,
)

MODEL = "agent-suite-test-model"
AGENT_NODE = "agent-1"


def _tool_response(*calls: tuple[str, float]) -> dict:
    return {
        "text": "done",
        "tool_calls": [
            {"name": name, "status": "success", "elapsed_ms": elapsed} for name, elapsed in calls
        ],
        "tool_metrics": {
            "count": len(calls),
            "total_duration_ms": sum(elapsed for _name, elapsed in calls),
        },
    }


class RealPostgresAgentSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        self.owner_id = uuid.uuid4()
        self.outsider_id = uuid.uuid4()
        self.workflow_id = uuid.uuid4()
        self.draft_workflow_id = uuid.uuid4()
        self.plain_workflow_id = uuid.uuid4()
        self.odd_workflow_id = uuid.uuid4()
        self.owner = SimpleNamespace(id=self.owner_id)
        self.outsider = SimpleNamespace(id=self.outsider_id)
        now = datetime.now(timezone.utc)

        def trace(user_id: uuid.UUID, minutes_ago: int, **kwargs: object) -> LLMTrace:
            values: dict = {
                "user_id": user_id,
                "workflow_id": self.workflow_id,
                "node_id": AGENT_NODE,
                "node_label": "Support Agent",
                "source": "workflow",
                "request_type": "chat.completions",
                "model": MODEL,
                "request": {},
                "response": {"text": "done"},
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
                "elapsed_ms": 1000.0,
                "created_at": now - timedelta(minutes=minutes_ago),
            }
            values.update(kwargs)
            return LLMTrace(**values)

        async with async_session_maker() as session:
            session.add_all(
                [
                    User(
                        id=user_id,
                        email=f"agent_suite_{user_id.hex[:8]}@example.com",
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
                            "data": {"label": "Support Agent", "tools": [{"name": "search"}]},
                        },
                        {"id": "llm-1", "type": "llm", "data": {"label": "Summarize"}},
                    ],
                    edges=[],
                )
            )
            session.add_all(
                [
                    Workflow(
                        id=self.draft_workflow_id,
                        name="Draft flow",
                        owner_id=self.owner_id,
                        nodes=[{"id": "agent-2", "type": "agent", "data": {}}],
                        edges=[],
                    ),
                    Workflow(
                        id=self.plain_workflow_id,
                        name="Plain flow",
                        owner_id=self.owner_id,
                        nodes=[{"id": "llm-2", "type": "llm", "data": {}}],
                        edges=[],
                    ),
                    # Nodes stored as an object rather than a list must not break the query.
                    Workflow(
                        id=self.odd_workflow_id,
                        name="Odd flow",
                        owner_id=self.owner_id,
                        nodes={},
                        edges=[],
                    ),
                ]
            )
            session.add(
                LLMPricingOverride(
                    user_id=self.owner_id,
                    model=MODEL,
                    input_per_1m_usd=Decimal("1"),
                    output_per_1m_usd=Decimal("2"),
                )
            )
            session.add(EvalSuite(owner_id=self.owner_id, name="Prompt suite"))
            await session.flush()
            session.add_all(
                [
                    trace(self.owner_id, 10, response=_tool_response(("search", 200.0))),
                    trace(
                        self.owner_id,
                        5,
                        elapsed_ms=2000.0,
                        response=_tool_response(("search", 100.0), ("send_email", 200.0)),
                    ),
                    trace(self.owner_id, 1, request_type="context.compression"),
                    trace(self.owner_id, 1, node_id="llm-1"),
                    trace(self.outsider_id, 1, response=_tool_response(("delete_all", 1.0))),
                ]
            )
            await session.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as session:
            await session.execute(
                delete(Workflow).where(
                    Workflow.id.in_(
                        [
                            self.workflow_id,
                            self.draft_workflow_id,
                            self.plain_workflow_id,
                            self.odd_workflow_id,
                        ]
                    )
                )
            )
            await session.execute(
                delete(User).where(User.id.in_([self.owner_id, self.outsider_id]))
            )
            await session.commit()
        await engine.dispose()

    async def _create_suite(self) -> uuid.UUID:
        async with async_session_maker() as session:
            suite = await create_agent_suite(
                AgentSuiteCreate(
                    name="Support checks",
                    workflow_id=self.workflow_id,
                    node_id=AGENT_NODE,
                    tool_assertions=[
                        ToolAssertion(name="search", expect="called"),
                        ToolAssertion(name="send_email", expect="not_called"),
                    ],
                    thresholds=AgentThresholdsModel(latency_ms=2500),
                ),
                self.owner,
                session,
            )
        return suite.id

    async def test_metrics_read_only_the_callers_runs_of_that_agent(self) -> None:
        async with async_session_maker() as session:
            metrics = await get_agent_metrics(self.workflow_id, AGENT_NODE, 10, self.owner, session)
        self.assertEqual(metrics.node_label, "Support Agent")
        self.assertEqual(metrics.workflow_name, "Support flow")
        self.assertEqual(len(metrics.runs), 2)
        newest, oldest = metrics.runs
        self.assertEqual([c.name for c in newest.tool_calls], ["search", "send_email"])
        self.assertEqual((newest.model_ms, newest.tool_ms, newest.latency_ms), (2000, 300, 2300))
        self.assertEqual(oldest.latency_ms, 1200)
        # 1000 input tokens at $1/1M plus 500 output tokens at $2/1M.
        self.assertAlmostEqual(newest.cost_usd or 0, 0.002)
        self.assertEqual(metrics.baseline.run_count, 2)
        self.assertEqual(metrics.baseline.tool_calls_max, 2)
        usage = {tool.name: (tool.runs_called, tool.configured) for tool in metrics.tools}
        self.assertEqual(usage, {"search": (2, True), "send_email": (1, False)})
        self.assertEqual(metrics.suggested_thresholds.tool_calls, 2)
        self.assertEqual(metrics.suggested_thresholds.latency_ms, 2800)

    async def test_agents_lists_agent_nodes_with_the_callers_run_counts(self) -> None:
        async with async_session_maker() as session:
            agents = await list_agents(self.owner, session)
            outsider_agents = await list_agents(self.outsider, session)
        listed = [(a.workflow_name, a.node_id, a.node_label, a.run_count) for a in agents]
        # The run agent comes first; the outsider's trace on it is not counted.
        self.assertEqual(
            listed,
            [
                ("Support flow", AGENT_NODE, "Support Agent", 2),
                ("Draft flow", "agent-2", "agent-2", 0),
            ],
        )
        self.assertIsNotNone(agents[0].last_run_at)
        self.assertIsNone(agents[1].last_run_at)
        self.assertEqual(outsider_agents, [])

    async def test_limit_takes_the_newest_runs(self) -> None:
        async with async_session_maker() as session:
            metrics = await get_agent_metrics(self.workflow_id, AGENT_NODE, 1, self.owner, session)
        self.assertEqual(len(metrics.runs), 1)
        self.assertEqual(metrics.runs[0].tool_count, 2)

    async def test_metrics_refuse_a_workflow_the_caller_cannot_reach(self) -> None:
        async with async_session_maker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await get_agent_metrics(self.workflow_id, AGENT_NODE, 10, self.outsider, session)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_metrics_refuse_a_node_that_is_not_an_agent(self) -> None:
        async with async_session_maker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await get_agent_metrics(self.workflow_id, "llm-1", 10, self.owner, session)
        self.assertEqual(ctx.exception.detail, "Agent node not found")

    async def test_create_snapshots_the_baseline_and_lists_with_its_type(self) -> None:
        suite_id = await self._create_suite()
        async with async_session_maker() as session:
            suite = await get_agent_suite(suite_id, self.owner, session)
            listed = await list_suites(self.owner, session)
        self.assertEqual(suite.baseline.run_count, 2)
        self.assertIsNotNone(suite.baseline.captured_at)
        self.assertEqual(suite.node_label, "Support Agent")
        types = {item.name: item.suite_type for item in listed}
        self.assertEqual(types, {"Support checks": "agent", "Prompt suite": "prompt"})

    async def test_report_scores_each_run(self) -> None:
        suite_id = await self._create_suite()
        async with async_session_maker() as session:
            report = await get_agent_suite_report(suite_id, 10, None, self.owner, session)
        self.assertEqual((report.run_count, report.passed_count, report.pass_rate), (2, 1, 50.0))
        newest, oldest = report.runs
        self.assertFalse(newest.passed)
        failed = [check.key for check in newest.checks if check.status == "fail"]
        self.assertEqual(failed, ["tool:tool:send_email"])
        self.assertTrue(oldest.passed)
        summary = {check.key: (check.passed, check.failed) for check in report.checks}
        self.assertEqual(summary["tool:tool:search"], (2, 0))
        self.assertEqual(summary["latency_ms"], (2, 0))
        deltas = {delta.metric: delta.delta_pct for delta in report.deltas}
        self.assertEqual(deltas["latency_p95_ms"], 0.0)

    async def test_update_replaces_checks_and_refreshes_the_baseline(self) -> None:
        suite_id = await self._create_suite()
        async with async_session_maker() as session:
            updated = await update_agent_suite(
                suite_id,
                AgentSuiteUpdate(
                    tool_assertions=[
                        ToolAssertion(name="send_email", expect="called"),
                        ToolAssertion(name="send_email", expect="not_called"),
                    ],
                    thresholds=AgentThresholdsModel(),
                    refresh_baseline=True,
                ),
                self.owner,
                session,
            )
        self.assertEqual(
            [(a.name, a.expect) for a in updated.tool_assertions], [("send_email", "not_called")]
        )
        self.assertIsNone(updated.thresholds.latency_ms)
        self.assertEqual(updated.baseline.run_count, 2)

    async def test_another_user_cannot_reach_the_suite(self) -> None:
        suite_id = await self._create_suite()
        async with async_session_maker() as session:
            for call in (
                get_agent_suite(suite_id, self.outsider, session),
                get_agent_suite_report(suite_id, 10, None, self.outsider, session),
                update_agent_suite(suite_id, AgentSuiteUpdate(name="x"), self.outsider, session),
                delete_agent_suite(suite_id, self.outsider, session),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await call
                self.assertEqual(ctx.exception.status_code, 404)
            listed = await list_suites(self.outsider, session)
        self.assertEqual(listed, [])


if __name__ == "__main__":
    unittest.main()
