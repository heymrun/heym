"""GHSA-c3f4-2mrj-jfqr: only the workflow owner may choose a workflow's error workflow.

The error workflow runs with the failed run's credential and global-variable context, and
for anonymous and triggered runs that context is the owner's. A shared collaborator who
points it at a workflow they own would run their own nodes with the owner's credentials,
so adding, replacing and clearing it are owner-only. Everything else sharing grants stays
editable.
"""

import unittest
import uuid
from collections.abc import Collection
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api.workflows import update_workflow
from app.models.schemas import WebhookBodyMode, WorkflowAuthType, WorkflowUpdate

# What the settings panel sends for "None": it clears the stored error workflow.
CLEAR_ERROR_WORKFLOW = uuid.UUID(int=0)


def _workflow(owner_id: uuid.UUID, error_workflow_id: uuid.UUID | None = None) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind="workflow",
        name="Owner workflow",
        description=None,
        nodes=[],
        edges=[],
        auth_type=WorkflowAuthType.jwt,
        auth_header_key=None,
        auth_header_value=None,
        webhook_body_mode=WebhookBodyMode.legacy,
        http_method="POST",
        allow_anonymous=False,
        owner_id=owner_id,
        folder_id=None,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        sse_node_config=None,
        auto_recover_runs=True,
        error_workflow_id=error_workflow_id,
        minutes_saved_per_run=None,
        workflow_timeout_seconds=None,
        created_at=now,
        updated_at=now,
    )


