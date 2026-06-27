# Send Email CC / BCC / Drive Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CC, BCC, and Drive-file attachment support to the existing `sendEmail` workflow node.

**Architecture:** Three new optional, expression-enabled fields (`cc`, `bcc`, `attachments`) on the `sendEmail` node. The backend executor evaluates them like `to`, builds a `MIMEMultipart("mixed")` message (nested `alternative` body part) so attachments can be added, resolves comma-separated Drive file UUIDs in the workflow owner's scope (reading bytes from disk like the Drive node), sets a `Cc` header (never a `Bcc` header), and sends to the combined to+cc+bcc envelope.

**Tech Stack:** Python 3.11 / FastAPI / smtplib / email.mime; Vue 3 + TypeScript (PropertiesPanel `ExpressionInput`).

---

## File Structure

- `frontend/src/types/node.ts` — add `cc`, `bcc`, `attachments` to `sendEmail.defaultData`.
- `frontend/src/components/Panels/PropertiesPanel.vue` — add Cc / Bcc / Attachments UI in the `sendEmail` template.
- `backend/app/services/workflow_executor.py` — `sendEmail` branch: CC/BCC headers, mixed container, attachment resolution, combined envelope, extended output.
- `backend/tests/test_send_email_node.py` — new test file covering CC header, BCC hidden+delivered, attachment resolution, invalid/inaccessible IDs, body rendering under mixed container.
- `frontend/src/docs/content/nodes/send-email-node.md` — doc update (via heym-documentation skill).

---

## Task 1: Add node default fields (frontend types)

**Files:**
- Modify: `frontend/src/types/node.ts` (sendEmail `defaultData`, ~line 390-396)

- [ ] **Step 1: Add the three fields to defaultData**

In `frontend/src/types/node.ts`, change the `sendEmail.defaultData` block from:

```ts
    defaultData: {
      label: "sendEmail",
      credentialId: "",
      to: "",
      subject: "",
      emailBody: "$input.text",
    },
```

to:

```ts
    defaultData: {
      label: "sendEmail",
      credentialId: "",
      to: "",
      cc: "",
      bcc: "",
      subject: "",
      emailBody: "$input.text",
      attachments: "",
    },
```

- [ ] **Step 2: Verify typecheck passes**

