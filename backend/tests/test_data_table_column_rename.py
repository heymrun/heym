"""Renaming a Data Table column keeps its values.

The column editor keeps a column's id and changes its name. The update pruned every row
key that was not a current column name, so a rename deleted the column's values.
"""

import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.api import data_tables as dt_api
from app.db.models import DataTable, DataTableRow
from app.models.schemas import DataTableColumnDef, DataTableUpdate

SKU = uuid.uuid4()
QTY = uuid.uuid4()
NOTE = uuid.uuid4()


class _User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.email = "owner@example.com"


def _result(**attrs: object) -> MagicMock:
    res = MagicMock()
    for name, value in attrs.items():
        setattr(res, name, value)
    return res


async def _update(row_data: dict, columns: list[DataTableColumnDef]) -> dict:
    user = _User()
    table = DataTable(
        name="Products",
        columns=[
            {"id": str(SKU), "name": "sku", "type": "string", "order": 0},
            {"id": str(QTY), "name": "qty", "type": "number", "order": 1},
            {"id": str(NOTE), "name": "note", "type": "string", "order": 2},
        ],
        owner_id=user.id,
    )
    table.id = uuid.uuid4()
    row = DataTableRow(table_id=table.id, data=dict(row_data))

    async def refresh(obj: DataTable) -> None:
        obj.created_at = obj.updated_at = datetime.datetime.now()

    rows = MagicMock()
    rows.all.return_value = [row]
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock(side_effect=refresh)
    db.execute = AsyncMock(
        side_effect=[
            _result(scalar_one_or_none=MagicMock(return_value=table)),
            _result(scalars=MagicMock(return_value=rows)),
            _result(scalar=MagicMock(return_value=1)),
        ]
    )
    await dt_api.update_data_table(
        table_id=table.id, data=DataTableUpdate(columns=columns), current_user=user, db=db
    )
    return row.data


def _col(column_id: uuid.UUID, name: str) -> DataTableColumnDef:
    return DataTableColumnDef(id=column_id, name=name)


class DataTableColumnRenameTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_renamed_column_keeps_its_values(self) -> None:
        data = await _update(
            {"sku": "A-1", "qty": 4, "note": "fragile"},
            [_col(SKU, "code"), _col(QTY, "qty"), _col(NOTE, "note")],
        )

        self.assertEqual(data, {"code": "A-1", "qty": 4, "note": "fragile"})

    async def test_two_columns_can_swap_names(self) -> None:
        data = await _update(
            {"sku": "A-1", "qty": 4, "note": "fragile"},
            [_col(SKU, "note"), _col(QTY, "qty"), _col(NOTE, "sku")],
        )

        self.assertEqual(data, {"note": "A-1", "qty": 4, "sku": "fragile"})

    async def test_a_removed_column_value_does_not_reappear_under_a_rename(self) -> None:
        # "note" is removed and "sku" takes its name; the old note must not stay.
        data = await _update(
            {"qty": 4, "note": "fragile"},
            [_col(SKU, "note"), _col(QTY, "qty")],
        )

        self.assertEqual(data, {"qty": 4})

    async def test_a_rename_to_a_name_another_column_has_keeps_that_column(self) -> None:
        # Two columns named qty are refused, so the rows and qty's values stay as they are.
        with self.assertRaises(HTTPException) as caught:
            await _update(
                {"sku": "A-1", "qty": 4, "note": "fragile"},
                [_col(SKU, "qty"), _col(QTY, "qty"), _col(NOTE, "note")],
            )

        self.assertEqual(caught.exception.status_code, 400)
        # Should such a list get through, the rename still moves nothing onto qty.
        old = [{"id": str(SKU), "name": "sku"}, {"id": str(QTY), "name": "qty"}]
        new = [{"id": str(SKU), "name": "qty"}, {"id": str(QTY), "name": "qty"}]
        self.assertEqual(dt_api._renamed_columns(old, new), {})

    async def test_a_removed_column_still_loses_its_values(self) -> None:
        data = await _update(
            {"sku": "A-1", "qty": 4, "note": "fragile"},
            [_col(SKU, "sku"), _col(QTY, "qty")],
        )

        self.assertEqual(data, {"sku": "A-1", "qty": 4})

    async def test_columns_sent_without_ids_keep_values_by_name(self) -> None:
        data = await _update(
            {"sku": "A-1", "qty": 4, "note": "fragile"},
            [DataTableColumnDef(name="sku"), DataTableColumnDef(name="qty")],
        )

        self.assertEqual(data, {"sku": "A-1", "qty": 4})


if __name__ == "__main__":
    unittest.main()
