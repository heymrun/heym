"""Skill Builder SSE endpoint for creating and editing Heym skills."""

import base64
import binascii
import io
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Literal
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_assistant import (
    _stream_sse_with_keepalive,
    get_credential_for_user,
    resolve_model_binding,
)
from app.api.deps import get_current_user
from app.db.models import LLM_CREDENTIAL_TYPES, User
from app.db.session import get_db
from app.services.encryption import decrypt_config
from app.services.llm_trace import LLMTraceContext, record_llm_trace

logger = logging.getLogger(__name__)

router = APIRouter()


class SkillBuilderFile(BaseModel):
    """A text file used by the skill builder assistant."""

    path: str
    content: str
    encoding: Literal["text"] = "text"


class SkillBuilderAttachment(BaseModel):
    """A non-editable file attached to the skill bundle."""

    path: str
    encoding: Literal["text", "base64"] = "text"
    mime_type: str | None = None
    size_bytes: int | None = None
    content: str | None = None


class SkillBuilderSkill(BaseModel):
    """Existing skill context passed to the assistant when editing."""

    name: str
    files: list[SkillBuilderFile] = Field(default_factory=list)
    attachments: list[SkillBuilderAttachment] = Field(default_factory=list)


class SkillBuilderConversationMessage(BaseModel):
    """A single prior chat message for multi-turn skill editing."""

    role: Literal["user", "assistant"]
    content: str


class SkillBuilderRequest(BaseModel):
    """Incoming request payload for the skill builder stream."""

    credential_id: uuid.UUID
    model: str
    message: str
    existing_skill: SkillBuilderSkill | None = None
    attachments: list[SkillBuilderAttachment] = Field(default_factory=list)
    conversation_history: list[SkillBuilderConversationMessage] = Field(default_factory=list)
    conversation_id: uuid.UUID | None = None


SET_SKILL_FILES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_skill_files",
        "description": (
            "Create Markdown or Python files, or replace a file's whole content. "
            "Send only the files you create or rewrite: files you leave out stay exactly as "
            "they are. To change part of an existing file, use `edit_skill_file` instead. "
            "List paths in `delete_paths` to remove files, for example the old path after a "
            "rename."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "description": (
                        "The .md and .py files to create or replace, each with its complete "
                        "new content. Leave out every file that does not change."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
                "delete_paths": {
                    "type": "array",
                    "description": "Paths of editable files to remove. SKILL.md cannot be removed.",
                    "items": {"type": "string"},
                },
            },
            "required": ["files"],
        },
    },
}

EDIT_SKILL_FILE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_skill_file",
        "description": (
            "Change part of an existing .md or .py file without resending it. Each edit "
            "replaces `old_string` with `new_string`. `old_string` must match the current "
            "file exactly, including whitespace and indentation, and must occur once unless "
            "`replace_all` is true. Edits apply in order, and either all of them apply or "
            "none do. Use this for any change that touches part of a file, especially a "
            "large one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path of the file to change, as listed in the current files.",
                },
                "edits": {
                    "type": "array",
                    "description": "Replacements to apply to the file, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {
                                "type": "string",
                                "description": "Exact text to replace.",
                            },
                            "new_string": {
                                "type": "string",
                                "description": "Text to put in its place.",
                            },
                            "replace_all": {
                                "type": "boolean",
                                "description": "Replace every occurrence instead of exactly one.",
                            },
                        },
                        "required": ["old_string", "new_string"],
                    },
                },
            },
            "required": ["path", "edits"],
        },
    },
}

SKILL_BUILDER_TOOLS: list[dict[str, Any]] = [SET_SKILL_FILES_TOOL, EDIT_SKILL_FILE_TOOL]

