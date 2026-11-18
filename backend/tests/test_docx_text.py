"""Reading the visible text of a Word document (docx_text)."""

import io
import unittest
import zipfile
from unittest.mock import patch

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from app.services.docx_text import docx_text
from app.services.office_archive import ArchiveTooLargeError

W = nsdecls("w")
MC = (
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
)


def _save(document: Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _with_body_xml(*fragments: str) -> bytes:
    """A document whose body holds `fragments` before its section properties."""
    document = Document()
    body = document.element.body
    for fragment in fragments:
        body.insert(len(body) - 1, parse_xml(fragment))
    return _save(document)


class DocxTextTests(unittest.TestCase):
    def test_paragraphs_and_table_rows_keep_document_order(self) -> None:
        document = Document()
        document.add_heading("Leave policy", level=1)
        document.add_paragraph("Everyone gets 14 days.")
        table = document.add_table(rows=3, cols=2)
        table.cell(0, 0).text = "Seniority"
        table.cell(0, 1).text = "Days"
        table.cell(2, 0).text = "5+ years"
        table.cell(2, 1).text = "20"
        document.add_paragraph("Ask your manager.")

        self.assertEqual(
            docx_text(_save(document)),
            "Leave policy\nEveryone gets 14 days.\nSeniority | Days\n5+ years | 20\n"
            "Ask your manager.",
        )

    def test_tracked_changes_read_as_accepted(self) -> None:
        data = _with_body_xml(
            f"<w:p {W}><w:r><w:t xml:space='preserve'>Approved by </w:t></w:r>"
            "<w:ins w:id='1' w:author='a'><w:r><w:t>the manager</w:t></w:r></w:ins>"
            "<w:del w:id='2' w:author='a'><w:r><w:delText>HR</w:delText></w:r></w:del>"
            "<w:moveFrom w:id='3' w:author='a'><w:r><w:t>moved away</w:t></w:r></w:moveFrom>"
            "<w:r><w:t>.</w:t></w:r></w:p>"
        )

        self.assertEqual(docx_text(data), "Approved by the manager.")

    def test_content_controls_are_read(self) -> None:
        data = _with_body_xml(
            f"<w:sdt {W}><w:sdtPr><w:alias w:val='Client'/></w:sdtPr><w:sdtContent>"
            "<w:p><w:r><w:t>Acme GmbH</w:t></w:r></w:p></w:sdtContent></w:sdt>",
            f"<w:tbl {W}><w:sdt><w:sdtContent><w:tr>"
            "<w:tc><w:p><w:r><w:t>Row</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>in a control</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:sdtContent></w:sdt></w:tbl>",
        )

        self.assertEqual(docx_text(data), "Acme GmbH\nRow | in a control")

    def test_text_box_is_read_once(self) -> None:
        box = "<w:txbxContent><w:p><w:r><w:t>Boxed note</w:t></w:r></w:p></w:txbxContent>"
        data = _with_body_xml(
            f"<w:p {W} {MC}><w:r><w:t>Before</w:t></w:r><w:r><mc:AlternateContent>"
            f"<mc:Choice Requires='wps'><w:drawing><wps:txbx>{box}</wps:txbx></w:drawing>"
            "</mc:Choice>"
            f"<mc:Fallback><w:pict><v:textbox>{box}</v:textbox></w:pict></mc:Fallback>"
            "</mc:AlternateContent></w:r></w:p>"
        )

        self.assertEqual(docx_text(data), "Before\nBoxed note")

    def test_tabs_and_breaks_separate_words_but_tab_stops_do_not(self) -> None:
        data = _with_body_xml(
            f"<w:p {W}><w:pPr><w:tabs><w:tab w:val='left' w:pos='720'/></w:tabs></w:pPr>"
            "<w:r><w:t>Name</w:t><w:tab/><w:t>Ada</w:t><w:br/><w:t>Role</w:t>"
            "<w:noBreakHyphen/><w:t>lead</w:t></w:r></w:p>"
        )

        self.assertEqual(docx_text(data), "Name\tAda\nRole-lead")

    def test_nested_table_stays_in_its_cell(self) -> None:
        document = Document()
        outer = document.add_table(rows=1, cols=2)
        outer.cell(0, 0).text = "Outer"
        inner = outer.cell(0, 1).add_table(rows=1, cols=2)
        inner.cell(0, 0).text = "in"
        inner.cell(0, 1).text = "ner"

        self.assertEqual(docx_text(_save(document)), "Outer | in | ner")

    def test_empty_document_has_no_text(self) -> None:
        self.assertEqual(docx_text(_save(Document())), "")

    def test_archive_that_unpacks_too_far_is_refused_before_parsing(self) -> None:
        data = _save(Document())

        with patch("app.services.office_archive.MAX_UNPACKED_BYTES", 1024):
            with patch("app.services.docx_text.Document") as parse:
                with self.assertRaises(ArchiveTooLargeError):
                    docx_text(data)

        parse.assert_not_called()

    def test_not_a_zip_is_refused(self) -> None:
        with self.assertRaises(zipfile.BadZipFile):
            docx_text(b"PK\x03\x04\x00\x00")
