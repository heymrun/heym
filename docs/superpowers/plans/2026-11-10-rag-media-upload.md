# RAG Media Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vector store uploads in Heym and Work accept images (OCR), audio (Whisper, in the background), scanned PDF pages (OCR fallback, in the background) and UTF-8 text files of any name.

**Architecture:** One backend module (`rag_ingest.py`) decides how a file becomes chunks, reusing the Converter's `ocr_service` and `speech_to_text_service`. Files that take minutes become rows in a new `vector_store_ingest_jobs` table, processed by an asyncio task in the accepting process with a heartbeat; stale rows fail lazily when listed. Heym's frontend gets an API-free file-type helper and polling core that Work imports through `@heym/...`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, pypdf, Tesseract (`ocr_service`), whisper.cpp (`speech_to_text_service`), Vue 3 + TypeScript, Vitest, Playwright.

Spec: `docs/superpowers/specs/2026-11-10-rag-media-upload-design.md`.

---

## File map

heymrun (`/Users/cerenakgun/Documents/Projects/heym_workspace/heym`):

| File | Change |
|---|---|
| `backend/app/services/file_processor.py` | split PDF path; add `process_extracted_text`, `process_timed_segments` |
| `backend/app/services/rag_ingest.py` | new: classify, UTF-8 rule, quick and full extraction |
| `backend/app/db/models.py` | new `VectorStoreIngestJob` model |
| `backend/alembic/versions/154_vector_store_ingest_jobs.py` | new migration |
| `backend/app/services/rag_ingest_jobs.py` | new: enqueue, run, heartbeat, stale, list, dismiss |
| `backend/app/models/schemas.py` | upload response fields, job response models |
| `backend/app/api/vector_stores.py` | upload rewrite, `GET/DELETE ingest-jobs` |
| `backend/tests/test_file_processor.py` | extend |
| `backend/tests/test_rag_ingest.py` | new |
| `backend/tests/test_rag_ingest_jobs.py` | new (mocked sessions) |
| `backend/tests/test_rag_ingest_jobs_postgres.py` | new (real PostgreSQL) |
| `backend/tests/test_vector_store_upload_api.py` | new |
| `backend/tests/test_alembic_migrations.py` | new head |
| `frontend/src/types/ragIngest.ts` | new job types |
| `frontend/src/lib/ragFileTypes.ts` (+ `.test.ts`) | new |
| `frontend/src/lib/ragIngestJobs.ts` (+ `.test.ts`) | new polling core |
| `frontend/src/services/api.ts` | upload response fields, `listIngestJobs`, `dismissIngestJob` |
| `frontend/src/components/VectorStores/VectorStoreIngestJobs.vue` | new |
| `frontend/src/components/VectorStores/VectorStoresPanel.vue` | picker, format line, queued message, jobs in items dialog |
| `frontend/e2e/tab-vectors.spec.ts` | mocked upload flow |
| `frontend/src/docs/content/tabs/vectorstores-tab.md`, `nodes/rag-node.md`, `reference/features.md` | docs |
| `frontend/src/features/release-tour/releaseRegistry.ts`, `tourVisuals.ts`, `components/visuals/RagMediaUploadTourVisual.vue` | tour |

heym-work (`/Users/cerenakgun/Documents/Projects/heym_workspace/heym-work`):

| File | Change |
|---|---|
| `backend/heym_work/api/heym_routes.py` | two job routes |
| `backend/heym_work/api/schemas.py` | `VectorStoreUploadView.status`, `.job_id` |
| `backend/tests/test_heym_routes.py`, `backend/tests/test_data_files.py` | extend |
| `frontend/src/types/api.ts` | `StoreUploadResult` fields |
| `frontend/src/services/heymApi.ts` | `heymRag.ingestJobs`, `heymRag.dismissIngestJob` |
| `frontend/src/lib/ragUpload.ts` (+ test) | async plan over `@heym/lib/ragFileTypes` |
| `frontend/src/composables/useStoreUpload.ts` (+ test) | queued notice |
| `frontend/src/components/rag/RagIngestJobs.vue` | new |
| `frontend/src/components/rag/RagDocuments.vue` | picker, format line, jobs |
| `vendor/heymrun` | pin to the Heym merge commit |

---

## Part A: heymrun backend

### Task 1: Branch

- [ ] **Step 1: Create the feature branch**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym
git checkout main && git pull --ff-only
git checkout -b feat/rag-media-upload
```

### Task 2: FileProcessor building blocks

**Files:**
- Modify: `backend/app/services/file_processor.py` (the `process_pdf` method and new methods after `process_text`)
- Test: `backend/tests/test_file_processor.py`

- [ ] **Step 1: Write the failing tests** (append to `backend/tests/test_file_processor.py`)

```python
from dataclasses import dataclass as _dataclass


@_dataclass
class _Segment:
    start: float
    end: float
    text: str


class PdfPageSplitTests(unittest.TestCase):
    def test_page_texts_keep_blank_pages_as_empty_strings(self) -> None:
        texts = FileProcessor().pdf_page_texts(_build_pdf("First page", "", "Third page"))

        self.assertEqual(texts, ["First page", "", "Third page"])

    def test_process_pdf_pages_marks_ocr_pages(self) -> None:
        chunks = FileProcessor().process_pdf_pages(
            ["Typed text", "Scanned text"], "scan.pdf", 42, ocr_pages=frozenset({2})
        )

        self.assertEqual([c.metadata["page"] for c in chunks], [1, 2])
        self.assertNotIn("ocr", chunks[0].metadata)
        self.assertTrue(chunks[1].metadata["ocr"])
        self.assertEqual(chunks[1].metadata["total_pages"], 2)
        self.assertEqual(chunks[1].metadata["file_type"], "pdf")

    def test_process_pdf_output_is_unchanged_by_the_split(self) -> None:
        pdf = _build_pdf("Alpha page", "", "Gamma page")
        processor = FileProcessor()

        via_pages = processor.process_pdf_pages(
            processor.pdf_page_texts(pdf), "a.pdf", len(pdf)
        )

        self.assertEqual(processor.process_pdf(pdf, "a.pdf"), via_pages)
        self.assertEqual([c.metadata["page"] for c in via_pages], [1, 3])


class ExtractedTextTests(unittest.TestCase):
    def test_extracted_text_carries_type_and_extra_metadata(self) -> None:
        chunks = FileProcessor().process_extracted_text(
            "Invoice 2026 total 40 EUR",
            "photo.png",
            10,
            file_type="image",
            extra_metadata={"ocr_language": "eng"},
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["file_type"], "image")
        self.assertEqual(chunks[0].metadata["ocr_language"], "eng")
        self.assertEqual(chunks[0].metadata["source"], "photo.png")


class TimedSegmentTests(unittest.TestCase):
    def test_segments_group_up_to_chunk_size_and_keep_their_times(self) -> None:
        # 19 + 12 characters fit in 40 with their separators; the third segment does not.
        processor = FileProcessor(chunk_size=40, overlap=5)
        segments = [
            _Segment(0.0, 2.0, "Hello there friend."),
            _Segment(2.0, 4.5, "How are you?"),
            _Segment(4.5, 9.0, "The invoice is late."),
        ]

        chunks = processor.process_timed_segments(
            segments, "call.mp3", 99, extra_metadata={"language": "en"}
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].metadata["start_seconds"], 0.0)
        self.assertEqual(chunks[0].metadata["end_seconds"], 4.5)
        self.assertEqual(chunks[1].metadata["start_seconds"], 4.5)
        self.assertEqual(chunks[1].metadata["end_seconds"], 9.0)
        self.assertEqual(chunks[1].metadata["file_type"], "audio")
        self.assertEqual(chunks[1].metadata["language"], "en")
        self.assertIn("The invoice is late.", chunks[1].text)

    def test_blank_segments_are_skipped(self) -> None:
        chunks = FileProcessor().process_timed_segments(
            [_Segment(0.0, 1.0, "  "), _Segment(1.0, 2.0, "Words")], "a.wav", 1
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["start_seconds"], 1.0)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_file_processor.py -q`
Expected: FAIL, `AttributeError: 'FileProcessor' object has no attribute 'pdf_page_texts'` (and the other new methods).

- [ ] **Step 3: Implement**

At the top of `file_processor.py`, add `from collections.abc import Sequence` and `from typing import Protocol` to the standard-library imports, and this protocol after `TextChunk`:

```python
class TimedSegment(Protocol):
    """A stretch of transcribed speech; `speech_to_text_service.SttSegment` is one."""

    start: float
    end: float
    text: str
```

Replace the whole `process_pdf` method with:

```python
    def pdf_page_texts(self, file_content: bytes) -> list[str]:
        """Each page's cleaned text layer, in order; "" for a page that has none."""
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_content))
        texts: list[str] = []
        for page in reader.pages:
            raw = page.extract_text() or ""
            cleaned = self._clean_pdf_text(raw) if raw.strip() else ""
            texts.append(cleaned if cleaned.strip() else "")
        return texts

    def process_pdf_pages(
        self,
        page_texts: Sequence[str],
        filename: str,
        file_size: int,
        ocr_pages: frozenset[int] = frozenset(),
    ) -> list[TextChunk]:
        """Chunk per-page text; pages listed in `ocr_pages` were read by OCR."""
        chunks: list[TextChunk] = []
        total = len(page_texts)
        for page_num, text in enumerate(page_texts, start=1):
            if not text.strip():
                continue
            metadata: dict = {
                "source": filename,
                "file_size": file_size,
                "page": page_num,
                "total_pages": total,
                "file_type": "pdf",
            }
            if page_num in ocr_pages:
                metadata["ocr"] = True
            chunks.extend(self._chunk_text(text, base_metadata=metadata))
        return self._add_context_overlap(chunks)

    def process_pdf(
        self, file_content: bytes, filename: str, file_size: int | None = None
    ) -> list[TextChunk]:
        actual_size = file_size if file_size is not None else len(file_content)
        return self.process_pdf_pages(self.pdf_page_texts(file_content), filename, actual_size)
```

After `process_text`, add:

```python
    def process_extracted_text(
        self,
        text: str,
        filename: str,
        file_size: int,
        *,
        file_type: str,
        extra_metadata: dict | None = None,
    ) -> list[TextChunk]:
        """Chunk text that came out of another reader (OCR, for example)."""
        chunks = self._chunk_text(
            text,
            base_metadata={
                "source": filename,
                "file_size": file_size,
                "file_type": file_type,
                **(extra_metadata or {}),
            },
        )
        return self._add_context_overlap(chunks)

    def process_timed_segments(
        self,
        segments: Sequence[TimedSegment],
        filename: str,
        file_size: int,
        extra_metadata: dict | None = None,
    ) -> list[TextChunk]:
        """Group transcript segments into chunks of up to `chunk_size` characters.

        Each chunk keeps the start of its first segment and the end of its last, so a search
        hit points at a moment in the recording.
        """
        base = {
            "source": filename,
            "file_size": file_size,
            "file_type": "audio",
            **(extra_metadata or {}),
        }
        chunks: list[TextChunk] = []
        texts: list[str] = []
        start = 0.0
        end = 0.0
        length = 0

        def flush() -> None:
            chunks.append(
                TextChunk(
                    text=" ".join(texts),
                    metadata={
                        **base,
                        "start_seconds": round(start, 2),
                        "end_seconds": round(end, 2),
                        "chunk_index": len(chunks),
                    },
                )
            )

        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            if texts and length + len(text) + 1 > self.chunk_size:
                flush()
                texts, length = [], 0
            if not texts:
                start = segment.start
            texts.append(text)
            end = segment.end
            length += len(text) + 1
        if texts:
            flush()
        return self._add_context_overlap(chunks)
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_file_processor.py tests/test_board_attachments*.py -q`
Expected: PASS (the board attachment tests still use `process_file`/`process_pdf`). If no `test_board_attachments*.py` exists, run `grep -rl board_attachment_service backend/tests` and run those files instead.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/file_processor.py backend/tests/test_file_processor.py
git commit -m "refactor(rag): split PDF chunking by page and chunk OCR and transcript text"
```

### Task 3: `rag_ingest` classification and the UTF-8 rule

**Files:**
- Create: `backend/app/services/rag_ingest.py`
- Test: `backend/tests/test_rag_ingest.py`

- [ ] **Step 1: Write the failing tests**

