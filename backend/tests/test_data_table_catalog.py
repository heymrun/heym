"""The data table catalog the workflow assistant sees: names, ids, access and columns."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.data_table_catalog import (
    PROMPT_COLUMN_LIMIT,
    PROMPT_TABLE_LIMIT,
    TOOL_TABLE_LIMIT,
    CatalogColumn,
    CatalogDataTable,
    DataTablePromptMode,
    build_data_tables_prompt,
    catalog_columns,
    format_data_tables_prompt,
    list_data_tables_payload,
    load_data_table_catalog,
)

ASK = DataTablePromptMode.ASK
APPLY = DataTablePromptMode.APPLY_CHOICES
NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)
COLUMNS = [
    {"id": "c2", "name": "name", "type": "string", "order": 1},
    {"id": "c1", "name": "email", "type": "string", "unique": True, "order": 0},
]


def _rows(*rows: tuple) -> MagicMock:
    result = MagicMock()
    result.all.return_value = list(rows)
    return result


def _table(name: str, access: str = "owner", shared_by: str | None = None) -> CatalogDataTable:
    return CatalogDataTable(
        uuid.uuid4(),
        name,
        f"{name} records",
        access,
        shared_by,
        (CatalogColumn("email", "string", unique=True), CatalogColumn("name", "string")),
    )


class CatalogColumnsTests(unittest.TestCase):
    def test_columns_follow_their_order_and_keep_flags(self) -> None:
        columns = catalog_columns(COLUMNS)

        self.assertEqual([column.name for column in columns], ["email", "name"])
        self.assertTrue(columns[0].unique)
        self.assertFalse(columns[1].unique)

    def test_unusable_definitions_are_skipped(self) -> None:
        self.assertEqual(catalog_columns(None), ())
        self.assertEqual(catalog_columns([{"name": "  "}, "email", {"type": "string"}]), ())


class CatalogDataTableTests(unittest.TestCase):
    def test_read_only_tables_fit_only_reading_operations(self) -> None:
        orders = _table("orders", access="read")

        self.assertTrue(orders.fits("find"))
        self.assertTrue(orders.fits("count"))
        self.assertFalse(orders.fits("insert"))
        self.assertFalse(orders.fits("upsert"))
        self.assertTrue(_table("leads").fits("insert"))
        self.assertTrue(_table("shared", access="write").fits("remove"))


class LoadDataTableCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_tables_come_first_then_shared_ones_newest_first(self) -> None:
        owned_id, direct_id, team_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _rows((owned_id, "leads", "Website leads", COLUMNS, NOW)),
                _rows(
                    (direct_id, "orders", None, [], NOW - timedelta(days=2), "read", "ali@x.com")
                ),
                _rows((team_id, "products", None, [], NOW - timedelta(days=1), "write", "ops")),
            ]
        )

        tables = await load_data_table_catalog(db, uuid.uuid4())

        self.assertEqual([table.name for table in tables], ["leads", "products", "orders"])
        self.assertEqual([table.access for table in tables], ["owner", "write", "read"])
        self.assertEqual(tables[1].shared_by, "ops")
        self.assertEqual([column.name for column in tables[0].columns], ["email", "name"])

    async def test_highest_permission_wins_across_direct_and_team_shares(self) -> None:
        table_id = uuid.uuid4()
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _rows(),
                _rows((table_id, "orders", None, [], NOW, "read", "ali@x.com")),
                _rows((table_id, "orders", None, [], NOW, "write", "ops")),
            ]
        )

        tables = await load_data_table_catalog(db, uuid.uuid4())

        self.assertEqual(len(tables), 1)
        self.assertEqual((tables[0].access, tables[0].shared_by), ("write", "ops"))

    async def test_a_shared_copy_of_an_owned_table_is_not_listed_twice(self) -> None:
        table_id = uuid.uuid4()
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _rows((table_id, "leads", None, [], NOW)),
                _rows(),
                _rows((table_id, "leads", None, [], NOW, "read", "ops")),
            ]
        )

        tables = await load_data_table_catalog(db, uuid.uuid4())

        self.assertEqual([(table.name, table.access) for table in tables], [("leads", "owner")])

    async def test_rows_are_never_queried(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows(), _rows(), _rows()])

        await load_data_table_catalog(db, uuid.uuid4())

        self.assertEqual(db.execute.await_count, 3)
        for call in db.execute.await_args_list:
            self.assertNotIn("data_table_rows", str(call.args[0]))

    async def test_prompt_is_built_even_without_tables(self) -> None:
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_rows(), _rows(), _rows()])

        prompt = await build_data_tables_prompt(db, uuid.uuid4(), ASK)

        self.assertIn("- The user has no data tables yet.", prompt)


class DataTablesPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.leads = _table("leads")
        self.orders = _table("orders", access="read", shared_by="ali@x.com")

    def test_lists_each_table_with_id_access_description_and_columns(self) -> None:
        prompt = format_data_tables_prompt([self.leads, self.orders], ASK)

        self.assertIn(
            f"- `leads` (id `{self.leads.id}`, owner): leads records. "
            "Columns: email string unique, name string",
            prompt,
        )
        self.assertIn(f"(id `{self.orders.id}`, read only, shared by ali@x.com)", prompt)

    def test_ask_prompt_asks_with_table_and_create_options(self) -> None:
        prompt = format_data_tables_prompt([self.leads], ASK)

        self.assertIn("overrides the `datatable-uuid` placeholder", prompt)
        self.assertIn("use it without asking", prompt)
        self.assertIn("one createTable option", prompt)
        self.assertIn('`Created data table "<name>" (id <id>)`', prompt)
        self.assertIn("Never change an existing table's columns", prompt)

    def test_apply_prompt_never_asks(self) -> None:
        prompt = format_data_tables_prompt([self.leads], APPLY)

        self.assertIn("You cannot ask questions in this step", prompt)
        self.assertNotIn("heym-clarify", prompt)
        self.assertIn("exact column names", prompt)

    def test_prompt_says_when_there_are_no_tables(self) -> None:
        self.assertIn("- The user has no data tables yet.", format_data_tables_prompt([], ASK))

    def test_prompt_caps_tables_columns_and_descriptions(self) -> None:
        wide = CatalogDataTable(
            uuid.uuid4(),
            "wide",
            "x" * 500,
            "owner",
            None,
            tuple(CatalogColumn(f"col_{i}", "string") for i in range(PROMPT_COLUMN_LIMIT + 5)),
        )
        tables = [wide, *(_table(f"t{i}") for i in range(PROMPT_TABLE_LIMIT + 2))]

        prompt = format_data_tables_prompt(tables, ASK)

        self.assertIn("and 5 more", prompt)
        self.assertNotIn("x" * 201, prompt)
        self.assertIn("- 3 more tables are not shown", prompt)


class ListDataTablesPayloadTests(unittest.TestCase):
    def test_payload_carries_columns_and_access_but_no_rows(self) -> None:
        leads = _table("leads")

        payload = list_data_tables_payload([leads])

        self.assertEqual(payload["count"], 1)
        self.assertFalse(payload["truncated"])
        self.assertEqual(
            payload["tables"][0],
            {
                "id": str(leads.id),
                "name": "leads",
                "description": "leads records",
                "access": "owner",
                "shared_by": None,
                "columns": [
                    {"name": "email", "type": "string", "required": False, "unique": True},
                    {"name": "name", "type": "string", "required": False, "unique": False},
                ],
            },
        )

    def test_payload_is_capped(self) -> None:
        payload = list_data_tables_payload([_table(f"t{i}") for i in range(TOOL_TABLE_LIMIT + 1)])

        self.assertEqual(payload["count"], TOOL_TABLE_LIMIT + 1)
        self.assertEqual(len(payload["tables"]), TOOL_TABLE_LIMIT)
        self.assertTrue(payload["truncated"])


if __name__ == "__main__":
    unittest.main()
