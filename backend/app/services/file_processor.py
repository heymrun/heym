import csv
import io
import json
import re
from dataclasses import dataclass


@dataclass
class TextChunk:
    text: str
    metadata: dict


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

        parts = text.split()
        if not parts:
            return text

        result = []
        i = 0
        while i < len(parts):
            part = parts[i]

            if len(part) == 1:
                j = i + 1
                while j < len(parts) and parts[j] == part:
                    j += 1
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
            new_cleaned = re.sub(r"([a-zA-Z])\s+\1(\s|$)", r"\1\1\2", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        cleaned = re.sub(r"([a-zA-Z]{2})\s+\1(\s|$)", r"\1\2", cleaned)

        cleaned_parts = cleaned.split()
        final_parts = []
        i = 0
        while i < len(cleaned_parts):
            part = cleaned_parts[i]
            if len(part) == 1 and part.isalpha():
                word_chars = [part]
                j = i + 1
                while j < len(cleaned_parts):
                    next_part = cleaned_parts[j]
                    if len(next_part) == 1 and next_part.isalpha():
                        word_chars.append(next_part)
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == next_part[1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part[0])
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == word_chars[-1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part[1])
                        j += 1
                    else:
                        break
                if len(word_chars) >= 2:
                    final_parts.append("".join(word_chars))
                    i = j
                    continue
            elif len(part) == 2 and part[0] == part[1] and part[0].isalpha():
                word_chars = [part[0]]
                j = i + 1
                while j < len(cleaned_parts):
                    next_part = cleaned_parts[j]
                    if len(next_part) == 1 and next_part.isalpha():
                        word_chars.append(next_part)
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == next_part[1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part[0])
                        j += 1
                    elif (
                        len(next_part) == 2
                        and next_part[0] == word_chars[-1]
                        and next_part[0].isalpha()
                    ):
                        word_chars.append(next_part[1])
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

        cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)

        cleaned = re.sub(r"([A-Z]{2,})([a-z])", r"\1 \2", cleaned)

        cleaned = re.sub(r"([A-Z]{2})([A-Z])([a-z])", r"\1 \2\3", cleaned)

        cleaned = re.sub(r"([A-Z]{3})\s+([a-z])", r"\1 \2", cleaned)

        cleaned = re.sub(r"([a-zA-Z]+)(and)([a-zA-Z]+)", r"\1 \2 \3", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(
            r"([a-zA-Z]+)(of|the|to)([A-Z])", r"\1 \2 \3", cleaned, flags=re.IGNORECASE
        )

        cleaned = re.sub(
            r"([a-zA-Z]+)(of|the|to)([a-z])", r"\1 \2 \3", cleaned, flags=re.IGNORECASE
        )

        cleaned = re.sub(r"([a-zA-Z]+)(of|the|to)(\s)", r"\1 \2\3", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"([a-zA-Z]+)(to)(the)", r"\1 \2 \3", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"([a-zA-Z]+)(To)(the)", r"\1 \2 \3", cleaned, flags=re.IGNORECASE)

        cleaned = re.sub(r"\(\s*/\s*([a-z]+)\s*/\s*", r"(/\1/", cleaned)

        cleaned = re.sub(r"([a-z]+)\s*/\s*(\d+)\s*/\s*", r"\1/\2/", cleaned)

        cleaned = re.sub(r"([a-z]+)\s+([a-z]+)\s*/\s*", r"\1\2/", cleaned)

        cleaned = re.sub(r"/\s+([a-z]+)\s+/", r"/\1/", cleaned)

        cleaned = re.sub(
            r"\b([a-zA-Z]{4,})\b\s+and\s+\b([a-zA-Z]{1})\b(\s|$|,|\.)",
            r"\1and\2\3",
            cleaned,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"\b([a-zA-Z]{4,})\b\s+and\s+\b(um|ed|er|al|ic|ly|en|in|on|at|it|is|as|an|or|ar|ur|ir|el|le|ne|te|re|se|de|ce|ge|me|pe|ve|we|ye|ze)\b(\s|$|,|\.)",
            r"\1and\2\3",
            cleaned,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(
            r"\b([a-zA-Z]{1,2})\b\s+and\s+\b([a-zA-Z]{4,})\b(\s|$|,|\.)",
            r"\1and\2\3",
            cleaned,
            flags=re.IGNORECASE,
        )

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

        while True:
            new_cleaned = re.sub(r"(\d)\s+(\d)", r"\1\2", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned

        cleaned = re.sub(r"\s+", " ", cleaned)

        return cleaned.strip()

    def process_pdf(
        self, file_content: bytes, filename: str, file_size: int | None = None
    ) -> list[TextChunk]:
        from pypdf import PdfReader

        actual_size = file_size if file_size is not None else len(file_content)
        reader = PdfReader(io.BytesIO(file_content))
        chunks = []

        for page_num, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""

            if not page_text.strip():
                continue

            page_text = self._clean_pdf_text(page_text)

            if not page_text.strip():
                continue

            page_chunks = self._chunk_text(
                page_text,
                base_metadata={
                    "source": filename,
                    "file_size": actual_size,
                    "page": page_num,
                    "total_pages": len(reader.pages),
                    "file_type": "pdf",
                },
            )
            chunks.extend(page_chunks)

        return self._add_context_overlap(chunks)

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