```python
"""How an uploaded file becomes vector store chunks (rag_ingest)."""

import io
import unittest
from unittest.mock import patch

from reportlab.pdfgen import canvas

from app.services import rag_ingest
from app.services.ocr_service import OcrPage, OcrResult
from app.services.rag_ingest import RagFileKind, RagIngestError
from app.services.speech_to_text_service import SttResult, SttSegment


def _pdf(*pages: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for text in pages:
        if text:
            c.drawString(100, 750, text)
        c.showPage()
    c.save()
    return buf.getvalue()


class Utf8RuleTests(unittest.TestCase):
    def test_plain_utf8_reads_as_text(self) -> None:
        self.assertTrue(rag_ingest.reads_as_utf8_text("4 rfc ve pr\n5 açık issue\n".encode()))

    def test_empty_file_reads_as_text(self) -> None:
        self.assertTrue(rag_ingest.reads_as_utf8_text(b""))

    def test_nul_byte_is_binary(self) -> None:
        self.assertFalse(rag_ingest.reads_as_utf8_text(b"abc\x00def"))

    def test_invalid_utf8_is_binary(self) -> None:
        self.assertFalse(rag_ingest.reads_as_utf8_text(b"caf\xe9 au lait"))

    def test_character_cut_at_the_sniff_limit_still_reads_as_text(self) -> None:
        data = b"a" * (rag_ingest.SNIFF_BYTES - 1) + "ç".encode() + b"tail"

        self.assertTrue(rag_ingest.reads_as_utf8_text(data))

    def test_short_file_ending_inside_a_character_is_binary(self) -> None:
        self.assertFalse(rag_ingest.reads_as_utf8_text("aç".encode()[:-1]))


class ClassifyTests(unittest.TestCase):
    def test_known_extensions_in_any_case(self) -> None:
        cases = {
            "a.PDF": RagFileKind.PDF,
            "b.md": RagFileKind.MARKDOWN,
            "c.markdown": RagFileKind.MARKDOWN,
            "d.txt": RagFileKind.TEXT,
            "e.csv": RagFileKind.CSV,
            "f.json": RagFileKind.JSON,
            "g.JPG": RagFileKind.IMAGE,
            "h.webp": RagFileKind.IMAGE,
            "i.tiff": RagFileKind.IMAGE,
            "j.mp3": RagFileKind.AUDIO,
            "k.flac": RagFileKind.AUDIO,
            ".md": RagFileKind.MARKDOWN,
        }
        for name, kind in cases.items():
            self.assertEqual(rag_ingest.classify(name, b"\x00binary"), kind, name)

    def test_unknown_name_with_utf8_content_is_text(self) -> None:
        self.assertEqual(rag_ingest.classify("burak.akgun", b"notes"), RagFileKind.TEXT)
        self.assertEqual(rag_ingest.classify("README", b"# hi"), RagFileKind.TEXT)

    def test_unknown_binary_is_refused(self) -> None:
        self.assertIsNone(rag_ingest.classify("report.docx", b"PK\x03\x04\x00\x00"))

    def test_refusal_message_names_the_file_and_the_formats(self) -> None:
        message = rag_ingest.unsupported_message("report.docx")

        self.assertIn("report.docx", message)
        self.assertIn("audio (mp3, wav, ogg, flac)", message)
        self.assertIn("other plain-text files", message)


class PageRangeTests(unittest.TestCase):
    def test_contiguous_pages_group_and_split_at_the_limit(self) -> None:
        ranges = rag_ingest.page_ranges([1, 2, 3, 5, 7, 8], max_len=2)

        self.assertEqual(ranges, [(1, 2), (3, 3), (5, 5), (7, 8)])
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_rag_ingest.py -q`
Expected: FAIL, `ImportError: cannot import name 'rag_ingest'`.

- [ ] **Step 3: Implement** `backend/app/services/rag_ingest.py`

```python
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
AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".ogg", ".flac"})

FORMATS_SENTENCE = (
    "Vector stores take PDF, Markdown, text, CSV, JSON, images (PNG, JPEG, TIFF, WebP, BMP), "
    "audio (mp3, wav, ogg, flac) and other plain-text files."
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
    """Group sorted 1-based page numbers into contiguous ranges of at most `max_len` pages."""
    ranges: list[tuple[int, int]] = []
    for page in sorted(pages):
        if ranges and page == ranges[-1][1] + 1 and page - ranges[-1][0] < max_len:
            ranges[-1] = (ranges[-1][0], page)
        else:
            ranges.append((page, page))
    return ranges
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_rag_ingest.py -q`
Expected: PASS for `Utf8RuleTests`, `ClassifyTests`, `PageRangeTests` (the imports of `OcrPage`, `SttResult` etc. are used in Task 4).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag_ingest.py backend/tests/test_rag_ingest.py
git commit -m "feat(rag): decide how an uploaded file enters a vector store"
```

### Task 4: `rag_ingest` extraction (images, audio, PDF OCR fallback)

**Files:**
- Modify: `backend/app/services/rag_ingest.py` (append)
- Test: `backend/tests/test_rag_ingest.py` (append)

- [ ] **Step 1: Write the failing tests** (append)

```python
class QuickChunkTests(unittest.TestCase):
    def test_utf8_file_of_any_name_is_chunked_as_text(self) -> None:
        chunks = rag_ingest.quick_chunks(RagFileKind.TEXT, b"pr review notes", "burak.akgun", 15)

        self.assertEqual(chunks[0].metadata["file_type"], "text")
        self.assertEqual(chunks[0].metadata["source"], "burak.akgun")

    def test_invalid_json_is_a_user_error(self) -> None:
        with self.assertRaises(RagIngestError) as raised:
            rag_ingest.quick_chunks(RagFileKind.JSON, b"{oops", "a.json", 5)

        self.assertIn("a.json is not valid JSON", str(raised.exception))

    def test_image_is_read_by_ocr(self) -> None:
        result = OcrResult(text="Total 40 EUR", language="eng", encoding="utf-8")
        with patch("app.services.ocr_service.image_to_text", return_value=result) as ocr:
            chunks = rag_ingest.quick_chunks(RagFileKind.IMAGE, b"png", "r.png", 3)

        ocr.assert_called_once_with(b"png", filename="r.png", language="auto")
        self.assertEqual(chunks[0].metadata["file_type"], "image")
        self.assertEqual(chunks[0].metadata["ocr_language"], "eng")

    def test_image_without_text_fails(self) -> None:
        result = OcrResult(text="  ", language="eng", encoding="utf-8")
        with patch("app.services.ocr_service.image_to_text", return_value=result):
            with self.assertRaises(RagIngestError) as raised:
                rag_ingest.quick_chunks(RagFileKind.IMAGE, b"png", "blank.png", 3)

        self.assertEqual(str(raised.exception), "No text was found in blank.png.")

    def test_audio_always_goes_to_the_background(self) -> None:
        self.assertIsNone(rag_ingest.quick_chunks(RagFileKind.AUDIO, b"ogg", "a.ogg", 3))

    def test_pdf_with_text_on_every_page_is_read_now(self) -> None:
        pdf = _pdf("One", "Two")

        chunks = rag_ingest.quick_chunks(RagFileKind.PDF, pdf, "a.pdf", len(pdf))

        self.assertEqual([c.metadata["page"] for c in chunks], [1, 2])

    def test_pdf_with_a_blank_page_goes_to_the_background(self) -> None:
        pdf = _pdf("One", "")

        self.assertIsNone(rag_ingest.quick_chunks(RagFileKind.PDF, pdf, "a.pdf", len(pdf)))

    def test_unreadable_pdf_is_a_user_error(self) -> None:
        with self.assertRaises(RagIngestError) as raised:
            rag_ingest.quick_chunks(RagFileKind.PDF, b"not a pdf", "a.pdf", 9)

        self.assertEqual(str(raised.exception), "Heym could not read a.pdf as a PDF.")


class FullExtractionTests(unittest.TestCase):
    def test_audio_is_transcribed_into_timed_chunks(self) -> None:
        result = SttResult(
            text="Hello. Invoice is late.",
            language="en",
            duration_seconds=7.25,
            segments=[SttSegment(0.0, 2.0, "Hello."), SttSegment(2.0, 7.25, "Invoice is late.")],
        )
        with patch(
            "app.services.speech_to_text_service.audio_to_text", return_value=result
        ) as stt:
            chunks = rag_ingest.extract_chunks(RagFileKind.AUDIO, b"mp3", "call.mp3", 3)

        stt.assert_called_once_with(b"mp3", filename="call.mp3", language="auto")
        self.assertEqual(chunks[0].metadata["start_seconds"], 0.0)
        self.assertEqual(chunks[0].metadata["end_seconds"], 7.25)
        self.assertEqual(chunks[0].metadata["duration_seconds"], 7.25)
        self.assertEqual(chunks[0].metadata["language"], "en")

    def test_audio_without_speech_fails(self) -> None:
        result = SttResult(text="", language="en", duration_seconds=3.0)
        with patch("app.services.speech_to_text_service.audio_to_text", return_value=result):
            with self.assertRaises(RagIngestError) as raised:
                rag_ingest.extract_chunks(RagFileKind.AUDIO, b"mp3", "quiet.mp3", 3)

        self.assertEqual(str(raised.exception), "No speech was found in quiet.mp3.")

    def test_pdf_ocr_reads_only_the_blank_pages_and_keeps_their_order(self) -> None:
        pdf = _pdf("Typed first", "", "Typed third")
        ocr = OcrResult(
            text="Scanned second",
            language="eng",
            encoding="utf-8",
            pages=[OcrPage(page=2, text="Scanned second")],
        )
        with patch("app.services.ocr_service.pdf_to_text", return_value=ocr) as pdf_ocr:
            chunks = rag_ingest.extract_chunks(RagFileKind.PDF, pdf, "mixed.pdf", len(pdf))

        pdf_ocr.assert_called_once_with(pdf, language="auto", page_range="2-2")
        self.assertEqual([c.metadata["page"] for c in chunks], [1, 2, 3])
        self.assertTrue(chunks[1].metadata["ocr"])
        self.assertNotIn("ocr", chunks[0].metadata)

    def test_pdf_still_empty_after_ocr_fails(self) -> None:
        pdf = _pdf("")
        ocr = OcrResult(text="", language="eng", encoding="utf-8", pages=[OcrPage(1, "")])
        with patch("app.services.ocr_service.pdf_to_text", return_value=ocr):
            with self.assertRaises(RagIngestError) as raised:
                rag_ingest.extract_chunks(RagFileKind.PDF, pdf, "scan.pdf", len(pdf))

        self.assertEqual(
            str(raised.exception),
            "No text was found in scan.pdf, even after reading its pages as images.",
        )

    def test_too_many_scanned_pages_fail_before_any_ocr(self) -> None:
        pdf = _pdf(*([""] * (rag_ingest.MAX_RAG_OCR_PAGES + 1)))
        with patch("app.services.ocr_service.pdf_to_text") as pdf_ocr:
            with self.assertRaises(RagIngestError) as raised:
                rag_ingest.extract_chunks(RagFileKind.PDF, pdf, "big.pdf", len(pdf))

        pdf_ocr.assert_not_called()
        self.assertIn("big.pdf has 201 pages without a text layer", str(raised.exception))

    def test_documents_are_the_same_as_the_quick_path(self) -> None:
        self.assertEqual(
            rag_ingest.extract_chunks(RagFileKind.MARKDOWN, b"# Title", "a.md", 7),
            rag_ingest.quick_chunks(RagFileKind.MARKDOWN, b"# Title", "a.md", 7),
        )
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_rag_ingest.py -q`
Expected: FAIL, `AttributeError: module 'app.services.rag_ingest' has no attribute 'quick_chunks'`.

- [ ] **Step 3: Implement** (append to `rag_ingest.py`)

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_rag_ingest.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag_ingest.py backend/tests/test_rag_ingest.py
git commit -m "feat(rag): read images with OCR, audio with Whisper and scanned PDF pages with OCR"
```

### Task 5: `VectorStoreIngestJob` model and migration

**Files:**
- Modify: `backend/app/db/models.py` (after `VectorStoreTeamShare`)
- Create: `backend/alembic/versions/154_vector_store_ingest_jobs.py`
- Modify: `backend/tests/test_alembic_migrations.py`

- [ ] **Step 1: Update the migration graph test first**

In `backend/tests/test_alembic_migrations.py`, change the head assertion and add a link test:

```python
    def test_revision_graph_has_one_head(self) -> None:
        self.assertEqual(self.script.get_heads(), ["154_vector_store_ingest_jobs"])

    def test_vector_store_ingest_jobs_follows_account_security(self) -> None:
        revision = self.script.get_revision("154_vector_store_ingest_jobs")

        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "153_account_security")
```

Run: `cd backend && uv run pytest tests/test_alembic_migrations.py -q`
Expected: FAIL (head is still `153_account_security`).

- [ ] **Step 2: Add the model** (in `models.py` after `VectorStoreTeamShare`)

