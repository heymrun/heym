"""Authorization tests for team management endpoints (GHSA-vxpw-x7j7-8723).

Team rename and roster changes (update / add member / remove member) must be
restricted to the team creator. These tests lock the creator-only gate so a
non-creator member can no longer seat arbitrary accounts into a team or evict
other members.
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, status

from app.api.teams import add_team_member, remove_team_member, update_team
from app.models.schemas import TeamMemberAddRequest, TeamUpdate


def _result(*, scalar=None, scalar_one=None, all_rows=None) -> MagicMock:
    m = MagicMock()
    m.scalar_one_or_none = MagicMock(return_value=scalar_one)
    m.scalar = MagicMock(return_value=scalar)
    m.all = MagicMock(return_value=all_rows or [])
    return m


def _db(execute_results: list) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_results)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _team(creator_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Team",
        description=None,
        creator_id=creator_id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class TeamMemberAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_creator_cannot_update_team(self) -> None:
        creator_id = uuid.uuid4()
        member = SimpleNamespace(id=uuid.uuid4(), email="m@x", name="M")
        team = _team(creator_id)
        db = _db([_result(scalar_one=team)])

        with self.assertRaises(HTTPException) as ctx:
            await update_team(team.id, TeamUpdate(name="hijack"), db=db, current_user=member)

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        db.commit.assert_not_called()

    async def test_non_creator_cannot_add_member(self) -> None:
        creator_id = uuid.uuid4()
        member = SimpleNamespace(id=uuid.uuid4(), email="m@x", name="M")
        team = _team(creator_id)
        db = _db([_result(scalar_one=team)])

        with self.assertRaises(HTTPException) as ctx:
            await add_team_member(
                team.id,
                TeamMemberAddRequest(email="attacker@example.com"),
                db=db,
                current_user=member,
            )

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        db.add.assert_not_called()
        db.commit.assert_not_called()
        # The attacker lookup by email must never run once authorization fails.
        self.assertEqual(db.execute.await_count, 1)

    async def test_non_creator_cannot_remove_other_member(self) -> None:
        creator_id = uuid.uuid4()
        member = SimpleNamespace(id=uuid.uuid4(), email="m@x", name="M")
        victim_id = uuid.uuid4()
        team = _team(creator_id)
        db = _db([_result(scalar_one=team)])

        with self.assertRaises(HTTPException) as ctx:
            await remove_team_member(team.id, victim_id, db=db, current_user=member)

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        db.delete.assert_not_called()
        db.commit.assert_not_called()

    async def test_creator_cannot_be_removed(self) -> None:
        creator = SimpleNamespace(id=uuid.uuid4(), email="c@x", name="C")
        team = _team(creator.id)
        db = _db([_result(scalar_one=team)])

        with self.assertRaises(HTTPException) as ctx:
            await remove_team_member(team.id, creator.id, db=db, current_user=creator)

        self.assertEqual(ctx.exception.status_code, status.HTTP_400_BAD_REQUEST)
        db.delete.assert_not_called()

    async def test_non_member_gets_404(self) -> None:
        outsider = SimpleNamespace(id=uuid.uuid4(), email="o@x", name="O")
        db = _db([_result(scalar_one=None)])

        with self.assertRaises(HTTPException) as ctx:
            await add_team_member(
                uuid.uuid4(),
                TeamMemberAddRequest(email="outsider@example.com"),
                db=db,
                current_user=outsider,
            )

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_member_cannot_remove_self(self) -> None:
        # Member roster changes are creator-only. Leaving a team is intentionally
        # not exposed on this endpoint (its response returns team detail, which a
        # departed member can no longer read); a dedicated leave flow can add it.
        creator_id = uuid.uuid4()
        member = SimpleNamespace(id=uuid.uuid4(), email="m@x", name="M")
        team = _team(creator_id)
        db = _db([_result(scalar_one=team)])

        with self.assertRaises(HTTPException) as ctx:
            await remove_team_member(team.id, member.id, db=db, current_user=member)

        self.assertEqual(ctx.exception.status_code, status.HTTP_403_FORBIDDEN)
        db.delete.assert_not_called()
        db.commit.assert_not_called()

    async def test_creator_can_update_team(self) -> None:
        creator = SimpleNamespace(id=uuid.uuid4(), email="c@x", name="C")
        team = _team(creator.id)
        db = _db(
            [
                _result(scalar_one=team),
                _result(scalar=1),
                _result(scalar_one=creator),
            ]
        )

        result = await update_team(team.id, TeamUpdate(name="Renamed"), db=db, current_user=creator)

        self.assertEqual(result.name, "Renamed")
        db.commit.assert_awaited_once()

    async def test_creator_can_remove_member(self) -> None:
        creator = SimpleNamespace(id=uuid.uuid4(), email="c@x", name="C")
        victim_id = uuid.uuid4()
        team = _team(creator.id)
        member_row = SimpleNamespace(id=uuid.uuid4())
        db = _db([_result(scalar_one=team), _result(scalar_one=member_row)])

        sentinel = object()
        with patch("app.api.teams.get_team", new=AsyncMock(return_value=sentinel)):
            result = await remove_team_member(team.id, victim_id, db=db, current_user=creator)

        self.assertIs(result, sentinel)
        db.delete.assert_awaited_once_with(member_row)

    async def test_creator_can_add_member(self) -> None:
        creator = SimpleNamespace(id=uuid.uuid4(), email="c@x", name="C")
        team = _team(creator.id)
        new_user = SimpleNamespace(id=uuid.uuid4(), email="new@example.com", name="N")
        db = _db(
            [
                _result(scalar_one=team),
                _result(scalar_one=new_user),
                _result(scalar_one=None),
            ]
        )

        sentinel = object()
        with patch("app.api.teams.get_team", new=AsyncMock(return_value=sentinel)):
            result = await add_team_member(
                team.id,
                TeamMemberAddRequest(email="new@example.com"),
                db=db,
                current_user=creator,
            )

        self.assertIs(result, sentinel)
        db.add.assert_called_once()
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