Run: `cd frontend && bun run typecheck`
Expected: PASS (no new errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/node.ts
git commit -m "feat(send-email): add cc/bcc/attachments node defaults"
```

---

## Task 2: Add Cc / Bcc / Attachments fields to the node UI

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue` (sendEmail template, after the `To` block ~line 10164, before the `Subject` block ~line 10166)

- [ ] **Step 1: Insert Cc, Bcc, and Attachments blocks**

In `PropertiesPanel.vue`, locate the `To` block inside `<template v-if="selectedNode.type === 'sendEmail'">`. It ends with:

```html
              <p class="text-xs text-muted-foreground">
                Recipient email (comma-separated for multiple)
              </p>
            </div>
```

Immediately AFTER that closing `</div>` (and before the `<div class="space-y-2">` that contains the `Subject` label), insert:

```html
            <div class="space-y-2">
              <Label>Cc</Label>
              <ExpressionInput
                :model-value="selectedNode.data.cc || ''"
                placeholder="cc@example.com"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Cc"
                field-key="cc"
                @update:model-value="updateNodeData('cc', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Carbon copy (comma-separated for multiple)
              </p>
            </div>

            <div class="space-y-2">
              <Label>Bcc</Label>
              <ExpressionInput
                :model-value="selectedNode.data.bcc || ''"
                placeholder="bcc@example.com"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Bcc"
                field-key="bcc"
                @update:model-value="updateNodeData('bcc', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Blind carbon copy — hidden from other recipients
              </p>
            </div>
```

- [ ] **Step 2: Add the Attachments block after the Body block**

The `Body` block ends with:

```html
              <p class="text-xs text-muted-foreground">
                Use $ expressions like {{ exampleRef }}
              </p>
            </div>
          </template>
```

Insert a new block AFTER the Body's closing `</div>` and BEFORE `</template>`:

```html
            <div class="space-y-2">
              <Label>Attachments</Label>
              <ExpressionInput
                :model-value="selectedNode.data.attachments || ''"
                placeholder="$drive.id"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Attachments"
                field-key="attachments"
                @update:model-value="updateNodeData('attachments', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Comma-separated Drive file IDs. Use $ expressions, e.g. an upstream Drive node's id.
              </p>
            </div>
```

- [ ] **Step 3: Verify lint + typecheck pass**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat(send-email): add cc/bcc/attachments fields to node UI"
```

---

## Task 3: Backend executor — CC / BCC / attachments (TDD)

**Files:**
- Create: `backend/tests/test_send_email_node.py`
- Modify: `backend/app/services/workflow_executor.py` (sendEmail branch, ~line 7611-7693)

### 3a. Write the failing tests

- [ ] **Step 1: Create the test file**

Create `backend/tests/test_send_email_node.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_send_email_node.py -v`
Expected: FAIL — `test_cc_*`, `test_bcc_*`, and attachment tests fail because `Cc` header is missing, BCC not in envelope, `attachment_count` not in output, and the mixed/attachment logic does not exist yet.

### 3b. Implement the executor changes

- [ ] **Step 3: Replace the sendEmail branch body**

In `backend/app/services/workflow_executor.py`, replace the entire `elif node_type == "sendEmail":` block (currently ~lines 7611-7693) with:

```python
            elif node_type == "sendEmail":
                import smtplib
                import uuid as _uuid
                from email.mime.application import MIMEApplication
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText

                from app.db.models import GeneratedFile
                from app.db.session import SessionLocal
                from app.services.encryption import decrypt_config
                from app.services.file_storage import _storage_root

                to_template = node_data.get("to", "")
                cc_template = node_data.get("cc", "")
                bcc_template = node_data.get("bcc", "")
                subject_template = node_data.get("subject", "")
                body_template = node_data.get("emailBody", "$input.text")
                attachments_template = node_data.get("attachments", "")

                to_address = self.evaluate_message_template(to_template, inputs, node_id)
                cc_address = self.evaluate_message_template(cc_template, inputs, node_id)
                bcc_address = self.evaluate_message_template(bcc_template, inputs, node_id)
                subject = self.evaluate_message_template(subject_template, inputs, node_id)
                body = self.evaluate_message_template(body_template, inputs, node_id)
                attachments_value = self.evaluate_message_template(
                    attachments_template, inputs, node_id
                )

                credential_id = node_data.get("credentialId")
                if not credential_id:
                    raise ValueError("Send Email node requires an SMTP credential")

                smtp_config: dict = {}
                with SessionLocal() as db:
                    cred = self._get_accessible_credential(db, credential_id)
                    if cred:
                        smtp_config = decrypt_config(cred.encrypted_config)

                smtp_server = smtp_config.get("smtp_server", "")
                smtp_port = int(smtp_config.get("smtp_port", 587))
                smtp_email = smtp_config.get("smtp_email", "")
                smtp_password = smtp_config.get("smtp_password", "")

                if not all([smtp_server, smtp_email, smtp_password]):
                    raise ValueError("SMTP credential is missing required fields")

                if not to_address:
                    raise ValueError("Email recipient (to) is required")

                msg = MIMEMultipart("mixed")
                msg["From"] = smtp_email
                msg["To"] = to_address
                if cc_address:
                    msg["Cc"] = cc_address
                msg["Subject"] = subject

                body_lower = body.strip().lower()
                is_html = (
                    body_lower.startswith("<!doctype html")
                    or body_lower.startswith("<html")
                    or "<body" in body_lower
                    or "<div" in body_lower
                    or "<table" in body_lower
                    or "<p>" in body_lower
                    or "<br>" in body_lower
                    or "<br/>" in body_lower
                    or "<br />" in body_lower
                )

                body_part = MIMEMultipart("alternative")
                if is_html:
                    import re

                    plain_text = re.sub(r"<[^>]+>", "", body)
                    plain_text = re.sub(r"\s+", " ", plain_text).strip()
                    body_part.attach(MIMEText(plain_text, "plain"))
                    body_part.attach(MIMEText(body, "html"))
                else:
                    body_part.attach(MIMEText(body, "plain"))
                msg.attach(body_part)

                attachment_count = 0
                attachment_ids = [
                    token.strip() for token in attachments_value.split(",") if token.strip()
                ]
                if attachment_ids:
                    owner_id = self.trace_user_id
                    if not owner_id:
                        raise ValueError("Send Email: no owner context available for attachments")
                    with SessionLocal() as db:
                        for token in attachment_ids:
                            try:
                                file_uuid = _uuid.UUID(token)
                            except ValueError as exc:
                                raise ValueError(
                                    f"Send Email: invalid attachment file ID '{token}'"
                                ) from exc
                            file_row = (
                                db.query(GeneratedFile)
                                .filter(
                                    GeneratedFile.id == file_uuid,
                                    GeneratedFile.owner_id == owner_id,
                                )
                                .first()
                            )
                            if not file_row:
                                raise ValueError(
                                    f"Send Email: attachment file not found or access denied: {file_uuid}"
                                )
                            disk_path = _storage_root() / file_row.storage_path
                            if not disk_path.exists():
                                raise ValueError(
                                    f"Send Email: attachment file missing on disk: {file_row.filename}"
                                )
                            file_bytes = disk_path.read_bytes()
                            mime_type = file_row.mime_type or "application/octet-stream"
                            maintype, _, subtype = mime_type.partition("/")
                            part = MIMEApplication(file_bytes, _subtype=subtype or "octet-stream")
                            part.add_header(
                                "Content-Disposition",
                                "attachment",
                                filename=file_row.filename,
                            )
                            msg.attach(part)
                            attachment_count += 1

                all_recipients = [
                    addr.strip()
                    for group in (to_address, cc_address, bcc_address)
                    for addr in group.split(",")
                    if addr.strip()
                ]

                try:
                    if smtp_port == 465:
                        with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30) as server:
                            server.login(smtp_email, smtp_password)
                            server.sendmail(smtp_email, all_recipients, msg.as_string())
                    else:
                        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
                            server.starttls()
                            server.login(smtp_email, smtp_password)
                            server.sendmail(smtp_email, all_recipients, msg.as_string())
                except smtplib.SMTPException as e:
                    raise ValueError(f"Failed to send email: {e}")

                output = {
                    "status": "sent",
                    "to": to_address,
                    "cc": cc_address,
                    "bcc": bcc_address,
                    "subject": subject,
                    "attachment_count": attachment_count,
                }
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_send_email_node.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Run ruff and format**

