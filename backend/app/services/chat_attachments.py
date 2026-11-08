"""Several files attached to one chat message.

A message carries up to `MAX_CHAT_ATTACHMENTS` files. Each one is stored as its own block after
the message text, in the order it was attached (`ai_assistant._build_user_message`).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, Protocol, TypeVar

MAX_CHAT_ATTACHMENTS = 10


class AttachmentLike(Protocol):
    """The fields a run reads to tell one attachment from another."""

    name: str
    kind: str
    file_id: uuid.UUID | None


AttachmentT = TypeVar("AttachmentT", bound=AttachmentLike)


def stored_attachments(value: object) -> list[dict[str, Any]]:
    """A queue row's attachments: a list, or one dict on rows queued before several files."""
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def run_attachment(
    attachments: Sequence[AttachmentT], inputs: dict[str, Any]
) -> AttachmentT | None:
    """The attachment a workflow run started in this turn receives.

    A single attachment is always the one. With several, the model names the one it means:
    the first whose Drive id, then whose file name, appears in the run's inputs. Otherwise the
    first Drive file, so a File Upload trigger still gets a sample.
    """
    if not attachments:
        return None
    if len(attachments) == 1:
        return attachments[0]
    named = json.dumps(inputs, default=str, ensure_ascii=False)
    for attachment in attachments:
        if attachment.file_id is not None and str(attachment.file_id) in named:
            return attachment
    for attachment in attachments:
        if attachment.name and attachment.name in named:
            return attachment
    return next((attachment for attachment in attachments if attachment.kind == "file"), None)
