"""Rows one request writes keep their order, against PostgreSQL.

`now()` is the transaction's start time, so every row of one CSV import, bulk create or
clone got the same created_at, and the rows list fell back to the random row id.
"""

import io
import unittest
import uuid

from fastapi import UploadFile
from sqlalchemy import delete, select, text

from app.api import data_tables as dt_api
from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal, async_session_maker, engine
from app.models.schemas import DataTableRowCreate

COLUMNS = [{"name": "step", "type": "number"}, {"name": "task", "type": "string"}]
STEPS = list(range(1, 13))


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTableRowOrderPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        await engine.dispose()
        self.user_id = uuid.uuid4()
        self.table_ids: list[uuid.UUID] = []
        async with async_session_maker() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"row-order-{self.user_id.hex[:8]}@example.com",
                    hashed_password="x",
                    name="Row order",
                )
            )
            await db.commit()
        async with async_session_maker() as db:
            self.user = (await db.execute(select(User).where(User.id == self.user_id))).scalar_one()

    async def asyncTearDown(self) -> None:
        async with async_session_maker() as db:
            await db.execute(delete(DataTableRow).where(DataTableRow.table_id.in_(self.table_ids)))
            await db.execute(delete(DataTable).where(DataTable.id.in_(self.table_ids)))
            await db.execute(delete(User).where(User.id == self.user_id))
            await db.commit()
        await engine.dispose()

    async def _new_table(self) -> uuid.UUID:
        table_id = uuid.uuid4()
        self.table_ids.append(table_id)
        async with async_session_maker() as db:
            db.add(
                DataTable(
                    id=table_id,
                    name=f"row_order_{table_id.hex[:8]}",
                    owner_id=self.user_id,
                    columns=COLUMNS,
                )
            )
            await db.commit()
        return table_id

    async def _steps(self, table_id: uuid.UUID, direction: str = "asc") -> list[int]:
        async with async_session_maker() as db:
            rows = await dt_api.list_rows(
                table_id,
                limit=100,
                offset=0,
                sort_by="created_at",
                sort_direction=direction,
                current_user=self.user,
                db=db,
            )
        return [row.data["step"] for row in rows]

    async def test_a_csv_import_keeps_the_file_order(self) -> None:
        table_id = await self._new_table()
        csv_text = "step,task\n" + "".join(f"{step},task {step}\n" for step in STEPS)
        async with async_session_maker() as db:
            await dt_api.import_csv(
                table_id,
                file=UploadFile(io.BytesIO(csv_text.encode()), filename="steps.csv"),
                current_user=self.user,
                db=db,
            )
            await db.commit()

        self.assertEqual(await self._steps(table_id), STEPS)
        self.assertEqual(await self._steps(table_id, "desc"), STEPS[::-1])

    async def test_a_bulk_create_keeps_the_request_order(self) -> None:
        table_id = await self._new_table()
        async with async_session_maker() as db:
            await dt_api.bulk_create_rows(
                table_id,
                rows=[DataTableRowCreate(data={"step": step, "task": "t"}) for step in STEPS],
                current_user=self.user,
                db=db,
            )
            await db.commit()

        self.assertEqual(await self._steps(table_id), STEPS)

    async def test_a_clone_keeps_the_source_order(self) -> None:
        table_id = await self._new_table()
        for step in STEPS:
            async with async_session_maker() as db:
                db.add(DataTableRow(table_id=table_id, data={"step": step, "task": "t"}))
                await db.commit()
        async with async_session_maker() as db:
            clone = await dt_api.clone_data_table(table_id, current_user=self.user, db=db)
            await db.commit()
        self.table_ids.append(clone.id)

        self.assertEqual(await self._steps(clone.id), STEPS)


if __name__ == "__main__":
    unittest.main()
