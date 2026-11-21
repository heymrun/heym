"""Data Table column rules, against PostgreSQL (issue #1074).

- A required column treats null and "" as missing on create, bulk and CSV import;
  0 and false are values.
- A row update checks only the values it changes, so a row that already breaks a rule
  stays editable (Heym Work sends the whole row on every edit).
- Turning Unique on, or changing a unique column's type, is refused while two rows share
  a value, with the row checks' comparison.
- The Data Table node fills column defaults on insert and upsert-insert and does not fail
  on required, type or unknown columns.
"""

import io
import unittest
import uuid
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select, text

from app.api import data_tables as dt_api
from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal, async_session_maker, engine
from app.models.schemas import (
    DataTableColumnDef,
    DataTableRowCreate,
    DataTableRowUpdate,
    DataTableUpdate,
)
from app.services.workflow_executor import execute_workflow

COLUMNS = [
    {"id": str(uuid.uuid4()), "name": "sku", "type": "string", "required": True},
    {"id": str(uuid.uuid4()), "name": "qty", "type": "number", "required": True},
    {"id": str(uuid.uuid4()), "name": "paid", "type": "boolean", "required": True},
    {"id": str(uuid.uuid4()), "name": "note", "type": "string", "defaultValue": "none"},
    {"id": str(uuid.uuid4()), "name": "code", "type": "string"},
]


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTableColumnRulesPostgresTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.table_id = uuid.uuid4()
        self.user = SimpleNamespace(
            id=self.user_id, email=f"rules-{self.user_id.hex[:8]}@example.com", name="Rules"
        )
        with SessionLocal() as db:
            db.add(User(id=self.user_id, email=self.user.email, hashed_password="x", name="Rules"))
            db.flush()
            db.add(
                DataTable(
                    id=self.table_id,
                    name=f"rules_{self.table_id.hex[:8]}",
                    owner_id=self.user_id,
                    columns=[dict(col) for col in COLUMNS],
                )
            )
            db.commit()

    async def asyncSetUp(self) -> None:
        # The async engine's pool belongs to the loop that opened it; each test has its own.
        await engine.dispose()

    async def asyncTearDown(self) -> None:
        await engine.dispose()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            db.execute(delete(DataTableRow).where(DataTableRow.table_id == self.table_id))
            db.execute(delete(DataTable).where(DataTable.id == self.table_id))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    # helpers ------------------------------------------------------------------

    def _add_rows(self, *rows: dict) -> list[uuid.UUID]:
        ids = []
        with SessionLocal() as db:
            for data in rows:
                row = DataTableRow(id=uuid.uuid4(), table_id=self.table_id, data=data)
                db.add(row)
                ids.append(row.id)
            db.commit()
        return ids

    def _stored(self) -> list[dict]:
        with SessionLocal() as db:
            return [
                data
                for data in db.execute(
                    select(DataTableRow.data)
                    .where(DataTableRow.table_id == self.table_id)
                    .order_by(DataTableRow.created_at)
                ).scalars()
            ]

    async def _call(self, func: Any, **kwargs: Any) -> Any:
        async with async_session_maker() as db:
            try:
                result = await func(table_id=self.table_id, current_user=self.user, db=db, **kwargs)
                await db.commit()
                return result
            except Exception:
                await db.rollback()
                raise

    async def _create(self, data: dict) -> int:
        try:
            await self._call(dt_api.create_row, row_data=DataTableRowCreate(data=data))
        except HTTPException as exc:
            return exc.status_code
        return 201

    async def _update(self, row_id: uuid.UUID, data: dict) -> tuple[int, str]:
        try:
            await self._call(
                dt_api.update_row, row_id=row_id, row_data=DataTableRowUpdate(data=data)
            )
        except HTTPException as exc:
            return exc.status_code, str(exc.detail)
        return 200, ""

    async def _set_columns(self, **changes: dict) -> tuple[int, str]:
        columns = []
        for col in COLUMNS:
            columns.append(DataTableColumnDef(**{**col, **changes.get(col["name"], {})}))
        try:
            await self._call(dt_api.update_data_table, data=DataTableUpdate(columns=columns))
        except HTTPException as exc:
            return exc.status_code, str(exc.detail)
        return 200, ""

    def _node(self, operation: str, data: str, **fields: str) -> dict:
        nodes = [
            {"id": "start", "type": "textInput", "data": {"label": "start"}},
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "table",
                    "dataTableId": str(self.table_id),
                    "dataTableOperation": operation,
                    "dataTableData": data,
                    **fields,
                },
            },
        ]
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=[{"id": "e1", "source": "start", "target": "dt"}],
            inputs={},
            actor_user_id=self.user_id,
        )
        return next(r for r in result.node_results if r.get("node_id") == "dt")

    # 3. required vs empty -----------------------------------------------------

    async def test_null_and_empty_are_missing_for_a_required_column(self) -> None:
        base = {"sku": "A", "qty": 1, "paid": True}
        self.assertEqual(await self._create({**base, "sku": ""}), 400)
        self.assertEqual(await self._create({**base, "sku": None}), 400)
        self.assertEqual(await self._create({**base, "qty": 0, "paid": False}), 201)

    async def test_bulk_and_csv_refuse_empty_required_values(self) -> None:
        bulk = await self._call(
            dt_api.bulk_create_rows,
            rows=[
                DataTableRowCreate(data={"sku": "", "qty": 1, "paid": True}),
                DataTableRowCreate(data={"sku": "B", "qty": 2, "paid": False}),
            ],
        )
        self.assertEqual(bulk.imported, 1)
        self.assertEqual(bulk.errors, [{"row": 1, "errors": ["Missing required field: sku"]}])

        upload = UploadFile(
            file=io.BytesIO(b"sku,qty,paid\n,3,true\nC,4,false\n"), filename="rows.csv"
        )
        imported = await self._call(dt_api.import_csv, file=upload)
        self.assertEqual(imported.imported, 1)
        self.assertEqual(imported.errors, [{"row": 1, "errors": ["Missing required field: sku"]}])

    async def test_a_default_fills_a_required_column_left_empty(self) -> None:
        self.assertEqual((await self._set_columns(sku={"defaultValue": "unknown"}))[0], 200)

        self.assertEqual(await self._create({"sku": "", "qty": 1, "paid": True}), 201)
        self.assertEqual(self._stored()[0]["sku"], "unknown")

    # a row update checks only what it changes -------------------------------------

    async def test_a_row_that_breaks_a_rule_stays_editable(self) -> None:
        # Written before the rules (or by the node): empty required sku, text in qty.
        (row_id,) = self._add_rows({"sku": "", "qty": "many", "paid": True, "stale": 1})

        # Heym Work sends the whole row with one value changed.
        status, detail = await self._update(
            row_id, {"sku": "", "qty": "many", "paid": True, "stale": 1, "note": "checked"}
        )

        self.assertEqual((status, detail), (200, ""))
        self.assertEqual(self._stored()[0]["note"], "checked")

    async def test_a_changed_value_is_still_checked(self) -> None:
        (row_id,) = self._add_rows({"sku": "A", "qty": 1, "paid": True})

        self.assertEqual((await self._update(row_id, {"sku": ""}))[0], 400)
        self.assertEqual((await self._update(row_id, {"qty": "many"}))[0], 400)
        self.assertEqual((await self._update(row_id, {"color": "red"}))[0], 400)
        self.assertEqual(await self._update(row_id, {"qty": "2"}), (200, ""))
        self.assertEqual(self._stored()[0]["qty"], 2)

    async def test_a_shared_unique_value_does_not_block_other_edits(self) -> None:
        self.assertEqual((await self._set_columns(code={"unique": True}))[0], 200)
        first, second = self._add_rows(
            {"sku": "A", "qty": 1, "paid": True, "code": "X"},
            {"sku": "B", "qty": 2, "paid": True, "code": "X"},
        )

        status, _ = await self._update(second, {"sku": "B", "code": "X", "note": "seen"})
        self.assertEqual(status, 200)
        status, detail = await self._update(first, {"code": "Y"})
        self.assertEqual(status, 200)
        status, detail = await self._update(first, {"code": "X"})
        self.assertEqual((status, detail), (409, "Duplicate value for unique column 'code': X"))

    # 2. unique over existing duplicates ---------------------------------------------

    async def test_turning_unique_on_over_duplicates_is_refused(self) -> None:
        self._add_rows({"code": "X"}, {"code": "X"}, {"code": "Y"})

        status, detail = await self._set_columns(code={"unique": True})

        self.assertEqual(status, 400)
        self.assertEqual(detail, "Cannot make 'code' unique: more than one row has the value X")
        with SessionLocal() as db:
            table = db.get(DataTable, self.table_id)
            self.assertFalse(next(c for c in table.columns if c["name"] == "code").get("unique"))

    async def test_one_and_one_point_zero_are_one_number(self) -> None:
        self._add_rows({"qty": 1}, {"qty": 1.0})

        status, detail = await self._set_columns(qty={"unique": True})

        self.assertEqual(status, 400)
        self.assertIn("more than one row has the value 1", detail)

    async def test_a_type_change_on_a_unique_column_is_checked(self) -> None:
        self.assertEqual((await self._set_columns(code={"unique": True}))[0], 200)
        self._add_rows({"code": "1"}, {"code": "1.0"})

        status, detail = await self._set_columns(code={"unique": True, "type": "number"})

        self.assertEqual(status, 400)
        self.assertIn("'code'", detail)

    async def test_empty_values_and_boolean_columns_are_skipped(self) -> None:
        self._add_rows({"code": ""}, {"code": None}, {"paid": True}, {"paid": True})

        self.assertEqual((await self._set_columns(code={"unique": True}))[0], 200)
        self.assertEqual((await self._set_columns(paid={"unique": True}))[0], 200)

    async def test_an_already_unique_column_is_not_checked_again(self) -> None:
        self.assertEqual((await self._set_columns(code={"unique": True}))[0], 200)
        self._add_rows({"code": "X"}, {"code": "X"})

        status, _ = await self._set_columns(code={"unique": True}, note={"defaultValue": "n/a"})

        self.assertEqual(status, 200)

    # 1. the Data Table node ---------------------------------------------------------

    def test_node_insert_fills_defaults_and_keeps_running(self) -> None:
        row = self._node("insert", '{"qty": "many", "color": "red"}')

        self.assertEqual(row["status"], "success", row)
        self.assertEqual(self._stored(), [{"qty": "many", "color": "red", "note": "none"}])

    def test_node_upsert_insert_fills_defaults(self) -> None:
        row = self._node("upsert", '{"sku": "Z", "qty": 3}', dataTableFilter='{"sku": "Z"}')

        self.assertEqual(row["output"]["operation"], "insert")
        self.assertEqual(self._stored(), [{"sku": "Z", "qty": 3, "note": "none"}])

    def test_node_update_checks_only_what_it_changes(self) -> None:
        with SessionLocal() as db:
            table = db.get(DataTable, self.table_id)
            table.columns = [
                {**col, "unique": True} if col["name"] == "code" else col for col in COLUMNS
            ]
            db.commit()
        first, _second = self._add_rows({"code": "X", "qty": 1}, {"code": "X", "qty": 2})

        row = self._node("update", '{"code": "X", "qty": 5}', dataTableRowId=str(first))

        self.assertEqual(row["status"], "success", row)
        with SessionLocal() as db:
            self.assertEqual(db.get(DataTableRow, first).data, {"code": "X", "qty": 5})


if __name__ == "__main__":
    unittest.main()
