"""global_variable_access agrees with the variable list for owners, direct and team shares."""

import unittest
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import global_variables as gv_api
from app.config import settings
from app.db.models import (
    GlobalVariable,
    GlobalVariableShare,
    GlobalVariableTeamShare,
    Team,
    TeamMember,
    User,
)
from app.services.global_variable_access import (
    get_global_variable_with_grant,
    global_variable_access_rows,
)


class GlobalVariableAccessPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.owner = User(
            email=f"owner-{uuid.uuid4()}@example.com", hashed_password="x", name="Owner"
        )
        self.member = User(
            email=f"member-{uuid.uuid4()}@example.com", hashed_password="x", name="Member"
        )
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add_all([self.owner, self.member])
            await db.flush()
            team = Team(name="T", creator_id=self.owner.id)
            db.add(team)
            await db.flush()
            db.add(TeamMember(team_id=team.id, user_id=self.member.id))
            self.variables = {
                name: GlobalVariable(
                    owner_id=owner.id,
                    name=f"{name}_{uuid.uuid4().hex[:8]}",
                    value={"v": 1},
                    value_type="number",
                )
                for name, owner in [
                    ("own", self.member),
                    ("direct", self.owner),
                    ("team", self.owner),
                    ("unshared", self.owner),
                ]
            }
            db.add_all(self.variables.values())
            await db.flush()
            db.add_all(
                [
                    GlobalVariableShare(
                        global_variable_id=self.variables["direct"].id, user_id=self.member.id
                    ),
                    GlobalVariableTeamShare(
                        global_variable_id=self.variables["team"].id, team_id=team.id
                    ),
                ]
            )
            await db.commit()
            self.team_id = team.id
        self.expected = {
            self.variables["own"].id: "owner",
            self.variables["direct"].id: "shared",
            self.variables["team"].id: "shared",
        }

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            ids = [v.id for v in self.variables.values()]
            await db.execute(
                delete(GlobalVariableShare).where(GlobalVariableShare.global_variable_id.in_(ids))
            )
            await db.execute(
                delete(GlobalVariableTeamShare).where(
                    GlobalVariableTeamShare.global_variable_id.in_(ids)
                )
            )
            await db.execute(delete(GlobalVariable).where(GlobalVariable.id.in_(ids)))
            await db.execute(delete(TeamMember).where(TeamMember.team_id == self.team_id))
            await db.execute(delete(Team).where(Team.id == self.team_id))
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.member.id])))
            await db.commit()
        await self.engine.dispose()

    async def test_access_rows_hold_one_grant_per_variable(self) -> None:
        async with AsyncSession(self.engine) as db:
            rows = (await db.execute(global_variable_access_rows(self.member.id))).all()
        self.assertEqual({row.global_variable_id: row.grant for row in rows}, self.expected)

    async def test_single_variable_check_matches_the_rows(self) -> None:
        async with AsyncSession(self.engine) as db:
            for variable_id, grant in self.expected.items():
                reached = await get_global_variable_with_grant(db, variable_id, self.member.id)
                self.assertIsNotNone(reached)
                self.assertEqual(reached[1], grant)
            unshared = self.variables["unshared"].id
            self.assertIsNone(await get_global_variable_with_grant(db, unshared, self.member.id))

    async def test_the_list_endpoint_shows_the_same_variables(self) -> None:
        async with AsyncSession(self.engine) as db:
            member = (await db.execute(select(User).where(User.id == self.member.id))).scalar_one()
            listed = await gv_api.list_global_variables(current_user=member, db=db)
        shown = {item.id: ("shared" if item.is_shared else "owner") for item in listed}
        self.assertEqual(shown, self.expected)
