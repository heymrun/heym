"""Direct table actions enforce sharing and use the UI's data mutation paths."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import chat_data_tables as chat
from app.api import data_tables
from app.db.models import DataTable, DataTableRow
from app.models.schemas import DataTableColumnDef, DataTableUpdate


class ChatDataTableTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4(), email="writer@example.com")
        self.table = DataTable(
            id=uuid.uuid4(),
            name="names",
            owner_id=self.user.id,
            columns=[DataTableColumnDef(name="email", unique=True).model_dump(mode="json")],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.row = DataTableRow(
            id=uuid.uuid4(),
            table_id=self.table.id,
            data={"email": "ada@example.com"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.db = MagicMock()
        self.db.flush = AsyncMock()
        self.db.refresh = AsyncMock()
        self.db.delete = AsyncMock()
        self.db.execute = AsyncMock(return_value=self._result())
        self.permission = patch.object(
            data_tables,
            "get_data_table_with_permission",
            AsyncMock(return_value=(self.table, "owner")),
        ).start()
        self.addCleanup(patch.stopall)

    def _result(self) -> MagicMock:
        return MagicMock(
            scalar=MagicMock(return_value=1),
            scalar_one_or_none=MagicMock(return_value=self.row),
            scalars=MagicMock(return_value=SimpleNamespace(all=lambda: [self.row])),
        )

    async def _call(self, name: str, **args: object) -> dict:
        return await chat.call_data_table_tool(
            self.db, self.user, name, {"table_id": str(self.table.id), **args}
        )

    async def test_example_url_adds_two_columns_and_keeps_existing_data(self) -> None:
        original = dict(self.table.columns[0])
        result = await self._call(
            "add_data_table_columns",
            table_id=f"https://heym.akgns.com/?tab=datatable/{self.table.id}",
            columns=[{"name": "name"}, {"name": "surname"}],
        )

        self.assertTrue(result["updated"])
        self.assertEqual([c["name"] for c in self.table.columns], ["email", "name", "surname"])
        self.assertEqual(self.table.columns[0], original)
        self.assertEqual(self.row.data, {"email": "ada@example.com"})
        self.assertEqual([c["order"] for c in self.table.columns], [0, 1, 2])
        self.assertEqual(self.table.columns[1]["type"], "string")

    async def test_shared_writer_can_add_and_remove_columns(self) -> None:
        self.table.owner_id = uuid.uuid4()
        self.permission.return_value = (self.table, "write")
        result = await self._call("add_data_table_columns", columns=[{"name": "surname"}])
        self.assertTrue(result["updated"])
        result = await self._call(
            "remove_data_table_columns", column_names=["email"], confirmed=True
        )
        self.assertTrue(result["updated"])
        self.assertEqual(self.row.data, {})
        self.assertEqual(self.row.updated_by, self.user.id)

    async def test_read_only_and_inaccessible_tables_reject_every_write(self) -> None:
        actions = {
            "add_data_table_columns": {"columns": [{"name": "name"}]},
            "remove_data_table_columns": {"column_names": ["email"], "confirmed": True},
            "insert_data_table_rows": {"rows": [{"email": "new@example.com"}]},
            "update_data_table_row": {"row_id": str(self.row.id), "data": {"email": "new"}},
            "delete_data_table_row": {"row_id": str(self.row.id)},
            "clear_data_table_rows": {"confirmed": True},
        }
        for permission in [(self.table, "read"), None]:
            self.permission.return_value = permission
            for name, args in actions.items():
                with self.subTest(permission=permission, action=name):
                    result = await self._call(name, **args)
                    self.assertEqual(
                        result["error"],
                        "Write access required" if permission else "Data table not found",
                    )
        self.db.add.assert_not_called()
        self.db.delete.assert_not_awaited()
        self.db.flush.assert_not_awaited()

    async def test_read_only_user_can_inspect_and_read_rows(self) -> None:
        self.permission.return_value = (self.table, "read")
        result = await self._call("get_data_table")
        self.assertEqual(result["table"]["row_count"], 1)
        result = await self._call("list_data_table_rows")
        self.assertEqual(result["rows"][0]["data"], self.row.data)

    async def test_remove_columns_requires_confirmation_and_prunes_only_selected_values(
        self,
    ) -> None:
        self.table.columns.append(DataTableColumnDef(name="surname").model_dump(mode="json"))
        self.row.data = {"email": "ada@example.com", "surname": "Lovelace"}
        result = await self._call("remove_data_table_columns", column_names=["surname"])
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["row_count"], 1)
        self.assertIn("cannot be undone", result["warning"])
        self.assertIn("surname", self.row.data)
        self.db.flush.assert_not_awaited()

        result = await self._call(
            "remove_data_table_columns", column_names=["surname"], confirmed=True
        )
        self.assertTrue(result["updated"])
        self.assertEqual(self.row.data, {"email": "ada@example.com"})

    async def test_clear_rows_requires_confirmation_and_uses_the_route_after_confirmation(
        self,
    ) -> None:
        with patch.object(data_tables, "clear_rows", AsyncMock()) as clear:
            result = await self._call("clear_data_table_rows")
            self.assertTrue(result["requires_confirmation"])
            clear.assert_not_awaited()
            result = await self._call("clear_data_table_rows", confirmed=True)
            self.assertEqual(result, {"cleared": True, "deleted_count": 1})
            clear.assert_awaited_once_with(self.table.id, current_user=self.user, db=self.db)

    async def test_invalid_and_duplicate_columns_do_not_mutate_schema(self) -> None:
        for columns in [
            [{"name": "Email"}],
            [{"name": "name"}, {"name": "NAME"}],
            [{"name": " "}],
            [{"name": "name", "type": "invalid"}],
            [],
        ]:
            with self.subTest(columns=columns):
                result = await self._call("add_data_table_columns", columns=columns)
                self.assertIn("error", result)
        self.assertEqual(len(self.table.columns), 1)
        self.db.flush.assert_not_awaited()

    async def test_unknown_removed_column_is_rejected(self) -> None:
        result = await self._call(
            "remove_data_table_columns", column_names=["not_a_column"], confirmed=True
        )
        self.assertIn("Unknown columns", result["error"])
        self.db.flush.assert_not_awaited()

    async def test_insert_applies_defaults_coercion_and_reports_partial_validation_errors(
        self,
    ) -> None:
        self.table.columns = [
            DataTableColumnDef(name="name", required=True).model_dump(mode="json"),
            DataTableColumnDef(name="age", type="number", defaultValue=42).model_dump(mode="json"),
        ]
        result = await self._call(
            "insert_data_table_rows",
            rows=[{"name": "Ada", "age": "36"}, {"name": "Ben"}, {"age": "bad"}],
        )
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["row"], 3)
        inserted = [call.args[0].data for call in self.db.add.call_args_list]
        self.assertEqual(inserted, [{"name": "Ada", "age": 36}, {"name": "Ben", "age": 42}])

    async def test_insert_enforces_unique_validation(self) -> None:
        with patch.object(
            data_tables, "_check_unique_constraints", AsyncMock(return_value=["Duplicate email"])
        ) as unique:
            result = await self._call("insert_data_table_rows", rows=[dict(self.row.data)])
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["errors"][0]["errors"], ["Duplicate email"])
        unique.assert_awaited_once()
        self.db.add.assert_not_called()

    async def test_update_preserves_other_fields_and_reuses_unique_validation(self) -> None:
        self.table.columns.append(DataTableColumnDef(name="name").model_dump(mode="json"))
        with patch.object(
            data_tables, "_check_unique_constraints", AsyncMock(return_value=[])
        ) as unique:
            result = await self._call(
                "update_data_table_row", row_id=str(self.row.id), data={"name": "Ada"}
            )
        self.assertEqual(result["row"]["data"], {"email": "ada@example.com", "name": "Ada"})
        self.assertEqual(unique.await_args.kwargs["exclude_row_id"], self.row.id)

    async def test_delete_row_is_scoped_to_the_requested_table(self) -> None:
        self.db.execute.return_value.scalar_one_or_none.return_value = None
        result = await self._call("delete_data_table_row", row_id=str(self.row.id))
        self.assertEqual(result["error"], "Row not found")
        statement = self.db.execute.await_args.args[0]
        self.assertIn("data_table_rows.table_id =", str(statement))
        self.assertIn(self.table.id, statement.compile().params.values())
        self.db.delete.assert_not_awaited()

    async def test_requested_single_row_deletion_needs_no_extra_confirmation(self) -> None:
        result = await self._call("delete_data_table_row", row_id=str(self.row.id))
        self.assertTrue(result["deleted"])
        self.db.delete.assert_awaited_once_with(self.row)

    async def test_row_pagination_is_bounded_and_reports_next_page(self) -> None:
        result = await self._call("list_data_table_rows", limit=1, offset=0)
        self.assertFalse(result["has_more"])
        self.db.execute.return_value.scalars.return_value.all = lambda: [self.row, self.row]
        result = await self._call("list_data_table_rows", limit=1)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_offset"], 1)
        self.assertEqual(len(result["rows"]), 1)
        for args in [{"limit": 0}, {"limit": 101}, {"offset": -1}]:
            self.assertIn("error", await self._call("list_data_table_rows", **args))

    async def test_bad_table_links_and_row_ids_do_not_query_tables(self) -> None:
        for reference in ["bad", "https://heym.example/?tab=datatable/llm-pricing"]:
            result = await self._call("get_data_table", table_id=reference)
            self.assertIn("error", result)
        result = await self._call("delete_data_table_row", row_id="bad")
        self.assertIn("error", result)
        self.permission.assert_not_awaited()

    async def test_shared_writer_cannot_rename_table_even_with_a_column_change(self) -> None:
        self.table.owner_id = uuid.uuid4()
        self.permission.return_value = (self.table, "write")
        with self.assertRaises(HTTPException) as error:
            await data_tables.update_data_table(
                self.table.id,
                DataTableUpdate(name="renamed", columns=[]),
                current_user=self.user,
                db=self.db,
            )
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.table.name, "names")
        self.assertEqual(len(self.table.columns), 1)
