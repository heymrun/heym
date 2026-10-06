"""Unit tests for FileProcessor (chunking + per-format text extraction).

Pure logic, no DB/network - process_pdf builds real minimal PDFs in-memory
with reportlab (already a project dependency) rather than hand-typing bytes,
since PdfReader needs genuine PDF structure.
"""

import io
import json
import unittest

from reportlab.pdfgen import canvas

from app.services.file_processor import FileProcessor, TextChunk


def _build_pdf(*pages: str) -> bytes:
    """Build a real in-memory PDF with one text-drawing page per string.
    An empty string produces a genuinely blank page (nothing drawn)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for text in pages:
        if text:
            c.drawString(100, 750, text)
        c.showPage()
    c.save()
    return buf.getvalue()


class CleanPdfTextTests(unittest.TestCase):
    def test_empty_string_returns_unchanged(self) -> None:
        self.assertEqual(FileProcessor()._clean_pdf_text(""), "")

    def test_single_letter_runs_collapse(self) -> None:
        result = FileProcessor()._clean_pdf_text("m m m i i ss ss i i oo nn")
        self.assertEqual(result, "mission")

    def test_overlapping_pairs_are_rejoined(self) -> None:
        result = FileProcessor()._clean_pdf_text("m mo ov ve em me en nt t")
        self.assertEqual(result, "movement")

    def test_fake_bold_doubled_letters_collapse(self) -> None:
        result = FileProcessor()._clean_pdf_text("mm ii ss ss ii oo nn")
        self.assertEqual(result, "mission")

    def test_trailing_single_letter_word_is_kept_separate(self) -> None:
        self.assertEqual(FileProcessor()._clean_pdf_text("data a"), "data a")

    def test_normal_text_is_not_mangled(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        self.assertEqual(FileProcessor()._clean_pdf_text(text), text)

    def test_spaced_out_word_is_rejoined(self) -> None:
        self.assertEqual(FileProcessor()._clean_pdf_text("J o i n t"), "Joint")


class ChunkTextTests(unittest.TestCase):
    def test_empty_text_returns_no_chunks(self) -> None:
        self.assertEqual(FileProcessor()._chunk_text("", {}), [])
        self.assertEqual(FileProcessor()._chunk_text("   ", {}), [])

    def test_short_text_is_a_single_chunk(self) -> None:
        chunks = FileProcessor()._chunk_text("hello world", {"source": "x.txt"})

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "hello world")
        self.assertEqual(chunks[0].metadata, {"source": "x.txt", "chunk_index": 0})

    def test_long_text_splits_into_multiple_chunks(self) -> None:
        text = " ".join(f"word{i}" for i in range(20))
        chunks = FileProcessor(chunk_size=20)._chunk_text(text, {})

        self.assertGreater(len(chunks), 1)
        self.assertEqual([c.metadata["chunk_index"] for c in chunks], list(range(len(chunks))))
        # The boundary check only runs before adding the NEXT word, so a chunk
        # can exceed chunk_size by at most one word's worth of overflow - not
        # by an arbitrary amount.
        longest_word = max(len(w) for w in text.split())
        for chunk in chunks[:-1]:
            self.assertLessEqual(len(chunk.text), 20 + longest_word + 1)

    def test_base_metadata_is_merged_into_every_chunk(self) -> None:
        text = " ".join(f"word{i}" for i in range(20))
        chunks = FileProcessor(chunk_size=20)._chunk_text(text, {"source": "x.txt", "page": 1})

        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk.metadata["source"], "x.txt")
            self.assertEqual(chunk.metadata["page"], 1)
            self.assertEqual(chunk.metadata["chunk_index"], i)


class AddContextOverlapTests(unittest.TestCase):
    def test_zero_or_one_chunks_are_returned_unchanged(self) -> None:
        fp = FileProcessor()
        self.assertEqual(fp._add_context_overlap([]), [])

        one = [TextChunk(text="solo", metadata={})]
        result = fp._add_context_overlap(one)
        self.assertEqual(result, one)
        self.assertNotIn("has_prev_context", result[0].metadata)

    def test_first_chunk_has_only_next_context(self) -> None:
        chunks = [
            TextChunk(text="first", metadata={}),
            TextChunk(text="second", metadata={}),
            TextChunk(text="third", metadata={}),
        ]
        result = FileProcessor()._add_context_overlap(chunks)

        self.assertFalse(result[0].metadata["has_prev_context"])
        self.assertTrue(result[0].metadata["has_next_context"])

    def test_last_chunk_has_only_prev_context(self) -> None:
        chunks = [
            TextChunk(text="first", metadata={}),
            TextChunk(text="second", metadata={}),
            TextChunk(text="third", metadata={}),
        ]
        result = FileProcessor()._add_context_overlap(chunks)

        self.assertTrue(result[-1].metadata["has_prev_context"])
        self.assertFalse(result[-1].metadata["has_next_context"])

    def test_middle_chunk_gets_both_contexts(self) -> None:
        chunks = [
            TextChunk(text="first", metadata={}),
            TextChunk(text="second", metadata={}),
            TextChunk(text="third", metadata={}),
        ]
        result = FileProcessor()._add_context_overlap(chunks)

        middle = result[1]
        self.assertTrue(middle.metadata["has_prev_context"])
        self.assertTrue(middle.metadata["has_next_context"])
        self.assertEqual(middle.text, "...first second third...")

    def test_overlap_is_truncated_to_the_configured_length(self) -> None:
        chunks = [
            TextChunk(text="abcdefghij", metadata={}),
            TextChunk(text="middle", metadata={}),
            TextChunk(text="klmnopqrst", metadata={}),
        ]
        result = FileProcessor(overlap=5)._add_context_overlap(chunks)

        middle = result[1]
        self.assertEqual(middle.text, "...fghij middle klmno...")


class ProcessCsvTests(unittest.TestCase):
    def test_parses_rows_into_chunks(self) -> None:
        csv_bytes = b"name,age\nAlice,30\nBob,25"
        chunks = FileProcessor().process_csv(csv_bytes, "people.csv")

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].text, "name: Alice | age: 30")
        self.assertEqual(chunks[0].metadata["row"], 1)
        self.assertEqual(chunks[0].metadata["file_type"], "csv")
        self.assertEqual(chunks[1].text, "name: Bob | age: 25")
        self.assertEqual(chunks[1].metadata["row"], 2)

    def test_rows_with_all_empty_values_are_skipped(self) -> None:
        csv_bytes = b"name,age\n,\nBob,25"
        chunks = FileProcessor().process_csv(csv_bytes, "people.csv")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "name: Bob | age: 25")


class ProcessJsonTests(unittest.TestCase):
    def test_array_of_objects_becomes_one_chunk_per_item(self) -> None:
        data = json.dumps([{"a": 1}, {"a": 2}]).encode()
        chunks = FileProcessor().process_json(data, "data.json")

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].text, "a: 1")
        self.assertEqual(chunks[0].metadata["index"], 0)
        self.assertEqual(chunks[1].text, "a: 2")
        self.assertEqual(chunks[1].metadata["index"], 1)

    def test_array_of_non_dict_items_uses_str_conversion(self) -> None:
        data = json.dumps([1, 2, 3]).encode()
        chunks = FileProcessor().process_json(data, "data.json")

        self.assertEqual([c.text for c in chunks], ["1", "2", "3"])

    def test_top_level_object_is_chunked_as_text(self) -> None:
        data = json.dumps({"key": "value"}).encode()
        chunks = FileProcessor().process_json(data, "data.json")

        self.assertEqual(len(chunks), 1)
        self.assertIn('"key": "value"', chunks[0].text)
        self.assertEqual(chunks[0].metadata["file_type"], "json")

    def test_top_level_scalar_becomes_a_single_chunk(self) -> None:
        chunks = FileProcessor().process_json(b"42", "data.json")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "42")


class ProcessFileTests(unittest.TestCase):
    def _assert_dispatches_to(self, filename: str, method_name: str) -> None:
        fp = FileProcessor()
        calls: list[str] = []
        for name in (
            "process_pdf",
            "process_markdown",
            "process_csv",
            "process_json",
            "process_text",
        ):
            setattr(fp, name, (lambda n: lambda *a, **k: calls.append(n) or [])(name))

        fp.process_file(b"content", filename)

        self.assertEqual(calls, [method_name])

    def test_dispatches_by_extension_case_insensitively(self) -> None:
        self._assert_dispatches_to("doc.pdf", "process_pdf")
        self._assert_dispatches_to("doc.PDF", "process_pdf")
        self._assert_dispatches_to("doc.md", "process_markdown")
        self._assert_dispatches_to("doc.Md", "process_markdown")
        self._assert_dispatches_to("doc.markdown", "process_markdown")
        self._assert_dispatches_to("doc.csv", "process_csv")
        self._assert_dispatches_to("doc.json", "process_json")
        self._assert_dispatches_to("doc.txt", "process_text")
        self._assert_dispatches_to("doc.xyz", "process_text")


class ProcessPdfTests(unittest.TestCase):
    def test_extracts_text_from_a_real_pdf(self) -> None:
        pdf_bytes = _build_pdf("Hello World")
        chunks = FileProcessor().process_pdf(pdf_bytes, "test.pdf")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "Hello World")
        self.assertEqual(chunks[0].metadata["page"], 1)
        self.assertEqual(chunks[0].metadata["total_pages"], 1)

    def test_blank_pages_are_skipped(self) -> None:
        # This asserts the final OUTCOME, not process_pdf's own early-exit
        # guards specifically - confirmed by mutation testing that removing
        # both `if not page_text.strip(): continue` checks still passes this
        # test, because _chunk_text has its own identical empty-text guard
        # downstream. The guards in process_pdf are an efficiency shortcut
        # (skip _clean_pdf_text and chunk setup for nothing), not something
        # that changes what chunks come out the other end.
        pdf_bytes = _build_pdf("", "Page Two Text")
        chunks = FileProcessor().process_pdf(pdf_bytes, "test.pdf")

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, "Page Two Text")
        self.assertEqual(chunks[0].metadata["page"], 2)
        self.assertEqual(chunks[0].metadata["total_pages"], 2)


if __name__ == "__main__":
    unittest.main()
