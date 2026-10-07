"""drive_file_access agrees with the Drive list for owned and team-shared files."""

import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import files as files_api
from app.config import settings
from app.db.models import FileTeamShare, GeneratedFile, Team, TeamMember, User
from app.services.drive_file_access import drive_file_access_rows, get_accessible_file


def _file(owner: User, name: str) -> GeneratedFile:
    return GeneratedFile(
        owner_id=owner.id,
        filename=name,
        storage_path=f"/tmp/{uuid.uuid4()}",
        mime_type="text/plain",
        size_bytes=1,
    )


class DriveFileAccessPostgresTests(unittest.IsolatedAsyncioTestCase):
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
            teams = [Team(name=name, creator_id=self.owner.id) for name in ("A", "B")]
            db.add_all(teams)
            await db.flush()
            db.add_all([TeamMember(team_id=team.id, user_id=self.member.id) for team in teams])
            self.files = {
                "own": _file(self.member, "own.txt"),
                "one_team": _file(self.owner, "one.txt"),
                "two_teams": _file(self.owner, "two.txt"),
                "unshared": _file(self.owner, "secret.txt"),
            }
            db.add_all(self.files.values())
            await db.flush()
            db.add_all(
                [
                    FileTeamShare(file_id=self.files["one_team"].id, team_id=teams[0].id),
                    FileTeamShare(file_id=self.files["two_teams"].id, team_id=teams[0].id),
                    FileTeamShare(file_id=self.files["two_teams"].id, team_id=teams[1].id),
                ]
            )
            await db.commit()
            self.team_ids = [team.id for team in teams]
        self.expected = {
            self.files["own"].id: "owner",
            self.files["one_team"].id: "shared",
            self.files["two_teams"].id: "shared",
        }

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            ids = [f.id for f in self.files.values()]
            await db.execute(delete(FileTeamShare).where(FileTeamShare.file_id.in_(ids)))
            await db.execute(delete(GeneratedFile).where(GeneratedFile.id.in_(ids)))
            await db.execute(delete(TeamMember).where(TeamMember.team_id.in_(self.team_ids)))
            await db.execute(delete(Team).where(Team.id.in_(self.team_ids)))
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.member.id])))
            await db.commit()
        await self.engine.dispose()

    async def test_access_rows_hold_one_grant_per_file(self) -> None:
        async with AsyncSession(self.engine) as db:
            rows = (await db.execute(drive_file_access_rows(self.member.id))).all()
        self.assertEqual({row.file_id: row.grant for row in rows}, self.expected)

    async def test_single_file_check_matches_the_rows(self) -> None:
        async with AsyncSession(self.engine) as db:
            for file_id, grant in self.expected.items():
                reached = await get_accessible_file(db, file_id, self.member.id)
                self.assertIsNotNone(reached)
                self.assertEqual("shared" if reached.is_shared else "owner", grant)
            unshared = self.files["unshared"].id
            self.assertIsNone(await get_accessible_file(db, unshared, self.member.id))

    async def test_the_list_endpoint_shows_the_same_files(self) -> None:
        async with AsyncSession(self.engine) as db:
            member = (await db.execute(select(User).where(User.id == self.member.id))).scalar_one()
            with patch.object(files_api, "build_public_base_url", return_value="http://heym.test"):
                listed = await files_api.list_files(
                    request=None, user=member, db=db, limit=50, offset=0
                )
        shown = {item.id: ("shared" if item.is_shared else "owner") for item in listed.files}
        self.assertEqual(shown, self.expected)
