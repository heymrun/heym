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
