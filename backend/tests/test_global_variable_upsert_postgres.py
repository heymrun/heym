"""Two runs that set the same new global variable at once both persist."""

from __future__ import annotations

import asyncio

from sqlalchemy import delete, select
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import GlobalVariable
from app.db.session import async_session_maker
from app.services.global_variables_service import upsert_global_variable


class GlobalVariableUpsertRaceTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._drop_variables)

    async def _drop_variables(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(GlobalVariable).where(GlobalVariable.owner_id == self.user_id))
            await db.commit()

    async def _stored(self, name: str) -> list[tuple[object, str]]:
        async with async_session_maker() as db:
            rows = await db.execute(
                select(GlobalVariable.value, GlobalVariable.value_type).where(
                    GlobalVariable.owner_id == self.user_id, GlobalVariable.name == name
                )
            )
            return [tuple(row) for row in rows]

    async def test_a_second_run_creating_the_same_variable_commits(self) -> None:
        async with async_session_maker() as a, async_session_maker() as b:
            await upsert_global_variable(a, self.user_id, "lastOrderId", 41, "number")
            # B persists while A's transaction is still open, as two concurrent runs do.
            b_upsert = asyncio.create_task(
                upsert_global_variable(b, self.user_id, "lastOrderId", 42, "number")
            )
            await asyncio.sleep(0.1)
            await a.commit()
            await asyncio.wait_for(b_upsert, timeout=10)
            await b.commit()

        self.assertEqual(await self._stored("lastOrderId"), [({"v": 42}, "number")])

    async def test_an_existing_variable_is_updated_in_place(self) -> None:
        for value, value_type in ((1, "number"), ("one", "string")):
            async with async_session_maker() as db:
                await upsert_global_variable(db, self.user_id, "status", value, value_type)
                await db.commit()

        self.assertEqual(await self._stored("status"), [({"v": "one"}, "string")])
