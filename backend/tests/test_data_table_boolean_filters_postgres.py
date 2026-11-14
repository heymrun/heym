import unittest
import uuid
from typing import Any

from sqlalchemy import delete, func, select, text

from app.api.data_tables import _coerce_row_data
from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal
from app.services.workflow_executor import WorkflowExecutor


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTablePostgreSqlBooleanFilterIntegrationTests(unittest.TestCase):
    """PostgreSQL integration tests covering issue #914 boolean filter & upsert criteria:

    - Boolean columns (stored in JSON):
      - Plain equality filters: true and false.
      - Comparison operators: $eq, $ne.
      - List inclusion operator: $in.
      - Both find and count operations.
    - Backward compatibility:
      - String columns storing "True" or "False" continue matching boolean filter literals.
    - Null and missing value handling:
      - Explicit null boolean fields and missing field rows.
      - Null filters never match rows where the boolean field is false.
      - Unknown columns do not produce false-positive matches.
    - Upsert operations:
      - Boolean-false keyed upsert updates existing matching row, retains row ID, avoids duplicates.
      - Boolean-true keyed upsert updates existing matching row, retains row ID, avoids duplicates.
      - Non-matching boolean-keyed upsert inserts a new row.
      - String-keyed upsert continues functioning as expected.
    """

    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")

        self.user_id = uuid.uuid4()
        self.table_id = uuid.uuid4()
        self.single_true_table_id = uuid.uuid4()

        self.columns = [
            {"name": "name", "type": "string"},
            {"name": "is_active", "type": "boolean"},
            {"name": "legacy_flag", "type": "string"},
        ]

        with SessionLocal() as db:
            user = User(
                id=self.user_id,
                email=f"test-boolean-{self.user_id}@example.com",
                hashed_password="hashed_pw",
                name="Boolean Tester",
            )
            db.add(user)
            db.flush()

            table = DataTable(
                id=self.table_id,
                name=f"bool_test_table_{self.table_id.hex[:8]}",
                owner_id=user.id,
                columns=self.columns,
            )
            db.add(table)
            db.flush()

            # Row 1: Alice (is_active=True, legacy_flag coerced from True -> "True")
            data_alice, _ = _coerce_row_data(
                {"name": "Alice", "is_active": True, "legacy_flag": True},
                self.columns,
            )
            self.row_alice = DataTableRow(
                id=uuid.uuid4(),
                table_id=table.id,
                data=data_alice,
            )

            # Row 2: Bob (is_active=False, legacy_flag coerced from False -> "False")
            data_bob, _ = _coerce_row_data(
                {"name": "Bob", "is_active": False, "legacy_flag": False},
                self.columns,
            )
            self.row_bob = DataTableRow(
                id=uuid.uuid4(),
                table_id=table.id,
                data=data_bob,
            )

            # Row 3: Charlie (is_active=None explicitly null, legacy_flag="other")
            data_charlie, _ = _coerce_row_data(
                {"name": "Charlie", "is_active": None, "legacy_flag": "other"},
                self.columns,
            )
            self.row_charlie = DataTableRow(
                id=uuid.uuid4(),
                table_id=table.id,
                data=data_charlie,
            )

            # Row 4: Dave (missing is_active key, legacy_flag="True")
            data_dave, _ = _coerce_row_data(
                {"name": "Dave", "legacy_flag": "True"},
                self.columns,
            )
            self.row_dave = DataTableRow(
                id=uuid.uuid4(),
                table_id=table.id,
                data=data_dave,
            )

            # Row 5: Eve (is_active=True, legacy_flag="something")
            data_eve, _ = _coerce_row_data(
                {"name": "Eve", "is_active": True, "legacy_flag": "something"},
                self.columns,
            )
            self.row_eve = DataTableRow(
                id=uuid.uuid4(),
                table_id=table.id,
                data=data_eve,
            )

            db.add_all(
                [
                    self.row_alice,
                    self.row_bob,
                    self.row_charlie,
                    self.row_dave,
                    self.row_eve,
                ]
            )

            # Dedicated isolated table containing a single row with is_active: True
            single_true_table = DataTable(
                id=self.single_true_table_id,
                name=f"single_true_table_{self.single_true_table_id.hex[:8]}",
                owner_id=user.id,
                columns=self.columns,
            )
            db.add(single_true_table)
            db.flush()

            data_only_true, _ = _coerce_row_data(
                {"name": "Existing True Only", "is_active": True, "legacy_flag": "initial"},
                self.columns,
            )
            self.row_only_true = DataTableRow(
                id=uuid.uuid4(),
                table_id=single_true_table.id,
                data=data_only_true,
            )
            db.add(self.row_only_true)

            db.commit()

    def tearDown(self) -> None:
        if not _is_db_reachable():
            return
        with SessionLocal() as db:
            table_ids = [self.table_id, self.single_true_table_id]
            db.execute(delete(DataTableRow).where(DataTableRow.table_id.in_(table_ids)))
            db.execute(delete(DataTable).where(DataTable.id.in_(table_ids)))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def _execute_dt(
        self,
        op: str,
        filter_str: str = "{}",
        data_str: str = "{}",
        table_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        target_table_id = table_id or self.table_id
        node_data: dict[str, Any] = {
            "label": "dt",
            "dataTableId": str(target_table_id),
            "dataTableOperation": op,
            "dataTableFilter": filter_str,
            "dataTableData": data_str,
        }
        nodes = [{"id": "dt", "type": "dataTable", "data": node_data}]
        executor = WorkflowExecutor(nodes=nodes, edges=[], actor_user_id=self.user_id)
        result = executor.execute_node("dt", {})
        self.assertEqual(result.status, "success")
        output: dict[str, Any] = result.output  # type: ignore[assignment]
        return output

    # ── Boolean Filtering Tests ──────────────────────────────────────────────

    def test_boolean_filter_plain_true_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": true}')
        rows = output["rows"]
        names = sorted([r["data"]["name"] for r in rows])
        self.assertEqual(names, ["Alice", "Eve"])
        self.assertNotIn("Dave", names)
        self.assertEqual(output["count"], 2)

    def test_boolean_filter_plain_false_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": false}')
        rows = output["rows"]
        names = [r["data"]["name"] for r in rows]
        self.assertEqual(names, ["Bob"])
        self.assertNotIn("Dave", names)
        self.assertEqual(output["count"], 1)

    def test_boolean_filter_plain_true_count(self) -> None:
        output = self._execute_dt("count", filter_str='{"is_active": true}')
        self.assertEqual(output["count"], 2)

    def test_boolean_filter_plain_false_count(self) -> None:
        output = self._execute_dt("count", filter_str='{"is_active": false}')
        self.assertEqual(output["count"], 1)

    def test_boolean_filter_eq_true_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": {"$eq": true}}')
        rows = output["rows"]
        names = sorted([r["data"]["name"] for r in rows])
        self.assertEqual(names, ["Alice", "Eve"])
        self.assertNotIn("Dave", names)

    def test_boolean_filter_eq_false_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": {"$eq": false}}')
        rows = output["rows"]
        names = [r["data"]["name"] for r in rows]
        self.assertEqual(names, ["Bob"])
        self.assertNotIn("Dave", names)

    def test_boolean_filter_ne_true_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": {"$ne": true}}')
        rows = output["rows"]
        names = sorted([r["data"]["name"] for r in rows])
        self.assertEqual(names, ["Bob"])
        self.assertNotIn("Alice", names)
        self.assertNotIn("Eve", names)
        self.assertNotIn("Dave", names)
        self.assertNotIn("Charlie", names)
        self.assertEqual(output["count"], 1)

    def test_boolean_filter_ne_false_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": {"$ne": false}}')
        rows = output["rows"]
        names = sorted([r["data"]["name"] for r in rows])
        self.assertEqual(names, ["Alice", "Eve"])
        self.assertNotIn("Bob", names)
        self.assertNotIn("Dave", names)
        self.assertNotIn("Charlie", names)
        self.assertEqual(output["count"], 2)

    def test_boolean_filter_in_single_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": {"$in": [true]}}')
        rows = output["rows"]
        names = sorted([r["data"]["name"] for r in rows])
        self.assertEqual(names, ["Alice", "Eve"])
        self.assertNotIn("Dave", names)

    def test_boolean_filter_in_multiple_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": {"$in": [true, false]}}')
        rows = output["rows"]
        names = sorted([r["data"]["name"] for r in rows])
        self.assertEqual(names, ["Alice", "Bob", "Eve"])
        self.assertNotIn("Dave", names)
        self.assertNotIn("Charlie", names)

    # ── Backward Compatibility Tests ─────────────────────────────────────────

    def test_string_column_holding_capital_true_backward_compat(self) -> None:
        output = self._execute_dt("find", filter_str='{"legacy_flag": true}')
        rows = output["rows"]
        names = sorted([r["data"]["name"] for r in rows])
        self.assertEqual(names, ["Alice", "Dave"])

    def test_string_column_holding_capital_false_backward_compat(self) -> None:
        output = self._execute_dt("find", filter_str='{"legacy_flag": false}')
        rows = output["rows"]
        names = [r["data"]["name"] for r in rows]
        self.assertEqual(names, ["Bob"])

    # ── Null & Missing Values Tests ──────────────────────────────────────────

    def test_null_filter_does_not_match_false_rows(self) -> None:
        output = self._execute_dt("find", filter_str='{"is_active": null}')
        rows = output["rows"]
        names = [r["data"]["name"] for r in rows]
        self.assertNotIn("Bob", names)

    def test_unknown_column_filter_find(self) -> None:
        output = self._execute_dt("find", filter_str='{"missing_field": true}')
        self.assertEqual(output["rows"], [])
        self.assertEqual(output["count"], 0)

    # ── Upsert Tests ─────────────────────────────────────────────────────────

    def test_upsert_boolean_false_key_updates_existing_row(self) -> None:
        with SessionLocal() as db:
            initial_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.table_id)
            )

        output = self._execute_dt(
            op="upsert",
            filter_str='{"is_active": false}',
            data_str='{"name": "Bob Updated", "legacy_flag": "reviewed"}',
        )

        self.assertEqual(output["operation"], "update")
        self.assertEqual(output["id"], str(self.row_bob.id))

        with SessionLocal() as db:
            updated_row = db.scalar(select(DataTableRow).where(DataTableRow.id == self.row_bob.id))
            self.assertIsNotNone(updated_row)
            assert updated_row is not None
            self.assertEqual(updated_row.data.get("name"), "Bob Updated")
            self.assertEqual(updated_row.data.get("legacy_flag"), "reviewed")

            final_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.table_id)
            )
            self.assertEqual(final_count, initial_count)

    def test_upsert_boolean_true_key_updates_existing_row(self) -> None:
        with SessionLocal() as db:
            initial_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.single_true_table_id)
            )
            self.assertEqual(initial_count, 1)

        output = self._execute_dt(
            op="upsert",
            filter_str='{"is_active": true}',
            data_str='{"name": "True Row Updated", "legacy_flag": "active_updated"}',
            table_id=self.single_true_table_id,
        )

        self.assertEqual(output["operation"], "update")
        self.assertEqual(output["id"], str(self.row_only_true.id))

        with SessionLocal() as db:
            updated_row = db.scalar(
                select(DataTableRow).where(DataTableRow.id == self.row_only_true.id)
            )
            self.assertIsNotNone(updated_row)
            assert updated_row is not None
            self.assertEqual(updated_row.data.get("name"), "True Row Updated")
            self.assertEqual(updated_row.data.get("legacy_flag"), "active_updated")

            final_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.single_true_table_id)
            )
            self.assertEqual(final_count, initial_count)

    def test_upsert_boolean_key_inserts_when_no_match(self) -> None:
        with SessionLocal() as db:
            initial_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.single_true_table_id)
            )
            self.assertEqual(initial_count, 1)

        output = self._execute_dt(
            op="upsert",
            filter_str='{"is_active": false}',
            data_str='{"name": "Frank", "is_active": false, "legacy_flag": "new"}',
            table_id=self.single_true_table_id,
        )

        self.assertEqual(output["operation"], "insert")
        new_row_id = output["id"]
        self.assertNotEqual(new_row_id, str(self.row_only_true.id))

        with SessionLocal() as db:
            final_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.single_true_table_id)
            )
            self.assertEqual(final_count, 2)

    def test_upsert_string_key_backward_compatibility(self) -> None:
        with SessionLocal() as db:
            initial_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.table_id)
            )

        output = self._execute_dt(
            op="upsert",
            filter_str='{"name": "Alice"}',
            data_str='{"name": "Alice", "legacy_flag": "active_confirmed"}',
        )

        self.assertEqual(output["operation"], "update")
        self.assertEqual(output["id"], str(self.row_alice.id))

        with SessionLocal() as db:
            final_count = db.scalar(
                select(func.count())
                .select_from(DataTableRow)
                .where(DataTableRow.table_id == self.table_id)
            )
            self.assertEqual(final_count, initial_count)
