"""Tests for the clickhouse credential summary and connection test."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.credentials import list_clickhouse_columns
from app.db.models import Credential
from app.models.schemas import CredentialType


def make_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


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

        svc = ClickHouseService({"host": "ch.example.com", "database": "analytics", "secure": True})
        with patch.object(svc, "_client", return_value=MagicMock()) as mock_client:
            svc.test_connection()
            mock_client.return_value.query.assert_called_once_with("SELECT 1")


class TestClickHouseCredentialApi(unittest.IsolatedAsyncioTestCase):
    async def test_list_clickhouse_columns_returns_discovered_columns(self) -> None:
        user_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        current_user = MagicMock(id=user_id)
        credential = Credential(
            id=credential_id,
            owner_id=user_id,
            name="ClickHouse",
            type=CredentialType.clickhouse,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=make_result(credential))

        with patch(
            "app.api.credentials.decrypt_config",
            return_value={"host": "ch.example.com", "database": "analytics"},
        ):
            with patch(
                "app.services.clickhouse_service.ClickHouseService.list_columns"
            ) as mock_columns:
                mock_columns.return_value = {
                    "columns": [
                        {"name": "id", "type": "String"},
                        {"name": "ts", "type": "DateTime"},
                    ],
                    "success": True,
                }
                result = await list_clickhouse_columns(
                    credential_id=credential_id,
                    table="events",
                    current_user=current_user,
                    db=db,
                )

        self.assertTrue(result.success)
        self.assertEqual(result.columns[0].name, "id")
        self.assertEqual(result.columns[1].type, "DateTime")
        mock_columns.assert_called_once_with("events")
