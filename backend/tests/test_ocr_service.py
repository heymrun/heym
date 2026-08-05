import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import ocr_service


def _completed(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["tesseract"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class LanguageSpecTests(unittest.TestCase):
    def test_blank_and_auto_map_to_auto(self) -> None:
        for raw in ("", None, "auto", "  AUTO  "):
            self.assertEqual(ocr_service.parse_language_spec(raw), ocr_service.AUTO_LANGUAGE)

    def test_single_and_combined_codes_pass_through(self) -> None:
        self.assertEqual(ocr_service.parse_language_spec("tur"), "tur")
        self.assertEqual(ocr_service.parse_language_spec(" eng + tur "), "eng+tur")
        self.assertEqual(ocr_service.parse_language_spec("chi_sim"), "chi_sim")
        self.assertEqual(ocr_service.parse_language_spec("script/Latin"), "script/Latin")

    def test_shell_metacharacters_are_rejected(self) -> None:
        for raw in ("tur; rm -rf /", "eng&&whoami", "../../etc/passwd", "eng|cat"):
            with self.assertRaises(ValueError):
                ocr_service.parse_language_spec(raw)

    def test_too_many_languages_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ocr_service.parse_language_spec("+".join(["eng"] * 9))


class EncodingTests(unittest.TestCase):
    def test_defaults_and_aliases(self) -> None:
        self.assertEqual(ocr_service.normalize_encoding(""), "utf-8")
        self.assertEqual(ocr_service.normalize_encoding("UTF8"), "utf-8")
        self.assertEqual(ocr_service.normalize_encoding("utf_8"), "utf-8")
        self.assertEqual(ocr_service.normalize_encoding("cp1254"), "cp1254")

    def test_unsupported_encoding_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ocr_service.normalize_encoding("rot13")

    def test_utf8_keeps_non_ascii_characters(self) -> None:
        text = "Gülşen İçöğü — naïve"
        self.assertEqual(
            ocr_service.apply_encoding(text, "utf-8", normalize_unicode=True),
            text,
        )

    def test_unicode_normalization_composes_combining_marks(self) -> None:
        decomposed = "Şehir"  # S + combining cedilla
        self.assertEqual(
            ocr_service.apply_encoding(decomposed, "utf-8", normalize_unicode=True),
            "Şehir",
        )
        self.assertEqual(
            ocr_service.apply_encoding(decomposed, "utf-8", normalize_unicode=False),
            decomposed,
        )

    def test_narrow_charset_replaces_unmappable_characters(self) -> None:
        result = ocr_service.apply_encoding("Şehir — 東京", "latin-1", normalize_unicode=True)
        self.assertNotIn("東", result)
        self.assertTrue(result.startswith("?ehir"))

    def test_cp1254_keeps_turkish_characters(self) -> None:
        text = "Şığüöç İ"
        self.assertEqual(ocr_service.apply_encoding(text, "cp1254", normalize_unicode=True), text)


class PsmAndDpiTests(unittest.TestCase):
    def test_psm_defaults_and_validation(self) -> None:
        self.assertEqual(ocr_service.normalize_psm(""), "3")
        self.assertEqual(ocr_service.normalize_psm("6"), "6")
        with self.assertRaises(ValueError):
            ocr_service.normalize_psm("99")

    def test_dpi_is_clamped(self) -> None:
        self.assertEqual(ocr_service.normalize_dpi(""), 300)
        self.assertEqual(ocr_service.normalize_dpi("150"), 150)
        self.assertEqual(ocr_service.normalize_dpi(10), ocr_service.MIN_PDF_DPI)
        self.assertEqual(ocr_service.normalize_dpi(99999), ocr_service.MAX_DPI)
        self.assertEqual(ocr_service.normalize_dpi("not a number"), 300)


class PageRangeTests(unittest.TestCase):
    def test_blank_range_covers_the_whole_document(self) -> None:
        self.assertEqual(ocr_service.parse_page_range("", 4), (1, 4))

    def test_single_page_and_span(self) -> None:
        self.assertEqual(ocr_service.parse_page_range("3", 10), (3, 3))
        self.assertEqual(ocr_service.parse_page_range("2-5", 10), (2, 5))

    def test_span_is_clamped_to_the_last_page(self) -> None:
        self.assertEqual(ocr_service.parse_page_range("2-99", 4), (2, 4))

    def test_invalid_ranges_rejected(self) -> None:
        for raw in ("abc", "0", "5-2", "12", "-3"):
            with self.assertRaises(ValueError):
                ocr_service.parse_page_range(raw, 4)

    def test_range_beyond_max_pages_rejected(self) -> None:
        with patch.object(ocr_service, "MAX_PAGES", 2):
            with self.assertRaises(ValueError):
                ocr_service.parse_page_range("1-4", 10)

    def test_range_at_the_page_limit_is_allowed(self) -> None:
        self.assertEqual(
            ocr_service.parse_page_range(f"1-{ocr_service.MAX_PAGES}", 999),
            (1, ocr_service.MAX_PAGES),
        )


class LanguageResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        ocr_service.reset_language_cache()
        self.addCleanup(ocr_service.reset_language_cache)

    def test_explicit_language_must_be_installed(self) -> None:
        with patch.object(ocr_service, "available_languages", return_value=["eng", "osd"]):
            self.assertEqual(ocr_service.resolve_language("eng", Path("x.png")), "eng")
            with self.assertRaises(ValueError) as ctx:
                ocr_service.resolve_language("tur", Path("x.png"))
        self.assertIn("tur", str(ctx.exception))

    def test_auto_prefers_the_script_model_for_the_detected_script(self) -> None:
        with (
            patch.object(
                ocr_service,
                "available_languages",
                return_value=["eng", "osd", "script/Cyrillic", "rus"],
            ),
            patch.object(ocr_service, "detect_script", return_value="Cyrillic"),
        ):
            self.assertEqual(
                ocr_service.resolve_language(ocr_service.AUTO_LANGUAGE, Path("x.png")),
                "script/Cyrillic",
            )

    def test_auto_falls_back_to_a_single_language_when_no_script_model(self) -> None:
        with (
            patch.object(ocr_service, "available_languages", return_value=["eng", "osd", "jpn"]),
            patch.object(ocr_service, "detect_script", return_value="Japanese"),
        ):
            self.assertEqual(
                ocr_service.resolve_language(ocr_service.AUTO_LANGUAGE, Path("x.png")),
                "jpn",
            )

    def test_auto_falls_back_to_english_when_detection_fails(self) -> None:
        with (
            patch.object(ocr_service, "available_languages", return_value=["eng", "tur", "osd"]),
            patch.object(ocr_service, "detect_script", return_value=None),
        ):
            self.assertEqual(
                ocr_service.resolve_language(ocr_service.AUTO_LANGUAGE, Path("x.png")),
                "eng",
            )

    def test_auto_uses_any_installed_model_when_english_is_absent(self) -> None:
        with (
            patch.object(ocr_service, "available_languages", return_value=["osd", "tur"]),
            patch.object(ocr_service, "detect_script", return_value=None),
        ):
            self.assertEqual(
                ocr_service.resolve_language(ocr_service.AUTO_LANGUAGE, Path("x.png")),
                "tur",
            )

    def test_no_language_data_raises(self) -> None:
        with (
            patch.object(ocr_service, "available_languages", return_value=["osd"]),
            patch.object(ocr_service, "detect_script", return_value=None),
        ):
            with self.assertRaises(ValueError):
                ocr_service.resolve_language(ocr_service.AUTO_LANGUAGE, Path("x.png"))

    def test_detect_script_parses_the_osd_report(self) -> None:
        osd = (
            b"Page number: 0\nOrientation in degrees: 0\nScript: Cyrillic\nScript confidence: 3.1\n"
        )
        with (
            patch.object(ocr_service, "available_languages", return_value=["osd", "eng"]),
            patch.object(ocr_service, "_resolve_binary", return_value="/usr/bin/tesseract"),
            patch.object(ocr_service, "_run", return_value=_completed(stdout=osd)),
        ):
            self.assertEqual(ocr_service.detect_script(Path("x.png")), "Cyrillic")

    def test_detect_script_returns_none_without_osd_data(self) -> None:
        with patch.object(ocr_service, "available_languages", return_value=["eng"]):
            self.assertIsNone(ocr_service.detect_script(Path("x.png")))

    def test_available_languages_parses_and_caches(self) -> None:
        stdout = b"List of available languages (3):\neng\nosd\ntur\n"
        with (
            patch.object(ocr_service, "_resolve_binary", return_value="/usr/bin/tesseract"),
            patch.object(ocr_service, "_run", return_value=_completed(stdout=stdout)) as run,
        ):
            self.assertEqual(ocr_service.available_languages(), ["eng", "osd", "tur"])
            self.assertEqual(ocr_service.available_languages(), ["eng", "osd", "tur"])
            self.assertEqual(run.call_count, 1)


class MissingBinaryTests(unittest.TestCase):
    def test_missing_tesseract_explains_how_to_install_it(self) -> None:
        with patch.object(ocr_service.shutil, "which", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                ocr_service._resolve_binary("tesseract", "tesseract-ocr")
        self.assertIn("tesseract-ocr", str(ctx.exception))

    def test_timeout_is_reported_as_a_value_error(self) -> None:
        with patch.object(
            ocr_service.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="tesseract", timeout=5),
        ):
            with self.assertRaises(ValueError) as ctx:
                ocr_service._run(["/usr/bin/tesseract"], timeout=5)
        self.assertIn("timed out", str(ctx.exception))


class ImageToTextTests(unittest.TestCase):
    def setUp(self) -> None:
        ocr_service.reset_language_cache()
        self.addCleanup(ocr_service.reset_language_cache)

    def test_recognized_text_is_trimmed_and_reported(self) -> None:
        with (
            patch.object(ocr_service, "resolve_language", return_value="tur"),
            patch.object(ocr_service, "_recognize", return_value="  Merhaba Dünya \n") as rec,
        ):
            result = ocr_service.image_to_text(b"\x89PNG fake", filename="scan.png", language="tur")

        self.assertEqual(result.text, "Merhaba Dünya")
        self.assertEqual(result.language, "tur")
        self.assertEqual(result.encoding, "utf-8")
        self.assertEqual(result.page_count, 1)
        self.assertEqual(rec.call_args.args[1], "tur")

    def test_empty_image_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ocr_service.image_to_text(b"")

    def test_tesseract_failure_surfaces_stderr(self) -> None:
        with (
            patch.object(ocr_service, "resolve_language", return_value="eng"),
            patch.object(ocr_service, "_resolve_binary", return_value="/usr/bin/tesseract"),
            patch.object(
                ocr_service,
                "_run",
                return_value=_completed(stderr=b"Error in pixReadStream", returncode=1),
            ),
        ):
            with self.assertRaises(ValueError) as ctx:
                ocr_service.image_to_text(b"not an image")
        self.assertIn("pixReadStream", str(ctx.exception))


class PdfToTextTests(unittest.TestCase):
    def setUp(self) -> None:
        ocr_service.reset_language_cache()
        self.addCleanup(ocr_service.reset_language_cache)

    @staticmethod
    def _pdf_bytes(pages: int) -> bytes:
        from pypdf import PdfWriter

        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=200, height=200)
        buffer = __import__("io").BytesIO()
        writer.write(buffer)
        return buffer.getvalue()

    def test_every_page_is_ocred_and_joined(self) -> None:
        texts = iter(["page one", "page two", "page three"])

        def fake_render(_pdf, out_dir, *, dpi, first, last):
            paths = []
            for index in range(first, last + 1):
                path = out_dir / f"page-{index}.png"
                path.write_bytes(b"png")
                paths.append(path)
            return paths

        with (
            patch.object(ocr_service, "resolve_language", return_value="eng"),
            patch.object(ocr_service, "_render_pdf_pages", side_effect=fake_render),
            patch.object(ocr_service, "_recognize", side_effect=lambda *_a, **_k: next(texts)),
        ):
            result = ocr_service.pdf_to_text(self._pdf_bytes(3))

        self.assertEqual(result.text, "page one\n\npage two\n\npage three")
        self.assertEqual([p.page for p in result.pages], [1, 2, 3])
        self.assertEqual(result.page_count, 3)

    def test_page_range_limits_rendering_and_numbering(self) -> None:
        captured: dict = {}

        def fake_render(_pdf, out_dir, *, dpi, first, last):
            captured.update({"dpi": dpi, "first": first, "last": last})
            path = out_dir / "page-2.png"
            path.write_bytes(b"png")
            return [path]

        with (
            patch.object(ocr_service, "resolve_language", return_value="eng"),
            patch.object(ocr_service, "_render_pdf_pages", side_effect=fake_render),
            patch.object(ocr_service, "_recognize", return_value="second"),
        ):
            result = ocr_service.pdf_to_text(self._pdf_bytes(4), page_range="2", dpi=150)

        self.assertEqual(captured, {"dpi": 150, "first": 2, "last": 2})
        self.assertEqual([p.page for p in result.pages], [2])
        self.assertEqual(result.text, "second")

    def test_language_is_detected_once_for_the_whole_document(self) -> None:
        def fake_render(_pdf, out_dir, *, dpi, first, last):
            paths = []
            for index in range(first, last + 1):
                path = out_dir / f"page-{index}.png"
                path.write_bytes(b"png")
                paths.append(path)
            return paths

        with (
            patch.object(ocr_service, "resolve_language", return_value="tur") as resolve,
            patch.object(ocr_service, "_render_pdf_pages", side_effect=fake_render),
            patch.object(ocr_service, "_recognize", return_value="metin"),
        ):
            result = ocr_service.pdf_to_text(self._pdf_bytes(3), language="auto")

        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(result.language, "tur")

    def test_unreadable_pdf_raises(self) -> None:
        with self.assertRaises(ValueError):
            ocr_service.pdf_to_text(b"%PDF-1.4 truncated garbage")

    def test_empty_pdf_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ocr_service.pdf_to_text(b"")


if __name__ == "__main__":
    unittest.main()
