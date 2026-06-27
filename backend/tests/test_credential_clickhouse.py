"""Tests for the clickhouse credential summary and connection test."""

import unittest
from unittest.mock import MagicMock, patch

from app.models.schemas import CredentialType


class TestClickHouseCredential(unittest.TestCase):
    def test_summary_includes_host_and_database(self) -> None:
        from app.api.credentials import get_masked_value

        summary = get_masked_value(
            CredentialType.clickhouse,
            {"host": "ch.example.com", "database": "analytics"},
        )
        self.assertIn("ch.example.com", summary)
        self.assertIn("analytics", summary)

    def test_test_connection_invoked(self) -> None:
        from app.services.clickhouse_service import ClickHouseService

        svc = ClickHouseService(
            {"host": "ch.example.com", "database": "analytics", "secure": True}
        )
        with patch.object(svc, "_client", return_value=MagicMock()) as mock_client:
            svc.test_connection()
            mock_client.return_value.query.assert_called_once_with("SELECT 1")
