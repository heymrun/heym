"""Outlook Send through an Exchange Server, over EWS: sent and saved in Sent Items."""

from __future__ import annotations

from typing import Any

from exchangelib import Body, FileAttachment, HTMLBody, Mailbox, Message

from app.services.email_compose import EmailAttachment, EmailFields, is_html_body, recipients
from app.services.exchange_server.connection import ews_account, ews_errors


def _mailboxes(group: str) -> list[Mailbox]:
    """A To, Cc or Bcc field as EWS mailboxes, display names kept."""
    return [
        Mailbox(email_address=address, name=name) if name else Mailbox(email_address=address)
        for name, address in recipients(group)
    ]


def build_message(
    account: Any, fields: EmailFields, from_address: str, attachments: list[EmailAttachment]
) -> Message:
    """The EWS message for the node's fields; Exchange writes the plain-text alternative."""
    body = HTMLBody(fields.body) if is_html_body(fields.body) else Body(fields.body)
    message = Message(
        account=account,
        folder=account.sent,
        subject=fields.subject,
        body=body,
        to_recipients=_mailboxes(fields.to),
        cc_recipients=_mailboxes(fields.cc) or None,
        bcc_recipients=_mailboxes(fields.bcc) or None,
    )
    if from_address:
        # Sending as another address needs Send As permission on that mailbox.
        message.author = Mailbox(email_address=from_address)
    for attachment in attachments:
        message.attach(
            FileAttachment(
                name=attachment.filename,
                content=attachment.content,
                content_type=attachment.mime_type,
            )
        )
    return message


def send_message(
    config: dict[str, Any],
    fields: EmailFields,
    from_address: str,
    attachments: list[EmailAttachment],
) -> None:
    """Send the email from the credential's Exchange Server mailbox."""
    with ews_errors():
        account = ews_account(config)
        build_message(account, fields, from_address, attachments).send_and_save()