_SKILL_DSL = """
## Heym Skill DSL

A Heym skill is a ZIP bundle containing:
- `SKILL.md` describing when and how the skill should be used
- `main.py` implementing `execute(params, files) -> dict`
- Optional extra `.py` or `.md` helper files
- Optional bundled asset files that existing skills may reference
- No binary files in generated Skill Builder output

### Optional Drive files helper

Agent skills can optionally read Heym Drive files when the skill card's
**Enable Drive files** setting is on. If the user asks for Drive access, mention
that this setting must be enabled on the skill. When it is enabled, Python code
can import:

```python
from heym_drive import (
    get_drive_file,
    get_drive_file_path,
    list_drive_files,
    read_drive_base64,
    read_drive_file,
    read_drive_text,
)
```

Use `file_id="..."` when the workflow has a Drive file id, or `filename="report.pdf"`
when the user refers to a file by name. Filename lookup uses the newest matching
accessible Drive file.

If a skill parameter may contain either a Drive id or a filename, branch before
calling the helper and pass filenames through `filename=...`. For example,
`read_drive_file(filename=identifier)` for `report.pdf`, and
`read_drive_file(file_id=identifier)` for a real Drive file id.

### Required SKILL.md format

```markdown
---
name: skill-name
description: One-line summary shown to the LLM
parameters:
  - name: input_name
    type: string
    description: What the parameter means
    required: true
outputs:
  - name: result
    type: string
    description: What the skill returns
timeout: 30
---

## Description

Explain what the skill does, when to call it, and what it returns.

## Parameters

- **input_name** (string, required): Detailed explanation.

## Returns

- **result**: The processed output.
```

### Required main.py shape

Every `main.py` MUST start with `#!/usr/bin/env python3`, import `json` and `sys`,
implement `execute()`, and include the `if __name__ == "__main__":` block below.
Without this boilerplate the script produces no output and the skill silently fails.

```python
#!/usr/bin/env python3
import json
import sys


def execute(params: dict, files: dict) -> dict:
    \"\"\"
    params: plain Python values parsed from stdin (the skill's input arguments)
    files:  dict of binary files provided by the user (usually empty for generated skills)
    returns: dict with plain Python values only

    To return generated files, write them to the _OUTPUT_DIR environment variable path:
        import os, pathlib
        out = pathlib.Path(os.environ["_OUTPUT_DIR"]) / "result.pdf"
        out.write_bytes(pdf_bytes)
    They will be attached automatically — do NOT include file bytes in the returned dict.
    \"\"\"
    # TODO: implement the skill logic here
    return {"result": "replace me"}


if __name__ == "__main__":
    try:
        raw = sys.stdin.read().strip()
        params = json.loads(raw) if raw else {}
        if not isinstance(params, dict):
            params = {"input": params}
        result = execute(params, {})
        print(json.dumps(result, default=str))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, default=str))
```

### Available Python libraries

Standard library is always available. Third-party libraries available in Heym:
- `reportlab` for PDF generation
- `python-docx` for DOCX generation
- `Pillow` (`PIL`) for image processing and format conversion
- `pypandoc` for document conversion (markdown/html/docx/txt → pdf/docx/html/md/txt/epub). Import as `import pypandoc`. The pandoc binary is bundled — no system install needed.
- `requests` for HTTP calls
- `pypdf` for PDF reading and text extraction

### Generating files with pypandoc

Use `pypandoc.convert_text` or `pypandoc.convert_file` to convert document formats. Always write output to `_OUTPUT_DIR`:

```python
import os
import pypandoc
import pathlib

def execute(params: dict, files: dict) -> dict:
    md_content = params.get("markdown", "# Hello")
    out_dir = pathlib.Path(os.environ["_OUTPUT_DIR"])

    # Markdown → PDF
    pdf_path = out_dir / "output.pdf"
    pypandoc.convert_text(
        md_content,
        "pdf",
        format="markdown",
        outputfile=str(pdf_path),
        extra_args=["--pdf-engine=weasyprint"],
    )

    # Markdown → DOCX
    docx_path = out_dir / "output.docx"
    pypandoc.convert_text(md_content, "docx", format="markdown", outputfile=str(docx_path))

    return {"status": "done"}
```

For HTML input: `format="html"`. For plain text input: `format="markdown"`. Supported output formats: `pdf`, `docx`, `html`, `markdown`, `plain`, `epub`.

### Generating files with Pillow

Use `PIL.Image` to create, resize, or convert images. Write output to `_OUTPUT_DIR`:

```python
import os
import pathlib
from PIL import Image, ImageDraw, ImageFont

def execute(params: dict, files: dict) -> dict:
    out_dir = pathlib.Path(os.environ["_OUTPUT_DIR"])

    # Create a simple image
    img = Image.new("RGB", (800, 400), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.text((40, 160), params.get("text", "Hello"), fill=(255, 255, 255))
    img.save(out_dir / "result.png", format="PNG")

    # Convert format: open input bytes, save as different format
    # if "image" in files:
    #     src = Image.open(io.BytesIO(files["image"]))
    #     src.save(out_dir / "converted.jpg", format="JPEG")

    return {"status": "done"}
```

### Critical rules

1. Every `main.py` MUST start with `#!/usr/bin/env python3` on line 1.
2. Every `main.py` MUST import `json` and `sys` and include the `if __name__ == "__main__":` block shown above. Without it the script produces no output and the skill silently fails.
3. NEVER embed fonts as Python strings or base64. Use reportlab built-in fonts: `Helvetica`, `Times-Roman`, `Courier`, and their bold/italic variants.
4. NEVER embed image bytes as Python constants or base64. Ask the user to pass images as input files.
5. Change only what the request needs. Use `edit_skill_file` to change part of an existing file and `set_skill_files` to create a file or rewrite one completely. Files you do not send stay as they are, so never resend a file you did not change.
6. Keep `SKILL.md` accurate because the LLM reads it to decide when to call the skill.
7. `execute()` must remain a top-level function in `main.py`.
8. Only generate or update `.md` and `.py` files.
9. Use English only for all natural language content, parameter names, descriptions, comments, docstrings, and user-facing strings.
10. Preserve existing file paths unless the user explicitly asks to reorganize them. If you rename or move a Python file, update imports, relative file reads/writes, and `SKILL.md` so the final ZIP layout still works.
11. When reading bundled assets, prefer paths based on `pathlib.Path(__file__).resolve().parent` so the code remains correct when the script lives in a subdirectory.
"""

