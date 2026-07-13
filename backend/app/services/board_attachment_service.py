"""Runtime extraction of a card's attachments.

A card carries its attachments as metadata (file id, name, url). That is not enough for a
workflow to actually use them, so every board run resolves them here: text-bearing files
(pdf, markdown, csv, json, plain text) are extracted to text, images are handed over as a
URL the vision path can load, and anything else is passed through as a plain reference.

The result lands in the workflow payload under ``card.attachments`` (and in the mapper's
reserved ``board`` block), so both the agentic mapper and plain expressions can read it.
"""

import logging
from typing import Any

from app.db.models import GeneratedFile
from app.services.file_processor import create_file_processor
from app.services.file_storage import get_file_path

logger = logging.getLogger(__name__)

# Per-attachment cap; enough for a long document, small enough to keep prompts sane.
MAX_EXTRACTED_CHARS = 20_000

_TEXT_EXTENSIONS = (
    ".pdf",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".txt",
    ".log",
    ".yaml",
    ".yml",
    ".html",
    ".xml",
)


def _kind(name: str, mime_type: str | None) -> str:
    if (mime_type or "").startswith("image/"):
        return "image"
    if (mime_type or "").startswith("text/") or name.lower().endswith(_TEXT_EXTENSIONS):
        return "text"
    return "binary"


def _extract_text(file_bytes: bytes, filename: str) -> str | None:
    """Text of a document, or None when nothing readable came out."""
    try:
        chunks = create_file_processor().process_file(file_bytes, filename)
    except Exception:  # noqa: BLE001 - a broken file must not fail the run
        logger.exception("Attachment text extraction failed for %s", filename)
        return None
    text = "\n\n".join(chunk.text for chunk in chunks).strip()
    if not text:
        return None
    return text[:MAX_EXTRACTED_CHARS]


async def load_card_attachments(db, card: Any) -> list[dict]:
    """Resolve a card's attachments into what a workflow can consume."""
    metadata = getattr(card, "card_metadata", None) or {}
    raw = metadata.get("attachments")
    if not isinstance(raw, list) or not raw:
        return []

    resolved: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "attachment")
        mime_type = entry.get("mime_type")
        attachment: dict[str, Any] = {
            "file_id": entry.get("file_id"),
            "name": name,
            "mime_type": mime_type,
            "size": entry.get("size"),
            "url": entry.get("url"),
            "kind": _kind(name, mime_type),
        }

        if attachment["kind"] == "text":
            stored = await db.get(GeneratedFile, entry["file_id"]) if entry.get("file_id") else None
            if stored is not None:
                path = get_file_path(stored)
                if path.exists():
                    text = _extract_text(path.read_bytes(), name)
                    if text:
                        attachment["text"] = text

        resolved.append(attachment)
    return resolved
