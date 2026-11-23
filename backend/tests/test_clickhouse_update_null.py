"""A null in the ClickHouse node's update data sets the column to NULL.

Every value was bound as a query parameter, and a null went out as a String parameter
that ClickHouse read as an empty string: `{"note": null}` wrote "" into a Nullable column.
"""

import unittest
from unittest.mock import MagicMock

from app.services.clickhouse_service import ClickHouseService


def _service() -> tuple[ClickHouseService, MagicMock]:
    client = MagicMock()
    svc = ClickHouseService({"host": "localhost", "port": 8123})
    svc._client = MagicMock(return_value=client)
    return svc, client


class ClickHouseUpdateNullTests(unittest.TestCase):
    def test_null_sets_null(self) -> None:
        svc, client = _service()
        svc.update("t", data={"note": None, "name": "b2"}, filters={"id": 2})
        sql = client.command.call_args[0][0]
        params = client.command.call_args[1]["parameters"]
        self.assertEqual(
            sql,
            "ALTER TABLE t UPDATE note = {set_note:Nullable(String)}, name = {set_name:String} "
            "WHERE id = {v_id:Int64}",
        )
        self.assertEqual(params, {"set_note": None, "set_name": "b2", "v_id": 2})

    def test_other_values_stay_bound_parameters(self) -> None:
        svc, client = _service()
        svc.update("t", data={"note": "", "count": 0, "active": False}, filters={"id": 2})
        sql = client.command.call_args[0][0]
        self.assertEqual(
            sql,
            "ALTER TABLE t UPDATE note = {set_note:String}, count = {set_count:Int64}, "
            "active = {set_active:Bool} WHERE id = {v_id:Int64}",
        )
        self.assertEqual(
            client.command.call_args[1]["parameters"],
            {"set_note": "", "set_count": 0, "set_active": False, "v_id": 2},
        )


if __name__ == "__main__":
    unittest.main()
