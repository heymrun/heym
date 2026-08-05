"""Convert a stored file from one format to another for the converter node.

Three engines cover the supported matrix: Pillow for image to image, pandoc for
documents, and the Python csv module for JSON to CSV (pandoc has no csv writer).
PDF and JSON inputs are flattened to text first so pandoc has something it can
read.

This used to live inside the Drive node's ``convertFile`` operation. It moved out
so the converter node owns every format conversion and the Drive node stays about
storage.
"""

from __future__ import annotations

import csv
import io
import json
import tempfile
from dataclasses import dataclass

IMAGE_FORMATS = ("jpg", "jpeg", "png", "bmp", "webp")
DOCUMENT_FORMATS = ("pdf", "docx", "html", "md", "txt", "csv", "epub")

_IMAGE_MIMES = frozenset({"image/jpeg", "image/jpg", "image/png", "image/bmp", "image/webp"})
_SPECIAL_INPUT_MIMES = frozenset({"application/pdf", "application/json"})

_PIL_FORMATS: dict[str, tuple[str, str]] = {
    "jpg": ("JPEG", "image/jpeg"),
    "jpeg": ("JPEG", "image/jpeg"),
    "png": ("PNG", "image/png"),
    "bmp": ("BMP", "image/bmp"),
    "webp": ("WEBP", "image/webp"),
}

_PANDOC_INPUT_BY_MIME: dict[str, str] = {
    "text/markdown": "markdown",
    "text/html": "html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "markdown",
    "text/csv": "csv",
}

_PANDOC_INPUT_BY_EXTENSION: dict[str, str] = {
    "md": "markdown",
    "markdown": "markdown",
    "html": "html",
    "htm": "html",
    "docx": "docx",
    "txt": "markdown",
    "csv": "csv",
}

_TARGET_EXTENSION: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "html": "html",
    "md": "md",
    "txt": "txt",
    "epub": "epub",
}

_TARGET_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html",
    "md": "text/markdown",
    "txt": "text/plain",
    "epub": "application/epub+zip",
}

_PANDOC_TARGET: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "html": "html",
    "md": "markdown",
    "txt": "plain",
    "epub": "epub",
}


@dataclass
class ConvertedFile:
    """The bytes, name, and MIME type of a freshly converted file."""

    content: bytes
    filename: str
    mime_type: str


def detect_pandoc_format(mime_type: str, filename: str) -> str | None:
    """Return the pandoc input format for a file, or None when unsupported."""
    if mime_type in _PANDOC_INPUT_BY_MIME:
        return _PANDOC_INPUT_BY_MIME[mime_type]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _PANDOC_INPUT_BY_EXTENSION.get(ext)


def convert_image(src_bytes: bytes, target_format: str) -> tuple[bytes, str]:
    """Convert image bytes to another image format. Returns (bytes, mime type)."""
    from PIL import Image

    if target_format not in _PIL_FORMATS:
        raise ValueError(f"Converter node: unsupported image output format '{target_format}'")
    pil_format, mime_type = _PIL_FORMATS[target_format]
    img = Image.open(io.BytesIO(src_bytes))
    # JPEG has no alpha channel, so transparency has to be flattened first.
    if pil_format == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format=pil_format)
    return buffer.getvalue(), mime_type


def extract_pdf_text(src_bytes: bytes) -> str:
    """Pull the embedded text layer out of a PDF via pypdf."""
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(src_bytes))
    parts = [page.extract_text() for page in reader.pages if page.extract_text()]
    return "\n\n".join(parts)


