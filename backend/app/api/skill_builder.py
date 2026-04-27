"""Skill Builder SSE endpoint for creating and editing Heym skills."""

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Literal

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


class SkillBuilderSkill(BaseModel):
    """Existing skill context passed to the assistant when editing."""

    name: str
    files: list[SkillBuilderFile] = Field(default_factory=list)


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
    conversation_history: list[SkillBuilderConversationMessage] = Field(default_factory=list)


SET_SKILL_FILES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_skill_files",
        "description": (
            "Set the complete current skill file contents. "
            "Call this whenever you create or update any file. "
            "Always include ALL files in a single call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "description": "All files that currently make up the skill.",
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
- No binary files in the generated output

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
- `Pillow` for image processing
- `requests` for HTTP calls
- `pandas` and `openpyxl` for spreadsheet work

### Critical rules

1. Every `main.py` MUST start with `#!/usr/bin/env python3` on line 1.
2. Every `main.py` MUST import `json` and `sys` and include the `if __name__ == "__main__":` block shown above. Without it the script produces no output and the skill silently fails.
3. NEVER embed fonts as Python strings or base64. Use reportlab built-in fonts: `Helvetica`, `Times-Roman`, `Courier`, and their bold/italic variants.
4. NEVER embed image bytes as Python constants or base64. Ask the user to pass images as input files.
5. Always call `set_skill_files` with the COMPLETE file set every time you create or modify files.
6. Keep `SKILL.md` accurate because the LLM reads it to decide when to call the skill.
7. `execute()` must remain a top-level function in `main.py`.
8. Only generate or update `.md` and `.py` files.
9. Use English only for all natural language content, parameter names, descriptions, comments, docstrings, and user-facing strings.
"""

MAX_SKILL_BUILDER_ROUNDS = 6
ALLOWED_SKILL_BUILDER_EXTENSIONS = (".md", ".py")


def _is_allowed_skill_builder_file(path: str) -> bool:
    """Return whether the skill builder may generate or edit the given file path."""

    normalized_path = path.lower()
    return normalized_path.endswith(ALLOWED_SKILL_BUILDER_EXTENSIONS)


def build_skill_builder_prompt(existing_skill: SkillBuilderSkill | None) -> str:
    """Build the system prompt for the skill builder assistant."""

    base = (
        "You are an expert Heym skill developer. "
        "You help users create and edit skills for the Heym AI workflow platform. "
        "A skill is a Python-backed tool bundle for Agent nodes. "
        "Generate and edit only `.md` and `.py` files. "
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
            base += f"### {file.path}\n\n```\n{file.content}\n```\n\n"
        skipped_files_count = len(existing_skill.files) - len(editable_files)
        if skipped_files_count > 0:
            base += (
                f"{skipped_files_count} attached file(s) were excluded from the AI editing "
                "context because only `.md` and `.py` files are editable here. "
                "Those excluded files must remain untouched.\n\n"
            )
        base += (
            "When you update files, always call `set_skill_files` with ALL files, "
            "including unchanged ones.\n"
        )
    else:
        base += (
            "\n\nThe user wants to create a NEW skill. "
            "If the request is specific enough, generate the skill immediately and call "
            "`set_skill_files`. If the request is vague, ask a concise clarifying question first."
        )

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
        if not _is_allowed_skill_builder_file(path):
            rejected_paths.append(path)
            continue
        files.append({"path": path, "content": content})
    return files, rejected_paths


async def run_skill_builder(
    client: Any,
    request: SkillBuilderRequest,
    trace_context: LLMTraceContext,
    provider: str,
) -> AsyncGenerator[str, None]:
    """Run a non-streaming tool loop and emit SSE events for chat and files."""

    system_prompt = build_skill_builder_prompt(request.existing_skill)
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
