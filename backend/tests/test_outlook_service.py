"""Outlook Graph client: token refresh, immutable ids, paging limits, safe errors."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from app.services import outlook_service
from app.services.outlook_service import (
    GRAPH_BASE,
    OutlookApiError,
    OutlookService,
    account_address,
    has_mail_scope,
    has_send_scope,
    oauth_tenant,
    refresh_scopes,
)

FRESH = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _response(status: int = 200, json: object | None = None, content: bytes | None = None):  # noqa: ANN202
    request = httpx.Request("GET", GRAPH_BASE)
    if content is not None:
        return httpx.Response(status, content=content, request=request)
    return httpx.Response(status, json=json if json is not None else {}, request=request)


def _service(**config: object) -> tuple[OutlookService, MagicMock]:
    db = MagicMock()
    base = {"client_id": "c", "client_secret": "s", "refresh_token": "r", "access_token": "a"}
    return OutlookService("cred", {**base, "token_expiry": FRESH, **config}, db), db


class TenantAndScopeTests(unittest.TestCase):
    def test_tenant_defaults_to_common_and_accepts_ids_and_domains(self) -> None:
        self.assertEqual(oauth_tenant({}), "common")
        for tenant in ("organizations", "consumers", "contoso.onmicrosoft.com", "1f2e-3d4c"):
            self.assertEqual(oauth_tenant({"tenant": f" {tenant} "}), tenant)

    def test_a_tenant_that_could_change_the_sign_in_url_is_rejected(self) -> None:
        for tenant in ("evil.com/x", "a?b=c", "../common", "a b", "-x", "a" * 101):
            with self.subTest(tenant=tenant), self.assertRaises(ValueError):
                oauth_tenant({"tenant": tenant})

    def test_mail_scope_is_found_in_short_and_full_forms(self) -> None:
        self.assertTrue(has_mail_scope("User.Read Mail.ReadWrite"))
        self.assertTrue(has_mail_scope("https://graph.microsoft.com/Mail.ReadWrite openid"))
        self.assertFalse(has_mail_scope("Mail.Read User.Read"))
        self.assertFalse(has_mail_scope(""))

    def test_send_scope_is_found_in_short_and_full_forms(self) -> None:
        self.assertTrue(has_send_scope("Mail.ReadWrite Mail.Send"))
        self.assertTrue(has_send_scope("https://graph.microsoft.com/Mail.Send openid"))
        self.assertFalse(has_send_scope("Mail.ReadWrite Mail.Send.Shared"))
        self.assertFalse(has_send_scope(None))

    def test_a_refresh_asks_for_mail_send_only_when_the_sign_in_granted_it(self) -> None:
        # Credentials connected before Outlook Send must keep refreshing for their trigger.
        self.assertNotIn("Mail.Send", refresh_scopes({"scope": "User.Read Mail.ReadWrite"}))
        self.assertNotIn("Mail.Send", refresh_scopes({}))
        self.assertIn("Mail.Send", refresh_scopes({"scope": "Mail.ReadWrite Mail.Send"}))
        self.assertIn("Mail.ReadWrite", refresh_scopes({}))

    def test_account_address_falls_back_to_the_user_principal_name(self) -> None:
        self.assertEqual(account_address({"mail": "a@contoso.com"}), "a@contoso.com")
        self.assertEqual(
            account_address({"mail": None, "userPrincipalName": "b@live.com"}), "b@live.com"
        )


class TokenTests(unittest.TestCase):
    def test_an_expired_token_is_refreshed_and_the_rotated_refresh_token_saved(self) -> None:
        service, db = _service(token_expiry="2000-01-01T00:00:00+00:00", tenant="contoso.com")
        credential = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = credential
        token = _response(json={"access_token": "new", "refresh_token": "r2", "expires_in": 60})
        with (
            patch.object(outlook_service.httpx, "post", return_value=token) as post,
            patch.object(outlook_service, "encrypt_config", side_effect=lambda c: c) as encrypt,
        ):
            self.assertEqual(service.access_token(), "new")

        self.assertEqual(
            post.call_args.args[0],
            "https://login.microsoftonline.com/contoso.com/oauth2/v2.0/token",
        )
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "refresh_token")
        self.assertIn("Mail.ReadWrite", post.call_args.kwargs["data"]["scope"])
        self.assertNotIn("Mail.Send", post.call_args.kwargs["data"]["scope"])
        saved = encrypt.call_args.args[0]
        self.assertEqual((saved["access_token"], saved["refresh_token"]), ("new", "r2"))
        db.commit.assert_called_once()

    def test_a_failed_refresh_asks_to_reconnect(self) -> None:
        service, _db = _service(token_expiry="")
        failed = _response(400, {"error": "invalid_grant", "error_description": "secret r"})
        with (
            patch.object(outlook_service.httpx, "post", return_value=failed),
            self.assertRaises(OutlookApiError) as caught,
        ):
            service.access_token()
        self.assertEqual(caught.exception.status_code, 401)
        self.assertNotIn("invalid_grant", str(caught.exception))

    def test_no_refresh_token_asks_to_reconnect(self) -> None:
        service, _db = _service(token_expiry="", refresh_token="")
        with self.assertRaises(OutlookApiError) as caught:
            service.access_token()
        self.assertEqual(caught.exception.status_code, 401)


class RequestTests(unittest.TestCase):
    def test_requests_ask_for_immutable_ids_and_errors_keep_only_the_status(self) -> None:
        service, _db = _service()
        body = {"error": {"message": "mailbox me@contoso.com token a"}}
        with (
            patch.object(
                outlook_service.httpx, "request", return_value=_response(403, body)
            ) as req,
            self.assertRaises(OutlookApiError) as caught,
        ):
            service.get_profile()
        headers = req.call_args.kwargs["headers"]
        self.assertEqual(headers["Prefer"], 'IdType="ImmutableId"')
        self.assertEqual(headers["Authorization"], "Bearer a")
        self.assertEqual(caught.exception.status_code, 403)
        self.assertNotIn("me@contoso.com", str(caught.exception))

    def test_listing_follows_graph_pages_up_to_the_limit(self) -> None:
        service, _db = _service()
        pages = [
            _response(
                json={
                    "value": [{"id": "1"}, {"id": "2"}],
                    "@odata.nextLink": f"{GRAPH_BASE}/messages?$skip=2",
                }
            ),
            _response(json={"value": [{"id": "3"}]}),
        ]
        with patch.object(outlook_service.httpx, "request", side_effect=pages) as req:
            messages, complete = service.list_messages("messages", {"$filter": "x"}, 10)
        self.assertEqual(([m["id"] for m in messages], complete), (["1", "2", "3"], True))
        self.assertEqual(req.call_args_list[0].kwargs["params"]["$top"], "100")
        self.assertIsNone(req.call_args_list[1].kwargs["params"])

        with patch.object(outlook_service.httpx, "request", return_value=pages[0]):
            messages, complete = service.list_messages("messages", {}, 1)
        self.assertEqual((len(messages), complete), (1, False))

    def test_a_next_link_outside_graph_is_never_followed(self) -> None:
        service, _db = _service()
        page = _response(json={"value": [], "@odata.nextLink": "https://evil.example/steal"})
        with (
            patch.object(outlook_service.httpx, "request", return_value=page) as req,
            self.assertRaises(OutlookApiError),
        ):
            service.list_messages("messages", {}, 10)
        self.assertEqual(req.call_count, 1)

    def test_mime_is_returned_as_bytes_and_ids_are_escaped(self) -> None:
        service, _db = _service()
        with patch.object(
            outlook_service.httpx, "request", return_value=_response(content=b"Subject: x\r\n")
        ) as req:
            self.assertEqual(service.get_mime("AA/b+c="), b"Subject: x\r\n")
        self.assertEqual(req.call_args.args[1], f"{GRAPH_BASE}/messages/AA%2Fb%2Bc%3D/$value")

    def test_a_missing_well_known_folder_is_none(self) -> None:
        service, _db = _service()
        with patch.object(outlook_service.httpx, "request", return_value=_response(404)):
            self.assertIsNone(service.folder_id("archive"))

    def test_mark_read_and_move_send_the_documented_bodies(self) -> None:
        service, _db = _service()
        with patch.object(outlook_service.httpx, "request", return_value=_response(json={})) as req:
            service.mark_read("m")
            service.move("m", "deleteditems")
        self.assertEqual(req.call_args_list[0].args[:2], ("PATCH", f"{GRAPH_BASE}/messages/m"))
        self.assertEqual(req.call_args_list[0].kwargs["json"], {"isRead": True})
        self.assertEqual(req.call_args_list[1].args[:2], ("POST", f"{GRAPH_BASE}/messages/m/move"))
        self.assertEqual(req.call_args_list[1].kwargs["json"], {"destinationId": "deleteditems"})

    def test_folders_are_listed_with_their_parents_path(self) -> None:
        service, _db = _service()
        pages = [
            _response(
                json={
                    "value": [
                        {"id": "inbox", "displayName": "Inbox", "childFolderCount": 1},
                        {"id": "sent", "displayName": "Sent Items", "childFolderCount": 0},
                    ]
                }
            ),
            _response(json={"value": [{"id": "inv", "displayName": "Invoices"}]}),
        ]
        with patch.object(outlook_service.httpx, "request", side_effect=pages):
            folders = service.list_folders()
        self.assertEqual(
            [(f["id"], f["path"]) for f in folders],
            [("inbox", "Inbox"), ("inv", "Inbox / Invoices"), ("sent", "Sent Items")],
        )


if __name__ == "__main__":
    unittest.main()


class SendMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = patch.object(outlook_service.httpx, "request").start()
        self.put = patch.object(outlook_service.httpx, "put").start()
        self.addCleanup(patch.stopall)
        self.service, _ = _service(scope="Mail.ReadWrite Mail.Send")
        self.message = {"subject": "Hi", "body": {"contentType": "Text", "content": "Body"}}

    def test_a_small_message_goes_through_send_mail_with_inline_attachments(self) -> None:
        self.request.return_value = _response(202, content=b"")
        self.service.send_message(self.message, [("a.pdf", "application/pdf", b"PDF")])

        method, url = self.request.call_args.args
        self.assertEqual((method, url), ("POST", f"{GRAPH_BASE}/sendMail"))
        sent = self.request.call_args.kwargs["json"]
        self.assertTrue(sent["saveToSentItems"])
        self.assertEqual(sent["message"]["subject"], "Hi")
        attachment = sent["message"]["attachments"][0]
        self.assertEqual(attachment["@odata.type"], "#microsoft.graph.fileAttachment")
        self.assertEqual((attachment["name"], attachment["contentBytes"]), ("a.pdf", "UERG"))
        self.assertNotIn("attachments", self.message)

    def test_a_refused_message_says_why(self) -> None:
        refusal = {"error": {"code": "ErrorInvalidRecipients", "message": "Recipient not valid"}}
        self.request.return_value = _response(400, json=refusal)
        with self.assertRaises(OutlookApiError) as raised:
            self.service.send_message(self.message, [])
        self.assertEqual(str(raised.exception), "Outlook: Recipient not valid")

    def test_a_large_message_is_sent_as_a_draft_with_an_upload_session(self) -> None:
        big = b"x" * (outlook_service._UPLOAD_CHUNK_BYTES + 10)
        upload_url = "https://outlook.office.com/api/v2.0/me/AttachmentSessions('s')?authtoken=t"
        self.request.side_effect = [
            _response(201, json={"id": "draft/1"}),
            _response(201, json={}),
            _response(200, json={"uploadUrl": upload_url}),
            _response(202, content=b""),
        ]
        self.put.return_value = _response(201, json={})
        self.service.send_message(
            self.message,
            [("small.txt", "text/plain", b"hello"), ("big.bin", "application/octet-stream", big)],
        )

        urls = [call.args[1] for call in self.request.call_args_list]
        draft = f"{GRAPH_BASE}/messages/draft%2F1"
        self.assertEqual(
            urls,
            [
                f"{GRAPH_BASE}/messages",
                f"{draft}/attachments",
                f"{draft}/attachments/createUploadSession",
                f"{draft}/send",
            ],
        )
        session = self.request.call_args_list[2].kwargs["json"]["AttachmentItem"]
        self.assertEqual((session["name"], session["size"]), ("big.bin", len(big)))
        ranges = [call.kwargs["headers"]["Content-Range"] for call in self.put.call_args_list]
        chunk = outlook_service._UPLOAD_CHUNK_BYTES
        self.assertEqual(
            ranges, [f"bytes 0-{chunk - 1}/{len(big)}", f"bytes {chunk}-{len(big) - 1}/{len(big)}"]
        )
        for call in self.put.call_args_list:
            self.assertNotIn("Authorization", call.kwargs["headers"])

    def test_a_draft_that_cannot_be_completed_is_removed(self) -> None:
        big = b"x" * (outlook_service.INLINE_MESSAGE_LIMIT)
        self.request.side_effect = [
            _response(201, json={"id": "d1"}),
            _response(200, json={"uploadUrl": "https://attacker.example/upload"}),
            _response(204, content=b""),
        ]
        with self.assertRaises(OutlookApiError):
            self.service.send_message(self.message, [("big.bin", "application/pdf", big)])

        self.put.assert_not_called()
        method, url = self.request.call_args_list[-1].args
        self.assertEqual((method, url), ("DELETE", f"{GRAPH_BASE}/messages/d1"))
