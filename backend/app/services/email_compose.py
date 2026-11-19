"""What the Send Email, Gmail Send and Outlook Send nodes share.

The three nodes take the same fields (to, cc, bcc, subject, body, Drive attachments) and
resolve them the same way. This module reads those fields, decides whether the body is
HTML, writes its plain-text alternative, loads the attachments from Drive and builds the
RFC 5322 message that SMTP and Gmail send as is.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr
from typing import Any

from app.services.node_execution.base import NodeExecutionContext

_BLOCK_TAGS = (
    *("p", "div", "br", "li", "tr", "table", "ul", "ol", "blockquote", "hr"),
    *("h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer"),
)
# The tags that make a body HTML, with or without attributes (<p style="...">, <br/>).
# The attributes stop at the next "<" as well as ">", so a body full of unclosed "<p "
# (a forwarded email, a webhook payload, model output) is scanned in linear time.
_HTML_TAG = re.compile(r"<(?:body|div|table|p|br)\b[^<>]*>", re.IGNORECASE)


@dataclass(frozen=True)
class EmailFields:
    """The node's email fields after expressions are resolved."""

    to: str
    cc: str
    bcc: str
    subject: str
    body: str
    attachments: str

    @property
    def attachment_ids(self) -> list[str]:
        """The comma-separated Drive file ids in the Attachments field."""
        return [token.strip() for token in self.attachments.split(",") if token.strip()]


@dataclass(frozen=True)
class EmailAttachment:
    """One Drive file to attach, read with the run owner's access."""

    filename: str
    mime_type: str
    content: bytes


def resolve_email_fields(ctx: NodeExecutionContext) -> EmailFields:
    """Resolve the To, Cc, Bcc, Subject, Body and Attachments fields of the node.

    A blank field stays blank: evaluate_message_template("") returns str(inputs), which
    would mail the run's whole input as the subject or body and skip the recipient check.
    """
    resolve = ctx.executor.evaluate_nonempty_message_template
    data = ctx.node_data

    def field(key: str, default: str = "") -> str:
        return resolve(data.get(key, default), ctx.inputs, ctx.node_id)

    return EmailFields(
        to=field("to"),
        cc=field("cc"),
        bcc=field("bcc"),
        subject=field("subject"),
        body=field("emailBody", "$input.text"),
        attachments=field("attachments"),
    )


def envelope(group: str) -> list[str]:
    """The addresses in one To/Cc/Bcc field, read as an RFC 5322 address list.

    A quoted display name may hold a comma ("Doe, John" <john@x.com>), so the field is not
    split on commas. What the parser rejects (it returns nothing for the whole field) is
    split on commas as before.
    """
    parsed = [addr for _name, addr in getaddresses([group]) if addr]
    return parsed or [addr.strip() for addr in group.split(",") if addr.strip()]


def recipients(group: str) -> list[tuple[str, str]]:
    """The (display name, address) pairs in one To/Cc/Bcc field, in the order written."""
    parsed = [(name, addr) for name, addr in getaddresses([group]) if addr]
    if parsed:
        return parsed
    return [("", addr.strip()) for addr in group.split(",") if addr.strip()]


def address_header(value: str) -> str:
    """An address field as it goes in a From/To/Cc/Bcc header.

    A header with a non-ASCII character is written as one encoded-word, addresses included,
    and a reader then finds no address in it. Each display name is encoded on its own
    instead, so "José García <jose@example.com>" keeps its address. An ASCII field, or one
    the parser cannot read, is used as written.
    """
    if value.isascii():
        return value
    pairs = [(name, addr) for name, addr in getaddresses([value]) if addr]
    if not pairs or not all(addr.isascii() for _name, addr in pairs):
        return value
    return ", ".join(formataddr(pair) for pair in pairs)


def is_html_body(body: str) -> bool:
    """Whether the body reads as HTML; a plain-text body is sent as text/plain."""
    lowered = body.strip().lower()
    return (
        lowered.startswith("<!doctype html")
        or lowered.startswith("<html")
        or _HTML_TAG.search(lowered) is not None
    )


