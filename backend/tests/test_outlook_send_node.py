"""Outlook Send: the same fields as Send Email, sent from the connected Outlook mailbox."""

import uuid
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.outlook_service import OutlookApiError, OutlookService

OUTLOOK_CONFIG = {
    "client_id": "client",
    "client_secret": "secret",
    "refresh_token": "refresh",
    "access_token": "access",
    "token_expiry": "2999-01-01T00:00:00+00:00",
    "email_address": "team@contoso.com",
    "scope": "User.Read Mail.ReadWrite Mail.Send",
}


def _db_mock(file_rows: list | None = None) -> MagicMock:
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)
    fake_db.query.return_value.filter.return_value.first.side_effect = list(file_rows or [])
    fake_db.query.return_value.join.return_value.join.return_value.filter.return_value.first.side_effect = (
        [None] * 10
    )
    return fake_db


def _run(
    data: dict,
    *,
    owner_id: uuid.UUID | None = None,
    db: MagicMock | None = None,
    config: dict | None = None,
    credential_type: CredentialType = CredentialType.outlook,
    send_side_effect: Exception | None = None,
) -> tuple[dict, MagicMock]:
    """Run textInput -> outlookSend -> output; return the node result and the send mock."""
    from app.services.workflow_executor import WorkflowExecutor

    nodes = [
        {"id": "n1", "type": "textInput", "data": {"label": "in", "text": "hi"}},
        {"id": "n2", "type": "outlookSend", "data": {"label": "outlookSend", **data}},
        {"id": "n3", "type": "output", "data": {"label": "output"}},
    ]
    edges = [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ]
    executor = WorkflowExecutor(nodes=nodes, edges=edges)
    executor.trace_user_id = owner_id or uuid.uuid4()
    executor._get_accessible_credential = MagicMock(
        return_value=SimpleNamespace(encrypted_config=b"enc", type=credential_type)
    )
    file_path = MagicMock()
    file_path.exists.return_value = True
    file_path.read_bytes.return_value = b"PDFDATA"
    with (
        patch("app.db.session.SessionLocal", return_value=db or _db_mock()),
        patch(
            "app.services.encryption.decrypt_config",
            return_value=dict(config if config is not None else OUTLOOK_CONFIG),
        ),
        patch("app.services.file_storage.get_file_path", return_value=file_path),
        patch.object(OutlookService, "send_message", side_effect=send_side_effect) as send,
    ):
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
        )
    node_result = next(r for r in result.node_results if r["node_type"] == "outlookSend")
    return node_result, send


BASE = {
    "credentialId": str(uuid.uuid4()),
    "to": "a@x.com",
    "subject": "Hi",
    "emailBody": "Body text",
}


class OutlookSendMessageTests(TestCase):
    def test_recipients_subject_and_text_body_become_a_graph_message(self) -> None:
        result, send = _run(
            {**BASE, "to": '"Doe, John" <john@x.com>, b@x.com', "cc": "c@x.com", "bcc": "h@x.com"}
        )

        self.assertEqual(result["status"], "success")
        message, attachments = send.call_args.args
        self.assertEqual(
            message["toRecipients"],
            [
                {"emailAddress": {"address": "john@x.com", "name": "Doe, John"}},
                {"emailAddress": {"address": "b@x.com"}},
            ],
        )
        self.assertEqual(message["ccRecipients"], [{"emailAddress": {"address": "c@x.com"}}])
        self.assertEqual(message["bccRecipients"], [{"emailAddress": {"address": "h@x.com"}}])
        self.assertEqual(message["subject"], "Hi")
        self.assertEqual(message["body"], {"contentType": "Text", "content": "Body text"})
        self.assertNotIn("from", message)
        self.assertEqual(attachments, [])

    def test_output_matches_send_email_and_names_the_sender(self) -> None:
        result, _ = _run(BASE)

        output = result["output"]
        self.assertEqual(output["status"], "sent")
        self.assertEqual((output["to"], output["cc"], output["bcc"]), ("a@x.com", "", ""))
        self.assertEqual(output["subject"], "Hi")
        self.assertEqual(output["attachment_count"], 0)
        self.assertEqual(output["from"], "team@contoso.com")

    def test_an_html_body_is_sent_as_html(self) -> None:
        _, send = _run({**BASE, "emailBody": "<table><tr><td>1</td></tr></table>"})

        self.assertEqual(send.call_args.args[0]["body"]["contentType"], "HTML")

    def test_html_tags_with_attributes_make_an_html_body(self) -> None:
        for body in ('<p style="margin:0">Shipped</p>', 'Shipped<br class="gap">Tracking: 42'):
            with self.subTest(body=body):
                _, send = _run({**BASE, "emailBody": body})

                self.assertEqual(send.call_args.args[0]["body"]["contentType"], "HTML")

    def test_text_that_only_mentions_angle_brackets_stays_text(self) -> None:
        for body in ("1 < 2 and 3 > 2", "Wrap code in <pre> tags"):
            with self.subTest(body=body):
                _, send = _run({**BASE, "emailBody": body})

                self.assertEqual(send.call_args.args[0]["body"]["contentType"], "Text")

    def test_a_from_address_is_sent_as_from(self) -> None:
        result, send = _run({**BASE, "fromAddress": "support@contoso.com"})

        self.assertEqual(
            send.call_args.args[0]["from"], {"emailAddress": {"address": "support@contoso.com"}}
        )
        self.assertEqual(result["output"]["from"], "support@contoso.com")

    def test_blank_cc_and_bcc_are_left_out_and_blank_subject_stays_blank(self) -> None:
        _, send = _run({**BASE, "cc": "", "bcc": " ", "subject": ""})

        message = send.call_args.args[0]
        self.assertNotIn("ccRecipients", message)
        self.assertNotIn("bccRecipients", message)
        self.assertEqual(message["subject"], "")

    def test_a_drive_file_is_attached(self) -> None:
        owner = uuid.uuid4()
        file_id = uuid.uuid4()
        row = SimpleNamespace(
            id=file_id,
            owner_id=owner,
            filename="report.pdf",
            mime_type="application/pdf",
            storage_path=f"{owner}/{file_id}/report.pdf",
        )
        result, send = _run(
            {**BASE, "attachments": f" {file_id} ,"}, owner_id=owner, db=_db_mock([row])
        )

        self.assertEqual(result["output"]["attachment_count"], 1)
        self.assertEqual(send.call_args.args[1], [("report.pdf", "application/pdf", b"PDFDATA")])


