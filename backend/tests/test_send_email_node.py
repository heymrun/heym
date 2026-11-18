"""Unit tests for Send Email node — CC, BCC, and Drive-file attachments."""

import unittest
import uuid
from email import message_from_string, policy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_workflow(email_data: dict) -> tuple[list, list]:
    """textInput -> sendEmail -> output workflow."""
    nodes = [
        {"id": "n1", "type": "textInput", "data": {"label": "in", "text": "hi"}},
        {"id": "n2", "type": "sendEmail", "data": email_data},
        {"id": "n3", "type": "output", "data": {"label": "output"}},
    ]
    edges = [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ]
    return nodes, edges


def _make_db_mock(file_rows_by_first: list, shared_rows_by_first: list | None = None) -> MagicMock:
    """Fake sync SessionLocal context manager. `file_rows_by_first` are returned
    in order from successive `.query(...).filter(...).first()` calls."""
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)
    fake_db.query.return_value.filter.return_value.first.side_effect = list(file_rows_by_first)
    fake_db.query.return_value.join.return_value.join.return_value.filter.return_value.first.side_effect = (
        list(shared_rows_by_first) if shared_rows_by_first is not None else [None] * 10
    )
    return fake_db


def _run_send_email(
    email_data: dict,
    owner_id: uuid.UUID,
    db_mock: MagicMock,
    file_bytes: bytes = b"PDFDATA",
    extra_smtp_config: dict | None = None,
) -> tuple[dict, MagicMock]:
    """Run the workflow; return (sendEmail node_result, captured SMTP server mock).

    Patches: _get_accessible_credential, decrypt_config, smtplib.SMTP, and the
    on-disk file read for attachments.
    """
    from app.services.workflow_executor import WorkflowExecutor

    nodes, edges = _make_workflow(email_data)
    executor = WorkflowExecutor(nodes=nodes, edges=edges)
    executor.trace_user_id = owner_id

    # SMTP credential: bypass DB credential lookup, return decrypted config.
    executor._get_accessible_credential = MagicMock(
        return_value=SimpleNamespace(encrypted_config=b"enc")
    )

    smtp_server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__ = MagicMock(return_value=smtp_server)
    smtp_cm.__exit__ = MagicMock(return_value=False)

    # Attachment bytes read from disk.
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.read_bytes.return_value = file_bytes

    with (
        patch("app.db.session.SessionLocal", return_value=db_mock),
        patch(
            "app.services.encryption.decrypt_config",
            return_value={
                "smtp_server": "smtp.test",
                "smtp_port": 587,
                "smtp_email": "sender@test.com",
                "smtp_password": "pw",
                **(extra_smtp_config or {}),
            },
        ),
        patch("smtplib.SMTP", return_value=smtp_cm),
        patch("smtplib.SMTP_SSL", return_value=smtp_cm),
        patch("app.services.file_storage.get_file_path", return_value=mock_path),
    ):
        result = executor.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "hi"}},
        )

    nr = next((r for r in result.node_results if r["node_type"] == "sendEmail"), None)
    if nr is None:
        raise AssertionError(
            f"sendEmail result missing. Status={result.status}. "
            f"Errors: {[r for r in result.node_results if r.get('status') == 'error']}"
        )
    return nr, smtp_server


def _sent_message(smtp_server: MagicMock):
    """Parse the MIME message passed to server.sendmail; return (envelope, msg)."""
    args = smtp_server.sendmail.call_args
    from_addr, to_addrs, raw = args.args
    return to_addrs, message_from_string(raw)


