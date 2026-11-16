"""Gmail pickers: owner access, user labels only, primary address first, safe errors."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api import gmail as gmail_api
from app.db.models import CredentialType
from app.services.gmail_service import GmailApiError

CREDENTIAL = uuid.uuid4()
USER = SimpleNamespace(id=uuid.uuid4())


class GmailPickerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.credential = SimpleNamespace(type=CredentialType.gmail, encrypted_config="sealed")
        self.access = AsyncMock(return_value=self.credential)
        for patcher in (
            patch.object(gmail_api, "get_accessible_credential", self.access),
            patch.object(gmail_api, "decrypt_config", return_value={"client_id": "c"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_labels_are_the_accounts_own_labels_by_name(self) -> None:
        labels = [
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "Label_2", "name": "receipts", "type": "user"},
            {"id": "Label_1", "name": "Invoices", "type": "user"},
        ]
        with patch.object(gmail_api, "_read", return_value=labels) as read:
            response = await gmail_api.list_labels(CREDENTIAL, USER, AsyncMock())

        self.assertEqual(
            [(label.id, label.name) for label in response.labels],
            [("Label_1", "Invoices"), ("Label_2", "receipts")],
        )
        self.assertEqual(read.call_args.args[2], "labels")
        self.assertEqual(self.access.await_args.args[1:], (CREDENTIAL, USER.id))

    async def test_addresses_list_the_primary_first(self) -> None:
        items = [
            {"sendAsEmail": "sales@example.com", "displayName": "Sales"},
            {"sendAsEmail": "me@gmail.com", "isPrimary": True},
            {"displayName": "no address"},
        ]
        with patch.object(gmail_api, "_read", return_value=items):
            response = await gmail_api.list_addresses(CREDENTIAL, USER, AsyncMock())

        self.assertEqual(
            [(a.email, a.is_primary, a.display_name) for a in response.addresses],
            [("me@gmail.com", True, ""), ("sales@example.com", False, "Sales")],
        )

    async def test_an_inaccessible_or_other_credential_is_not_found(self) -> None:
        for credential in (None, SimpleNamespace(type=CredentialType.google_drive)):
            with self.subTest(credential=credential):
                self.access.return_value = credential
                with (
                    patch.object(gmail_api, "_read") as read,
                    self.assertRaises(HTTPException) as caught,
                ):
                    await gmail_api.list_labels(CREDENTIAL, USER, AsyncMock())
                self.assertEqual(caught.exception.status_code, 404)
                read.assert_not_called()

    async def test_gmail_errors_become_safe_http_errors(self) -> None:
        for status, expected in ((403, 400), (401, 400), (500, 502)):
            with self.subTest(status=status):
                error = GmailApiError(status, "Gmail: something")
                with (
                    patch.object(gmail_api, "_read", side_effect=error),
                    self.assertRaises(HTTPException) as caught,
                ):
                    await gmail_api.list_addresses(CREDENTIAL, USER, AsyncMock())
                self.assertEqual(caught.exception.status_code, expected)


if __name__ == "__main__":
    unittest.main()
