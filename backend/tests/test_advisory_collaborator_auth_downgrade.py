"""GHSA-5939-m9jm-7gf5: a shared collaborator must not move the execution auth boundary.

``update_workflow`` authorizes through ``get_workflow_for_user``, which accepts direct and
team-shared collaborators. Setting ``auth_type=anonymous`` publishes the workflow to
unauthenticated callers, and an anonymous run resolves credentials and global variables as
the owner - so the downgrade is an escalation, not ordinary canvas editing.
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api.workflows import _reject_non_owner_auth_change, update_workflow
from app.models.schemas import WebhookBodyMode, WorkflowAuthType, WorkflowUpdate
from app.services.workflow_access import workflow_access_clause


def _workflow(
    owner_id: uuid.UUID,
    *,
    auth_type: WorkflowAuthType = WorkflowAuthType.jwt,
    header_key: str | None = "X-API-Key",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id,
        auth_type=auth_type,
        auth_header_key=header_key,
        auth_header_value="s3cr3t",
        webhook_body_mode=WebhookBodyMode.legacy,
        http_method="POST",
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        sse_node_config=None,
    )


class CollaboratorAuthDowngradeTests(unittest.TestCase):
    def _assert_forbidden(
        self, workflow: SimpleNamespace, update: WorkflowUpdate, actor: uuid.UUID
    ) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _reject_non_owner_auth_change(workflow, update, actor)
        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)

    def test_collaborator_cannot_downgrade_to_anonymous(self) -> None:
        """The reported attack: shared editor publishes the owner's workflow."""
        workflow = _workflow(uuid.uuid4())

        self._assert_forbidden(
            workflow,
            WorkflowUpdate(auth_type=WorkflowAuthType.anonymous),
            uuid.uuid4(),
        )

    def test_collaborator_cannot_change_auth_header_key(self) -> None:
        """The key pairs with the owner-only secret, so it is owner-only too."""
        workflow = _workflow(uuid.uuid4(), auth_type=WorkflowAuthType.header_auth)

        self._assert_forbidden(
            workflow,
            WorkflowUpdate(auth_header_key="X-Attacker-Chosen"),
            uuid.uuid4(),
        )

    def test_collaborator_cannot_upgrade_either(self) -> None:
        """The guard is about ownership of the boundary, not the direction of the change."""
        workflow = _workflow(uuid.uuid4(), auth_type=WorkflowAuthType.anonymous)

        self._assert_forbidden(
            workflow,
            WorkflowUpdate(auth_type=WorkflowAuthType.jwt),
            uuid.uuid4(),
        )

    def test_owner_may_still_downgrade(self) -> None:
        """Publishing a workflow anonymously stays a supported owner action."""
        owner_id = uuid.uuid4()
        workflow = _workflow(owner_id)

        _reject_non_owner_auth_change(
            workflow,
            WorkflowUpdate(auth_type=WorkflowAuthType.anonymous),
            owner_id,
        )

    def test_collaborator_echoing_current_auth_config_is_allowed(self) -> None:
        """A no-op write cannot move the boundary, so it must not break collaborator saves."""
        workflow = _workflow(uuid.uuid4(), auth_type=WorkflowAuthType.header_auth)

        _reject_non_owner_auth_change(
            workflow,
            WorkflowUpdate(
                auth_type=WorkflowAuthType.header_auth,
                auth_header_key="X-API-Key",
            ),
            uuid.uuid4(),
        )

    def test_collaborator_may_still_edit_the_canvas(self) -> None:
        """Sharing still grants canvas access; only the execution boundary is withheld."""
        workflow = _workflow(uuid.uuid4())

        _reject_non_owner_auth_change(
            workflow,
            WorkflowUpdate(name="renamed", nodes=[{"id": "n1"}], edges=[]),
            uuid.uuid4(),
        )

    def test_collaborator_cannot_change_request_body_contract(self) -> None:
        """webhook_body_mode is part of the published request contract, not the canvas."""
        workflow = _workflow(uuid.uuid4())

        self._assert_forbidden(workflow, WorkflowUpdate(webhook_body_mode="generic"), uuid.uuid4())


