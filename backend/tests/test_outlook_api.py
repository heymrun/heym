"""Outlook pickers: owner access, folder paths, primary address first, safe errors."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api import outlook as outlook_api
from app.db.models import CredentialType
from app.services.outlook_service import OutlookApiError

CREDENTIAL = uuid.uuid4()
USER = SimpleNamespace(id=uuid.uuid4())


class OutlookPickerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.credential = SimpleNamespace(type=CredentialType.outlook, encrypted_config="sealed")
        self.access = AsyncMock(return_value=self.credential)
        for patcher in (
            patch.object(outlook_api, "get_accessible_credential", self.access),
            patch.object(outlook_api, "decrypt_config", return_value={"client_id": "c"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_folders_are_listed_with_their_paths(self) -> None:
        folders = [{"id": "a", "path": "Inbox"}, {"id": "b", "path": "Inbox / Invoices"}]
        with patch.object(outlook_api, "_folders", return_value=folders):
            response = await outlook_api.list_folders(CREDENTIAL, USER, AsyncMock())

        self.assertEqual(
            [(folder.id, folder.path) for folder in response.folders],
            [("a", "Inbox"), ("b", "Inbox / Invoices")],
        )
        self.assertEqual(self.access.await_args.args[1:], (CREDENTIAL, USER.id))

    async def test_addresses_list_the_primary_first_then_smtp_aliases(self) -> None:
        profile = {
            "mail": "Me@Contoso.com",
            "proxyAddresses": [
                "smtp:sales@contoso.com",
                "SMTP:me@contoso.com",
                "X500:/o=Exchange/cn=me",
                "smtp:billing@contoso.com",
            ],
        }
        with patch.object(outlook_api, "_profile", return_value=profile):
            response = await outlook_api.list_addresses(CREDENTIAL, USER, AsyncMock())

        self.assertEqual(
            [(a.email, a.is_primary) for a in response.addresses],
            [
                ("me@contoso.com", True),
                ("billing@contoso.com", False),
                ("sales@contoso.com", False),
            ],
        )

    async def test_a_personal_account_lists_its_sign_in_address(self) -> None:
        profile = {"mail": None, "userPrincipalName": "me@outlook.com", "proxyAddresses": []}
        with patch.object(outlook_api, "_profile", return_value=profile):
            response = await outlook_api.list_addresses(CREDENTIAL, USER, AsyncMock())
        self.assertEqual([a.email for a in response.addresses], ["me@outlook.com"])

    async def test_an_inaccessible_or_other_credential_is_not_found(self) -> None:
        for credential in (None, SimpleNamespace(type=CredentialType.gmail)):
            with self.subTest(credential=credential):
                self.access.return_value = credential
                with self.assertRaises(HTTPException) as caught:
                    await outlook_api.list_folders(CREDENTIAL, USER, AsyncMock())
                self.assertEqual(caught.exception.status_code, 404)

    async def test_graph_errors_become_safe_responses(self) -> None:
        for status, expected in ((401, 400), (403, 400), (500, 502)):
            with (
                self.subTest(status=status),
                patch.object(
                    outlook_api, "_folders", side_effect=OutlookApiError(status, "Outlook: x")
                ),
                self.assertRaises(HTTPException) as caught,
            ):
                await outlook_api.list_folders(CREDENTIAL, USER, AsyncMock())
            self.assertEqual(caught.exception.status_code, expected)


if __name__ == "__main__":
    unittest.main()
