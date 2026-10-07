"""data_table_access agrees with the data table list for owners, direct and team shares."""

import unittest
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import data_tables as dt_api
from app.config import settings
from app.db.models import DataTable, DataTableShare, DataTableTeamShare, Team, TeamMember, User
from app.services.data_table_access import (
    data_table_access_rows,
    get_data_table_with_permission,
)


class DataTableAccessPostgresTests(unittest.IsolatedAsyncioTestCase):
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
            team_x = Team(name="X", creator_id=self.owner.id)
            team_y = Team(name="Y", creator_id=self.owner.id)
            db.add_all([team_x, team_y])
            await db.flush()
            db.add_all(
                [
                    TeamMember(team_id=team_x.id, user_id=self.member.id),
                    TeamMember(team_id=team_y.id, user_id=self.member.id),
                ]
            )
            self.tables = {
                name: DataTable(name=f"{name}-{uuid.uuid4()}", columns=[], owner_id=owner_id)
                for name, owner_id in [
                    ("direct_read_team_write", self.owner.id),
                    ("own", self.member.id),
                    ("two_team_reads", self.owner.id),
                    ("unshared", self.owner.id),
                    ("direct_write_team_read", self.owner.id),
                ]
            }
            db.add_all(self.tables.values())
            await db.flush()
            t = {name: table.id for name, table in self.tables.items()}
            db.add_all(
                [
                    DataTableShare(
                        table_id=t["direct_read_team_write"],
                        user_id=self.member.id,
                        permission="read",
                    ),
                    DataTableTeamShare(
                        table_id=t["direct_read_team_write"], team_id=team_x.id, permission="write"
                    ),
                    DataTableTeamShare(
                        table_id=t["two_team_reads"], team_id=team_x.id, permission="read"
                    ),
                    DataTableTeamShare(
                        table_id=t["two_team_reads"], team_id=team_y.id, permission="read"
                    ),
                    DataTableShare(
                        table_id=t["direct_write_team_read"],
                        user_id=self.member.id,
                        permission="write",
                    ),
                    DataTableTeamShare(
                        table_id=t["direct_write_team_read"], team_id=team_y.id, permission="read"
                    ),
                ]
            )
            await db.commit()
            self.team_ids = [team_x.id, team_y.id]
        self.expected = {
            self.tables["direct_read_team_write"].id: "write",
            self.tables["own"].id: "owner",
            self.tables["two_team_reads"].id: "read",
            self.tables["direct_write_team_read"].id: "write",
        }

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            ids = [table.id for table in self.tables.values()]
            await db.execute(delete(DataTableShare).where(DataTableShare.table_id.in_(ids)))
            await db.execute(delete(DataTableTeamShare).where(DataTableTeamShare.table_id.in_(ids)))
            await db.execute(delete(DataTable).where(DataTable.id.in_(ids)))
            await db.execute(delete(TeamMember).where(TeamMember.team_id.in_(self.team_ids)))
            await db.execute(delete(Team).where(Team.id.in_(self.team_ids)))
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.member.id])))
            await db.commit()
        await self.engine.dispose()

    async def test_access_rows_hold_the_strongest_grant_per_table(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            rows = (await db.execute(data_table_access_rows(self.member.id))).all()
        self.assertEqual({row.table_id: row.permission for row in rows}, self.expected)

    async def test_single_table_check_matches_the_rows(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            for table_id, permission in self.expected.items():
                reached = await get_data_table_with_permission(db, table_id, self.member.id)
                self.assertIsNotNone(reached)
                self.assertEqual(reached[1], permission)
            unshared = self.tables["unshared"].id
            self.assertIsNone(await get_data_table_with_permission(db, unshared, self.member.id))

    async def test_the_list_endpoint_shows_the_same_tables_and_permissions(self) -> None:
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            member = (await db.execute(select(User).where(User.id == self.member.id))).scalar_one()
            listed = await dt_api.list_data_tables(current_user=member, db=db)
        shown = {item.id: (item.permission if item.is_shared else "owner") for item in listed}
        self.assertEqual({tid: shown[tid] for tid in self.expected}, self.expected)
        self.assertNotIn(self.tables["unshared"].id, shown)