def html_to_text(html: str) -> str:
    """The text/plain alternative of an HTML body, as a text-only client should show it.

    Style, script and head content are dropped, entities are decoded, every block element
    starts a new line, table cells are spaced, and a link keeps its URL so a call to action
    still works.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["style", "script", "head"]):
        tag.decompose()
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        if href.startswith(("http://", "https://")) and href != link.get_text().strip():
            link.append(f" ({href})")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    for cell in soup.find_all(("td", "th")):
        cell.insert_after(" ")
    lines = (re.sub(r"\s+", " ", line).strip() for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def load_attachments(
    ctx: NodeExecutionContext, fields: EmailFields, node_name: str
) -> list[EmailAttachment]:
    """Read every Drive file in the Attachments field with the run owner's access.

    Own files and files shared with one of the owner's teams can be attached, as in the
    Drive node. The files come back in the order their ids were written.
    """
    ids = fields.attachment_ids
    if not ids:
        return []

    from app.db.session import SessionLocal
    from app.services.file_storage import load_readable_file_sync

    owner_id = ctx.executor.trace_user_id
    if not owner_id:
        raise ValueError(f"{node_name}: no owner context available for attachments")
    attachments: list[EmailAttachment] = []
    with SessionLocal() as db:
        for token in ids:
            try:
                file_uuid = uuid.UUID(token)
            except ValueError as exc:
                raise ValueError(f"{node_name}: invalid attachment file ID '{token}'") from exc
            file_row, file_bytes = load_readable_file_sync(
                db,
                file_id=file_uuid,
                owner_id=owner_id,
                context=f"{node_name}: attachment",
            )
            attachments.append(
                EmailAttachment(
                    filename=file_row.filename,
                    mime_type=file_row.mime_type or "application/octet-stream",
                    content=file_bytes,
                )
            )
    return attachments


def build_mime_message(
    fields: EmailFields,
    sender: str,
    attachments: list[EmailAttachment],
    *,
    bcc_header: bool,
    account: str = "",
) -> MIMEMultipart:
    """The message as it is sent: headers, the body and its alternative, then attachments.

    SMTP sends Bcc only in the envelope. Gmail reads the recipients from the headers and
    removes the Bcc header from what other recipients get, so it needs ``bcc_header``.
    A blank ``sender`` leaves From to the provider; ``account`` then names the domain of
    the Message-ID.
    """
    msg = MIMEMultipart("mixed")
    if sender:
        msg["From"] = address_header(sender)
    # RFC 5322 requires Date; Gmail refuses mail without a Message-ID. Relays that do not add
    # missing headers for remote clients (Postfix's default) pass the message on as built.
    msg["Date"] = formatdate(localtime=True)
    domain = parseaddr(sender or account)[1].rpartition("@")[2]
    msg["Message-ID"] = make_msgid(domain=domain or None)
    msg["To"] = address_header(fields.to)
    if fields.cc:
        msg["Cc"] = address_header(fields.cc)
    if bcc_header and fields.bcc:
        msg["Bcc"] = address_header(fields.bcc)
    msg["Subject"] = fields.subject

    body_part = MIMEMultipart("alternative")
    if is_html_body(fields.body):
        body_part.attach(MIMEText(html_to_text(fields.body), "plain"))
        body_part.attach(MIMEText(fields.body, "html"))
    else:
        body_part.attach(MIMEText(fields.body, "plain"))
    msg.attach(body_part)

    for attachment in attachments:
        maintype, _, subtype = attachment.mime_type.partition("/")
        if subtype and maintype not in ("multipart", "message"):
            # The file's own type (image/png, text/calendar), base64 like any attachment.
            part = MIMEBase(maintype, subtype)
            part.set_payload(attachment.content)
            encoders.encode_base64(part)
        else:
            # A multipart or message body must not be base64 encoded; send it as data.
            part = MIMEApplication(attachment.content, _subtype=subtype or "octet-stream")
        part.add_header("Content-Disposition", "attachment", filename=attachment.filename)
        msg.attach(part)
    return msg


def sent_output(fields: EmailFields, attachment_count: int, **extra: Any) -> dict[str, Any]:
    """The node output every email node returns, plus the provider's own fields."""
    return {
        "status": "sent",
        "to": fields.to,
        "cc": fields.cc,
        "bcc": fields.bcc,
        "subject": fields.subject,
        "attachment_count": attachment_count,
        **extra,
    }