MAX_SKILL_BUILDER_ROUNDS = 6
SKILL_BUILDER_SSE_KEEPALIVE_SECONDS = 10.0
ALLOWED_SKILL_BUILDER_EXTENSIONS = (".md", ".py")
MACOS_METADATA_DIR = "__MACOSX"
MACOS_METADATA_FILENAMES = {".DS_Store"}
ATTACHMENT_TEXT_CONTEXT_MAX_CHARS = 12_000
DOCX_CONTEXT_MAX_TABLES = 12
DOCX_CONTEXT_MAX_ROWS = 30
DOCX_CONTEXT_MAX_CELLS = 8
DOCX_CONTEXT_MAX_CELL_CHARS = 120
DOCX_CONTEXT_MAX_PARAGRAPHS = 20
DOCX_XML_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _normalize_skill_builder_path(path: str) -> str:
    """Normalize a skill file path for prompt and tool use."""

    normalized = path.replace("\\", "/").lstrip("/")
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    return "/".join(parts)


def _is_ignored_skill_builder_path(path: str) -> bool:
    """Return whether a path is generated OS metadata that should be skipped."""

    normalized = _normalize_skill_builder_path(path)
    if not normalized:
        return True

    parts = normalized.split("/")
    return any(
        part == MACOS_METADATA_DIR or part in MACOS_METADATA_FILENAMES or part.startswith("._")
        for part in parts
    )


def _is_allowed_skill_builder_file(path: str) -> bool:
    """Return whether the skill builder may generate or edit the given file path."""

    if _is_ignored_skill_builder_path(path):
        return False

    normalized_path = _normalize_skill_builder_path(path).lower()
    return normalized_path.endswith(ALLOWED_SKILL_BUILDER_EXTENSIONS)


def _append_limited_line(lines: list[str], line: str, max_chars: int) -> bool:
    """Append a line unless doing so would exceed max_chars."""

    current_chars = sum(len(existing) + 1 for existing in lines)
    if current_chars + len(line) + 1 > max_chars:
        lines.append("... truncated ...")
        return False
    lines.append(line)
    return True


def _truncate_text(value: str, max_chars: int) -> str:
    """Return value capped to max_chars, preserving a truncation marker."""

    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _decode_attachment_bytes(attachment: SkillBuilderAttachment) -> bytes | None:
    """Decode attachment content into bytes when the caller opted into context."""

    if not attachment.content:
        return None
    if attachment.encoding == "base64":
        try:
            return base64.b64decode(attachment.content, validate=True)
        except (binascii.Error, ValueError):
            return None
    return attachment.content.encode("utf-8", errors="replace")


def _docx_node_text(node: ElementTree.Element) -> str:
    """Extract visible text from a DOCX XML node."""

    return "".join(text.text or "" for text in node.findall(".//w:t", DOCX_XML_NS)).strip()


