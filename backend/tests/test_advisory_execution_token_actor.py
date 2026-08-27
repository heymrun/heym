"""GHSA-5939-m9jm-7gf5 follow-up: a scoped execution token must run as its minter.

Execution tokens carry no ``type: access`` claim, so ``verify_access_token`` returns None and
``get_current_user_optional`` hands the endpoint ``current_user=None``. The execute endpoints
then resolve credentials and global variables as ``workflow.owner_id``. Because any
collaborator may mint a token for a shared workflow, that fallback let a collaborator run with
the owner's credential context without ever touching ``auth_type``.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api.workflows import validate_workflow_auth
from app.models.schemas import WorkflowAuthType
from app.services.auth import create_workflow_execution_token, verify_access_token


def _workflow(owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id,
        auth_type=WorkflowAuthType.jwt,
        auth_header_key=None,
        auth_header_value=None,
    )


def _request(token: str) -> SimpleNamespace:
    return SimpleNamespace(headers={"Authorization": f"Bearer {token}"})


class ExecutionTokenIsNotAnAccessToken(unittest.TestCase):
    """The precondition for the bypass, asserted so a token change cannot hide it."""

    def test_execution_token_does_not_resolve_to_a_session_user(self) -> None:
        token, _jti, _exp = create_workflow_execution_token(uuid.uuid4(), uuid.uuid4(), 3600)

        self.assertIsNone(verify_access_token(token))


class ExecutionTokenActorTests(unittest.IsolatedAsyncioTestCase):
    async def _validate(self, workflow, token: str, actor):
        db = AsyncMock()
        # First execute(): the un-revoked token row. Second: the actor lookup.
        db.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(jti=uuid.uuid4())),
                SimpleNamespace(scalar_one_or_none=lambda: actor),
            ]
        )
        return await validate_workflow_auth(workflow, _request(token), None, db)

    async def test_token_runs_as_its_minter_not_the_owner(self) -> None:
        owner_id = uuid.uuid4()
        collaborator_id = uuid.uuid4()
        workflow = _workflow(owner_id)
        token, _jti, _exp = create_workflow_execution_token(collaborator_id, workflow.id, 3600)
        collaborator = SimpleNamespace(id=collaborator_id)

        actor = await self._validate(workflow, token, collaborator)

        # The endpoint does `current_user.id if current_user else workflow.owner_id`, so a
        # non-None actor here is exactly what keeps the run off the owner's credentials.
        self.assertIsNotNone(actor)
        self.assertEqual(actor.id, collaborator_id)
        self.assertNotEqual(actor.id, owner_id)

    async def test_token_for_a_deleted_user_is_rejected_not_downgraded(self) -> None:
        workflow = _workflow(uuid.uuid4())
        token, _jti, _exp = create_workflow_execution_token(uuid.uuid4(), workflow.id, 3600)

        with self.assertRaises(HTTPException) as ctx:
            await self._validate(workflow, token, None)

        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    async def test_anonymous_workflow_still_runs_as_owner(self) -> None:
        """The public-webhook feature is unchanged: no caller means owner context."""
        workflow = _workflow(uuid.uuid4())
        workflow.auth_type = WorkflowAuthType.anonymous
        db = AsyncMock()

        actor = await validate_workflow_auth(workflow, _request(""), None, db)

        self.assertIsNone(actor)

    async def test_signed_in_user_is_still_the_actor(self) -> None:
        workflow = _workflow(uuid.uuid4())
        caller = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()

        with patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)):
            actor = await validate_workflow_auth(workflow, _request(""), caller, db)

        self.assertIs(actor, caller)


if __name__ == "__main__":
    unittest.main()
