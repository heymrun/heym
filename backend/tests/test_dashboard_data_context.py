"""What the page planner and the widget builder learn about the data tables a page uses."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import dashboard_data_context as context
from app.services.dashboard_data_context import (
    ColumnProfile,
    TableContext,
    TableUnavailableError,
    describe_tables,
    profile_columns,
)

COLUMNS = [
    {"name": "amount", "type": "number", "order": 1},
    {"name": "vendor_source", "type": "string", "order": 0},
]
ROWS = [
    {"vendor_source": "Google", "amount": 120},
    {"vendor_source": "Meta", "amount": 80.5},
    {"vendor_source": "Google", "amount": 40},
    {"vendor_source": "", "amount": None},
]


class ProfileColumnsTests(unittest.TestCase):
    def test_text_columns_get_their_top_values_and_numbers_their_range(self) -> None:
        self.assertEqual(
            profile_columns(COLUMNS, ROWS),
            [
                ColumnProfile("vendor_source", "string", [("Google", 2), ("Meta", 1)], 2),
                ColumnProfile("amount", "number", minimum=40.0, maximum=120.0),
            ],
        )

    def test_a_column_without_values_still_shows(self) -> None:
        self.assertEqual(
            profile_columns([{"name": "note", "type": "string"}], []),
            [ColumnProfile("note", "string", [], 0)],
        )


class DescribeTablesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.table = TableContext(
            id=uuid.UUID(int=7),
            name="Invoices",
            profiled_rows=3,
            columns=profile_columns(COLUMNS, ROWS),
            examples=[ROWS[0]],
        )

    def test_the_planner_sees_values_counts_and_example_rows(self) -> None:
        text = describe_tables([self.table], with_data=True)

        self.assertIn(f'"Invoices" (dataTableId: {uuid.UUID(int=7)}', text)
        self.assertIn("vendor_source (string): Google (2), Meta (1)", text)
        self.assertIn("amount (number): from 40 to 120", text)
        self.assertIn("'vendor_source': 'Google'", text)

    def test_the_builder_sees_the_id_and_the_columns_only(self) -> None:
        text = describe_tables([self.table], with_data=False)

        self.assertIn("dataTableId", text)
        self.assertIn("  - vendor_source (string)", text)
        self.assertNotIn("Google", text)

    def test_no_tables_is_no_text(self) -> None:
        self.assertEqual(describe_tables([], with_data=True), "")


class LoadTableContextsTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_unreadable_table_is_refused(self) -> None:
        with patch.object(context, "get_data_table_with_permission", AsyncMock(return_value=None)):
            with self.assertRaises(TableUnavailableError):
                await context.load_table_contexts(MagicMock(), [uuid.uuid4()], uuid.uuid4())

    async def test_a_readable_table_is_profiled_from_its_rows(self) -> None:
        table = MagicMock(id=uuid.uuid4(), columns=COLUMNS)
        table.name = "Invoices"
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: ROWS)))
        )

        with patch.object(
            context, "get_data_table_with_permission", AsyncMock(return_value=(table, "read"))
        ):
            tables = await context.load_table_contexts(db, [table.id, table.id], uuid.uuid4())

        self.assertEqual(len(tables), 1)
        self.assertEqual((tables[0].name, tables[0].profiled_rows), ("Invoices", 4))
        self.assertEqual(tables[0].columns[0].top_values, [("Google", 2), ("Meta", 1)])
