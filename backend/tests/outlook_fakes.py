"""An in-memory Outlook mailbox that answers like Microsoft Graph, for Outlook Trigger tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from app.services.google_triggers.events import ItemWrite
from app.services.outlook_service import OutlookApiError
from app.services.outlook_trigger.reader import OutlookRead

FOLDER_IDS = {
    "inbox": "F-INBOX",
    "sentitems": "F-SENT",
    "drafts": "F-DRAFTS",
    "deleteditems": "F-DELETED",
    "junkemail": "F-JUNK",
    "outbox": "F-OUTBOX",
    "archive": "F-ARCHIVE",
}


@dataclass
class FakeMessage:
    id: str
    received: datetime
    folder: str = "F-INBOX"
    flagged: bool = False
    importance: str = "normal"
    inference: str = "focused"
    to: str = "me@contoso.com"

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "receivedDateTime": self.received.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "conversationId": f"conv-{self.id}",
            "parentFolderId": self.folder,
            "categories": ["Blue category"],
            "importance": self.importance,
            "inferenceClassification": self.inference,
            "flag": {"flagStatus": "flagged" if self.flagged else "notFlagged"},
            "isRead": False,
            "webLink": f"https://outlook.office.com/mail/{self.id}",
            "bodyPreview": f"Preview {self.id}",
        }

    def mime(self) -> bytes:
        message = EmailMessage()
        message["Subject"] = f"Subject {self.id}"
        message["From"] = "sender@example.com"
        message["To"] = self.to
        message["Message-ID"] = f"<{self.id}@example.com>"
        message.set_content(f"Body {self.id}")
        return message.as_bytes()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class FakeOutlook:
    """Implements the OutlookService methods the trigger uses."""

    def __init__(self, address: str = "me@contoso.com") -> None:
        self.address = address
        self.messages: dict[str, FakeMessage] = {}
        self.listings: list[tuple[str, dict[str, Any]]] = []
        self.fetched: list[str] = []
        self.marked_read: list[str] = []
        self.moved: list[tuple[str, str]] = []

    def add(self, message: FakeMessage) -> FakeMessage:
        self.messages[message.id] = message
        return message

    def get_profile(self) -> dict[str, Any]:
        return {"mail": self.address, "userPrincipalName": self.address}

    def folder_id(self, well_known_name: str) -> str | None:
        return FOLDER_IDS.get(well_known_name)

    def list_messages(
        self, path: str, params: dict[str, Any], limit: int
    ) -> tuple[list[dict[str, Any]], bool]:
        self.listings.append((path, dict(params)))
        pool = list(self.messages.values())
        folder = re.fullmatch(r"mailFolders/([^/]+)/messages", path)
        if folder:
            folder_id = FOLDER_IDS.get(folder.group(1), folder.group(1))
            pool = [item for item in pool if item.folder == folder_id]
        query = str(params.get("$filter") or "")
        since = re.search(r"receivedDateTime ge (\S+)", query)
        if since:
            pool = [item for item in pool if item.received >= _parse(since.group(1))]
        if "flag/flagStatus eq 'flagged'" in query:
            pool = [item for item in pool if item.flagged]
        inference = re.search(r"inferenceClassification eq '(\w+)'", query)
        if inference:
            pool = [item for item in pool if item.inference == inference.group(1)]
        importance = re.search(r"importance eq '(\w+)'", query)
        if importance:
            pool = [item for item in pool if item.importance == importance.group(1)]
        pool.sort(key=lambda item: item.received)
        return [item.summary() for item in pool[:limit]], len(pool) <= limit

    def get_mime(self, message_id: str) -> bytes:
        self.fetched.append(message_id)
        if message_id not in self.messages:
            raise OutlookApiError(404, "Outlook: not found")
        return self.messages[message_id].mime()

    def mark_read(self, message_id: str) -> None:
        self.marked_read.append(message_id)

    def move(self, message_id: str, destination: str) -> None:
        self.moved.append((message_id, destination))


def apply_read(stored: dict[str, dict[str, Any]] | None, read: OutlookRead) -> dict[str, Any]:
    """The snapshot after every email of ``read`` ran, as the poller would leave it."""
    if read.baseline or stored is None:
        return dict(read.items)
    snapshot = dict(stored)
    writes: list[ItemWrite] = [email.write for email in read.emails] + list(read.silent)
    for write in writes:
        if write.payload is None:
            snapshot.pop(write.item_key, None)
        else:
            snapshot[write.item_key] = write.payload
    return snapshot
