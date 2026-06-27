"""Unit tests for ClickHouseService and the clickhouse executor branch."""

import unittest
from unittest.mock import MagicMock, patch


def _make_config() -> dict:
    return {
        "host": "ch.example.com",
        "port": 8443,
        "username": "default",
        "password": "secret",
        "database": "analytics",
        "secure": True,
    }


class TestClickHouseServiceValidation(unittest.TestCase):
    def _make_service(self):
        from app.services.clickhouse_service import ClickHouseService

        return ClickHouseService(_make_config())

    def test_requires_host(self) -> None:
        from app.services.clickhouse_service import ClickHouseService

        with self.assertRaises(ValueError):
            ClickHouseService({"host": "", "database": "db"})

    def test_rejects_bad_table_name(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError):
            svc.find("bad-table; DROP", filters={}, limit=10, sort="")

    def test_rejects_bad_column_in_filter(self) -> None:
        svc = self._make_service()
        with self.assertRaises(ValueError):
            svc.find("events", filters={"bad col": 1}, limit=10, sort="")


class TestClickHouseReads(unittest.TestCase):
    def _svc_with_client(self, mock_client):
        from app.services.clickhouse_service import ClickHouseService

        svc = ClickHouseService(_make_config())
        svc._client = MagicMock(return_value=mock_client)
        return svc

    def _mock_query_result(self, rows, columns):
        result = MagicMock()
        result.result_rows = rows
        result.column_names = columns
        return result

    def test_query_select_returns_rows(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result(
            [(1, "a"), (2, "b")], ["id", "name"]
        )
        svc = self._svc_with_client(client)
        out = svc.query("SELECT id, name FROM events")
        self.assertEqual(out["rows"], [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["success"])

    def test_query_non_select_uses_command(self) -> None:
        client = MagicMock()
        client.command.return_value = "OK"
        svc = self._svc_with_client(client)
        out = svc.query("ALTER TABLE events DELETE WHERE id = 1")
        client.command.assert_called_once()
        self.assertTrue(out["success"])

    def test_find_builds_parameterized_where(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([(1,)], ["id"])
        svc = self._svc_with_client(client)
        svc.find("events", filters={"status": "active"}, limit=5, sort="created_at DESC")
        sql, kwargs = client.query.call_args[0][0], client.query.call_args[1]
        self.assertIn("status = {", sql)
        self.assertIn("LIMIT 5", sql)
        self.assertIn("ORDER BY", sql)
        self.assertEqual(kwargs["parameters"]["v_status"], "active")

    def test_count_returns_int(self) -> None:
        client = MagicMock()
        result = MagicMock()
        result.result_rows = [(42,)]
        result.column_names = ["count"]
        client.query.return_value = result
        svc = self._svc_with_client(client)
        out = svc.count("events", filters={})
        self.assertEqual(out["count"], 42)
        self.assertTrue(out["success"])

    def test_get_by_id(self) -> None:
        client = MagicMock()
        client.query.return_value = self._mock_query_result([(7, "x")], ["id", "name"])
        svc = self._svc_with_client(client)
        out = svc.get_by_id("events", "7")
        self.assertEqual(out["row"], {"id": 7, "name": "x"})
