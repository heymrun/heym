"""Gmail API client: token refresh, requests, and errors that never echo Google's body."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from app.services import gmail_service
from app.services.gmail_service import GMAIL_BASE, GmailApiError, GmailService


def _config(expired: bool = False) -> dict:
    expiry = datetime.now(timezone.utc) + (timedelta(hours=-1) if expired else timedelta(hours=1))
    return {
        "client_id": "client",
        "client_secret": "secret",
        "refresh_token": "refresh",
        "access_token": "access",
        "token_expiry": expiry.isoformat(),
    }


def _response(status: int = 200, json: object | None = None, method: str = "GET") -> httpx.Response:
    return httpx.Response(status, json=json, request=httpx.Request(method, GMAIL_BASE))


class GmailServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = MagicMock()
        self.request = patch.object(gmail_service.httpx, "request").start()
        self.post = patch.object(gmail_service.httpx, "post").start()
        self.addCleanup(patch.stopall)

    def test_history_asks_for_added_messages_and_added_labels(self) -> None:
        self.request.return_value = _response(json={"historyId": "9"})
        GmailService("cred", _config(), self.db).list_history(42, "page-2")

        method, url = self.request.call_args.args
        self.assertEqual((method, url), ("GET", f"{GMAIL_BASE}/history"))
        params = self.request.call_args.kwargs["params"]
        self.assertIn(("startHistoryId", "42"), params)
        self.assertIn(("historyTypes", "messageAdded"), params)
        self.assertIn(("historyTypes", "labelAdded"), params)
        self.assertIn(("pageToken", "page-2"), params)
        self.assertEqual(
            self.request.call_args.kwargs["headers"], {"Authorization": "Bearer access"}
        )

    def test_actions_modify_labels_or_trash(self) -> None:
        self.request.return_value = _response(json={}, method="POST")
        service = GmailService("cred", _config(), self.db)
        service.modify_labels("m/1", remove=["UNREAD"])
        service.trash_message("m1")

        modify, trash = self.request.call_args_list
        self.assertEqual(modify.args, ("POST", f"{GMAIL_BASE}/messages/m%2F1/modify"))
        self.assertEqual(modify.kwargs["json"], {"addLabelIds": [], "removeLabelIds": ["UNREAD"]})
        self.assertEqual(trash.args, ("POST", f"{GMAIL_BASE}/messages/m1/trash"))

    def test_an_expired_token_is_refreshed_and_saved_encrypted(self) -> None:
        self.post.return_value = _response(
            json={"access_token": "fresh", "expires_in": 3600}, method="POST"
        )
        self.request.return_value = _response(json={"emailAddress": "me@gmail.com"})
        credential = MagicMock()
        self.db.query.return_value.filter.return_value.first.return_value = credential

        with patch.object(gmail_service, "encrypt_config", return_value="sealed") as encrypt:
            GmailService("cred", _config(expired=True), self.db).get_profile()

        self.assertEqual(
            self.request.call_args.kwargs["headers"], {"Authorization": "Bearer fresh"}
        )
        self.assertEqual(encrypt.call_args.args[0]["access_token"], "fresh")
        self.assertEqual(encrypt.call_args.args[0]["refresh_token"], "refresh")
        self.assertEqual(credential.encrypted_config, "sealed")
        self.db.commit.assert_called_once()

    def test_a_credential_never_connected_asks_for_a_reconnect(self) -> None:
        config = _config(expired=True)
        config.pop("refresh_token")
        with self.assertRaises(GmailApiError) as caught:
            GmailService("cred", config, self.db).get_profile()
        self.assertEqual(caught.exception.status_code, 401)
        self.post.assert_not_called()

    def test_errors_keep_the_status_but_not_googles_body(self) -> None:
        for status in (403, 404, 429, 500):
            with self.subTest(status=status):
                self.request.return_value = _response(
                    status, json={"error": {"message": "leaked me@gmail.com"}}
                )
                with self.assertRaises(GmailApiError) as caught:
                    GmailService("cred", _config(), self.db).get_raw_message("m1")
                self.assertEqual(caught.exception.status_code, status)
                self.assertNotIn("leaked", str(caught.exception))

    def test_a_network_failure_is_a_502(self) -> None:
        self.request.side_effect = httpx.ConnectError("down")
        with self.assertRaises(GmailApiError) as caught:
            GmailService("cred", _config(), self.db).list_labels()
        self.assertEqual(caught.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
