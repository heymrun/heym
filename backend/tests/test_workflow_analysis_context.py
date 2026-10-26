import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.ai_assistant import (
    _build_workflow_analysis_context,
    _workflow_has_agent_suite,
    _workflow_has_alert,
)


class BuildWorkflowAnalysisContextTests(unittest.TestCase):
    def test_includes_existing_checks(self) -> None:
        workflow = {
            "nodes": [{"type": "errorHandler"}],
            "error_workflow_id": str(uuid.uuid4()),
            "minutes_saved_per_run": 12.5,
        }
        ctx = _build_workflow_analysis_context(workflow, has_alert_configured=False)
        self.assertTrue(ctx["hasErrorHandler"])
        self.assertTrue(ctx["errorWorkflowConfigured"])
        self.assertEqual(ctx["minutesSavedPerRun"], 12.5)

    def test_flags_alert_configured(self) -> None:
        workflow = {"nodes": [{"type": "cron"}]}
        ctx = _build_workflow_analysis_context(workflow, has_alert_configured=True)
        self.assertTrue(ctx["hasAlertConfigured"])

    def test_lists_agent_and_llm_nodes_for_the_evals_check(self) -> None:
        workflow = {
            "nodes": [
                {"id": "a1", "type": "agent", "data": {"label": "Support Agent"}},
                {"id": "a2", "type": "agent", "data": {}},
                {"id": "l1", "type": "llm", "data": {"label": "Summarize"}},
                {"id": "h1", "type": "httpRequest", "data": {"label": "Fetch"}},
            ]
        }
        ctx = _build_workflow_analysis_context(
            workflow, has_alert_configured=False, has_agent_suite=True
        )
        self.assertEqual(ctx["agentNodes"], ["Support Agent", "a2"])
        self.assertEqual(ctx["llmNodes"], ["Summarize"])
        self.assertTrue(ctx["hasAgentSuite"])

    def test_defaults_when_workflow_none(self) -> None:
        ctx = _build_workflow_analysis_context(None, has_alert_configured=False)
        self.assertFalse(ctx["hasErrorHandler"])
        self.assertFalse(ctx["errorWorkflowConfigured"])
        self.assertIsNone(ctx["minutesSavedPerRun"])
        self.assertFalse(ctx["hasAlertConfigured"])
        self.assertEqual(ctx["agentNodes"], [])
        self.assertEqual(ctx["llmNodes"], [])
        self.assertFalse(ctx["hasAgentSuite"])


class WorkflowHasAlertTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_false_when_no_workflow_id(self) -> None:
        db = AsyncMock()
        user = SimpleNamespace(id=uuid.uuid4())
        self.assertFalse(await _workflow_has_alert(db, user, None))
        db.execute.assert_not_called()

    async def test_returns_true_when_alerts_exist(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=3)))
        user = SimpleNamespace(id=uuid.uuid4())
        self.assertTrue(await _workflow_has_alert(db, user, uuid.uuid4()))

    async def test_returns_false_when_no_alerts(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=0)))
        user = SimpleNamespace(id=uuid.uuid4())
        self.assertFalse(await _workflow_has_alert(db, user, uuid.uuid4()))


class WorkflowHasAgentSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_false_when_no_workflow_id(self) -> None:
        db = AsyncMock()
        self.assertFalse(
            await _workflow_has_agent_suite(db, SimpleNamespace(id=uuid.uuid4()), None)
        )
        db.execute.assert_not_called()

    async def test_counts_the_users_suites_on_the_workflow(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one=MagicMock(return_value=1)))
        user = SimpleNamespace(id=uuid.uuid4())
        self.assertTrue(await _workflow_has_agent_suite(db, user, uuid.uuid4()))
        sql = str(db.execute.await_args.args[0])
        self.assertIn("agent_suites.owner_id", sql)
        self.assertIn("agent_suites.workflow_id", sql)