def _base_name(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _json_to_csv_bytes(src_bytes: bytes) -> bytes:
    """Write a JSON array of objects out as CSV."""
    raw = src_bytes.decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError("JSON must be an array of objects for CSV conversion")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(data[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(data)
    return buffer.getvalue().encode("utf-8")


def _convert_document(
    src_bytes: bytes,
    src_mime: str,
    src_filename: str,
    target_format: str,
) -> ConvertedFile:
    """Convert a document through pandoc, or through the csv writer for CSV output."""
    pandoc_format = detect_pandoc_format(src_mime, src_filename)
    if pandoc_format is None and src_mime not in _SPECIAL_INPUT_MIMES:
        raise ValueError(f"Converter node: unsupported input format '{src_mime}'")
    if target_format not in DOCUMENT_FORMATS:
        raise ValueError(f"Converter node: unsupported output format '{target_format}'")

    base = _base_name(src_filename)

    if target_format == "csv":
        if src_mime != "application/json":
            raise ValueError("Converter node: CSV output is only supported for JSON array input")
        try:
            content = _json_to_csv_bytes(src_bytes)
        except Exception as exc:
            raise ValueError(f"Converter node: conversion failed: {exc}") from exc
        return ConvertedFile(content=content, filename=f"{base}.csv", mime_type="text/csv")

    out_ext = _TARGET_EXTENSION[target_format]
    try:
        content = _run_pandoc(
            src_bytes, src_mime, src_filename, pandoc_format, target_format, out_ext
        )
    except Exception as exc:
        raise ValueError(f"Converter node: conversion failed: {exc}") from exc

    return ConvertedFile(
        content=content,
        filename=f"{base}.{out_ext}",
        mime_type=_TARGET_MIME[target_format],
    )


def _run_pandoc(
    src_bytes: bytes,
    src_mime: str,
    src_filename: str,
    pandoc_format: str | None,
    target_format: str,
    out_ext: str,
) -> bytes:
    """Write the source to a temp file in a shape pandoc accepts, then convert it."""
    import pypandoc

    with tempfile.TemporaryDirectory() as tmpdir:
        if src_mime == "application/pdf":
            src_path = f"{tmpdir}/input.txt"
            with open(src_path, "w", encoding="utf-8") as handle:
                handle.write(extract_pdf_text(src_bytes))
            pandoc_format = "markdown"
        elif src_mime == "application/json":
            raw = src_bytes.decode("utf-8", errors="replace")
            try:
                pretty = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
            except json.JSONDecodeError:
                pretty = raw
            src_path = f"{tmpdir}/input.md"
            with open(src_path, "w", encoding="utf-8") as handle:
                handle.write(f"```json\n{pretty}\n```\n")
            pandoc_format = "markdown"
        else:
            src_ext = src_filename.rsplit(".", 1)[-1] if "." in src_filename else "txt"
            src_path = f"{tmpdir}/input.{src_ext}"
            with open(src_path, "wb") as handle:
                handle.write(src_bytes)

        out_path = f"{tmpdir}/output.{out_ext}"
        extra_args = ["--pdf-engine=weasyprint"] if target_format == "pdf" else []
        pypandoc.convert_file(
            src_path,
            _PANDOC_TARGET[target_format],
            outputfile=out_path,
            format=pandoc_format,
            extra_args=extra_args,
        )
        with open(out_path, "rb") as handle:
            return handle.read()


def convert_file(
    *,
    src_bytes: bytes,
    src_mime: str,
    src_filename: str,
    target_format: str,
) -> ConvertedFile:
    """Convert a stored file to ``target_format``.

    Image inputs stay images and document inputs stay documents; crossing the two
    is rejected up front because neither engine can do it usefully.
    """
    target_format = (target_format or "").strip().lower()
    if not target_format:
        raise ValueError("Converter node: a target format is required")

    src_mime = src_mime or ""
    src_filename = src_filename or "file"
    is_image_input = src_mime in _IMAGE_MIMES

    if is_image_input and target_format in DOCUMENT_FORMATS:
        raise ValueError(
            f"Converter node: cannot convert an image to '{target_format}'. "
            "Choose an image output format (jpg, png, bmp, webp), or use imageToText to read it."
        )
    if not is_image_input and target_format in IMAGE_FORMATS:
        raise ValueError(
            f"Converter node: cannot convert a document to '{target_format}'. "
            "Choose a document output format (pdf, docx, html, md, txt, csv, epub)."
        )

    if is_image_input:
        try:
            content, mime_type = convert_image(src_bytes, target_format)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Converter node: conversion failed: {exc}") from exc
        normalized_ext = "jpg" if target_format in ("jpg", "jpeg") else target_format
        return ConvertedFile(
            content=content,
            filename=f"{_base_name(src_filename)}.{normalized_ext}",
            mime_type=mime_type,
        )

    return _convert_document(src_bytes, src_mime, src_filename, target_format)
