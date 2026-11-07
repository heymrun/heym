"""Re-encryption under the new ENCRYPTION_KEY, on real PostgreSQL in a database of its own."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from sqlalchemy import select

from app.db.models import (
    ENCRYPTION_CANARY_ID,
    SSO_SETTINGS_ID,
    Credential,
    CredentialType,
    EncryptionCanary,
    KeyRotation,
    SsoSettings,
    User,
)
from app.services import encryption, key_rotation
from app.services.cluster import identity
from app.services.cluster.registry import InstanceView
from tests.isolated_postgres import create_isolated_database

OLD = "old-encryption-key-for-tests"
NEW = "new-encryption-key-for-tests"
LOST = "a-key-nobody-has-any-more"
UPDATED = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _keys(primary: str, extra: str = ""):  # noqa: ANN202 - context manager helper
    return patch.multiple(encryption.settings, encryption_key=primary, encryption_keys_extra=extra)


def _instance(id: str, primary: str, extra: str = "", *, live: bool = True) -> InstanceView:
    with _keys(primary, extra):
        keys, decrypts = identity.keys_fingerprint(), tuple(identity.decrypt_fingerprints())
    now = datetime.now(timezone.utc)
    beat = now if live else now - timedelta(minutes=5)
    return InstanceView(
        id=id,
        name=id,
        role="main" if id == "main" else "worker",
        enabled=True,
        weight=50,
        weight_configured=True,
        version="1",
        schema_revision="152",
        keys_fingerprint=keys,
        docker_ok=True,
        db_latency_ms=1.0,
        heartbeat_at=beat,
        credentials_synced_at=beat,
        decrypt_fingerprints=decrypts,
    )


def _fp(key: str) -> str:
    with _keys(key):
        return identity.primary_fingerprint()


class KeyRotationPostgresTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = await create_isolated_database(self)
        self.owner = User(id=uuid.uuid4(), email="o@example.com", hashed_password="x", name="o")
        async with self.database.sessions() as db:
            db.add(self.owner)
            await db.commit()
        self.rotated_fleet = [_instance("main", NEW, OLD), _instance("w1", NEW, OLD)]

    async def asyncTearDown(self) -> None:
        await self.database.drop()

    async def _add(
        self, key: str, *, count: int = 1, id: uuid.UUID | None = None
    ) -> list[uuid.UUID]:
        ids = []
        async with self.database.sessions() as db:
            for _ in range(count):
                with _keys(key):
                    token = encryption.encrypt_config({"api_key": f"sk-{key}"})
                credential = Credential(
                    id=id or uuid.uuid4(),
                    owner_id=self.owner.id,
                    name=f"c-{uuid.uuid4().hex[:8]}",
                    type=CredentialType.openai,
                    encrypted_config=token,
                    updated_at=UPDATED,
                )
                db.add(credential)
                ids.append(credential.id)
            await db.commit()
        return ids

    async def _add_singletons(self, key: str) -> None:
        with _keys(key):
            sso = encryption.encrypt_config({"client_secret": "s"})
            canary = encryption.encrypt_config({"heym": "encryption-canary"})
        async with self.database.sessions() as db:
            db.add(SsoSettings(id=SSO_SETTINGS_ID, encrypted_client_secret=sso))
            db.add(EncryptionCanary(id=ENCRYPTION_CANARY_ID, token=canary))
            await db.commit()

    async def _start(self, fleet: list[InstanceView] | None = None) -> KeyRotation:
        async with self.database.sessions() as db:
            user = await db.get(User, self.owner.id)
            return await key_rotation.start_rotation(db, user, fleet or self.rotated_fleet)

    async def _run(self, fleet: list[InstanceView] | None = None, limit: int = 50) -> KeyRotation:
        rotation = None
        for _ in range(limit):
            rotation = await key_rotation.step(
                fleet or self.rotated_fleet, sessions=self.database.sessions
            )
            if rotation is None or rotation.state != "running" or rotation.cursor is None:
                if rotation is None or rotation.state in ("completed", "paused"):
                    break
        return rotation

    async def _tokens(self) -> dict[uuid.UUID, str]:
        async with self.database.sessions() as db:
            rows = await db.execute(select(Credential.id, Credential.encrypted_config))
            return dict(rows.all())

    # Starting.

    async def test_start_is_refused_until_every_live_instance_encrypts_with_one_key(self) -> None:
        behind = [_instance("main", NEW, OLD), _instance("w1", OLD, NEW)]
        with _keys(NEW, OLD), self.assertRaisesRegex(key_rotation.RotationRefusedError, "w1"):
            await self._start(behind)

    async def test_an_offline_instance_doesnt_block_the_start(self) -> None:
        fleet = [_instance("main", NEW, OLD), _instance("w1", OLD, live=False)]
        with _keys(NEW, OLD):
            rotation = await self._start(fleet)
        self.assertEqual(rotation.state, "running")

    async def test_only_one_rotation_at_a_time(self) -> None:
        with _keys(NEW, OLD):
            await self._start()
            with self.assertRaisesRegex(key_rotation.RotationRefusedError, "already"):
                await self._start()

    async def test_start_records_the_target_retired_keys_and_counts(self) -> None:
        await self._add(OLD, count=3)
        await self._add(NEW, count=2)
        await self._add(LOST, count=1)
        with _keys(NEW, OLD):
            rotation = await self._start()
        self.assertEqual(rotation.target_fingerprint, _fp(NEW))
        self.assertEqual(rotation.retired_fingerprints, [_fp(OLD)])
        self.assertEqual((rotation.remaining, rotation.unreadable), (3, 1))

    # Running.

    async def test_a_full_rotation(self) -> None:
        old_ids = await self._add(OLD, count=5)
        await self._add(NEW, count=2)
        lost_ids = await self._add(LOST, count=1)
        await self._add_singletons(OLD)
        async with self.database.sessions() as db:
            db.add(
                Credential(
                    owner_id=self.owner.id,
                    name="from-a-secret",
                    type=CredentialType.openai,
                    encrypted_config="k8s:heym/x",
                    source="k8s:heym/x",
                )
            )
            await db.commit()
        before = await self._tokens()

        with _keys(NEW, OLD), patch.object(key_rotation, "BATCH_SIZE", 2):
            await self._start()
            rotation = await self._run()

        self.assertEqual(rotation.state, "completed")
        self.assertFalse(rotation.active)
        self.assertEqual((rotation.done, rotation.remaining, rotation.unreadable), (7, 0, 1))
        after = await self._tokens()
        with _keys(NEW):
            for credential_id in old_ids:
                self.assertTrue(encryption.readable_by_primary(after[credential_id]))
                self.assertEqual(
                    encryption.decrypt_config(after[credential_id]), {"api_key": f"sk-{OLD}"}
                )
        # Unreadable rows and Secret pointers are left as they were.
        self.assertEqual(after[lost_ids[0]], before[lost_ids[0]])
        self.assertIn("k8s:heym/x", after.values())
        async with self.database.sessions() as db:
            # A re-encryption isn't an edit.
            stamps = (
                await db.execute(select(Credential.updated_at).where(Credential.id.in_(old_ids)))
            ).scalars()
            self.assertEqual(set(stamps), {UPDATED})
            sso = await db.get(SsoSettings, SSO_SETTINGS_ID)
            canary = await db.get(EncryptionCanary, ENCRYPTION_CANARY_ID)
        with _keys(NEW):
            self.assertTrue(encryption.readable_by_primary(sso.encrypted_client_secret))
            self.assertTrue(encryption.readable_by_primary(canary.token))

    async def test_it_pauses_when_an_instance_still_encrypts_with_the_old_key(self) -> None:
        old_ids = await self._add(OLD, count=3)
        with _keys(NEW, OLD):
            await self._start()
            # An instance rolled back, or a new one joined on the old primary.
            rotation = await self._run([*self.rotated_fleet, _instance("w2", OLD, NEW)])
            self.assertEqual(rotation.state, "paused")
            self.assertIn("w2", rotation.message)
            self.assertEqual(rotation.done, 0)
            self.assertFalse(encryption.readable_by_primary((await self._tokens())[old_ids[0]]))
            # Once it's gone, the job resumes.
            rotation = await self._run()
        self.assertEqual(rotation.state, "completed")
        self.assertEqual(rotation.done, 3)

    async def test_a_leader_on_another_key_pauses_instead_of_rotating_back(self) -> None:
        await self._add(OLD, count=2)
        with _keys(NEW, OLD):
            await self._start()
        # This process (the leader) is somehow back on OLD, like the whole fleet.
        with _keys(OLD, NEW):
            rotation = await self._run([_instance("main", OLD, NEW)])
        self.assertEqual(rotation.state, "paused")
        self.assertEqual(rotation.done, 0)

    async def test_a_row_written_under_the_old_key_mid_pass_is_caught_by_the_recount(self) -> None:
        await self._add(OLD, count=4)
        with _keys(NEW, OLD), patch.object(key_rotation, "BATCH_SIZE", 2):
            await self._start()
            first = await key_rotation.step(self.rotated_fleet, sessions=self.database.sessions)
            self.assertIsNotNone(first.cursor)
            # Behind the cursor: this pass won't see it again.
            late = await self._add(OLD, id=uuid.UUID(int=1))
            rotation = await self._run()
        self.assertEqual(rotation.state, "completed")
        with _keys(NEW):
            self.assertTrue(encryption.readable_by_primary((await self._tokens())[late[0]]))

    async def test_nothing_to_do_completes_at_once(self) -> None:
        await self._add(NEW, count=2)
        with _keys(NEW, OLD):
            await self._start()
            rotation = await self._run()
        self.assertEqual((rotation.state, rotation.done, rotation.remaining), ("completed", 0, 0))

    async def test_no_active_rotation_means_no_work(self) -> None:
        with _keys(NEW, OLD):
            self.assertIsNone(
                await key_rotation.step(self.rotated_fleet, sessions=self.database.sessions)
            )

    # Unreadable rows.

    async def test_unreadable_credentials_are_listed_with_their_owner(self) -> None:
        await self._add(NEW, count=1)
        lost = await self._add(LOST, count=1)
        with _keys(NEW, OLD):
            async with self.database.sessions() as db:
                listed = await key_rotation.unreadable_credentials(db)
        self.assertEqual([(c.id, c.owner_email) for c in listed], [(lost[0], "o@example.com")])