class SendEmailFromHeaderTests(unittest.TestCase):
    """smtp_from sets the visible From header; login and envelope stay smtp_email."""

    def _send(self, extra_smtp_config: dict) -> tuple[MagicMock, object]:
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "subject": "Hi",
                "emailBody": "Body text",
            },
            uuid.uuid4(),
            _make_db_mock([]),
            extra_smtp_config=extra_smtp_config,
        )
        self.assertEqual(nr["status"], "success")
        self.assertNotIn("from", nr["output"])
        _, msg = _sent_message(server)
        return server, msg

    def _assert_signs_in_as_username(self, server: MagicMock) -> None:
        server.login.assert_called_once_with("sender@test.com", "pw")
        self.assertEqual(server.sendmail.call_args.args[0], "sender@test.com")

    def test_blank_smtp_from_uses_smtp_email(self) -> None:
        for label, extra in (
            ("missing", {}),
            ("empty", {"smtp_from": ""}),
            ("whitespace", {"smtp_from": "   "}),
            ("null", {"smtp_from": None}),
        ):
            with self.subTest(smtp_from=label):
                server, msg = self._send(extra)
                self.assertEqual(msg["From"], "sender@test.com")
                self._assert_signs_in_as_username(server)

    def test_set_smtp_from_becomes_the_from_header(self) -> None:
        server, msg = self._send({"smtp_from": " team@test.com "})
        self.assertEqual(msg["From"], "team@test.com")
        self._assert_signs_in_as_username(server)

    def test_every_message_has_a_date_and_its_own_message_id(self) -> None:
        from email.utils import parsedate_to_datetime

        _, first = self._send({})
        _, second = self._send({"smtp_from": "Acme Support <support@acme.test>"})

        for msg in (first, second):
            self.assertIsNotNone(parsedate_to_datetime(msg["Date"]).tzinfo)
        self.assertTrue(first["Message-ID"].endswith("@test.com>"))
        self.assertTrue(second["Message-ID"].endswith("@acme.test>"))
        self.assertNotEqual(first["Message-ID"], second["Message-ID"])

    def test_a_from_name_with_accents_keeps_its_address(self) -> None:
        server, _ = self._send({"smtp_from": "Café Zürich <team@test.com>"})

        msg = message_from_string(server.sendmail.call_args.args[2], policy=policy.default)
        (sender,) = msg["From"].addresses
        self.assertEqual((sender.display_name, sender.addr_spec), ("Café Zürich", "team@test.com"))
        self._assert_signs_in_as_username(server)


class SendEmailRecipientListTests(unittest.TestCase):
    """To/Cc/Bcc are address lists: a quoted display name may hold a comma."""

    def _envelope(self, **fields: str) -> tuple[list[str], object]:
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "subject": "Hi",
                "emailBody": "Body text",
                **fields,
            },
            uuid.uuid4(),
            _make_db_mock([]),
        )
        self.assertEqual(nr["status"], "success")
        return _sent_message(server)

    def test_a_display_name_with_a_comma_is_one_recipient(self) -> None:
        envelope, msg = self._envelope(
            to='"Doe, John" <john@x.com>, Jane Roe <jane@x.com>',
            cc='"M\u00fcller, Hans" <hans@y.de>',
            bcc="audit@x.com",
        )
        self.assertEqual(envelope, ["john@x.com", "jane@x.com", "hans@y.de", "audit@x.com"])
        self.assertEqual(msg["To"], '"Doe, John" <john@x.com>, Jane Roe <jane@x.com>')

    def test_names_with_accents_keep_their_addresses_in_the_headers(self) -> None:
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "José García <jose@x.com>, b@x.com",
                "cc": '"Müller, Hans" <hans@y.de>',
                "subject": "Hi",
            },
            uuid.uuid4(),
            _make_db_mock([]),
        )
        self.assertEqual(nr["status"], "success")
        self.assertEqual(server.sendmail.call_args.args[1], ["jose@x.com", "b@x.com", "hans@y.de"])

        msg = message_from_string(server.sendmail.call_args.args[2], policy=policy.default)
        to = [(a.display_name, a.addr_spec) for a in msg["To"].addresses]
        cc = [(a.display_name, a.addr_spec) for a in msg["Cc"].addresses]
        self.assertEqual(to, [("José García", "jose@x.com"), ("", "b@x.com")])
        self.assertEqual(cc, [("Müller, Hans", "hans@y.de")])

    def test_plain_comma_separated_addresses_are_unchanged(self) -> None:
        envelope, _ = self._envelope(to="a@x.com, b@x.com,c@x.com,", cc=" ")
        self.assertEqual(envelope, ["a@x.com", "b@x.com", "c@x.com"])


