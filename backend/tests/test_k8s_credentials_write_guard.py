"""A Secret-backed credential row never stores a value: the model guard and the database.

The PostgreSQL half needs a migrated test database, like the other ``*_postgres``
suites, and skips without one. It exists because a constraint that only looks right
is easy to write: revision 3 of the design compared ``k8s:ns/name`` with
``k8s:k8s:ns/name``, and an early draft of this one let a pointer without a source
through, because ``encrypted_config = NULL`` is NULL and a CHECK only refuses false.
"""

from __future__ import annotations

import asyncio
import unittest
import uuid
from unittest import IsolatedAsyncioTestCase

from asyncpg import CannotConnectNowError, PostgresConnectionError
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.models import (
    Credential,
    CredentialType,
    CredentialWriteBackError,
    User,
    _credential_pointer_needs_source,
)
from app.db.session import async_session_maker, engine
from app.services.encryption import encrypt_config

POINTER = "k8s:heym/heym-cred-llm"


class ModelGuardTests(unittest.TestCase):
    def test_constructor_accepts_a_pointer_row_in_either_order(self) -> None:
        Credential(source=POINTER, encrypted_config=POINTER)
        Credential(encrypted_config=POINTER, source=POINTER)

    def test_constructor_refuses_a_value_on_a_secret_backed_row(self) -> None:
        with self.assertRaises(CredentialWriteBackError):
            Credential(source=POINTER, encrypted_config=encrypt_config({"api_key": "leak"}))
        with self.assertRaises(CredentialWriteBackError):
            Credential(encrypted_config=encrypt_config({"api_key": "leak"}), source=POINTER)

    def test_write_back_after_a_refresh_is_refused_and_names_the_secret(self) -> None:
        credential = Credential(source=POINTER, encrypted_config=POINTER)

        with self.assertRaisesRegex(CredentialWriteBackError, "heym/heym-cred-llm"):
            credential.encrypted_config = encrypt_config({"access_token": "refreshed"})

    def test_a_pointer_without_a_source_is_refused_at_flush(self) -> None:
        with self.assertRaises(CredentialWriteBackError):
            _credential_pointer_needs_source(None, None, Credential(encrypted_config=POINTER))  # type: ignore[arg-type]

    def test_ui_credentials_are_unaffected(self) -> None:
        credential = Credential(encrypted_config=encrypt_config({"api_key": "a"}))
        credential.encrypted_config = encrypt_config({"api_key": "b"})


class ConstraintPostgresTests(IsolatedAsyncioTestCase):
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
        self.user_id = uuid.uuid4()
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"k8s-guard-{self.user_id.hex}@example.com",
                    hashed_password="test-only",
                    name="Guard fixture",
                )
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(Credential).where(Credential.owner_id == self.user_id))
            await db.execute(delete(User).where(User.id == self.user_id))
            await db.commit()
        await engine.dispose()

    async def _insert(self, encrypted_config: str, source: str | None) -> None:
        """Raw SQL, so only the database constraint stands in the way."""
        async with async_session_maker() as db:
            await db.execute(
                text(
                    "INSERT INTO credentials (id, owner_id, name, type, encrypted_config, source) "
                    "VALUES (:id, :owner, :name, 'custom', :config, :source)"
                ),
                {
                    "id": uuid.uuid4(),
                    "owner": self.user_id,
                    "name": uuid.uuid4().hex,
                    "config": encrypted_config,
                    "source": source,
                },
            )
            await db.commit()

    async def test_a_ui_row_and_a_pointer_row_are_accepted(self) -> None:
        await self._insert("gAAAAAciphertext", None)
        await self._insert(POINTER, POINTER)

    async def test_a_value_on_a_secret_backed_row_is_refused(self) -> None:
        with self.assertRaisesRegex(IntegrityError, "ck_credentials_source_pointer"):
            await self._insert("gAAAAAleaked", POINTER)

    async def test_a_pointer_without_a_source_is_refused(self) -> None:
        with self.assertRaisesRegex(IntegrityError, "ck_credentials_source_pointer"):
            await self._insert(POINTER, None)

    async def test_the_orm_refuses_a_pointer_without_a_source_at_flush(self) -> None:
        with self.assertRaises(CredentialWriteBackError):
            async with async_session_maker() as db:
                db.add(
                    Credential(
                        owner_id=self.user_id,
                        name="pointer-only",
                        type=CredentialType.custom,
                        encrypted_config=POINTER,
                    )
                )
                await db.commit()

    async def test_a_raw_update_writing_a_value_is_refused(self) -> None:
        credential_id = uuid.uuid4()
        async with async_session_maker() as db:
            db.add(
                Credential(
                    id=credential_id,
                    owner_id=self.user_id,
                    name="secret-backed",
                    type=CredentialType.custom,
                    source=POINTER,
                    encrypted_config=POINTER,
                )
            )
            await db.commit()

        with self.assertRaisesRegex(IntegrityError, "ck_credentials_source_pointer"):
            async with async_session_maker() as db:
                await db.execute(
                    text("UPDATE credentials SET encrypted_config = 'gAAAAAleaked' WHERE id = :id"),
                    {"id": credential_id},
                )
                await db.commit()


if __name__ == "__main__":
    unittest.main()
