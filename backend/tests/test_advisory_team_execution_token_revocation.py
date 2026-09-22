"""GHSA-pwr6-6377-3cgv follow-up: a team change must not leave a stale execution token.

Removing a member from a team, or deleting the team outright, could previously leave that
member's workflow execution tokens usable: only the direct share/team-share removal
endpoints revoked tokens, and a team change never did. That also meant re-adding the member
(or, worse, a fresh team reusing the same workflow shares) silently made the old token work
again, since nothing had ever flipped it to ``revoked``.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.teams import delete_team, remove_team_member


def _team(creator_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), name="Team", creator_id=creator_id)


class TeamChangeRevokesStaleExecutionTokensTests(unittest.IsolatedAsyncioTestCase):
    async def test_member_removal_revokes_their_token_on_a_team_shared_workflow(self) -> None:
        creator = SimpleNamespace(id=uuid.uuid4())
        team = _team(creator.id)
        removed_user_id = uuid.uuid4()
        member_row = SimpleNamespace()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="wf")
        token = SimpleNamespace(user_id=removed_user_id, revoked=False)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: team),  # _get_team_for_member
                SimpleNamespace(scalar_one_or_none=lambda: member_row),  # TeamMember lookup
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [workflow.id])
                ),  # WorkflowTeamShare.workflow_id, captured before the delete
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [workflow])
                ),  # Workflow lookup by id, inside the revoke helper
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [token])
                ),  # WorkflowExecutionToken lookup for that workflow
            ]
        )
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        with (
            patch(
                "app.services.workflow_access.user_has_workflow_access",
                AsyncMock(return_value=False),
            ),
            patch("app.api.teams.get_team", AsyncMock(return_value="ignored")),
        ):
            await remove_team_member(team.id, removed_user_id, db=db, current_user=creator)

        self.assertTrue(token.revoked)
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_deleting_the_team_revokes_tokens_before_the_share_rows_cascade_away(
        self,
    ) -> None:
        """WorkflowTeamShare rows cascade-delete with the team, so the affected workflow
        ids must be captured before ``db.delete(team)`` is flushed, not queried after."""
        creator = SimpleNamespace(id=uuid.uuid4())
        team = _team(creator.id)
        member_user_id = uuid.uuid4()
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), name="wf")
        token = SimpleNamespace(user_id=member_user_id, revoked=False)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: team),  # Team lookup
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [workflow.id])
                ),  # WorkflowTeamShare.workflow_id, captured before delete cascades
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [workflow])
                ),  # Workflow lookup by id, inside the revoke helper
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [token])
                ),  # WorkflowExecutionToken lookup for that workflow
            ]
        )
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        with patch(
            "app.services.workflow_access.user_has_workflow_access",
            AsyncMock(return_value=False),
        ):
            await delete_team(team.id, db=db, current_user=creator)

        self.assertTrue(token.revoked)
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
