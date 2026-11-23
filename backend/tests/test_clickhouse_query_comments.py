"""A ClickHouse `query` SELECT that starts with a comment returns its rows.

The node told reads from commands by the first word of the SQL, so `-- report` before a
SELECT sent it through `command()`, which returned the rows as TSV text in `result`.
"""

import unittest
from unittest.mock import MagicMock

from app.services.clickhouse_service import ClickHouseService

READS = [
    "-- every id\nSELECT id FROM t",
    "# every id\nSELECT id FROM t",
    "/* every id */ SELECT id FROM t",
    "/* outer /* nested */ still a comment */\nSELECT id FROM t",
    "  -- one\n  -- two\n  WITH 1 AS x SELECT x",
    "( SELECT id FROM t )",
    "-- totals\n(SELECT id FROM t)",
    "select id from t",
]
COMMANDS = [
    "-- clean up\nINSERT INTO t VALUES (1)",
    "/* SELECT */ DELETE FROM t WHERE id = 1",
    "# SELECT in a comment\nALTER TABLE t DELETE WHERE 1",
    "-- SELECT with no statement",
]


def _service() -> tuple[ClickHouseService, MagicMock]:
    client = MagicMock()
    result = MagicMock()
    result.result_rows = [(1,)]
    result.column_names = ["id"]
    client.query.return_value = result
    client.command.return_value = "OK"
    svc = ClickHouseService({"host": "localhost", "port": 8123})
    svc._client = MagicMock(return_value=client)
    return svc, client


class ClickHouseQueryCommentTests(unittest.TestCase):
    def test_a_select_after_comments_returns_rows(self) -> None:
        for sql in READS:
            with self.subTest(sql=sql):
                svc, client = _service()
                out = svc.query(sql)
                self.assertEqual(out, {"rows": [{"id": 1}], "count": 1, "success": True})
                client.query.assert_called_once_with(sql.strip(), parameters={})
                client.command.assert_not_called()

    def test_other_statements_after_comments_run_as_commands(self) -> None:
        for sql in COMMANDS:
            with self.subTest(sql=sql):
                svc, client = _service()
                self.assertEqual(svc.query(sql), {"result": "OK", "success": True})
                client.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
