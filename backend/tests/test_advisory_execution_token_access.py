"""GHSA-pwr6-6377-3cgv: an execution token must not outlive its minter's access.

A collaborator can mint a scoped execution token for a shared workflow. Validation used to
check the signature, the workflow id, the ``revoked`` flag and that the minting user exists,
but never that the user could still reach the workflow. Removing a share left the token
working for its full lifetime, up to ten years.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, status

from app.api.workflows import (
    remove_workflow_share,
    remove_workflow_team_share,
    validate_workflow_auth,
)
from app.models.schemas import WorkflowAuthType
from app.services.auth import create_workflow_execution_token
from app.services.workflow_access import revoke_execution_tokens_without_access


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


def _db_for_token(actor: SimpleNamespace | None) -> AsyncMock:
    """First execute(): the unrevoked token row. Second: the minting user lookup."""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(jti=uuid.uuid4())),
            SimpleNamespace(scalar_one_or_none=lambda: actor),
        ]
    )
    return db


class ExecutionTokenAccessRecheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_token_is_rejected_once_minter_lost_access(self) -> None:
        workflow = _workflow(uuid.uuid4())
        minter = SimpleNamespace(id=uuid.uuid4())
        token, _jti, _exp = create_workflow_execution_token(minter.id, workflow.id, 315360000)

        with patch(
            "app.api.workflows.user_has_workflow_access", AsyncMock(return_value=False)
        ) as access:
            with self.assertRaises(HTTPException) as ctx:
                await validate_workflow_auth(workflow, _request(token), None, _db_for_token(minter))

        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)
        access.assert_awaited_once()
        self.assertEqual(access.await_args.args[2], minter.id)

    async def test_token_is_accepted_while_minter_has_access(self) -> None:
        workflow = _workflow(uuid.uuid4())
        minter = SimpleNamespace(id=uuid.uuid4())
        token, _jti, _exp = create_workflow_execution_token(minter.id, workflow.id, 3600)

        with patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)):
            actor = await validate_workflow_auth(
                workflow, _request(token), None, _db_for_token(minter)
            )

        self.assertIs(actor, minter)

    async def test_token_minted_by_user_who_never_had_access_is_rejected(self) -> None:
        workflow = _workflow(uuid.uuid4())
        stranger = SimpleNamespace(id=uuid.uuid4())
        token, _jti, _exp = create_workflow_execution_token(stranger.id, workflow.id, 3600)

        with patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=False)):
            with self.assertRaises(HTTPException) as ctx:
                await validate_workflow_auth(
                    workflow, _request(token), None, _db_for_token(stranger)
                )

        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)


class RevokeTokensWithoutAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_tokens_of_users_without_access_are_revoked(self) -> None:
        workflow = _workflow(uuid.uuid4())
        kept_user = uuid.uuid4()
        removed_user = uuid.uuid4()
        kept = SimpleNamespace(user_id=kept_user, revoked=False)
        removed = SimpleNamespace(user_id=removed_user, revoked=False)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [kept, removed])
            )
        )

        async def has_access(_db, _workflow, user_id: uuid.UUID) -> bool:
            return user_id == kept_user

        with patch("app.services.workflow_access.user_has_workflow_access", side_effect=has_access):
            await revoke_execution_tokens_without_access(db, workflow)

        self.assertFalse(kept.revoked)
        self.assertTrue(removed.revoked)


class ShareRemovalRevokesTokensEndToEndTests(unittest.IsolatedAsyncioTestCase):
    """Runs the real removal endpoints, not a mocked stand-in for them.

    Only ``user_has_workflow_access`` is stubbed, at the module it is actually called from
    (``app.services.workflow_access``), so the endpoint's own control flow, the
    flush-before-revoke ordering, and ``revoke_execution_tokens_without_access`` all run for
    real.
    """

    async def test_user_share_removal_revokes_only_the_removed_users_token(self) -> None:
        owner_id = uuid.uuid4()
        removed_user_id = uuid.uuid4()
        other_user_id = uuid.uuid4()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=owner_id, name="wf")
        share = SimpleNamespace()
        removed_token = SimpleNamespace(user_id=removed_user_id, revoked=False)
        other_token = SimpleNamespace(user_id=other_user_id, revoked=False)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: workflow),  # get_workflow_for_user
                SimpleNamespace(scalar_one_or_none=lambda: share),  # WorkflowShare lookup
                SimpleNamespace(  # WorkflowExecutionToken lookup, inside the revoke helper
                    scalars=lambda: SimpleNamespace(all=lambda: [removed_token, other_token])
                ),
            ]
        )
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        async def has_access(_db, _workflow, user_id: uuid.UUID) -> bool:
            return user_id != removed_user_id

        with patch("app.services.workflow_access.user_has_workflow_access", side_effect=has_access):
            await remove_workflow_share(
                workflow.id,
                user_id=removed_user_id,
                current_user=SimpleNamespace(id=owner_id),
                db=db,
            )

        self.assertTrue(removed_token.revoked)
        self.assertFalse(other_token.revoked)
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_team_share_removal_discriminates_between_two_token_holders(self) -> None:
        """The multi-team case, with both outcomes in the same call.

        A token holder reachable only through the team share being removed loses access and
        must be revoked. A second token holder reachable through a different team must not
        be touched. Asserting only the kept token stays unrevoked (as an earlier version of
        this test did) also passes if the revocation helper never runs at all, so this
        exercises both sides in the same removal to prove the helper actually discriminates.
        """
        owner_id = uuid.uuid4()
        member_of_two_teams = uuid.uuid4()
        member_of_only_this_team = uuid.uuid4()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=owner_id, name="wf")
        team_share = SimpleNamespace()
        kept_token = SimpleNamespace(user_id=member_of_two_teams, revoked=False)
        lost_token = SimpleNamespace(user_id=member_of_only_this_team, revoked=False)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: workflow),
                SimpleNamespace(scalar_one_or_none=lambda: team_share),
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [kept_token, lost_token])
                ),
            ]
        )
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        async def has_access(_db, _workflow, user_id: uuid.UUID) -> bool:
            # Reachable through the other team; the removed team was this user's only path.
            return user_id == member_of_two_teams

        with patch("app.services.workflow_access.user_has_workflow_access", side_effect=has_access):
            await remove_workflow_team_share(
                workflow.id,
                team_id=uuid.uuid4(),
                current_user=SimpleNamespace(id=owner_id),
                db=db,
            )

        self.assertFalse(kept_token.revoked)
        self.assertTrue(lost_token.revoked)


if __name__ == "__main__":
    unittest.main()