class SendEmailBlankFieldTests(unittest.TestCase):
    """A blank field stays blank instead of becoming the node's whole input."""

    def _send(self, **fields: str) -> tuple[dict, MagicMock]:
        return _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "ops@x.com",
                "subject": "Invoice 42",
                "emailBody": "See attached.",
                **fields,
            },
            uuid.uuid4(),
            _make_db_mock([]),
        )

    def test_blank_subject_sends_an_empty_subject(self) -> None:
        nr, server = self._send(subject="")
        self.assertEqual(nr["status"], "success")
        _, msg = _sent_message(server)
        self.assertEqual(msg["Subject"], "")
        self.assertEqual(nr["output"]["subject"], "")

    def test_blank_body_sends_an_empty_body(self) -> None:
        nr, server = self._send(emailBody="")
        self.assertEqual(nr["status"], "success")
        _, msg = _sent_message(server)
        plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
        self.assertEqual(plain.get_payload(decode=True).decode().strip(), "")

    def test_blank_to_fails_before_sending(self) -> None:
        nr, server = self._send(to="")
        self.assertEqual(nr["status"], "error")
        self.assertEqual(nr["error"], "Email recipient (to) is required")
        server.sendmail.assert_not_called()

    def test_expressions_still_resolve(self) -> None:
        nr, server = self._send(subject="Re: $in.text")
        _, msg = _sent_message(server)
        self.assertEqual(msg["Subject"], "Re: hi")


class SendEmailCcBccTests(unittest.TestCase):
    def test_cc_appears_in_header_and_envelope(self) -> None:
        owner = uuid.uuid4()
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "cc": "c@x.com",
                "subject": "Hi",
                "emailBody": "Body text",
            },
            owner,
            _make_db_mock([]),
        )
        self.assertEqual(nr["status"], "success")
        envelope, msg = _sent_message(server)
        self.assertEqual(msg["Cc"], "c@x.com")
        self.assertIn("a@x.com", envelope)
        self.assertIn("c@x.com", envelope)

    def test_bcc_hidden_from_headers_but_in_envelope(self) -> None:
        owner = uuid.uuid4()
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "bcc": "secret@x.com",
                "subject": "Hi",
                "emailBody": "Body text",
            },
            owner,
            _make_db_mock([]),
        )
        self.assertEqual(nr["status"], "success")
        envelope, msg = _sent_message(server)
        self.assertIsNone(msg["Bcc"])
        self.assertIn("secret@x.com", envelope)
        self.assertIn("a@x.com", envelope)


