"""Tesseract-backed OCR used by the converter node (image/PDF -> text).

Two external binaries do the work: ``tesseract`` for recognition and poppler's
``pdftoppm`` to rasterize PDF pages. Both ship with every way of running Heym
(run.sh, docker-compose, and the single release image), so they are treated as
part of the platform rather than something an operator configures. The limits
below are fixed for the same reason.

Language handling has three levels:

* an explicit spec such as ``tur`` or ``eng+tur`` is validated against the
  languages Tesseract actually has installed;
* ``auto`` runs Tesseract's orientation-and-script detection first and picks the
  best installed model for the detected script (script models such as ``Latin``
  cover every language written in that script);
* anything undetectable falls back to ``eng``.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

TESSERACT_CMD = "tesseract"
PDFTOPPM_CMD = "pdftoppm"

# Fixed operational limits. OCR is CPU bound and runs on the executor's worker
# threads, so these caps protect the whole workflow engine, not just this node.
TIMEOUT_SECONDS = 120
MAX_PAGES = 50
MAX_DPI = 600

AUTO_LANGUAGE = "auto"
DEFAULT_LANGUAGE = "eng"
DEFAULT_ENCODING = "utf-8"
DEFAULT_PSM = "3"
DEFAULT_PDF_DPI = 300
MIN_PDF_DPI = 72

# Tesseract always writes UTF-8. The configured encoding is the charset the
# extracted text is normalized to, so downstream systems that cannot handle the
# full Unicode range still receive text they can store.
SUPPORTED_ENCODINGS: tuple[str, ...] = (
    "utf-8",
    "utf-8-sig",
    "utf-16",
    "latin-1",
    "cp1252",
    "cp1254",
    "iso-8859-9",
    "ascii",
)

# Page segmentation modes worth exposing; the rest are diagnostic-only.
SUPPORTED_PSM: tuple[str, ...] = ("1", "3", "4", "6", "7", "11", "12", "13")

# Preferred models per detected script, best first. Script models (``script/Latin``)
# read every language of that script, so they beat a single-language guess.
_SCRIPT_LANGUAGE_PREFERENCE: dict[str, tuple[str, ...]] = {
    "Latin": ("script/Latin", "Latin", "eng"),
    "Fraktur": ("script/Fraktur", "Fraktur", "script/Latin", "Latin", "deu"),
    "Cyrillic": ("script/Cyrillic", "Cyrillic", "rus"),
    "Greek": ("script/Greek", "Greek", "ell"),
    "Arabic": ("script/Arabic", "Arabic", "ara"),
    "Hebrew": ("script/Hebrew", "Hebrew", "heb"),
    "Devanagari": ("script/Devanagari", "Devanagari", "hin"),
    "Han": ("script/HanS", "HanS", "chi_sim"),
    "HanS": ("script/HanS", "HanS", "chi_sim"),
    "HanT": ("script/HanT", "HanT", "chi_tra"),
    "Japanese": ("script/Japanese", "Japanese", "jpn"),
    "Korean": ("script/Hangul", "Hangul", "kor"),
    "Hangul": ("script/Hangul", "Hangul", "kor"),
    "Thai": ("script/Thai", "Thai", "tha"),
    "Vietnamese": ("script/Vietnamese", "Vietnamese", "vie"),
}

_LANGUAGE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?$")
_MAX_LANGUAGE_TOKENS = 8
_PAGE_RANGE_RE = re.compile(r"^(\d+)(?:\s*-\s*(\d+))?$")
_SCRIPT_LINE_RE = re.compile(r"^Script:\s*(?P<script>.+?)\s*$", re.MULTILINE)

_language_cache: list[str] | None = None


@dataclass
class OcrPage:
    """Text recognized on a single rasterized page."""

    page: int
    text: str


@dataclass
class OcrResult:
    """Outcome of one OCR run over an image or a PDF."""

    text: str
    language: str
    encoding: str
    pages: list[OcrPage] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def reset_language_cache() -> None:
    """Forget the cached ``tesseract --list-langs`` result (used by tests)."""
    global _language_cache
    _language_cache = None


def _resolve_binary(command: str, install_hint: str) -> str:
    """Return an executable path for ``command`` or explain how to install it."""
    candidate = (command or "").strip()
    if not candidate:
        raise ValueError(f"OCR: no command configured for {install_hint}")
    resolved = shutil.which(candidate)
    if resolved:
        return resolved
    path = Path(candidate)
    if path.is_absolute() and path.exists():
        return str(path)
    raise ValueError(
        f"OCR: '{candidate}' was not found on PATH. It ships with Heym, so a missing binary "
        f"means the backend is running outside a standard install. Install {install_hint} on "
        "the host to restore it."
    )


def _run(cmd: list[str], *, timeout: int) -> subprocess.CompletedProcess[bytes]:
    """Run an OCR helper binary, converting failures into ValueError."""
    try:
        return subprocess.run(cmd, capture_output=True, timeout=max(1, timeout), check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"OCR: '{Path(cmd[0]).name}' timed out after {timeout}s") from exc
    except OSError as exc:
        raise ValueError(f"OCR: failed to start '{Path(cmd[0]).name}': {exc}") from exc


def _stderr_text(completed: subprocess.CompletedProcess[bytes]) -> str:
    return (completed.stderr or b"").decode("utf-8", errors="replace").strip()


def available_languages() -> list[str]:
    """Return the language/script models Tesseract has installed."""
    global _language_cache
    if _language_cache is not None:
        return list(_language_cache)

    binary = _resolve_binary(TESSERACT_CMD, "tesseract-ocr")
    completed = _run([binary, "--list-langs"], timeout=TIMEOUT_SECONDS)
    if completed.returncode != 0:
        raise ValueError(f"OCR: could not list Tesseract languages: {_stderr_text(completed)}")

    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    langs = [
        line.strip()
        for line in stdout.splitlines()
        if line.strip() and not line.strip().lower().startswith("list of available")
    ]
    _language_cache = langs
    return list(langs)


def parse_language_spec(raw: object) -> str:
    """Validate a user-supplied language spec (``auto``, ``tur``, ``eng+tur``)."""
    text = str(raw).strip() if raw not in (None, "") else AUTO_LANGUAGE
    if not text or text.lower() == AUTO_LANGUAGE:
        return AUTO_LANGUAGE

    tokens = [token.strip() for token in text.split("+") if token.strip()]
    if not tokens:
        return AUTO_LANGUAGE
    if len(tokens) > _MAX_LANGUAGE_TOKENS:
        raise ValueError(
            f"OCR: at most {_MAX_LANGUAGE_TOKENS} languages can be combined, got {len(tokens)}"
        )
    for token in tokens:
        if not _LANGUAGE_TOKEN_RE.match(token):
            raise ValueError(f"OCR: invalid language code '{token}'")
    return "+".join(tokens)


def _require_installed(spec: str) -> str:
    """Fail with an actionable message when a requested model is not installed."""
    installed = available_languages()
    missing = [token for token in spec.split("+") if token not in installed]
    if missing:
        raise ValueError(
            f"OCR: language data for {', '.join(missing)} is not installed. "
            f"Available: {', '.join(installed) or 'none'}"
        )
    return spec


def detect_script(image_path: Path) -> str | None:
    """Return the script Tesseract's OSD pass detected, or None."""
    installed = available_languages()
    if "osd" not in installed:
        return None
    binary = _resolve_binary(TESSERACT_CMD, "tesseract-ocr")
    completed = _run(
        [binary, str(image_path), "stdout", "--psm", "0", "-l", "osd"],
        timeout=TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        return None
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    match = _SCRIPT_LINE_RE.search(stdout)
    return match.group("script") if match else None


def resolve_language(spec: str, image_path: Path) -> str:
    """Turn a validated spec into a concrete Tesseract ``-l`` value."""
    if spec != AUTO_LANGUAGE:
        return _require_installed(spec)

    installed = available_languages()
    script = detect_script(image_path)
    for candidate in _SCRIPT_LANGUAGE_PREFERENCE.get(script or "", ()):
        if candidate in installed:
            return candidate
    if DEFAULT_LANGUAGE in installed:
        return DEFAULT_LANGUAGE
    usable = [lang for lang in installed if lang != "osd"]
    if usable:
        return usable[0]
    raise ValueError("OCR: no Tesseract language data is installed")


def normalize_encoding(raw: object) -> str:
    """Validate the requested output charset against the supported list."""
    text = str(raw).strip().lower() if raw not in (None, "") else DEFAULT_ENCODING
    if not text:
        return DEFAULT_ENCODING
    text = text.replace("_", "-")
    aliases = {"utf8": "utf-8", "utf-8-bom": "utf-8-sig", "utf8-sig": "utf-8-sig"}
    text = aliases.get(text, text)
    if text not in SUPPORTED_ENCODINGS:
        raise ValueError(
            f"OCR: unsupported encoding '{text}'. Supported: {', '.join(SUPPORTED_ENCODINGS)}"
        )
    return text


def normalize_psm(raw: object) -> str:
    """Validate the page segmentation mode."""
    text = str(raw).strip() if raw not in (None, "") else DEFAULT_PSM
    if not text:
        return DEFAULT_PSM
    if text not in SUPPORTED_PSM:
        raise ValueError(
            f"OCR: unsupported page segmentation mode '{text}'. "
            f"Supported: {', '.join(SUPPORTED_PSM)}"
        )
    return text


def normalize_dpi(raw: object) -> int:
    """Clamp the PDF rasterization DPI into a sane range."""
    try:
        dpi = int(str(raw).strip()) if raw not in (None, "") else DEFAULT_PDF_DPI
    except (TypeError, ValueError):
        dpi = DEFAULT_PDF_DPI
    return max(MIN_PDF_DPI, min(MAX_DPI, dpi))


def parse_page_range(raw: object, total_pages: int) -> tuple[int, int]:
    """Resolve a ``"2"`` / ``"2-5"`` page range into inclusive 1-based bounds."""
    if total_pages <= 0:
        raise ValueError("OCR: the PDF has no pages")

    text = str(raw).strip() if raw not in (None, "") else ""
    if not text:
        first, last = 1, total_pages
    else:
        match = _PAGE_RANGE_RE.match(text)
        if not match:
            raise ValueError(f"OCR: invalid page range '{text}'. Use '3' or '2-5'.")
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) else first
        if first < 1 or last < first:
            raise ValueError(f"OCR: invalid page range '{text}'. Use '3' or '2-5'.")
        if first > total_pages:
            raise ValueError(f"OCR: page range '{text}' starts past the last page ({total_pages})")
        last = min(last, total_pages)

    max_pages = max(1, MAX_PAGES)
    if last - first + 1 > max_pages:
        raise ValueError(
            f"OCR: page range covers {last - first + 1} pages, the limit is {max_pages}. "
            "Narrow the range, or split the document across several runs."
        )
    return first, last


