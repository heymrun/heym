from __future__ import annotations

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the sendEmail node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

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
    cc_address = self.evaluate_message_template(cc_template, inputs, node_id) if cc_template else ""
    bcc_address = (
        self.evaluate_message_template(bcc_template, inputs, node_id) if bcc_template else ""
    )
    subject = self.evaluate_message_template(subject_template, inputs, node_id)
    body = self.evaluate_message_template(body_template, inputs, node_id)
    attachments_value = (
        self.evaluate_message_template(attachments_template, inputs, node_id)
        if attachments_template
        else ""
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
    attachment_ids = [token.strip() for token in attachments_value.split(",") if token.strip()]
    if attachment_ids:
        owner_id = self.trace_user_id
        if not owner_id:
            raise ValueError("Send Email: no owner context available for attachments")
        with SessionLocal() as db:
            for token in attachment_ids:
                try:
                    file_uuid = _uuid.UUID(token)
                except ValueError as exc:
                    raise ValueError(f"Send Email: invalid attachment file ID '{token}'") from exc
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
                _, _, subtype = mime_type.partition("/")
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
    return output
