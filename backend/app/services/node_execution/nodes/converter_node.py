from __future__ import annotations

import csv
import io
import json
import re
import uuid

from app.services.node_execution.base import NodeExecutionContext

_DELIMITER_ESCAPES = {"\\t": "\t", "\\n": "\n", "\\r": "\r"}

OCR_CONVERSIONS = ("imageToText", "pdfToText")
# Conversions that read a stored Drive file instead of an expression value.
FILE_CONVERSIONS = ("imageToText", "pdfToText", "fileConvert")

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_FILE_ID_KEYS = ("id", "file_id", "fileId", "fileID")
_PDF_MAGIC = b"%PDF"
_AUTO_LANGUAGE = "auto"


def _ocr_language(node_data: dict) -> object:
    """Resolve the language select, honoring the custom-codes escape hatch."""
    selected = node_data.get("ocrLanguage", _AUTO_LANGUAGE)
    if isinstance(selected, str) and selected.strip().lower() == "custom":
        custom = node_data.get("ocrLanguageCustom", "")
        return custom if isinstance(custom, str) and custom.strip() else _AUTO_LANGUAGE
    return selected


def _resolve_delimiter(raw: object) -> str:
    """Resolve the configured delimiter, honoring escapes like ``\\t`` for tab."""
    text = str(raw) if raw not in (None, "") else ","
    text = _DELIMITER_ESCAPES.get(text, text)
    return text[:1] or ","


def _dedupe_headers(header: list[str]) -> list[str]:
    """Make duplicate header names unique (``a, a`` -> ``a, a_2``).

    A generated suffix is bumped until the candidate is free — not already used
    and not another original column name elsewhere in the header — so a real
    column such as ``a_2`` is never overwritten and no value is dropped.
    """
    originals = list(header)
    used: set[str] = set()
    result: list[str] = []
    for name in originals:
        candidate = name
        if candidate in used:
            index = 2
            candidate = f"{name}_{index}"
            while candidate in used or candidate in originals:
                index += 1
                candidate = f"{name}_{index}"
        used.add(candidate)
        result.append(candidate)
    return result


def _coerce_rows(value: object) -> list:
    """Normalize an arbitrary value into a list of rows for CSV building."""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            value = json.loads(stripped)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return list(value)
    return []


def _normalize_columns(columns_raw: object) -> list[str] | None:
    """Accept an explicit column order as a list or a comma-separated string."""
    if isinstance(columns_raw, str):
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
        return columns or None
    if isinstance(columns_raw, list):
        columns = [str(c) for c in columns_raw]
        return columns or None
    return None