```python
class VectorStoreIngestJob(Base):
    """A vector store upload read in the background: audio, or a PDF with scanned pages.

    The row lives while the file is read and is deleted once its chunks are in the store. A
    failed row keeps its error until someone dismisses it. `heartbeat_at` moves every 30
    seconds while the process that runs the job is alive; see rag_ingest_jobs.py.
    """

    __tablename__ = "vector_store_ingest_jobs"
    __table_args__ = (
        Index("ix_vector_store_ingest_jobs_store_status", "vector_store_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vector_store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vector_stores.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_duplicates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 3: Add the migration** `backend/alembic/versions/154_vector_store_ingest_jobs.py`

```python
"""Vector store uploads read in the background.

Audio and PDFs with scanned pages take minutes to read, longer than an upload request should
stay open. Each such upload is a row here while it is read; the row is deleted once its chunks
are in the store, and a failed row keeps its error until it is dismissed.

Revision ID: 154_vector_store_ingest_jobs
Revises: 153_account_security
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "154_vector_store_ingest_jobs"
down_revision: str = "153_account_security"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "vector_store_ingest_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vector_store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vector_stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "override_duplicates", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_vector_store_ingest_jobs_store_status",
        "vector_store_ingest_jobs",
        ["vector_store_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vector_store_ingest_jobs_store_status", table_name="vector_store_ingest_jobs"
    )
    op.drop_table("vector_store_ingest_jobs")
```

- [ ] **Step 4: Run the graph test and apply the migration locally**

Run: `cd backend && uv run pytest tests/test_alembic_migrations.py -q`
Expected: PASS.

Apply against the local database the dev stack uses (memory: `check.sh` needs Postgres on 6543):
Run: `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: no errors; `154_vector_store_ingest_jobs` is current (`uv run alembic current`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/154_vector_store_ingest_jobs.py backend/tests/test_alembic_migrations.py
git commit -m "feat(rag): table for vector store uploads read in the background"
```

### Task 6: `rag_ingest_jobs` service

**Files:**
- Create: `backend/app/services/rag_ingest_jobs.py`
- Test: `backend/tests/test_rag_ingest_jobs.py`, `backend/tests/test_rag_ingest_jobs_postgres.py`

- [ ] **Step 1: Write the failing unit tests** `backend/tests/test_rag_ingest_jobs.py`

```python
"""Background vector store uploads: one job's run, with sessions and backends mocked."""

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from app.db.models import Credential, CredentialType, VectorStore, VectorStoreIngestJob
from app.services import rag_ingest_jobs
from app.services.file_processor import TextChunk
from app.services.rag_ingest import RagFileKind, RagIngestError


class _Sessions:
    """Stands in for async_session_maker: every `async with` yields the same mock session."""

    def __init__(self, db: AsyncMock) -> None:
        self.db = db

    def __call__(self) -> "_Sessions":
        return self

    async def __aenter__(self) -> AsyncMock:
        return self.db

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class RunJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Calls",
            collection_name="calls",
            owner_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
        )
        self.credential = Credential(
            id=self.store.credential_id,
            owner_id=self.store.owner_id,
            name="RAG",
            type=CredentialType.rag,
            encrypted_config="x",
        )
        self.job = VectorStoreIngestJob(
            id=uuid.uuid4(),
            vector_store_id=self.store.id,
            filename="call.mp3",
            file_size=3,
            kind=RagFileKind.AUDIO.value,
            status="queued",
            override_duplicates=True,
        )
        rows = {VectorStoreIngestJob: self.job, VectorStore: self.store, Credential: self.credential}
        self.db = AsyncMock()
        self.db.get = AsyncMock(side_effect=lambda model, _key: rows[model])
        self.db.add = Mock()
        self.service = Mock()
        work_dir = Path(self.tmp.name)
        for target, value in (
            ("app.services.rag_ingest_jobs.async_session_maker", _Sessions(self.db)),
            ("app.services.rag_ingest_jobs._work_dir", Mock(return_value=work_dir)),
            ("app.services.rag_ingest_jobs.decrypt_config", Mock(return_value={})),
            (
                "app.services.rag_ingest_jobs.create_vector_store_service_for_credential",
                Mock(return_value=self.service),
            ),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        rag_ingest_jobs.job_file_path(self.job.id).write_bytes(b"mp3")

    async def test_success_replaces_the_old_source_inserts_and_deletes_the_row(self) -> None:
        chunks = [TextChunk(text="Hello", metadata={"source": "call.mp3"})]
        with patch("app.services.rag_ingest.extract_chunks", return_value=chunks) as extract:
            await rag_ingest_jobs.run_job(self.job.id)

        extract.assert_called_once_with(RagFileKind.AUDIO, b"mp3", "call.mp3", 3)
        self.service.delete_by_source.assert_called_once_with("calls", "call.mp3")
        self.service.insert_batch.assert_called_once_with(
            "calls", ["Hello"], [{"source": "call.mp3"}]
        )
        self.assertEqual(self.job.status, "processing")
        deleted = self.db.execute.await_args_list[-1].args[0]
        self.assertEqual(deleted.table.name, "vector_store_ingest_jobs")
        self.assertEqual(deleted.__visit_name__, "delete")
        self.assertFalse(rag_ingest_jobs.job_file_path(self.job.id).exists())

    async def test_a_read_error_keeps_the_old_source_and_records_the_message(self) -> None:
        with (
            patch(
                "app.services.rag_ingest.extract_chunks",
                side_effect=RagIngestError("No speech was found in call.mp3."),
            ),
            patch.object(rag_ingest_jobs, "_mark_failed", new=AsyncMock()) as failed,
        ):
            await rag_ingest_jobs.run_job(self.job.id)

        failed.assert_awaited_once_with(self.job.id, "No speech was found in call.mp3.")
        self.service.delete_by_source.assert_not_called()
        self.service.insert_batch.assert_not_called()
        self.assertFalse(rag_ingest_jobs.job_file_path(self.job.id).exists())

    async def test_an_unexpected_error_records_a_generic_message(self) -> None:
        with (
            patch("app.services.rag_ingest.extract_chunks", side_effect=RuntimeError("boom")),
            patch.object(rag_ingest_jobs, "_mark_failed", new=AsyncMock()) as failed,
            self.assertLogs("app.services.rag_ingest_jobs", level="ERROR"),
        ):
            await rag_ingest_jobs.run_job(self.job.id)

        failed.assert_awaited_once_with(self.job.id, rag_ingest_jobs.GENERIC_FAILURE)

    async def test_a_job_that_is_no_longer_queued_is_left_alone(self) -> None:
        self.job.status = "failed"
        with patch("app.services.rag_ingest.extract_chunks") as extract:
            await rag_ingest_jobs.run_job(self.job.id)

        extract.assert_not_called()


class EnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_writes_the_file_commits_and_starts_the_job(self) -> None:
        db = AsyncMock()
        db.add = Mock()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("app.services.rag_ingest_jobs._work_dir", return_value=Path(tmp)),
            patch("app.services.rag_ingest_jobs.start") as start,
        ):
            job_id = await rag_ingest_jobs.enqueue(
                db,
                store_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                filename="../../etc/passwd.mp3",
                data=b"audio",
                kind=RagFileKind.AUDIO,
                override_duplicates=False,
            )
            written = Path(tmp) / str(job_id)
            self.assertEqual(written.read_bytes(), b"audio")

        job = db.add.call_args.args[0]
        self.assertEqual(job.id, job_id)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.kind, "audio")
        db.commit.assert_awaited_once()
        start.assert_called_once_with(job_id)
```

- [ ] **Step 2: Write the failing PostgreSQL tests** `backend/tests/test_rag_ingest_jobs_postgres.py`

```python
"""rag_ingest_jobs queries against real PostgreSQL: stale jobs, the in-flight check, listing."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import Credential, CredentialType, User, VectorStore, VectorStoreIngestJob
from app.services import rag_ingest_jobs


class RagIngestJobsPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1 FROM vector_store_ingest_jobs LIMIT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL with migration 154 is not reachable")
        now = datetime.now(timezone.utc)
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            self.user = User(email=f"jobs-{uuid.uuid4()}@example.com", hashed_password="x", name="J")
            db.add(self.user)
            await db.flush()
            credential = Credential(
                owner_id=self.user.id, name="RAG", type=CredentialType.rag, encrypted_config="x"
            )
            db.add(credential)
            await db.flush()
            self.store = VectorStore(
                name="Calls",
                collection_name=f"calls-{uuid.uuid4()}",
                owner_id=self.user.id,
                credential_id=credential.id,
            )
            self.other = VectorStore(
                name="Other",
                collection_name=f"other-{uuid.uuid4()}",
                owner_id=self.user.id,
                credential_id=credential.id,
            )
            db.add_all([self.store, self.other])
            await db.flush()

            def job(store: VectorStore, name: str, status: str, age: timedelta) -> VectorStoreIngestJob:
                return VectorStoreIngestJob(
                    vector_store_id=store.id,
                    filename=name,
                    file_size=1,
                    kind="audio",
                    status=status,
                    heartbeat_at=now - age,
                    created_at=now - age,
                )

            self.jobs = {
                "live": job(self.store, "live.mp3", "processing", timedelta(seconds=10)),
                "stale": job(self.store, "stale.mp3", "processing", timedelta(minutes=10)),
                "stale_queued": job(self.store, "q.mp3", "queued", timedelta(minutes=5)),
                "failed": job(self.store, "failed.mp3", "failed", timedelta(minutes=10)),
                "elsewhere": job(self.other, "stale.mp3", "processing", timedelta(minutes=10)),
            }
            db.add_all(self.jobs.values())
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(User).where(User.id == self.user.id))
            await db.commit()
        await self.engine.dispose()

    async def _status(self, key: str) -> tuple[str, str | None]:
        async with AsyncSession(self.engine) as db:
            row = await db.get(VectorStoreIngestJob, self.jobs[key].id)
            return row.status, row.error

    async def test_stale_active_jobs_of_the_store_fail(self) -> None:
        async with AsyncSession(self.engine) as db:
            await rag_ingest_jobs.fail_stale_jobs(db, self.store.id)

        self.assertEqual(await self._status("live"), ("processing", None))
        self.assertEqual(await self._status("stale"), ("failed", rag_ingest_jobs.RESTARTED_MESSAGE))
        self.assertEqual(
            await self._status("stale_queued"), ("failed", rag_ingest_jobs.RESTARTED_MESSAGE)
        )
        self.assertEqual((await self._status("elsewhere"))[0], "processing")

    async def test_only_a_live_job_blocks_the_same_name(self) -> None:
        async with AsyncSession(self.engine) as db:
            self.assertTrue(await rag_ingest_jobs.has_active_job(db, self.store.id, "live.mp3"))
            self.assertFalse(await rag_ingest_jobs.has_active_job(db, self.store.id, "stale.mp3"))
            self.assertFalse(await rag_ingest_jobs.has_active_job(db, self.store.id, "failed.mp3"))
            self.assertFalse(await rag_ingest_jobs.has_active_job(db, self.other.id, "live.mp3"))

    async def test_listing_is_newest_first_and_counts_the_store_only(self) -> None:
        async with AsyncSession(self.engine) as db:
            jobs, total = await rag_ingest_jobs.list_jobs(db, self.store.id, limit=2, offset=0)

        self.assertEqual(total, 4)
        self.assertEqual([j.filename for j in jobs], ["live.mp3", "q.mp3"])

    async def test_dismiss_removes_failed_jobs_only(self) -> None:
        async with AsyncSession(self.engine) as db:
            running = await rag_ingest_jobs.dismiss(db, self.store.id, self.jobs["live"].id)
            wrong_store = await rag_ingest_jobs.dismiss(db, self.other.id, self.jobs["failed"].id)
            done = await rag_ingest_jobs.dismiss(db, self.store.id, self.jobs["failed"].id)

        self.assertEqual((running, wrong_store, done), ("running", "missing", "deleted"))
        async with AsyncSession(self.engine) as db:
            self.assertIsNone(await db.get(VectorStoreIngestJob, self.jobs["failed"].id))

    async def test_deleting_the_store_deletes_its_jobs(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(VectorStore).where(VectorStore.id == self.store.id))
            await db.commit()
            left = await db.scalars(
                select(VectorStoreIngestJob.id).where(
                    VectorStoreIngestJob.vector_store_id == self.store.id
                )
            )
            self.assertEqual(list(left), [])
```

- [ ] **Step 3: Run both to see them fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_rag_ingest_jobs.py tests/test_rag_ingest_jobs_postgres.py -q`
Expected: FAIL, `ImportError: cannot import name 'rag_ingest_jobs'`. (Point `DATABASE_URL` at the local Postgres on 6543 so the PostgreSQL tests run rather than skip.)

- [ ] **Step 4: Implement** `backend/app/services/rag_ingest_jobs.py`

```python
"""Vector store uploads read in the background (audio, PDFs with scanned pages).

A job runs as an asyncio task in the process that accepted the upload, so the file only has to
exist on that host: it waits in `<tempdir>/heym-rag-ingest/<job id>`. Each process reads one
such file at a time, which keeps concurrent uploads from saturating the instance.

The job's row moves `heartbeat_at` every 30 seconds. A process that dies (restart, crash,
worker recycle) stops the heartbeat; the next listing of the store's jobs marks the row
failed. This needs no startup hook and no leader, and holds with several uvicorn workers per
instance and several instances.

Audit lines are written by the router when a job is queued, never from here (AGENTS.md).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Credential, VectorStore, VectorStoreIngestJob
from app.db.session import async_session_maker
from app.services import rag_ingest
from app.services.encryption import decrypt_config
from app.services.file_processor import TextChunk
from app.services.rag_ingest import RagFileKind
from app.services.vector_store import create_vector_store_service_for_credential

logger = logging.getLogger(__name__)

QUEUED = "queued"
PROCESSING = "processing"
FAILED = "failed"
ACTIVE_STATUSES = (QUEUED, PROCESSING)

HEARTBEAT_SECONDS = 30
STALE_AFTER = timedelta(minutes=3)
MAX_CONCURRENT_JOBS = 1
MAX_ERROR_CHARS = 2000

RESTARTED_MESSAGE = "Processing stopped because Heym restarted. Upload the file again."
GENERIC_FAILURE = "Heym could not read this file."
MISSING_STORE_MESSAGE = "The vector store or its credential no longer exists."

