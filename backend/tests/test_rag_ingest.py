"""How an uploaded file becomes vector store chunks (rag_ingest)."""

import io
import unittest
import zipfile
from unittest.mock import patch

from docx import Document
from openpyxl import Workbook
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


def _docx(*paragraphs: str) -> bytes:
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
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
            "contract.DOCX": RagFileKind.DOCX,
            "budget.XLSX": RagFileKind.XLSX,
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
            "WhatsApp Audio 2026-11-10 at 10.00.36.opus": RagFileKind.AUDIO,
            ".md": RagFileKind.MARKDOWN,
        }
        for name, kind in cases.items():
            self.assertEqual(rag_ingest.classify(name, b"\x00binary"), kind, name)

    def test_unknown_name_with_utf8_content_is_text(self) -> None:
        self.assertEqual(rag_ingest.classify("burak.akgun", b"notes"), RagFileKind.TEXT)
        self.assertEqual(rag_ingest.classify("README", b"# hi"), RagFileKind.TEXT)

    def test_unknown_binary_is_refused(self) -> None:
        self.assertIsNone(rag_ingest.classify("deck.pptx", b"PK\x03\x04\x00\x00"))

    def test_refusal_message_names_the_file_and_the_formats(self) -> None:
        message = rag_ingest.unsupported_message("deck.pptx")

        self.assertIn("deck.pptx", message)
        self.assertIn("Word (DOCX)", message)
        self.assertIn("Excel (XLSX)", message)
        self.assertIn("audio (mp3, wav, ogg, opus, flac)", message)
        self.assertIn("other plain-text files", message)


class PageRangeTests(unittest.TestCase):
    def test_contiguous_pages_group_and_split_at_the_limit(self) -> None:
        ranges = rag_ingest.page_ranges([1, 2, 3, 5, 7, 8], max_len=2)

        self.assertEqual(ranges, [(1, 2), (3, 3), (5, 5), (7, 8)])


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


class DocxChunkTests(unittest.TestCase):
    def test_word_document_is_read_now(self) -> None:
        data = _docx("Refunds are paid within 14 days.", "Ask finance for exceptions.")

        chunks = rag_ingest.quick_chunks(RagFileKind.DOCX, data, "Policy.docx", len(data))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(
            chunks[0].text, "Refunds are paid within 14 days. Ask finance for exceptions."
        )
        self.assertEqual(chunks[0].metadata["file_type"], "docx")
        self.assertEqual(chunks[0].metadata["source"], "Policy.docx")
        self.assertEqual(chunks[0].metadata["file_size"], len(data))

    def test_background_extraction_reads_it_the_same_way(self) -> None:
        data = _docx("One paragraph.")

        self.assertEqual(
            [c.text for c in rag_ingest.extract_chunks(RagFileKind.DOCX, data, "a.docx", 1)],
            [c.text for c in rag_ingest.quick_chunks(RagFileKind.DOCX, data, "a.docx", 1)],
        )

    def test_word_document_without_text_fails(self) -> None:
        data = _docx()

        with self.assertRaises(RagIngestError) as raised:
            rag_ingest.quick_chunks(RagFileKind.DOCX, data, "empty.docx", len(data))

        self.assertEqual(str(raised.exception), "No text was found in empty.docx.")

    def test_unreadable_word_documents_are_user_errors(self) -> None:
        other_zip = io.BytesIO()
        with zipfile.ZipFile(other_zip, "w") as archive:
            archive.writestr("notes.txt", "not a Word document")
        cases = {
            "not a zip": b"PK\x03\x04\x00\x00",
            "zip without a document": other_zip.getvalue(),
            "legacy .doc renamed": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
        }
        for label, data in cases.items():
            with self.assertRaises(RagIngestError, msg=label) as raised:
                rag_ingest.quick_chunks(RagFileKind.DOCX, data, "a.docx", len(data))

            self.assertEqual(
                str(raised.exception), "Heym could not read a.docx as a Word document.", label
            )

    def test_archive_that_unpacks_too_far_is_a_user_error(self) -> None:
        data = _docx("x")

        with patch("app.services.office_archive.MAX_UNPACKED_BYTES", 1024):
            with self.assertRaises(RagIngestError) as raised:
                rag_ingest.quick_chunks(RagFileKind.DOCX, data, "big.docx", len(data))

        self.assertEqual(str(raised.exception), "big.docx is too large to read once unpacked.")


