"""The Data Table API refuses two columns with the same name.

Both columns read and write the same row key: the table then checked the first column's
values against the second column's type and exported every value twice. The chat tool
already refused a duplicate name; the API behind the DataTable tab did not.
"""

import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.api import data_tables as dt_api
from app.db.models import DataTable
from app.models.schemas import DataTableColumnDef, DataTableCreate, DataTableUpdate


class _User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.email = "owner@example.com"


def _db(*results: object) -> MagicMock:
    async def flush() -> None:
        for call in db.add.call_args_list:
            obj = call.args[0]
            obj.id = obj.id or uuid.uuid4()

    async def refresh(obj: object) -> None:
        obj.created_at = obj.updated_at = datetime.datetime.now()

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock(side_effect=flush)
    db.refresh = AsyncMock(side_effect=refresh)
    db.execute = AsyncMock(side_effect=list(results))
    return db


def _result(**attrs: object) -> MagicMock:
    res = MagicMock()
    for name, value in attrs.items():
        setattr(res, name, MagicMock(return_value=value))
    return res


def _columns(*names: str) -> list[DataTableColumnDef]:
    return [DataTableColumnDef(name=name) for name in names]


class DuplicateColumnNameTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_refuses_a_repeated_name(self) -> None:
        db = _db(_result(scalar_one_or_none=None))

        with self.assertRaises(HTTPException) as caught:
            await dt_api.create_data_table(
                data=DataTableCreate(name="Stock", columns=_columns("sku", "qty", "sku")),
                current_user=_User(),
                db=db,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail, "Duplicate column name: sku")
        db.add.assert_not_called()

    async def test_create_accepts_distinct_names(self) -> None:
        db = _db(_result(scalar_one_or_none=None))

        response = await dt_api.create_data_table(
            data=DataTableCreate(name="Stock", columns=_columns("sku", "SKU", "qty")),
            current_user=_User(),
            db=db,
        )

        self.assertEqual([column["name"] for column in response.columns], ["sku", "SKU", "qty"])

    async def test_update_refuses_adding_a_column_with_an_existing_name(self) -> None:
        user = _User()
        table = DataTable(
            name="Stock",
            columns=[{"id": str(uuid.uuid4()), "name": "sku", "type": "string", "order": 0}],
            owner_id=user.id,
        )
        table.id = uuid.uuid4()
        db = _db(_result(scalar_one_or_none=table))
        columns = [
            DataTableColumnDef.model_validate(table.columns[0]),
            DataTableColumnDef(name="sku", type="number", order=1),
        ]

        with self.assertRaises(HTTPException) as caught:
            await dt_api.update_data_table(
                table_id=table.id,
                data=DataTableUpdate(columns=columns),
                current_user=user,
                db=db,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(len(table.columns), 1)


if __name__ == "__main__":
    unittest.main()