def _summarize_docx_context(data: bytes) -> str:
    """Return a compact, LLM-readable summary of a DOCX document."""

    try:
        with ZipFile(io.BytesIO(data)) as docx:
            document_xml = docx.read("word/document.xml")
    except (BadZipFile, KeyError):
        return "DOCX summary unavailable: document.xml could not be read."

    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        return "DOCX summary unavailable: document.xml is not valid XML."

    lines: list[str] = [
        "DOCX structure summary:",
        "Use this to compare Python placeholder logic with the actual template layout.",
    ]

    body = root.find(".//w:body", DOCX_XML_NS)
    if body is not None:
        paragraph_texts = [
            _docx_node_text(paragraph)
            for paragraph in body.findall("./w:p", DOCX_XML_NS)
            if _docx_node_text(paragraph)
        ][:DOCX_CONTEXT_MAX_PARAGRAPHS]
        if paragraph_texts:
            lines.append("Top-level paragraphs:")
            for index, text in enumerate(paragraph_texts, start=1):
                if not _append_limited_line(
                    lines,
                    f"- Paragraph {index}: {_truncate_text(text, DOCX_CONTEXT_MAX_CELL_CHARS)}",
                    ATTACHMENT_TEXT_CONTEXT_MAX_CHARS,
                ):
                    return "\n".join(lines)

    label_value_candidates: list[str] = []
    tables = root.findall(".//w:tbl", DOCX_XML_NS)
    if tables:
        lines.append("Tables:")

    for table_index, table in enumerate(tables[:DOCX_CONTEXT_MAX_TABLES], start=1):
        if not _append_limited_line(
            lines, f"Table {table_index}:", ATTACHMENT_TEXT_CONTEXT_MAX_CHARS
        ):
            return "\n".join(lines)
        rows = table.findall("./w:tr", DOCX_XML_NS)
        for row_index, row in enumerate(rows[:DOCX_CONTEXT_MAX_ROWS], start=1):
            cells: list[str] = []
            raw_cell_texts: list[str] = []
            for cell in row.findall("./w:tc", DOCX_XML_NS)[:DOCX_CONTEXT_MAX_CELLS]:
                text = _docx_node_text(cell)
                raw_cell_texts.append(text)
                if text:
                    cells.append(_truncate_text(text, DOCX_CONTEXT_MAX_CELL_CHARS))
                    continue
                run_count = len(cell.findall(".//w:r", DOCX_XML_NS))
                cells.append(f"<EMPTY runs={run_count}>")
            if len(raw_cell_texts) >= 2 and raw_cell_texts[0] and not raw_cell_texts[1]:
                label_value_candidates.append(
                    f"Table {table_index} row {row_index}: `{raw_cell_texts[0]}` -> adjacent empty cell"
                )
            if not _append_limited_line(
                lines,
                f"  Row {row_index}: {' | '.join(cells)}",
                ATTACHMENT_TEXT_CONTEXT_MAX_CHARS,
            ):
                return "\n".join(lines)

    if label_value_candidates:
        lines.append("Detected label/value table candidates:")
        for candidate in label_value_candidates[:20]:
            if not _append_limited_line(lines, f"- {candidate}", ATTACHMENT_TEXT_CONTEXT_MAX_CHARS):
                return "\n".join(lines)
        lines.append(
            "If Python code replaces text in the label cell, update it to write the value into "
            "the adjacent empty cell instead."
        )

    return "\n".join(lines)


def _summarize_text_attachment(data: bytes) -> str:
    """Return a capped UTF-8 text summary for included text attachments."""

    text = data.decode("utf-8", errors="replace")
    return _truncate_text(text, ATTACHMENT_TEXT_CONTEXT_MAX_CHARS)


def _summarize_pdf_context(data: bytes) -> str:
    """Return a compact text summary of a PDF attachment."""

    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(data))
        parts: list[str] = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip():
                continue
            parts.append(f"Page {page_index}:\n{text.strip()}")
        if not parts:
            return "PDF text extraction returned no readable text."
        return _truncate_text("\n\n".join(parts), ATTACHMENT_TEXT_CONTEXT_MAX_CHARS)
    except Exception as exc:
        return f"PDF summary unavailable: {exc}"


