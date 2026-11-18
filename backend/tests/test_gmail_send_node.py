"""Gmail Send: the same fields as Send Email, sent from the connected Gmail account."""

import base64
import unittest
import uuid
from email import message_from_bytes, policy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.gmail_service import GmailApiError, GmailService

GMAIL_CONFIG = {
    "client_id": "client",
    "client_secret": "secret",
    "refresh_token": "refresh",
    "access_token": "access",
    "token_expiry": "2999-01-01T00:00:00+00:00",
    "email_address": "team@example.com",
}


def _db_mock(file_rows: list | None = None, shared_rows: list | None = None) -> MagicMock:
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)
    fake_db.query.return_value.filter.return_value.first.side_effect = list(file_rows or [])
    fake_db.query.return_value.join.return_value.join.return_value.filter.return_value.first.side_effect = (
        list(shared_rows) if shared_rows is not None else [None] * 10
    )
    return fake_db


def _run(
    data: dict,
    *,
    owner_id: uuid.UUID | None = None,
    db: MagicMock | None = None,
    credential_type: CredentialType = CredentialType.gmail,
    send_as: list | None = None,
    send_side_effect: Exception | None = None,
) -> tuple[dict, MagicMock, MagicMock]:
    """Run textInput -> gmailSend -> output; return the node result and the Gmail mocks."""
    from app.services.workflow_executor import WorkflowExecutor

    nodes = [
        {"id": "n1", "type": "textInput", "data": {"label": "in", "text": "hi"}},
        {"id": "n2", "type": "gmailSend", "data": {"label": "gmailSend", **data}},
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
        patch("app.services.encryption.decrypt_config", return_value=dict(GMAIL_CONFIG)),
        patch("app.services.file_storage.get_file_path", return_value=file_path),
        patch.object(
            GmailService,
            "send_message",
            return_value={"id": "msg-1", "threadId": "thread-1"},
            side_effect=send_side_effect,
        ) as send,
        patch.object(GmailService, "list_send_as", return_value=send_as or []) as list_send_as,
    ):
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
        )
    node_result = next(r for r in result.node_results if r["node_type"] == "gmailSend")
    return node_result, send, list_send_as


def _sent(send: MagicMock):
    return message_from_bytes(send.call_args.args[0])


BASE = {
    "credentialId": str(uuid.uuid4()),
    "to": "a@x.com",
    "subject": "Hi",
    "emailBody": "Body text",
}


