# Skill Builder & AI Builder Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an AI-powered Skill Builder modal to the Agent node's properties panel, and fix the AI Builder context overflow by stripping all skill files except SKILL.md before sending to the LLM.

**Architecture:** Feature 1 is a one-line computed property change in DebugPanel.vue. Feature 2 adds a new FastAPI SSE endpoint (`/api/ai/skill-builder`) with a non-streaming tool-use loop, a service function + composable on the frontend, and a new modal component wired into PropertiesPanel.vue.

**Tech Stack:** Vue 3 (Composition API, `<script setup>`), TypeScript strict, Pinia, JSZip (already in package.json), FastAPI, Pydantic, OpenAI SDK (non-streaming tool calls + SSE chunked response), pytest/unittest.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `frontend/src/components/Panels/DebugPanel.vue:710-720` | Filter skill files in `currentWorkflowContext` |
| Modify | `frontend/src/lib/skillZipParser.ts` | Export `extractNameFromFrontmatter` |
| Create | `backend/app/api/skill_builder.py` | New SSE endpoint + system prompt builder |
| Create | `backend/tests/test_skill_builder.py` | Backend unit tests |
| Modify | `backend/app/main.py` | Register new router |
| Create | `frontend/src/services/skillBuilderApi.ts` | Fetch + SSE parse for skill builder stream |
| Create | `frontend/src/composables/useSkillBuilder.ts` | Chat + files state for the modal |
| Create | `frontend/src/components/Panels/SkillBuilderModal.vue` | Modal UI: chat left, files right |
| Modify | `frontend/src/components/Panels/PropertiesPanel.vue` | Add ✨ AI Build + per-skill ✨ buttons, mount modal |

---

## Task 1: AI Builder Filter — currentWorkflowContext

**Files:**
- Modify: `frontend/src/components/Panels/DebugPanel.vue:710-720`

- [ ] **Step 1: Apply the filter**

Replace lines 710–720 in `DebugPanel.vue`:

```typescript
const currentWorkflowContext = computed(() => {
  if (workflowStore.nodes.length === 0 && workflowStore.edges.length === 0) {
    return undefined;
  }

  const filteredNodes = workflowStore.nodes.map((node) => {
    if (node.data?.nodeType !== "agent") return node;
    const filteredSkills = (node.data.skills ?? []).map((skill: AgentSkill) => ({
      ...skill,
      files: (skill.files ?? []).filter((f: AgentSkillFile) => f.path.endsWith(".md")),
    }));
    return { ...node, data: { ...node.data, skills: filteredSkills } };
  });

  return {
    id: workflowStore.currentWorkflow?.id,
    name: workflowStore.currentWorkflow?.name,
    nodes: filteredNodes,
    edges: workflowStore.edges,
  };
});
```

Check that `AgentSkill` and `AgentSkillFile` are already imported at the top of the file. Both are defined in `frontend/src/types/workflow.ts`. If not imported, add them to the existing import line for `workflow.ts`.

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Panels/DebugPanel.vue
git commit -m "fix: strip non-SKILL.md files from AI Builder workflow context

Large .py files and fonts embedded as Python string constants were
filling the 128k context window. Only SKILL.md is needed for workflow
structure understanding.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Export extractNameFromFrontmatter from skillZipParser

**Files:**
- Modify: `frontend/src/lib/skillZipParser.ts:46`

- [ ] **Step 1: Export the function**

Change line 46 from:

```typescript
function extractNameFromFrontmatter(content: string): string {
```

to:

```typescript
export function extractNameFromFrontmatter(content: string): string {
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: 0 errors.

---

## Task 3: Backend — skill_builder.py

**Files:**
- Create: `backend/app/api/skill_builder.py`

- [ ] **Step 1: Create the file**

```python
"""Skill Builder — AI assistant for creating and editing Heym skills."""

import json
import logging
import time
from typing import Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.ai_assistant import get_credential_for_user, get_openai_client
from app.api.deps import get_current_user
from app.db.models import CredentialType, User
from app.db.session import get_db
from app.services.encryption import decrypt_config
from app.services.llm_trace import LLMTraceContext, record_llm_trace

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SkillBuilderFile(BaseModel):
    """A single file in the skill (SKILL.md or .py only — no binaries)."""

    path: str
    content: str


class SkillBuilderSkill(BaseModel):
    """Existing skill passed when editing (None = new skill)."""

    name: str
    files: list[SkillBuilderFile]


