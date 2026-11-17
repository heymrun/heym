from __future__ import annotations

from app.services.email_compose import (
    build_mime_message,
    envelope,
    load_attachments,
    resolve_email_fields,
    sent_output,
)
from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the sendEmail node."""
    import smtplib

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    fields = resolve_email_fields(ctx)

    credential_id = ctx.node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Send Email node requires an SMTP credential")

    with SessionLocal() as db:
        cred = ctx.executor._get_accessible_credential(db, credential_id)
        if cred is None:
            raise ValueError("SMTP credential not found or not accessible")
        smtp_config: dict = decrypt_config(cred.encrypted_config)

    smtp_server = smtp_config.get("smtp_server", "")
    smtp_port = int(smtp_config.get("smtp_port", 587))
    smtp_email = smtp_config.get("smtp_email", "")
    smtp_password = smtp_config.get("smtp_password", "")
    smtp_from = str(smtp_config.get("smtp_from") or "").strip()

    missing_fields = [
        name
        for name, value in (
            ("smtp_server", smtp_server),
            ("smtp_email", smtp_email),
            ("smtp_password", smtp_password),
        )
        if not value
    ]
    if missing_fields:
        raise ValueError(f"SMTP credential requires {', '.join(missing_fields)}")

    if not fields.to:
        raise ValueError("Email recipient (to) is required")

    attachments = load_attachments(ctx, fields, "Send Email")
    msg = build_mime_message(fields, smtp_from or smtp_email, attachments, bcc_header=False)
    all_recipients = [
        addr for group in (fields.to, fields.cc, fields.bcc) for addr in envelope(group)
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

    return sent_output(fields, len(attachments))
