import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.services import ocr_service
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import converter_node

_FILE_UUID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_NEW_FILE_UUID = uuid.UUID("22222222-3333-4444-5555-666666666666")
_OWNER_UUID = uuid.UUID("99999999-8888-7777-6666-555555555555")
_WORKFLOW_UUID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


class _FakeSession:
    """Stand-in for the executor's synchronous SQLAlchemy session."""

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def commit(self) -> None:
        pass


def _ctx(node_data: dict, source_value: object) -> NodeExecutionContext:
    # The handler resolves `source` via the executor; the stub returns the
    # provided value regardless of the template, and also serves as the
    # first-visible-input fallback when `source` is empty.
    executor = SimpleNamespace(
        resolve_expression=lambda _expr, *_a, **_k: source_value,
        _first_visible_input=lambda _inputs: source_value,
        evaluate_message_template=lambda expr, *_a, **_k: expr.replace("$pages", "2-4"),
    )
    return NodeExecutionContext(
        executor=executor,
        node_id="conv_1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "conv_1"},
        node_type="converter",
        node_data=node_data,
        node_label="conv1",
    )


class CsvToJsonTests(unittest.TestCase):
    def test_header_rows_become_dicts(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "source": "$in"}, "name,age\nAda,36\nGrace,45")
        )

        self.assertEqual(output["conversion"], "csvToJson")
        self.assertEqual(
            output["result"],
            [{"name": "Ada", "age": "36"}, {"name": "Grace", "age": "45"}],
        )

    def test_without_header_returns_lists(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "hasHeader": False}, "Ada,36\nGrace,45")
        )

        self.assertEqual(output["result"], [["Ada", "36"], ["Grace", "45"]])

    def test_quoted_field_with_delimiter(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson"}, 'name,note\n"Smith, Jr.",hi')
        )

        self.assertEqual(output["result"], [{"name": "Smith, Jr.", "note": "hi"}])

    def test_quoted_field_with_embedded_newline(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson"}, 'name,note\nAda,"line1\nline2"')
        )

        self.assertEqual(output["result"], [{"name": "Ada", "note": "line1\nline2"}])

    def test_custom_delimiter(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "delimiter": ";"}, "name;age\nAda;36")
        )

        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_ragged_row_fills_missing_with_empty_string(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "name,age\nAda"))

        self.assertEqual(output["result"], [{"name": "Ada", "age": ""}])

    def test_empty_input_returns_empty_list(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, ""))

        self.assertEqual(output["result"], [])

    def test_csv_to_json_is_the_default_conversion(self) -> None:
        output = converter_node.execute(_ctx({}, "name\nAda"))

        self.assertEqual(output["conversion"], "csvToJson")
        self.assertEqual(output["result"], [{"name": "Ada"}])

    def test_leading_utf8_bom_is_stripped(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "\ufeffname,age\nAda,36"))

        # The first key is "name", not the BOM-prefixed variant.
        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_duplicate_headers_are_made_unique(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "a,a\n1,2"))

        self.assertEqual(output["result"], [{"a": "1", "a_2": "2"}])

    def test_dedupe_does_not_collide_with_existing_column(self) -> None:
        # The generated suffix must skip a real "a_2" column so no value is lost.
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "a,a,a_2\n1,2,3"))

        self.assertEqual(output["result"], [{"a": "1", "a_3": "2", "a_2": "3"}])

    def test_tab_delimiter_via_escape(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "delimiter": "\\t"}, "name\tage\nAda\t36")
        )

        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_trim_values_default_strips_whitespace(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "csvToJson"}, "name, age\nAda , 36"))

        # Header keys and cell values are trimmed by default.
        self.assertEqual(output["result"], [{"name": "Ada", "age": "36"}])

    def test_trim_values_false_keeps_whitespace(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "csvToJson", "trimValues": False}, "name, age\nAda , 36")
        )

        self.assertEqual(output["result"], [{"name": "Ada ", " age": " 36"}])


