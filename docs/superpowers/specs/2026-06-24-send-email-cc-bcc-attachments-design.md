# Send Email node: CC, BCC & Drive-file attachments

**Date:** 2026-06-24
**Status:** Approved (pending spec review)

## Goal

Extend the existing `sendEmail` node so a workflow author can:

- Add **CC** recipients (visible in headers).
- Add **BCC** recipients (delivered but hidden from headers).
- Attach **Drive file(s)** by referencing their Drive file UUID(s), including dynamically
  via `$` expressions (e.g. an upstream Drive node's `id` output).

## Context

- **Backend:** `sendEmail` handling lives in
  `backend/app/services/workflow_executor.py` (~line 7611). It builds a
  `MIMEMultipart("alternative")` message, evaluates `to`/`subject`/`emailBody`
  templates, loads SMTP config from a credential, and sends to
  `to_address.split(",")`.
- **Drive files:** stored as `GeneratedFile` rows (UUID primary key) with bytes on
  disk at `_storage_root() / storage_path`. The Drive node resolves files in an
  owner-scoped context (`workflow_executor.py` ~line 10876+) and can read bytes from
  disk (`driveIncludeBinary` path, ~line 11198).
- **Frontend:** node defaults in `frontend/src/types/node.ts` (`sendEmail` ~line 382);
  config UI in `frontend/src/components/Panels/PropertiesPanel.vue`
  (`sendEmail` template ~line 10126) using `ExpressionInput` for To/Subject/Body.

## Design

### 1. Node data model

Add three fields to `sendEmail` `defaultData` in `node.ts`:

| Field         | Type     | Default | Meaning |
|---------------|----------|---------|---------|
| `cc`          | string   | `""`    | Comma-separated CC recipients, expression-enabled |
| `bcc`         | string   | `""`    | Comma-separated BCC recipients, expression-enabled |
| `attachments` | string   | `""`    | Comma-separated Drive file UUIDs, expression-enabled |

All three are optional; empty means "not used".

### 2. Frontend (PropertiesPanel)

In the `sendEmail` template, after the `To` block, add three `ExpressionInput`
blocks following the existing To/Subject pattern:

- **Cc** — `field-key="cc"`, placeholder `cc@example.com`, helper "Comma-separated for multiple".
- **Bcc** — `field-key="bcc"`, placeholder `bcc@example.com`, helper "Hidden from other recipients".
- **Attachments** — `field-key="attachments"`, placeholder `$drive.id`, helper
  "Comma-separated Drive file IDs. Use `$` expressions, e.g. an upstream Drive node's `id`."

Each wires `:model-value` from `selectedNode.data.<field>` and emits via
`updateNodeData('<field>', $event)`, matching the existing fields.

### 3. Backend executor

In the `sendEmail` branch:

1. Read and evaluate templates: `cc`, `bcc`, `attachments` (via
   `evaluate_message_template`, like `to`).
2. **Message container:** switch from `MIMEMultipart("alternative")` to
   `MIMEMultipart("mixed")`. Build the body as a nested
   `MIMEMultipart("alternative")` (plain + optional html) and attach it to the
   mixed root. This keeps body rendering identical while allowing attachments.
3. **Headers:** set `msg["To"]`, `msg["Cc"] = cc` (only if non-empty), `msg["Subject"]`.
   Do **not** set a `Bcc` header (BCC must stay hidden).
4. **Attachments:** if `attachments` is non-empty, split on `,`, strip whitespace,
   drop empties. For each token:
   - Parse as `uuid.UUID`; invalid → `ValueError("Send Email: invalid attachment file ID '<token>'")`.
   - Look up the `GeneratedFile` in the workflow owner's scope (reuse the same
     owner context the Drive node uses; not accessible → `ValueError` naming the ID).
   - Read bytes from `_storage_root() / storage_path`; missing on disk → `ValueError`.
   - Attach via `email.mime.application.MIMEApplication` (or `MIMEBase` +
     `encoders.encode_base64`) with `Content-Disposition: attachment; filename=<file.filename>`
     and the file's `mime_type` when available.
5. **Recipient envelope:** build the full recipient list as the union of
   `to`, `cc`, and `bcc` (each split on `,`, trimmed, empties dropped) and pass it
   to `server.sendmail(smtp_email, all_recipients, msg.as_string())`. This delivers
   to BCC recipients without exposing them in headers.

### 4. Output

Extend the result dict with:

```python
output = {
    "status": "sent",
    "to": to_address,
    "cc": cc,            # "" when unused
    "bcc": bcc,          # "" when unused
    "subject": subject,
    "attachment_count": <int>,
}
```

### 5. Access control

Attachments resolve **only** files the workflow owner can access — same owner-scoped
lookup as the Drive node. No cross-user file access. Invalid or inaccessible IDs fail
the node with a clear error rather than silently skipping.

## Error handling

- Missing SMTP fields / missing `to`: unchanged (existing validation).
- Invalid attachment UUID, inaccessible file, or file missing on disk: `ValueError`
  with the offending ID — fails the node (no partial/silent send).
- SMTP failures: unchanged (`smtplib.SMTPException` → `ValueError`).

## Testing

Backend tests (extend the existing sendEmail coverage):

1. CC recipients appear in the `Cc` header and in the delivered envelope.
2. BCC recipients are **absent** from headers but **present** in the `sendmail`
   recipient list.
3. A valid Drive file UUID is attached (filename + content present in the message).
4. Invalid UUID and inaccessible/owned-by-other file raise `ValueError`.
5. Body rendering (plain vs html) still works under the new `mixed` container.

Mock SMTP (`smtplib`) and the DB/file lookups with `AsyncMock`/patches per repo
conventions. Run `./check.sh` before push.

## Docs

Update `frontend/src/docs/content/nodes/send-email-node.md` via the
`heym-documentation` skill (new CC/BCC/Attachments fields, Drive-ID usage example).

## Out of scope (YAGNI)

- Visual file picker / multi-select UI for attachments (expression-only for now).
- Attaching arbitrary base64 / upstream binary payloads not stored in Drive.
- Per-attachment rename or inline (CID) images.