EXCHANGE_CONFIG = {
    "auth_mode": "ews",
    "ews_email": "ada@heym.run",
    "ews_username": "HEYM\\ada",
    "ews_password": "pw",
    "ews_server": "mail.heym.run",
}


class OutlookSendExchangeTests(TestCase):
    def test_an_exchange_server_credential_sends_over_ews_without_a_mail_send_scope(self) -> None:
        with patch("app.services.exchange_server.send.send_message") as ews_send:
            result, graph_send = _run({**BASE, "attachments": ""}, config=EXCHANGE_CONFIG)

        self.assertEqual(result["status"], "success", result.get("error"))
        graph_send.assert_not_called()
        config, fields, from_address, attachments = ews_send.call_args.args
        self.assertEqual(config["ews_email"], "ada@heym.run")
        self.assertEqual(
            (fields.to, fields.subject, from_address, attachments), ("a@x.com", "Hi", "", [])
        )
        self.assertEqual(result["output"]["from"], "ada@heym.run")

    def test_an_exchange_refusal_is_reported(self) -> None:
        refusal = OutlookApiError(403, "Exchange Server: access denied for this mailbox")
        with patch("app.services.exchange_server.send.send_message", side_effect=refusal):
            result, _ = _run(BASE, config=EXCHANGE_CONFIG)

        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to send email: Exchange Server: access denied", result["error"])


class OutlookSendFailureTests(TestCase):
    def test_a_credential_without_mail_send_asks_for_a_reconnect(self) -> None:
        # Connected before Outlook Send: the trigger works, sending needs a reconnect.
        old = {**OUTLOOK_CONFIG, "scope": "User.Read Mail.ReadWrite"}
        result, send = _run(BASE, config=old)

        self.assertEqual(result["status"], "error")
        self.assertIn("reconnect it in Credentials to allow Mail.Send", result["error"])
        send.assert_not_called()

    def test_missing_credential_recipient_and_wrong_type_fail_before_sending(self) -> None:
        cases = (
            ({**BASE, "credentialId": ""}, CredentialType.outlook, "requires an Outlook"),
            ({**BASE, "to": ""}, CredentialType.outlook, "Email recipient (to) is required"),
            (BASE, CredentialType.gmail, "Outlook credential not found or not accessible"),
        )
        for data, credential_type, message in cases:
            with self.subTest(message=message):
                result, send = _run(data, credential_type=credential_type)
                self.assertEqual(result["status"], "error")
                self.assertIn(message, result["error"])
                send.assert_not_called()

    def test_a_graph_refusal_is_reported(self) -> None:
        refusal = OutlookApiError(403, "Outlook: not allowed to send as support@contoso.com")
        result, _ = _run({**BASE, "fromAddress": "support@contoso.com"}, send_side_effect=refusal)

        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to send email: Outlook: not allowed", result["error"])


if __name__ == "__main__":
    main()