class JsonToCsvTests(unittest.TestCase):
    def test_dicts_become_csv_with_header(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv"},
                [{"name": "Ada", "age": 36}, {"name": "Grace", "age": 45}],
            )
        )

        self.assertEqual(output["result"], "name,age\nAda,36\nGrace,45")

    def test_include_header_false_omits_header(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv", "includeHeader": False},
                [{"name": "Ada", "age": 36}],
            )
        )

        self.assertEqual(output["result"], "Ada,36")

    def test_explicit_column_order(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv", "converterColumns": "age, name"},
                [{"name": "Ada", "age": 36}],
            )
        )

        self.assertEqual(output["result"], "age,name\n36,Ada")

    def test_values_needing_quotes_are_escaped(self) -> None:
        output = converter_node.execute(
            _ctx(
                {"conversion": "jsonToCsv"},
                [{"note": 'He said "hi", loudly'}],
            )
        )

        self.assertEqual(output["result"], 'note\n"He said ""hi"", loudly"')

    def test_list_of_lists(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, [["a", "b"], ["c", "d"]]))

        self.assertEqual(output["result"], "a,b\nc,d")

    def test_json_string_input_is_parsed(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, '[{"name": "Ada"}]'))

        self.assertEqual(output["result"], "name\nAda")

    def test_single_dict_becomes_one_row(self) -> None:
        output = converter_node.execute(
            _ctx({"conversion": "jsonToCsv"}, {"name": "Ada", "age": 36})
        )

        self.assertEqual(output["result"], "name,age\nAda,36")

    def test_empty_list_returns_empty_string(self) -> None:
        output = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, []))

        self.assertEqual(output["result"], "")


class ConverterRoundTripTests(unittest.TestCase):
    def test_build_then_parse_round_trip(self) -> None:
        rows = [{"name": "Ada", "age": "36"}, {"name": "Grace", "age": "45"}]

        csv_out = converter_node.execute(_ctx({"conversion": "jsonToCsv"}, rows))
        parsed = converter_node.execute(_ctx({"conversion": "csvToJson"}, csv_out["result"]))

        self.assertEqual(parsed["result"], rows)


class FileIdExtractionTests(unittest.TestCase):
    def test_plain_uuid_string(self) -> None:
        self.assertEqual(
            converter_node._extract_file_id("  " + str(_FILE_UUID) + " "),
            _FILE_UUID,
        )

    def test_uuid_inside_a_download_url(self) -> None:
        url = f"https://heym.example.com/api/files/{_FILE_UUID}/download"
        self.assertEqual(converter_node._extract_file_id(url), _FILE_UUID)

    def test_file_object_from_the_upload_trigger(self) -> None:
        payload = {"file": {"id": str(_FILE_UUID), "name": "scan.png"}, "uploaded_at": "now"}
        self.assertEqual(converter_node._extract_file_id(payload), _FILE_UUID)

    def test_drive_node_output_shape(self) -> None:
        self.assertEqual(
            converter_node._extract_file_id({"id": str(_FILE_UUID), "filename": "a.pdf"}),
            _FILE_UUID,
        )

    def test_first_item_of_a_list(self) -> None:
        self.assertEqual(
            converter_node._extract_file_id([{"id": str(_FILE_UUID)}]),
            _FILE_UUID,
        )

    def test_unusable_values_return_none(self) -> None:
        for value in (None, "", "not-a-file", 42, {}, {"file": {}}, []):
            self.assertIsNone(converter_node._extract_file_id(value))


