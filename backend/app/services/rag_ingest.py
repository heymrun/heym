"""How an uploaded file becomes vector store chunks.

The one place that decides which files a vector store takes and how their text is read:
documents through FileProcessor, images through the Converter's Tesseract OCR, audio through
the Converter's Whisper transcription, and PDF pages without a text layer through OCR. Upload
routes call it; nothing else keeps its own list (the frontend mirror is
`frontend/src/lib/ragFileTypes.ts`).
"""

from __future__ import annotations

import codecs
import json
from collections.abc import Iterable
from enum import StrEnum

from pypdf.errors import PdfReadError

from app.services import ocr_service, speech_to_text_service
from app.services.file_processor import TextChunk, create_file_processor

# Same rule as frontend/src/lib/textFileSniff.ts.
SNIFF_BYTES = 64 * 1024
MAX_RAG_OCR_PAGES = 200


class RagFileKind(StrEnum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"
    CSV = "csv"
    JSON = "json"
    IMAGE = "image"
    AUDIO = "audio"


DOCUMENT_EXTENSIONS: dict[str, RagFileKind] = {
    ".pdf": RagFileKind.PDF,
    ".md": RagFileKind.MARKDOWN,
    ".markdown": RagFileKind.MARKDOWN,
    ".txt": RagFileKind.TEXT,
    ".csv": RagFileKind.CSV,
    ".json": RagFileKind.JSON,
}
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"})
# .opus is how WhatsApp names its voice notes (Opus in an Ogg container).
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".opus", ".flac"})

FORMATS_SENTENCE = (
    "Vector stores take PDF, Markdown, text, CSV, JSON, images (PNG, JPEG, TIFF, WebP, BMP), "
    "audio (mp3, wav, ogg, opus, flac) and other plain-text files."
)


class RagIngestError(ValueError):
    """A file Heym cannot turn into chunks; the message is shown to the user."""


def _extension(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def reads_as_utf8_text(data: bytes) -> bool:
    """Whether a file is plain text whatever its name.

    Its first 64 KB hold no NUL byte and decode as UTF-8. A character cut at the 64 KB limit
    is not an error when the file goes on; a short file must end on a whole character.
    """
    head = data[:SNIFF_BYTES]
    if b"\x00" in head:
        return False
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head, final=len(data) <= SNIFF_BYTES)
    except UnicodeDecodeError:
        return False
    return True


def classify(filename: str, data: bytes) -> RagFileKind | None:
    """How a file enters a store, or None when Heym cannot read it."""
    ext = _extension(filename)
    if ext in DOCUMENT_EXTENSIONS:
        return DOCUMENT_EXTENSIONS[ext]
    if ext in IMAGE_EXTENSIONS:
        return RagFileKind.IMAGE
    if ext in AUDIO_EXTENSIONS:
        return RagFileKind.AUDIO
    if reads_as_utf8_text(data):
        return RagFileKind.TEXT
    return None


def unsupported_message(filename: str) -> str:
    """The refusal shown for a file `classify` does not take."""
    return f"Heym cannot read {filename}. {FORMATS_SENTENCE}"


def page_ranges(pages: Iterable[int], *, max_len: int) -> list[tuple[int, int]]:
    """Group 1-based page numbers into contiguous ranges of at most `max_len` pages."""
    ranges: list[tuple[int, int]] = []
    for page in sorted(pages):
        if ranges and page == ranges[-1][1] + 1 and page - ranges[-1][0] < max_len:
            ranges[-1] = (ranges[-1][0], page)
        else:
            ranges.append((page, page))
    return ranges


def _pdf_page_texts(data: bytes, filename: str) -> list[str]:
    try:
        return create_file_processor().pdf_page_texts(data)
    except (PdfReadError, ValueError, OSError, KeyError, TypeError) as exc:
        raise RagIngestError(f"Heym could not read {filename} as a PDF.") from exc