_tasks: set[asyncio.Task[None]] = set()
_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


@dataclass(frozen=True)
class _Target:
    collection: str
    credential_type: object
    config: dict


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _work_dir() -> Path:
    path = Path(tempfile.gettempdir()) / "heym-rag-ingest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_file_path(job_id: uuid.UUID) -> Path:
    """Where a job's upload waits; named by the job id, never by the uploaded name."""
    return _work_dir() / str(job_id)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        _semaphores[loop] = semaphore
    return semaphore


async def enqueue(
    db: AsyncSession,
    *,
    store_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
    kind: RagFileKind,
    override_duplicates: bool,
) -> uuid.UUID:
    """Record a background job for an upload, keep its bytes, and start it."""
    job = VectorStoreIngestJob(
        id=uuid.uuid4(),
        vector_store_id=store_id,
        created_by_id=user_id,
        filename=filename,
        file_size=len(data),
        kind=kind.value,
        status=QUEUED,
        override_duplicates=override_duplicates,
        heartbeat_at=_now(),
    )
    db.add(job)
    await db.flush()
    await asyncio.to_thread(job_file_path(job.id).write_bytes, data)
    # get_db commits after the response is sent; the job's task must see the row now.
    await db.commit()
    start(job.id)
    return job.id


def start(job_id: uuid.UUID) -> None:
    """Run a job in this process; the task is kept referenced until it ends."""
    task = asyncio.create_task(run_job(job_id), name=f"rag-ingest-{job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_job(job_id: uuid.UUID) -> None:
    """Read a queued job's file into its store and delete the row, or record why not."""
    beat = asyncio.create_task(_heartbeat(job_id))
    try:
        async with _semaphore():
            await _process(job_id)
    except Exception:  # noqa: BLE001 - a background job must never die without a trace
        logger.exception("RAG ingest job %s failed", job_id)
        await _mark_failed(job_id, GENERIC_FAILURE)
    finally:
        beat.cancel()
        job_file_path(job_id).unlink(missing_ok=True)


async def _process(job_id: uuid.UUID) -> None:
    async with async_session_maker() as db:
        job = await db.get(VectorStoreIngestJob, job_id)
        if job is None or job.status != QUEUED:
            return
        store = await db.get(VectorStore, job.vector_store_id)
        credential = await db.get(Credential, store.credential_id) if store else None
        if store is None or credential is None:
            job.status = FAILED
            job.error = MISSING_STORE_MESSAGE
            await db.commit()
            return
        job.status = PROCESSING
        await db.commit()
        target = _Target(
            collection=store.collection_name,
            credential_type=credential.type,
            config=decrypt_config(credential.encrypted_config),
        )
        filename = job.filename
        file_size = job.file_size
        kind = RagFileKind(job.kind)
        override = job.override_duplicates

    try:
        data = await asyncio.to_thread(job_file_path(job_id).read_bytes)
        chunks = await asyncio.to_thread(
            rag_ingest.extract_chunks, kind, data, filename, file_size
        )
        await asyncio.to_thread(_write_chunks, target, filename, chunks, override)
    except ValueError as exc:  # OCR, STT, "no text", backend unavailable: shown as they are
        await _mark_failed(job_id, str(exc))
        return

    async with async_session_maker() as db:
        await db.execute(delete(VectorStoreIngestJob).where(VectorStoreIngestJob.id == job_id))
        await db.commit()


def _write_chunks(
    target: _Target, filename: str, chunks: list[TextChunk], override: bool
) -> None:
    """Replace a same-named source only now, so the old one stayed searchable meanwhile."""
    service = create_vector_store_service_for_credential(target.credential_type, target.config)
    if override:
        service.delete_by_source(target.collection, filename)
    if chunks:
        service.insert_batch(
            target.collection,
            [chunk.text for chunk in chunks],
            [chunk.metadata for chunk in chunks],
        )


async def _mark_failed(job_id: uuid.UUID, message: str) -> None:
    async with async_session_maker() as db:
        await db.execute(
            update(VectorStoreIngestJob)
            .where(VectorStoreIngestJob.id == job_id)
            .values(status=FAILED, error=message[:MAX_ERROR_CHARS], updated_at=_now())
        )
        await db.commit()


async def _heartbeat(job_id: uuid.UUID) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            async with async_session_maker() as db:
                await db.execute(
                    update(VectorStoreIngestJob)
                    .where(
                        VectorStoreIngestJob.id == job_id,
                        VectorStoreIngestJob.status.in_(ACTIVE_STATUSES),
                    )
                    .values(heartbeat_at=_now())
                )
                await db.commit()
        except Exception:  # noqa: BLE001 - a missed beat must not end the job
            logger.warning("RAG ingest heartbeat for %s failed", job_id, exc_info=True)


async def has_active_job(db: AsyncSession, store_id: uuid.UUID, filename: str) -> bool:
    """Whether a live job is reading a file of this name into the store."""
    result = await db.execute(
        select(VectorStoreIngestJob.id)
        .where(
            VectorStoreIngestJob.vector_store_id == store_id,
            VectorStoreIngestJob.filename == filename,
            VectorStoreIngestJob.status.in_(ACTIVE_STATUSES),
            VectorStoreIngestJob.heartbeat_at >= _now() - STALE_AFTER,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def fail_stale_jobs(db: AsyncSession, store_id: uuid.UUID) -> None:
    """Mark the store's jobs whose process stopped beating as failed."""
    result = await db.execute(
        update(VectorStoreIngestJob)
        .where(
            VectorStoreIngestJob.vector_store_id == store_id,
            VectorStoreIngestJob.status.in_(ACTIVE_STATUSES),
            VectorStoreIngestJob.heartbeat_at < _now() - STALE_AFTER,
        )
        .values(status=FAILED, error=RESTARTED_MESSAGE, updated_at=_now())
        .returning(VectorStoreIngestJob.id)
        .execution_options(synchronize_session=False)
    )
    stale = list(result.scalars())
    if not stale:
        return
    await db.commit()
    for job_id in stale:
        job_file_path(job_id).unlink(missing_ok=True)


async def list_jobs(
    db: AsyncSession, store_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[list[VectorStoreIngestJob], int]:
    """The store's jobs, newest first, and how many there are."""
    total = await db.scalar(
        select(func.count())
        .select_from(VectorStoreIngestJob)
        .where(VectorStoreIngestJob.vector_store_id == store_id)
    )
    rows = await db.scalars(
        select(VectorStoreIngestJob)
        .where(VectorStoreIngestJob.vector_store_id == store_id)
        .order_by(VectorStoreIngestJob.created_at.desc(), VectorStoreIngestJob.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), int(total or 0)


async def dismiss(
    db: AsyncSession, store_id: uuid.UUID, job_id: uuid.UUID
) -> Literal["deleted", "missing", "running"]:
    """Remove a failed job; a running one stays."""
    job = await db.get(VectorStoreIngestJob, job_id)
    if job is None or job.vector_store_id != store_id:
        return "missing"
    if job.status != FAILED:
        return "running"
    await db.delete(job)
    await db.commit()
    return "deleted"
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes DATABASE_URL=<local 6543 URL> uv run pytest tests/test_rag_ingest_jobs.py tests/test_rag_ingest_jobs_postgres.py -q`
Expected: PASS, and the PostgreSQL tests report as run, not skipped.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/rag_ingest_jobs.py backend/tests/test_rag_ingest_jobs.py backend/tests/test_rag_ingest_jobs_postgres.py
git commit -m "feat(rag): run long vector store uploads in the background with a heartbeat"
```

### Task 7: Schemas and API

**Files:**
- Modify: `backend/app/models/schemas.py:1198` (`VectorStoreUploadResponse`), add job models after it
- Modify: `backend/app/api/vector_stores.py` (imports, `upload_file_to_vector_store`, two new routes)
- Test: `backend/tests/test_vector_store_upload_api.py`

- [ ] **Step 1: Write the failing tests** `backend/tests/test_vector_store_upload_api.py`

```python
"""The vector store upload route and its background job routes."""

import io
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, UploadFile

from app.db.models import Credential, CredentialType, VectorStore, VectorStoreIngestJob
from app.services.ocr_service import OcrResult


def _result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class UploadRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Docs",
            collection_name="docs",
            owner_id=self.user.id,
            credential_id=uuid.uuid4(),
        )
        credential = Credential(
            id=self.store.credential_id,
            owner_id=self.user.id,
            name="RAG",
            type=CredentialType.rag,
            encrypted_config="x",
        )
        self.db = AsyncMock()
        self.db.execute = AsyncMock(return_value=_result(credential))
        self.service = Mock()
        self.service.insert_batch.return_value = ["p1"]
        self.has_active = AsyncMock(return_value=False)
        self.enqueue = AsyncMock(return_value=uuid.uuid4())
        self.audit = Mock()
        for target, value in (
            ("app.api.vector_stores._get_accessible_store", AsyncMock(return_value=self.store)),
            ("app.api.vector_stores.decrypt_config", Mock(return_value={})),
            ("app.api.vector_stores.get_vector_store_service_from_config", Mock(return_value=self.service)),
            ("app.api.vector_stores.rag_ingest_jobs.has_active_job", self.has_active),
            ("app.api.vector_stores.rag_ingest_jobs.enqueue", self.enqueue),
            ("app.api.vector_stores.audit", self.audit),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _upload(self, name: str, data: bytes, override: bool = False):
        from app.api.vector_stores import upload_file_to_vector_store

        return await upload_file_to_vector_store(
            self.store.id,
            file=UploadFile(file=io.BytesIO(data), filename=name),
            override_duplicates=override,
            current_user=self.user,
            db=self.db,
        )

    async def test_utf8_file_of_any_name_is_added_now(self) -> None:
        response = await self._upload("burak.akgun", "açık issue listesi".encode())

        self.assertEqual(response.status, "done")
        self.assertEqual(response.points_inserted, 1)
        _, texts, metadata = self.service.insert_batch.call_args.args
        self.assertIn("açık issue listesi", texts[0])
        self.assertEqual(metadata[0]["file_type"], "text")

    async def test_unknown_binary_file_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await self._upload("report.docx", b"PK\x03\x04\x00\x00")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Heym cannot read report.docx", raised.exception.detail)
        self.service.insert_batch.assert_not_called()

    async def test_image_is_read_by_ocr_now(self) -> None:
        ocr = OcrResult(text="Total 40 EUR", language="eng", encoding="utf-8")
        with patch("app.services.ocr_service.image_to_text", return_value=ocr):
            response = await self._upload("receipt.jpg", b"\xff\xd8\xff\x00")

        self.assertEqual(response.status, "done")
        self.assertEqual(self.service.insert_batch.call_args.args[2][0]["file_type"], "image")

    async def test_image_without_text_is_unprocessable(self) -> None:
        ocr = OcrResult(text="", language="eng", encoding="utf-8")
        with patch("app.services.ocr_service.image_to_text", return_value=ocr):
            with self.assertRaises(HTTPException) as raised:
                await self._upload("blank.png", b"\x89PNG\x00")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail, "No text was found in blank.png.")

    async def test_audio_is_queued_and_audited(self) -> None:
        response = await self._upload("call.mp3", b"ID3\x00", override=True)

        self.assertEqual(response.status, "queued")
        self.assertEqual(response.job_id, self.enqueue.return_value)
        self.assertEqual((response.chunks_processed, response.points_inserted), (0, 0))
        kwargs = self.enqueue.await_args.kwargs
        self.assertEqual(kwargs["filename"], "call.mp3")
        self.assertTrue(kwargs["override_duplicates"])
        self.service.delete_by_source.assert_not_called()
        self.assertTrue(self.audit.call_args.kwargs["queued"])

    async def test_same_name_in_flight_conflicts(self) -> None:
        self.has_active.return_value = True

        with self.assertRaises(HTTPException) as raised:
            await self._upload("call.mp3", b"ID3\x00")

        self.assertEqual(raised.exception.status_code, 409)
        self.enqueue.assert_not_awaited()

    async def test_override_deletes_the_old_source_after_reading_the_new_one(self) -> None:
        order: list[str] = []
        self.service.delete_by_source.side_effect = lambda *_: order.append("delete")
        self.service.insert_batch.side_effect = lambda *_: order.append("insert") or ["p"]

        await self._upload("faq.md", b"# FAQ", override=True)

        self.assertEqual(order, ["delete", "insert"])
        self.service.delete_by_source.assert_called_once_with("docs", "faq.md")


class IngestJobRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Docs",
            collection_name="docs",
            owner_id=self.user.id,
            credential_id=uuid.uuid4(),
        )
        patcher = patch(
            "app.api.vector_stores._get_accessible_store", AsyncMock(return_value=self.store)
        )
        self.accessible = patcher.start()
        self.addCleanup(patcher.stop)

    async def test_listing_fails_stale_jobs_first(self) -> None:
        from app.api.vector_stores import list_ingest_jobs

        now = datetime.now(timezone.utc)
        job = VectorStoreIngestJob(
            id=uuid.uuid4(),
            vector_store_id=self.store.id,
            filename="call.mp3",
            file_size=10,
            kind="audio",
            status="processing",
            error=None,
            created_at=now,
            updated_at=now,
        )
        db = AsyncMock()
        with (
            patch("app.api.vector_stores.rag_ingest_jobs.fail_stale_jobs", new=AsyncMock()) as stale,
            patch(
                "app.api.vector_stores.rag_ingest_jobs.list_jobs",
                new=AsyncMock(return_value=([job], 1)),
            ),
        ):
            response = await list_ingest_jobs(
                self.store.id, limit=100, offset=0, current_user=self.user, db=db
            )

        stale.assert_awaited_once_with(db, self.store.id)
        self.assertEqual(response.total, 1)
        self.assertEqual(response.jobs[0].status, "processing")

    async def test_listing_needs_store_access(self) -> None:
        from app.api.vector_stores import list_ingest_jobs

        self.accessible.side_effect = HTTPException(status_code=404, detail="Vector store not found")
        with self.assertRaises(HTTPException) as raised:
            await list_ingest_jobs(
                self.store.id, limit=100, offset=0, current_user=self.user, db=AsyncMock()
            )

        self.assertEqual(raised.exception.status_code, 404)

    async def test_dismiss_maps_outcomes(self) -> None:
        from app.api.vector_stores import dismiss_ingest_job

        for outcome, code in (("missing", 404), ("running", 409)):
            with patch(
                "app.api.vector_stores.rag_ingest_jobs.dismiss",
                new=AsyncMock(return_value=outcome),
            ):
                with self.assertRaises(HTTPException) as raised:
                    await dismiss_ingest_job(
                        self.store.id, uuid.uuid4(), current_user=self.user, db=AsyncMock()
                    )
            self.assertEqual(raised.exception.status_code, code)

        with patch(
            "app.api.vector_stores.rag_ingest_jobs.dismiss", new=AsyncMock(return_value="deleted")
        ):
            self.assertIsNone(
                await dismiss_ingest_job(
                    self.store.id, uuid.uuid4(), current_user=self.user, db=AsyncMock()
                )
            )
```

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_vector_store_upload_api.py -q`
Expected: FAIL (no `rag_ingest_jobs` attribute on the router module, no `status` on the response, no job routes).

- [ ] **Step 3: Update the schemas** (`backend/app/models/schemas.py`, replace `VectorStoreUploadResponse`)

```python
class VectorStoreUploadResponse(BaseModel):
    chunks_processed: int
    points_inserted: int
    # "queued": Heym reads the file in the background (audio, scanned PDF pages); it shows
    # under GET /vector-stores/{id}/ingest-jobs until its chunks are in the store.
    status: Literal["done", "queued"] = "done"
    job_id: uuid.UUID | None = None


class VectorStoreIngestJobResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_size: int
    kind: Literal["audio", "pdf"]
    status: Literal["queued", "processing", "failed"]
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VectorStoreIngestJobsResponse(BaseModel):
    jobs: list[VectorStoreIngestJobResponse]
    total: int
```

(`schemas.py` sets `from_attributes` with an inner `class Config`, as above.)

- [ ] **Step 4: Update the router** (`backend/app/api/vector_stores.py`)

Imports: change the FastAPI import to `from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status`; add `VectorStoreIngestJobResponse` and `VectorStoreIngestJobsResponse` to the schemas import; replace `from app.services.file_processor import create_file_processor` with `from app.services import rag_ingest, rag_ingest_jobs`.

Replace the whole `upload_file_to_vector_store` function with:

```python
@router.post("/{vector_store_id}/upload", response_model=VectorStoreUploadResponse)
async def upload_file_to_vector_store(
    vector_store_id: uuid.UUID,
    file: UploadFile = File(...),
    override_duplicates: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreUploadResponse:
    """Add a file to a store.

    Documents, images and plain-text files of any name are read during the request. Audio and
    PDFs with pages that need OCR are read in the background: the response says ``queued``
    and the job is listed under ``/ingest-jobs`` until its chunks are in the store.
    """
    store = await _get_accessible_store(vector_store_id, current_user.id, db)

    filename = file.filename or "unknown.txt"
    file_content = await read_upload_file_limited(file)
    file_size = len(file_content)
    kind = rag_ingest.classify(filename, file_content)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=rag_ingest.unsupported_message(filename),
        )

    cred_result = await db.execute(select(Credential).where(Credential.id == store.credential_id))
    credential = cred_result.scalar_one_or_none()
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    if await rag_ingest_jobs.has_active_job(db, store.id, filename):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{filename} is still being processed in this store.",
        )

    try:
        chunks = await asyncio.to_thread(
            rag_ingest.quick_chunks, kind, file_content, filename, file_size
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if chunks is None:
        job_id = await rag_ingest_jobs.enqueue(
            db,
            store_id=store.id,
            user_id=current_user.id,
            filename=filename,
            data=file_content,
            kind=kind,
            override_duplicates=override_duplicates,
        )
        audit(
            action="vector_store.upload",
            actor=current_user,
            target_type="vector_store",
            target_id=store.id,
            target_name=store.name,
            file_name=filename,
            file_size=file_size,
            points_inserted=0,
            replaced_duplicates=override_duplicates,
            queued=True,
        )
        return VectorStoreUploadResponse(
            chunks_processed=0, points_inserted=0, status="queued", job_id=job_id
        )

    config = decrypt_config(credential.encrypted_config)
    service = get_vector_store_service_from_config(config, credential.type)

    if override_duplicates:
        await asyncio.to_thread(service.delete_by_source, store.collection_name, filename)

    if not chunks:
        return VectorStoreUploadResponse(chunks_processed=0, points_inserted=0)

    texts = [chunk.text for chunk in chunks]
    metadata_list = [chunk.metadata for chunk in chunks]

    try:
        point_ids = await asyncio.to_thread(
            service.insert_batch, store.collection_name, texts, metadata_list
        )
    except VectorStoreBackendUnavailableError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to insert vectors: {e!s}",
        )

    audit(
        action="vector_store.upload",
        actor=current_user,
        target_type="vector_store",
        target_id=store.id,
        target_name=store.name,
        file_name=filename,
        file_size=file_size,
        points_inserted=len(point_ids),
        replaced_duplicates=override_duplicates,
    )
    return VectorStoreUploadResponse(
        chunks_processed=len(chunks),
        points_inserted=len(point_ids),
    )


@router.get("/{vector_store_id}/ingest-jobs", response_model=VectorStoreIngestJobsResponse)
async def list_ingest_jobs(
    vector_store_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VectorStoreIngestJobsResponse:
    """Uploads of this store that Heym is reading in the background, or failed to read."""
    store = await _get_accessible_store(vector_store_id, current_user.id, db)
    await rag_ingest_jobs.fail_stale_jobs(db, store.id)
    jobs, total = await rag_ingest_jobs.list_jobs(db, store.id, limit=limit, offset=offset)
    return VectorStoreIngestJobsResponse(
        jobs=[VectorStoreIngestJobResponse.model_validate(job) for job in jobs],
        total=total,
    )


@router.delete(
    "/{vector_store_id}/ingest-jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def dismiss_ingest_job(
    vector_store_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a failed background upload from the store's list."""
    store = await _get_accessible_store(vector_store_id, current_user.id, db)
    outcome = await rag_ingest_jobs.dismiss(db, store.id, job_id)
    if outcome == "missing":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if outcome == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This file is still being processed."
        )
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_vector_store_upload_api.py tests/test_vector_store_credential_access.py tests/test_vector_store_search.py -q`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
cd backend && uv run ruff format . && uv run ruff check . && cd ..
git add backend/app/models/schemas.py backend/app/api/vector_stores.py backend/tests/test_vector_store_upload_api.py
git commit -m "feat(rag): accept images, audio and any plain-text file in vector store uploads"
```

## Part B: heymrun frontend

### Task 8: API-free file types and job polling

**Files:**
- Create: `frontend/src/types/ragIngest.ts`, `frontend/src/lib/ragFileTypes.ts`, `frontend/src/lib/ragFileTypes.test.ts`, `frontend/src/lib/ragIngestJobs.ts`, `frontend/src/lib/ragIngestJobs.test.ts`

- [ ] **Step 1: Types** `frontend/src/types/ragIngest.ts`

```ts
/** A vector store upload Heym reads in the background: audio, or a PDF with scanned pages. */
export interface RagIngestJob {
  id: string;
  filename: string;
  file_size: number;
  kind: "audio" | "pdf";
  status: "queued" | "processing" | "failed";
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RagIngestJobList {
  jobs: RagIngestJob[];
  total: number;
}
```

- [ ] **Step 2: Write the failing tests**

`frontend/src/lib/ragFileTypes.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { RAG_FORMATS_LINE, ragFileKind } from "@/lib/ragFileTypes";

function file(name: string, body: BlobPart = "x"): File {
  return new File([body], name);
}

describe("ragFileKind", () => {
  it("knows documents, images and audio by extension, in any case", async () => {
    expect(await ragFileKind(file("a.PDF", new Uint8Array([0])))).toBe("document");
    expect(await ragFileKind(file(".md"))).toBe("document");
    expect(await ragFileKind(file("scan.JPEG", new Uint8Array([0])))).toBe("image");
    expect(await ragFileKind(file("call.flac", new Uint8Array([0])))).toBe("audio");
  });

  it("takes a UTF-8 file of any name as text", async () => {
    expect(await ragFileKind(file("burak.akgun", "4 rfc ve pr\n5 açık issue\n"))).toBe("text");
    expect(await ragFileKind(file("README", "# hi"))).toBe("text");
  });

  it("refuses binary files it does not know", async () => {
    expect(await ragFileKind(file("report.docx", new Uint8Array([0x50, 0x4b, 0, 0])))).toBeNull();
  });

  it("names the formats in one line", () => {
    expect(RAG_FORMATS_LINE).toContain("audio (mp3, wav, ogg, flac)");
  });
});
```

`frontend/src/lib/ragIngestJobs.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import type { RagIngestJob } from "@/types/ragIngest";

import { useIngestJobPolling } from "@/lib/ragIngestJobs";

function job(id: string, status: RagIngestJob["status"]): RagIngestJob {
  return { id, filename: `${id}.mp3`, file_size: 1, kind: "audio", status, error: null, created_at: "", updated_at: "" };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useIngestJobPolling", () => {
  it("polls while a job runs and reports when it is gone", async () => {
    const load = vi.fn()
      .mockResolvedValueOnce([job("a", "processing")])
      .mockResolvedValueOnce([job("a", "processing")])
      .mockResolvedValueOnce([]);
    const finished = vi.fn();
    const scope = effectScope();
    const polling = scope.run(() => useIngestJobPolling(load, finished, 1000))!;

    await polling.refresh();
    expect(polling.jobs.value).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(finished).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(finished).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(load).toHaveBeenCalledTimes(3);
    scope.stop();
  });

  it("does not poll when only failed jobs are left", async () => {
    const load = vi.fn().mockResolvedValue([job("a", "failed")]);
    const scope = effectScope();
    const polling = scope.run(() => useIngestJobPolling(load, vi.fn(), 1000))!;

    await polling.refresh();
    await vi.advanceTimersByTimeAsync(5000);
    expect(load).toHaveBeenCalledTimes(1);
    scope.stop();
  });

  it("stops polling when its scope ends", async () => {
    const load = vi.fn().mockResolvedValue([job("a", "queued")]);
    const scope = effectScope();
    const polling = scope.run(() => useIngestJobPolling(load, vi.fn(), 1000))!;

    await polling.refresh();
    scope.stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(load).toHaveBeenCalledTimes(1);
  });
});
```

Run: `cd frontend && bun run test src/lib/ragFileTypes.test.ts src/lib/ragIngestJobs.test.ts`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement** `frontend/src/lib/ragFileTypes.ts`

```ts
import { readsAsUtf8Text } from "@/lib/textFileSniff";

/** How a file enters a vector store; mirrors backend/app/services/rag_ingest.py. */
export type RagFileKind = "document" | "image" | "audio" | "text";

export const RAG_DOCUMENT_EXTENSIONS: readonly string[] = [".pdf", ".md", ".markdown", ".txt", ".csv", ".json"];
export const RAG_IMAGE_EXTENSIONS: readonly string[] = [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"];
export const RAG_AUDIO_EXTENSIONS: readonly string[] = [".mp3", ".wav", ".ogg", ".flac"];

/** What a vector store takes, for upload dialogs and notices. */
export const RAG_FORMATS_LINE =
  "PDF, Markdown, text, CSV, JSON, images (PNG, JPEG, TIFF, WebP, BMP), audio (mp3, wav, ogg, flac) and any other plain-text file";

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

/** How Heym reads a file into a vector store, or null when it cannot: judged as Heym judges it. */
export async function ragFileKind(file: File): Promise<RagFileKind | null> {
  const ext = extension(file.name);
  if (RAG_DOCUMENT_EXTENSIONS.includes(ext)) return "document";
  if (RAG_IMAGE_EXTENSIONS.includes(ext)) return "image";
  if (RAG_AUDIO_EXTENSIONS.includes(ext)) return "audio";
  return (await readsAsUtf8Text(file)) ? "text" : null;
}
```

`frontend/src/lib/ragIngestJobs.ts`:

```ts
import { onScopeDispose, ref, type Ref } from "vue";

import type { RagIngestJob } from "@/types/ragIngest";

export const INGEST_POLL_MS = 4000;

export interface IngestJobPolling {
  jobs: Ref<RagIngestJob[]>;
  /** Loads the jobs now, and again every few seconds while one is queued or processing. */
  refresh: () => Promise<void>;
}

export function isActiveIngestJob(job: RagIngestJob): boolean {
  return job.status !== "failed";
}

/**
 * A store's background uploads, polled while one runs. A job that was running and is gone has
 * its chunks in the store, so `onFinished` is called to reload the documents. API-free: Heym
 * and Work pass their own `load`.
 */
export function useIngestJobPolling(
  load: () => Promise<RagIngestJob[]>,
  onFinished: () => void,
  intervalMs: number = INGEST_POLL_MS,
): IngestJobPolling {
  const jobs = ref<RagIngestJob[]>([]);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  async function refresh(): Promise<void> {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    const running = jobs.value.filter(isActiveIngestJob).map((job) => job.id);
    let next: RagIngestJob[];
    try {
      next = await load();
    } catch {
      return;
    }
    if (disposed) return;
    jobs.value = next;
    const present = new Set(next.map((job) => job.id));
    if (running.some((id) => !present.has(id))) onFinished();
    if (next.some(isActiveIngestJob)) {
      timer = setTimeout(() => void refresh(), intervalMs);
    }
  }

  onScopeDispose(() => {
    disposed = true;
    if (timer !== null) clearTimeout(timer);
  });

  return { jobs, refresh };
}
```

- [ ] **Step 4: Run the tests**

Run: `cd frontend && bun run test src/lib/ragFileTypes.test.ts src/lib/ragIngestJobs.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/ragIngest.ts frontend/src/lib/ragFileTypes.ts frontend/src/lib/ragFileTypes.test.ts frontend/src/lib/ragIngestJobs.ts frontend/src/lib/ragIngestJobs.test.ts
git commit -m "feat(rag): API-free file types and background upload polling for both apps"
```

### Task 9: API client, jobs component, panel

**Files:**
- Modify: `frontend/src/services/api.ts:2442` (response type) and the `vectorStoresApi` object (after `deleteItem`)
- Create: `frontend/src/components/VectorStores/VectorStoreIngestJobs.vue`
- Modify: `frontend/src/components/VectorStores/VectorStoresPanel.vue`

- [ ] **Step 1: API client**

Replace `VectorStoreUploadResponse` and add the import of the job types next to the other `@/types/...` imports at the top of `api.ts`:

```ts
import type { RagIngestJobList } from "@/types/ragIngest";
```

```ts
export interface VectorStoreUploadResponse {
  chunks_processed: number;
  points_inserted: number;
  /** "queued": Heym reads the file in the background; see `listIngestJobs`. */
  status?: "done" | "queued";
  job_id?: string | null;
}
```

Add to `vectorStoresApi` after `deleteItem`:

```ts
  listIngestJobs: async (id: string): Promise<RagIngestJobList> => {
    const response = await api.get<RagIngestJobList>(`/vector-stores/${id}/ingest-jobs`);
    return response.data;
  },

  dismissIngestJob: async (id: string, jobId: string): Promise<void> => {
    await api.delete(`/vector-stores/${id}/ingest-jobs/${jobId}`);
  },
```

- [ ] **Step 2: Component** `frontend/src/components/VectorStores/VectorStoreIngestJobs.vue`

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { AlertTriangle, Loader2, X } from "lucide-vue-next";

import type { RagIngestJob } from "@/types/ragIngest";

import Button from "@/components/ui/Button.vue";
import { useIngestJobPolling } from "@/lib/ragIngestJobs";
import { formatFileSize } from "@/lib/utils";
import { vectorStoresApi } from "@/services/api";

/** A store's uploads Heym is still reading in the background, or failed to read. */
const props = defineProps<{ storeId: string }>();
const emit = defineEmits<{ finished: [] }>();

const polling = useIngestJobPolling(
  async () => (await vectorStoresApi.listIngestJobs(props.storeId)).jobs,
  () => emit("finished"),
);
const { jobs } = polling;
const dismissing = ref<string | null>(null);
const dismissError = ref("");

function label(job: RagIngestJob): string {
  if (job.status === "failed") return job.error ?? "Heym could not read this file.";
  if (job.status === "queued") return "Waiting its turn";
  return job.kind === "audio" ? "Transcribing" : "Reading scanned pages";
}

async function dismiss(job: RagIngestJob): Promise<void> {
  dismissing.value = job.id;
  dismissError.value = "";
  try {
    await vectorStoresApi.dismissIngestJob(props.storeId, job.id);
    jobs.value = jobs.value.filter((item) => item.id !== job.id);
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    dismissError.value = err.response?.data?.detail || "Could not dismiss this file";
  } finally {
    dismissing.value = null;
  }
}

defineExpose({ refresh: polling.refresh });
onMounted(() => void polling.refresh());
</script>

<template>
  <div
    v-if="jobs.length > 0"
    class="space-y-1"
    data-testid="vector-store-ingest-jobs"
  >
    <div
      v-for="job in jobs"
      :key="job.id"
      class="flex items-center gap-2 rounded-lg border p-3 text-sm"
      :class="job.status === 'failed' ? 'border-destructive/40 bg-destructive/5' : 'bg-muted/30'"
    >
      <AlertTriangle
        v-if="job.status === 'failed'"
        class="h-4 w-4 flex-shrink-0 text-destructive"
      />
      <Loader2
        v-else
        class="h-4 w-4 flex-shrink-0 animate-spin text-muted-foreground"
      />
      <span class="truncate font-medium">{{ job.filename }}</span>
      <span class="flex-shrink-0 text-xs text-muted-foreground">{{ formatFileSize(job.file_size) }}</span>
      <span
        class="min-w-0 flex-1 truncate text-xs"
        :class="job.status === 'failed' ? 'text-destructive' : 'text-muted-foreground'"
        :title="label(job)"
      >{{ label(job) }}</span>
      <Button
        v-if="job.status === 'failed'"
        variant="ghost"
        size="icon"
        class="h-6 w-6 flex-shrink-0 text-muted-foreground"
        :loading="dismissing === job.id"
        title="Dismiss"
        @click="dismiss(job)"
      >
        <X class="h-3 w-3" />
      </Button>
    </div>
    <p
      v-if="dismissError"
      class="text-xs text-destructive"
    >
      {{ dismissError }}
    </p>
  </div>
</template>
```

- [ ] **Step 3: Panel wiring** (`VectorStoresPanel.vue`)

Imports: add `import VectorStoreIngestJobs from "@/components/VectorStores/VectorStoreIngestJobs.vue";` with the other component imports, and `import { RAG_FORMATS_LINE } from "@/lib/ragFileTypes";` before `@/lib/utils`.

In `submitUpload`, replace the loop and the success message:

```ts
    let totalChunks = 0;
    let totalPoints = 0;
    let queued = 0;
    uploadProgress.value = { current: 0, total: uploadFiles.value.length };

    for (let i = 0; i < uploadFiles.value.length; i++) {
      const file = uploadFiles.value[i];
      uploadProgress.value.current = i + 1;

      const result = await vectorStoresApi.uploadFile(
        uploadingStore.value.id,
        file,
        overrideDuplicates.value
      );
      if (result.status === "queued") {
        queued += 1;
      } else {
        totalChunks += result.chunks_processed;
        totalPoints += result.points_inserted;
      }
    }

    const added = uploadFiles.value.length - queued;
    const notes: string[] = [];
    if (added > 0) notes.push(`Uploaded ${added} file(s): ${totalChunks} chunks, ${totalPoints} vectors`);
    if (queued > 0) notes.push(`${queued} file(s) are being read in the background; open the store to follow them`);
    uploadSuccess.value = notes.join(". ");
```

In the upload dialog template, replace `Supported formats: PDF, Markdown, Text, CSV, JSON` with `Supported formats: {{ RAG_FORMATS_LINE }}.` and delete the line `accept=".pdf,.md,.markdown,.txt,.csv,.json"` from the file input.

In the items dialog, directly after the `<p v-if="itemsError" ...>` block, add:

```vue
        <VectorStoreIngestJobs
          v-if="itemsStore"
          :key="itemsStore.id"
          :store-id="itemsStore.id"
          @finished="loadItems"
        />
```

- [ ] **Step 4: Lint, typecheck, unit tests**

Run: `cd frontend && bun run lint && bun run typecheck && bun run test`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts frontend/src/components/VectorStores/VectorStoreIngestJobs.vue frontend/src/components/VectorStores/VectorStoresPanel.vue
git commit -m "feat(rag): show background uploads in a vector store and drop the picker filter"
```

### Task 10: Playwright coverage with a mocked store API

**Files:**
- Modify: `frontend/e2e/tab-vectors.spec.ts` (append)

- [ ] **Step 1: Write the spec** (append)

```ts
const STORE_ID = "11111111-1111-4111-8111-111111111111";
const store = {
  id: STORE_ID,
  name: "Call notes",
  description: null,
  collection_name: "call_notes",
  created_at: "2026-11-10T10:00:00Z",
  updated_at: "2026-11-10T10:00:00Z",
  is_shared: false,
  shared_by: null,
  stats: null,
  backend: "pgvector",
};

test("adds a plain-text file of any name and follows a background upload", async ({ page }) => {
  const uploads: string[] = [];
  let jobsListed = 0;
  let audioDone = false;

  await page.route("**/api/vector-stores", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [store] }) : route.fallback(),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/check-duplicates`, (route) =>
    route.fulfill({ json: { duplicates: [] } }),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/upload**`, async (route) => {
    const body = route.request().postDataBuffer()?.toString("latin1") ?? "";
    const name = /filename="([^"]+)"/.exec(body)?.[1] ?? "";
    uploads.push(name);
    const queued = name.endsWith(".mp3");
    await route.fulfill({
      json: queued
        ? { chunks_processed: 0, points_inserted: 0, status: "queued", job_id: "job-1" }
        : { chunks_processed: 1, points_inserted: 1, status: "done", job_id: null },
    });
  });
  await page.route(`**/api/vector-stores/${STORE_ID}/ingest-jobs`, (route) => {
    jobsListed += 1;
    if (jobsListed >= 2) audioDone = true;
    const jobs = audioDone
      ? []
      : [{ id: "job-1", filename: "call.mp3", file_size: 4, kind: "audio", status: "processing", error: null, created_at: "", updated_at: "" }];
    return route.fulfill({ json: { jobs, total: jobs.length } });
  });
  await page.route(`**/api/vector-stores/${STORE_ID}/items**`, (route) =>
    route.fulfill({
      json: audioDone
        ? { sources: [{ source: "call.mp3", file_size: 4, chunk_count: 2, items: [] }], total_items: 2 }
        : { sources: [], total_items: 0 },
    }),
  );

  await page.goto("/?tab=vectorstores");
  await page.getByTitle("Upload files").click();
  await expect(page.getByText(/audio \(mp3, wav, ogg, flac\)/)).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles([
    { name: "burak.akgun", mimeType: "", buffer: Buffer.from("4 rfc ve pr\n") },
    { name: "call.mp3", mimeType: "audio/mpeg", buffer: Buffer.from("ID3\u0000") },
  ]);
  await page.getByRole("button", { name: "Upload (2)" }).click();

  await expect(page.getByText(/1 file\(s\) are being read in the background/)).toBeVisible();
  expect(uploads).toEqual(["burak.akgun", "call.mp3"]);

  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.getByText("Call notes").click();
  // The first jobs listing says the audio is processing; the next one (4 s later) is empty,
  // which reloads the items and shows the new source.
  await expect(page.getByTestId("vector-store-ingest-jobs")).toContainText("Transcribing");
  await expect(page.getByText("(2 chunks)")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("vector-store-ingest-jobs")).toBeHidden();
});

test("dismisses a background upload that failed", async ({ page }) => {
  let dismissed = false;
  await page.route("**/api/vector-stores", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [store] }) : route.fallback(),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/items**`, (route) =>
    route.fulfill({ json: { sources: [], total_items: 0 } }),
  );
  await page.route(`**/api/vector-stores/${STORE_ID}/ingest-jobs/job-2`, (route) => {
    dismissed = true;
    return route.fulfill({ status: 204 });
  });
  await page.route(`**/api/vector-stores/${STORE_ID}/ingest-jobs`, (route) =>
    route.fulfill({
      json: {
        jobs: [{ id: "job-2", filename: "quiet.mp3", file_size: 4, kind: "audio", status: "failed", error: "No speech was found in quiet.mp3.", created_at: "", updated_at: "" }],
        total: 1,
      },
    }),
  );

  await page.goto("/?tab=vectorstores");
  await page.getByText("Call notes").click();
  const jobs = page.getByTestId("vector-store-ingest-jobs");
  await expect(jobs).toContainText("No speech was found in quiet.mp3.");
  await jobs.getByTitle("Dismiss").click();
  await expect(jobs).toBeHidden();
  expect(dismissed).toBe(true);
});
```

The labels come from `VectorStoresPanel.vue`: the submit button reads `Upload (n)` while files are selected, the dialog's other button is `Close`, the card's upload button has `title="Upload files"`, and clicking a store card opens its items dialog.

- [ ] **Step 2: Run it**

Run: `./run_e2e.sh e2e/tab-vectors.spec.ts` (the script passes its arguments to `bun run test:e2e` inside `frontend/`)
Expected: the four vector store specs pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/tab-vectors.spec.ts
git commit -m "test(e2e): vector store upload of any-name text and a background upload"
```

### Task 11: Docs and release tour

**Files:**
- Modify: `frontend/src/docs/content/tabs/vectorstores-tab.md`, `frontend/src/docs/content/nodes/rag-node.md`, `frontend/src/docs/content/reference/features.md:814`
- Create: `frontend/src/features/release-tour/components/visuals/RagMediaUploadTourVisual.vue`
- Modify: `frontend/src/features/release-tour/tourVisuals.ts`, `frontend/src/features/release-tour/releaseRegistry.ts`

Use the `heym-documentation` skill if it is available (AGENTS.md).

- [ ] **Step 1: `vectorstores-tab.md`** — replace the "Uploading Documents" section:

```markdown
## Uploading Documents

- **Upload files** – Drag and drop or pick several files. A store takes:
  - **Documents** – PDF, Markdown, text, CSV and JSON
  - **Images** – PNG, JPEG, TIFF, WebP and BMP, read with the same Tesseract OCR as the
    [Converter](../nodes/converter-node.md) node, language detected automatically
  - **Audio** – mp3, wav, ogg and flac, transcribed with the Converter's Whisper model on your
    own instance; each chunk keeps where it starts and ends in the recording
    (`start_seconds`, `end_seconds`)
  - **Any other plain-text file** – a file such as `notes` or `burak.akgun` is read as text when
    it is valid UTF-8
- **Scanned PDFs** – pages without a text layer are read with OCR, up to 200 such pages per file
- **Background uploads** – audio and PDFs with scanned pages take minutes, so Heym reads them in
  the background. They show at the top of the store's items as *Transcribing* or *Reading scanned
  pages* and turn into a normal source when their chunks are in. A failed one shows why and can
  be dismissed. With **Override existing files**, the old version stays searchable until the new
  one is ready
- **Duplicate handling** – Choose to override or skip duplicate filenames
- **Progress** – Upload progress is shown during ingestion

An image without readable text, an audio file without speech, and a binary file of another type
are refused with a message.
```

- [ ] **Step 2: `rag-node.md`** — after the Insert table's `**Output:**` line add:

```markdown
To store an image's text or a recording's transcript from a workflow, put a
[Converter](./converter-node.md) node (`imageToText`, `pdfToText` or `audioToText`) before the
insert and pass `$converterNode.result` as `documentContent`. Files uploaded in the
[Vectorstores](../tabs/vectorstores-tab.md) tab go through the same readers on their own.
```

- [ ] **Step 3: `features.md`** — in the Vectorstores paragraph replace `then upload documents (PDF, TXT, etc.)` with `then upload documents (PDF, Markdown, text, CSV, JSON, images read with OCR, mp3/wav/ogg/flac audio transcribed on the instance, and any other UTF-8 text file; audio and scanned PDFs are read in the background)`.

- [ ] **Step 4: Tour visual** `RagMediaUploadTourVisual.vue` (mock UI, `useCycleStep`, semantic tokens)

```vue
<script setup lang="ts">
import { computed } from "vue";
import { AudioLines, Database, FileText, Image, Loader2 } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// Mock UI only. 0: files dropped · 1: the image is read, audio transcribes · 2: all are sources.
const step = useCycleStep(3, 2400);

const files = [
  { name: "receipt.jpg", icon: Image, quick: true },
  { name: "burak.akgun", icon: FileText, quick: true },
  { name: "support-call.mp3", icon: AudioLines, quick: false },
];

const caption = computed<string>(
  () =>
    [
      "Drop photos, recordings and text files on a store",
      "Images are read now, audio transcribes in the background",
      "Every file is a searchable source for RAG",
    ][step.value],
);

function state(quick: boolean): "waiting" | "working" | "done" {
  if (step.value === 0) return "waiting";
  if (step.value === 1) return quick ? "done" : "working";
  return "done";
}
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2.5 rounded-lg bg-card p-3.5">
    <div class="flex items-center gap-2 text-[11px] leading-4 text-muted-foreground">
      <Database class="h-3 w-3" />
      Vector store · Call notes
    </div>
    <div class="flex min-h-0 flex-1 flex-col gap-1.5">
      <div
        v-for="file in files"
        :key="file.name"
        class="flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[11px] leading-4 transition-colors duration-500"
        :class="state(file.quick) === 'done' ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-border bg-background'"
      >
        <component
          :is="file.icon"
          class="h-3.5 w-3.5 shrink-0 text-primary"
        />
        <span class="truncate text-foreground">{{ file.name }}</span>
        <span class="ml-auto flex shrink-0 items-center gap-1 text-[10px] text-muted-foreground">
          <Loader2
            v-if="state(file.quick) === 'working'"
            class="h-3 w-3 animate-spin"
          />
          {{ state(file.quick) === "done" ? "Added" : state(file.quick) === "working" ? "Transcribing" : "Dropped" }}
        </span>
      </div>
    </div>
    <p class="shrink-0 text-[10px] leading-4 text-muted-foreground">
      {{ caption }}
    </p>
  </div>
</template>
```

Register it in `tourVisuals.ts`: add the import next to the others and `"rag-media-upload": RagMediaUploadTourVisual,` in `TOUR_VISUALS`.

- [ ] **Step 5: Release registry** — since #886 every feature gets its own release entry (2026.28 voice, 2026.29 reranker). Add a new first entry `2026.30` (`publishedAt` after 2026.29's `2026-11-10T16:00:00Z`, `tourEnabled: true` as the neighbouring entries ship, `sectionOrder: ["rag-media-upload"]`, headline "Images, audio and any text file in vector stores", introDescription "Photos, recordings and scanned pages become searchable RAG sources.") holding the section below. The registry keeps five sections: also delete the `2026.25` entry (`board-task-fields`), `components/visuals/BoardTaskFieldsTourVisual.vue` and its `tourVisuals.ts` registration, and in `releaseTourMapper.test.ts` ("shipped release registry") change the expected slide ids to `["rag-media-upload", "decision-reranker", "voice-transcribe", "account-security", "google-meet"]`.

```ts
    {
      id: "rag-media-upload", title: "Images, audio and any text file in vector stores",
      publishedAt: new Date("2026-11-10T22:00:00Z"),
      blocks: [{ type: "prose", markdown: "Drop a photo, a screenshot, a voice note or a call recording on a vector store and it becomes searchable. Images are read with the Converter's OCR, and audio is transcribed on your own instance with the same Whisper model, in the background, so a long recording does not hold the upload open. PDF pages without a text layer are now read with OCR instead of being skipped, and a plain-text file of any name, such as `notes` or `burak.akgun`, goes in as text. Heym Work's Knowledge pages take the same files." }],
      tour: {
        description: "Put photos, recordings, scanned PDFs and plain-text files of any name into a vector store.",
        useCases: ["Search call recordings from a RAG node", "Make photographed receipts and whiteboards searchable", "Index scanned contracts without a separate OCR step"],
        tourVisual: "rag-media-upload",
        docTarget: { categoryId: "tabs", slug: "vectorstores-tab", title: "Vectorstores" },
      },
    },
```

- [ ] **Step 6: Run the tour tests, lint, typecheck**

Run: `cd frontend && bun run test src/features/release-tour && bun run lint && bun run typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/docs frontend/src/features/release-tour
git commit -m "docs(rag): media and any-name text uploads, with a release tour section"
```

### Task 12: Full check and PR

- [ ] **Step 1: Run the full check against PostgreSQL**

Run (from the repo root, with the throwaway Postgres on 6543 per memory): `SECRET_KEY=test-secret-key-for-tests-only-32-bytes DATABASE_URL=<6543 URL> ./check.sh`
Expected: frontend lint/typecheck, Ruff, and all backend tests pass. Commit any `ruff format` diff.

- [ ] **Step 2: Vitest** (not part of `check.sh`)

Run: `cd frontend && bun run test`
Expected: PASS.

- [ ] **Step 3: Real-file smoke test** (OCR binaries and the Whisper model are needed; `run.sh` downloads the model)

With the dev stack running and a Postgres-backed store: upload a PNG screenshot, a short mp3 voice note, a PDF with one scanned page, and a file named `burak.akgun`. Confirm the image and text file appear at once, the audio and PDF show as background rows, and both turn into sources with `start_seconds` / `ocr: true` in their chunk metadata.

- [ ] **Step 4: Push and open the PR**

Ask the user about attribution first (memory: the public heym repo has had no-attribution PRs; ask if unsaid). Then:

```bash
git push -u origin feat/rag-media-upload
gh pr create --title "Images, audio and any plain-text file in vector store uploads" --body "<summary, test plan, the E2E-mocking note, the smoke test result>"
```

## Part C: heym-work

Work changes wait until the Heym PR is merged, so the vendor pin can point at the merge commit. Work works on `main` locally; push only when the user says.

### Task 13: Proxy routes and upload schema

**Files:**
- Modify: `backend/heym_work/api/heym_routes.py` (RAG block), `backend/heym_work/api/schemas.py:852`
- Test: `backend/tests/test_heym_routes.py`, `backend/tests/test_data_files.py:31-48`

- [ ] **Step 1: Failing tests**

Append to `RouteMatchTests` in `test_heym_routes.py`:

```python
    def test_background_uploads_are_read_by_viewers_and_dismissed_by_editors(self) -> None:
        store = uuid.uuid4()
        listed = find_route("GET", f"/vector-stores/{store}/ingest-jobs")
        dismissed = find_route("DELETE", f"/vector-stores/{store}/ingest-jobs/{uuid.uuid4()}")

        self.assertIsNotNone(listed)
        self.assertEqual(listed.minimum, Role.VIEWER)
        self.assertIsNotNone(dismissed)
        self.assertEqual(dismissed.minimum, Role.EDITOR)
```

In `test_data_files.py`, change the expected JSON of `test_an_editor_uploads_to_a_store_and_may_replace_a_source` to `{"chunks_processed": 3, "points_inserted": 3, "status": "done", "job_id": None}` and add:

```python
    def test_a_queued_upload_passes_its_job_through(self) -> None:
        self.set_role("vera@test.example", "editor")
        job_id = str(uuid.uuid4())
        self.fake.answer(
            "POST",
            f"/api/vector-stores/{STORE}/upload",
            {"chunks_processed": 0, "points_inserted": 0, "status": "queued", "job_id": job_id},
        )

        response = self.vera.post(
            f"/api/data/vector-stores/{STORE}/upload",
            files={"file": ("call.mp3", b"ID3", "audio/mpeg")},
            headers=ORIGIN,
        )

        self.assertEqual(response.json()["status"], "queued")
        self.assertEqual(response.json()["job_id"], job_id)
```

(Add `import uuid` to `test_data_files.py` if it is not there.)

Run: `cd backend && uv run pytest tests/test_heym_routes.py tests/test_data_files.py -q`
Expected: FAIL.

- [ ] **Step 2: Implement**

In `heym_routes.py`, after `HeymRoute("POST", "/vector-stores/{vector_store_id}/search", Role.VIEWER),` add:

```python
    # Uploads Heym reads in the background (audio, scanned PDF pages); an Editor dismisses a
    # failed one.
    HeymRoute("GET", "/vector-stores/{vector_store_id}/ingest-jobs", Role.VIEWER),
    HeymRoute("DELETE", "/vector-stores/{vector_store_id}/ingest-jobs/{job_id}", Role.EDITOR),
```

In `schemas.py`:

```python
class VectorStoreUploadView(BaseModel):
    chunks_processed: int
    points_inserted: int
    # An older Heym omits both; its uploads are always read during the request.
    status: Literal["done", "queued"] = "done"
    job_id: str | None = None
```

(Import `Literal` from `typing` if `schemas.py` does not yet.)

Run: `cd backend && uv run pytest tests/test_heym_routes.py tests/test_data_files.py -q`
Expected: PASS.

- [ ] **Step 3: Commit** (in heym-work)

```bash
git add backend/heym_work/api/heym_routes.py backend/heym_work/api/schemas.py backend/tests/test_heym_routes.py backend/tests/test_data_files.py
git commit -m "Knowledge: pass Heym's background uploads through"
```

### Task 14: Pin Heym and update the upload plan

**Files:**
- Modify: `vendor/heymrun` (submodule), `frontend/src/lib/ragUpload.ts`, `frontend/src/lib/ragUpload.test.ts`

- [ ] **Step 1: Pin the submodule to the Heym merge commit**

```bash
cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym-work
git -C vendor/heymrun fetch origin && git -C vendor/heymrun checkout <heym merge commit>
test -f vendor/heymrun/frontend/src/lib/ragFileTypes.ts && echo ok
```

Expected: `ok`.

- [ ] **Step 2: Failing tests** — replace `frontend/src/lib/ragUpload.test.ts` with:

```ts
import { describe, expect, it } from "vitest";

import { fileNames, planStoreUpload } from "@/lib/ragUpload";

function file(name: string, body: BlobPart = "x"): File {
  return new File([body], name);
}

const BINARY = new Uint8Array([0x50, 0x4b, 0, 0]);

describe("ragUpload", () => {
  it("splits files into new, same-named and refused", async () => {
    const plan = await planStoreUpload(
      [file("new.pdf"), file("faq.md"), file("photo.png", BINARY), file("call.mp3", BINARY), file("report.docx", BINARY)],
      ["faq.md", "other.txt"],
    );

    expect(plan.fresh.map((f) => f.name)).toEqual(["new.pdf", "photo.png", "call.mp3"]);
    expect(plan.duplicates.map((f) => f.name)).toEqual(["faq.md"]);
    expect(plan.rejected.map((f) => f.name)).toEqual(["report.docx"]);
  });

  it("takes a UTF-8 file of any name", async () => {
    const plan = await planStoreUpload([file("burak.akgun", "4 rfc ve pr\n")], []);

    expect(plan.fresh.map((f) => f.name)).toEqual(["burak.akgun"]);
  });

  it("keeps the last of two picked files with one name", async () => {
    const plan = await planStoreUpload([file("faq.md", "old"), file("faq.md", "newer")], []);

    expect(plan.fresh).toHaveLength(1);
    expect(plan.fresh[0].size).toBe(5);
  });

  it("names up to three files, then counts the rest", () => {
    expect(fileNames([file("a.md")])).toBe('"a.md"');
    expect(fileNames(["a", "b", "c", "d", "e"].map((name) => file(`${name}.md`)))).toBe('"a.md", "b.md", "c.md" and 2 more');
  });
});
```

Run: `cd frontend && bun run test src/lib/ragUpload.test.ts`
Expected: FAIL (`planStoreUpload` is synchronous and refuses `photo.png`).

- [ ] **Step 3: Implement** — replace `frontend/src/lib/ragUpload.ts` above `fileNames` with:

```ts
import { ragFileKind } from "@heym/lib/ragFileTypes";

/** What happens to each picked or dropped file before anything is sent. */
export interface StoreUploadPlan {
  /** Files the store does not have yet. */
  fresh: File[];
  /** Files named like a document the store already has. */
  duplicates: File[];
  /** Files Heym would refuse for their type. */
  rejected: File[];
}

/** Sorts files for a store that already holds documents named `existing`, judged as Heym judges them. */
export async function planStoreUpload(files: readonly File[], existing: readonly string[]): Promise<StoreUploadPlan> {
  const kinds = await Promise.all(files.map((file) => ragFileKind(file)));
  const rejected = files.filter((_file, index) => kinds[index] === null);
  // Two files with one name would become one source in Heym; the last one picked is kept.
  const byName = new Map(files.filter((_file, index) => kinds[index] !== null).map((file) => [file.name, file]));
  const known = new Set(existing);
  const accepted = [...byName.values()];
  return {
    fresh: accepted.filter((file) => !known.has(file.name)),
    duplicates: accepted.filter((file) => known.has(file.name)),
    rejected,
  };
}
```

(`RAG_ACCEPT` and `isRagDocument` go away; `grep -rn "RAG_ACCEPT\|isRagDocument" frontend/src` must come back empty after Task 15.)

- [ ] **Step 4: Run** `cd frontend && bun run test src/lib/ragUpload.test.ts src/heym`
Expected: PASS, including Work's `heymImports.test.ts` (nothing Work imports may reach Heym's services, and Work's `src` must not shadow `@/lib/textFileSniff` or `@/types/ragIngest`).

- [ ] **Step 5: Commit**

```bash
git add vendor/heymrun frontend/src/lib/ragUpload.ts frontend/src/lib/ragUpload.test.ts
git commit -m "Pin Heym to <short sha>: images, audio and any text file in vector stores"
```

### Task 15: Queued notice, jobs list, picker

**Files:**
- Modify: `frontend/src/types/api.ts:542`, `frontend/src/services/heymApi.ts` (`heymRag`), `frontend/src/composables/useStoreUpload.ts`, `frontend/src/composables/useStoreUpload.test.ts`, `frontend/src/components/rag/RagDocuments.vue`
- Create: `frontend/src/components/rag/RagIngestJobs.vue`

- [ ] **Step 1: Failing tests** — in `useStoreUpload.test.ts`:

1. In the first test, `file("c.png")` is now accepted. Change that test's files to `[file("a.md"), file("b.pdf"), new File([new Uint8Array([0x50, 0x4b, 0, 0])], "c.docx")]` and the refusal expectation to `expect.stringContaining('"c.docx" cannot be added')`.
2. Add:

```ts
  it("reports an upload Heym reads in the background", async () => {
    vi.mocked(uploadToStore).mockResolvedValue({ chunks_processed: 0, points_inserted: 0, status: "queued", job_id: "job-1" });
    const onAdded = vi.fn();
    const upload = useStoreUpload(onAdded);

    await upload.add("store-1", [file("call.mp3")], []);

    expect(showToast).toHaveBeenLastCalledWith("call.mp3 is being read in the background. It appears in the store when it is ready.", "success", 4000);
    expect(onAdded).toHaveBeenCalledTimes(1);
  });
```

Run: `cd frontend && bun run test src/composables/useStoreUpload.test.ts`
Expected: FAIL on the new test (and type errors on `status`).

- [ ] **Step 2: Types and API** — `frontend/src/types/api.ts`:

```ts
export interface StoreUploadResult {
  chunks_processed: number;
  points_inserted: number;
  /** "queued": Heym reads the file in the background (audio, scanned PDF pages). */
  status?: "done" | "queued";
  job_id?: string | null;
}
```

`heymApi.ts`, in `heymRag` after `removeChunk` (add `import type { RagIngestJob, RagIngestJobList } from "@heym/types/ragIngest";` to the type imports, and `isAxiosError` from `axios` if the file does not import it yet):

```ts
  /** Uploads Heym is reading in the background; a Heym without the route has none. */
  async ingestJobs(storeId: string): Promise<RagIngestJob[]> {
    try {
      return (await api.get<RagIngestJobList>(heym(`/vector-stores/${storeId}/ingest-jobs`))).data.jobs;
    } catch (err: unknown) {
      if (isAxiosError(err) && err.response?.status === 404) return [];
      throw err;
    }
  },
  async dismissIngestJob(storeId: string, jobId: string): Promise<void> {
    await api.delete(heym(`/vector-stores/${storeId}/ingest-jobs/${jobId}`));
  },
```

Note: a 404 also means "store not found"; for a store the user just opened that cannot happen without the store page failing first, so treating it as "no jobs" is safe.

- [ ] **Step 3: `useStoreUpload.ts`** — import the format line and handle queued uploads:

Add `import { RAG_FORMATS_LINE } from "@heym/lib/ragFileTypes";` to the imports. In `send`, track queued files:

```ts
    const added: File[] = [];
    const queued: File[] = [];
    const failed: { file: File; message: string }[] = [];
    let chunks = 0;
    for (const [index, { file, replace }] of uploads.entries()) {
      try {
        const result = await uploadToStore(storeId, file, replace);
        if (result.status === "queued") queued.push(file);
        else {
          chunks += result.points_inserted;
          added.push(file);
        }
      } catch (err: unknown) {
        failed.push({ file, message: apiErrorMessage(err, "Heym could not read it.") });
      }
      progress.value = { storeId, done: index + 1, total: uploads.length };
    }
    progress.value = null;
    const notice: string[] = [];
    if (added.length === 1) notice.push(`Added ${added[0].name} in ${chunks} chunks.`);
    else if (added.length > 1) notice.push(`Added ${added.length} documents in ${chunks} chunks.`);
    if (queued.length === 1) notice.push(`${queued[0].name} is being read in the background. It appears in the store when it is ready.`);
    else if (queued.length > 1) notice.push(`${fileNames(queued)} are being read in the background. They appear in the store when they are ready.`);
    if (failed.length === 1) notice.push(`${failed[0].file.name} could not be added: ${failed[0].message}`);
    else if (failed.length > 1) notice.push(`${fileNames(failed.map((item) => item.file))} could not be added.`);
    showToast(notice.join(" "), failed.length > 0 ? "error" : "success", failed.length > 0 ? 8000 : 4000);
    if (added.length > 0 || queued.length > 0) await onAdded(storeId);
```

In `add`, `const plan = await planStoreUpload(files, names);` and the refusal text becomes:

```ts
      showToast(`${fileNames(plan.rejected)} cannot be added. Knowledge reads ${RAG_FORMATS_LINE}.`, "error", 6000);
```

- [ ] **Step 4: `RagIngestJobs.vue`** (Work styling)

```vue
<script setup lang="ts">
import { onMounted, ref } from "vue";
import { AlertTriangle, Loader2, X } from "lucide-vue-next";

import type { RagIngestJob } from "@heym/types/ragIngest";

import { useIngestJobPolling } from "@heym/lib/ragIngestJobs";
import { apiErrorMessage } from "@/lib/api";
import { formatSize } from "@/lib/drive";
import { heymRag } from "@/services/heymApi";

/** A store's uploads Heym is still reading in the background, or failed to read. */
const props = defineProps<{ storeId: string; canDismiss: boolean }>();
const emit = defineEmits<{ finished: [] }>();

const polling = useIngestJobPolling(() => heymRag.ingestJobs(props.storeId), () => emit("finished"));
const { jobs } = polling;
const error = ref<string | null>(null);

function label(job: RagIngestJob): string {
  if (job.status === "failed") return job.error ?? "Heym could not read this file.";
  if (job.status === "queued") return "Waiting its turn";
  return job.kind === "audio" ? "Transcribing" : "Reading scanned pages";
}

async function dismiss(job: RagIngestJob): Promise<void> {
  error.value = null;
  try {
    await heymRag.dismissIngestJob(props.storeId, job.id);
    jobs.value = jobs.value.filter((item) => item.id !== job.id);
  } catch (err: unknown) {
    error.value = apiErrorMessage(err, "It could not be dismissed.");
  }
}

defineExpose({ refresh: polling.refresh });
onMounted(() => void polling.refresh());
</script>

<template>
  <ul
    v-if="jobs.length > 0"
    class="mt-3 space-y-1"
    aria-label="Files being read"
  >
    <li
      v-for="job in jobs"
      :key="job.id"
      class="flex items-center gap-2 rounded-card border px-3 py-2 text-sm"
      :class="job.status === 'failed' ? 'border-destructive/40 bg-destructive/5' : 'border-border bg-card'"
    >
      <AlertTriangle
        v-if="job.status === 'failed'"
        class="h-4 w-4 shrink-0 text-destructive"
      />
      <Loader2
        v-else
        class="h-4 w-4 shrink-0 animate-spin text-muted-foreground"
      />
      <span class="truncate font-medium">{{ job.filename }}</span>
      <span class="shrink-0 text-xs tabular-nums text-muted-foreground">{{ formatSize(job.file_size) }}</span>
      <span
        class="min-w-0 flex-1 truncate text-xs"
        :class="job.status === 'failed' ? 'text-destructive' : 'text-muted-foreground'"
        :title="label(job)"
      >{{ label(job) }}</span>
      <button
        v-if="job.status === 'failed' && canDismiss"
        type="button"
        class="rounded p-1 text-muted-foreground hover:bg-muted"
        :aria-label="`Dismiss ${job.filename}`"
        @click="dismiss(job)"
      >
        <X class="h-3.5 w-3.5" />
      </button>
    </li>
    <li
      v-if="error"
      role="alert"
      class="text-xs text-destructive"
    >
      {{ error }}
    </li>
  </ul>
</template>
```

- [ ] **Step 5: `RagDocuments.vue`**

- Imports: drop `RAG_ACCEPT`; add `import RagIngestJobs from "@/components/rag/RagIngestJobs.vue";` and `import { RAG_FORMATS_LINE } from "@heym/lib/ragFileTypes";`.
- Add `const jobsList = ref<InstanceType<typeof RagIngestJobs> | null>(null);` and make the upload callback refresh the jobs too: `const uploads = useStoreUpload(async () => { await load(); await jobsList.value?.refresh(); });`
- Template: replace the hint `PDF, Markdown, text, CSV or JSON. Drop files here, or add several at once.` with `{{ RAG_FORMATS_LINE }}. Drop files here, or add several at once.`; delete `:accept="RAG_ACCEPT"`; after the `<p v-if="error" ...>` block insert:

```vue
    <RagIngestJobs
      ref="jobsList"
      :store-id="storeId"
      :can-dismiss="canUpload"
      @finished="load"
    />
```

- [ ] **Step 6: Checks**

Run: `cd frontend && bun run test && bun run lint && bun run typecheck`, then `./check.sh` from the Work root.
Expected: all pass; `grep -rn "RAG_ACCEPT\|isRagDocument" frontend/src` is empty.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "Knowledge takes images, audio and any plain-text file, and shows files Heym reads in the background"
```

- [ ] **Step 8: Docs sync and hand-off**

Run `bun run sync-docs` after the Heym docs are on `main` and commit the snapshot if it changed (AGENTS: never edit the snapshot by hand). Tell the user the Work commits are local and unpushed; release notes go in the annotated tag of the release that carries the pin.
