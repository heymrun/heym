"""A Google credential saved but never connected says so, as Gmail and Outlook do.

Until the user connects it, the credential holds a client id and secret and no refresh
token. Reading the refresh token unguarded made the node fail with "'refresh_token'".
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services.bigquery_service import BigQueryService
from app.services.google_drive_service import GoogleDriveService
from app.services.google_sheets_service import GoogleSheetsService

UNCONNECTED = {"client_id": "id.apps.googleusercontent.com", "client_secret": "secret"}


class UnconnectedGoogleCredentialTests(unittest.TestCase):
    def test_a_token_request_asks_to_reconnect_and_calls_nothing(self) -> None:
        for name, service_class in (
            ("Google Drive", GoogleDriveService),
            ("Google Sheets", GoogleSheetsService),
            ("BigQuery", BigQueryService),
        ):
            with self.subTest(name), patch("httpx.post") as post:
                service = service_class("cred-1", dict(UNCONNECTED), MagicMock())

                with self.assertRaises(ValueError) as raised:
                    service._get_valid_token()

                self.assertEqual(
                    str(raised.exception),
                    f"{name} node: credential is not connected — reconnect it in "
                    "Dashboard → Credentials",
                )
                post.assert_not_called()

    def test_a_connected_credential_still_refreshes(self) -> None:
        response = MagicMock()
        response.json.return_value = {"access_token": "fresh", "expires_in": 3600}
        for service_class in (GoogleDriveService, GoogleSheetsService, BigQueryService):
            with self.subTest(service_class.__name__), patch("httpx.post", return_value=response):
                service = service_class(
                    "cred-1", {**UNCONNECTED, "refresh_token": "refresh"}, MagicMock()
                )

                self.assertEqual(service._get_valid_token(), "fresh")


if __name__ == "__main__":
    unittest.main()
