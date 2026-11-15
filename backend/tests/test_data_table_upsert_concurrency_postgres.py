"""Concurrent dataTable node upserts of one key, against real PostgreSQL.

The upsert looks the row up and then inserts or updates it. Without a lock around both,
runs that upsert the same key at the same time all see "no row": a table without a
unique column gets one row per run, and one with a unique column fails all but the first
run's unique check instead of updating.

Like ``test_data_table_unique_concurrency_postgres.py``, every run pauses between lookup
and write (here in the row coercion that sits between them), so an unfixed build fails
every time instead of now and then. With the lock held, the pause just queues the runs.
"""

import threading
import time
import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import delete, select, text

from app.db.models import DataTable, DataTableRow, User
from app.db.session import SessionLocal
from app.services import workflow_executor
from app.services.workflow_executor import execute_workflow

RUNS = 4
RACE_WINDOW_SECONDS = 0.2


def _is_db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


class DataTableUpsertConcurrencyPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        if not _is_db_reachable():
            self.skipTest("PostgreSQL database is not reachable")
        self.user_id = uuid.uuid4()
        self.plain_id = uuid.uuid4()
        self.unique_id = uuid.uuid4()
        with SessionLocal() as db:
            db.add(
                User(
                    id=self.user_id,
                    email=f"upsert-race-{self.user_id.hex[:8]}@example.com",
                    hashed_password="x",
                    name="Upsert race",
                )
            )
            db.flush()
            for table_id, unique in ((self.plain_id, False), (self.unique_id, True)):
                db.add(
                    DataTable(
                        id=table_id,
                        name=f"upsert_race_{table_id.hex[:8]}",
                        owner_id=self.user_id,
                        columns=[
                            {"name": "email", "type": "string", "unique": unique},
                            {"name": "last_message", "type": "string"},
                        ],
                    )
                )
            db.commit()

    def tearDown(self) -> None:
        with SessionLocal() as db:
            tables = [self.plain_id, self.unique_id]
            db.execute(delete(DataTableRow).where(DataTableRow.table_id.in_(tables)))
            db.execute(delete(DataTable).where(DataTable.id.in_(tables)))
            db.execute(delete(User).where(User.id == self.user_id))
            db.commit()

    def _upsert(self, table_id: uuid.UUID, message: str) -> str:
        nodes = [
            {"id": "start", "type": "textInput", "data": {"label": "start"}},
            {
                "id": "dt",
                "type": "dataTable",
                "data": {
                    "label": "saveContact",
                    "dataTableId": str(table_id),
                    "dataTableOperation": "upsert",
                    "dataTableFilter": '{"email": "$start.email"}',
                    "dataTableData": '{"email": "$start.email", "last_message": "$start.text"}',
                },
            },
        ]
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=[{"id": "e1", "source": "start", "target": "dt"}],
            inputs={"email": "ada@example.com", "text": message},
            actor_user_id=self.user_id,
        )
        return next(r for r in result.node_results if r.get("node_id") == "dt")["status"]

    def _concurrent_upserts(self, table_id: uuid.UUID) -> list[str]:
        original = workflow_executor._coerce_row_data

        def slow(*args, **kwargs):
            coerced = original(*args, **kwargs)
            time.sleep(RACE_WINDOW_SECONDS)
            return coerced

        statuses = [""] * RUNS
        start = threading.Barrier(RUNS)

        def run(i: int) -> None:
            start.wait()
            statuses[i] = self._upsert(table_id, f"message {i}")

        with patch.object(workflow_executor, "_coerce_row_data", slow):
            threads = [threading.Thread(target=run, args=(i,)) for i in range(RUNS)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        return statuses

    def _rows(self, table_id: uuid.UUID) -> list[dict]:
        with SessionLocal() as db:
            rows = db.execute(select(DataTableRow.data).where(DataTableRow.table_id == table_id))
            return [row[0] for row in rows.all()]

    def test_concurrent_upserts_of_one_key_keep_one_row(self) -> None:
        statuses = self._concurrent_upserts(self.plain_id)

        self.assertEqual(statuses, ["success"] * RUNS)
        self.assertEqual(len(self._rows(self.plain_id)), 1, self._rows(self.plain_id))

    def test_concurrent_upserts_on_a_unique_key_update_instead_of_failing(self) -> None:
        statuses = self._concurrent_upserts(self.unique_id)

        self.assertEqual(statuses, ["success"] * RUNS)
        self.assertEqual(len(self._rows(self.unique_id)), 1)


if __name__ == "__main__":
    unittest.main()
