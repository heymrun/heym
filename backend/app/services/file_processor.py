import csv
import io
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass
class TextChunk:
    text: str
    metadata: dict


class TimedSegment(Protocol):
    """A stretch of transcribed speech; `speech_to_text_service.SttSegment` is one."""

    start: float
    end: float
    text: str


DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 200


class FileProcessor:
    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def _clean_pdf_text(self, text: str) -> str:
        """
        Clean PDF text by removing character duplication patterns and spacing issues.
        Fixes:
        - "m m m i i ss ss i i oo nn" -> "mission"
        - "J o i n t" -> "Joint"
        - "m mo ov ve em me en nt t" -> "movement"
        """
        if not text:
            return text

        # Keep words hyphenated across a line break ("self-\nservice") intact;
        # split() below would otherwise leave "self- service".
        text = re.sub(r"(\w)-[ \t]*\r?\n[ \t]*(\w)", r"\1-\2", text)

        parts = text.split()
        if not parts:
            return text

        result = []
        i = 0
        while i < len(parts):
            part = parts[i]

            if len(part) == 1:
                j = i + 1
                count = 1
                while j < len(parts) and parts[j] == part:
                    count += 1
                    j += 1
                # An even run of the same LETTER is the same shape a single
                # faux-bold-struck letter produces (each real occurrence struck
                # exactly twice), just scaled up for a genuine doubled letter -
                # halve, don't collapse to one. Scoped to letters only: digits
                # and punctuation runs (spaced tables, dashed rules, bullet
                # rows) keep today's collapse-to-one behavior unchanged.
                repeat = count // 2 if part.isalpha() and count % 2 == 0 else 1
                for _ in range(repeat):
                    result.append(part)
                i = j
            elif len(part) == 2 and part[0] == part[1]:
                j = i + 1
                count = 1
                while j < len(parts) and parts[j] == part:
                    count += 1
                    j += 1
                for _ in range(count):
                    result.append(part[0])
                i = j
            else:
                result.append(part)
                i += 1

        cleaned = " ".join(result)

        while True:
            new_cleaned = re.sub(r"(?<!\S)([a-zA-Z])\s+\1(\s|$)", r"\1\1\2", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        cleaned = re.sub(r"(?<!\S)([a-zA-Z]{2})\s+\1(\s|$)", r"\1\2", cleaned)

        cleaned_parts = cleaned.split()
        final_parts = []
        i = 0
        while i < len(cleaned_parts):
            part = cleaned_parts[i]
            if len(part) == 1 and part.isalpha():
                word_chars = [part]
                paired = False
                j = i + 1
                while j < len(cleaned_parts):
                    next_part = cleaned_parts[j]
                    if len(next_part) == 1 and next_part.isalpha():
                        if paired and next_part == word_chars[-1][-1]:
                            j += 1
                            break
                        word_chars.append(next_part)
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == next_part[1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part)
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == word_chars[-1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part[1])
                        paired = True
                        j += 1
                    else:
                        break
                if len(word_chars) >= 2:
                    final_parts.append("".join(word_chars))
                    i = j
                    continue
            elif len(part) == 2 and part[0] == part[1] and part[0].isalpha():
                word_chars = [part]
                paired = False
                j = i + 1
                while j < len(cleaned_parts):
                    next_part = cleaned_parts[j]
                    if len(next_part) == 1 and next_part.isalpha():
                        if paired and next_part == word_chars[-1][-1]:
                            j += 1
                            break
                        word_chars.append(next_part)
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == next_part[1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part)
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == word_chars[-1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part[1])
                        paired = True
                        j += 1
                    else:
                        break
                if len(word_chars) >= 2:
                    final_parts.append("".join(word_chars))
                    i = j
                    continue
            final_parts.append(part)
            i += 1

        cleaned = " ".join(final_parts)

        cleaned = re.sub(r"\(\s*/\s*([a-z]+)\s*/\s*", r"(/\1/", cleaned)

        cleaned = re.sub(r"([a-z]+)\s*/\s*(\d+)\s*/\s*", r"\1/\2/", cleaned)

        cleaned = re.sub(r"([a-z]+)\s+([a-z]+)\s*/\s*", r"\1\2/", cleaned)

        cleaned = re.sub(r"/\s+([a-z]+)\s+/", r"/\1/", cleaned)

        cleaned = re.sub(r"\?\s*nid\s*=\s*", r"?nid=", cleaned)

        cleaned = re.sub(r"&\s*chronos\s*=\s*", r"&chronos=", cleaned)

        cleaned = re.sub(r"#\s*", r"#", cleaned)

        cleaned = re.sub(r"([a-z0-9])\s*-\s*\s*([a-z0-9])", r"\1-\2", cleaned)

        cleaned = re.sub(r"([a-z0-9])\s+-\s+([a-z0-9])", r"\1-\2", cleaned)

        cleaned = re.sub(r"-\s+-\s+", r"-", cleaned)

        cleaned = re.sub(r"-\s+-\s*([a-z])", r"-\1", cleaned)

        while True:
            new_cleaned = re.sub(r"([a-z])\s+([a-z])\s*-\s*", r"\1\2-", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        while True:
            new_cleaned = re.sub(r"([a-z])\s+([a-z])\s*-\s*([a-z])", r"\1\2-\3", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        cleaned = re.sub(r"([a-z])\s+([a-z])\s+([a-z])\s*-\s*", r"\1\2\3-", cleaned)

        cleaned = re.sub(r"([a-z])([a-z])([a-z])\s*--\s*", r"\1\2\3-", cleaned)

        cleaned = re.sub(r"([a-z])([a-z])([a-z])\s*--\s*([a-z])", r"\1\2\3-\4", cleaned)

        cleaned = re.sub(r"([a-z])\s+([a-z])\s+([a-z])\s*-\s*-\s*([a-z])", r"\1\2\3-\4", cleaned)

        cleaned = re.sub(r"([a-z]+)-\s*([a-z])\s+([a-z])\s+([a-z])\s*-\s*", r"\1-\2\3\4-", cleaned)

        cleaned = re.sub(
            r"([a-z]+)-\s*([a-z])\s+([a-z])\s+([a-z])\s+([a-z])\s*-\s*", r"\1-\2\3\4\5-", cleaned
        )

        while True:
            new_cleaned = re.sub(
                r"([a-z])\s+([a-z])\s+([a-z])\s+([a-z])\s*-\s*", r"\1\2\3\4-", cleaned
            )
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        while True:
            new_cleaned = re.sub(
                r"([a-z])\s+([a-z])\s+([a-z])\s+([a-z])\s+([a-z])\s*-\s*", r"\1\2\3\4\5-", cleaned
            )
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        cleaned = re.sub(r"([a-z]+)-\s*([a-z])\s+([a-z])\s+([a-z])\s*-\s*", r"\1-\2\3\4-", cleaned)

        cleaned = re.sub(r"von\s+(\d)(\d{2})\.", r"von \1 \2.", cleaned)

        cleaned = re.sub(r"von\s+(\d{3})\.", r"von \1.", cleaned)

        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip()

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

    def process_markdown(
        self, file_content: bytes, filename: str, file_size: int | None = None
    ) -> list[TextChunk]:
        actual_size = file_size if file_size is not None else len(file_content)
        text = file_content.decode("utf-8", errors="ignore")
        chunks = self._chunk_text(
            text,
            base_metadata={
                "source": filename,
                "file_size": actual_size,
                "file_type": "markdown",
            },
        )
        return self._add_context_overlap(chunks)

    def process_text(
        self, file_content: bytes, filename: str, file_size: int | None = None
    ) -> list[TextChunk]:
        actual_size = file_size if file_size is not None else len(file_content)
        text = file_content.decode("utf-8", errors="ignore")
        chunks = self._chunk_text(
            text,
            base_metadata={
                "source": filename,
                "file_size": actual_size,
                "file_type": "text",
            },
        )
        return self._add_context_overlap(chunks)

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

    def process_csv(
        self, file_content: bytes, filename: str, file_size: int | None = None
    ) -> list[TextChunk]:
        actual_size = file_size if file_size is not None else len(file_content)
        text = file_content.decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text))
        chunks = []

        for row_num, row in enumerate(reader, start=1):
            row_text = " | ".join(f"{k}: {v}" for k, v in row.items() if v)
            if not row_text.strip():
                continue

            chunks.append(
                TextChunk(
                    text=row_text,
                    metadata={
                        "source": filename,
                        "file_size": actual_size,
                        "row": row_num,
                        "file_type": "csv",
                    },
                )
            )

        return chunks

    def process_json(
        self, file_content: bytes, filename: str, file_size: int | None = None
    ) -> list[TextChunk]:
        actual_size = file_size if file_size is not None else len(file_content)
        text = file_content.decode("utf-8", errors="ignore")
        data = json.loads(text)
        chunks = []

        if isinstance(data, list):
            for idx, item in enumerate(data):
                if isinstance(item, dict):
                    item_text = " | ".join(f"{k}: {v}" for k, v in item.items())
                else:
                    item_text = str(item)

                if not item_text.strip():
                    continue

                chunks.append(
                    TextChunk(
                        text=item_text,
                        metadata={
                            "source": filename,
                            "file_size": actual_size,
                            "index": idx,
                            "file_type": "json",
                        },
                    )
                )
        elif isinstance(data, dict):
            json_text = json.dumps(data, ensure_ascii=False, indent=2)
            chunks = self._chunk_text(
                json_text,
                base_metadata={
                    "source": filename,
                    "file_size": actual_size,
                    "file_type": "json",
                },
            )
            chunks = self._add_context_overlap(chunks)
        else:
            chunks.append(
                TextChunk(
                    text=str(data),
                    metadata={
                        "source": filename,
                        "file_size": actual_size,
                        "file_type": "json",
                    },
                )
            )

        return chunks

    def process_file(
        self, file_content: bytes, filename: str, file_size: int | None = None
    ) -> list[TextChunk]:
        lower_filename = filename.lower()

        if lower_filename.endswith(".pdf"):
            return self.process_pdf(file_content, filename, file_size)
        elif lower_filename.endswith(".md") or lower_filename.endswith(".markdown"):
            return self.process_markdown(file_content, filename, file_size)
        elif lower_filename.endswith(".csv"):
            return self.process_csv(file_content, filename, file_size)
        elif lower_filename.endswith(".json"):
            return self.process_json(file_content, filename, file_size)
        elif lower_filename.endswith(".txt"):
            return self.process_text(file_content, filename, file_size)
        else:
            return self.process_text(file_content, filename, file_size)

    def _chunk_text(self, text: str, base_metadata: dict) -> list[TextChunk]:
        if not text.strip():
            return []

        words = text.split()
        chunks = []
        current_chunk_words = []
        current_length = 0

        for word in words:
            word_len = len(word) + 1
            if current_length + word_len > self.chunk_size and current_chunk_words:
                chunk_text = " ".join(current_chunk_words)
                chunks.append(
                    TextChunk(
                        text=chunk_text,
                        metadata={
                            **base_metadata,
                            "chunk_index": len(chunks),
                        },
                    )
                )
                current_chunk_words = []
                current_length = 0

            current_chunk_words.append(word)
            current_length += word_len

        if current_chunk_words:
            chunk_text = " ".join(current_chunk_words)
            chunks.append(
                TextChunk(
                    text=chunk_text,
                    metadata={
                        **base_metadata,
                        "chunk_index": len(chunks),
                    },
                )
            )

        return chunks

    def _add_context_overlap(self, chunks: list[TextChunk]) -> list[TextChunk]:
        if len(chunks) <= 1:
            return chunks

        result = []
        for i, chunk in enumerate(chunks):
            prev_context = ""
            next_context = ""

            if i > 0:
                prev_text = chunks[i - 1].text
                prev_context = (
                    prev_text[-self.overlap :] if len(prev_text) > self.overlap else prev_text
                )

            if i < len(chunks) - 1:
                next_text = chunks[i + 1].text
                next_context = (
                    next_text[: self.overlap] if len(next_text) > self.overlap else next_text
                )

            full_text = ""
            if prev_context:
                full_text = f"...{prev_context} "
            full_text += chunk.text
            if next_context:
                full_text += f" {next_context}..."

            result.append(
                TextChunk(
                    text=full_text,
                    metadata={
                        **chunk.metadata,
                        "has_prev_context": bool(prev_context),
                        "has_next_context": bool(next_context),
                    },
                )
            )

        return result


def create_file_processor(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> FileProcessor:
    return FileProcessor(chunk_size=chunk_size, overlap=overlap)
