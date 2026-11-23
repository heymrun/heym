"""A null in the ClickHouse node's filter matches NULL cells.

The filter bound null as a String parameter, which ClickHouse read as an empty string:
`{"note": null}` matched rows whose note is "" and left the NULL ones out, so `remove`
deleted the empty notes and `find`, `count` and `update` acted on the same wrong rows.
"""

import unittest
from unittest.mock import MagicMock

from app.services.clickhouse_service import ClickHouseService


def _service(client: MagicMock) -> ClickHouseService:
    svc = ClickHouseService({"host": "localhost", "port": 8123})
    svc._client = MagicMock(return_value=client)
    return svc


def _client() -> MagicMock:
    client = MagicMock()
    result = MagicMock()
    result.result_rows = [(1,)]
    result.column_names = ["id"]
    client.query.return_value = result
    return client


class ClickHouseNullFilterTests(unittest.TestCase):
    def test_find_reads_null_as_is_null(self) -> None:
        client = _client()
        _service(client).find("t", filters={"note": None, "status": "open"}, limit=0, sort="")
        sql = client.query.call_args[0][0]
        params = client.query.call_args[1]["parameters"]
        self.assertEqual(sql, "SELECT * FROM t WHERE note IS NULL AND status = {v_status:String}")
        self.assertEqual(params, {"v_status": "open"})

    def test_count_reads_null_as_is_null(self) -> None:
        client = _client()
        _service(client).count("t", filters={"note": None})
        self.assertEqual(client.query.call_args[0][0], "SELECT count() FROM t WHERE note IS NULL")

    def test_update_and_remove_read_null_as_is_null(self) -> None:
        client = _client()
        svc = _service(client)
        svc.update("t", data={"status": "done"}, filters={"note": None})
        self.assertEqual(
            client.command.call_args[0][0],
            "ALTER TABLE t UPDATE status = {set_status:String} WHERE note IS NULL",
        )
        svc.remove("t", filters={"note": None})
        self.assertEqual(client.command.call_args[0][0], "DELETE FROM t WHERE note IS NULL")

    def test_other_values_stay_bound_parameters(self) -> None:
        client = _client()
        _service(client).find("t", filters={"note": "", "id": 0}, limit=0, sort="")
        sql = client.query.call_args[0][0]
        self.assertEqual(sql, "SELECT * FROM t WHERE note = {v_note:String} AND id = {v_id:Int64}")
        self.assertEqual(client.query.call_args[1]["parameters"], {"v_note": "", "v_id": 0})


if __name__ == "__main__":
    unittest.main()