class SendEmailAttachmentTests(unittest.TestCase):
    def test_drive_file_attached(self) -> None:
        owner = uuid.uuid4()
        file_id = uuid.uuid4()
        file_row = SimpleNamespace(
            id=file_id,
            owner_id=owner,
            filename="report.pdf",
            mime_type="application/pdf",
            storage_path=f"{owner}/{file_id}/report.pdf",
        )
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "subject": "Hi",
                "emailBody": "Body text",
                "attachments": str(file_id),
            },
            owner,
            _make_db_mock([file_row]),
        )
        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["attachment_count"], 1)
        _, msg = _sent_message(server)
        filenames = [p.get_filename() for p in msg.walk() if p.get_filename()]
        self.assertIn("report.pdf", filenames)

    def test_an_attachment_keeps_its_drive_file_type(self) -> None:
        for filename, mime_type, sent_type in (
            ("chart.png", "image/png", "image/png"),
            ("meeting.ics", "text/calendar", "text/calendar"),
            ("report.pdf", "application/pdf", "application/pdf"),
            ("blob", "", "application/octet-stream"),
        ):
            with self.subTest(mime_type=mime_type):
                owner = uuid.uuid4()
                file_id = uuid.uuid4()
                file_row = SimpleNamespace(
                    id=file_id,
                    owner_id=owner,
                    filename=filename,
                    mime_type=mime_type,
                    storage_path=f"{owner}/{file_id}/{filename}",
                )
                nr, server = _run_send_email(
                    {
                        "label": "sendEmail",
                        "credentialId": str(uuid.uuid4()),
                        "to": "a@x.com",
                        "subject": "Hi",
                        "attachments": str(file_id),
                    },
                    owner,
                    _make_db_mock([file_row]),
                )
                self.assertEqual(nr["status"], "success")
                _, msg = _sent_message(server)
                (part,) = [p for p in msg.walk() if p.get_filename()]
                self.assertEqual(part.get_content_type(), sent_type)
                self.assertEqual(part["Content-Transfer-Encoding"], "base64")
                self.assertEqual(part.get_payload(decode=True), b"PDFDATA")

    def test_team_shared_drive_file_attached(self) -> None:
        owner = uuid.uuid4()
        other_user = uuid.uuid4()
        file_id = uuid.uuid4()
        shared_file_row = SimpleNamespace(
            id=file_id,
            owner_id=other_user,
            filename="team_shared_report.pdf",
            mime_type="application/pdf",
            storage_path=f"{other_user}/{file_id}/team_shared_report.pdf",
        )
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "subject": "Hi",
                "emailBody": "Body text",
                "attachments": str(file_id),
            },
            owner,
            _make_db_mock([None], [shared_file_row]),
        )
        self.assertEqual(nr["status"], "success")
        self.assertEqual(nr["output"]["attachment_count"], 1)
        _, msg = _sent_message(server)
        filenames = [p.get_filename() for p in msg.walk() if p.get_filename()]
        self.assertIn("team_shared_report.pdf", filenames)

    def test_invalid_attachment_uuid_errors(self) -> None:
        owner = uuid.uuid4()
        nr, _ = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "subject": "Hi",
                "emailBody": "Body",
                "attachments": "not-a-uuid",
            },
            owner,
            _make_db_mock([]),
        )
        self.assertEqual(nr["status"], "error")
        self.assertIn("attachment", nr["error"].lower())

    def test_inaccessible_attachment_errors(self) -> None:
        owner = uuid.uuid4()
        file_id = uuid.uuid4()
        nr, _ = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "subject": "Hi",
                "emailBody": "Body",
                "attachments": str(file_id),
            },
            owner,
            _make_db_mock([None]),  # owner-scoped lookup returns nothing
        )
        self.assertEqual(nr["status"], "error")
        self.assertIn(str(file_id), nr["error"])


class SendEmailBodyRenderingTests(unittest.TestCase):
    def test_html_body_still_renders_under_mixed(self) -> None:
        owner = uuid.uuid4()
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "subject": "Hi",
                "emailBody": "<html><body><p>Hello</p></body></html>",
            },
            owner,
            _make_db_mock([]),
        )
        self.assertEqual(nr["status"], "success")
        _, msg = _sent_message(server)
        content_types = {p.get_content_type() for p in msg.walk()}
        self.assertIn("text/html", content_types)
        self.assertIn("text/plain", content_types)

    def test_html_tags_with_attributes_make_an_html_body(self) -> None:
        for body in ('<p style="margin:0">Shipped</p>', 'Shipped<br class="gap">Tracking: 42'):
            with self.subTest(body=body):
                nr, server = _run_send_email(
                    {
                        "label": "sendEmail",
                        "credentialId": str(uuid.uuid4()),
                        "to": "a@x.com",
                        "subject": "Hi",
                        "emailBody": body,
                    },
                    uuid.uuid4(),
                    _make_db_mock([]),
                )
                self.assertEqual(nr["status"], "success")
                _, msg = _sent_message(server)
                kinds = {part.get_content_type() for part in msg.walk()}
                self.assertTrue({"text/html", "text/plain"} <= kinds, kinds)

    def test_the_plain_part_of_an_html_body_reads_as_text(self) -> None:
        html = (
            "<html><head><style>body { font-family: Arial }</style></head><body>"
            "<p>Hi Tom &amp; Jerry,</p><p>Your order #42 shipped.</p>"
            "<ul><li>Item A &times; 2</li><li>Item B</li></ul>"
            "<table><tr><td>Total</td><td>&euro;30</td></tr></table>"
            '<p><a href="https://acme.test/t/42">Track it</a></p></body></html>'
        )
        nr, server = _run_send_email(
            {
                "label": "sendEmail",
                "credentialId": str(uuid.uuid4()),
                "to": "a@x.com",
                "subject": "Hi",
                "emailBody": html,
            },
            uuid.uuid4(),
            _make_db_mock([]),
        )
        self.assertEqual(nr["status"], "success")
        _, msg = _sent_message(server)
        plain = next(p for p in msg.walk() if p.get_content_type() == "text/plain")
        self.assertEqual(
            plain.get_payload(decode=True).decode(plain.get_content_charset()),
            "Hi Tom & Jerry,\nYour order #42 shipped.\nItem A \u00d7 2\nItem B\n"
            "Total \u20ac30\nTrack it (https://acme.test/t/42)",
        )