class ErrorWorkflowOwnershipTests(unittest.IsolatedAsyncioTestCase):
    """Drives ``update_workflow`` itself, so a guard that is never called cannot pass."""

    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.collaborator_id = uuid.uuid4()
        self.db = AsyncMock()
        self.db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        self.db.add = lambda _row: None

    async def _put(
        self,
        workflow: SimpleNamespace,
        actor_id: uuid.UUID,
        payload: WorkflowUpdate,
        *,
        hidden: Collection[uuid.UUID] = (),
    ) -> None:
        """Save ``payload`` as ``actor_id``.

        Every other workflow resolves for the actor unless it is ``hidden``, as the target does
        for an attacker who owns it, so the target lookup is never what refuses a collaborator.
        """

        async def visible(
            _db: object, workflow_id: uuid.UUID, _user_id: uuid.UUID
        ) -> SimpleNamespace | None:
            if workflow_id == workflow.id:
                return workflow
            return None if workflow_id in hidden else SimpleNamespace(id=workflow_id)

        with (
            patch("app.api.workflows.get_workflow_for_user", AsyncMock(side_effect=visible)),
            patch("app.api.workflows._build_workflow_response", return_value=None),
            patch("app.api.workflows.publish_event", AsyncMock()),
            patch("app.services.websocket_trigger_service.websocket_trigger_manager.request_sync"),
        ):
            await update_workflow(
                workflow_id=workflow.id,
                workflow_data=payload,
                current_user=SimpleNamespace(id=actor_id, email="user@example.com"),
                db=self.db,
            )

    async def _assert_collaborator_refused(
        self, workflow: SimpleNamespace, payload: WorkflowUpdate
    ) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._put(workflow, self.collaborator_id, payload)

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        self.db.commit.assert_not_awaited()

    async def test_collaborator_cannot_add_an_error_workflow(self) -> None:
        """The reported attack: the collaborator's own workflow would run as the owner."""
        workflow = _workflow(self.owner_id)

        await self._assert_collaborator_refused(
            workflow, WorkflowUpdate(error_workflow_id=uuid.uuid4())
        )

        self.assertIsNone(workflow.error_workflow_id)

    async def test_collaborator_cannot_replace_the_configured_error_workflow(self) -> None:
        configured = uuid.uuid4()
        workflow = _workflow(self.owner_id, configured)

        await self._assert_collaborator_refused(
            workflow, WorkflowUpdate(error_workflow_id=uuid.uuid4())
        )

        self.assertEqual(workflow.error_workflow_id, configured)

    async def test_collaborator_cannot_clear_the_configured_error_workflow(self) -> None:
        """Removing the owner's failure handling is a change too."""
        configured = uuid.uuid4()
        workflow = _workflow(self.owner_id, configured)

        await self._assert_collaborator_refused(
            workflow, WorkflowUpdate(error_workflow_id=CLEAR_ERROR_WORKFLOW)
        )

        self.assertEqual(workflow.error_workflow_id, configured)

    async def test_refused_save_changes_nothing_else_either(self) -> None:
        """The whole request is refused, not just the error workflow part of it."""
        workflow = _workflow(self.owner_id)

        await self._assert_collaborator_refused(
            workflow,
            WorkflowUpdate(name="Renamed", nodes=[{"id": "n1"}], error_workflow_id=uuid.uuid4()),
        )

        self.assertEqual(workflow.name, "Owner workflow")
        self.assertEqual(workflow.nodes, [])

    async def test_collaborator_can_still_edit_what_sharing_grants(self) -> None:
        configured = uuid.uuid4()
        workflow = _workflow(self.owner_id, configured)
        nodes = [{"id": "n1", "type": "textInput", "data": {}}]
        edges = [{"id": "e1", "source": "n1", "target": "n2"}]

        await self._put(
            workflow,
            self.collaborator_id,
            WorkflowUpdate(name="Renamed", description="Edited", nodes=nodes, edges=edges),
        )

        self.assertEqual(workflow.name, "Renamed")
        self.assertEqual(workflow.description, "Edited")
        self.assertEqual(workflow.nodes, nodes)
        self.assertEqual(workflow.edges, edges)
        self.assertEqual(workflow.error_workflow_id, configured)
        self.db.commit.assert_awaited_once()

    async def test_collaborator_echoing_the_error_workflow_still_saves(self) -> None:
        """A client that sends back what it read changes nothing, so the save goes through.

        The owner's error workflow is usually private to the owner, so an unchanged value must
        not be looked up again as the collaborator.
        """
        configured = uuid.uuid4()
        workflow = _workflow(self.owner_id, configured)
        nodes = [{"id": "n1", "type": "textInput", "data": {}}]

        await self._put(
            workflow,
            self.collaborator_id,
            WorkflowUpdate(nodes=nodes, error_workflow_id=configured),
            hidden={configured},
        )

        self.assertEqual(workflow.nodes, nodes)
        self.assertEqual(workflow.error_workflow_id, configured)
        self.db.commit.assert_awaited_once()

    async def test_collaborator_clearing_an_unset_error_workflow_is_a_no_op(self) -> None:
        workflow = _workflow(self.owner_id)

        await self._put(
            workflow, self.collaborator_id, WorkflowUpdate(error_workflow_id=CLEAR_ERROR_WORKFLOW)
        )

        self.assertIsNone(workflow.error_workflow_id)
        self.db.commit.assert_awaited_once()

    async def test_owner_can_add_an_error_workflow(self) -> None:
        workflow = _workflow(self.owner_id)
        target = uuid.uuid4()

        await self._put(workflow, self.owner_id, WorkflowUpdate(error_workflow_id=target))

        self.assertEqual(workflow.error_workflow_id, target)
        self.db.commit.assert_awaited_once()

    async def test_owner_can_replace_the_error_workflow(self) -> None:
        workflow = _workflow(self.owner_id, uuid.uuid4())
        target = uuid.uuid4()

        await self._put(workflow, self.owner_id, WorkflowUpdate(error_workflow_id=target))

        self.assertEqual(workflow.error_workflow_id, target)
        self.db.commit.assert_awaited_once()

    async def test_owner_can_clear_the_error_workflow(self) -> None:
        workflow = _workflow(self.owner_id, uuid.uuid4())

        await self._put(
            workflow, self.owner_id, WorkflowUpdate(error_workflow_id=CLEAR_ERROR_WORKFLOW)
        )

        self.assertIsNone(workflow.error_workflow_id)
        self.db.commit.assert_awaited_once()

    async def test_owner_still_cannot_pick_a_workflow_they_cannot_open(self) -> None:
        """The owner's own target check is unchanged."""
        workflow = _workflow(self.owner_id)
        foreign = uuid.uuid4()

        with self.assertRaises(HTTPException) as ctx:
            await self._put(
                workflow,
                self.owner_id,
                WorkflowUpdate(error_workflow_id=foreign),
                hidden={foreign},
            )

        self.assertEqual(ctx.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIsNone(workflow.error_workflow_id)
        self.db.commit.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
