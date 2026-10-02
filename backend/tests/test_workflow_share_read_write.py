"""Read / write permissions on direct and team workflow shares."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api import agent_memory as agent_memory_api
from app.api import workflows as workflows_api
from app.db.models import User, Workflow, WorkflowShare, WorkflowTeamShare
from app.models.schemas import (
    WorkflowShareRequest,
    WorkflowTeamShareRequest,
    WorkflowUpdate,
)
from app.services.workflow_access import (
    get_workflow_permission,
    user_can_write_workflow,
)


def _workflow(owner_id: uuid.UUID) -> Workflow:
    return Workflow(
        id=uuid.uuid4(),
        name="Shared Workflow",
        description=None,
        owner_id=owner_id,
        nodes=[],
        edges=[],
        kind="workflow",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _scalars(values: list[str]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _db_with_permissions(direct: list[str], team: list[str]) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalars(direct), _scalars(team)])
    return db


class GetWorkflowPermissionTest(unittest.IsolatedAsyncioTestCase):
    async def test_owner_writes_without_querying(self) -> None:
        owner_id = uuid.uuid4()
        db = AsyncMock()

        permission = await get_workflow_permission(db, _workflow(owner_id), owner_id)

        self.assertEqual(permission, "write")
        db.execute.assert_not_awaited()

    async def test_direct_read_share_is_read(self) -> None:
        workflow = _workflow(uuid.uuid4())
        db = _db_with_permissions(["read"], [])

        self.assertEqual(await get_workflow_permission(db, workflow, uuid.uuid4()), "read")

    async def test_direct_write_share_is_write(self) -> None:
        workflow = _workflow(uuid.uuid4())
        db = _db_with_permissions(["write"], [])

        self.assertEqual(await get_workflow_permission(db, workflow, uuid.uuid4()), "write")

    async def test_team_write_wins_over_direct_read(self) -> None:
        workflow = _workflow(uuid.uuid4())
        db = _db_with_permissions(["read"], ["write"])

        self.assertEqual(await get_workflow_permission(db, workflow, uuid.uuid4()), "write")

    async def test_direct_write_wins_over_team_read(self) -> None:
        workflow = _workflow(uuid.uuid4())
        db = _db_with_permissions(["write"], ["read", "read"])

        self.assertEqual(await get_workflow_permission(db, workflow, uuid.uuid4()), "write")

    async def test_only_read_grants_stay_read(self) -> None:
        workflow = _workflow(uuid.uuid4())
        db = _db_with_permissions(["read"], ["read"])

        self.assertFalse(await user_can_write_workflow(db, workflow, uuid.uuid4()))

    async def test_no_grant_is_no_permission(self) -> None:
        workflow = _workflow(uuid.uuid4())
        db = _db_with_permissions([], [])

        self.assertIsNone(await get_workflow_permission(db, workflow, uuid.uuid4()))

    async def test_direct_lookup_ignores_folder_only_rows(self) -> None:
        workflow = _workflow(uuid.uuid4())
        db = _db_with_permissions([], [])

        await get_workflow_permission(db, workflow, uuid.uuid4())

        sql = str(db.execute.await_args_list[0].args[0])
        self.assertIn("is_explicit_share", sql)


class ShareRequestSchemaTest(unittest.TestCase):
    def test_existing_clients_that_omit_permission_keep_write(self) -> None:
        self.assertEqual(WorkflowShareRequest(email="a@example.com").permission, "write")
        self.assertEqual(WorkflowTeamShareRequest(team_id=uuid.uuid4()).permission, "write")

    def test_rejects_unknown_permission(self) -> None:
        with self.assertRaises(ValidationError):
            WorkflowShareRequest(email="a@example.com", permission="admin")
        with self.assertRaises(ValidationError):
            WorkflowTeamShareRequest(team_id=uuid.uuid4(), permission="owner")


class RequireWorkflowWriteTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_collaborator_gets_403(self) -> None:
        workflow = _workflow(uuid.uuid4())
        with patch.object(workflows_api, "user_can_write_workflow", AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                await workflows_api.require_workflow_write(AsyncMock(), workflow, uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 403)

    async def test_writer_passes(self) -> None:
        workflow = _workflow(uuid.uuid4())
        with patch.object(workflows_api, "user_can_write_workflow", AsyncMock(return_value=True)):
            await workflows_api.require_workflow_write(AsyncMock(), workflow, uuid.uuid4())


class UpdateWorkflowRequiresWriteTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_collaborator_cannot_save(self) -> None:
        workflow = _workflow(uuid.uuid4())
        collaborator = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()

        with (
            patch.object(workflows_api, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(workflows_api, "user_can_write_workflow", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await workflows_api.update_workflow(
                    workflow.id, WorkflowUpdate(name="Renamed"), collaborator, db
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(workflow.name, "Shared Workflow")

    async def test_read_only_collaborator_cannot_clear_cache(self) -> None:
        workflow = _workflow(uuid.uuid4())
        collaborator = SimpleNamespace(id=uuid.uuid4())

        with (
            patch.object(workflows_api, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(workflows_api, "user_can_write_workflow", AsyncMock(return_value=False)),
            patch.object(workflows_api.response_cache, "clear_workflow", AsyncMock()) as clear,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await workflows_api.clear_workflow_response_cache(
                    workflow.id, collaborator, AsyncMock()
                )

        self.assertEqual(ctx.exception.status_code, 403)
        clear.assert_not_awaited()


class AgentMemoryMutationsRequireWriteTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_collaborator_cannot_add_memory_node(self) -> None:
        workflow = _workflow(uuid.uuid4())
        collaborator = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        body = SimpleNamespace(entity_name="x", entity_type="t", properties={}, confidence=1.0)

        with (
            patch.object(
                agent_memory_api, "get_workflow_for_user", AsyncMock(return_value=workflow)
            ),
            patch.object(workflows_api, "user_can_write_workflow", AsyncMock(return_value=False)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await agent_memory_api.add_memory_node(workflow.id, "node", body, db, collaborator)

        self.assertEqual(ctx.exception.status_code, 403)
        db.add.assert_not_called()


def _user(email: str = "member@example.com") -> User:
    return User(id=uuid.uuid4(), email=email, name="Member", hashed_password="hashed")


class CreateWorkflowShareStoresPermissionTest(unittest.IsolatedAsyncioTestCase):
    async def _create(
        self, existing: WorkflowShare | None, request: WorkflowShareRequest, target: User
    ):
        owner = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com", name="Owner")
        workflow = _workflow(owner_id=owner.id)
        user_lookup = MagicMock()
        user_lookup.scalar_one_or_none.return_value = target
        share_lookup = MagicMock()
        share_lookup.scalar_one_or_none.return_value = existing
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(side_effect=[user_lookup, share_lookup])

        async def refresh(obj: WorkflowShare) -> None:
            obj.id = obj.id or uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        db.refresh = AsyncMock(side_effect=refresh)

        with (
            patch.object(workflows_api, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(workflows_api, "audit") as audit,
        ):
            response = await workflows_api.create_workflow_share(workflow.id, request, owner, db)
        return response, db, audit

    async def test_new_read_share_is_stored_as_read(self) -> None:
        target = _user()

        response, db, _audit = await self._create(
            None, WorkflowShareRequest(email=target.email, permission="read"), target
        )

        stored = db.add.call_args.args[0]
        self.assertEqual(stored.permission, "read")
        self.assertEqual(response.permission, "read")

    async def test_resharing_updates_the_permission(self) -> None:
        target = _user()
        existing = WorkflowShare(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            user_id=target.id,
            is_explicit_share=True,
            permission="write",
            created_at=datetime.now(timezone.utc),
        )

        response, db, audit = await self._create(
            existing, WorkflowShareRequest(email=target.email, permission="read"), target
        )

        self.assertEqual(existing.permission, "read")
        self.assertEqual(response.permission, "read")
        db.add.assert_not_called()
        self.assertEqual(audit.call_args.kwargs["action"], "workflow.share_update")
        self.assertEqual(audit.call_args.kwargs["previous_permission"], "write")

    async def test_resharing_with_same_permission_is_a_no_op(self) -> None:
        target = _user()
        existing = WorkflowShare(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            user_id=target.id,
            is_explicit_share=True,
            permission="write",
            created_at=datetime.now(timezone.utc),
        )

        _response, _db, audit = await self._create(
            existing, WorkflowShareRequest(email=target.email, permission="write"), target
        )

        audit.assert_not_called()


class WorkflowTeamShareEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def _create(self, existing: WorkflowTeamShare | None, permission: str):
        owner = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com", name="Owner")
        workflow = _workflow(owner_id=owner.id)
        team = SimpleNamespace(id=uuid.uuid4(), name="Platform")
        team_lookup = MagicMock()
        team_lookup.scalar_one_or_none.return_value = team
        share_lookup = MagicMock()
        share_lookup.scalar_one_or_none.return_value = existing
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(side_effect=[team_lookup, share_lookup])

        async def refresh(obj: WorkflowTeamShare) -> None:
            obj.id = obj.id or uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)

        db.refresh = AsyncMock(side_effect=refresh)
        payload = WorkflowTeamShareRequest(team_id=team.id, permission=permission)

        with (
            patch.object(workflows_api, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(workflows_api, "audit") as audit,
        ):
            response = await workflows_api.create_workflow_team_share(
                workflow.id, payload, owner, db
            )
        return response, db, audit, team

    async def test_new_team_share_stores_permission(self) -> None:
        response, db, _audit, _team = await self._create(None, "read")

        self.assertEqual(db.add.call_args.args[0].permission, "read")
        self.assertEqual(response.permission, "read")

    async def test_existing_team_share_permission_is_updated(self) -> None:
        existing = WorkflowTeamShare(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            team_id=uuid.uuid4(),
            permission="write",
            created_at=datetime.now(timezone.utc),
        )

        response, db, audit, _team = await self._create(existing, "read")

        self.assertEqual(existing.permission, "read")
        self.assertEqual(response.permission, "read")
        db.add.assert_not_called()
        self.assertEqual(audit.call_args.kwargs["action"], "workflow.team_share_update")


class BackwardCompatibilityTest(unittest.TestCase):
    def test_share_columns_default_to_write(self) -> None:
        for model in (WorkflowShare, WorkflowTeamShare):
            column = model.__table__.c.permission
            with self.subTest(model=model.__name__):
                self.assertFalse(column.nullable)
                self.assertEqual(column.default.arg, "write")
                self.assertEqual(str(column.server_default.arg), "write")


if __name__ == "__main__":
    unittest.main()