def _build_attachment_context(
    normalized_path: str, attachment: SkillBuilderAttachment
) -> str | None:
    """Build optional attachment content context for the skill builder prompt."""

    data = _decode_attachment_bytes(attachment)
    if data is None:
        return None

    lower_path = normalized_path.lower()
    mime_type = (attachment.mime_type or "").lower()
    if lower_path.endswith(".docx") or mime_type.endswith(
        "officedocument.wordprocessingml.document"
    ):
        return _summarize_docx_context(data)
    if lower_path.endswith(".pdf") or mime_type == "application/pdf":
        return _summarize_pdf_context(data)
    if attachment.encoding == "text" or mime_type.startswith("text/"):
        return _summarize_text_attachment(data)

    return None


def _attachment_details(attachment: SkillBuilderAttachment) -> str:
    """Return a compact attachment metadata string for prompts."""

    details = [attachment.encoding]
    if attachment.mime_type:
        details.append(attachment.mime_type)
    if attachment.size_bytes is not None:
        details.append(f"{attachment.size_bytes} bytes")
    return ", ".join(details)


def _attachment_context_sections(
    attachments: list[tuple[str, SkillBuilderAttachment]],
) -> list[str]:
    """Build prompt sections for attachments that have extractable content."""

    attachment_contexts: list[str] = []
    for normalized_path, attachment in attachments:
        context = _build_attachment_context(normalized_path, attachment)
        if context:
            attachment_contexts.append(f"### {normalized_path}\n\n{context}")
    return attachment_contexts


def build_skill_builder_prompt(
    existing_skill: SkillBuilderSkill | None,
    message_attachments: list[SkillBuilderAttachment] | None = None,
) -> str:
    """Build the system prompt for the skill builder assistant."""

    base = (
        "You are an expert Heym skill developer. "
        "You help users create and edit skills for the Heym AI workflow platform. "
        "A skill is a Python-backed tool bundle for Agent nodes. "
        "Generate and edit only `.md` and `.py` files. "
        "Existing non-editable attachments may be referenced by path, but you must not "
        "generate placeholders for them. "
        "Uploaded files in this chat are bundled assets; use their context and paths, "
        "but do not include them in `set_skill_files`. "
        "All natural language content must be English only, including parameter names, "
        "descriptions, output names, output descriptions, comments, docstrings, "
        "and user-facing strings.\n\n"
    )
    base += _SKILL_DSL

    if existing_skill:
        base += f"\n\n## Current Skill: {existing_skill.name}\n\n"
        base += "The user is editing an existing skill. Current files:\n\n"
        editable_files = [
            file for file in existing_skill.files if _is_allowed_skill_builder_file(file.path)
        ]
        for file in editable_files:
            normalized_path = _normalize_skill_builder_path(file.path)
            base += f"### {normalized_path}\n\n```\n{file.content}\n```\n\n"
        skipped_files_count = len(existing_skill.files) - len(editable_files)
        if skipped_files_count > 0:
            base += (
                f"{skipped_files_count} attached file(s) were excluded from the AI editing "
                "context because only `.md` and `.py` files are editable here. "
                "Those excluded files must remain untouched.\n\n"
            )
        attachments = [
            (_normalize_skill_builder_path(attachment.path), attachment)
            for attachment in existing_skill.attachments
            if _normalize_skill_builder_path(attachment.path)
            and not _is_ignored_skill_builder_path(attachment.path)
        ]
        if attachments:
            base += (
                "Non-editable files attached to the final ZIP bundle. Their contents are "
                "not shown, but their paths are real and must stay valid:\n"
            )
            for normalized_path, attachment in attachments:
                base += f"- `{normalized_path}` ({_attachment_details(attachment)})\n"
            base += (
                "\nDo not include these non-editable files in `set_skill_files`. "
                "If you move a Python file that reads one of these paths, update the "
                "code and `SKILL.md` so the relative path still points to the asset in "
                "the final ZIP layout.\n\n"
            )
            attachment_contexts = _attachment_context_sections(attachments)
            if attachment_contexts:
                base += (
                    "## Included Attachment Context\n\n"
                    "The user explicitly selected these binary/non-editable files for context. "
                    "Use these extracted summaries to diagnose mismatches between the "
                    "Python code and bundled templates, then update only editable `.md` "
                    "and `.py` files.\n\n"
                )
                base += "\n\n".join(attachment_contexts)
                base += "\n\n"
        base += (
            "To change files, call `edit_skill_file` for targeted replacements and "
            "`set_skill_files` for new or completely rewritten files. Send only what "
            "changes: files you leave out stay exactly as they are, so a large file never "
            "needs to be resent.\n"
        )
    else:
        base += (
            "\n\nThe user wants to create a NEW skill. "
            "If the request is specific enough, generate the skill immediately and call "
            "`set_skill_files` with every file the skill needs. If the request is vague, ask "
            "a concise clarifying question first."
        )

    uploaded_attachments = [
        (_normalize_skill_builder_path(attachment.path), attachment)
        for attachment in (message_attachments or [])
        if _normalize_skill_builder_path(attachment.path)
        and not _is_ignored_skill_builder_path(attachment.path)
    ]
    if uploaded_attachments:
        base += (
            "\n\n## Uploaded Files For This Request\n\n"
            "The user attached these files with the current comment. They will be preserved "
            "as bundled skill assets when the user saves the skill. Reference their exact "
            "paths from Python code when needed, but do not include them in `set_skill_files`.\n"
        )
        for normalized_path, attachment in uploaded_attachments:
            base += f"- `{normalized_path}` ({_attachment_details(attachment)})\n"

        uploaded_contexts = _attachment_context_sections(uploaded_attachments)
        if uploaded_contexts:
            base += (
                "\n## Uploaded File Context\n\n"
                "Use this extracted context to update only editable `.md` and `.py` files.\n\n"
            )
            base += "\n\n".join(uploaded_contexts)
            base += "\n\n"

    return base.strip()


