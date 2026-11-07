"""Rows (never values) follow the labelled Secrets, on real PostgreSQL.

Requires a migrated PostgreSQL test database, like the other ``*_postgres`` suites.
Each test owns and removes only its random fixture rows.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest import IsolatedAsyncioTestCase

from asyncpg import CannotConnectNowError, PostgresConnectionError
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.db.models import (
    Credential,
    CredentialShare,
    CredentialTeamShare,
    CredentialType,
    Team,
    User,
)
from app.db.session import async_session_maker, engine
from app.services.encryption import encrypt_config
from app.services.k8s_credentials import rows
from app.services.k8s_credentials.store import SecretCredential


class ReconcilePostgresTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await engine.dispose()
        try:
            async with asyncio.timeout(10):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except (OSError, TimeoutError, PostgresConnectionError, CannotConnectNowError) as exc:
            await engine.dispose()
            self.skipTest(f"PostgreSQL is unavailable ({type(exc).__name__})")
        except DBAPIError as exc:
            if not exc.connection_invalidated:
                raise
            await engine.dispose()
            self.skipTest("PostgreSQL connection is unavailable")
        self.suffix = uuid.uuid4().hex[:10]
        self.owner_id, self.alice_id, self.team_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        self.owner_email = f"owner-{self.suffix}@example.com"
        self.alice_email = f"alice-{self.suffix}@example.com"
        self.team_name = f"automation-{self.suffix}"
        async with async_session_maker() as db:
            for user_id, email in (
                (self.owner_id, self.owner_email),
                (self.alice_id, self.alice_email),
            ):
                db.add(User(id=user_id, email=email, hashed_password="test-only", name=email))
            await db.flush()
            db.add(Team(id=self.team_id, name=self.team_name, creator_id=self.owner_id))
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            ids = [self.owner_id, self.alice_id]
            await db.execute(delete(Credential).where(Credential.owner_id.in_(ids)))
            await db.execute(delete(Team).where(Team.id == self.team_id))
            await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()
        await engine.dispose()

    def _item(self, **over: object) -> SecretCredential:
        fields: dict = dict(
            namespace="heym",
            secret_name=f"heym-cred-{self.suffix}",
            name=f"llm-{self.suffix}",
            type="openai",
            owner_email=self.owner_email,
            share_users=(self.alice_email, self.owner_email),
            share_teams=(self.team_name,),
            config={"api_key": "sk-never-stored"},
        )
        fields.update(over)
        return SecretCredential(**fields)

    async def _reconcile(self, items: list[SecretCredential]) -> list[rows.SecretStatus]:
        # reconcile() reports every Secret-backed row in the database. A shared dev
        # database can hold rows from a live run, so keep only this test's Secrets.
        async with async_session_maker() as db:
            statuses = await rows.reconcile(db, items)
        return [s for s in statuses if s.secret_name.endswith(self.suffix)]

    async def _row(self, credential_id: uuid.UUID) -> Credential | None:
        async with async_session_maker() as db:
            return await db.get(Credential, credential_id)

    async def _shares(self, credential_id: uuid.UUID) -> tuple[set, set]:
        async with async_session_maker() as db:
            users = set(
                (
                    await db.execute(
                        select(CredentialShare.user_id).where(
                            CredentialShare.credential_id == credential_id
                        )
                    )
                ).scalars()
            )
            teams = set(
                (
                    await db.execute(
                        select(CredentialTeamShare.team_id).where(
                            CredentialTeamShare.credential_id == credential_id
                        )
                    )
                ).scalars()
            )
        return users, teams

    async def test_a_secret_becomes_a_row_holding_only_its_pointer(self) -> None:
        item = self._item()

        (status,) = await self._reconcile([item])

        row = await self._row(item.credential_id)
        assert row is not None
        self.assertEqual(status.status, rows.STATUS_AVAILABLE)
        self.assertEqual((row.encrypted_config, row.source), (item.pointer, item.pointer))
        self.assertEqual(
            (row.owner_id, row.name, row.type), (self.owner_id, item.name, CredentialType.openai)
        )
        # The owner is never shared with themselves.
        self.assertEqual(await self._shares(item.credential_id), ({self.alice_id}, {self.team_id}))

    async def test_an_unchanged_secret_changes_nothing(self) -> None:
        item = self._item()
        await self._reconcile([item])
        before = await self._row(item.credential_id)

        await self._reconcile([item])

        after = await self._row(item.credential_id)
        assert before is not None and after is not None
        self.assertEqual(after.updated_at, before.updated_at)

    async def test_annotation_changes_rename_and_unshare(self) -> None:
        await self._reconcile([self._item()])

        renamed = self._item(name=f"renamed-{self.suffix}", share_users=(), share_teams=())
        await self._reconcile([renamed])

        row = await self._row(renamed.credential_id)
        assert row is not None
        self.assertEqual(row.name, renamed.name)
        self.assertEqual(await self._shares(renamed.credential_id), (set(), set()))

    async def test_a_deleted_secret_keeps_its_row_and_shares_and_comes_back_whole(self) -> None:
        item = self._item()
        await self._reconcile([item])

        statuses = await self._reconcile([])

        gone = [s for s in statuses if s.credential_id == item.credential_id]
        self.assertEqual([s.status for s in gone], [rows.STATUS_UNAVAILABLE])
        self.assertIsNotNone(await self._row(item.credential_id))

        await self._reconcile([item])
        self.assertEqual(await self._shares(item.credential_id), ({self.alice_id}, {self.team_id}))

    async def test_an_owner_who_has_not_signed_in_is_reported_not_created(self) -> None:
        item = self._item(owner_email=f"nobody-{self.suffix}@example.com")

        (status,) = await self._reconcile([item])

        self.assertEqual(status.status, rows.STATUS_OWNER_MISSING)
        self.assertIsNone(await self._row(item.credential_id))

    async def test_a_ui_credential_with_the_same_name_is_never_taken_over(self) -> None:
        item = self._item()
        ui_id = uuid.uuid4()
        async with async_session_maker() as db:
            db.add(
                Credential(
                    id=ui_id,
                    owner_id=self.owner_id,
                    name=item.name,
                    type=CredentialType.openai,
                    encrypted_config=encrypt_config({"api_key": "ui"}),
                )
            )
            await db.commit()

        (status,) = await self._reconcile([item])

        self.assertEqual(status.status, rows.STATUS_NAME_CONFLICT)
        self.assertIsNone(await self._row(item.credential_id))
        ui_row = await self._row(ui_id)
        assert ui_row is not None
        self.assertIsNone(ui_row.source)

    async def test_an_invalid_secret_is_reported_not_created(self) -> None:
        item = self._item(problem="missing annotation heym.run/type")

        (status,) = await self._reconcile([item])

        self.assertEqual((status.status, status.detail), (rows.STATUS_INVALID, item.problem))
        self.assertIsNone(await self._row(item.credential_id))

    async def test_unknown_share_targets_are_warnings_not_failures(self) -> None:
        item = self._item(
            share_users=(f"ghost-{self.suffix}@example.com",), share_teams=("no-such-team",)
        )

        (status,) = await self._reconcile([item])

        self.assertEqual(status.status, rows.STATUS_AVAILABLE)
        self.assertEqual(len(status.warnings), 2)
