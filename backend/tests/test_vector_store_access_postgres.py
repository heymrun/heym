"""vector_store_access agrees with the vector store list for owners, direct and team shares."""

import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import vector_stores as vs_api
from app.config import settings
from app.db.models import (
    Credential,
    CredentialType,
    Team,
    TeamMember,
    User,
    VectorStore,
    VectorStoreShare,
    VectorStoreTeamShare,
)
from app.services.vector_store_access import get_vector_store_with_grant, vector_store_access_rows


class VectorStoreAccessPostgresTests(unittest.IsolatedAsyncioTestCase):
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
            self.credentials = [
                Credential(
                    owner_id=user.id, name="Store", type=CredentialType.openai, encrypted_config="x"
                )
                for user in (self.owner, self.member)
            ]
            db.add_all(self.credentials)
            team = Team(name="T", creator_id=self.owner.id)
            db.add(team)
            await db.flush()
            db.add(TeamMember(team_id=team.id, user_id=self.member.id))

            def store(name: str, owner: User, credential: Credential) -> VectorStore:
                return VectorStore(
                    name=name,
                    collection_name=f"{name}-{uuid.uuid4()}",
                    owner_id=owner.id,
                    credential_id=credential.id,
                )

            self.stores = {
                "own": store("own", self.member, self.credentials[1]),
                "direct": store("direct", self.owner, self.credentials[0]),
                "team": store("team", self.owner, self.credentials[0]),
                "both": store("both", self.owner, self.credentials[0]),
                "unshared": store("unshared", self.owner, self.credentials[0]),
            }
            db.add_all(self.stores.values())
            await db.flush()
            db.add_all(
                [
                    VectorStoreShare(
                        vector_store_id=self.stores["direct"].id, user_id=self.member.id
                    ),
                    VectorStoreTeamShare(vector_store_id=self.stores["team"].id, team_id=team.id),
                    VectorStoreShare(
                        vector_store_id=self.stores["both"].id, user_id=self.member.id
                    ),
                    VectorStoreTeamShare(vector_store_id=self.stores["both"].id, team_id=team.id),
                ]
            )
            await db.commit()
            self.team_id = team.id
        self.expected = {
            self.stores["own"].id: "owner",
            self.stores["direct"].id: "shared",
            self.stores["team"].id: "shared",
            self.stores["both"].id: "shared",
        }

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            ids = [store.id for store in self.stores.values()]
            await db.execute(
                delete(VectorStoreShare).where(VectorStoreShare.vector_store_id.in_(ids))
            )
            await db.execute(
                delete(VectorStoreTeamShare).where(VectorStoreTeamShare.vector_store_id.in_(ids))
            )
            await db.execute(delete(VectorStore).where(VectorStore.id.in_(ids)))
            await db.execute(delete(TeamMember).where(TeamMember.team_id == self.team_id))
            await db.execute(delete(Team).where(Team.id == self.team_id))
            await db.execute(
                delete(Credential).where(Credential.id.in_([c.id for c in self.credentials]))
            )
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.member.id])))
            await db.commit()
        await self.engine.dispose()

    async def test_access_rows_hold_one_grant_per_store(self) -> None:
        async with AsyncSession(self.engine) as db:
            rows = (await db.execute(vector_store_access_rows(self.member.id))).all()
        self.assertEqual({row.vector_store_id: row.grant for row in rows}, self.expected)

    async def test_single_store_check_matches_the_rows(self) -> None:
        async with AsyncSession(self.engine) as db:
            for store_id, grant in self.expected.items():
                reached = await get_vector_store_with_grant(db, store_id, self.member.id)
                self.assertIsNotNone(reached)
                self.assertEqual(reached[1], grant)
            unshared = self.stores["unshared"].id
            self.assertIsNone(await get_vector_store_with_grant(db, unshared, self.member.id))

    async def test_the_list_endpoint_shows_the_same_stores(self) -> None:
        async with AsyncSession(self.engine) as db:
            member = (await db.execute(select(User).where(User.id == self.member.id))).scalar_one()
            with (
                patch.object(vs_api, "_get_store_stats", AsyncMock(return_value=None)),
                patch.object(vs_api, "_store_backend", AsyncMock(return_value="qdrant")),
            ):
                listed = await vs_api.list_vector_stores(current_user=member, db=db)
        shown = {item.id: ("shared" if item.is_shared else "owner") for item in listed}
        self.assertEqual(shown, self.expected)