def _serialize_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """Convert OpenAI tool call objects into a JSON-serializable structure."""

    if not tool_calls:
        return []
    serialized: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        serialized.append(
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
        )
    return serialized


def _normalize_skill_files(raw_files: list[Any]) -> tuple[list[dict[str, str]], list[str]]:
    """Validate and normalize skill files before sending them to the frontend."""

    files: list[dict[str, str]] = []
    rejected_paths: list[str] = []
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            continue
        path = raw_file.get("path")
        content = raw_file.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            continue
        normalized_path = _normalize_skill_builder_path(path)
        if not _is_allowed_skill_builder_file(normalized_path):
            rejected_paths.append(path)
            continue
        files.append({"path": normalized_path, "content": content})
    return files, rejected_paths


@dataclass
class SkillFileToolOutcome:
    """What one file tool call did to the turn's editable files, and what the model reads."""

    result: str
    changed_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)


ENGLISH_ONLY_REMINDER = (
    "Keep all natural language content in English and only use `.md` and `.py` files."
)


def _initial_skill_files(existing_skill: SkillBuilderSkill | None) -> dict[str, str]:
    """Return the editable files a turn starts from, keyed by normalized path."""

    files: dict[str, str] = {}
    if existing_skill is None:
        return files
    for file in existing_skill.files:
        path = _normalize_skill_builder_path(file.path)
        if _is_allowed_skill_builder_file(path):
            files[path] = file.content
    return files


def _apply_set_skill_files(
    skill_files: dict[str, str], args: dict[str, Any]
) -> SkillFileToolOutcome:
    """Write whole files and remove listed ones; files the call leaves out stay as they are."""

    raw_files = args.get("files")
    files, rejected_paths = _normalize_skill_files(raw_files if isinstance(raw_files, list) else [])
    raw_deletes = args.get("delete_paths")
    notes: list[str] = []
    changed: list[str] = []
    deleted: list[str] = []

    for raw_path in raw_deletes if isinstance(raw_deletes, list) else []:
        if not isinstance(raw_path, str):
            continue
        path = _normalize_skill_builder_path(raw_path)
        if path.lower() == "skill.md":
            notes.append("`SKILL.md` cannot be deleted, so it was kept.")
        elif path in skill_files:
            del skill_files[path]
            deleted.append(path)
        else:
            notes.append(f"`{raw_path}` was not deleted because no editable file has that path.")

    for file in files:
        path = file["path"]
        if path in deleted:
            deleted.remove(path)
        if skill_files.get(path) != file["content"]:
            skill_files[path] = file["content"]
            changed.append(path)

    if rejected_paths:
        rejected_list = ", ".join(rejected_paths)
        notes.insert(
            0,
            "Some files were ignored because Skill Builder only accepts `.md` and `.py` "
            f"files: {rejected_list}.",
        )
    if changed or deleted:
        summary = []
        if changed:
            summary.append("wrote " + ", ".join(f"`{path}`" for path in changed))
        if deleted:
            summary.append("deleted " + ", ".join(f"`{path}`" for path in deleted))
        notes.insert(0, f"Skill files updated: {'; '.join(summary)}. Other files are unchanged.")
    elif files:
        notes.insert(0, "The files you sent already had that content, so nothing changed.")
    elif not notes:
        notes.append("No valid files were accepted.")
    notes.append(ENGLISH_ONLY_REMINDER)
    return SkillFileToolOutcome(" ".join(notes), changed, deleted)


