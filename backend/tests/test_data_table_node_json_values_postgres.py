"""dataTable node values holding a quote or a line break, against PostgreSQL.

The data and filter fields are JSON templates. Substituting a resolved value into the raw
text broke the JSON, and the node then fell back to {}: an empty row was inserted and a
find returned the whole table.
"""

import unittest
import uuid
from typing import Any

from sqlalchemy import delete, select, text

from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal
from app.services.workflow_executor import execute_workflow

TRICKY = 'Dana said "hi"\nsecond line'


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTableNodeJsonValuesPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.table_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"test-dt-json-{self.user_id}@example.com",
                    hashed_password="x",
                    name="Data table JSON",
                )
            )
            db.flush()
            db.add(
                DataTable(
                    id=self.table_id,
                    name=f"dt_json_{self.table_id.hex[:8]}",
                    owner_id=self.user_id,
                    columns=[
                        {"name": "name", "type": "string"},
                        {"name": "status", "type": "string"},
                        {"name": "age", "type": "number"},
                    ],
                )
            )
            db.flush()
            for name, age in (("Ada", 36), ("Ben", 17), ("Cy", 52)):
                db.add(
                    DataTableRow(
                        table_id=self.table_id,
                        data={"name": name, "status": "done", "age": age},
                    )
                )
            db.commit()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            db.execute(delete(DataTableRow).where(DataTableRow.table_id == self.table_id))
            db.execute(delete(DataTable).where(DataTable.id == self.table_id))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def _run(
        self, operation: str, inputs: dict[str, Any], upstream: str = "start", **fields: str
    ) -> dict[str, Any]:
        node = self._node(operation, inputs, upstream, **fields)
        self.assertEqual(node["status"], "success", node)
        return node["output"]

    def _node(
        self, operation: str, inputs: dict[str, Any], upstream: str = "start", **fields: str
    ) -> dict[str, Any]:
        nodes = [
            {"id": "start", "type": "textInput", "data": {"label": upstream}},
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "table",
                    "dataTableId": str(self.table_id),
                    "dataTableOperation": operation,
                    **fields,
                },
            },
        ]
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=[{"id": "e1", "source": "start", "target": "dt"}],
            inputs=inputs,
            actor_user_id=self.user_id,
        )
        return next(r for r in result.node_results if r.get("node_id") == "dt")

    def _stored(self) -> list[dict]:
        with SessionLocal() as db:
            rows = db.execute(
                select(DataTableRow.data).where(DataTableRow.table_id == self.table_id)
            )
            return [row[0] for row in rows.all()]

    def test_insert_keeps_a_value_with_a_quote_and_a_line_break(self) -> None:
        self._run(
            "insert",
            {"text": TRICKY},
            dataTableData='{"name": "$start.text", "status": "pending"}',
        )

        self.assertIn({"name": TRICKY, "status": "pending"}, self._stored())
        self.assertNotIn({}, self._stored())

    def test_find_and_count_apply_a_filter_with_such_a_value(self) -> None:
        found = self._run("find", {"text": TRICKY}, dataTableFilter='{"name": "$start.text"}')
        counted = self._run("count", {"text": TRICKY}, dataTableFilter='{"name": "$start.text"}')

        self.assertEqual(found["rows"], [])
        self.assertEqual(counted["count"], 0)

    def test_an_unquoted_expression_is_still_substituted_first(self) -> None:
        self._run(
            "insert",
            {"text": "Eve", "age": "41"},
            dataTableData='{"name": "$start.text", "age": $start.age}',
        )

        self.assertIn({"name": "Eve", "age": 41}, self._stored())

    def test_operator_filters_still_apply(self) -> None:
        found = self._run("find", {"text": "x"}, dataTableFilter='{"age": {"$gt": 18}}')

        self.assertEqual(sorted(row["data"]["name"] for row in found["rows"]), ["Ada", "Cy"])

    def test_an_operator_key_stays_an_operator_next_to_a_node_of_that_name(self) -> None:
        cases = (
            ("gt", '{"age": {"$gt": 18}}', ["Ada", "Cy"]),
            ("in", '{"name": {"$in": ["Ben", "Cy"]}}', ["Ben", "Cy"]),
            ("contains", '{"name": {"$contains": "d"}}', ["Ada"]),
        )
        for upstream, filter_template, want in cases:
            with self.subTest(upstream=upstream):
                found = self._run(
                    "find", {"text": "x"}, upstream=upstream, dataTableFilter=filter_template
                )
                names = sorted(row["data"]["name"] for row in found["rows"])
                self.assertEqual(names, want)

    def test_a_key_with_a_path_still_resolves(self) -> None:
        found = self._run(
            "find", {"text": "x", "column": "name"}, dataTableFilter='{"$start.column": "Ben"}'
        )

        self.assertEqual([row["data"]["name"] for row in found["rows"]], ["Ben"])

    def test_row_data_that_is_not_json_once_filled_in_fails_the_insert(self) -> None:
        # The unquoted form with a value the request left out stays as text: not JSON.
        node = self._node(
            "insert",
            {"text": "Eve"},
            dataTableData='{"name": "$start.text", "age": $start.age}',
        )

        self.assertEqual(node["status"], "error")
        self.assertIn("DataTable insert: the row data is not valid JSON", node["error"])
        self.assertNotIn({}, self._stored())
        self.assertEqual(len(self._stored()), 3)

    def test_a_filter_that_is_not_json_fails_instead_of_matching_every_row(self) -> None:
        for operation in ("find", "count", "upsert"):
            with self.subTest(operation=operation):
                node = self._node(
                    operation,
                    {"text": "Eve"},
                    dataTableFilter='{"age": $start.age}',
                    dataTableData='{"name": "Eve"}',
                )

                self.assertEqual(node["status"], "error")
                self.assertIn(f"DataTable {operation}: the filter is not valid JSON", node["error"])
        self.assertEqual(len(self._stored()), 3)

    def test_a_blank_filter_still_finds_every_row(self) -> None:
        found = self._run("find", {"text": "x"}, dataTableFilter="")

        self.assertEqual(len(found["rows"]), 3)


if __name__ == "__main__":
    unittest.main()
