"""A null in a Data Table filter matches empty cells, not the text "None".

Every value for a data column was compared as str(value), so `{"note": null}` compiled to
`data ->> 'note' = 'None'`: it found a cell holding the text "None" and none of the null or
missing cells, and `{"$ne": null}` left that cell out.
"""

import json
import unittest
import uuid

from sqlalchemy import delete, select, text

from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal
from app.services.data_table_filters import build_data_table_filter_clauses
from app.services.workflow_executor import execute_workflow

COLUMNS = [
    {"name": "name", "type": "string"},
    {"name": "note", "type": "string"},
    {"name": "done", "type": "boolean"},
]

ROWS = (
    {"name": "a", "note": None, "done": None},
    {"name": "b", "note": "x", "done": True},
    {"name": "c"},
    {"name": "d", "note": "", "done": False},
    {"name": "e", "note": "None", "done": True},
)


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTableNullFilterPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.table_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"test-null-filter-{self.user_id}@example.com",
                    hashed_password="hashed_pw",
                    name="Null Filter Tester",
                )
            )
            db.flush()
            db.add(
                DataTable(
                    id=self.table_id,
                    name=f"null_filter_{self.table_id.hex[:8]}",
                    owner_id=self.user_id,
                    columns=COLUMNS,
                )
            )
            db.flush()
            for data in ROWS:
                db.add(DataTableRow(table_id=self.table_id, data=data))
            db.commit()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            db.execute(delete(DataTableRow).where(DataTableRow.table_id == self.table_id))
            db.execute(delete(DataTable).where(DataTable.id == self.table_id))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def _find(self, filter_dict: dict) -> list[str]:
        clauses = build_data_table_filter_clauses(filter_dict, COLUMNS)
        with SessionLocal() as db:
            rows = db.execute(
                select(DataTableRow.data).where(DataTableRow.table_id == self.table_id, *clauses)
            )
            return sorted(data["name"] for data in rows.scalars().all())

    def test_null_matches_null_and_missing_cells(self) -> None:
        self.assertEqual(self._find({"note": None}), ["a", "c"])
        self.assertEqual(self._find({"note": {"$eq": None}}), ["a", "c"])
        self.assertEqual(self._find({"done": None}), ["a", "c"])

    def test_ne_null_matches_cells_that_hold_a_value(self) -> None:
        self.assertEqual(self._find({"note": {"$ne": None}}), ["b", "d", "e"])

    def test_in_with_null(self) -> None:
        self.assertEqual(self._find({"note": {"$in": ["x", None]}}), ["a", "b", "c"])

    def test_upsert_with_a_null_filter_updates_a_row_with_an_empty_cell(self) -> None:
        # `{"note": null}` finds a row whose note is null or missing, so the upsert updates
        # that row instead of inserting one. A cell holding "" is not matched.
        nodes = [
            {"id": "start", "type": "textInput", "data": {"label": "start"}},
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "table",
                    "dataTableId": str(self.table_id),
                    "dataTableOperation": "upsert",
                    "dataTableFilter": json.dumps({"note": None}),
                    "dataTableData": json.dumps({"note": "filled"}),
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
        node = next(r for r in result.node_results if r.get("node_id") == "dt")
        self.assertEqual(node["status"], "success", node)
        self.assertEqual(node["output"]["operation"], "update")
        with SessionLocal() as db:
            rows = (
                db.execute(select(DataTableRow.data).where(DataTableRow.table_id == self.table_id))
                .scalars()
                .all()
            )
        self.assertEqual(len(rows), len(ROWS))
        filled = [data["name"] for data in rows if data.get("note") == "filled"]
        self.assertEqual(len(filled), 1)
        self.assertIn(filled[0], {"a", "c"})

    def test_values_still_match_as_text(self) -> None:
        self.assertEqual(self._find({"note": "None"}), ["e"])
        self.assertEqual(self._find({"note": ""}), ["d"])
        self.assertEqual(self._find({"done": True}), ["b", "e"])
        self.assertEqual(self._find({"note": {"$ne": "x"}}), ["d", "e"])


if __name__ == "__main__":
    unittest.main()
