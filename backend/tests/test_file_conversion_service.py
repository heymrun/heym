import unittest
from unittest.mock import MagicMock, patch

from app.services import file_conversion_service as fcs


class DetectPandocFormatTests(unittest.TestCase):
    def test_detects_by_mime(self) -> None:
        self.assertEqual(fcs.detect_pandoc_format("text/markdown", "doc.md"), "markdown")
        self.assertEqual(fcs.detect_pandoc_format("text/html", "page.html"), "html")
        self.assertEqual(fcs.detect_pandoc_format("text/plain", "notes.txt"), "markdown")
        self.assertEqual(fcs.detect_pandoc_format("text/csv", "data.csv"), "csv")
        self.assertEqual(
            fcs.detect_pandoc_format(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "report.docx",
            ),
            "docx",
        )

    def test_falls_back_to_the_extension(self) -> None:
        self.assertEqual(
            fcs.detect_pandoc_format("application/octet-stream", "readme.md"), "markdown"
        )

    def test_unsupported_returns_none(self) -> None:
        self.assertIsNone(fcs.detect_pandoc_format("application/zip", "archive.zip"))


class ConvertImageTests(unittest.TestCase):
    def test_png_to_jpg(self) -> None:
        img = MagicMock()
        img.mode = "RGB"
        with patch("PIL.Image.open", return_value=img):
            out_bytes, out_mime = fcs.convert_image(b"png-bytes", "jpg")

        self.assertEqual(out_mime, "image/jpeg")
        self.assertIsInstance(out_bytes, bytes)
        self.assertEqual(img.save.call_args.kwargs["format"], "JPEG")

    def test_rgba_is_flattened_before_jpeg(self) -> None:
        img = MagicMock()
        img.mode = "RGBA"
        with patch("PIL.Image.open", return_value=img):
            fcs.convert_image(b"png-rgba-bytes", "jpg")

        img.convert.assert_called_once_with("RGB")

    def test_unsupported_image_format_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_image(b"bytes", "docx")
        self.assertIn("unsupported image output format", str(ctx.exception))


class ExtractPdfTextTests(unittest.TestCase):
    def test_joins_pages_with_a_blank_line(self) -> None:
        reader = MagicMock()
        first, second = MagicMock(), MagicMock()
        first.extract_text.return_value = "page one"
        second.extract_text.return_value = "page two"
        reader.pages = [first, second]

        with patch("pypdf.PdfReader", return_value=reader):
            self.assertEqual(fcs.extract_pdf_text(b"fake-pdf"), "page one\n\npage two")

    def test_skips_pages_without_text(self) -> None:
        reader = MagicMock()
        empty, filled = MagicMock(), MagicMock()
        empty.extract_text.return_value = ""
        filled.extract_text.return_value = "only this"
        reader.pages = [empty, filled]

        with patch("pypdf.PdfReader", return_value=reader):
            self.assertEqual(fcs.extract_pdf_text(b"fake-pdf"), "only this")