class SkillBuilderRequest(BaseModel):
    credential_id: str
    model: str
    message: str
    existing_skill: SkillBuilderSkill | None = None
    conversation_history: list[dict] | None = None


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

SET_SKILL_FILES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "set_skill_files",
        "description": (
            "Set the complete current skill file contents. "
            "Call this whenever you create or update any file. "
            "Always include ALL files (SKILL.md + every .py file) in a single call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "File path, e.g. SKILL.md or main.py",
                            },
                            "content": {
                                "type": "string",
                                "description": "Full file content as a string.",
                            },
                        },
                        "required": ["path", "content"],
                    },
                    "description": "All files that make up this skill.",
                }
            },
            "required": ["files"],
        },
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SKILL_DSL = """
## Heym Skill DSL

A **skill** is a ZIP containing:
- `SKILL.md` — describes the skill to the LLM (required)
- `main.py` — Python entry point (required for executable skills)
- Additional `.py` helper modules (optional)
- NO binary files — no fonts, no images embedded as bytes or base64

### SKILL.md format

```
---
name: skill-name
description: One-line description shown to the LLM
parameters:
  - name: param_name
    type: string
    description: What this parameter is
    required: true
outputs:
  - name: result
    type: string
    description: What is returned
timeout: 30
---

## Description

Longer markdown description for the LLM about what this skill does,
when to call it, and what it returns.

## Parameters

- **param_name** (string, required): Detailed explanation.

## Returns

- **result**: The processed output.
```

### main.py entry point

```python
def execute(params: dict, files: dict) -> dict:
    \"\"\"
    params: dict of input parameters (strings, numbers, booleans)
    files:  dict of binary files passed to the skill (base64-decoded bytes)
    returns: dict — plain Python types only (str, int, float, bool, list, dict)
             to return a generated file add it under _generated_files:
             {"_generated_files": [{"filename": "out.pdf", "file_bytes": b"...", "mime_type": "application/pdf"}]}
    \"\"\"
    ...
```

### Available Python libraries

Standard library always available. Third-party available in Heym's sandbox:
- **PDF**: `reportlab` — use built-in fonts only: `Helvetica`, `Times-Roman`, `Courier` and their Bold/Italic variants. NEVER embed font files.
- **Word/DOCX**: `python-docx`
- **Images**: `Pillow` (PIL)
- **Spreadsheets**: `openpyxl`, `pandas`
- **HTTP**: `requests`
- **Data**: `json`, `csv`, `base64`, `io`, `pathlib`

### Critical rules

1. NEVER embed fonts as Python string constants or base64 — use reportlab built-in fonts.
2. NEVER embed image bytes as Python constants — if images are needed, require them as input parameters.
3. Always call `set_skill_files` with the COMPLETE file set (not partial updates) every time you modify files.
4. Keep SKILL.md accurate — it is what the LLM reads to decide when to call the skill.
5. `execute()` must be a top-level function in `main.py`.
"""


def build_skill_builder_prompt(existing_skill: SkillBuilderSkill | None) -> str:
    """Build the system prompt for the skill builder assistant."""
    base = (
        "You are an expert Heym skill developer. "
        "You help users create and edit skills for the Heym AI workflow platform. "
        "A skill is a Python script with a SKILL.md descriptor that an AI agent can call as a tool.\n\n"
    )
    base += _SKILL_DSL

    if existing_skill:
        base += f"\n\n## Current Skill: {existing_skill.name}\n\n"
        base += "The user is editing an existing skill. Current files:\n\n"
        for f in existing_skill.files:
            base += f"### {f.path}\n\n```\n{f.content}\n```\n\n"
        base += (
            "When you update files, always call `set_skill_files` with ALL files "
            "(including unchanged ones).\n"
        )
    else:
        base += (
            "\n\nThe user wants to create a NEW skill. "
            "Start by asking what the skill should do if the first message is vague, "
            "otherwise generate SKILL.md and main.py immediately and call `set_skill_files`."
        )

    return base.strip()


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

MAX_SKILL_BUILDER_ROUNDS = 6


