"""A global variable switched between number and boolean keeps the new JSON value.

Python treats 1 == True and 0 == False. The stored value is a JSON object, so
SQLAlchemy would otherwise omit that column from the UPDATE and leave the old
number or boolean in place while value_type still changes.
"""

from __future__ import annotations

import os
import unittest
import uuid

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from app.api.global_variables import update_global_variable
from app.db.models import GlobalVariable, User
from app.models.schemas import GlobalVariableUpdate

# (label, old value, old type, new value, new type, stored Python type, stored value)
_CASES = (
    ("number 1 to boolean true", 1, "number", True, "boolean", bool, True),
    ("boolean true to number 1", True, "boolean", 1, "number", int, 1),
    ("number 0 to boolean false", 0, "number", False, "boolean", bool, False),
    ("boolean false to number 0", False, "boolean", 0, "number", int, 0),
)


class GlobalVariableBooleanNumberSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = None
        self.user_id = None
        url = os.environ.get("DATABASE_URL", "")
        if url.startswith("postgresql"):
            engine = create_async_engine(url, poolclass=NullPool)
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            except Exception:
                await engine.dispose()
            else:
                self.kind = "postgres"
                self.engine = engine
        if self.engine is None:
            try:
                engine = create_async_engine(
                    "sqlite+aiosqlite://",
                    poolclass=StaticPool,
                    connect_args={"check_same_thread": False},
                )
                async with engine.begin() as conn:
                    await conn.run_sync(User.__table__.create)
                    await conn.run_sync(GlobalVariable.__table__.create)
            except Exception as exc:  # noqa: BLE001 - no PostgreSQL and no sqlite driver
                self.skipTest(f"no database for the JSON round trip ({type(exc).__name__})")
            self.kind = "sqlite"
            self.engine = engine
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            user = User(
                email=f"switch-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                name="Switch",
            )
            db.add(user)
            await db.commit()
            self.user_id = user.id

    async def asyncTearDown(self) -> None:
        if self.engine is None:
            return
        if self.kind == "postgres" and self.user_id is not None:
            async with self.sessions() as db:
                await db.execute(
                    delete(GlobalVariable).where(GlobalVariable.owner_id == self.user_id)
                )
                await db.execute(delete(User).where(User.id == self.user_id))
                await db.commit()
        await self.engine.dispose()

    async def _switch(
        self,
        old: object,
        old_type: str,
        new: object,
        new_type: str,
        expect_type: type,
        expect: object,
    ) -> None:
        async with self.sessions() as db:
            user = (await db.execute(select(User).where(User.id == self.user_id))).scalar_one()
            variable = GlobalVariable(
                owner_id=user.id,
                name=f"featureOn-{uuid.uuid4().hex[:8]}",
                value={"v": old},
                value_type=old_type,
            )
            db.add(variable)
            await db.commit()
            await update_global_variable(
                variable.id,
                GlobalVariableUpdate(value=new, value_type=new_type),
                current_user=user,
                db=db,
            )
            await db.commit()
            variable_id = variable.id
        async with self.sessions() as fresh:
            stored = (
                await fresh.execute(select(GlobalVariable).where(GlobalVariable.id == variable_id))
            ).scalar_one()
        self.assertEqual(stored.value_type, new_type)
        got = stored.value["v"]
        self.assertIs(type(got), expect_type)
        self.assertEqual(got, expect)

    async def test_equal_python_values_of_different_types_are_stored(self) -> None:
        for label, old, old_type, new, new_type, expect_type, expect in _CASES:
            with self.subTest(label):
                await self._switch(old, old_type, new, new_type, expect_type, expect)

    async def test_a_number_that_is_not_equal_in_python_is_stored(self) -> None:
        await self._switch(True, "boolean", 2, "number", int, 2)