class GmailSendMessageTests(unittest.TestCase):
    def test_to_cc_bcc_and_subject_are_in_the_headers_gmail_reads(self) -> None:
        result, send, _ = _run({**BASE, "cc": "c@x.com", "bcc": "hidden@x.com"})

        self.assertEqual(result["status"], "success")
        msg = _sent(send)
        self.assertEqual(msg["To"], "a@x.com")
        self.assertEqual(msg["Cc"], "c@x.com")
        # Gmail delivers to the Bcc header and leaves it out of what the others receive.
        self.assertEqual(msg["Bcc"], "hidden@x.com")
        self.assertEqual(msg["Subject"], "Hi")
        self.assertIsNotNone(msg["Date"])
        self.assertTrue(msg["Message-ID"].endswith("@example.com>"))

    def test_names_with_accents_keep_the_addresses_gmail_delivers_to(self) -> None:
        result, send, _ = _run(
            {
                **BASE,
                "to": "José García <jose@x.com>, b@x.com",
                "cc": '"Müller, Hans" <hans@y.de>',
                "bcc": "東京チーム <tokyo@x.jp>",
            }
        )

        self.assertEqual(result["status"], "success")
        msg = message_from_bytes(send.call_args.args[0], policy=policy.default)
        headers = {
            name: [(a.display_name, a.addr_spec) for a in msg[name].addresses]
            for name in ("To", "Cc", "Bcc")
        }
        self.assertEqual(
            headers,
            {
                "To": [("José García", "jose@x.com"), ("", "b@x.com")],
                "Cc": [("Müller, Hans", "hans@y.de")],
                "Bcc": [("東京チーム", "tokyo@x.jp")],
            },
        )

    def test_a_blank_from_lets_gmail_use_the_account_address(self) -> None:
        result, send, list_send_as = _run(BASE)

        self.assertIsNone(_sent(send)["From"])
        list_send_as.assert_not_called()
        output = result["output"]
        self.assertEqual(output["from"], "team@example.com")
        self.assertEqual((output["message_id"], output["thread_id"]), ("msg-1", "thread-1"))
        self.assertEqual(output["status"], "sent")
        self.assertEqual(output["attachment_count"], 0)

    def test_a_send_as_alias_becomes_the_from_header_with_its_name(self) -> None:
        aliases = [
            {"sendAsEmail": "team@example.com", "isPrimary": True},
            {
                "sendAsEmail": "support@example.com",
                "displayName": "Support Desk",
                "verificationStatus": "accepted",
            },
        ]
        result, send, _ = _run({**BASE, "fromAddress": "Support@example.com"}, send_as=aliases)

        self.assertEqual(result["status"], "success")
        self.assertEqual(_sent(send)["From"], "Support Desk <support@example.com>")
        self.assertEqual(result["output"]["from"], "Support@example.com")

    def test_an_address_that_is_not_a_verified_alias_fails_before_sending(self) -> None:
        aliases = [
            {"sendAsEmail": "team@example.com", "isPrimary": True},
            {"sendAsEmail": "pending@example.com", "verificationStatus": "pending"},
        ]
        for address in ("pending@example.com", "someone@else.com"):
            with self.subTest(address=address):
                result, send, _ = _run({**BASE, "fromAddress": address}, send_as=aliases)
                self.assertEqual(result["status"], "error")
                self.assertIn("is not a Send mail as address", result["error"])
                send.assert_not_called()

    def test_an_html_body_gets_a_plain_text_alternative(self) -> None:
        _, send, _ = _run({**BASE, "emailBody": "<p>Hello <b>there</b></p>"})

        parts = {part.get_content_type(): part for part in _sent(send).walk()}
        self.assertIn("text/html", parts)
        self.assertEqual(parts["text/plain"].get_payload(decode=True).decode(), "Hello there")

    def test_html_tags_with_attributes_make_an_html_body(self) -> None:
        for body in ('<p style="margin:0">Shipped</p>', 'Shipped<br class="gap">Tracking: 42'):
            with self.subTest(body=body):
                _, send, _ = _run({**BASE, "emailBody": body})

                kinds = {part.get_content_type() for part in _sent(send).walk()}
                self.assertTrue({"text/html", "text/plain"} <= kinds, kinds)

    def test_blank_fields_stay_blank_and_expressions_resolve(self) -> None:
        _, send, _ = _run({**BASE, "subject": "", "emailBody": "Got $in.text"})

        msg = _sent(send)
        self.assertEqual(msg["Subject"], "")
        self.assertIn("Got hi", msg.get_payload()[0].get_payload()[0].get_payload())

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
        result, send, _ = _run(
            {**BASE, "attachments": str(file_id)}, owner_id=owner, db=_db_mock([row])
        )

        self.assertEqual(result["output"]["attachment_count"], 1)
        attached = [part for part in _sent(send).walk() if part.get_filename()]
        self.assertEqual([part.get_filename() for part in attached], ["report.pdf"])
        self.assertEqual(attached[0].get_payload(decode=True), b"PDFDATA")
        self.assertEqual(
            base64.b64decode(attached[0].get_payload()), b"PDFDATA"
        )  # base64 on the wire, as SMTP sends it

    def test_an_attachment_keeps_its_drive_file_type(self) -> None:
        for filename, mime_type in (("chart.png", "image/png"), ("meeting.ics", "text/calendar")):
            with self.subTest(mime_type=mime_type):
                owner = uuid.uuid4()
                file_id = uuid.uuid4()
                row = SimpleNamespace(
                    id=file_id,
                    owner_id=owner,
                    filename=filename,
                    mime_type=mime_type,
                    storage_path=f"{owner}/{file_id}/{filename}",
                )
                _, send, _ = _run(
                    {**BASE, "attachments": str(file_id)}, owner_id=owner, db=_db_mock([row])
                )

                (part,) = [p for p in _sent(send).walk() if p.get_filename()]
                self.assertEqual(part.get_content_type(), mime_type)
                self.assertEqual(part.get_payload(decode=True), b"PDFDATA")

    def test_an_inaccessible_drive_file_fails_before_sending(self) -> None:
        result, send, _ = _run({**BASE, "attachments": str(uuid.uuid4())}, db=_db_mock([None]))

        self.assertEqual(result["status"], "error")
        self.assertIn("Gmail Send: attachment", result["error"])
        send.assert_not_called()


class GmailSendFailureTests(unittest.TestCase):
    def test_missing_credential_and_recipient_fail_before_sending(self) -> None:
        cases = (
            ({**BASE, "credentialId": ""}, "requires a Gmail credential"),
            ({**BASE, "to": "  "}, "Email recipient (to) is required"),
        )
        for data, message in cases:
            with self.subTest(message=message):
                result, send, _ = _run(data)
                self.assertEqual(result["status"], "error")
                self.assertIn(message, result["error"])
                send.assert_not_called()

    def test_a_credential_of_another_type_is_not_used(self) -> None:
        result, send, _ = _run(BASE, credential_type=CredentialType.smtp)

        self.assertEqual(result["status"], "error")
        self.assertIn("Gmail credential not found or not accessible", result["error"])
        send.assert_not_called()

    def test_gmail_refusal_is_reported(self) -> None:
        refusal = GmailApiError(400, "Gmail: Invalid To header")
        result, _, _ = _run(BASE, send_side_effect=refusal)

        self.assertEqual(result["status"], "error")
        self.assertIn("Failed to send email: Gmail: Invalid To header", result["error"])


class GmailSendAgentToolTests(unittest.TestCase):
    def test_every_email_field_can_be_left_to_the_agent(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        fields = ["to", "cc", "bcc", "subject", "emailBody", "attachments", "fromAddress"]
        nodes = [
            {"id": "agent1", "type": "agent", "data": {"label": "agent"}},
            {
                "id": "mail1",
                "type": "gmailSend",
                "data": {"label": "replyByGmail", "agentProvidedFields": fields},
            },
        ]
        edges = [{"id": "e1", "source": "mail1", "target": "agent1", "targetHandle": "tool-input"}]
        schemas = WorkflowExecutor(nodes=nodes, edges=edges)._build_node_tool_schemas("agent1")

        self.assertEqual(sorted(schemas[0]["parameters"]["properties"]), sorted(fields))


if __name__ == "__main__":
    unittest.main()
