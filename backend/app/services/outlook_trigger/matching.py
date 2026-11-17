"""Where an Outlook Trigger looks for mail, and which emails reach its aliases."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from app.services.gmail_trigger.matching import normalize_address, recipient_addresses
from app.services.outlook_trigger.config import OutlookTriggerConfig

# Folders whose mail never counts as received, for the mailboxes that span every folder.
NOT_RECEIVED_FOLDERS: tuple[str, ...] = (
    "sentitems",
    "drafts",
    "deleteditems",
    "junkemail",
    "outbox",
)


@dataclass(frozen=True)
class MailSource:
    """A Graph message listing: its path under /me, an extra filter, and whether it spans
    every folder (then the not-received folders are left out by id)."""

    path: str
    filter: str | None = None
    all_folders: bool = False


def mail_source(config: OutlookTriggerConfig) -> MailSource:
    """The listing that holds the mailbox the trigger watches."""
    mailbox = config.mailbox
    if mailbox == "focused":
        return MailSource("mailFolders/inbox/messages", "inferenceClassification eq 'focused'")
    if mailbox == "other":
        return MailSource("mailFolders/inbox/messages", "inferenceClassification eq 'other'")
    if mailbox == "important":
        return MailSource("messages", "importance eq 'high'", all_folders=True)
    if mailbox == "sent":
        return MailSource("mailFolders/sentitems/messages")
    if mailbox == "all":
        return MailSource("messages", all_folders=True)
    if mailbox == "folder":
        return MailSource(f"mailFolders/{quote(config.folder_id, safe='')}/messages")
    return MailSource("mailFolders/inbox/messages")


def reaches_aliases(config: OutlookTriggerConfig, raw_bytes: bytes) -> bool:
    """True with no aliases set, else when one of them is among the email's recipients."""
    if not config.aliases:
        return True
    wanted = {normalize_address(alias) for alias in config.aliases}
    return bool(wanted & recipient_addresses(raw_bytes))