Run: `cd backend && uv run ruff check . && uv run ruff format --check .`
Expected: PASS (apply `uv run ruff format .` and re-stage if formatting changes are reported).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/workflow_executor.py backend/tests/test_send_email_node.py
git commit -m "feat(send-email): support cc, bcc, and Drive-file attachments"
```

---

## Task 4: Update node documentation

**Files:**
- Modify: `frontend/src/docs/content/nodes/send-email-node.md`

- [ ] **Step 1: Invoke the heym-documentation skill**

Use the `heym-documentation` skill to update `send-email-node.md`. Document the new fields:
- **Cc** — comma-separated carbon-copy recipients (expression-enabled).
- **Bcc** — comma-separated blind-copy recipients; hidden from other recipients.
- **Attachments** — comma-separated Drive file IDs (expression-enabled). Example: reference an upstream Drive node's `id` output, e.g. `$drive.id`. Only files owned by the workflow owner can be attached.

Add a short example showing a Drive node feeding the Send Email node's Attachments field.

- [ ] **Step 2: Verify docs build/lint**

Run: `cd frontend && bun run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs/content/nodes/send-email-node.md
git commit -m "docs(send-email): document cc, bcc, and attachments"
```

---

## Final verification

- [ ] **Run the full check suite**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: frontend lint/typecheck pass, backend ruff passes, backend tests pass (including `test_send_email_node.py`).

- [ ] **Optional E2E (if practical):** add a Playwright spec in `frontend/e2e/` that opens a Send Email node and asserts the Cc, Bcc, and Attachments fields render; run with `./run_e2e.sh`.

---

## Notes / gotchas

- `decrypt_config`, `smtplib`, and `_storage_root` are imported **inside** the `sendEmail` branch — tests patch them at their source modules (`app.services.encryption.decrypt_config`, `smtplib.SMTP`, `app.services.file_storage._storage_root`) and patch `app.db.session.SessionLocal`.
- Attachment file lookup mirrors the Drive node exactly: sync `db.query(GeneratedFile).filter(id ==, owner_id ==).first()` under `SessionLocal()`, owner from `self.trace_user_id`.
- `Bcc` is deliberately never set as a header; BCC delivery happens only via the `sendmail` envelope (`all_recipients`).
- The body becomes a nested `MIMEMultipart("alternative")` inside a `MIMEMultipart("mixed")` root so plain/html rendering is unchanged while attachments are siblings of the body part.
```