def _xlsx(*rows: list) -> bytes:
    workbook = Workbook()
    workbook.active.title = "Orders"
    for row in rows:
        workbook.active.append(row)
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


class XlsxChunkTests(unittest.TestCase):
    def test_every_row_is_one_chunk_like_a_csv_row(self) -> None:
        data = _xlsx(["Order", "Status"], ["A-1", "shipped"], ["A-2", "open"])

        chunks = rag_ingest.quick_chunks(RagFileKind.XLSX, data, "Orders.xlsx", len(data))

        self.assertEqual(
            [c.text for c in chunks], ["Order: A-1 | Status: shipped", "Order: A-2 | Status: open"]
        )
        self.assertEqual(
            chunks[0].metadata,
            {
                "source": "Orders.xlsx",
                "file_size": len(data),
                "sheet": "Orders",
                "row": 2,
                "file_type": "xlsx",
            },
        )

    def test_background_extraction_reads_it_the_same_way(self) -> None:
        data = _xlsx(["Order"], ["A-1"])

        self.assertEqual(
            [c.text for c in rag_ingest.extract_chunks(RagFileKind.XLSX, data, "o.xlsx", 1)],
            ["Order: A-1"],
        )

    def test_empty_workbook_fails(self) -> None:
        data = _xlsx()

        with self.assertRaises(RagIngestError) as raised:
            rag_ingest.quick_chunks(RagFileKind.XLSX, data, "empty.xlsx", len(data))

        self.assertEqual(str(raised.exception), "No text was found in empty.xlsx.")

    def test_unreadable_workbooks_are_user_errors(self) -> None:
        other_zip = io.BytesIO()
        with zipfile.ZipFile(other_zip, "w") as archive:
            archive.writestr("notes.txt", "not a workbook")
        cases = {
            "not a zip": b"PK\x03\x04\x00\x00",
            "zip without a workbook": other_zip.getvalue(),
            "Word document renamed": _docx("hello"),
            "legacy .xls renamed": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,
        }
        for label, data in cases.items():
            with self.assertRaises(RagIngestError, msg=label) as raised:
                rag_ingest.quick_chunks(RagFileKind.XLSX, data, "a.xlsx", len(data))

            self.assertEqual(
                str(raised.exception), "Heym could not read a.xlsx as an Excel workbook.", label
            )

    def test_archive_that_unpacks_too_far_is_a_user_error(self) -> None:
        data = _xlsx(["x"])

        with patch("app.services.office_archive.MAX_UNPACKED_BYTES", 1024):
            with self.assertRaises(RagIngestError) as raised:
                rag_ingest.quick_chunks(RagFileKind.XLSX, data, "big.xlsx", len(data))

        self.assertEqual(str(raised.exception), "big.xlsx is too large to read once unpacked.")


class FullExtractionTests(unittest.TestCase):
    def test_audio_is_transcribed_into_timed_chunks(self) -> None:
        result = SttResult(
            text="Hello. Invoice is late.",
            language="en",
            duration_seconds=7.25,
            segments=[SttSegment(0.0, 2.0, "Hello."), SttSegment(2.0, 7.25, "Invoice is late.")],
        )
        with patch("app.services.speech_to_text_service.audio_to_text", return_value=result) as stt:
            chunks = rag_ingest.extract_chunks(RagFileKind.AUDIO, b"mp3", "call.mp3", 3)

        stt.assert_called_once_with(b"mp3", filename="call.mp3", language="auto")
        self.assertEqual(chunks[0].metadata["start_seconds"], 0.0)
        self.assertEqual(chunks[0].metadata["end_seconds"], 7.25)
        self.assertEqual(chunks[0].metadata["duration_seconds"], 7.25)
        self.assertEqual(chunks[0].metadata["language"], "en")

    def test_audio_without_segments_keeps_the_whole_text(self) -> None:
        result = SttResult(text="One sentence.", language="en", duration_seconds=2.0)
        with patch("app.services.speech_to_text_service.audio_to_text", return_value=result):
            chunks = rag_ingest.extract_chunks(RagFileKind.AUDIO, b"mp3", "a.mp3", 3)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["end_seconds"], 2.0)

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