class SendEmailAgentToolTests(unittest.TestCase):
    """sendEmail as an agent tool: cc/bcc/attachments are agent-fillable."""

    def _make_agent_tool_workflow(self) -> tuple[list, list]:
        email_node = {
            "id": "email1",
            "type": "sendEmail",
            "data": {
                "label": "sendMail",
                "credentialId": str(uuid.uuid4()),
                "to": "fixed@x.com",
                "agentProvidedFields": ["to", "cc", "bcc", "attachments"],
            },
        }
        agent_node = {"id": "agent1", "type": "agent", "data": {"label": "agent"}}
        nodes = [agent_node, email_node]
        edges = [
            {
                "id": "e1",
                "source": "email1",
                "target": "agent1",
                "targetHandle": "tool-input",
            }
        ]
        return nodes, edges

    def test_tool_schema_exposes_new_fields(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = self._make_agent_tool_workflow()
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        schemas = executor._build_node_tool_schemas("agent1")

        self.assertEqual(len(schemas), 1)
        props = schemas[0]["parameters"]["properties"]
        for field in ("to", "cc", "bcc", "attachments"):
            self.assertIn(field, props)
        required = schemas[0]["parameters"]["required"]
        for field in ("cc", "bcc", "attachments"):
            self.assertIn(field, required)

    def test_agent_supplied_cc_bcc_used_when_executed(self) -> None:
        owner = uuid.uuid4()
        from app.services.workflow_executor import WorkflowExecutor

        nodes, edges = self._make_agent_tool_workflow()
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        executor.trace_user_id = owner
        executor._get_accessible_credential = MagicMock(
            return_value=SimpleNamespace(encrypted_config=b"enc")
        )

        smtp_server = MagicMock()
        smtp_cm = MagicMock()
        smtp_cm.__enter__ = MagicMock(return_value=smtp_server)
        smtp_cm.__exit__ = MagicMock(return_value=False)

        tool_def = {"_source": "node_tool", "_node_id": "email1"}
        with (
            patch("app.db.session.SessionLocal", return_value=_make_db_mock([])),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={
                    "smtp_server": "smtp.test",
                    "smtp_port": 587,
                    "smtp_email": "sender@test.com",
                    "smtp_password": "pw",
                },
            ),
            patch("smtplib.SMTP", return_value=smtp_cm),
            patch("smtplib.SMTP_SSL", return_value=smtp_cm),
        ):
            out = executor._execute_node_tool(
                tool_def,
                {"to": "agent@x.com", "cc": "agentcc@x.com", "bcc": "agentbcc@x.com"},
            )

        self.assertEqual(out.get("status"), "sent")
        self.assertEqual(out.get("to"), "agent@x.com")
        self.assertEqual(out.get("cc"), "agentcc@x.com")
        self.assertEqual(out.get("bcc"), "agentbcc@x.com")
        envelope, msg = _sent_message(smtp_server)
        self.assertEqual(msg["Cc"], "agentcc@x.com")
        self.assertIn("agentbcc@x.com", envelope)
        self.assertIsNone(msg["Bcc"])


if __name__ == "__main__":
    unittest.main()
