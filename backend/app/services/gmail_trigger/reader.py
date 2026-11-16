"""Reads what arrived in a Gmail Trigger's mailbox since its cursor.

Synchronous: the poller calls it in a worker thread. The cursor is the account's Gmail
history id; a message fires when it is added with the mailbox's labels, or when one of
those labels is added to it later, like a message showing up in an IMAP folder.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.gmail_service import GmailApiError, GmailService, decode_raw_message
from app.services.gmail_trigger.config import GmailTriggerConfig
from app.services.gmail_trigger.matching import entry_labels, in_mailbox, reaches_aliases
from app.services.imap_trigger_service import email_payload

logger = logging.getLogger("gmail_trigger")

# Messages fetched per poll; the rest wait for the next one.
MAX_MESSAGES_PER_POLL = 50
# History pages (500 records each) read per poll before handing over to the next one.
MAX_HISTORY_PAGES = 20

_AFTER_ACTION_LABELS: dict[str, list[str]] = {
    "markRead": ["UNREAD"],
    "archive": ["INBOX"],
    "markReadAndArchive": ["UNREAD", "INBOX"],
}


def account_scope(email_address: str) -> str:
    """Identity of the Gmail account the cursor belongs to; a reconnect to another resets it."""
    return hashlib.sha256(str(email_address or "").strip().lower().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GmailCursor:
    scope: str
    history_id: int


@dataclass(frozen=True)
class GmailEmail:
    """One email to run, with the history record that brought it into the mailbox."""

    history_id: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class GmailRead:
    """``cursor`` is where the next poll starts once every email here has run.

    ``baseline`` means nothing is to run and ``cursor`` replaces the stored one: a first
    poll, another account behind the credential, or history Gmail no longer keeps.
    """

    cursor: GmailCursor
    emails: list[GmailEmail] = field(default_factory=list)
    baseline: bool = False


@dataclass(frozen=True)
class _Candidate:
    history_id: int
    message_id: str
    # None when the history record carried no labels; decided after the fetch instead.
    labels: tuple[str, ...] | None


def _history_since(service: GmailService, start: int) -> tuple[list[dict[str, Any]], int]:
    """History records after ``start`` and the history id the next poll starts from."""
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    latest = start
    for _ in range(MAX_HISTORY_PAGES):
        page = service.list_history(start, page_token)
        records.extend(item for item in page.get("history") or [] if isinstance(item, dict))
        page_token = page.get("nextPageToken")
        if not page_token:
            latest = max(latest, int(page.get("historyId") or start))
            return records, latest
    # Stopped early: the next poll continues after the last record read here.
    for record in records:
        latest = max(latest, int(record.get("id") or 0))
    return records, latest


def _candidates(
    records: list[dict[str, Any]], config: GmailTriggerConfig, after: int
) -> list[_Candidate]:
    """Messages that entered the mailbox, once each, in history order."""
    entry = entry_labels(config)
    chosen: list[_Candidate] = []
    seen: set[str] = set()

    def consider(message: Any, history_id: int) -> None:
        if not isinstance(message, dict):
            return
        message_id = str(message.get("id") or "")
        if not message_id or message_id in seen:
            return
        raw_labels = message.get("labelIds")
        labels = tuple(str(item) for item in raw_labels) if isinstance(raw_labels, list) else None
        if labels is not None and not in_mailbox(config, labels):
            return
        seen.add(message_id)
        chosen.append(_Candidate(history_id, message_id, labels))

    for record in sorted(records, key=lambda item: int(item.get("id") or 0)):
        history_id = int(record.get("id") or 0)
        if history_id <= after:
            continue
        for added in record.get("messagesAdded") or []:
            consider((added or {}).get("message"), history_id)
        for labelled in record.get("labelsAdded") or []:
            if entry & set((labelled or {}).get("labelIds") or []):
                consider((labelled or {}).get("message"), history_id)
    return chosen


def _gmail_payload(message: dict[str, Any], raw_bytes: bytes) -> dict[str, Any]:
    return {
        "id": str(message.get("id") or ""),
        "threadId": str(message.get("threadId") or ""),
        "labelIds": [str(item) for item in message.get("labelIds") or []],
        "snippet": str(message.get("snippet") or ""),
        **email_payload(raw_bytes),
    }


def read_new_mail(
    service: GmailService, config: GmailTriggerConfig, cursor: GmailCursor | None
) -> GmailRead:
    """Emails that entered the watched mailbox after ``cursor`` and reach the aliases."""
    profile = service.get_profile()
    scope = account_scope(str(profile.get("emailAddress") or ""))
    baseline = GmailRead(GmailCursor(scope, int(profile.get("historyId") or 0)), baseline=True)
    if cursor is None or cursor.scope != scope:
        return baseline
    try:
        records, latest = _history_since(service, cursor.history_id)
    except GmailApiError as exc:
        if exc.status_code == 404:
            logger.info("Gmail history before %s is gone; starting over", cursor.history_id)
            return baseline
        raise

    emails: list[GmailEmail] = []
    candidates = _candidates(records, config, cursor.history_id)
    end = latest
    for index, candidate in enumerate(candidates):
        # Stop between history records, so the next poll never lands inside one.
        previous = candidates[index - 1].history_id if index else None
        if index >= MAX_MESSAGES_PER_POLL and candidate.history_id != previous:
            end = previous or end
            break
        try:
            message = service.get_raw_message(candidate.message_id)
        except GmailApiError as exc:
            if exc.status_code == 404:
                continue  # deleted before this poll
            raise
        if candidate.labels is None and not in_mailbox(config, message.get("labelIds") or []):
            continue
        raw = str(message.get("raw") or "")
        if not raw:
            continue
        raw_bytes = decode_raw_message(raw)
        if not reaches_aliases(config, raw_bytes):
            continue
        emails.append(GmailEmail(candidate.history_id, _gmail_payload(message, raw_bytes)))
    return GmailRead(GmailCursor(scope, max(end, cursor.history_id)), emails)


def apply_after_action(service: GmailService, message_id: str, action: str) -> None:
    """Mark read, archive, or move to Trash. ``none`` and unknown actions do nothing."""
    if action == "trash":
        service.trash_message(message_id)
        return
    remove = _AFTER_ACTION_LABELS.get(action)
    if remove:
        service.modify_labels(message_id, remove=remove)
