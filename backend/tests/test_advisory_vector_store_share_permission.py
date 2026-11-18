"""Vector store shares carry read or write, and a read share never changes a store.

Runs against real PostgreSQL. Covers the access helper, the routes, and the RAG node lookup
for owners, direct and team shares of either level, a user in two teams, and a stranger.
"""

import io
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, UploadFile
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
from app.db.session import SessionLocal
from app.models.schemas import VectorStoreShareRequest, VectorStoreTeamShareRequest
from app.services.vector_store_access import (
    get_vector_store_with_permission,
    vector_store_access_rows,
)
from app.services.workflow_executor import WorkflowExecutor


class VectorStoreSharePermissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")

        def user(name: str) -> User:
            return User(email=f"{name}-{uuid.uuid4()}@example.com", hashed_password="x", name=name)

        self.users = {
            name: user(name)
            for name in (
                "owner",
                "reader",
                "writer",
                "team_reader",
                "two_teams",
                "mixed",
                "stranger",
            )
        }
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add_all(self.users.values())
            await db.flush()
            owner = self.users["owner"]
            self.credential = Credential(
                owner_id=owner.id,
                name="Store",
                type=CredentialType.qdrant,
                encrypted_config="x",
            )
            db.add(self.credential)
            self.read_team = Team(name=f"read-{uuid.uuid4()}", creator_id=owner.id)
            self.write_team = Team(name=f"write-{uuid.uuid4()}", creator_id=owner.id)
            self.spare_team = Team(name=f"spare-{uuid.uuid4()}", creator_id=owner.id)
            db.add_all([self.read_team, self.write_team, self.spare_team])
            await db.flush()
            db.add_all(
                [
                    TeamMember(team_id=self.read_team.id, user_id=self.users["team_reader"].id),
                    TeamMember(team_id=self.read_team.id, user_id=self.users["two_teams"].id),
                    TeamMember(team_id=self.write_team.id, user_id=self.users["two_teams"].id),
                    TeamMember(team_id=self.write_team.id, user_id=self.users["mixed"].id),
                    TeamMember(team_id=self.spare_team.id, user_id=owner.id),
                ]
            )
            self.store = VectorStore(
                name=f"store-{uuid.uuid4()}",
                collection_name=f"col-{uuid.uuid4()}",
                owner_id=owner.id,
                credential_id=self.credential.id,
            )
            db.add(self.store)
            await db.flush()
            db.add_all(
                [
                    VectorStoreShare(
                        vector_store_id=self.store.id,
                        user_id=self.users["reader"].id,
                        permission="read",
                    ),
                    VectorStoreShare(
                        vector_store_id=self.store.id,
                        user_id=self.users["writer"].id,
                        permission="write",
                    ),
                    VectorStoreShare(
                        vector_store_id=self.store.id,
                        user_id=self.users["mixed"].id,
                        permission="read",
                    ),
                    VectorStoreTeamShare(
                        vector_store_id=self.store.id,
                        team_id=self.read_team.id,
                        permission="read",
                    ),
                    VectorStoreTeamShare(
                        vector_store_id=self.store.id,
                        team_id=self.write_team.id,
                        permission="write",
                    ),
                ]
            )
            await db.commit()
        self.expected = {
            "owner": "owner",
            "reader": "read",
            "writer": "write",
            "team_reader": "read",
            "two_teams": "write",
            "mixed": "write",
        }

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(
                delete(VectorStoreShare).where(VectorStoreShare.vector_store_id == self.store.id)
            )
            await db.execute(
                delete(VectorStoreTeamShare).where(
                    VectorStoreTeamShare.vector_store_id == self.store.id
                )
            )
            await db.execute(delete(VectorStore).where(VectorStore.id == self.store.id))
            team_ids = [self.read_team.id, self.write_team.id, self.spare_team.id]
            await db.execute(delete(TeamMember).where(TeamMember.team_id.in_(team_ids)))
            await db.execute(delete(Team).where(Team.id.in_(team_ids)))
            await db.execute(delete(Credential).where(Credential.id == self.credential.id))
            user_ids = [user.id for user in self.users.values()]
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()
        await self.engine.dispose()

    async def _user(self, db: AsyncSession, name: str) -> User:
        return (await db.execute(select(User).where(User.id == self.users[name].id))).scalar_one()

    async def test_a_share_saved_without_a_permission_is_read(self) -> None:
        async with AsyncSession(self.engine) as db:
            stranger = self.users["stranger"].id
            await db.execute(
                text(
                    "INSERT INTO vector_store_shares (id, vector_store_id, user_id) "
                    "VALUES (:id, :store, :user)"
                ),
                {"id": uuid.uuid4(), "store": self.store.id, "user": stranger},
            )
            await db.execute(
                text(
                    "INSERT INTO vector_store_team_shares (id, vector_store_id, team_id) "
                    "VALUES (:id, :store, :team)"
                ),
                {"id": uuid.uuid4(), "store": self.store.id, "team": self.spare_team.id},
            )
            await db.commit()
            permissions = (
                await db.execute(
                    text(
                        "SELECT permission FROM vector_store_shares "
                        "WHERE vector_store_id = :store AND user_id = :user "
                        "UNION ALL SELECT permission FROM vector_store_team_shares "
                        "WHERE vector_store_id = :store AND team_id = :team"
                    ),
                    {"store": self.store.id, "user": stranger, "team": self.spare_team.id},
                )
            ).scalars()
            self.assertEqual(list(permissions), ["read", "read"])
            reached = await get_vector_store_with_permission(db, self.store.id, stranger)
        self.assertEqual(reached[1], "read")

    async def test_access_rows_and_single_lookup_agree_on_the_strongest_grant(self) -> None:
        async with AsyncSession(self.engine) as db:
            for name, permission in self.expected.items():
                user_id = self.users[name].id
                rows = (await db.execute(vector_store_access_rows(user_id))).all()
                store_rows = [row for row in rows if row.vector_store_id == self.store.id]
                self.assertEqual(len(store_rows), 1, name)
                self.assertEqual(store_rows[0].permission, permission, name)
                self.assertEqual(
                    store_rows[0].grant, "owner" if name == "owner" else "shared", name
                )
                reached = await get_vector_store_with_permission(db, self.store.id, user_id)
                self.assertEqual(reached[1], permission, name)
            stranger = self.users["stranger"].id
            self.assertIsNone(await get_vector_store_with_permission(db, self.store.id, stranger))
            rows = (await db.execute(vector_store_access_rows(stranger))).all()
            self.assertNotIn(self.store.id, [row.vector_store_id for row in rows])

    async def test_the_list_and_get_routes_report_the_same_permission(self) -> None:
        async with AsyncSession(self.engine) as db:
            with (
                patch.object(vs_api, "_get_store_stats", AsyncMock(return_value=None)),
                patch.object(vs_api, "_store_backend", AsyncMock(return_value="qdrant")),
            ):
                for name, permission in self.expected.items():
                    user = await self._user(db, name)
                    listed = await vs_api.list_vector_stores(current_user=user, db=db)
                    shown = [item for item in listed if item.id == self.store.id]
                    self.assertEqual([item.permission for item in shown], [permission], name)
                    got = await vs_api.get_vector_store(self.store.id, current_user=user, db=db)
                    self.assertEqual(got.permission, permission, name)

    async def test_a_read_share_cannot_change_documents(self) -> None:
        service_factory = Mock()
        enqueue = AsyncMock()
        async with AsyncSession(self.engine) as db:
            with (
                patch.object(vs_api, "get_vector_store_service_from_config", service_factory),
                patch.object(vs_api.rag_ingest_jobs, "enqueue", enqueue),
                patch.object(vs_api.rag_ingest_jobs, "dismiss", AsyncMock()),
            ):
                for name in ("reader", "team_reader"):
                    user = await self._user(db, name)
                    calls = (
                        vs_api.upload_file_to_vector_store(
                            self.store.id,
                            file=UploadFile(file=io.BytesIO(b"notes"), filename="a.txt"),
                            override_duplicates=False,
                            current_user=user,
                            db=db,
                        ),
                        vs_api.delete_items_by_source(
                            self.store.id, source="a.txt", current_user=user, db=db
                        ),
                        vs_api.delete_item(self.store.id, point_id="p1", current_user=user, db=db),
                        vs_api.dismiss_ingest_job(
                            self.store.id, job_id=uuid.uuid4(), current_user=user, db=db
                        ),
                    )
                    for call in calls:
                        with self.assertRaises(HTTPException) as raised:
                            await call
                        self.assertEqual(raised.exception.status_code, 403, name)
        service_factory.assert_not_called()
        enqueue.assert_not_called()

    async def test_a_write_share_deletes_documents(self) -> None:
        service = Mock()
        async with AsyncSession(self.engine) as db:
            with (
                patch.object(
                    vs_api, "get_vector_store_service_from_config", Mock(return_value=service)
                ),
                patch.object(vs_api, "decrypt_config", Mock(return_value={})),
            ):
                for name in ("writer", "two_teams", "mixed"):
                    user = await self._user(db, name)
                    await vs_api.delete_items_by_source(
                        self.store.id, source="a.txt", current_user=user, db=db
                    )
                    await vs_api.delete_item(self.store.id, point_id="p1", current_user=user, db=db)
        self.assertEqual(service.delete_by_source.call_count, 3)
        self.assertEqual(service.delete_point.call_count, 3)

    async def test_a_write_share_cannot_manage_the_store_or_its_shares(self) -> None:
        async with AsyncSession(self.engine) as db:
            writer = await self._user(db, "writer")
            stranger = self.users["stranger"]
            calls = (
                vs_api.update_vector_store(
                    self.store.id,
                    vs_api.VectorStoreUpdate(name="renamed"),
                    current_user=writer,
                    db=db,
                ),
                vs_api.delete_vector_store(self.store.id, current_user=writer, db=db),
                vs_api.list_vector_store_shares(self.store.id, current_user=writer, db=db),
                vs_api.create_vector_store_share(
                    self.store.id,
                    VectorStoreShareRequest(email=stranger.email, permission="write"),
                    current_user=writer,
                    db=db,
                ),
                vs_api.delete_vector_store_share(
                    self.store.id, self.users["reader"].id, current_user=writer, db=db
                ),
                vs_api.list_vector_store_team_shares(self.store.id, current_user=writer, db=db),
                vs_api.create_vector_store_team_share(
                    self.store.id,
                    VectorStoreTeamShareRequest(team_id=self.spare_team.id, permission="write"),
                    current_user=writer,
                    db=db,
                ),
            )
            for call in calls:
                with self.assertRaises(HTTPException) as raised:
                    await call
                self.assertEqual(raised.exception.status_code, 404)
            stored = (
                await db.execute(select(VectorStore).where(VectorStore.id == self.store.id))
            ).scalar_one()
            self.assertEqual(stored.name, self.store.name)
            self.assertIsNone(
                (
                    await db.execute(
                        select(VectorStoreShare).where(
                            VectorStoreShare.vector_store_id == self.store.id,
                            VectorStoreShare.user_id == stranger.id,
                        )
                    )
                ).scalar_one_or_none()
            )

    async def test_the_owner_sets_and_changes_a_share_permission(self) -> None:
        audit = Mock()
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            owner = await self._user(db, "owner")
            stranger = self.users["stranger"]
            with patch.object(vs_api, "audit", audit):
                added = await vs_api.create_vector_store_share(
                    self.store.id,
                    VectorStoreShareRequest(email=stranger.email, permission="write"),
                    current_user=owner,
                    db=db,
                )
                self.assertEqual(added.permission, "write")
                lowered = await vs_api.create_vector_store_share(
                    self.store.id,
                    VectorStoreShareRequest(email=stranger.email, permission="read"),
                    current_user=owner,
                    db=db,
                )
                self.assertEqual((lowered.id, lowered.permission), (added.id, "read"))
                team = await vs_api.create_vector_store_team_share(
                    self.store.id,
                    VectorStoreTeamShareRequest(team_id=self.spare_team.id),
                    current_user=owner,
                    db=db,
                )
                self.assertEqual(team.permission, "read")
                raised = await vs_api.create_vector_store_team_share(
                    self.store.id,
                    VectorStoreTeamShareRequest(team_id=self.spare_team.id, permission="write"),
                    current_user=owner,
                    db=db,
                )
                self.assertEqual((raised.id, raised.permission), (team.id, "write"))
            await db.commit()
            shares = await vs_api.list_vector_store_shares(self.store.id, current_user=owner, db=db)
            self.assertIn((stranger.id, "read"), [(s.user_id, s.permission) for s in shares])
            team_shares = await vs_api.list_vector_store_team_shares(
                self.store.id, current_user=owner, db=db
            )
            self.assertIn(
                (self.spare_team.id, "write"), [(s.team_id, s.permission) for s in team_shares]
            )
            reached = await get_vector_store_with_permission(db, self.store.id, stranger.id)
            self.assertEqual(reached[1], "read")
        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertEqual(
            actions,
            [
                "vector_store.share_add",
                "vector_store.share_update",
                "vector_store.team_share_add",
                "vector_store.team_share_update",
            ],
        )

    def test_the_rag_node_needs_write_to_change_documents(self) -> None:
        def lookup(name: str, operation: str) -> object:
            executor = WorkflowExecutor(nodes=[], edges=[], actor_user_id=self.users[name].id)
            with SessionLocal() as db:
                return executor._get_accessible_vector_store(db, self.store.id, operation)

        for name in ("reader", "team_reader"):
            self.assertEqual(lookup(name, "search").id, self.store.id)
            for operation in ("insert", "upsert", "delete"):
                with self.assertRaisesRegex(ValueError, "Write access required"):
                    lookup(name, operation)
        for name in ("owner", "writer", "two_teams", "mixed"):
            for operation in ("search", "insert", "upsert", "delete"):
                self.assertEqual(lookup(name, operation).id, self.store.id, (name, operation))
        for operation in ("search", "insert"):
            self.assertIsNone(lookup("stranger", operation))


if __name__ == "__main__":
    unittest.main()
