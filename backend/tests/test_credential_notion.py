"""Tests for Notion credential validation, testing, and discovery."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import (
    _merge_notion_test_config,
    get_masked_value,
    list_notion_data_sources,
    list_notion_pages,
    merge_credential_config_for_update,
    run_credential_connection_test,
    validate_credential_config,
)
from app.db.models import Credential, CredentialType
from app.models.schemas import CredentialTestRequest


class NotionCredentialTests(unittest.TestCase):
    def test_validation_requires_token_or_oauth_client(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(CredentialType.notion, {})
        self.assertIn("OAuth", str(context.exception.detail))

    def test_validation_accepts_oauth_client(self) -> None:
        validate_credential_config(
            CredentialType.notion,
            {
                "auth_mode": "oauth",
                "client_id": "client",
                "client_secret": "secret",
            },
            allow_pending_oauth=True,
        )

    def test_validation_rejects_pending_oauth_without_allow_flag(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(
                CredentialType.notion,
                {
                    "auth_mode": "oauth",
                    "client_id": "client",
                    "client_secret": "secret",
                },
            )
        self.assertIn("completed authorization", str(context.exception.detail))

    def test_validation_rejects_oauth_without_client_credentials(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(
                CredentialType.notion,
                {"auth_mode": "oauth"},
                allow_pending_oauth=True,
            )
        self.assertEqual(context.exception.status_code, 400)

    def test_masked_value_masks_token(self) -> None:
        masked = get_masked_value(CredentialType.notion, {"api_token": "secret_token_value"})
        self.assertNotEqual(masked, "secret_token_value")
        self.assertIn("*", masked or "")

    def test_masked_value_marks_oauth_connected(self) -> None:
        self.assertEqual(
            get_masked_value(CredentialType.notion, {"access_token": "oauth-token"}),
            "connected",
        )

    def test_masked_value_includes_workspace_name(self) -> None:
        self.assertEqual(
            get_masked_value(
                CredentialType.notion,
                {"access_token": "oauth-token", "workspace_name": "Acme HQ"},
            ),
            "connected (Acme HQ)",
        )

    def test_masked_value_marks_pending_oauth(self) -> None:
        self.assertEqual(
            get_masked_value(CredentialType.notion, {"auth_mode": "oauth"}),
            "Not connected",
        )

    def test_public_fields_include_workspace_name(self) -> None:
        from app.api.credentials import get_public_credential_fields

        fields = get_public_credential_fields(
            CredentialType.notion,
            {"auth_mode": "oauth", "workspace_name": "Acme HQ"},
        )
        self.assertEqual(fields["auth_mode"], "oauth")
        self.assertEqual(fields["workspace_name"], "Acme HQ")

    def test_merge_notion_test_config_preserves_stored_auth_mode(self) -> None:
        merged = _merge_notion_test_config(
            {"auth_mode": "oauth"},
            {"auth_mode": "oauth", "access_token": "oauth-token"},
        )
        self.assertEqual(merged["access_token"], "oauth-token")
        self.assertEqual(merged["auth_mode"], "oauth")

    def test_update_preserves_blank_token(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.notion,
            {"api_token": "stored-token"},
            {"api_token": ""},
        )
        self.assertEqual(merged["api_token"], "stored-token")

    def test_update_switches_between_token_and_oauth(self) -> None:
        oauth_config = merge_credential_config_for_update(
            CredentialType.notion,
            {"api_token": "stored-token"},
            {"auth_mode": "oauth"},
        )
        self.assertNotIn("api_token", oauth_config)
        token_config = merge_credential_config_for_update(
            CredentialType.notion,
            {"auth_mode": "oauth", "access_token": "oauth-token"},
            {"api_token": "new-token"},
        )
        self.assertNotIn("access_token", token_config)
        self.assertEqual(token_config["auth_mode"], "token")


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
            ) as list_data_sources_mock,
        ):
            response = await list_notion_data_sources(
                credential_id=credential.id,
                query="Task",
                start_cursor="cursor-1",
                page_size=25,
                current_user=MagicMock(id=user_id),
                db=db,
            )
        self.assertEqual(response.data_sources[0].title, "Tasks")
        list_data_sources_mock.assert_called_once_with(
            "Task",
            start_cursor="cursor-1",
            page_size=25,
        )

    async def test_page_discovery(self) -> None:
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
                "app.services.notion_service.NotionService.list_pages",
                return_value={
                    "pages": [{"id": "page-1", "title": "Home", "url": "https://notion.so/home"}],
                    "success": True,
                },
            ),
        ):
            response = await list_notion_pages(
                credential_id=credential.id,
                query="Home",
                current_user=MagicMock(id=user_id),
                db=db,
            )
        self.assertEqual(response.pages[0].title, "Home")