def _edit_refused(reason: str) -> SkillFileToolOutcome:
    return SkillFileToolOutcome(f"Nothing was changed: {reason}")


def _apply_edit_skill_file(
    skill_files: dict[str, str], args: dict[str, Any]
) -> SkillFileToolOutcome:
    """Apply exact string replacements to one file, all of them or none."""

    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not _normalize_skill_builder_path(raw_path):
        return _edit_refused("`path` is required.")
    path = _normalize_skill_builder_path(raw_path)
    if not _is_allowed_skill_builder_file(path):
        return _edit_refused(f"Skill Builder only edits `.md` and `.py` files, not `{raw_path}`.")
    if path not in skill_files:
        return _edit_refused(f"`{path}` does not exist. Use `set_skill_files` to create it.")

    edits = args.get("edits")
    if not isinstance(edits, list) or not edits:
        if isinstance(args.get("old_string"), str):
            edits = [args]
        else:
            return _edit_refused("`edits` must list at least one replacement.")

    original = skill_files[path]
    content = original
    for index, edit in enumerate(edits, start=1):
        old_string = edit.get("old_string") if isinstance(edit, dict) else None
        new_string = edit.get("new_string") if isinstance(edit, dict) else None
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            return _edit_refused(f"edit {index} needs `old_string` and `new_string`.")
        if not old_string:
            return _edit_refused(
                f"edit {index} has an empty `old_string`. Use `set_skill_files` to replace "
                "a whole file."
            )
        replace_all = edit.get("replace_all") in (True, "true")
        count = content.count(old_string)
        if count == 0:
            return _edit_refused(
                f"edit {index}: `old_string` was not found in `{path}`. Copy it exactly from "
                "the current file, including whitespace and indentation, and account for "
                "earlier edits."
            )
        if count > 1 and not replace_all:
            return _edit_refused(
                f"edit {index}: `old_string` occurs {count} times in `{path}`. Include more "
                "surrounding text so it matches once, or set `replace_all` to true."
            )
        content = content.replace(old_string, new_string, -1 if replace_all else 1)

    if content == original:
        return SkillFileToolOutcome(f"`{path}` already had that content, so nothing changed.")
    skill_files[path] = content
    return SkillFileToolOutcome(
        f"Edited `{path}` with {len(edits)} replacement(s). The rest of the file and every "
        f"other file are unchanged. {ENGLISH_ONLY_REMINDER}",
        changed_paths=[path],
    )


def apply_skill_file_tool(
    skill_files: dict[str, str], name: str, raw_arguments: str | None
) -> SkillFileToolOutcome:
    """Run one Skill Builder file tool against the turn's editable files."""

    try:
        args = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        args = None
    if not isinstance(args, dict):
        return SkillFileToolOutcome(
            "Nothing was changed: the tool arguments were not a valid JSON object."
        )
    if name == "set_skill_files":
        return _apply_set_skill_files(skill_files, args)
    if name == "edit_skill_file":
        return _apply_edit_skill_file(skill_files, args)
    return SkillFileToolOutcome(f"Unsupported tool: {name}")


def _skill_files_update_event(skill_files: dict[str, str], outcome: SkillFileToolOutcome) -> str:
    """The SSE event for a file change: every editable file, plus what this call changed.

    `files` is the whole editable set so a client that replaces its list stays correct;
    `changed_paths` and `deleted_paths` let a client that merges touch only those.
    """

    payload = {
        "type": "skill_files_update",
        "files": [{"path": path, "content": content} for path, content in skill_files.items()],
        "changed_paths": outcome.changed_paths,
        "deleted_paths": outcome.deleted_paths,
    }
    return f"data: {json.dumps(payload)}\n\n"