class OcrConversionTests(unittest.TestCase):
    def _run(
        self,
        node_data: dict,
        *,
        file_bytes: bytes = b"\x89PNG\r\n",
        filename: str = "scan.png",
        source_value: object = None,
        ocr_result: object = None,
    ) -> tuple[dict, dict]:
        """Execute an OCR conversion with the DB and Tesseract stubbed out."""
        calls: dict = {}
        result = ocr_result or ocr_service.OcrResult(
            text="Merhaba",
            language="tur",
            encoding="utf-8",
            pages=[ocr_service.OcrPage(page=1, text="Merhaba")],
        )

        row = SimpleNamespace(
            id=_FILE_UUID,
            filename=filename,
            mime_type="image/png",
            size_bytes=len(file_bytes),
        )

        def fake_loader(_db, *, file_id, owner_id, context):
            calls["file_id"] = file_id
            calls["owner_id"] = owner_id
            return row, file_bytes

        def fake_image(data, **kwargs):
            calls["image"] = {"bytes": data, **kwargs}
            return result

        def fake_pdf(data, **kwargs):
            calls["pdf"] = {"bytes": data, **kwargs}
            return result

        ctx = _ctx(node_data, source_value)
        ctx.executor.trace_user_id = _OWNER_UUID

        with (
            patch("app.db.session.SessionLocal", return_value=_FakeSession()),
            patch("app.services.file_storage.load_readable_file_sync", side_effect=fake_loader),
            patch.object(ocr_service, "image_to_text", side_effect=fake_image),
            patch.object(ocr_service, "pdf_to_text", side_effect=fake_pdf),
        ):
            output = converter_node.execute(ctx)

        return output, calls

    def test_image_to_text_reads_the_referenced_file(self) -> None:
        output, calls = self._run(
            {
                "conversion": "imageToText",
                "converterFileId": "$Upload.file.id",
                "ocrLanguage": "tur",
            },
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["file_id"], _FILE_UUID)
        self.assertEqual(calls["owner_id"], _OWNER_UUID)
        self.assertEqual(calls["image"]["language"], "tur")
        self.assertEqual(output["conversion"], "imageToText")
        self.assertEqual(output["result"], "Merhaba")
        self.assertEqual(output["language"], "tur")
        self.assertEqual(output["encoding"], "utf-8")
        self.assertEqual(output["page_count"], 1)
        self.assertEqual(output["pages"], [{"page": 1, "text": "Merhaba"}])
        self.assertEqual(output["file"]["filename"], "scan.png")

    def test_language_defaults_to_auto(self) -> None:
        _, calls = self._run(
            {"conversion": "imageToText"},
            source_value={"file": {"id": str(_FILE_UUID)}},
        )

        self.assertEqual(calls["image"]["language"], "auto")
        self.assertEqual(calls["image"]["encoding"], "utf-8")
        self.assertEqual(calls["image"]["psm"], "3")
        self.assertTrue(calls["image"]["normalize_unicode"])

    def test_custom_language_option_uses_the_free_text_codes(self) -> None:
        _, calls = self._run(
            {
                "conversion": "imageToText",
                "ocrLanguage": "custom",
                "ocrLanguageCustom": "eng+tur",
            },
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["image"]["language"], "eng+tur")

    def test_custom_language_without_codes_falls_back_to_auto(self) -> None:
        _, calls = self._run(
            {"conversion": "imageToText", "ocrLanguage": "custom", "ocrLanguageCustom": "  "},
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["image"]["language"], "auto")

    def test_encoding_and_normalization_options_are_forwarded(self) -> None:
        _, calls = self._run(
            {
                "conversion": "imageToText",
                "ocrEncoding": "cp1254",
                "ocrPsm": "6",
                "ocrNormalizeUnicode": False,
            },
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["image"]["encoding"], "cp1254")
        self.assertEqual(calls["image"]["psm"], "6")
        self.assertFalse(calls["image"]["normalize_unicode"])

    def test_pdf_to_text_forwards_dpi_and_page_range(self) -> None:
        output, calls = self._run(
            {"conversion": "pdfToText", "ocrDpi": "150", "ocrPageRange": "2-3"},
            file_bytes=b"%PDF-1.7\n...",
            filename="invoice.pdf",
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["pdf"]["dpi"], 150)
        self.assertEqual(calls["pdf"]["page_range"], "2-3")
        self.assertEqual(output["conversion"], "pdfToText")

    def test_page_range_expression_is_evaluated(self) -> None:
        _, calls = self._run(
            {"conversion": "pdfToText", "ocrPageRange": "$pages"},
            file_bytes=b"%PDF-1.7\n",
            filename="doc.pdf",
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["pdf"]["page_range"], "2-4")

    def test_pdf_conversion_rejects_a_non_pdf_file(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(
                {"conversion": "pdfToText"},
                file_bytes=b"\x89PNG\r\n",
                source_value=str(_FILE_UUID),
            )
        self.assertIn("not a PDF", str(ctx.exception))

    def test_image_conversion_rejects_a_pdf_file(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(
                {"conversion": "imageToText"},
                file_bytes=b"%PDF-1.7\n",
                filename="doc.pdf",
                source_value=str(_FILE_UUID),
            )
        self.assertIn("pdfToText", str(ctx.exception))

    def test_missing_file_reference_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run({"conversion": "imageToText"}, source_value="no file here")
        self.assertIn("Heym file is required", str(ctx.exception))

    def test_missing_owner_context_raises(self) -> None:
        ctx = _ctx({"conversion": "imageToText"}, str(_FILE_UUID))
        ctx.executor.trace_user_id = None

        with self.assertRaises(ValueError) as raised:
            converter_node.execute(ctx)
        self.assertIn("owner context", str(raised.exception))

    def test_invalid_language_is_rejected_before_any_file_read(self) -> None:
        with self.assertRaises(ValueError):
            self._run(
                {"conversion": "imageToText", "ocrLanguage": "tur; rm -rf /"},
                source_value=str(_FILE_UUID),
            )


class FileConvertTests(unittest.TestCase):
    def _run(
        self,
        node_data: dict,
        *,
        src_bytes: bytes = b"# hello",
        src_mime: str = "text/markdown",
        filename: str = "doc.md",
        source_value: object = None,
    ) -> tuple[dict, dict]:
        """Execute a fileConvert with the DB and the conversion engines stubbed out."""
        from app.services import file_conversion_service

        calls: dict = {}
        src_row = SimpleNamespace(
            id=_FILE_UUID,
            filename=filename,
            mime_type=src_mime,
            size_bytes=len(src_bytes),
        )
        new_row = SimpleNamespace(id=_NEW_FILE_UUID)

        def fake_loader(_db, *, file_id, owner_id, context):
            calls["file_id"] = file_id
            calls["owner_id"] = owner_id
            return src_row, src_bytes

        def fake_convert(**kwargs):
            calls["convert"] = kwargs
            return file_conversion_service.ConvertedFile(
                content=b"<h1>hello</h1>",
                filename="doc.html",
                mime_type="text/html",
            )

        def fake_store(_db, **kwargs):
            calls["store"] = kwargs
            return new_row, "tok_abc"

        ctx = _ctx(node_data, source_value)
        ctx.executor.trace_user_id = _OWNER_UUID
        ctx.executor.workflow_id = _WORKFLOW_UUID
        ctx.executor._base_url = "https://heym.example.com"

        with (
            patch("app.db.session.SessionLocal", return_value=_FakeSession()),
            patch("app.services.file_storage.load_readable_file_sync", side_effect=fake_loader),
            patch("app.services.file_storage.store_file_sync", side_effect=fake_store),
            patch.object(file_conversion_service, "convert_file", side_effect=fake_convert),
        ):
            output = converter_node.execute(ctx)

        return output, calls

    def test_converts_and_stores_a_new_file(self) -> None:
        output, calls = self._run(
            {
                "conversion": "fileConvert",
                "converterFileId": "$Upload.file.id",
                "converterTargetFormat": "html",
                "label": "toHtml",
            },
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["file_id"], _FILE_UUID)
        self.assertEqual(calls["convert"]["target_format"], "html")
        self.assertEqual(calls["convert"]["src_mime"], "text/markdown")
        self.assertEqual(calls["convert"]["src_filename"], "doc.md")

        self.assertEqual(calls["store"]["filename"], "doc.html")
        self.assertEqual(calls["store"]["mime_type"], "text/html")
        self.assertEqual(calls["store"]["owner_id"], _OWNER_UUID)
        self.assertEqual(calls["store"]["workflow_id"], _WORKFLOW_UUID)
        self.assertEqual(calls["store"]["source_node_label"], "toHtml")

        self.assertEqual(output["conversion"], "fileConvert")
        self.assertEqual(output["status"], "success")
        self.assertEqual(output["id"], str(_NEW_FILE_UUID))
        self.assertEqual(output["filename"], "doc.html")
        self.assertEqual(output["mime_type"], "text/html")
        self.assertEqual(output["size_bytes"], len(b"<h1>hello</h1>"))
        self.assertEqual(output["download_url"], "https://heym.example.com/api/files/dl/tok_abc")
        self.assertEqual(output["result"]["id"], str(_NEW_FILE_UUID))
        self.assertEqual(output["source_file"]["filename"], "doc.md")

    def test_target_format_is_normalized(self) -> None:
        _, calls = self._run(
            {"conversion": "fileConvert", "converterTargetFormat": "  HTML  "},
            source_value=str(_FILE_UUID),
        )

        self.assertEqual(calls["convert"]["target_format"], "html")

    def test_target_format_expression_is_evaluated(self) -> None:
        _, calls = self._run(
            {"conversion": "fileConvert", "converterTargetFormat": "$pages"},
            source_value=str(_FILE_UUID),
        )

        # The stub executor rewrites "$pages" to "2-4"; only the evaluation matters here.
        self.assertEqual(calls["convert"]["target_format"], "2-4")

    def test_missing_target_format_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run({"conversion": "fileConvert"}, source_value=str(_FILE_UUID))
        self.assertIn("target format is required", str(ctx.exception))

    def test_missing_file_reference_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(
                {"conversion": "fileConvert", "converterTargetFormat": "html"},
                source_value="nothing here",
            )
        self.assertIn("Heym file is required", str(ctx.exception))

    def test_missing_owner_context_raises(self) -> None:
        ctx = _ctx({"conversion": "fileConvert", "converterTargetFormat": "html"}, str(_FILE_UUID))
        ctx.executor.trace_user_id = None

        with self.assertRaises(ValueError) as raised:
            converter_node.execute(ctx)
        self.assertIn("owner context", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
