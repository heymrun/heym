"""A data table's CSV export can be imported back, JSON columns included."""

import io
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import UploadFile

from app.api import data_tables

COLUMNS = [
    {"id": "c1", "name": "name", "type": "string", "order": 0},
    {"id": "c2", "name": "score", "type": "number", "order": 1},
    {"id": "c3", "name": "meta", "type": "json", "order": 2},
]


def _rows_result(rows: list[dict]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = [SimpleNamespace(data=data) for data in rows]
    return result


class DataTableCsvRoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def _export(self, rows: list[dict]) -> str:
        table = SimpleNamespace(id=uuid.uuid4(), name="Customers", columns=COLUMNS)
        db = AsyncMock()
        db.execute.return_value = _rows_result(rows)
        with (
            patch.object(data_tables, "_get_data_table_with_access", AsyncMock(return_value=table)),
            patch.object(data_tables, "audit"),
        ):
            response = await data_tables.export_csv(table.id, SimpleNamespace(id=uuid.uuid4()), db)
        chunks = [chunk async for chunk in response.body_iterator]
        return "".join(c.decode() if isinstance(c, bytes) else c for c in chunks)

    async def _import(self, csv_text: str) -> tuple[list[dict], list]:
        table = SimpleNamespace(id=uuid.uuid4(), name="Customers", columns=COLUMNS)
        db = AsyncMock()
        db.add = MagicMock()
        upload = UploadFile(file=io.BytesIO(csv_text.encode()), filename="customers.csv")
        with (
            patch.object(data_tables, "_get_data_table_with_access", AsyncMock(return_value=table)),
            patch.object(data_tables, "audit"),
        ):
            result = await data_tables.import_csv(
                table.id, upload, SimpleNamespace(id=uuid.uuid4()), db
            )
        stored = [call.args[0].data for call in db.add.call_args_list]
        return stored, result.errors

    async def test_json_cells_are_exported_as_json(self) -> None:
        csv_text = await self._export([{"name": "Ada", "meta": {"plan": "pro", "seats": 3}}])
        self.assertIn('"{""plan"": ""pro"", ""seats"": 3}"', csv_text)
        self.assertNotIn("'plan'", csv_text)

    async def test_an_exported_table_imports_back_unchanged(self) -> None:
        rows = [
            {"name": "Ada", "score": 42, "meta": {"plan": "pro", "seats": 3}},
            {"name": "Bob", "score": 1.5, "meta": ["a", "b"]},
            {"name": "Cem", "score": 7, "meta": "free text"},
            {"name": "Dee", "score": 0, "meta": {"city": "İzmir"}},
        ]
        stored, errors = await self._import(await self._export(rows))
        self.assertEqual(errors, [])
        self.assertEqual(stored, rows)

    async def test_an_empty_json_cell_stays_empty(self) -> None:
        csv_text = await self._export([{"name": "Ada", "score": 1, "meta": None}, {"name": "Bob"}])
        self.assertEqual(csv_text.splitlines()[1:], ["Ada,1,", "Bob,,"])


if __name__ == "__main__":
    unittest.main()