def _csv_to_json(text: object, delimiter: str, has_header: bool, trim_values: bool) -> list:
    """Parse CSV text into a list of row dicts (with header) or row lists."""
    if not isinstance(text, str):
        text = str(text)
    # Strip a leading UTF-8 BOM so Excel exports don't produce a "\ufeffname" key.
    text = text.lstrip("\ufeff")
    if text.strip() == "":
        return []
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if trim_values:
        rows = [[cell.strip() for cell in row] for row in rows]
    if not rows:
        return []
    if not has_header:
        return rows
    header = _dedupe_headers(rows[0])
    return [
        {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
        for row in rows[1:]
    ]


def _json_to_csv(
    value: object, delimiter: str, include_header: bool, columns: list[str] | None
) -> str:
    """Build CSV text from a list of dicts (or lists), escaping per RFC 4180."""
    rows = _coerce_rows(value)
    buffer = io.StringIO()
    if rows and isinstance(rows[0], dict):
        if columns is not None:
            fieldnames = columns
        else:
            fieldnames = []
            for row in rows:
                if isinstance(row, dict):
                    for key in row:
                        if key not in fieldnames:
                            fieldnames.append(key)
        writer = csv.DictWriter(
            buffer,
            fieldnames=fieldnames,
            delimiter=delimiter,
            extrasaction="ignore",
            lineterminator="\n",
        )
        if include_header:
            writer.writeheader()
        for row in rows:
            source = row if isinstance(row, dict) else {}
            writer.writerow({name: source.get(name, "") for name in fieldnames})
    else:
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
        for row in rows:
            writer.writerow(row if isinstance(row, list) else [row])
    return buffer.getvalue().rstrip("\n")


def _extract_file_id(value: object, depth: int = 0) -> uuid.UUID | None:
    """Pull a Heym Drive file id out of an id string, URL, or file object.

    Upstream nodes hand the file over in several shapes: ``$Upload.file.id`` is a
    bare UUID, ``$Upload.file`` is a dict, and ``fileUploadTrigger`` output nests
    that dict under ``file``. All three resolve to the same id here.
    """
    if depth > 3 or value is None:
        return None

    if isinstance(value, uuid.UUID):
        return value

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return uuid.UUID(text)
        except ValueError:
            match = _UUID_RE.search(text)
            if not match:
                return None
            try:
                return uuid.UUID(match.group(0))
            except ValueError:
                return None

    if isinstance(value, dict):
        for key in _FILE_ID_KEYS:
            if key in value:
                found = _extract_file_id(value[key], depth + 1)
                if found is not None:
                    return found
        for key in ("file", "result", "data"):
            if key in value:
                found = _extract_file_id(value[key], depth + 1)
                if found is not None:
                    return found
        return None

    if isinstance(value, list) and value:
        return _extract_file_id(value[0], depth + 1)

    return None


def _resolve_source_file_id(ctx: NodeExecutionContext, source_value: object) -> uuid.UUID:
    """Resolve the Drive file a file-based conversion reads from."""
    self = ctx.executor
    node_data = ctx.node_data

    file_reference: object = source_value
    file_template = node_data.get("converterFileId", "")
    if isinstance(file_template, str) and file_template.strip():
        file_reference = self.resolve_expression(
            file_template.strip(), ctx.inputs, ctx.node_id, preserve_type=True
        )

    file_id = _extract_file_id(file_reference)
    if file_id is None:
        raise ValueError(
            "Converter node: a Heym file is required. Point File at a Drive file id, "
            "for example $Upload.file.id."
        )
    return file_id


def _owner_id(ctx: NodeExecutionContext) -> object:
    owner_id = getattr(ctx.executor, "trace_user_id", None)
    if not owner_id:
        raise ValueError("Converter node: no owner context available for file access")
    return owner_id


def _convert_stored_file(ctx: NodeExecutionContext, source_value: object) -> dict:
    """Convert a stored Drive file into another format and store the result."""
    from app.db.session import SessionLocal
    from app.services import file_conversion_service
    from app.services.file_storage import (
        build_download_url,
        load_readable_file_sync,
        store_file_sync,
    )

    self = ctx.executor
    node_data = ctx.node_data

    owner_id = _owner_id(ctx)
    file_id = _resolve_source_file_id(ctx, source_value)

    target_format = node_data.get("converterTargetFormat", "")
    if isinstance(target_format, str) and "$" in target_format:
        target_format = self.evaluate_message_template(target_format, ctx.inputs, ctx.node_id)
    target_format = str(target_format or "").strip().lower()
    if not target_format:
        raise ValueError("Converter node: a target format is required for fileConvert")

    with SessionLocal() as db:
        row, src_bytes = load_readable_file_sync(
            db, file_id=file_id, owner_id=owner_id, context="Converter node"
        )
        source_meta = {
            "id": str(row.id),
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
        }

        converted = file_conversion_service.convert_file(
            src_bytes=src_bytes,
            src_mime=row.mime_type or "",
            src_filename=row.filename or "",
            target_format=target_format,
        )

        new_row, token = store_file_sync(
            db,
            owner_id=owner_id,
            file_bytes=converted.content,
            filename=converted.filename,
            mime_type=converted.mime_type,
            workflow_id=getattr(self, "workflow_id", None),
            source_node_id=ctx.node_id,
            source_node_label=node_data.get("label"),
            context="Converter node",
        )
        new_id = str(new_row.id)
        db.commit()

    download_url = build_download_url(self._base_url, token)
    result = {
        "id": new_id,
        "filename": converted.filename,
        "mime_type": converted.mime_type,
        "size_bytes": len(converted.content),
        "download_url": download_url,
    }
    return {
        "result": result,
        "conversion": "fileConvert",
        "status": "success",
        "target_format": target_format,
        "source_file": source_meta,
        **result,
    }


def _ocr_to_text(ctx: NodeExecutionContext, conversion: str, source_value: object) -> dict:
    """Run Tesseract over a Drive file and return the converter output payload."""
    from app.db.session import SessionLocal
    from app.services import ocr_service
    from app.services.file_storage import load_readable_file_sync

    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    owner_id = _owner_id(ctx)
    file_id = _resolve_source_file_id(ctx, source_value)

    language = ocr_service.parse_language_spec(_ocr_language(node_data))
    encoding = ocr_service.normalize_encoding(node_data.get("ocrEncoding"))
    psm = ocr_service.normalize_psm(node_data.get("ocrPsm"))
    normalize_unicode = node_data.get("ocrNormalizeUnicode", True) is not False

    page_range = node_data.get("ocrPageRange", "")
    if isinstance(page_range, str) and "$" in page_range:
        page_range = self.evaluate_message_template(page_range, inputs, node_id)

    with SessionLocal() as db:
        row, file_bytes = load_readable_file_sync(
            db, file_id=file_id, owner_id=owner_id, context="Converter node"
        )
        file_meta = {
            "id": str(row.id),
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
        }

    is_pdf = file_bytes[:4] == _PDF_MAGIC
    if conversion == "pdfToText":
        if not is_pdf:
            raise ValueError(
                f"Converter node: '{file_meta['filename']}' is not a PDF. "
                "Use the imageToText conversion for images."
            )
        result = ocr_service.pdf_to_text(
            file_bytes,
            language=language,
            encoding=encoding,
            psm=psm,
            dpi=ocr_service.normalize_dpi(node_data.get("ocrDpi")),
            page_range=page_range,
            normalize_unicode=normalize_unicode,
        )
    else:
        if is_pdf:
            raise ValueError(
                f"Converter node: '{file_meta['filename']}' is a PDF. "
                "Use the pdfToText conversion instead."
            )
        result = ocr_service.image_to_text(
            file_bytes,
            filename=file_meta["filename"],
            language=language,
            encoding=encoding,
            psm=psm,
            normalize_unicode=normalize_unicode,
        )

    return {
        "result": result.text,
        "conversion": conversion,
        "language": result.language,
        "encoding": result.encoding,
        "page_count": result.page_count,
        "pages": [{"page": page.page, "text": page.text} for page in result.pages],
        "file": file_meta,
    }


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the converter node.

    A technology-neutral data converter. Text conversions are ``csvToJson``
    (CSV text -> list of row objects) and ``jsonToCsv`` (a list of objects/rows
    -> CSV text). File conversions read a stored Drive file: ``imageToText`` and
    ``pdfToText`` run Tesseract OCR, and ``fileConvert`` writes the file back out
    in another format. The ``conversion`` field leaves room for more formats
    later without changing the node's contract.
    """
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    conversion = node_data.get("conversion", "csvToJson")
    delimiter = _resolve_delimiter(node_data.get("delimiter"))
    source_template = node_data.get("source", "")

    if isinstance(source_template, str) and source_template.strip():
        source_value = self.resolve_expression(
            source_template.strip(), inputs, node_id, preserve_type=True
        )
    else:
        source_value = self._first_visible_input(inputs)

    if conversion in OCR_CONVERSIONS:
        return _ocr_to_text(ctx, conversion, source_value)

    if conversion == "fileConvert":
        return _convert_stored_file(ctx, source_value)

    if conversion == "jsonToCsv":
        include_header = node_data.get("includeHeader", True)
        columns = _normalize_columns(node_data.get("converterColumns"))
        result: object = _json_to_csv(source_value, delimiter, include_header, columns)
    else:
        has_header = node_data.get("hasHeader", True)
        trim_values = node_data.get("trimValues", True)
        result = _csv_to_json(source_value, delimiter, has_header, trim_values)

    return {"result": result, "conversion": conversion}
