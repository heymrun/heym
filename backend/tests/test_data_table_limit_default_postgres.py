"""A Data Table find or getAll without `dataTableLimit` returns every matching row.

The node page and the AI builder's DSL said the limit defaulted to 100, while the editor
says "Leave empty for no limit" and the node applies no limit. A builder that left the
field out expecting 100 rows got the whole table.
"""

import re
import unittest
import uuid
from pathlib import Path

from sqlalchemy import delete, text

from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import WorkflowExecutor

ROWS = 105


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTableLimitDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.table_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"test-limit-{self.user_id}@example.com",
                    hashed_password="hashed_pw",
                    name="Limit Tester",
                )
            )
            db.flush()
            db.add(
                DataTable(
                    id=self.table_id,
                    name=f"limit_test_table_{self.table_id}",
                    owner_id=self.user_id,
                    columns=[{"name": "n", "type": "number"}],
                )
            )
            db.flush()
            db.add_all(
                DataTableRow(table_id=self.table_id, data={"n": i}, created_by=self.user_id)
                for i in range(ROWS)
            )
            db.commit()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            db.execute(delete(DataTableRow).where(DataTableRow.table_id == self.table_id))
            db.execute(delete(DataTable).where(DataTable.id == self.table_id))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def _count(self, operation: str, **extra: object) -> int:
        node_data = {
            "label": "dt",
            "dataTableId": str(self.table_id),
            "dataTableOperation": operation,
            **extra,
        }
        nodes = [{"id": "dt", "type": "dataTable", "data": node_data}]
        result = WorkflowExecutor(nodes=nodes, edges=[], actor_user_id=self.user_id).execute_node(
            "dt", {}
        )
        self.assertEqual(result.status, "success")
        return result.output["count"]

    def test_no_limit_returns_every_row(self) -> None:
        for operation in ("find", "getAll"):
            for extra in ({}, {"dataTableLimit": None}, {"dataTableLimit": 0}):
                with self.subTest(operation=operation, extra=extra):
                    self.assertEqual(self._count(operation, **extra), ROWS)

    def test_a_limit_caps_the_rows(self) -> None:
        self.assertEqual(self._count("getAll", dataTableLimit=10), 10)


class DataTableLimitDocsTests(unittest.TestCase):
    """Reads only the DSL prompt and the node page, so it runs without a database."""

    def test_the_dsl_does_not_promise_a_default_limit(self) -> None:
        line = re.search(r"`dataTableLimit`:[^\n]*", WORKFLOW_DSL_SYSTEM_PROMPT)
        assert line is not None

        self.assertNotIn("default", line.group(0))
        self.assertIn("every matching row", line.group(0))

    def test_the_page_names_the_canvas_start_and_no_limit(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend/src/docs/content/nodes/datatable-node.md"
        ).read_text(encoding="utf-8")
        row = next(line for line in page.splitlines() if line.startswith("| `dataTableLimit`"))

        self.assertIn("starts at `100`", row)
        self.assertIn("every matching row", row)


if __name__ == "__main__":
    unittest.main()
