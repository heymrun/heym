"""Only the workflow owner changes a workflow's run settings.

Timeout, concurrency, auto-recover and time saved per run shape every production run and the
owner's analytics. The editor's settings panel already disables them for collaborators; the
server refuses the change too, so a client that is not that panel (Heym Work, a script) cannot
make it as a shared collaborator. Echoing the stored value still saves.
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api.workflows import update_workflow
from app.models.schemas import WebhookBodyMode, WorkflowAuthType, WorkflowUpdate

# A change each run setting would make on a workflow left at its defaults.
CHANGES: dict[str, Any] = {
    "auto_recover_runs": False,
    "minutes_saved_per_run": 15.0,
    "workflow_timeout_seconds": 120,
    "concurrency_limit": 2,
    "concurrency_max_queue": 10,
    "concurrency_max_wait_seconds": 60,
}


def _workflow(owner_id: uuid.UUID, **overrides: Any) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": "workflow",
        "name": "Owner workflow",
        "description": None,
        "nodes": [],
        "edges": [],
        "auth_type": WorkflowAuthType.jwt,
        "auth_header_key": None,
        "auth_header_value": None,
        "webhook_body_mode": WebhookBodyMode.legacy,
        "http_method": "POST",
        "allow_anonymous": False,
        "owner_id": owner_id,
        "folder_id": None,
        "cache_ttl_seconds": None,
        "rate_limit_requests": None,
        "rate_limit_window_seconds": None,
        "sse_enabled": False,
        "sse_node_config": None,
        "auto_recover_runs": True,
        "error_workflow_id": None,
        "minutes_saved_per_run": None,
        "workflow_timeout_seconds": None,
        "concurrency_limit": None,
        "concurrency_max_queue": None,
        "concurrency_max_wait_seconds": None,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RunSettingsOwnershipTests(unittest.IsolatedAsyncioTestCase):
    """Drives ``update_workflow`` itself, so a guard that is never called cannot pass."""

    def setUp(self) -> None:
        patcher = patch("app.api.workflows.user_can_write_workflow", AsyncMock(return_value=True))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.owner_id = uuid.uuid4()
        self.collaborator_id = uuid.uuid4()
        self.db = AsyncMock()
        self.db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        self.db.add = lambda _row: None

    async def _put(
        self, workflow: SimpleNamespace, actor_id: uuid.UUID, payload: WorkflowUpdate
    ) -> None:
        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch("app.api.workflows._build_workflow_response", return_value=None),
            patch("app.api.workflows.publish_event", AsyncMock()),
            patch("app.api.workflows.workflow_concurrency.promote", AsyncMock(return_value=0)),
            patch("app.services.websocket_trigger_service.websocket_trigger_manager.request_sync"),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=payload,
                current_user=SimpleNamespace(id=actor_id, email="user@example.com"),
                db=self.db,
            )

    async def test_collaborator_cannot_change_any_run_setting(self) -> None:
        for field, value in CHANGES.items():
            with self.subTest(field=field):
                workflow = _workflow(self.owner_id)
                before = getattr(workflow, field)
                self.db.commit.reset_mock()

                with self.assertRaises(HTTPException) as ctx:
                    await self._put(
                        workflow, self.collaborator_id, WorkflowUpdate(**{field: value})
                    )

                self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(getattr(workflow, field), before)
                self.db.commit.assert_not_awaited()

    async def test_collaborator_cannot_clear_a_configured_run_setting(self) -> None:
        workflow = _workflow(self.owner_id, workflow_timeout_seconds=300, concurrency_limit=3)

        for field in ("workflow_timeout_seconds", "concurrency_limit"):
            with self.subTest(field=field), self.assertRaises(HTTPException) as ctx:
                await self._put(workflow, self.collaborator_id, WorkflowUpdate(**{field: 0}))
            self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(workflow.workflow_timeout_seconds, 300)
        self.assertEqual(workflow.concurrency_limit, 3)

    async def test_refused_save_changes_nothing_else_either(self) -> None:
        workflow = _workflow(self.owner_id)

        with self.assertRaises(HTTPException):
            await self._put(
                workflow,
                self.collaborator_id,
                WorkflowUpdate(name="Renamed", workflow_timeout_seconds=5),
            )

        self.assertEqual(workflow.name, "Owner workflow")
        self.assertIsNone(workflow.workflow_timeout_seconds)

    async def test_collaborator_echoing_the_stored_settings_still_saves(self) -> None:
        workflow = _workflow(
            self.owner_id,
            minutes_saved_per_run=12.5,
            workflow_timeout_seconds=300,
            concurrency_limit=2,
        )

        await self._put(
            workflow,
            self.collaborator_id,
            WorkflowUpdate(
                name="Renamed",
                auto_recover_runs=True,
                minutes_saved_per_run=12.5,
                workflow_timeout_seconds=300,
                concurrency_limit=2,
                concurrency_max_queue=0,
            ),
        )

        self.assertEqual(workflow.name, "Renamed")
        self.db.commit.assert_awaited_once()

    async def test_collaborator_can_still_rename(self) -> None:
        workflow = _workflow(self.owner_id)

        await self._put(
            workflow, self.collaborator_id, WorkflowUpdate(name="Renamed", description="New")
        )

        self.assertEqual((workflow.name, workflow.description), ("Renamed", "New"))
        self.db.commit.assert_awaited_once()

    async def test_owner_changes_every_run_setting(self) -> None:
        workflow = _workflow(self.owner_id)

        await self._put(workflow, self.owner_id, WorkflowUpdate(**CHANGES))

        for field, value in CHANGES.items():
            self.assertEqual(getattr(workflow, field), value, field)
        self.db.commit.assert_awaited_once()

    async def test_owner_clears_with_zero(self) -> None:
        workflow = _workflow(self.owner_id, minutes_saved_per_run=10.0, workflow_timeout_seconds=60)

        await self._put(
            workflow,
            self.owner_id,
            WorkflowUpdate(minutes_saved_per_run=0, workflow_timeout_seconds=0),
        )

        self.assertIsNone(workflow.minutes_saved_per_run)
        self.assertIsNone(workflow.workflow_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