async def run_skill_builder(
    client: Any,
    request: SkillBuilderRequest,
    trace_context: LLMTraceContext,
    provider: str,
) -> AsyncGenerator[str, None]:
    """Non-streaming tool-use loop; emits SSE events for text and file updates."""
    system_prompt = build_skill_builder_prompt(request.existing_skill)

    messages: list[dict] = list(request.conversation_history or [])
    messages.append({"role": "user", "content": request.message})

    all_messages = [{"role": "system", "content": system_prompt}] + messages

    start_time = time.time()

    try:
        for _round in range(MAX_SKILL_BUILDER_ROUNDS):
            response = client.chat.completions.create(
                model=request.model,
                messages=all_messages,
                tools=[SET_SKILL_FILES_TOOL],
                temperature=0.3,
                stream=False,
            )

            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            choice = response.choices[0] if response.choices else None
            if not choice:
                yield f"data: {json.dumps({'type': 'error', 'message': 'No response from model'})}\n\n"
                return

            msg = choice.message
            usage = getattr(response, "usage", None)

            record_llm_trace(
                context=trace_context,
                request_type="chat.completions",
                request={"model": request.model, "messages": all_messages},
                response={"content": msg.content or "", "model": request.model},
                model=request.model,
                provider=provider,
                error=None,
                elapsed_ms=elapsed_ms,
                prompt_tokens=usage.prompt_tokens if usage else None,
                completion_tokens=usage.completion_tokens if usage else None,
                total_tokens=usage.total_tokens if usage else None,
            )

            if msg.content:
                yield f"data: {json.dumps({'type': 'text_chunk', 'content': msg.content})}\n\n"

            if not msg.tool_calls:
                break

            # Append assistant turn with tool_calls
            all_messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                if tc.function.name == "set_skill_files":
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    files = args.get("files", [])
                    yield f"data: {json.dumps({'type': 'skill_files_update', 'files': files})}\n\n"

                all_messages.append(
                    {
                        "role": "tool",
                        "content": "Files updated successfully.",
                        "tool_call_id": tc.id,
                    }
                )

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as exc:
        logger.exception("Skill builder error: %s", exc)
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/skill-builder")
async def skill_builder_stream(
    request: SkillBuilderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream skill builder AI responses via SSE."""
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
```

- [ ] **Step 2: Verify the file lints cleanly**

```bash
cd backend && uv run ruff check app/api/skill_builder.py
```

Expected: no errors.

---

## Task 4: Backend tests

**Files:**
- Create: `backend/tests/test_skill_builder.py`

- [ ] **Step 1: Create tests**

```python
"""Unit tests for the Skill Builder endpoint helpers."""

import json
import unittest

from app.api.skill_builder import (
    SkillBuilderFile,
    SkillBuilderSkill,
    build_skill_builder_prompt,
    run_skill_builder,
)


class TestBuildSkillBuilderPrompt(unittest.TestCase):
    """build_skill_builder_prompt returns correct content for new and edit modes."""

    def test_new_skill_prompt_contains_dsl(self) -> None:
        prompt = build_skill_builder_prompt(None)
        self.assertIn("SKILL.md", prompt)
        self.assertIn("def execute(params", prompt)
        self.assertIn("reportlab", prompt)
        self.assertIn("NEVER embed font", prompt)

    def test_new_skill_prompt_mentions_new_skill(self) -> None:
        prompt = build_skill_builder_prompt(None)
        self.assertIn("NEW skill", prompt)

    def test_edit_skill_prompt_contains_skill_name(self) -> None:
        skill = SkillBuilderSkill(
            name="pdf-generator",
            files=[
                SkillBuilderFile(
                    path="SKILL.md",
                    content="---\nname: pdf-generator\n---\nGenerates PDFs.",
                )
            ],
        )
        prompt = build_skill_builder_prompt(skill)
        self.assertIn("pdf-generator", prompt)
        self.assertIn("Generates PDFs.", prompt)

    def test_edit_skill_prompt_includes_file_contents(self) -> None:
        skill = SkillBuilderSkill(
            name="my-skill",
            files=[
                SkillBuilderFile(path="SKILL.md", content="# SKILL"),
                SkillBuilderFile(path="main.py", content="def execute(p, f): return {}"),
            ],
        )
        prompt = build_skill_builder_prompt(skill)
        self.assertIn("main.py", prompt)
        self.assertIn("def execute(p, f)", prompt)


class TestRunSkillBuilderGenerator(unittest.IsolatedAsyncioTestCase):
    """run_skill_builder emits correct SSE event types."""

    async def _collect(self, gen) -> list[dict]:
        events = []
        async for line in gen:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    async def test_emits_text_chunk_and_done_when_no_tool_calls(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        # Fake OpenAI response: content only, no tool calls
        fake_msg = SimpleNamespace(content="Here is your skill.", tool_calls=None)
        fake_choice = SimpleNamespace(message=fake_msg)
        fake_usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        fake_response = SimpleNamespace(choices=[fake_choice], usage=fake_usage)

        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = fake_response

        from app.api.skill_builder import SkillBuilderRequest
        from app.services.llm_trace import LLMTraceContext
        import uuid

        request = SkillBuilderRequest(
            credential_id="cred-1",
            model="gpt-4o",
            message="Make me a skill that says hello.",
        )
        trace = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            workflow_id=None,
            node_label="Skill Builder",
            source="skill_builder",
        )

        with unittest.mock.patch("app.api.skill_builder.record_llm_trace"):
            events = await self._collect(
                run_skill_builder(fake_client, request, trace, "openai")
            )

        types = [e["type"] for e in events]
        self.assertIn("text_chunk", types)
        self.assertIn("done", types)
        self.assertEqual(events[-1]["type"], "done")

    async def test_emits_skill_files_update_when_tool_called(self) -> None:
        import unittest.mock
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        files_payload = [
            {"path": "SKILL.md", "content": "---\nname: hello\n---"},
            {"path": "main.py", "content": "def execute(p, f): return {'msg': 'hi'}"},
        ]

        # Round 1: tool call
        tool_call = SimpleNamespace(
            id="tc-1",
            function=SimpleNamespace(
                name="set_skill_files",
                arguments=json.dumps({"files": files_payload}),
            ),
        )
        msg_with_tool = SimpleNamespace(content=None, tool_calls=[tool_call])

        # Round 2: final content, no tool calls
        msg_final = SimpleNamespace(content="Done! Skill is ready.", tool_calls=None)

        fake_usage = SimpleNamespace(prompt_tokens=5, completion_tokens=5, total_tokens=10)
        r1 = SimpleNamespace(choices=[SimpleNamespace(message=msg_with_tool)], usage=fake_usage)
        r2 = SimpleNamespace(choices=[SimpleNamespace(message=msg_final)], usage=fake_usage)

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [r1, r2]

        from app.api.skill_builder import SkillBuilderRequest
        from app.services.llm_trace import LLMTraceContext
        import uuid

        request = SkillBuilderRequest(
            credential_id="cred-1",
            model="gpt-4o",
            message="Create a hello skill.",
        )
        trace = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            workflow_id=None,
            node_label="Skill Builder",
            source="skill_builder",
        )

        with unittest.mock.patch("app.api.skill_builder.record_llm_trace"):
            events = await self._collect(
                run_skill_builder(fake_client, request, trace, "openai")
            )

        types = [e["type"] for e in events]
        self.assertIn("skill_files_update", types)
        self.assertIn("text_chunk", types)
        self.assertIn("done", types)

        update_event = next(e for e in events if e["type"] == "skill_files_update")
        self.assertEqual(len(update_event["files"]), 2)
        self.assertEqual(update_event["files"][0]["path"], "SKILL.md")
```

- [ ] **Step 2: Run tests**

```bash
cd backend && uv run pytest tests/test_skill_builder.py -v
```

Expected: all 4 tests PASS.

---

## Task 5: Register router in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add import and router registration**

In `backend/app/main.py`, add the import after the `ai_assistant` import line (around line 15):

```python
from app.api import (
    ...
    skill_builder,
    ...
)
```

Then add router registration after the `ai_assistant` router line (line 183):

```python
app.include_router(skill_builder.router, prefix="/api/ai", tags=["Skill Builder"])
```

- [ ] **Step 2: Run all tests to confirm nothing broke**

```bash
cd backend && ./run_tests.sh
```

Expected: all suites pass.

- [ ] **Step 3: Commit backend**

```bash
git add backend/app/api/skill_builder.py backend/tests/test_skill_builder.py backend/app/main.py
git commit -m "feat: add skill builder SSE endpoint at /api/ai/skill-builder

Non-streaming tool-use loop with set_skill_files tool. Emits text_chunk,
skill_files_update, and done SSE events. Traced as skill_builder.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Frontend service — skillBuilderApi.ts

**Files:**
- Create: `frontend/src/services/skillBuilderApi.ts`

- [ ] **Step 1: Create the file**

```typescript
import { heymClientHeaders } from "@/constants/httpIdentity";

export interface SkillBuilderFile {
  path: string;
  content: string;
}

export interface SkillBuilderExistingSkill {
  name: string;
  files: SkillBuilderFile[];
}

export interface SkillBuilderRequest {
  credentialId: string;
  model: string;
  message: string;
  existingSkill?: SkillBuilderExistingSkill;
  conversationHistory?: { role: string; content: string }[];
}

export function skillBuilderStream(
  request: SkillBuilderRequest,
  onChunk: (text: string) => void,
  onFilesUpdate: (files: SkillBuilderFile[]) => void,
  onDone: () => void,
  onError: (error: Error) => void,
  signal?: AbortSignal,
): void {
  const API_URL = import.meta.env.VITE_API_URL || "";

  fetch(`${API_URL}/api/ai/skill-builder`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...heymClientHeaders,
    },
    body: JSON.stringify({
      credential_id: request.credentialId,
      model: request.model,
      message: request.message,
      existing_skill: request.existingSkill ?? null,
      conversation_history: request.conversationHistory ?? null,
    }),
    signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
          (errorData as { detail?: string }).detail ||
            `HTTP error! status: ${response.status}`,
        );
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = JSON.parse(line.slice(6)) as {
            type: string;
            content?: string;
            files?: SkillBuilderFile[];
            message?: string;
          };

          if (data.type === "text_chunk" && data.content !== undefined) {
            onChunk(data.content);
          } else if (data.type === "skill_files_update" && data.files !== undefined) {
            onFilesUpdate(data.files);
          } else if (data.type === "done") {
            onDone();
          } else if (data.type === "error") {
            throw new Error(data.message ?? "Unknown error");
          }
        }
      }
    })
    .catch(onError);
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: 0 errors.

---

## Task 7: Frontend composable — useSkillBuilder.ts

**Files:**
- Create: `frontend/src/composables/useSkillBuilder.ts`

- [ ] **Step 1: Create the file**

```typescript
import { ref } from "vue";

import type { SkillBuilderExistingSkill, SkillBuilderFile } from "@/services/skillBuilderApi";
import { skillBuilderStream } from "@/services/skillBuilderApi";

export interface SkillChatMessage {
  role: "user" | "assistant";
  content: string;
}

export function useSkillBuilder() {
  const messages = ref<SkillChatMessage[]>([]);
  const currentFiles = ref<SkillBuilderFile[]>([]);
  const isStreaming = ref(false);
  const error = ref<string | null>(null);
  const abortController = ref<AbortController | null>(null);

  function reset(): void {
    abortController.value?.abort();
    abortController.value = null;
    messages.value = [];
    currentFiles.value = [];
    isStreaming.value = false;
    error.value = null;
  }

  function sendMessage(
    text: string,
    credentialId: string,
    model: string,
    existingSkill?: SkillBuilderExistingSkill,
  ): void {
    if (isStreaming.value) return;

    messages.value.push({ role: "user", content: text });
    const assistantMsg: SkillChatMessage = { role: "assistant", content: "" };
    messages.value.push(assistantMsg);

    isStreaming.value = true;
    error.value = null;

    const history = messages.value
      .slice(0, -2)
      .map((m) => ({ role: m.role, content: m.content }));

    abortController.value = new AbortController();

    skillBuilderStream(
      {
        credentialId,
        model,
        message: text,
        existingSkill,
        conversationHistory: history,
      },
      (chunk) => {
        assistantMsg.content += chunk;
      },
      (files) => {
        currentFiles.value = files;
      },
      () => {
        isStreaming.value = false;
      },
      (err) => {
        error.value = err.message;
        isStreaming.value = false;
        if (!assistantMsg.content) {
          messages.value.pop();
        }
      },
      abortController.value.signal,
    );
  }

  return { messages, currentFiles, isStreaming, error, reset, sendMessage };
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: 0 errors.

---

## Task 8: Frontend component — SkillBuilderModal.vue

**Files:**
- Create: `frontend/src/components/Panels/SkillBuilderModal.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";

import { Button } from "@/components/ui/button";
import { extractNameFromFrontmatter } from "@/lib/skillZipParser";
import type { SkillBuilderExistingSkill, SkillBuilderFile } from "@/services/skillBuilderApi";
import type { AgentSkill } from "@/types/workflow";
import { useSkillBuilder } from "@/composables/useSkillBuilder";

interface Props {
  open: boolean;
  credentialId: string;
  model: string;
  existingSkill?: AgentSkill;
}

interface Emits {
  (e: "update:open", value: boolean): void;
  (e: "save", skill: AgentSkill): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const { messages, currentFiles, isStreaming, error, reset, sendMessage } = useSkillBuilder();

const inputText = ref("");
const messagesContainer = ref<HTMLElement | null>(null);
const activeFileIndex = ref(0);

// ---------------------------------------------------------------------------
// Derived existing skill (only .md and .py files sent to API)
// ---------------------------------------------------------------------------

const existingSkillForApi = computed<SkillBuilderExistingSkill | undefined>(() => {
  if (!props.existingSkill) return undefined;
  const files: SkillBuilderFile[] = [
    { path: "SKILL.md", content: props.existingSkill.content },
    ...(props.existingSkill.files ?? [])
      .filter((f) => f.path.endsWith(".py"))
      .map((f) => ({ path: f.path, content: f.content })),
  ];
  return { name: props.existingSkill.name, files };
});

// ---------------------------------------------------------------------------
// Lifecycle — reset on open, pre-fill files when editing
// ---------------------------------------------------------------------------

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    reset();
    activeFileIndex.value = 0;

    if (existingSkillForApi.value) {
      currentFiles.value = existingSkillForApi.value.files;
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  reset();
});

// ---------------------------------------------------------------------------
// Scroll chat to bottom on new messages
// ---------------------------------------------------------------------------

watch(
  messages,
  () => {
    nextTick(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight;
      }
    });
  },
  { deep: true },
);

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function close(): void {
  emit("update:open", false);
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape") close();
}

function submit(): void {
  const text = inputText.value.trim();
  if (!text || isStreaming.value) return;
  inputText.value = "";
  sendMessage(text, props.credentialId, props.model, existingSkillForApi.value);
}

const canSave = computed(() => currentFiles.value.length > 0);

function buildSkillFromFiles(): AgentSkill {
  const skillMd = currentFiles.value.find(
    (f) => f.path === "SKILL.md" || f.path.toLowerCase().endsWith("skill.md"),
  );
  const otherFiles = currentFiles.value.filter((f) => f !== skillMd);
  const name = skillMd
    ? (extractNameFromFrontmatter(skillMd.content) || props.existingSkill?.name || "skill")
    : (props.existingSkill?.name || "skill");

  return {
    id: props.existingSkill?.id ?? crypto.randomUUID(),
    name,
    content: skillMd?.content ?? "",
    files: otherFiles.map((f) => ({
      path: f.path,
      content: f.content,
      encoding: "text" as const,
      mimeType: "text/plain",
    })),
    timeoutSeconds: props.existingSkill?.timeoutSeconds ?? 30,
  };
}

function save(): void {
  if (!canSave.value) return;
  emit("save", buildSkillFromFiles());
  close();
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

const modalTitle = computed(() =>
  props.existingSkill ? `Edit: ${props.existingSkill.name}` : "New Skill",
);

const activeFileContent = computed(
  () => currentFiles.value[activeFileIndex.value]?.content ?? "",
);
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      @keydown="handleKeydown"
      @click.self="close"
    >
      <div
        class="relative flex flex-col bg-background rounded-xl shadow-2xl overflow-hidden"
        style="width: min(90vw, 900px); height: min(85vh, 700px)"
        @click.stop
      >
        <!-- Header -->
        <div
          class="flex items-center gap-2 px-4 py-3 border-b bg-muted/40 shrink-0"
        >
          <span class="text-purple-500 text-base">✨</span>
          <span class="font-semibold text-sm">Skill Builder</span>
          <span class="text-xs text-muted-foreground ml-1">{{ modalTitle }}</span>
          <Button
            variant="ghost"
            size="sm"
            class="ml-auto h-7 w-7 p-0"
            @click="close"
          >
            ✕
          </Button>
        </div>

        <!-- Body: chat (left) + files (right) -->
        <div class="flex flex-1 min-h-0">
          <!-- Chat panel -->
          <div class="flex flex-1 flex-col min-w-0 border-r">
            <!-- Messages -->
            <div
              ref="messagesContainer"
              class="flex-1 overflow-y-auto p-4 space-y-3"
            >
              <div
                v-if="messages.length === 0"
                class="text-sm text-muted-foreground text-center mt-8"
              >
                {{ existingSkill
                  ? `Editing "${existingSkill.name}". Describe your changes.`
                  : "Describe the skill you want to build."
                }}
              </div>
              <div
                v-for="(msg, i) in messages"
                :key="i"
                :class="[
                  'max-w-[85%] rounded-lg px-3 py-2 text-sm whitespace-pre-wrap break-words',
                  msg.role === 'user'
                    ? 'bg-muted self-start'
                    : 'bg-purple-600 text-white self-end ml-auto',
                ]"
              >
                {{ msg.content }}
                <span
                  v-if="msg.role === 'assistant' && isStreaming && i === messages.length - 1 && !msg.content"
                  class="inline-block w-2 h-4 bg-white animate-pulse rounded-sm"
                />
              </div>
            </div>

            <!-- Error -->
            <p
              v-if="error"
              class="text-xs text-destructive px-4 pb-1"
            >
              {{ error }}
            </p>

            <!-- Input -->
            <div class="flex gap-2 p-3 border-t shrink-0">
              <input
                v-model="inputText"
                class="flex-1 border rounded-md px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-purple-400 bg-background"
                placeholder="Describe or ask for changes..."
                :disabled="isStreaming"
                @keydown.enter.prevent="submit"
              />
              <Button
                size="sm"
                class="bg-purple-600 hover:bg-purple-700 text-white"
                :disabled="isStreaming || !inputText.trim()"
                @click="submit"
              >
                →
              </Button>
            </div>
          </div>

          <!-- Files panel -->
          <div class="flex flex-col shrink-0 w-64">
            <!-- File tabs -->
            <div class="flex gap-1 px-3 pt-3 flex-wrap shrink-0">
              <button
                v-for="(file, idx) in currentFiles"
                :key="file.path"
                type="button"
                :class="[
                  'text-xs rounded px-2 py-1 border transition-colors',
                  idx === activeFileIndex
                    ? 'bg-purple-100 border-purple-400 text-purple-700'
                    : 'bg-muted border-transparent text-muted-foreground hover:border-border',
                ]"
                @click="activeFileIndex = idx"
              >
                {{ file.path }}
              </button>
            </div>

            <!-- Code viewer -->
            <div class="flex-1 min-h-0 overflow-y-auto p-3">
              <pre
                v-if="currentFiles.length > 0"
                class="text-xs font-mono whitespace-pre-wrap break-all text-foreground"
              >{{ activeFileContent }}</pre>
              <p
                v-else
                class="text-xs text-muted-foreground text-center mt-8"
              >
                Files will appear here once the AI generates them.
              </p>
            </div>

            <!-- Save button -->
            <div class="p-3 border-t shrink-0">
              <Button
                class="w-full bg-purple-600 hover:bg-purple-700 text-white"
                size="sm"
                :disabled="!canSave || isStreaming"
                @click="save"
              >
                Kaydet &amp; Ekle
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: 0 errors.

---

## Task 9: Integrate SkillBuilderModal into PropertiesPanel.vue

**Files:**
- Modify: `frontend/src/components/Panels/PropertiesPanel.vue`

- [ ] **Step 1: Add import**

In the `<script setup>` block, find where other local components are imported (search for existing `import.*from "@/components/Panels`) and add:

```typescript
import SkillBuilderModal from "@/components/Panels/SkillBuilderModal.vue";
```

Also import the `AgentSkill` type if not already imported at the top with the workflow types import.

- [ ] **Step 2: Add reactive state for modal**

Find the section where `expandedSkillIds` is declared (around line 2096) and add below it:

```typescript
const skillBuilderOpen = ref(false);
const skillBuilderTargetSkill = ref<AgentSkill | undefined>(undefined);
```

- [ ] **Step 3: Add handler functions**

Below the `toggleSkillExpanded` function (around line 2098), add:

```typescript
function openSkillBuilderNew(): void {
  skillBuilderTargetSkill.value = undefined;
  skillBuilderOpen.value = true;
}

function openSkillBuilderEdit(skill: AgentSkill): void {
  skillBuilderTargetSkill.value = skill;
  skillBuilderOpen.value = true;
}

function handleSkillBuilderSave(newSkill: AgentSkill): void {
  if (!selectedNode.value) return;
  const current: AgentSkill[] = selectedNode.value.data.skills || [];
  if (skillBuilderTargetSkill.value) {
    // Replace existing skill matched by id
    const updated = current.map((s) =>
      s.id === skillBuilderTargetSkill.value!.id ? newSkill : s,
    );
    updateNodeData("skills", updated);
  } else {
    // Add new skill
    updateNodeData("skills", [...current, newSkill]);
  }
}
```

- [ ] **Step 4: Add "✨ AI Build" button to Skills header**

Find the Skills header section (around line 3716–3729):

```html
<div class="flex items-center justify-between">
  <Label class="flex items-center gap-1">
    <BookOpen class="w-3.5 h-3.5" />
    Skills
  </Label>
  <Button
    variant="outline"
    size="sm"
    class="gap-1"
    @click="addAgentSkill"
  >
    <Plus class="w-3.5 h-3.5" />
    Add Skill
  </Button>
</div>
```

Replace with:

```html
<div class="flex items-center justify-between">
  <Label class="flex items-center gap-1">
    <BookOpen class="w-3.5 h-3.5" />
    Skills
  </Label>
  <div class="flex gap-1">
    <Button
      variant="outline"
      size="sm"
      class="gap-1"
      @click="addAgentSkill"
    >
      <Plus class="w-3.5 h-3.5" />
      Add Skill
    </Button>
    <Button
      variant="outline"
      size="sm"
      class="gap-1 border-purple-300 text-purple-600 hover:bg-purple-50 hover:text-purple-700"
      :disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
      @click="openSkillBuilderNew"
    >
      ✨ AI Build
    </Button>
  </div>
</div>
```

- [ ] **Step 5: Add "✨" icon to each skill card**

Find the skill card remove button (around line 3772–3780):

```html
<Button
  variant="ghost"
  size="sm"
  class="gap-1 text-destructive hover:text-destructive hover:bg-destructive/10"
  @click="removeAgentSkill(idx)"
>
  <Trash2 class="w-3.5 h-3.5" />
  Remove
</Button>
```

Replace with:

```html
<div class="flex gap-1">
  <Button
    variant="ghost"
    size="sm"
    class="h-7 w-7 p-0 text-purple-500 hover:text-purple-700 hover:bg-purple-50"
    :disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
    :title="'Edit with AI'"
    @click="openSkillBuilderEdit(skill)"
  >
    ✨
  </Button>
  <Button
    variant="ghost"
    size="sm"
    class="gap-1 text-destructive hover:text-destructive hover:bg-destructive/10"
    @click="removeAgentSkill(idx)"
  >
    <Trash2 class="w-3.5 h-3.5" />
    Remove
  </Button>
</div>
```

- [ ] **Step 6: Mount the modal**

Find the end of the `<template>` section (the closing `</template>` tag) and add the modal just before it:

```html
<SkillBuilderModal
  v-model:open="skillBuilderOpen"
  :credential-id="selectedNode?.data?.credentialId || ''"
  :model="selectedNode?.data?.model || ''"
  :existing-skill="skillBuilderTargetSkill"
  @save="handleSkillBuilderSave"
/>
```

- [ ] **Step 7: Lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: 0 errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/skillZipParser.ts \
        frontend/src/services/skillBuilderApi.ts \
        frontend/src/composables/useSkillBuilder.ts \
        frontend/src/components/Panels/SkillBuilderModal.vue \
        frontend/src/components/Panels/PropertiesPanel.vue
git commit -m "feat: add skill builder modal to agent node properties panel

Adds ✨ AI Build button (new skill) and per-skill ✨ icon (edit)
to the Skills section. Opens a modal with chat + file preview.
AI generates SKILL.md + .py files; user saves them to the node.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: Final verification

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && ./run_tests.sh
```

Expected: all suites pass.

- [ ] **Step 2: Run frontend checks**

```bash
cd frontend && rm -rf dist && bun run lint && bun run typecheck && bun run build
```

Expected: lint clean, typecheck 0 errors, build succeeds.

- [ ] **Step 3: Manual smoke test**

1. Start the app: `./run.sh`
2. Open a workflow with an Agent node.
3. Select the Agent node → confirm `credentialId` and `model` are set.
4. Open AI Builder → send a message referencing the workflow → confirm no 128k error even with large skill files loaded.
5. In Skills section, click `✨ AI Build` → modal opens with "New Skill" title.
6. Type "Create a skill that generates a simple PDF with Helvetica font" → AI responds and files appear in the right panel.
7. Click `Kaydet & Ekle` → skill appears in the Skills list.
8. Click `✨` on the newly created skill → modal opens with "Edit: <name>" title and pre-filled files.
9. ESC closes modal without saving.
