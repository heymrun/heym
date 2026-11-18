"""Where the Outlook Trigger reads mail: Microsoft Graph, or an Exchange Server over EWS.

The reader works on message summaries shaped like Graph's (``id``, ``receivedDateTime``,
``parentFolderId``, ``flag``...). Each client lists them for a mailbox, oldest first, and
fetches a message's MIME source. ``snapshotKey``, when a client sets it, is what the
snapshot remembers instead of ``id``: EWS ids change when a message moves between folders.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from app.services.outlook_service import OutlookService, account_address
from app.services.outlook_trigger.config import OutlookTriggerConfig
from app.services.outlook_trigger.matching import NOT_RECEIVED_FOLDERS, MailSource, mail_source

SUMMARY_FIELDS = ",".join(
    (
        "id",
        "receivedDateTime",
        "conversationId",
        "parentFolderId",
        "categories",
        "importance",
        "inferenceClassification",
        "flag",
        "isRead",
        "webLink",
        "bodyPreview",
    )
)

Listing = tuple[list[dict[str, Any]], bool]


class MailboxClient(Protocol):
    """What the reader and the after-run actions need from a mailbox."""

    def account_address(self) -> str:
        """The mailbox's own address."""

    def received_since(self, config: OutlookTriggerConfig, since: datetime, limit: int) -> Listing:
        """Received mail in the watched mailbox from ``since``, oldest first; complete flag."""

    def flagged(self, config: OutlookTriggerConfig, limit: int) -> Listing:
        """Flagged mail in the watched mailbox; whether the listing is complete."""

    def get_mime(self, message_id: str) -> bytes:
        """The message's RFC822 source."""

    def mark_read(self, message_id: str) -> None:
        """Mark one message as read."""

    def move(self, message_id: str, destination: str) -> None:
        """Move one message to ``archive`` or ``deleteditems``."""


def _graph_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GraphMailbox:
    """The signed-in Microsoft account's mailbox, through Microsoft Graph."""

    def __init__(self, service: OutlookService) -> None:
        self._service = service

    def account_address(self) -> str:
        return account_address(self._service.get_profile())

    def _excluded(self, source: MailSource) -> frozenset[str]:
        if not source.all_folders:
            return frozenset()
        found = (self._service.folder_id(name) for name in NOT_RECEIVED_FOLDERS)
        return frozenset(folder_id for folder_id in found if folder_id)

    def _without_excluded(self, source: MailSource, listing: Listing) -> Listing:
        excluded = self._excluded(source)
        messages, complete = listing
        kept = [item for item in messages if str(item.get("parentFolderId") or "") not in excluded]
        return kept, complete

    def received_since(self, config: OutlookTriggerConfig, since: datetime, limit: int) -> Listing:
        source = mail_source(config)
        # Graph requires the $orderby property to come first in $filter.
        clauses = [f"receivedDateTime ge {_graph_time(since)}"]
        if source.filter:
            clauses.append(source.filter)
        params = {
            "$filter": " and ".join(clauses),
            "$orderby": "receivedDateTime asc",
            "$select": SUMMARY_FIELDS,
        }
        return self._without_excluded(
            source, self._service.list_messages(source.path, params, limit)
        )

    def flagged(self, config: OutlookTriggerConfig, limit: int) -> Listing:
        source = mail_source(config)
        clauses = ["flag/flagStatus eq 'flagged'"]
        if source.filter:
            clauses.append(source.filter)
        params = {"$filter": " and ".join(clauses), "$select": SUMMARY_FIELDS}
        return self._without_excluded(
            source, self._service.list_messages(source.path, params, limit)
        )

    def get_mime(self, message_id: str) -> bytes:
        return self._service.get_mime(message_id)

    def mark_read(self, message_id: str) -> None:
        self._service.mark_read(message_id)

    def move(self, message_id: str, destination: str) -> None:
        self._service.move(message_id, destination)
