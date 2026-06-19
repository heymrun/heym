"""Tests for Notion credential validation, testing, and discovery."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    list_notion_data_sources,
    merge_credential_config_for_update,
    run_credential_connection_test,
    validate_credential_config,
)
from app.db.models import Credential, CredentialType
from app.models.schemas import CredentialTestRequest


class NotionCredentialTests(unittest.TestCase):
    def test_validation_requires_token(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(CredentialType.notion, {})
        self.assertIn("api_token", str(context.exception.detail))

    def test_masked_value_masks_token(self) -> None:
        masked = get_masked_value(CredentialType.notion, {"api_token": "secret_token_value"})
        self.assertNotEqual(masked, "secret_token_value")
        self.assertIn("*", masked or "")

    def test_update_preserves_blank_token(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.notion,
            {"api_token": "stored-token"},
            {"api_token": ""},
        )
        self.assertEqual(merged["api_token"], "stored-token")


class NotionCredentialApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_success(self) -> None:
        with patch(
            "app.services.notion_service.NotionService.test_connection",
            return_value={"id": "bot"},
        ):
            response = await run_credential_connection_test(
                CredentialTestRequest(
                    type=CredentialType.notion,
                    config={"api_token": "secret"},
                ),
                current_user=MagicMock(id=uuid.uuid4()),
                db=AsyncMock(),
            )
        self.assertTrue(response.success)

    async def test_data_source_discovery(self) -> None:
        user_id = uuid.uuid4()
        credential = Credential(
            id=uuid.uuid4(),
            owner_id=user_id,
            name="Notion",
            type=CredentialType.notion,
            encrypted_config="encrypted",
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = credential
        db = AsyncMock()
        db.execute.return_value = result

        with (
            patch("app.api.credentials.decrypt_config", return_value={"api_token": "secret"}),
            patch(
                "app.services.notion_service.NotionService.list_data_sources",
                return_value={
                    "data_sources": [
                        {"id": "ds-1", "title": "Tasks", "url": "https://notion.so/tasks"}
                    ],
                    "success": True,
                },
            ),
        ):
            response = await list_notion_data_sources(
                credential_id=credential.id,
                query="Task",
                current_user=MagicMock(id=user_id),
                db=db,
            )
        self.assertEqual(response.data_sources[0].title, "Tasks")