async def run_skill_builder(
    client: Any,
    request: SkillBuilderRequest,
    trace_context: LLMTraceContext,
    provider: str,
) -> AsyncGenerator[str, None]:
    """Run a non-streaming tool loop and emit SSE events for chat and files."""

    system_prompt = build_skill_builder_prompt(request.existing_skill, request.attachments)
    skill_files = _initial_skill_files(request.existing_skill)
    history = [message.model_dump() for message in request.conversation_history]
    all_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": request.message},
    ]

    start_time = time.time()
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    final_response_content: str = ""

    try:
        for _round in range(MAX_SKILL_BUILDER_ROUNDS):
            response = client.chat.completions.create(
                model=request.model,
                messages=all_messages,
                tools=SKILL_BUILDER_TOOLS,
                temperature=0.3,
                stream=False,
            )

            choice = response.choices[0] if response.choices else None
            if not choice:
                elapsed_ms = round((time.time() - start_time) * 1000, 2)
                record_llm_trace(
                    context=trace_context,
                    request_type="chat.completions",
                    request={"model": request.model, "messages": all_messages},
                    response={"model": request.model},
                    model=request.model,
                    provider=provider,
                    error="No response from model",
                    elapsed_ms=elapsed_ms,
                    prompt_tokens=total_prompt_tokens or None,
                    completion_tokens=total_completion_tokens or None,
                    total_tokens=total_tokens or None,
                )
                yield f"data: {json.dumps({'type': 'error', 'message': 'No response from model'})}\n\n"
                return

            message = choice.message
            usage = getattr(response, "usage", None)
            if usage:
                total_prompt_tokens += usage.prompt_tokens or 0
                total_completion_tokens += usage.completion_tokens or 0
                total_tokens += usage.total_tokens or 0

            if message.content:
                final_response_content += message.content
                yield f"data: {json.dumps({'type': 'text_chunk', 'content': message.content})}\n\n"

            if not message.tool_calls:
                break

            all_messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": _serialize_tool_calls(message.tool_calls),
                }
            )

            for tool_call in message.tool_calls:
                outcome = apply_skill_file_tool(
                    skill_files, tool_call.function.name, tool_call.function.arguments
                )
                if outcome.changed_paths or outcome.deleted_paths:
                    yield _skill_files_update_event(skill_files, outcome)

                all_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": outcome.result,
                    }
                )

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        record_llm_trace(
            context=trace_context,
            request_type="chat.completions",
            request={"model": request.model, "messages": all_messages},
            response={"content": final_response_content, "model": request.model},
            model=request.model,
            provider=provider,
            error=None,
            elapsed_ms=elapsed_ms,
            prompt_tokens=total_prompt_tokens or None,
            completion_tokens=total_completion_tokens or None,
            total_tokens=total_tokens or None,
        )
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
    except Exception as exc:
        logger.exception("Skill builder error: %s", exc)
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        record_llm_trace(
            context=trace_context,
            request_type="chat.completions",
            request={"model": request.model, "messages": all_messages},
            response={"content": final_response_content, "model": request.model},
            model=request.model,
            provider=provider,
            error=str(exc),
            elapsed_ms=elapsed_ms,
            prompt_tokens=total_prompt_tokens or None,
            completion_tokens=total_completion_tokens or None,
            total_tokens=total_tokens or None,
        )
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


@router.post("/skill-builder")
async def skill_builder_stream(
    request: SkillBuilderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream skill builder responses over Server-Sent Events."""

    credential = await get_credential_for_user(request.credential_id, current_user, db)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )

    if credential.type not in LLM_CREDENTIAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    session_id = str(request.conversation_id or uuid.uuid4())

    trace_context = LLMTraceContext(
        session_id=session_id,
        user_id=current_user.id,
        credential_id=credential.id,
        workflow_id=None,
        node_label="Skill Builder",
        source="skill_builder",
    )
    client, provider, request.model, trace_context = resolve_model_binding(
        credential,
        config,
        request.model,
        session_id=session_id,
        trace_context=trace_context,
        system_prompt=build_skill_builder_prompt(request.existing_skill, request.attachments),
        message=request.message,
    )

    # The model call blocks for as long as the answer takes, and a long file rewrite can
    # run for minutes. Run it off the event loop and send keepalives meanwhile, or a proxy
    # such as Cloudflare drops the silent connection (about 100 s) and the client sees 502.
    return StreamingResponse(
        _stream_sse_with_keepalive(
            run_skill_builder(client, request, trace_context, provider),
            keepalive_seconds=SKILL_BUILDER_SSE_KEEPALIVE_SECONDS,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