def _image_chunks(data: bytes, filename: str, file_size: int) -> list[TextChunk]:
    result = ocr_service.image_to_text(data, filename=filename, language=ocr_service.AUTO_LANGUAGE)
    if not result.text.strip():
        raise RagIngestError(f"No text was found in {filename}.")
    return create_file_processor().process_extracted_text(
        result.text,
        filename,
        file_size,
        file_type="image",
        extra_metadata={"ocr_language": result.language},
    )


def _audio_chunks(data: bytes, filename: str, file_size: int) -> list[TextChunk]:
    result = speech_to_text_service.audio_to_text(
        data, filename=filename, language=speech_to_text_service.AUTO_LANGUAGE
    )
    if not result.text.strip():
        raise RagIngestError(f"No speech was found in {filename}.")
    segments = result.segments or [
        speech_to_text_service.SttSegment(0.0, result.duration_seconds, result.text)
    ]
    return create_file_processor().process_timed_segments(
        segments,
        filename,
        file_size,
        extra_metadata={
            "language": result.language,
            "duration_seconds": round(result.duration_seconds, 2),
        },
    )


def _pdf_chunks_with_ocr(data: bytes, filename: str, file_size: int) -> list[TextChunk]:
    texts = _pdf_page_texts(data, filename)
    blank = [number for number, text in enumerate(texts, start=1) if not text]
    if len(blank) > MAX_RAG_OCR_PAGES:
        raise RagIngestError(
            f"{filename} has {len(blank)} pages without a text layer. Heym reads at most "
            f"{MAX_RAG_OCR_PAGES} of them; split the file."
        )
    for first, last in page_ranges(blank, max_len=ocr_service.MAX_PAGES):
        result = ocr_service.pdf_to_text(
            data, language=ocr_service.AUTO_LANGUAGE, page_range=f"{first}-{last}"
        )
        for page in result.pages:
            texts[page.page - 1] = page.text.strip()
    chunks = create_file_processor().process_pdf_pages(
        texts, filename, file_size, ocr_pages=frozenset(blank)
    )
    if not chunks:
        raise RagIngestError(
            f"No text was found in {filename}, even after reading its pages as images."
        )
    return chunks


def _document_chunks(
    kind: RagFileKind, data: bytes, filename: str, file_size: int
) -> list[TextChunk]:
    processor = create_file_processor()
    if kind is RagFileKind.MARKDOWN:
        return processor.process_markdown(data, filename, file_size)
    if kind is RagFileKind.CSV:
        return processor.process_csv(data, filename, file_size)
    if kind is RagFileKind.JSON:
        try:
            return processor.process_json(data, filename, file_size)
        except json.JSONDecodeError as exc:
            raise RagIngestError(
                f"{filename} is not valid JSON: {exc.msg} (line {exc.lineno})."
            ) from exc
    return processor.process_text(data, filename, file_size)


def quick_chunks(
    kind: RagFileKind, data: bytes, filename: str, file_size: int
) -> list[TextChunk] | None:
    """The file's chunks when they come quickly; None when it needs a background job.

    Audio always needs one, and so does a PDF with a page that has no text layer. Blocking:
    callers run it in a thread.
    """
    if kind is RagFileKind.AUDIO:
        return None
    if kind is RagFileKind.PDF:
        texts = _pdf_page_texts(data, filename)
        if any(not text for text in texts):
            return None
        return create_file_processor().process_pdf_pages(texts, filename, file_size)
    if kind is RagFileKind.IMAGE:
        return _image_chunks(data, filename, file_size)
    return _document_chunks(kind, data, filename, file_size)


def extract_chunks(
    kind: RagFileKind, data: bytes, filename: str, file_size: int
) -> list[TextChunk]:
    """All of the file's chunks, however long reading it takes (background jobs)."""
    if kind is RagFileKind.AUDIO:
        return _audio_chunks(data, filename, file_size)
    if kind is RagFileKind.PDF:
        return _pdf_chunks_with_ocr(data, filename, file_size)
    return quick_chunks(kind, data, filename, file_size) or []
