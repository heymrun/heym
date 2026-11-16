import unittest
import uuid

from sqlalchemy import delete, select, text

from app.api.data_tables import _coerce_row_data
from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal
from app.services.data_table_filters import build_data_table_filter_clauses

COLUMNS = [
    {"name": "sku", "type": "string"},
    {"name": "price", "type": "number"},
]


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTableNumberFilterPostgresTests(unittest.TestCase):
    """Number columns compare as numbers, against rows as the CSV import stores them."""

    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.table_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"test-number-filter-{self.user_id}@example.com",
                    hashed_password="hashed_pw",
                    name="Number Filter Tester",
                )
            )
            db.flush()
            db.add(
                DataTable(
                    id=self.table_id,
                    name=f"number_filter_{self.table_id.hex[:8]}",
                    owner_id=self.user_id,
                    columns=COLUMNS,
                )
            )
            db.flush()
            # CSV cells: "10.00" is stored as 10.0, a blank cell stays "".
            for sku, price in (("A", "10.00"), ("B", "25"), ("C", "3"), ("D", "")):
                data, errors = _coerce_row_data({"sku": sku, "price": price}, COLUMNS)
                self.assertEqual(errors, [])
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
            return sorted(data["sku"] for data in rows.scalars().all())

    def test_equality_matches_a_number_written_with_decimals(self) -> None:
        self.assertEqual(self._find({"price": 10}), ["A"])
        self.assertEqual(self._find({"price": {"$eq": 10}}), ["A"])
        self.assertEqual(self._find({"price": "10"}), ["A"])

    def test_in_and_ne_compare_as_numbers(self) -> None:
        self.assertEqual(self._find({"price": {"$in": [10, 3]}}), ["A", "C"])
        self.assertEqual(self._find({"price": {"$ne": 10}}), ["B", "C", "D"])

    def test_a_blank_cell_does_not_break_a_range_filter(self) -> None:
        self.assertEqual(self._find({"price": {"$gte": 20}}), ["B"])
        self.assertEqual(self._find({"price": {"$lt": "5"}}), ["C"])

    def test_a_blank_filter_value_still_matches_blank_cells(self) -> None:
        self.assertEqual(self._find({"price": ""}), ["D"])


if __name__ == "__main__":
    unittest.main()