class UpdateWorkflowEndpointTests(unittest.IsolatedAsyncioTestCase):
    """The guard is only worth anything if ``update_workflow`` actually runs it."""

    def _shared_workflow(self, workflow_id: uuid.UUID) -> SimpleNamespace:
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            id=workflow_id,
            kind="workflow",
            name="Owner workflow",
            description=None,
            nodes=[],
            edges=[],
            auth_type=WorkflowAuthType.jwt,
            auth_header_key=None,
            auth_header_value="s3cr3t",
            webhook_body_mode=WebhookBodyMode.legacy,
            allow_anonymous=False,
            owner_id=uuid.uuid4(),
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
            created_at=now,
            updated_at=now,
        )

    async def test_collaborator_put_is_rejected_and_nothing_is_persisted(self) -> None:
        workflow_id = uuid.uuid4()
        workflow = self._shared_workflow(workflow_id)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        db.add = lambda _row: None
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await update_workflow(
                    workflow_id=workflow_id,
                    workflow_data=WorkflowUpdate(auth_type=WorkflowAuthType.anonymous),
                    current_user=SimpleNamespace(id=uuid.uuid4()),
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        # The boundary is unchanged in memory and no write reached the database.
        self.assertEqual(workflow.auth_type, WorkflowAuthType.jwt)
        self.assertFalse(workflow.allow_anonymous)
        db.commit.assert_not_awaited()

    async def test_owner_put_still_publishes_anonymously(self) -> None:
        workflow_id = uuid.uuid4()
        workflow = self._shared_workflow(workflow_id)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        db.add = lambda _row: None
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with (
            patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ),
            patch("app.api.workflows._build_workflow_response", return_value={"ok": True}),
            patch("app.api.workflows.publish_event", AsyncMock()),
            patch("app.services.websocket_trigger_service.websocket_trigger_manager.request_sync"),
        ):
            await update_workflow(
                workflow_id=workflow_id,
                workflow_data=WorkflowUpdate(auth_type=WorkflowAuthType.anonymous),
                current_user=SimpleNamespace(id=workflow.owner_id),
                db=db,
            )

        self.assertEqual(workflow.auth_type, WorkflowAuthType.anonymous)
        db.commit.assert_awaited_once()


class SharedCollaboratorRegressionTests(unittest.IsolatedAsyncioTestCase):
    """Both share kinds reach ``update_workflow``; neither may move the boundary.

    There is no DB-backed test harness in this repo, so the two share paths are proven at
    the place they actually differ - the access clause - and the guard is then proven to
    reject every non-owner. Mocking ``get_workflow_for_user`` twice would only assert the
    same code path under two names.
    """

    def test_access_clause_admits_both_direct_and_team_shares(self) -> None:
        """The precondition: a collaborator of either kind reaches update_workflow at all."""
        clause = workflow_access_clause(uuid.uuid4())
        sql = str(clause.compile(compile_kwargs={"literal_binds": True}))

        self.assertIn("workflow_shares", sql)
        self.assertIn("workflow_team_shares", sql)
        self.assertIn("workflows.owner_id", sql)

    async def _put_as(
        self, collaborator_id: uuid.UUID, payload: WorkflowUpdate
    ) -> tuple[HTTPException, SimpleNamespace, AsyncMock]:
        workflow_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        workflow = SimpleNamespace(
            id=workflow_id,
            kind="workflow",
            name="Owner workflow",
            description=None,
            nodes=[],
            edges=[],
            auth_type=WorkflowAuthType.jwt,
            auth_header_key=None,
            auth_header_value="s3cr3t",
            webhook_body_mode=WebhookBodyMode.legacy,
            http_method="POST",
            allow_anonymous=False,
            owner_id=uuid.uuid4(),
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
            created_at=now,
            updated_at=now,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=SimpleNamespace(scalar=lambda: 0))
        db.add = lambda _row: None
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=workflow),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await update_workflow(
                    workflow_id=workflow_id,
                    workflow_data=payload,
                    current_user=SimpleNamespace(id=collaborator_id),
                    db=db,
                )
        return ctx.exception, workflow, db

    async def test_non_owner_cannot_publish_anonymously(self) -> None:
        exc, workflow, db = await self._put_as(
            uuid.uuid4(), WorkflowUpdate(auth_type=WorkflowAuthType.anonymous)
        )

        self.assertEqual(exc.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(workflow.auth_type, WorkflowAuthType.jwt)
        db.commit.assert_not_awaited()

    async def test_collaborator_cannot_change_rate_limit(self) -> None:
        """Rate limit and cache are the owner's cost controls, not canvas state."""
        exc, _workflow, _db = await self._put_as(
            uuid.uuid4(), WorkflowUpdate(rate_limit_requests=100000)
        )

        self.assertEqual(exc.status_code, status.HTTP_403_FORBIDDEN)

    async def test_collaborator_cannot_change_http_method(self) -> None:
        exc, _workflow, _db = await self._put_as(uuid.uuid4(), WorkflowUpdate(http_method="GET"))

        self.assertEqual(exc.status_code, status.HTTP_403_FORBIDDEN)


class NormalizedNoOpTests(unittest.TestCase):
    """A write that stores the same value must not be mistaken for a change."""

    def test_lowercase_http_method_echo_is_a_no_op(self) -> None:
        workflow = _workflow(uuid.uuid4())
        workflow.http_method = "POST"

        _reject_non_owner_auth_change(workflow, WorkflowUpdate(http_method="post"), uuid.uuid4())

    def test_zero_cache_ttl_against_unset_is_a_no_op(self) -> None:
        workflow = _workflow(uuid.uuid4())
        workflow.cache_ttl_seconds = None

        _reject_non_owner_auth_change(workflow, WorkflowUpdate(cache_ttl_seconds=0), uuid.uuid4())


if __name__ == "__main__":
    unittest.main()
