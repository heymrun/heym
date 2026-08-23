import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.api.folders import _workflow_list_response
from app.api.workflows import get_workflow
from app.db.models import User, Workflow
from app.services.workflow_last_trigger import (
    fetch_last_trigger_source,
    fetch_last_trigger_sources,
)
from app.services.workflow_status import compute_trigger_status, refine_manual_status


def make_workflow(nodes: list[dict]) -> Workflow:
    return Workflow(
        id=uuid.uuid4(),
        name="Workflow",
        description=None,
        owner_id=uuid.uuid4(),
        nodes=nodes,
        edges=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_detail_workflow(owner_id: uuid.UUID) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="wf",
        description=None,
        kind="workflow",
        nodes=[],
        edges=[],
        auth_type="jwt",
        auth_header_key=None,
        auth_header_value=None,
        webhook_body_mode="legacy",
        allow_anonymous=False,
        owner_id=owner_id,
        folder_id=None,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        sse_node_config=None,
        auto_recover_runs=True,
        error_workflow_id=None,
        minutes_saved_per_run=None,
        workflow_timeout_seconds=None,
        portal_enabled=False,
        portal_slug=None,
        created_at=now,
        updated_at=now,
    )


class ComputeTriggerStatusTests(unittest.TestCase):
    def test_no_nodes_is_manual(self) -> None:
        self.assertEqual(compute_trigger_status([]), "manual")
        self.assertEqual(compute_trigger_status(None), "manual")

    def test_only_action_nodes_is_manual(self) -> None:
        nodes = [{"type": "textInput", "data": {}}, {"type": "llm", "data": {}}]
        self.assertEqual(compute_trigger_status(nodes), "manual")

    def test_active_cron_is_scheduled(self) -> None:
        nodes = [{"type": "cron", "data": {"cronExpression": "0 * * * *"}}]
        self.assertEqual(compute_trigger_status(nodes), "scheduled")

    def test_event_trigger_is_listening(self) -> None:
        nodes = [{"type": "slackTrigger", "data": {}}]
        self.assertEqual(compute_trigger_status(nodes), "listening")

    def test_cron_wins_over_event_trigger(self) -> None:
        nodes = [{"type": "slackTrigger", "data": {}}, {"type": "cron", "data": {}}]
        self.assertEqual(compute_trigger_status(nodes), "scheduled")

    def test_all_triggers_deactivated_is_paused(self) -> None:
        nodes = [
            {"type": "cron", "data": {"active": False}},
            {"type": "imapTrigger", "data": {"active": False}},
        ]
        self.assertEqual(compute_trigger_status(nodes), "paused")

    def test_one_active_trigger_among_disabled_is_not_paused(self) -> None:
        nodes = [
            {"type": "cron", "data": {"active": False}},
            {"type": "imapTrigger", "data": {"active": True}},
        ]
        self.assertEqual(compute_trigger_status(nodes), "listening")

    def test_missing_data_dict_counts_as_active(self) -> None:
        self.assertEqual(compute_trigger_status([{"type": "cron"}]), "scheduled")

    def test_non_dict_entries_are_ignored(self) -> None:
        self.assertEqual(compute_trigger_status(["nonsense", None]), "manual")


class RefineManualStatusTests(unittest.TestCase):
    def test_last_api_run_becomes_api(self) -> None:
        self.assertEqual(refine_manual_status("manual", "API"), "api")

    def test_last_sub_workflow_run_becomes_sub_workflow(self) -> None:
        self.assertEqual(refine_manual_status("manual", "SUB_WORKFLOW"), "subWorkflow")

    def test_last_portal_run_becomes_portal(self) -> None:
        self.assertEqual(refine_manual_status("manual", "portal"), "portal")

    def test_surrounding_whitespace_is_ignored(self) -> None:
        self.assertEqual(refine_manual_status("manual", "  api  "), "api")

    def test_never_run_workflow_stays_manual(self) -> None:
        self.assertEqual(refine_manual_status("manual", None), "manual")
        self.assertEqual(refine_manual_status("manual", ""), "manual")

    def test_unknown_trigger_source_stays_manual(self) -> None:
        self.assertEqual(refine_manual_status("manual", "board"), "manual")
        self.assertEqual(refine_manual_status("manual", "AI Agents"), "manual")

    def test_trigger_nodes_win_over_the_last_run(self) -> None:
        """A cron workflow called once over HTTP is still a scheduled workflow."""
        self.assertEqual(refine_manual_status("scheduled", "API"), "scheduled")
        self.assertEqual(refine_manual_status("listening", "SUB_WORKFLOW"), "listening")
        self.assertEqual(refine_manual_status("paused", "portal"), "paused")


class FetchLastTriggerSourcesTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_rows_by_workflow_id(self) -> None:
        first, second = uuid.uuid4(), uuid.uuid4()
        result = Mock()
        result.all.return_value = [
            SimpleNamespace(workflow_id=first, trigger_source="API"),
            SimpleNamespace(workflow_id=second, trigger_source="SUB_WORKFLOW"),
        ]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        sources = await fetch_last_trigger_sources(db, [first, second])

        self.assertEqual(sources, {first: "API", second: "SUB_WORKFLOW"})

    async def test_no_workflow_ids_skips_the_query(self) -> None:
        db = AsyncMock()

        self.assertEqual(await fetch_last_trigger_sources(db, []), {})
        db.execute.assert_not_awaited()

    async def test_single_lookup_returns_none_when_never_run(self) -> None:
        workflow_id = uuid.uuid4()
        result = Mock()
        result.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        self.assertIsNone(await fetch_last_trigger_source(db, workflow_id))


class WorkflowListResponseTriggerStatusTests(unittest.TestCase):
    def test_folder_list_response_carries_trigger_status(self) -> None:
        workflow = make_workflow([{"type": "cron", "data": {}}])

        response = _workflow_list_response(workflow, None, None)

        self.assertEqual(response.trigger_status, "scheduled")

    def test_folder_list_response_refines_manual_with_last_trigger_source(self) -> None:
        workflow = make_workflow([{"type": "llm", "data": {}}])

        self.assertEqual(_workflow_list_response(workflow, None, None, "API").trigger_status, "api")
        self.assertEqual(
            _workflow_list_response(workflow, None, None, "SUB_WORKFLOW").trigger_status,
            "subWorkflow",
        )
        self.assertEqual(
            _workflow_list_response(workflow, None, None, "portal").trigger_status, "portal"
        )
        self.assertEqual(_workflow_list_response(workflow, None, None).trigger_status, "manual")


class WorkflowDetailOwnerNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_sees_own_name(self) -> None:
        current_user = User(id=uuid.uuid4(), email="a@b.c", hashed_password="hashed", name="Anna")
        workflow = make_detail_workflow(current_user.id)

        db = AsyncMock()
        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)):
            response = await get_workflow(workflow.id, current_user, db)

        self.assertEqual(response.owner_name, "Anna")

    async def test_collaborator_sees_owner_name_from_db(self) -> None:
        current_user = User(id=uuid.uuid4(), email="a@b.c", hashed_password="hashed", name="Ben")
        workflow = make_detail_workflow(uuid.uuid4())

        share_result = Mock()
        share_result.scalar_one_or_none.return_value = None
        owner_result = Mock()
        owner_result.scalar_one_or_none.return_value = "Anna"

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[share_result, owner_result])

        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)):
            response = await get_workflow(workflow.id, current_user, db)

        self.assertEqual(response.owner_name, "Anna")


class WorkflowDetailPortalFieldsTests(unittest.IsolatedAsyncioTestCase):
    """The listing preview reads the portal link off the workflow detail, not a second call."""

    async def test_portal_fields_are_returned(self) -> None:
        current_user = User(id=uuid.uuid4(), email="a@b.c", hashed_password="hashed", name="Anna")
        workflow = make_detail_workflow(current_user.id)
        workflow.portal_enabled = True
        workflow.portal_slug = "support"

        db = AsyncMock()
        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)):
            response = await get_workflow(workflow.id, current_user, db)

        self.assertTrue(response.portal_enabled)
        self.assertEqual(response.portal_slug, "support")

    async def test_portal_defaults_to_disabled(self) -> None:
        current_user = User(id=uuid.uuid4(), email="a@b.c", hashed_password="hashed", name="Anna")
        workflow = make_detail_workflow(current_user.id)

        db = AsyncMock()
        with patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)):
            response = await get_workflow(workflow.id, current_user, db)

        self.assertFalse(response.portal_enabled)
        self.assertIsNone(response.portal_slug)


class WebStatusTests(unittest.TestCase):
    HTML_NODE = {"id": "html1", "type": "htmlOutputMapper", "data": {"label": "page"}}

    def test_sole_html_terminal_reads_web_instead_of_manual(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}, self.HTML_NODE]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(compute_trigger_status(nodes, edges), "web")

    def test_web_survives_the_api_refinement(self) -> None:
        """A page-serving workflow reads WEB, not API, after its first HTTP call."""
        nodes = [{"id": "in1", "type": "textInput", "data": {}}, self.HTML_NODE]
        edges = [{"source": "in1", "target": "html1"}]
        status = compute_trigger_status(nodes, edges)
        self.assertEqual(refine_manual_status(status, "api"), "web")

    def test_a_cron_trigger_still_wins(self) -> None:
        nodes = [
            {"id": "c1", "type": "cron", "data": {"cronExpression": "* * * * *"}},
            self.HTML_NODE,
        ]
        edges = [{"source": "c1", "target": "html1"}]
        self.assertEqual(compute_trigger_status(nodes, edges), "scheduled")

    def test_a_second_terminal_keeps_manual(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            self.HTML_NODE,
            {"id": "out1", "type": "output", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}, {"source": "in1", "target": "out1"}]
        self.assertEqual(compute_trigger_status(nodes, edges), "manual")

    def test_edges_omitted_keeps_the_old_manual_behaviour(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}]
        self.assertEqual(compute_trigger_status(nodes), "manual")


if __name__ == "__main__":
    unittest.main()
