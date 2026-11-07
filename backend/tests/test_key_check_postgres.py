"""`python -m app.key_check` on real PostgreSQL, in a database of its own (#862)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from sqlalchemy import select, text

from app import key_check
from app.db.models import (
    ENCRYPTION_CANARY_ID,
    SSO_SETTINGS_ID,
    Credential,
    CredentialType,
    EncryptionCanary,
    KeyRotation,
    KeyRotationState,
    SsoSettings,
    User,
)
from app.services import encryption
from app.services.cluster import identity
from tests.isolated_postgres import create_isolated_database

OLD = "old-encryption-key-for-tests"
NEW = "new-encryption-key-for-tests"
OTHER = "someone-elses-encryption-key"


def _keys(primary: str, extra: str = "", *, accept: bool = False):  # noqa: ANN202
    return patch.multiple(
        encryption.settings,
        encryption_key=primary,
        encryption_keys_extra=extra,
        accept_current_encryption_key=accept,
    )


def _fingerprint(key: str) -> str:
    with _keys(key):
        return identity.primary_fingerprint()


class KeyCheckPostgresTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = await create_isolated_database(self)
        self.owner_id = uuid.uuid4()
        async with self.database.sessions() as db:
            db.add(User(id=self.owner_id, email="o@example.com", hashed_password="x", name="o"))
            await db.commit()

    async def asyncTearDown(self) -> None:
        await self.database.drop()

    async def _check(self) -> key_check.KeyCheckResult:
        async with self.database.sessions() as db:
            return await key_check.check(db)

    async def _store(self, key: str, *, count: int = 1, age: timedelta = timedelta()) -> None:
        with _keys(key):
            token = encryption.encrypt_config({"api_key": "sk"})
        async with self.database.sessions() as db:
            for _ in range(count):
                db.add(
                    Credential(
                        owner_id=self.owner_id,
                        name=f"c-{uuid.uuid4().hex[:8]}",
                        type=CredentialType.openai,
                        encrypted_config=token,
                        updated_at=datetime.now(timezone.utc) - age,
                    )
                )
            await db.commit()

    async def _canary(self) -> EncryptionCanary | None:
        async with self.database.sessions() as db:
            return await db.get(EncryptionCanary, ENCRYPTION_CANARY_ID)

    # First start: seeding the canary.

    async def test_an_empty_database_records_the_key(self) -> None:
        with _keys(NEW):
            result = await self._check()
            self.assertIn("recorded", result.message)
            canary = await self._canary()
            self.assertIsNotNone(canary)
            self.assertEqual(encryption.decrypt_config(canary.token), key_check._CANARY_VALUE)

    async def test_a_stored_value_that_decrypts_records_the_key(self) -> None:
        await self._store(NEW)
        with _keys(NEW):
            await self._check()
        self.assertIsNotNone(await self._canary())

    async def test_a_wrong_key_at_first_boot_is_refused_and_not_recorded(self) -> None:
        await self._store(NEW, count=3)
        with _keys(OTHER), self.assertRaisesRegex(key_check.KeyCheckError, "does not match"):
            await self._check()
        self.assertIsNone(await self._canary())

    async def test_seeding_reads_the_newest_rows_first(self) -> None:
        # The key changed the hard way long ago: old rows are unreadable, recent ones fine.
        await self._store(OTHER, count=30, age=timedelta(days=30))
        await self._store(NEW, count=1)
        with _keys(NEW):
            await self._check()
        self.assertIsNotNone(await self._canary())

    async def test_secret_backed_rows_are_skipped_when_seeding(self) -> None:
        async with self.database.sessions() as db:
            db.add(
                Credential(
                    owner_id=self.owner_id,
                    name="k8s",
                    type=CredentialType.openai,
                    encrypted_config="k8s:heym/x",
                    source="k8s:heym/x",
                )
            )
            await db.commit()
        with _keys(NEW):
            result = await self._check()
        self.assertIn("recorded", result.message)

    async def test_the_sso_secret_counts_as_a_stored_value(self) -> None:
        with _keys(NEW):
            token = encryption.encrypt_config({"client_secret": "s"})
        async with self.database.sessions() as db:
            db.add(SsoSettings(id=SSO_SETTINGS_ID, encrypted_client_secret=token))
            await db.commit()
        with _keys(OTHER), self.assertRaises(key_check.KeyCheckError):
            await self._check()
        with _keys(NEW):
            await self._check()

    async def test_a_concurrent_first_start_keeps_the_first_canary(self) -> None:
        with _keys(NEW):
            await self._check()
            first = (await self._canary()).token
            await self._check()
        self.assertEqual((await self._canary()).token, first)

    # Later starts: the canary.

    async def test_the_recorded_key_passes_and_another_is_refused(self) -> None:
        with _keys(NEW):
            await self._check()
            self.assertIn("matches", (await self._check()).message)
        with _keys(OTHER), self.assertRaisesRegex(key_check.KeyCheckError, "HEYM_ACCEPT"):
            await self._check()

    async def test_the_old_key_as_an_extra_passes_during_a_rotation(self) -> None:
        with _keys(OLD):
            await self._check()
        with _keys(NEW, OLD):
            self.assertIn("matches", (await self._check()).message)
        with _keys(OLD, NEW):
            self.assertIn("matches", (await self._check()).message)

    # The way out for installs where nothing decrypts.

    async def test_accepting_the_current_key_records_it_when_nothing_decrypts(self) -> None:
        await self._store(OTHER, count=2)
        with _keys(NEW, accept=True):
            self.assertIn("recorded", (await self._check()).message)
        with _keys(NEW):
            self.assertIn("matches", (await self._check()).message)

    async def test_accepting_the_current_key_replaces_a_canary_it_cant_read(self) -> None:
        with _keys(OTHER):
            await self._check()
        with _keys(NEW, accept=True):
            self.assertIn("accepted", (await self._check()).message)
        with _keys(NEW):
            self.assertIn("matches", (await self._check()).message)

    # Retired keys.

    async def _complete_rotation(self, retired: list[str]) -> None:
        async with self.database.sessions() as db:
            db.add(
                KeyRotation(
                    state=KeyRotationState.completed.value,
                    active=False,
                    target_fingerprint=_fingerprint(NEW),
                    retired_fingerprints=retired,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await db.commit()

    async def test_a_primary_a_completed_rotation_retired_is_refused(self) -> None:
        with _keys(OLD):
            await self._check()
        await self._complete_rotation([_fingerprint(OLD)])
        # A restored old .env, even with the new key as an extra.
        with _keys(OLD, NEW), self.assertRaisesRegex(key_check.KeyCheckError, "rotation"):
            await self._check()
        with _keys(OLD, NEW, accept=True), self.assertRaises(key_check.KeyCheckError):
            await self._check()

    async def test_the_next_rotation_can_promote_a_new_key(self) -> None:
        # mbakgun's case: phase 2 of a second rotation promotes a key no rotation has
        # targeted yet. Only retired keys are refused, so this starts.
        third = "third-encryption-key-for-tests"
        with _keys(OLD):
            await self._check()
        # The first rotation re-encrypted everything under NEW, the canary included.
        async with self.database.sessions() as db:
            canary = await db.get(EncryptionCanary, ENCRYPTION_CANARY_ID)
            with _keys(NEW, OLD):
                canary.token = encryption.rotate_token(canary.token)
            await db.commit()
        await self._complete_rotation([_fingerprint(OLD)])
        with _keys(NEW, OLD):
            await self._check()
        with _keys(third, NEW):
            self.assertIn("matches", (await self._check()).message)

    # Schema not migrated yet.

    async def test_a_database_without_the_tables_is_skipped(self) -> None:
        async with self.database.engine.begin() as conn:
            await conn.execute(text("DROP TABLE encryption_canary"))
        with _keys(OTHER):
            self.assertIn("skipped", (await self._check()).message)

    async def test_nothing_is_written_but_the_canary(self) -> None:
        await self._store(NEW)
        with _keys(NEW):
            await self._check()
        async with self.database.sessions() as db:
            rotations = (await db.execute(select(KeyRotation))).scalars().all()
        self.assertEqual(rotations, [])
