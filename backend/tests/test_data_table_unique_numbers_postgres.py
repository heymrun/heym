"""A unique number column treats 1 and 1.0 as one value, against PostgreSQL.

JSONB keeps a number as written, so `data ->> 'sku'` reads 1.0 back as the text "1.0".
Comparing that text with "1" let a CSV row with 1.0 (as pandas writes a float column) or
a JSON row with 1.0 sit next to a row with 1.
"""

import unittest
import uuid

from sqlalchemy import delete, text

from app.api.data_tables import _check_unique_constraints_sync
from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal

COLUMNS = [
    {"name": "sku", "type": "number", "unique": True},
    {"name": "code", "type": "string", "unique": True},
]


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class UniqueNumberColumnPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.table_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"unique-number-{self.user_id.hex[:8]}@example.com",
                    hashed_password="x",
                    name="Unique numbers",
                )
            )
            db.flush()
            db.add(
                DataTable(
                    id=self.table_id,
                    name=f"unique_number_{self.table_id.hex[:8]}",
                    owner_id=self.user_id,
                    columns=COLUMNS,
                )
            )
            db.flush()
            for data in ({"sku": 1, "code": "1"}, {"sku": 2.5, "code": "A"}, {"sku": 7.0}):
                db.add(DataTableRow(table_id=self.table_id, data=data))
            db.commit()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            db.execute(delete(DataTableRow).where(DataTableRow.table_id == self.table_id))
            db.execute(delete(DataTable).where(DataTable.id == self.table_id))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def _errors(self, data: dict) -> list[str]:
        with SessionLocal() as db:
            errors = _check_unique_constraints_sync(self.table_id, data, COLUMNS, db)
            db.rollback()
        return errors

    def test_the_same_number_written_another_way_is_a_duplicate(self) -> None:
        cases = (
            ({"sku": 1.0}, "1"),
            ({"sku": "1.00"}, "1"),
            ({"sku": 2.50}, "2.5"),
            ({"sku": 7}, "7"),
        )
        for data, shown in cases:
            with self.subTest(data=data):
                self.assertEqual(
                    self._errors(data), [f"Duplicate value for unique column 'sku': {shown}"]
                )

    def test_a_different_number_is_not_a_duplicate(self) -> None:
        self.assertEqual(self._errors({"sku": 1.5}), [])
        self.assertEqual(self._errors({"sku": 3}), [])

    def test_a_string_column_still_compares_the_text(self) -> None:
        self.assertEqual(self._errors({"code": "1.0"}), [])
        self.assertEqual(
            self._errors({"code": "1"}), ["Duplicate value for unique column 'code': 1"]
        )

    def test_text_past_numeric_range_is_compared_as_text(self) -> None:
        # Comparing "1e200000" as a jsonb number overflowed PostgreSQL's numeric type.
        self.assertEqual(self._errors({"code": "1e200000"}), [])
        self.assertEqual(self._errors({"sku": "1e200000"}), [])

    def test_a_string_column_never_compares_as_a_number(self) -> None:
        with SessionLocal() as db:
            db.add(DataTableRow(table_id=self.table_id, data={"code": 5}))
            db.commit()
        self.assertEqual(self._errors({"code": "5.0"}), [])


if __name__ == "__main__":
    unittest.main()
