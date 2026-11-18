"""The text of a Word (.docx) document, as a vector store reads it.

The body is read in document order: paragraphs, table rows (cells joined with " | "),
content controls and text boxes. Tracked changes read as accepted: insertions stay and
deletions go. Headers, footers, footnotes and comments are left out.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator

from docx import Document
from docx.oxml.ns import qn
from lxml.etree import _Element

from app.services.office_archive import ensure_unpacked_size

_MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"

_P = qn("w:p")
_TBL = qn("w:tbl")
_TR = qn("w:tr")
_TC = qn("w:tc")
_T = qn("w:t")
_TAB = qn("w:tab")
_NO_BREAK_HYPHEN = qn("w:noBreakHyphen")
_TXBX_CONTENT = qn("w:txbxContent")
_LINE_BREAKS = frozenset({qn("w:br"), qn("w:cr")})
_WRAPPERS = frozenset({qn("w:sdt"), qn("w:sdtContent"), qn("w:customXml")})
# Properties hold no visible text (w:pPr even holds w:tab stops); deletions are not shown;
# mc:Fallback repeats its mc:Choice for older readers.
_SKIPPED = frozenset(
    {
        qn("w:pPr"),
        qn("w:rPr"),
        qn("w:sdtPr"),
        qn("w:del"),
        qn("w:moveFrom"),
        _MC_FALLBACK,
    }
)


def _inline_text(element: _Element, out: list[str]) -> None:
    for child in element:
        tag = child.tag
        if tag in _SKIPPED:
            continue
        if tag == _T:
            out.append(child.text or "")
        elif tag == _TAB:
            out.append("\t")
        elif tag == _NO_BREAK_HYPHEN:
            out.append("-")
        elif tag in _LINE_BREAKS:
            out.append("\n")
        elif tag == _TXBX_CONTENT:
            out.append("\n" + "\n".join(_blocks(child)) + "\n")
        else:
            _inline_text(child, out)


def _paragraph_text(paragraph: _Element) -> str:
    out: list[str] = []
    _inline_text(paragraph, out)
    return "".join(out).strip()


def _children(element: _Element, tag: str) -> Iterator[_Element]:
    """Children with `tag`, looking through content controls and custom XML around them."""
    for child in element:
        if child.tag == tag:
            yield child
        elif child.tag in _WRAPPERS:
            yield from _children(child, tag)


def _table_rows(table: _Element) -> Iterator[str]:
    for row in _children(table, _TR):
        cells = [
            re.sub(r"\s+", " ", " ".join(_blocks(cell))).strip() for cell in _children(row, _TC)
        ]
        if any(cells):
            yield " | ".join(cells)


def _blocks(container: _Element) -> Iterator[str]:
    for child in container:
        tag = child.tag
        if tag in _SKIPPED:
            continue
        if tag == _P:
            text = _paragraph_text(child)
            if text:
                yield text
        elif tag == _TBL:
            yield from _table_rows(child)
        else:
            yield from _blocks(child)


def docx_text(data: bytes) -> str:
    """The document's visible body text, one paragraph or table row per line.

    Raises zipfile.BadZipFile, KeyError, ValueError, SyntaxError (lxml) or
    docx.opc.exceptions.PackageNotFoundError for a file that is not a readable .docx, and
    office_archive.ArchiveTooLargeError for one that unpacks too far.
    """
    ensure_unpacked_size(data)
    body = Document(io.BytesIO(data)).element.body
    return "\n".join(_blocks(body))
