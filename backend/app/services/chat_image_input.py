"""An image attached in chat, handed to a workflow's image input as a data URL.

Chat attachments that are images go to Heym Drive and reach the model only as a file it opens in
the file sandbox. A workflow run from the chat still receives the picture itself: when the
workflow has an input named like an image field, that field gets the image's data URL, as it did
when chat images were sent inline.
"""

from __future__ import annotations

import asyncio
import base64
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.drive_file_access import get_accessible_file
from app.services.file_storage import get_file_path

IMAGE_FIELD_KEYWORDS = frozenset({"image", "base64", "photo", "picture", "img"})
# The most an inline chat image ever carried; a larger picture stays a Drive file.
MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024


def image_field(field_keys: list[str]) -> str | None:
    """The first input named like an image field, or None. Never another field."""
    return next(
        (key for key in field_keys if any(word in key.lower() for word in IMAGE_FIELD_KEYWORDS)),
        None,
    )


def is_image(mime: str | None) -> bool:
    return bool(mime) and str(mime).lower().startswith("image/")


async def image_data_url(db: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID) -> str | None:
    """A Drive image the user can open, as a data URL; None when it is not one or too large."""
    found = await get_accessible_file(db, file_id, user_id)
    if found is None:
        return None
    row = found.file
    if not is_image(row.mime_type) or (row.size_bytes or 0) > MAX_INLINE_IMAGE_BYTES:
        return None
    try:
        data = await asyncio.to_thread(get_file_path(row).read_bytes)
    except (OSError, ValueError):
        return None
    return f"data:{row.mime_type};base64,{base64.b64encode(data).decode('ascii')}"


async def image_input(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    file_id: uuid.UUID | None,
    mime: str | None,
    field_keys: list[str],
) -> tuple[str, str] | None:
    """The image field of a workflow and the attached image's data URL, when both exist."""
    if file_id is None or not is_image(mime):
        return None
    key = image_field(field_keys)
    if key is None:
        return None
    url = await image_data_url(db, user_id, file_id)
    return (key, url) if url else None
