"""Editing an earlier user message in a dashboard chat.

Editing works like a rewind: the edited message and every message after it are removed, and
the new text is sent as the conversation's next turn, with the model the client picked. The
model therefore sees the conversation exactly as it stood before the edited message.

An attachment the original message carried stays with the edit. The server stored it as a
block after the message text (`_build_user_message`), so that block is read back here:

- A Drive file is rebuilt from its id, so access is checked again and the turn gets the same
  attachment routing as a new upload.
- Inline text, PDF, image and zip blocks keep their stored text verbatim. Their raw bytes were
  never stored, so a workflow run in the edited turn cannot receive an inline image again.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

DRIVE_FILE_MARKER = "\n\n[ATTACHED DRIVE FILE: "
ATTACHMENT_MARKERS = (
    DRIVE_FILE_MARKER,
    "\n\n[ATTACHED FILE: ",
    "\n\n[ATTACHED IMAGE: ",
    "\n\n[ATTACHED ZIP: ",
)
_DRIVE_FILE_ID = re.compile(
    r" · id ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)

EDIT_WHILE_RUNNING = "Wait for the reply to finish, or stop it, before editing a message."
EDIT_NOT_FOUND = "Message not found"


class StoredMessage(Protocol):
    """The fields of a stored chat message an edit reads."""

    id: uuid.UUID
    role: str
    content: str


@dataclass(frozen=True)
class CarriedAttachment:
    """What an edited message keeps of the attachment its original carried."""

    # Appended verbatim after the edited text (inline files, or a Drive file without an id).
    text_tail: str = ""
    # A Drive file, checked and described again like a new attachment.
    drive_file_id: uuid.UUID | None = None


def split_attachment_block(content: str) -> tuple[str, str]:
    """A stored user message's text, and the attachment block the server appended to it."""
    positions = [index for marker in ATTACHMENT_MARKERS if (index := content.find(marker)) != -1]
    if not positions:
        return content, ""
    start = min(positions)
    return content[:start], content[start:]


def carried_attachment(content: str) -> CarriedAttachment:
    """The attachment a stored user message carried, in the form an edit can send again."""
    _, block = split_attachment_block(content)
    if not block:
        return CarriedAttachment()
    if block.startswith(DRIVE_FILE_MARKER):
        header = block[len(DRIVE_FILE_MARKER) :].split("\n", 1)[0]
        match = _DRIVE_FILE_ID.search(header)
        if match is not None:
            return CarriedAttachment(drive_file_id=uuid.UUID(match.group(1)))
    return CarriedAttachment(text_tail=block)


def messages_from_edit(
    messages: Sequence[StoredMessage], message_id: uuid.UUID
) -> list[StoredMessage] | None:
    """The edited user message and every message after it, in conversation order.

    None when the id is not one of the conversation's user messages.
    """
    for index, message in enumerate(messages):
        if message.id == message_id:
            return list(messages[index:]) if message.role == "user" else None
    return None