def apply_encoding(text: str, encoding: str, *, normalize_unicode: bool) -> str:
    """Normalize recognized text and make it safe for the target charset."""
    if normalize_unicode:
        text = unicodedata.normalize("NFC", text)
    if encoding in ("utf-8", "utf-8-sig", "utf-16"):
        return text
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _recognize(image_path: Path, language: str, psm: str) -> str:
    """Run one Tesseract recognition pass and return its UTF-8 output."""
    binary = _resolve_binary(TESSERACT_CMD, "tesseract-ocr")
    completed = _run(
        [binary, str(image_path), "stdout", "-l", language, "--psm", psm],
        timeout=TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise ValueError(f"OCR: tesseract failed: {_stderr_text(completed) or 'unknown error'}")
    return (completed.stdout or b"").decode("utf-8", errors="replace")


def _render_pdf_pages(
    pdf_path: Path, out_dir: Path, *, dpi: int, first: int, last: int
) -> list[Path]:
    """Rasterize a PDF page range to PNG files via poppler's pdftoppm."""
    binary = _resolve_binary(PDFTOPPM_CMD, "poppler-utils")
    prefix = out_dir / "page"
    completed = _run(
        [
            binary,
            "-r",
            str(dpi),
            "-f",
            str(first),
            "-l",
            str(last),
            "-png",
            str(pdf_path),
            str(prefix),
        ],
        timeout=TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise ValueError(f"OCR: pdftoppm failed: {_stderr_text(completed) or 'unknown error'}")

    rendered = sorted(out_dir.glob("page*.png"))
    if not rendered:
        raise ValueError("OCR: pdftoppm produced no page images")
    return rendered


def image_to_text(
    image_bytes: bytes,
    *,
    filename: str = "image",
    language: str = AUTO_LANGUAGE,
    encoding: str = DEFAULT_ENCODING,
    psm: str = DEFAULT_PSM,
    normalize_unicode: bool = True,
) -> OcrResult:
    """Recognize the text in a single image."""
    if not image_bytes:
        raise ValueError("OCR: the image is empty")

    suffix = Path(filename).suffix or ".png"
    with tempfile.TemporaryDirectory(prefix="heym-ocr-") as tmp:
        image_path = Path(tmp) / f"input{suffix}"
        image_path.write_bytes(image_bytes)

        resolved_language = resolve_language(language, image_path)
        raw_text = _recognize(image_path, resolved_language, psm)

    text = apply_encoding(raw_text.strip(), encoding, normalize_unicode=normalize_unicode)
    return OcrResult(
        text=text,
        language=resolved_language,
        encoding=encoding,
        pages=[OcrPage(page=1, text=text)],
    )


def pdf_to_text(
    pdf_bytes: bytes,
    *,
    language: str = AUTO_LANGUAGE,
    encoding: str = DEFAULT_ENCODING,
    psm: str = DEFAULT_PSM,
    dpi: int = DEFAULT_PDF_DPI,
    page_range: object = "",
    normalize_unicode: bool = True,
) -> OcrResult:
    """Rasterize every selected PDF page and recognize its text.

    Every page goes through Tesseract; an embedded text layer is ignored on
    purpose so scanned and digital PDFs behave identically.
    """
    if not pdf_bytes:
        raise ValueError("OCR: the PDF is empty")

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        total_pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except (PdfReadError, ValueError, OSError) as exc:
        raise ValueError(f"OCR: could not read the PDF: {exc}") from exc

    first, last = parse_page_range(page_range, total_pages)

    pages: list[OcrPage] = []
    resolved_language = ""
    with tempfile.TemporaryDirectory(prefix="heym-ocr-") as tmp:
        tmp_dir = Path(tmp)
        pdf_path = tmp_dir / "input.pdf"
        pdf_path.write_bytes(pdf_bytes)
        render_dir = tmp_dir / "pages"
        render_dir.mkdir()

        rendered = _render_pdf_pages(pdf_path, render_dir, dpi=dpi, first=first, last=last)
        for offset, image_path in enumerate(rendered):
            if not resolved_language:
                resolved_language = resolve_language(language, image_path)
            raw_text = _recognize(image_path, resolved_language, psm)
            pages.append(
                OcrPage(
                    page=first + offset,
                    text=apply_encoding(
                        raw_text.strip(), encoding, normalize_unicode=normalize_unicode
                    ),
                )
            )

    text = "\n\n".join(page.text for page in pages if page.text).strip()
    return OcrResult(
        text=text,
        language=resolved_language or DEFAULT_LANGUAGE,
        encoding=encoding,
        pages=pages,
    )
