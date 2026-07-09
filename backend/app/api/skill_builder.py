"""Skill Builder SSE endpoint for creating and editing Heym skills."""

import base64
import binascii
import io
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Literal
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_assistant import get_credential_for_user, get_openai_client
from app.api.deps import get_current_user
from app.db.models import CredentialType, User
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


SET_SKILL_FILES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_skill_files",
        "description": (
            "Set the complete current editable skill file contents. "
            "Call this whenever you create or update any Markdown or Python file. "
            "Always include ALL editable .md and .py files in a single call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "description": "All editable .md and .py files that currently make up the skill.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                }
            },
            "required": ["files"],
        },
    },
}

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
5. Always call `set_skill_files` with the COMPLETE editable `.md`/`.py` file set every time you create or modify files.
6. Keep `SKILL.md` accurate because the LLM reads it to decide when to call the skill.
7. `execute()` must remain a top-level function in `main.py`.
8. Only generate or update `.md` and `.py` files.
9. Use English only for all natural language content, parameter names, descriptions, comments, docstrings, and user-facing strings.
10. Preserve existing file paths unless the user explicitly asks to reorganize them. If you rename or move a Python file, update imports, relative file reads/writes, and `SKILL.md` so the final ZIP layout still works.
11. When reading bundled assets, prefer paths based on `pathlib.Path(__file__).resolve().parent` so the code remains correct when the script lives in a subdirectory.
"""

MAX_SKILL_BUILDER_ROUNDS = 6
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
            "When you update files, always call `set_skill_files` with ALL editable "
            "`.md`/`.py` files, including unchanged editable files.\n"
        )
    else:
        base += (
            "\n\nThe user wants to create a NEW skill. "
            "If the request is specific enough, generate the skill immediately and call "
            "`set_skill_files`. If the request is vague, ask a concise clarifying question first."
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


async def run_skill_builder(
    client: Any,
    request: SkillBuilderRequest,
    trace_context: LLMTraceContext,
    provider: str,
) -> AsyncGenerator[str, None]:
    """Run a non-streaming tool loop and emit SSE events for chat and files."""

    system_prompt = build_skill_builder_prompt(request.existing_skill, request.attachments)
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
                tools=[SET_SKILL_FILES_TOOL],
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
                if tool_call.function.name == "set_skill_files":
                    try:
                        args = json.loads(tool_call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    files, rejected_paths = _normalize_skill_files(args.get("files", []))
                    if files:
                        yield f"data: {json.dumps({'type': 'skill_files_update', 'files': files})}\n\n"
                    if rejected_paths:
                        rejected_list = ", ".join(rejected_paths)
                        tool_result = (
                            "Some files were ignored because Skill Builder only accepts `.md` "
                            f"and `.py` files: {rejected_list}. Keep all natural language "
                            "content in English only."
                        )
                    elif files:
                        tool_result = (
                            "Skill files updated successfully. Keep all natural language "
                            "content in English and only use `.md` and `.py` files."
                        )
                    else:
                        tool_result = (
                            "No valid files were accepted. Skill Builder only accepts `.md` "
                            "and `.py` files, and all natural language content must stay in English."
                        )
                else:
                    tool_result = f"Unsupported tool: {tool_call.function.name}"

                all_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
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

    if credential.type not in (
        CredentialType.openai,
        CredentialType.google,
        CredentialType.custom,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    client, provider = get_openai_client(credential.type, config)

    trace_context = LLMTraceContext(
        user_id=current_user.id,
        credential_id=credential.id,
        workflow_id=None,
        node_label="Skill Builder",
        source="skill_builder",
    )

    return StreamingResponse(
        run_skill_builder(client, request, trace_context, provider),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
