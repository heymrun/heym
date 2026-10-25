"""Instance administrators can retire workflows without taking ownership."""

import copy
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api import workflows as api
from app.api.schedules import _workflows_where_clause
from app.config import settings
from app.db.models import User, Workflow
from app.services.instance_admin import instance_admin_clause, is_instance_admin
from app.services.workflow_access import get_workflow_permission, workflow_access_clause
from app.services.workflow_lifecycle import (
    has_unfinished_workflow_executions,
    set_automatic_triggers_paused,
)
from app.services.workflow_status import TRIGGER_NODE_TYPES


def _sql(statement: object) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


class AdminWorkflowAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.object(settings, "admin_emails", " ADMIN@example.com , ")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = User(id=uuid.uuid4(), email="Admin@example.com", name="Admin")

    async def test_admin_write_access_does_not_need_a_share(self) -> None:
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar=lambda: True)
        workflow = Workflow(id=uuid.uuid4(), owner_id=uuid.uuid4())

        self.assertEqual(await get_workflow_permission(db, workflow, self.admin.id), "write")
        db.execute.assert_awaited_once()
        sql = _sql(db.execute.await_args.args[0])
        self.assertIn(str(self.admin.id), sql)
        self.assertIn("lower(trim(users.email)) IN ('admin@example.com')", sql)

    async def test_non_admin_still_needs_a_share(self) -> None:
        db = AsyncMock()
        no_share = MagicMock()
        no_share.scalars.return_value.all.return_value = []
        db.execute.side_effect = [MagicMock(scalar=lambda: False), no_share, no_share]
        workflow = Workflow(id=uuid.uuid4(), owner_id=uuid.uuid4())
        self.assertIsNone(await get_workflow_permission(db, workflow, self.admin.id))

    def test_access_uses_database_identity_and_environment_not_a_client_flag(self) -> None:
        sql = _sql(select(Workflow.id).where(workflow_access_clause(self.admin.id)))
        self.assertIn("FROM users", sql)
        self.assertIn(str(self.admin.id), sql)
        self.assertIn("'admin@example.com'", sql)
        self.assertTrue(is_instance_admin(self.admin))
        self.assertFalse(
            is_instance_admin(SimpleNamespace(email="other@example.com", is_admin=True))
        )
        with patch.object(settings, "admin_emails", ""):
            self.assertFalse(is_instance_admin(self.admin))
            self.assertEqual(
                _sql(select(instance_admin_clause(self.admin.id))), "SELECT false AS anon_1"
            )

    def test_admin_subquery_is_not_correlated_to_workflow_owner_join(self) -> None:
        statement = (
            select(Workflow.id)
            .join(User, Workflow.owner_id == User.id)
            .where(workflow_access_clause(self.admin.id))
        )
        self.assertIn("FROM users", _sql(statement))

    def test_schedule_all_scope_includes_admin_and_own_scope_stays_own(self) -> None:
        self.assertIn(
            "FROM users", _sql(select(Workflow.id).where(_workflows_where_clause(self.admin, True)))
        )
        own_sql = _sql(select(Workflow.id).where(_workflows_where_clause(self.admin, False)))
        self.assertNotIn("FROM users", own_sql)
        self.assertIn(f"workflows.owner_id = '{self.admin.id}'", own_sql)


class AdminWorkflowLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch.object(settings, "admin_emails", "admin@example.com")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = User(id=uuid.uuid4(), email="admin@example.com", name="Admin")
        self.workflow = Workflow(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Departed employee workflow",
            kind="workflow",
            nodes=[],
            edges=[],
            updated_at=datetime.now(timezone.utc),
        )
        self.db = AsyncMock()
        for name, value in (
            ("get_workflow_for_user", AsyncMock(return_value=self.workflow)),
            ("publish_event", AsyncMock()),
            ("audit", MagicMock()),
        ):
            patcher = patch.object(api, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_admin_can_delete_another_owners_idle_workflow(self) -> None:
        with patch.object(api, "has_unfinished_workflow_executions", AsyncMock(return_value=False)):
            await api.delete_workflow(self.workflow.id, self.admin, self.db)
        self.db.delete.assert_awaited_once_with(self.workflow)
        self.db.commit.assert_awaited_once()
        self.assertTrue(api.audit.call_args.kwargs["admin_override"])
        self.assertEqual(api.audit.call_args.kwargs["owner_id"], str(self.workflow.owner_id))
        self.assertEqual(api.publish_event.call_args.kwargs["owner_id"], self.workflow.owner_id)

    async def test_collaborator_cannot_delete(self) -> None:
        actor = User(id=uuid.uuid4(), email="collaborator@example.com")
        with self.assertRaises(HTTPException) as raised:
            await api.delete_workflow(self.workflow.id, actor, self.db)
        self.assertEqual(raised.exception.status_code, 403)
        self.db.delete.assert_not_awaited()

    async def test_admin_cannot_delete_until_workers_settle(self) -> None:
        with patch.object(api, "has_unfinished_workflow_executions", AsyncMock(return_value=True)):
            with self.assertRaises(HTTPException) as raised:
                await api.delete_workflow(self.workflow.id, self.admin, self.db)
        self.assertEqual(raised.exception.status_code, 409)
        self.db.delete.assert_not_awaited()

    async def test_pause_only_disables_automatic_triggers_and_uses_versioned_update(self) -> None:
        nodes = [{"id": t, "type": t, "data": {"active": True}} for t in sorted(TRIGGER_NODE_TYPES)]
        nodes += [{"id": "agent", "type": "agent", "data": {"active": True}}]
        self.workflow.nodes = copy.deepcopy(nodes)
        with patch.object(api, "update_workflow", AsyncMock(return_value="saved")) as update:
            response = await api.pause_workflow_triggers(self.workflow.id, self.admin, self.db)
        self.assertEqual(response, "saved")
        payload = update.call_args.args[1]
        self.assertTrue(all(n["data"]["active"] is False for n in payload.nodes[:-1]))
        self.assertTrue(payload.nodes[-1]["data"]["active"])
        self.assertEqual(self.workflow.nodes, nodes)
        self.assertEqual(payload.base_updated_at, self.workflow.updated_at)

    async def test_non_admin_cannot_use_admin_pause_endpoint(self) -> None:
        actor = User(id=self.workflow.owner_id, email="owner@example.com")
        with self.assertRaises(HTTPException) as raised:
            await api.pause_workflow_triggers(self.workflow.id, actor, self.db)
        self.assertEqual(raised.exception.status_code, 403)
        self.db.execute.assert_not_awaited()

    async def test_admin_can_cancel_remote_run_and_audits_actor(self) -> None:
        execution_id = uuid.uuid4()
        with (
            patch.object(api, "cancel_pending_review_execution", AsyncMock(return_value=False)),
            patch.object(api.workflow_concurrency, "cancel_held", AsyncMock(return_value=False)),
            patch.object(api, "cancel_active_execution", return_value=False),
            patch.object(
                api, "request_persisted_execution_cancel", AsyncMock(return_value=True)
            ) as cancel,
        ):
            await api.cancel_workflow_execution(self.workflow.id, execution_id, self.admin, self.db)
        cancel.assert_awaited_once_with(
            self.db, workflow_id=self.workflow.id, execution_id=execution_id
        )
        self.assertEqual(api.audit.call_args.kwargs["actor"], self.admin)

    async def test_registry_guard_includes_queue_reviews_and_cancel_requested_workers(self) -> None:
        self.db.execute.return_value = MagicMock(first=lambda: (uuid.uuid4(),))
        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[]):
            self.assertTrue(await has_unfinished_workflow_executions(self.db, self.workflow.id))
        sql = _sql(self.db.execute.call_args.args[0])
        for table in (
            "active_workflow_executions",
            "workflow_run_queue",
            "hitl_requests",
            "codex_followup_requests",
        ):
            self.assertIn(table, sql)
        self.assertNotIn("cancel_requested_at IS NULL", sql)

    async def test_cancel_requested_local_worker_still_blocks_deletion(self) -> None:
        handle = SimpleNamespace(workflow_id=self.workflow.id)
        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[handle]):
            self.assertTrue(await has_unfinished_workflow_executions(self.db, self.workflow.id))
        self.db.execute.assert_not_awaited()

    async def test_idle_workflow_is_safe_to_delete(self) -> None:
        self.db.execute.return_value = MagicMock(first=lambda: None)
        with patch("app.services.workflow_lifecycle.list_active_executions", return_value=[]):
            self.assertFalse(await has_unfinished_workflow_executions(self.db, self.workflow.id))

    async def test_admin_can_resume_using_a_versioned_update(self) -> None:
        self.workflow.nodes = [{"id": "cron", "type": "cron", "data": {"active": False}}]
        with patch.object(api, "update_workflow", AsyncMock(return_value="saved")) as update:
            response = await api.resume_workflow_triggers(self.workflow.id, self.admin, self.db)
        self.assertEqual(response, "saved")
        payload = update.call_args.args[1]
        self.assertTrue(payload.nodes[0]["data"]["active"])
        self.assertEqual(payload.base_updated_at, self.workflow.updated_at)
        self.assertEqual(api.audit.call_args.kwargs["action"], "workflow.resume_triggers")

    async def test_non_admin_cannot_resume(self) -> None:
        actor = User(id=self.workflow.owner_id, email="owner@example.com")
        with self.assertRaises(HTTPException) as raised:
            await api.resume_workflow_triggers(self.workflow.id, actor, self.db)
        self.assertEqual(raised.exception.status_code, 403)

    def test_resume_preserves_previously_disabled_triggers_across_repeated_requests(self) -> None:
        nodes = [
            {"id": "active", "type": "cron", "data": {"active": True}},
            {"id": "inactive", "type": "cron", "data": {"active": False}},
            {"id": "agent", "type": "agent", "data": {"active": True}},
        ]
        paused = set_automatic_triggers_paused(nodes, paused=True)
        paused_again = set_automatic_triggers_paused(paused, paused=True)
        self.assertEqual(paused_again, paused)
        resumed = set_automatic_triggers_paused(paused_again, paused=False)
        self.assertEqual(resumed, nodes)
        self.assertEqual(set_automatic_triggers_paused(resumed, paused=False), nodes)

    def test_resume_handles_existing_paused_workflows_without_markers(self) -> None:
        nodes = [{"id": "cron", "type": "cron", "data": {"active": False}}]
        self.assertTrue(set_automatic_triggers_paused(nodes, paused=False)[0]["data"]["active"])

    async def test_scheduled_cleanup_retains_busy_workflows(self) -> None:
        from app.services.cron_scheduler import CronScheduler

        self.db.execute.return_value = MagicMock()
        self.db.execute.return_value.scalars.return_value.all.return_value = [self.workflow]
        session = MagicMock()
        session.return_value.__aenter__ = AsyncMock(return_value=self.db)
        session.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch("app.services.cron_scheduler.async_session_maker", session),
            patch(
                "app.services.workflow_lifecycle.has_unfinished_workflow_executions",
                AsyncMock(return_value=True),
            ),
        ):
            await CronScheduler()._cleanup_scheduled_workflows()
        self.db.delete.assert_not_awaited()
