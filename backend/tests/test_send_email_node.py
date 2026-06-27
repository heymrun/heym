"""Unit tests for Send Email node — CC, BCC, and Drive-file attachments."""

import unittest
import uuid
from email import message_from_string
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


def _make_db_mock(file_rows_by_first: list) -> MagicMock:
    """Fake sync SessionLocal context manager. `file_rows_by_first` are returned
    in order from successive `.query(...).filter(...).first()` calls."""
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)
    fake_db.query.return_value.filter.return_value.first.side_effect = list(file_rows_by_first)
    return fake_db


def _run_send_email(
    email_data: dict,
    owner_id: uuid.UUID,
    db_mock: MagicMock,
    file_bytes: bytes = b"PDFDATA",
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
            },
        ),
        patch("smtplib.SMTP", return_value=smtp_cm),
        patch("smtplib.SMTP_SSL", return_value=smtp_cm),
        patch("app.services.file_storage._storage_root") as mock_root,
    ):
        mock_root.return_value.__truediv__ = MagicMock(return_value=mock_path)
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
