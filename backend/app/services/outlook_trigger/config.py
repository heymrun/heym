"""Outlook Trigger node settings, read from a node's data by the poller.

These fields hold plain values rather than `$` expressions: the poller reads them, never
the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.gmail_trigger.config import parse_aliases, parse_poll_minutes

OUTLOOK_TRIGGER = "outlookTrigger"

MAILBOXES: tuple[str, ...] = (
    "inbox",
    "focused",
    "other",
    "important",
    "sent",
    "all",
    "folder",
)
AFTER_ACTIONS: tuple[str, ...] = ("none", "markRead", "archive", "markReadAndArchive", "delete")


@dataclass(frozen=True)
class OutlookTriggerConfig:
    """What one Outlook Trigger node watches and does with each email."""

    credential_id: str
    mailbox: str
    folder_id: str
    flagged_only: bool
    aliases: tuple[str, ...]
    after_action: str
    poll_minutes: int

    def problem(self) -> str | None:
        """Why this node cannot be polled yet, or None."""
        if not self.credential_id:
            return "no credential selected"
        if self.mailbox == "folder" and not self.folder_id:
            return "no folder selected"
        return None


def parse_outlook_config(data: dict[str, Any]) -> OutlookTriggerConfig:
    """Read an outlookTrigger node's data; unknown values fall back to the defaults."""
    mailbox = str(data.get("outlookMailbox") or "inbox")
    if mailbox not in MAILBOXES:
        mailbox = "inbox"
    after_action = str(data.get("outlookAfterAction") or "none")
    return OutlookTriggerConfig(
        credential_id=str(data.get("credentialId") or "").strip(),
        mailbox=mailbox,
        folder_id=str(data.get("outlookFolderId") or "").strip() if mailbox == "folder" else "",
        flagged_only=data.get("outlookFlaggedOnly") is True,
        aliases=parse_aliases(data.get("outlookAliases")),
        after_action=after_action if after_action in AFTER_ACTIONS else "none",
        poll_minutes=parse_poll_minutes(data.get("pollIntervalMinutes")),
    )