class ConvertFileTests(unittest.TestCase):
    def test_image_to_image_keeps_the_base_name(self) -> None:
        img = MagicMock()
        img.mode = "RGB"
        with patch("PIL.Image.open", return_value=img):
            result = fcs.convert_file(
                src_bytes=b"png",
                src_mime="image/png",
                src_filename="logo.png",
                target_format="jpeg",
            )

        self.assertEqual(result.filename, "logo.jpg")
        self.assertEqual(result.mime_type, "image/jpeg")

    def test_image_to_document_is_rejected_with_an_ocr_hint(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_file(
                src_bytes=b"png",
                src_mime="image/png",
                src_filename="scan.png",
                target_format="pdf",
            )
        self.assertIn("imageToText", str(ctx.exception))

    def test_document_to_image_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_file(
                src_bytes=b"# hi",
                src_mime="text/markdown",
                src_filename="doc.md",
                target_format="png",
            )
        self.assertIn("cannot convert a document", str(ctx.exception))

    def test_markdown_to_html_goes_through_pandoc(self) -> None:
        captured: dict = {}

        def fake_convert(src, target, outputfile, format, extra_args):
            captured.update({"target": target, "format": format, "extra_args": extra_args})
            with open(outputfile, "wb") as handle:
                handle.write(b"<h1>hi</h1>")

        with patch("pypandoc.convert_file", side_effect=fake_convert):
            result = fcs.convert_file(
                src_bytes=b"# hi",
                src_mime="text/markdown",
                src_filename="doc.md",
                target_format="html",
            )

        self.assertEqual(captured["target"], "html")
        self.assertEqual(captured["format"], "markdown")
        self.assertEqual(captured["extra_args"], [])
        self.assertEqual(result.filename, "doc.html")
        self.assertEqual(result.mime_type, "text/html")
        self.assertEqual(result.content, b"<h1>hi</h1>")

    def test_pdf_output_uses_weasyprint(self) -> None:
        captured: dict = {}

        def fake_convert(src, target, outputfile, format, extra_args):
            captured["extra_args"] = extra_args
            with open(outputfile, "wb") as handle:
                handle.write(b"%PDF-1.7")

        with patch("pypandoc.convert_file", side_effect=fake_convert):
            fcs.convert_file(
                src_bytes=b"# hi",
                src_mime="text/markdown",
                src_filename="doc.md",
                target_format="pdf",
            )

        self.assertEqual(captured["extra_args"], ["--pdf-engine=weasyprint"])

    def test_pdf_input_is_flattened_to_text_first(self) -> None:
        captured: dict = {}

        def fake_convert(src, target, outputfile, format, extra_args):
            captured["format"] = format
            captured["source_text"] = open(src, encoding="utf-8").read()
            with open(outputfile, "wb") as handle:
                handle.write(b"plain")

        reader = MagicMock()
        page = MagicMock()
        page.extract_text.return_value = "extracted body"
        reader.pages = [page]

        with (
            patch("pypdf.PdfReader", return_value=reader),
            patch("pypandoc.convert_file", side_effect=fake_convert),
        ):
            result = fcs.convert_file(
                src_bytes=b"%PDF",
                src_mime="application/pdf",
                src_filename="report.pdf",
                target_format="txt",
            )

        self.assertEqual(captured["format"], "markdown")
        self.assertEqual(captured["source_text"], "extracted body")
        self.assertEqual(result.filename, "report.txt")

    def test_json_to_csv_uses_the_csv_writer(self) -> None:
        result = fcs.convert_file(
            src_bytes=b'[{"name": "Ada", "age": 36}, {"name": "Grace", "age": 45}]',
            src_mime="application/json",
            src_filename="people.json",
            target_format="csv",
        )

        self.assertEqual(result.mime_type, "text/csv")
        self.assertEqual(result.filename, "people.csv")
        self.assertEqual(
            result.content.decode().replace("\r\n", "\n").strip(),
            "name,age\nAda,36\nGrace,45",
        )

    def test_csv_output_from_a_non_json_input_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_file(
                src_bytes=b"# hi",
                src_mime="text/markdown",
                src_filename="doc.md",
                target_format="csv",
            )
        self.assertIn("JSON array input", str(ctx.exception))

    def test_json_that_is_not_an_array_of_objects_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_file(
                src_bytes=b'{"name": "Ada"}',
                src_mime="application/json",
                src_filename="one.json",
                target_format="csv",
            )
        self.assertIn("conversion failed", str(ctx.exception))

    def test_unsupported_input_format_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_file(
                src_bytes=b"PK",
                src_mime="application/zip",
                src_filename="archive.zip",
                target_format="txt",
            )
        self.assertIn("unsupported input format", str(ctx.exception))

    def test_unsupported_output_format_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_file(
                src_bytes=b"# hi",
                src_mime="text/markdown",
                src_filename="doc.md",
                target_format="xlsx",
            )
        self.assertIn("unsupported output format", str(ctx.exception))

    def test_missing_target_format_is_rejected(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            fcs.convert_file(
                src_bytes=b"# hi",
                src_mime="text/markdown",
                src_filename="doc.md",
                target_format="  ",
            )
        self.assertIn("target format is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
