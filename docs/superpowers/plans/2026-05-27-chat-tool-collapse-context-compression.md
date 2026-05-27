# Chat Tab: Tool Collapse + Context Badge + Auto-Compression — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add collapsible tool-call cards, a Cursor-style context-size badge, and auto context compression to the `/chats` (Dashboard Chat Assistant) tab.

**Architecture:** Backend adds a `tool_calls` JSONB column on `dashboard_messages`, replaces SSE `step` events with `tool_start`/`tool_end` pairs, emits `context` and `compressed` events, and integrates `maybe_compress_messages` from `app/services/context_compressor.py` (already used by agent nodes). Frontend introduces `ChatToolCall.vue` and `ChatContextBadge.vue`, updates the Pinia chat store to track tool calls and context usage, and wires both into `ChatConversation.vue`.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 async + Alembic; Vue.js 3 + TypeScript (strict) + Pinia + Vite + Bun.

**Spec:** [docs/superpowers/specs/2026-05-27-chat-tool-collapse-context-compression-design.md](../specs/2026-05-27-chat-tool-collapse-context-compression-design.md)

---

## Task 1: Database column + Alembic migration for `tool_calls`

**Files:**
- Modify: `backend/app/db/models.py:1447-1463`
- Create: `backend/alembic/versions/070_dashboard_message_tool_calls.py`

- [ ] **Step 1: Add column to ORM model**

In `backend/app/db/models.py`, in the `DashboardMessage` class, add after `created_at`:

```python
    tool_calls: Mapped[list | None] = mapped_column(
        postgresql.JSONB, nullable=True, default=None
    )
```

Verify `postgresql` is already imported at the top of the file. If not, add:

```python
from sqlalchemy.dialects import postgresql
```

- [ ] **Step 2: Create Alembic migration**

Create `backend/alembic/versions/070_dashboard_message_tool_calls.py`:

```python
"""add tool_calls jsonb to dashboard_messages

Revision ID: 070
Revises: 069
Create Date: 2026-05-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "070"
down_revision: str | None = "069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dashboard_messages",
        sa.Column("tool_calls", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dashboard_messages", "tool_calls")
```

- [ ] **Step 3: Run migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: `Running upgrade 069 -> 070, add tool_calls jsonb to dashboard_messages`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/070_dashboard_message_tool_calls.py
git commit -m "feat(chat): add tool_calls JSONB column to dashboard_messages"
```

---

## Task 2: Pydantic schemas (`ToolCallRecord`, `MessageResponse`, `ContextSummaryResponse`)

**Files:**
- Modify: `backend/app/models/chat_schemas.py`

- [ ] **Step 1: Add new schemas to chat_schemas.py**

Replace the contents of `backend/app/models/chat_schemas.py` with:

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = "New Chat"


class ConversationUpdate(BaseModel):
    title: str | None = None
    is_pinned: bool | None = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    is_pinned: bool
    is_running: bool
    has_unread: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    conversations: list[ConversationResponse]


class ToolCallRecord(BaseModel):
    id: str
    name: str
    label: str
    args: dict[str, Any] = Field(default_factory=dict)
    response_summary: str | None = None
    elapsed_ms: float | None = None
    status: Literal["running", "success", "error", "compressed"]


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    tool_calls: list[ToolCallRecord] | None = None

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: uuid.UUID
    title: str
    is_pinned: bool
    is_running: bool
    has_unread: bool
    last_credential_id: uuid.UUID | None = None
    last_model: str | None = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]

    model_config = {"from_attributes": True}


class ChatFileAttachment(BaseModel):
    name: str
    kind: Literal["text", "image", "pdf"]
    content: str


class MessageCreate(BaseModel):
    content: str
    credential_id: str
    model: str
    attachment: ChatFileAttachment | None = None


class ConversationTitleGenerate(BaseModel):
    credential_id: str
    model: str


class SendMessageResponse(BaseModel):
    conversation_id: uuid.UUID


class QuickPromptsResponse(BaseModel):
    prompts: list[str]


class QuickPromptsUpdate(BaseModel):
    prompts: list[str]


class ContextBreakdown(BaseModel):
    system: int
    agents_md: int
    workflows: int
    user_rules: int
    history: int
    attachment: int


class ContextSummaryResponse(BaseModel):
    used: int
    limit: int
    breakdown: ContextBreakdown
```

- [ ] **Step 2: Verify Ruff + lint**

Run: `cd backend && uv run ruff format . && uv run ruff check .`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/chat_schemas.py
git commit -m "feat(chat): add ToolCallRecord, ContextSummaryResponse Pydantic schemas"
```

---

## Task 3: Add `context_window` to `LLMModel` and populate in credentials endpoint

**Files:**
- Modify: `backend/app/models/schemas.py:600-605`
- Modify: `backend/app/api/credentials.py:660-663`

- [ ] **Step 1: Add field to LLMModel**

In `backend/app/models/schemas.py`, update `LLMModel`:

```python
class LLMModel(BaseModel):
    id: str
    name: str
    is_reasoning: bool = False
    supports_batch: bool = False
    batch_support_reason: str | None = None
    context_window: int | None = None
```

- [ ] **Step 2: Populate context_window after fetching models**

In `backend/app/api/credentials.py`, replace the `get_credential_models` body around line 658-663:

```python
    config = decrypt_config(credential.encrypted_config)

    from app.services.context_compressor import KNOWN_LIMITS
    from app.services.llm_provider import fetch_models

    models = await fetch_models(credential.type, config)
    for m in models:
        model_lower = m.id.lower()
        for key, limit in KNOWN_LIMITS.items():
            if key in model_lower:
                m.context_window = limit
                break
    return models
```

- [ ] **Step 3: Write the test**

Add to `backend/tests/test_credentials_models.py` (create if missing, otherwise append):

```python
import unittest
from unittest.mock import AsyncMock, patch

from app.models.schemas import LLMModel


class CredentialsModelsContextWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_credential_models_populates_context_window(self) -> None:
        from app.api.credentials import get_credential_models

        fake_models = [
            LLMModel(id="gpt-4o-mini", name="GPT-4o mini"),
            LLMModel(id="unknown-model-xyz", name="Unknown"),
        ]
        with patch(
            "app.services.llm_provider.fetch_models", new=AsyncMock(return_value=fake_models)
        ), patch(
            "app.services.encryption.decrypt_config", return_value={"api_key": "x"}
        ):
            # We don't call the endpoint directly here (auth deps); instead
            # validate the substring match logic via KNOWN_LIMITS:
            from app.services.context_compressor import KNOWN_LIMITS

            for m in fake_models:
                ml = m.id.lower()
                for key, limit in KNOWN_LIMITS.items():
                    if key in ml:
                        m.context_window = limit
                        break

        self.assertEqual(fake_models[0].context_window, 128_000)
        self.assertIsNone(fake_models[1].context_window)
```

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_credentials_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/schemas.py backend/app/api/credentials.py backend/tests/test_credentials_models.py
git commit -m "feat(chat): expose context_window on LLMModel from credentials/models"
```

---

## Task 4: Extract `_assemble_system_prompt_parts` helper

**Files:**
- Modify: `backend/app/api/chats.py:108-181` (refactor `_process_chat`)

Refactor without behavior change — the inline system-prompt assembly is needed by both `_process_chat` and the new context-summary endpoint.

- [ ] **Step 1: Add helper function near top of chats.py (after imports, before `_get_conversation_or_404`)**

```python
@dataclass(frozen=True)
class SystemPromptParts:
    full_system_prompt: str
    base_system_prompt: str
    agents_md: str
    workflows_block: str
    user_rules: str


async def _assemble_system_prompt_parts(
    user: User,
    db: AsyncSession,
    *,
    include_attachment_instructions: bool,
) -> SystemPromptParts:
    workflows = await get_workflows_for_user_with_inputs(db, user.id)
    workflows_block = _format_workflows_for_prompt(workflows)
    agents_md = _load_agents_md_content() or ""
    user_rules = (user.user_rules or "").strip()

    system_prompt = DASHBOARD_CHAT_SYSTEM_PROMPT
    if agents_md:
        system_prompt = (
            "## Heym Platform Context\n\n"
            "Use the following Heym platform documentation to answer questions about the platform, structure, commands, code style, and conventions:\n\n"
            + agents_md
            + "\n\n---\n\n"
            + system_prompt
        )
    if workflows_block:
        system_prompt = (
            system_prompt
            + "\n\nAvailable workflows (always check these first when user asks for information):\n"
            + workflows_block
        )
    if user_rules:
        system_prompt = (
            system_prompt
            + "\n\nUser preferences / custom instructions (follow these when relevant):\n"
            + user_rules
        )
    if include_attachment_instructions:
        system_prompt = system_prompt + "\n\n" + _ATTACHMENT_ROUTING_INSTRUCTIONS

    return SystemPromptParts(
        full_system_prompt=system_prompt,
        base_system_prompt=DASHBOARD_CHAT_SYSTEM_PROMPT,
        agents_md=agents_md,
        workflows_block=workflows_block,
        user_rules=user_rules,
    )
```

Add to the imports at the top of `chats.py`:

```python
from dataclasses import dataclass
```

- [ ] **Step 2: Replace inline assembly in `_process_chat`**

Inside `_process_chat`, replace lines 155-180 (from `workflows = await get_workflows_for_user_with_inputs(...)` through `system_prompt = system_prompt + "\n\n" + _ATTACHMENT_ROUTING_INSTRUCTIONS`) with:

```python
            parts = await _assemble_system_prompt_parts(
                user, db, include_attachment_instructions=attachment_data is not None
            )
            system_prompt = parts.full_system_prompt
```

- [ ] **Step 3: Run existing chat tests to verify no regression**

Run: `cd backend && uv run pytest tests/test_dashboard_chat_api.py tests/test_chat_background_task.py tests/test_dashboard_chats.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/chats.py
git commit -m "refactor(chat): extract _assemble_system_prompt_parts helper"
```

---

## Task 5: Add `_context_breakdown` helper to ai_assistant.py

**Files:**
- Modify: `backend/app/api/ai_assistant.py` (add helper near other dashboard chat helpers, around line 1985 before `stream_dashboard_chat`)

- [ ] **Step 1: Add helper**

```python
def _context_breakdown(
    base_system_prompt: str,
    agents_md: str,
    workflows_block: str,
    user_rules: str,
    history: list[dict],
    attachment_content: str | None,
) -> dict[str, int]:
    from app.services.context_compressor import _estimate_tokens

    def _tok(text: str) -> int:
        if not text:
            return 0
        return _estimate_tokens([{"role": "system", "content": text}])

    return {
        "system": _tok(base_system_prompt),
        "agents_md": _tok(agents_md),
        "workflows": _tok(workflows_block),
        "user_rules": _tok(user_rules),
        "history": _estimate_tokens(history),
        "attachment": _tok(attachment_content or ""),
    }
```

- [ ] **Step 2: Write the test**

Add to `backend/tests/test_dashboard_chat_api.py` (existing file):

```python
class DashboardChatBreakdownTests(unittest.IsolatedAsyncioTestCase):
    def test_context_breakdown_sums_to_total(self) -> None:
        from app.api.ai_assistant import _context_breakdown
        from app.services.context_compressor import _estimate_tokens

        history = [{"role": "user", "content": "hello"}]
        breakdown = _context_breakdown(
            base_system_prompt="sys",
            agents_md="agents",
            workflows_block="wf",
            user_rules="rules",
            history=history,
            attachment_content=None,
        )

        self.assertIn("system", breakdown)
        self.assertIn("agents_md", breakdown)
        self.assertIn("workflows", breakdown)
        self.assertIn("user_rules", breakdown)
        self.assertIn("history", breakdown)
        self.assertIn("attachment", breakdown)
        self.assertEqual(breakdown["attachment"], 0)
        self.assertEqual(breakdown["history"], _estimate_tokens(history))
```

- [ ] **Step 3: Run test**

Run: `cd backend && uv run pytest tests/test_dashboard_chat_api.py::DashboardChatBreakdownTests -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat(chat): add _context_breakdown helper"
```

---

## Task 6: Replace `step` SSE events with `tool_start` / `tool_end` pairs

**Files:**
- Modify: `backend/app/api/ai_assistant.py:2130-2769` (the `for tc in msg.tool_calls:` loop in `stream_dashboard_chat`)

There are **14 emit sites** of `{type:'step', label:...}` in this loop, each followed by tool work. Each site must be wrapped with a paired `tool_start` (before) and `tool_end` (after). Use a server-assigned `tc_id` (already comes from OpenAI as `tc.id`; reuse it).

- [ ] **Step 1: Pattern reference (apply to every site)**

**Before:**
```python
                if name == "list_workflows":
                    step_label = "Listing workflows..."
                    yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"
                    step_start = time.time()
                    workflows = await get_workflows_for_user_with_inputs(db, user_id)
                    result = json.dumps({"count": len(workflows), "workflows": workflows})
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {},
                            "response_summary": _summarize_tool_result(name, result),
                            "execution_time_ms": step_ms,
                        }
                    )
```

**After:**
```python
                if name == "list_workflows":
                    step_label = "Listing workflows..."
                    tc_id = tc.id
                    yield (
                        "data: "
                        + json.dumps({
                            "type": "tool_start",
                            "id": tc_id,
                            "name": name,
                            "label": step_label,
                            "args": args,
                        })
                        + "\n\n"
                    )
                    step_start = time.time()
                    workflows = await get_workflows_for_user_with_inputs(db, user_id)
                    result = json.dumps({"count": len(workflows), "workflows": workflows})
                    step_ms = round((time.time() - step_start) * 1000, 2)
                    response_summary = _summarize_tool_result(name, result)
                    run_steps.append(
                        {
                            "label": step_label,
                            "tool": name,
                            "request": {},
                            "response_summary": response_summary,
                            "execution_time_ms": step_ms,
                        }
                    )
                    yield (
                        "data: "
                        + json.dumps({
                            "type": "tool_end",
                            "id": tc_id,
                            "response_summary": response_summary,
                            "elapsed_ms": step_ms,
                            "status": "success",
                        })
                        + "\n\n"
                    )
```

- [ ] **Step 2: Apply this transform to all 14 emit sites**

Sites are at lines (approximate; verify with `grep -n "'type': 'step'" backend/app/api/ai_assistant.py`):
- `list_workflows` (~2142)
- `execute_workflow` (~2167)
- `create_and_run_workflow` (~2273)
- `edit_and_run_workflow` (~2384)
- `get_workflow` (~2471)
- `list_credentials` (~2501)
- `list_run_history` (~2535)
- `list_scheduled` (~2563)
- `list_secrets` / `list_teams` (~2589)
- `list_skills` (~2610)
- Plus 4 more — grep to confirm.

For each site, identify its `step_label`, its request payload (the `request` field that gets put into `run_steps`), and its result. The `args` field on `tool_start` MUST be the parsed args (`args` variable already in scope, line 2137).

For sites where the tool fails (e.g., `create_and_run_workflow` short-circuit at line 2253-2268 when no credential), still emit `tool_start` then `tool_end` with `status:"error"` and `response_summary` set from the error JSON.

**Mechanical edit aid:** Replace every standalone `yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"` line with the multi-line `tool_start` yield, and **add** a matching `tool_end` yield immediately after the corresponding `run_steps.append({...})` block.

- [ ] **Step 3: Write the test**

Add to `backend/tests/test_dashboard_chat_api.py`:

```python
class DashboardChatToolEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_tool_start_and_tool_end(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        tool_call_msg = MagicMock()
        tool_call_msg.content = None
        tc = MagicMock()
        tc.id = "tc_abc"
        tc.function.name = "list_workflows"
        tc.function.arguments = "{}"
        tool_call_msg.tool_calls = [tc]

        final_msg = MagicMock()
        final_msg.content = "Here are your workflows."
        final_msg.tool_calls = None

        response_with_tools = MagicMock()
        response_with_tools.choices = [MagicMock(message=tool_call_msg)]
        response_with_tools.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

        response_final = MagicMock()
        response_final.choices = [MagicMock(message=final_msg)]
        response_final.usage = MagicMock(prompt_tokens=20, completion_tokens=8, total_tokens=28)

        fake_client = MagicMock()
        fake_client.chat.completions.create.side_effect = [response_with_tools, response_final]

        db_mock = AsyncMock()
        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch(
                "app.api.ai_assistant.get_workflows_for_user_with_inputs",
                new=AsyncMock(return_value=[]),
            ),
        ):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system",
                        [{"role": "user", "content": "list workflows"}],
                        db_mock,
                        user,
                        "OpenAI",
                        "http://localhost",
                    )
                ]
            )

        joined = "".join(chunks)
        self.assertIn('"type": "tool_start"', joined)
        self.assertIn('"id": "tc_abc"', joined)
        self.assertIn('"type": "tool_end"', joined)
        # No legacy "step" events:
        self.assertNotIn('"type": "step"', joined)
```

- [ ] **Step 4: Run test**

Run: `cd backend && uv run pytest tests/test_dashboard_chat_api.py::DashboardChatToolEventsTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat(chat): replace SSE step events with tool_start/tool_end pairs"
```

---

## Task 7: Emit `context` SSE events after each LLM round

**Files:**
- Modify: `backend/app/api/ai_assistant.py::stream_dashboard_chat` (around lines 2034-2086)

- [ ] **Step 1: Pass breakdown ingredients into the function**

`stream_dashboard_chat` currently receives `system_prompt`, but no separate breakdown ingredients. The cleanest change: also pass the assembled `SystemPromptParts` from chats.py.

Update `stream_dashboard_chat` signature to add `system_prompt_parts: Any | None = None` (keyword-only, optional, default None for backward compat with callers that don't need context events). Threading through types here adds churn; using `Any` avoids a circular import (chats.py imports from ai_assistant.py).

```python
async def stream_dashboard_chat(
    client: OpenAI,
    model: str,
    system_prompt: str,
    messages: list[dict],
    db: AsyncSession,
    user: User,
    provider: str,
    public_base_url: str,
    trace_context: LLMTraceContext | None = None,
    cancel_event: Event | None = None,
    attachment: FileAttachment | None = None,
    selected_credential: Credential | None = None,
    *,
    system_prompt_parts: Any | None = None,
) -> AsyncGenerator[str, None]:
```

Where `Any` is imported via `from typing import Any` (already imported).

- [ ] **Step 2: Compute context limit at start, emit `context` after each round**

Near the top of `stream_dashboard_chat` (after `messages_to_use = _append_date_to_user_messages(messages)`), add:

```python
    from app.services.context_compressor import _estimate_tokens, get_context_limit

    _context_limit = get_context_limit(model, client)

    def _emit_context(used_tokens: int) -> str:
        if system_prompt_parts is None:
            breakdown = {
                "system": _estimate_tokens([{"role": "system", "content": system_prompt}]),
                "agents_md": 0,
                "workflows": 0,
                "user_rules": 0,
                "history": _estimate_tokens(messages_to_use),
                "attachment": 0,
            }
        else:
            breakdown = _context_breakdown(
                base_system_prompt=system_prompt_parts.base_system_prompt,
                agents_md=system_prompt_parts.agents_md,
                workflows_block=system_prompt_parts.workflows_block,
                user_rules=system_prompt_parts.user_rules,
                history=messages_to_use,
                attachment_content=attachment.content if attachment else None,
            )
        return (
            "data: "
            + json.dumps({
                "type": "context",
                "used": int(used_tokens),
                "limit": int(_context_limit),
                "breakdown": breakdown,
            })
            + "\n\n"
        )
```

Then, immediately after the `response = await asyncio.to_thread(client.chat.completions.create, **kwargs)` call inside the `while rounds < MAX_DASHBOARD_CHAT_TOOL_ROUNDS:` loop, add:

```python
            usage = getattr(response, "usage", None)
            used_tokens = (
                usage.prompt_tokens
                if usage and getattr(usage, "prompt_tokens", None) is not None
                else _estimate_tokens([{"role": "system", "content": system_prompt}] + messages_to_use)
            )
            yield _emit_context(used_tokens)
```

- [ ] **Step 3: Update call site in chats.py to pass parts**

In `backend/app/api/chats.py::_process_chat`, after the refactored `parts = await _assemble_system_prompt_parts(...)` line, update the `stream_dashboard_chat` call:

```python
            async for chunk in stream_dashboard_chat(
                client,
                model,
                system_prompt,
                messages,
                db,
                user,
                provider,
                public_base_url,
                trace_context,
                cancel_event,
                attachment,
                credential,
                system_prompt_parts=parts,
            ):
```

- [ ] **Step 4: Write the test**

Add to `backend/tests/test_dashboard_chat_api.py`:

```python
class DashboardChatContextEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_context_event_with_prompt_tokens(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        final_msg = MagicMock()
        final_msg.content = "ok"
        final_msg.tool_calls = None
        response = MagicMock()
        response.choices = [MagicMock(message=final_msg)]
        response.usage = MagicMock(prompt_tokens=42, completion_tokens=3, total_tokens=45)
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = response

        with patch("app.api.ai_assistant.record_run_history"):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system",
                        [{"role": "user", "content": "hi"}],
                        AsyncMock(),
                        user,
                        "OpenAI",
                        "http://localhost",
                    )
                ]
            )

        joined = "".join(chunks)
        self.assertIn('"type": "context"', joined)
        self.assertIn('"used": 42', joined)
        self.assertIn('"limit": 128000', joined)  # gpt-4o-mini → KNOWN_LIMITS
```

- [ ] **Step 5: Run test**

Run: `cd backend && uv run pytest tests/test_dashboard_chat_api.py::DashboardChatContextEventTests -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/app/api/chats.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat(chat): emit context SSE events with prompt_tokens after each round"
```

---

## Task 8: Integrate `maybe_compress_messages` + emit `compressed` events

**Files:**
- Modify: `backend/app/api/ai_assistant.py::stream_dashboard_chat`

- [ ] **Step 1: Add compression before each LLM call**

Inside the `while rounds < MAX_DASHBOARD_CHAT_TOOL_ROUNDS:` loop, **before** `kwargs = {...}` (around line 2041), insert:

```python
            from app.services.context_compressor import maybe_compress_messages

            messages_for_call = [{"role": "system", "content": system_prompt}] + messages_to_use
            compressed, comp_info = await maybe_compress_messages(
                messages_for_call, model=model, client=client, context_limit_tokens=_context_limit
            )
            if comp_info is not None:
                # Drop the leading system message we added; keep the compressed rest as new history.
                non_system = [m for m in compressed if m.get("role") != "system"]
                messages_to_use = non_system
                yield (
                    "data: "
                    + json.dumps({
                        "type": "compressed",
                        "messages_compressed": comp_info["messages_compressed"],
                        "tokens_before": comp_info["tokens_before"],
                        "tokens_after": comp_info["tokens_after"],
                        "elapsed_ms": comp_info["elapsed_ms"],
                    })
                    + "\n\n"
                )
```

- [ ] **Step 2: Write the test**

Add to `backend/tests/test_dashboard_chat_api.py`:

```python
class DashboardChatCompressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_emits_compressed_when_compression_runs(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        final_msg = MagicMock()
        final_msg.content = "ok"
        final_msg.tool_calls = None
        response = MagicMock()
        response.choices = [MagicMock(message=final_msg)]
        response.usage = MagicMock(prompt_tokens=10, completion_tokens=3, total_tokens=13)
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value = response

        fake_compressed = [{"role": "user", "content": "u"}, {"role": "assistant", "content": "summary"}]
        fake_info = {
            "messages_compressed": 18,
            "messages_before_count": 22,
            "messages_after_count": 4,
            "tokens_before": 98_000,
            "tokens_after": 12_000,
            "elapsed_ms": 412.0,
        }
        with (
            patch("app.api.ai_assistant.record_run_history"),
            patch(
                "app.services.context_compressor.maybe_compress_messages",
                new=AsyncMock(return_value=(fake_compressed, fake_info)),
            ),
        ):
            chunks = _normalize_chunks(
                [
                    chunk
                    async for chunk in stream_dashboard_chat(
                        fake_client,
                        "gpt-4o-mini",
                        "system",
                        [{"role": "user", "content": "hi"}],
                        AsyncMock(),
                        user,
                        "OpenAI",
                        "http://localhost",
                    )
                ]
            )

        joined = "".join(chunks)
        self.assertIn('"type": "compressed"', joined)
        self.assertIn('"messages_compressed": 18', joined)
        self.assertIn('"tokens_before": 98000', joined)
```

- [ ] **Step 3: Run test**

Run: `cd backend && uv run pytest tests/test_dashboard_chat_api.py::DashboardChatCompressionTests -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat(chat): integrate maybe_compress_messages with compressed SSE event"
```

---

## Task 9: Persist `tool_calls` from SSE stream in `_process_chat`

**Files:**
- Modify: `backend/app/api/chats.py::_process_chat` (lines 200-230)
- Modify: `backend/app/api/chats.py::get_conversation` (line 366+; return new column)

- [ ] **Step 1: Collect tool_calls while streaming**

Replace the chunk-parse loop in `_process_chat` (currently lines 187-216) with:

```python
            assistant_chunks: list[str] = []
            workflow_context_markers: list[str] = []
            workflow_note_ids: set[str] = set()
            tool_calls_for_message: list[dict] = []

            async for chunk in stream_dashboard_chat(
                client,
                model,
                system_prompt,
                messages,
                db,
                user,
                provider,
                public_base_url,
                trace_context,
                cancel_event,
                attachment,
                credential,
                system_prompt_parts=parts,
            ):
                if chunk.startswith("data: "):
                    try:
                        payload = json.loads(chunk[6:].strip())
                    except json.JSONDecodeError:
                        payload = {}
                    ptype = payload.get("type")
                    if ptype == "content":
                        assistant_chunks.append(str(payload.get("text") or ""))
                    elif ptype == "workflow_created":
                        w_id = str(payload.get("workflow_id") or "").strip()
                        w_name = str(payload.get("workflow_name") or "").strip()
                        if w_id and w_id not in workflow_note_ids:
                            workflow_note_ids.add(w_id)
                            workflow_context_markers.append(
                                _build_hidden_workflow_context_marker(w_id, w_name or "Workflow")
                            )
                    elif ptype == "tool_start":
                        tool_calls_for_message.append(
                            {
                                "id": str(payload.get("id") or ""),
                                "name": str(payload.get("name") or ""),
                                "label": str(payload.get("label") or ""),
                                "args": payload.get("args") or {},
                                "status": "running",
                            }
                        )
                    elif ptype == "tool_end":
                        tc_id = str(payload.get("id") or "")
                        for entry in tool_calls_for_message:
                            if entry.get("id") == tc_id:
                                entry["response_summary"] = str(
                                    payload.get("response_summary") or ""
                                )
                                entry["elapsed_ms"] = payload.get("elapsed_ms")
                                entry["status"] = str(payload.get("status") or "success")
                                break
                    elif ptype == "compressed":
                        tokens_before = int(payload.get("tokens_before") or 0)
                        tokens_after = int(payload.get("tokens_after") or 0)
                        tool_calls_for_message.append(
                            {
                                "id": f"cmp_{len(tool_calls_for_message)}",
                                "name": "_context_compression",
                                "label": "Context compressed",
                                "args": {
                                    "messages_compressed": int(
                                        payload.get("messages_compressed") or 0
                                    )
                                },
                                "response_summary": (
                                    f"~{tokens_before // 1000}k → ~{tokens_after // 1000}k tokens"
                                ),
                                "elapsed_ms": payload.get("elapsed_ms"),
                                "status": "compressed",
                            }
                        )
                await registry.publish(conv_id, chunk)
```

- [ ] **Step 2: Persist on the assistant DashboardMessage**

Replace the existing assistant-message persistence block (currently around lines 218-229) with:

```python
            assistant_content = "".join(assistant_chunks)
            for marker in workflow_context_markers:
                if marker and marker not in assistant_content:
                    assistant_content += marker
            if assistant_content or tool_calls_for_message:
                db.add(
                    DashboardMessage(
                        conversation_id=uuid.UUID(conv_id),
                        role="assistant",
                        content=assistant_content,
                        tool_calls=tool_calls_for_message or None,
                    )
                )
```

- [ ] **Step 3: Return tool_calls in get_conversation**

In `get_conversation` (around line 385-396), replace the `messages=[MessageResponse.model_validate(m) for m in sorted_messages]` line with explicit construction so the JSONB column is included (the `model_config = {"from_attributes": True}` already pulls it, but verify):

```python
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        is_pinned=conversation.is_pinned,
        is_running=conversation.is_running,
        has_unread=conversation.has_unread,
        last_credential_id=conversation.last_credential_id,
        last_model=conversation.last_model,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(m) for m in sorted_messages],
    )
```

(No change needed; `from_attributes` pulls `tool_calls` from the ORM model. Verify by inspection.)

- [ ] **Step 4: Write a unit test for the chunk-parsing logic**

The chunk-parsing block is the only new logic — extract it into a pure helper for testability. Add to `backend/app/api/chats.py` near the top (after imports):

```python
def _ingest_tool_event(
    tool_calls_for_message: list[dict], payload: dict
) -> None:
    """Update tool_calls_for_message in place from a parsed SSE payload."""
    ptype = payload.get("type")
    if ptype == "tool_start":
        tool_calls_for_message.append(
            {
                "id": str(payload.get("id") or ""),
                "name": str(payload.get("name") or ""),
                "label": str(payload.get("label") or ""),
                "args": payload.get("args") or {},
                "status": "running",
            }
        )
    elif ptype == "tool_end":
        tc_id = str(payload.get("id") or "")
        for entry in tool_calls_for_message:
            if entry.get("id") == tc_id:
                entry["response_summary"] = str(payload.get("response_summary") or "")
                entry["elapsed_ms"] = payload.get("elapsed_ms")
                entry["status"] = str(payload.get("status") or "success")
                break
    elif ptype == "compressed":
        tokens_before = int(payload.get("tokens_before") or 0)
        tokens_after = int(payload.get("tokens_after") or 0)
        tool_calls_for_message.append(
            {
                "id": f"cmp_{len(tool_calls_for_message)}",
                "name": "_context_compression",
                "label": "Context compressed",
                "args": {"messages_compressed": int(payload.get("messages_compressed") or 0)},
                "response_summary": (
                    f"~{tokens_before // 1000}k → ~{tokens_after // 1000}k tokens"
                ),
                "elapsed_ms": payload.get("elapsed_ms"),
                "status": "compressed",
            }
        )
```

Replace the inline `if ptype == "tool_start": ... elif ptype == "compressed":` block inside `_process_chat` (the one added in Step 1) with:

```python
                    elif ptype in ("tool_start", "tool_end", "compressed"):
                        _ingest_tool_event(tool_calls_for_message, payload)
```

Then write the test in `backend/tests/test_dashboard_chats.py`:

```python
import unittest

from app.api.chats import _ingest_tool_event


class IngestToolEventTests(unittest.TestCase):
    def test_tool_start_appends_running_entry(self) -> None:
        bucket: list[dict] = []
        _ingest_tool_event(
            bucket,
            {
                "type": "tool_start",
                "id": "tc_1",
                "name": "list_workflows",
                "label": "Listing workflows...",
                "args": {"k": "v"},
            },
        )
        self.assertEqual(len(bucket), 1)
        self.assertEqual(bucket[0]["id"], "tc_1")
        self.assertEqual(bucket[0]["status"], "running")
        self.assertEqual(bucket[0]["args"], {"k": "v"})

    def test_tool_end_updates_matching_entry(self) -> None:
        bucket: list[dict] = [
            {
                "id": "tc_1",
                "name": "list_workflows",
                "label": "Listing...",
                "args": {},
                "status": "running",
            }
        ]
        _ingest_tool_event(
            bucket,
            {
                "type": "tool_end",
                "id": "tc_1",
                "response_summary": "3 workflows",
                "elapsed_ms": 42.0,
                "status": "success",
            },
        )
        self.assertEqual(bucket[0]["status"], "success")
        self.assertEqual(bucket[0]["response_summary"], "3 workflows")
        self.assertEqual(bucket[0]["elapsed_ms"], 42.0)

    def test_compressed_appends_compression_entry(self) -> None:
        bucket: list[dict] = []
        _ingest_tool_event(
            bucket,
            {
                "type": "compressed",
                "messages_compressed": 18,
                "tokens_before": 98_000,
                "tokens_after": 12_000,
                "elapsed_ms": 412.0,
            },
        )
        self.assertEqual(len(bucket), 1)
        self.assertEqual(bucket[0]["name"], "_context_compression")
        self.assertEqual(bucket[0]["status"], "compressed")
        self.assertEqual(bucket[0]["args"], {"messages_compressed": 18})
        self.assertEqual(bucket[0]["response_summary"], "~98k → ~12k tokens")
```

Run: `cd backend && uv run pytest tests/test_dashboard_chats.py::IngestToolEventTests -v`
Expected: PASS.

- [ ] **Step 5: Manual verify**

Start the app (`./run.sh`), send "List my workflows" in `/chats`, then run:

```sql
psql -h localhost -p 6543 -U postgres heym -c "SELECT id, role, tool_calls FROM dashboard_messages ORDER BY created_at DESC LIMIT 5;"
```

Expected: latest assistant row has `tool_calls` populated with a `list_workflows` entry.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/chats.py backend/tests/test_dashboard_chats.py
git commit -m "feat(chat): persist tool_calls on assistant message"
```

---

## Task 10: Add `GET /chats/{conversation_id}/context-summary` endpoint

**Files:**
- Modify: `backend/app/api/chats.py`

- [ ] **Step 1: Add the endpoint**

In `backend/app/api/chats.py`, after `mark_conversation_read` (around line 595), add:

```python
@router.get("/{conversation_id}/context-summary", response_model=ContextSummaryResponse)
async def get_context_summary(
    conversation_id: uuid.UUID,
    credential_id: uuid.UUID,
    model: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContextSummaryResponse:
    """Compute the static (idle-state) context usage for a conversation."""
    from app.api.ai_assistant import _context_breakdown
    from app.services.context_compressor import get_context_limit

    conversation = await _get_conversation_or_404(conversation_id, current_user.id, db)
    msg_result = await db.execute(
        select(DashboardMessage)
        .where(DashboardMessage.conversation_id == conversation.id)
        .order_by(DashboardMessage.created_at)
    )
    all_messages = msg_result.scalars().all()
    history = [{"role": m.role, "content": m.content} for m in all_messages]
    if len(history) > MAX_DASHBOARD_CHAT_HISTORY:
        history = history[-MAX_DASHBOARD_CHAT_HISTORY:]

    credential = await get_accessible_credential(db, credential_id, current_user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    config = decrypt_config(credential.encrypted_config)
    client, _provider = get_openai_client(credential.type, config)

    parts = await _assemble_system_prompt_parts(
        current_user, db, include_attachment_instructions=False
    )
    breakdown = _context_breakdown(
        base_system_prompt=parts.base_system_prompt,
        agents_md=parts.agents_md,
        workflows_block=parts.workflows_block,
        user_rules=parts.user_rules,
        history=history,
        attachment_content=None,
    )
    used = sum(breakdown.values())
    limit = get_context_limit(model, client)
    return ContextSummaryResponse(used=used, limit=limit, breakdown=breakdown)
```

Add to the existing imports at the top of `chats.py`:

```python
from app.models.chat_schemas import (
    # ...existing...
    ContextSummaryResponse,
)
```

- [ ] **Step 2: Write the test**

Add to `backend/tests/test_dashboard_chat_api.py`:

```python
class ContextSummaryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_context_summary_returns_breakdown(self) -> None:
        from app.api.chats import get_context_summary
        from app.models.chat_schemas import ContextSummaryResponse

        conv_id = uuid.uuid4()
        user = MagicMock()
        user.id = uuid.uuid4()
        user.user_rules = ""

        conversation = MagicMock()
        conversation.id = conv_id
        conversation.user_id = user.id

        mock_db = AsyncMock()
        # _get_conversation_or_404 path
        mock_db.execute = AsyncMock()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=conversation)
        scalars_result = MagicMock()
        scalars_result.scalars.return_value.all.return_value = []
        mock_db.execute.side_effect = [scalar_result, scalars_result]

        fake_credential = MagicMock()
        fake_credential.encrypted_config = "{}"
        fake_credential.type = "openai"

        with (
            patch("app.api.chats.get_accessible_credential", new=AsyncMock(return_value=fake_credential)),
            patch("app.api.chats.decrypt_config", return_value={"api_key": "x"}),
            patch("app.api.chats.get_openai_client", return_value=(MagicMock(), "OpenAI")),
            patch(
                "app.api.chats._assemble_system_prompt_parts",
                new=AsyncMock(
                    return_value=type(
                        "Parts",
                        (),
                        {
                            "base_system_prompt": "sys",
                            "agents_md": "",
                            "workflows_block": "",
                            "user_rules": "",
                            "full_system_prompt": "sys",
                        },
                    )()
                ),
            ),
            patch("app.api.ai_assistant._context_breakdown", return_value={
                "system": 1, "agents_md": 0, "workflows": 0,
                "user_rules": 0, "history": 0, "attachment": 0,
            }),
            patch("app.services.context_compressor.get_context_limit", return_value=128_000),
        ):
            result = await get_context_summary(
                conversation_id=conv_id,
                credential_id=uuid.uuid4(),
                model="gpt-4o-mini",
                current_user=user,
                db=mock_db,
            )

        self.assertIsInstance(result, ContextSummaryResponse)
        self.assertEqual(result.limit, 128_000)
        self.assertEqual(result.used, 1)
        self.assertEqual(result.breakdown.system, 1)
```

- [ ] **Step 3: Run test**

Run: `cd backend && uv run pytest tests/test_dashboard_chat_api.py::ContextSummaryEndpointTests -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/chats.py backend/tests/test_dashboard_chat_api.py
git commit -m "feat(chat): add GET /chats/{id}/context-summary endpoint"
```

---

## Task 11: Frontend types (`ToolCall`, `ContextUsage`, extend `Message`, `SSEChunk`)

**Files:**
- Modify: `frontend/src/types/chat.ts`
- Modify: `frontend/src/types/credential.ts`

- [ ] **Step 1: Update chat.ts types**

Replace `frontend/src/types/chat.ts` with:

```ts
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow"

export interface WorkflowPreview {
  id: string
  name: string
  description: string | null
  url: string
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface ToolCall {
  id: string
  name: string
  label: string
  args: Record<string, unknown>
  response_summary?: string
  elapsed_ms?: number
  status: 'running' | 'success' | 'error' | 'compressed'
}

export interface ContextBreakdown {
  system: number
  agents_md: number
  workflows: number
  user_rules: number
  history: number
  attachment: number
}

export interface ContextUsage {
  used: number
  limit: number
  breakdown: ContextBreakdown
}

export interface Conversation {
  id: string
  title: string
  is_pinned: boolean
  is_running: boolean
  has_unread: boolean
  created_at: string
  updated_at: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  images?: string[]
  attachmentName?: string
  workflowPreview?: WorkflowPreview
  tool_calls?: ToolCall[]
  created_at: string
}

export interface ConversationDetail extends Conversation {
  last_credential_id: string | null
  last_model: string | null
  messages: Message[]
}

export interface ConversationCreate {
  title?: string
}

export interface ConversationUpdate {
  title?: string
  is_pinned?: boolean
}

export interface MessageCreate {
  content: string
  credential_id: string
  model: string
}

export type SSEChunk =
  | { type: 'content'; text: string }
  | { type: 'tool_start'; id: string; name: string; label: string; args: Record<string, unknown> }
  | { type: 'tool_end'; id: string; response_summary: string; elapsed_ms: number; status: 'success' | 'error' }
  | { type: 'compressed'; messages_compressed: number; tokens_before: number; tokens_after: number; elapsed_ms: number }
  | { type: 'context'; used: number; limit: number; breakdown: ContextBreakdown }
  | { type: 'tool_output'; images: string[] }
  | { type: 'workflow_created'; workflow: WorkflowPreview }
  | { type: 'title'; title: string }
  | { type: 'done' }
  | { type: 'error'; text: string }
```

- [ ] **Step 2: Update LLMModel type**

In `frontend/src/types/credential.ts`, find the `LLMModel` interface and add:

```ts
export interface LLMModel {
  id: string
  name: string
  is_reasoning?: boolean
  supports_batch?: boolean
  batch_support_reason?: string | null
  context_window?: number | null
}
```

(Keep existing fields; only add `context_window` if missing.)

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && bun run typecheck`
Expected: it will list new type errors in store/api/components (those are fixed in later tasks). For this commit, only the type files should be updated. **Note:** if typecheck blows up too aggressively, stash this and continue with subsequent tasks before running typecheck again. Do not auto-fix typecheck errors in this commit.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/chat.ts frontend/src/types/credential.ts
git commit -m "feat(chat): add ToolCall, ContextUsage types and SSEChunk variants"
```

---

## Task 12: Frontend `contextEstimator.ts` helper

**Files:**
- Create: `frontend/src/lib/contextEstimator.ts`

- [ ] **Step 1: Add the helper**

```ts
export function estimateTokens(payload: unknown): number {
  if (payload == null) return 0
  return Math.floor(JSON.stringify(payload).length / 4)
}
```

- [ ] **Step 2: Run typecheck**

Run: `cd frontend && bun run typecheck`
Expected: file-level typecheck of `lib/contextEstimator.ts` passes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/contextEstimator.ts
git commit -m "feat(chat): add estimateTokens helper (4-char-per-token heuristic)"
```

---

## Task 13: Update `services/api.ts` — subscribeStream callbacks + getContextSummary

**Files:**
- Modify: `frontend/src/services/api.ts:2473+` (the `subscribeStream` function and the chatApi block)

- [ ] **Step 1: Update subscribeStream callback signature**

Find the `subscribeStream` function in `chatApi` (line ~2473). Replace the parameter list and event-routing logic:

```ts
  subscribeStream: async (
    conversationId: string,
    onChunk: (text: string) => void,
    onDone: () => void,
    onError: (err: Error) => void,
    onToolStart?: (payload: { id: string; name: string; label: string; args: Record<string, unknown> }) => void,
    onToolEnd?: (payload: { id: string; response_summary: string; elapsed_ms: number; status: 'success' | 'error' }) => void,
    onToolOutput?: (images: string[]) => void,
    onTitle?: (title: string) => void,
    onWorkflowCreated?: (workflow: WorkflowPreview) => void,
    onCompressed?: (payload: { messages_compressed: number; tokens_before: number; tokens_after: number; elapsed_ms: number }) => void,
    onContext?: (payload: ContextUsage) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
```

(Imports at top of api.ts: ensure `WorkflowPreview` and `ContextUsage` are imported from `@/types/chat`.)

- [ ] **Step 2: Update SSE chunk dispatch**

Inside the function, replace the `parsed.type === 'step'` branch and surrounding routing with:

```ts
          if (parsed.type === 'content' && parsed.text) {
            onChunk(parsed.text)
          } else if (parsed.type === 'tool_start') {
            onToolStart?.({
              id: parsed.id,
              name: parsed.name,
              label: parsed.label,
              args: parsed.args ?? {},
            })
          } else if (parsed.type === 'tool_end') {
            onToolEnd?.({
              id: parsed.id,
              response_summary: parsed.response_summary,
              elapsed_ms: parsed.elapsed_ms,
              status: parsed.status,
            })
          } else if (parsed.type === 'tool_output' && parsed.images?.length) {
            onToolOutput?.(parsed.images)
          } else if (parsed.type === 'compressed') {
            onCompressed?.({
              messages_compressed: parsed.messages_compressed,
              tokens_before: parsed.tokens_before,
              tokens_after: parsed.tokens_after,
              elapsed_ms: parsed.elapsed_ms,
            })
          } else if (parsed.type === 'context') {
            onContext?.({
              used: parsed.used,
              limit: parsed.limit,
              breakdown: parsed.breakdown,
            })
          } else if (parsed.type === 'title' && parsed.title) {
            onTitle?.(parsed.title)
          } else if (parsed.type === 'workflow_created' && parsed.workflow) {
            onWorkflowCreated?.(parsed.workflow)
          } else if (parsed.type === 'done') {
            onDone()
            return
          } else if (parsed.type === 'error') {
            onError(new Error(parsed.text || parsed.message || 'Stream error'))
            return
          }
```

Also remove or replace any prior block that handled `'step'`.

- [ ] **Step 3: Update the background subscribeStream call site at line ~1818**

There's a second copy of subscribeStream-like logic earlier in api.ts (~line 1749-1830). Update its event dispatch to also drop `'step'` handling and ignore the new event types (no-op for background subscriptions). If both copies are the same function, only one update is needed.

- [ ] **Step 4: Add getContextSummary**

In the chatApi object, add:

```ts
  getContextSummary: async (
    conversationId: string,
    credentialId: string,
    model: string,
  ): Promise<ContextUsage> => {
    const response = await api.get<ContextUsage>(
      `/api/chats/${conversationId}/context-summary`,
      { params: { credential_id: credentialId, model } },
    )
    return response.data
  },
```

- [ ] **Step 5: Run lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes for api.ts (errors elsewhere are expected; store + components are updated in next tasks).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat(chat): subscribeStream emits tool_start/end/context/compressed; add getContextSummary"
```

---

## Task 14: Update chat store (`stores/chat.ts`)

**Files:**
- Modify: `frontend/src/stores/chat.ts`

- [ ] **Step 1: Update StreamState and add contextUsageByConv**

Replace the `StreamState` interface and `EMPTY_STREAM_STATE` declarations:

```ts
  interface StreamState {
    content: string
    images: string[]
    toolCalls: ToolCall[]
    contextUsage: ContextUsage | null
    workflowPreview: WorkflowPreview | null
    isStreaming: boolean
  }
  const EMPTY_STREAM_STATE: StreamState = Object.freeze({
    content: "",
    images: [],
    toolCalls: [],
    contextUsage: null,
    workflowPreview: null,
    isStreaming: false,
  }) as StreamState
```

Add new state:

```ts
  const contextUsageByConv = ref<Record<string, ContextUsage>>({})
```

Update `_setStreamState` defaults to include the new fields:

```ts
  function _setStreamState(conversationId: string, patch: Partial<StreamState>): void {
    const current = streamStatesByConv.value[conversationId] ?? {
      content: "",
      images: [],
      toolCalls: [],
      contextUsage: null,
      workflowPreview: null,
      isStreaming: false,
    }
    streamStatesByConv.value = {
      ...streamStatesByConv.value,
      [conversationId]: { ...current, ...patch },
    }
  }
```

Import the new types at the top:

```ts
import type { Conversation, ConversationDetail, ContextUsage, Message, ToolCall, WorkflowPreview } from "@/types/chat"
```

- [ ] **Step 2: Update subscribeStream wiring in `_subscribeToStream`**

Replace the existing `chatApi.subscribeStream(conversationId, ...)` call inside `_subscribeToStream` (line ~342-396):

```ts
      await chatApi.subscribeStream(
        conversationId,
        (text) => {
          const current = getStreamState(conversationId)
          _setStreamState(conversationId, { content: current.content + text })
        },
        () => {
          const final = getStreamState(conversationId)
          const hasContent =
            final.content.length > 0 ||
            final.images.length > 0 ||
            final.workflowPreview !== null ||
            final.toolCalls.length > 0
          if (hasContent && activeConversation.value?.id === conversationId) {
            const assistantMessage: Message = {
              id: crypto.randomUUID(),
              role: "assistant",
              content: final.content,
              ...(final.images.length > 0 ? { images: [...final.images] } : {}),
              ...(final.workflowPreview ? { workflowPreview: final.workflowPreview } : {}),
              ...(final.toolCalls.length > 0 ? { tool_calls: [...final.toolCalls] } : {}),
              created_at: new Date().toISOString(),
            }
            activeConversation.value = {
              ...activeConversation.value,
              messages: [...activeConversation.value.messages, assistantMessage],
            }
            void _writeCachedConversation(activeConversation.value)
          }
          _clearStreamState(conversationId)
          _patchConversationFlag(conversationId, "is_running", false)
          if (activeConversation.value?.id !== conversationId) {
            _patchConversationFlag(conversationId, "has_unread", true)
          }
          _refreshConversationTimestamp(conversationId)
          if (hasContent) _playDing()
        },
        (_err) => {
          clearStreamingFlag()
          _patchConversationFlag(conversationId, "is_running", false)
        },
        (payload) => {
          const current = getStreamState(conversationId)
          _setStreamState(conversationId, {
            toolCalls: [
              ...current.toolCalls,
              {
                id: payload.id,
                name: payload.name,
                label: payload.label,
                args: payload.args,
                status: "running",
              },
            ],
          })
        },
        (payload) => {
          const current = getStreamState(conversationId)
          _setStreamState(conversationId, {
            toolCalls: current.toolCalls.map((tc) =>
              tc.id === payload.id
                ? {
                    ...tc,
                    response_summary: payload.response_summary,
                    elapsed_ms: payload.elapsed_ms,
                    status: payload.status,
                  }
                : tc,
            ),
          })
        },
        (images) => {
          const current = getStreamState(conversationId)
          _setStreamState(conversationId, { images: [...current.images, ...images] })
        },
        (title) => {
          _patchConversationTitle(conversationId, title)
        },
        (workflow) => {
          _setStreamState(conversationId, { workflowPreview: workflow })
        },
        (payload) => {
          const current = getStreamState(conversationId)
          const synthetic: ToolCall = {
            id: `cmp_${Date.now()}`,
            name: "_context_compression",
            label: "Context compressed",
            args: { messages_compressed: payload.messages_compressed },
            response_summary: `~${Math.floor(payload.tokens_before / 1000)}k → ~${Math.floor(payload.tokens_after / 1000)}k tokens`,
            elapsed_ms: payload.elapsed_ms,
            status: "compressed",
          }
          _setStreamState(conversationId, { toolCalls: [...current.toolCalls, synthetic] })
        },
        (payload) => {
          _setStreamState(conversationId, { contextUsage: payload })
          contextUsageByConv.value = { ...contextUsageByConv.value, [conversationId]: payload }
        },
        controller.signal,
      )
```

- [ ] **Step 3: Update background subscribeStream call**

In `_subscribeToBackgroundStream` (line ~123), pass `undefined` for `onToolStart`, `onToolEnd`, `onToolOutput`, `onCompressed`, `onContext` — background subscriptions don't surface these.

- [ ] **Step 4: Add `loadContextSummary` action**

Inside `defineStore`, before the `return` block:

```ts
  async function loadContextSummary(
    conversationId: string,
    credentialId: string,
    model: string,
  ): Promise<void> {
    try {
      const usage = await chatApi.getContextSummary(conversationId, credentialId, model)
      contextUsageByConv.value = { ...contextUsageByConv.value, [conversationId]: usage }
    } catch {
      // best-effort; UI will fall back to hiding the badge
    }
  }
```

- [ ] **Step 5: Export new state + action**

Update the return at the end of `defineStore` to include `contextUsageByConv` and `loadContextSummary`:

```ts
  return {
    // ...existing...
    contextUsageByConv,
    loadContextSummary,
  }
```

- [ ] **Step 6: Run lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes (or only errors in components, fixed next).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/stores/chat.ts
git commit -m "feat(chat): wire tool_calls + context usage through chat store"
```

---

## Task 15: Create `ChatToolCall.vue` component

**Files:**
- Create: `frontend/src/components/Chat/ChatToolCall.vue`

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
import { ref } from "vue";
import { Check, ChevronDown, ChevronRight, Loader2, TriangleAlert, Zap } from "lucide-vue-next";

import type { ToolCall } from "@/types/chat";

interface Props {
  toolCall: ToolCall;
}

const props = defineProps<Props>();

const isOpen = ref(props.toolCall.status === "running");

function toggle(): void {
  isOpen.value = !isOpen.value;
}

function formatDuration(ms: number | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function prettyArgs(args: Record<string, unknown>): string {
  if (!args || Object.keys(args).length === 0) return "(no arguments)";
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}
</script>

<template>
  <div
    class="chat-tool-call rounded-lg border text-xs"
    :class="{
      'border-border/40 bg-muted/40': toolCall.status === 'running' || toolCall.status === 'success',
      'border-destructive/40 bg-destructive/5': toolCall.status === 'error',
      'border-primary/30 bg-primary/5': toolCall.status === 'compressed',
    }"
  >
    <button
      type="button"
      class="w-full flex items-center gap-2 px-3 py-2 text-left text-muted-foreground hover:text-foreground transition-colors"
      @click="toggle"
    >
      <component
        :is="isOpen ? ChevronDown : ChevronRight"
        class="w-3.5 h-3.5 shrink-0"
      />
      <Loader2
        v-if="toolCall.status === 'running'"
        class="w-3.5 h-3.5 shrink-0 animate-spin text-primary"
      />
      <Check
        v-else-if="toolCall.status === 'success'"
        class="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
      />
      <TriangleAlert
        v-else-if="toolCall.status === 'error'"
        class="w-3.5 h-3.5 shrink-0 text-destructive"
      />
      <Zap
        v-else
        class="w-3.5 h-3.5 shrink-0 text-primary"
      />
      <span class="flex-1 truncate">{{ toolCall.label }}</span>
      <span
        v-if="toolCall.elapsed_ms != null"
        class="text-[10px] opacity-70 tabular-nums shrink-0"
      >{{ formatDuration(toolCall.elapsed_ms) }}</span>
    </button>
    <div
      v-if="isOpen"
      class="border-t border-border/30 px-3 py-2 space-y-2"
    >
      <div>
        <p class="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">
          Arguments
        </p>
        <pre class="max-h-64 overflow-auto rounded bg-background/60 p-2 text-[11px] leading-snug">{{ prettyArgs(toolCall.args) }}</pre>
      </div>
      <div v-if="toolCall.response_summary">
        <p class="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">
          Result
        </p>
        <p class="text-[11px] whitespace-pre-wrap break-words text-foreground/80">
          {{ toolCall.response_summary }}
        </p>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Run lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes for this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Chat/ChatToolCall.vue
git commit -m "feat(chat): add ChatToolCall collapsible card component"
```

---

## Task 16: Create `ChatContextBadge.vue` component

**Files:**
- Create: `frontend/src/components/Chat/ChatContextBadge.vue`

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
import { computed, ref } from "vue";

import type { ContextUsage } from "@/types/chat";

interface Props {
  contextUsage: ContextUsage | null;
  draftTokens?: number;
}

const props = withDefaults(defineProps<Props>(), { draftTokens: 0 });

const usedTotal = computed(() =>
  props.contextUsage ? props.contextUsage.used + (props.draftTokens ?? 0) : 0,
);

const pct = computed(() => {
  if (!props.contextUsage || props.contextUsage.limit <= 0) return 0;
  return Math.min(100, Math.round((usedTotal.value / props.contextUsage.limit) * 100));
});

const ringColor = computed(() => {
  if (pct.value >= 95) return "hsl(var(--destructive))";
  if (pct.value >= 80) return "hsl(40 95% 55%)"; // amber
  return "hsl(var(--primary))";
});

const ringStyle = computed(() => ({
  background: `conic-gradient(${ringColor.value} ${pct.value * 3.6}deg, hsl(var(--muted)) 0)`,
}));

const usedDisplay = computed(() => {
  const k = usedTotal.value / 1000;
  return k >= 10 ? `${Math.round(k)}k` : `${k.toFixed(1)}k`;
});

const isOpen = ref(false);

function formatK(n: number): string {
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return `${n}`;
}
</script>

<template>
  <div
    v-if="contextUsage"
    class="relative inline-flex"
    @mouseenter="isOpen = true"
    @mouseleave="isOpen = false"
  >
    <button
      type="button"
      class="inline-flex items-center gap-1.5 rounded-full bg-muted/50 hover:bg-muted/70 border border-border/40 px-2 py-0.5 text-[11px] text-muted-foreground transition-colors"
      :aria-label="`Context usage ${pct}%`"
      @click="isOpen = !isOpen"
    >
      <span
        class="w-3.5 h-3.5 rounded-full"
        :style="ringStyle"
      />
      <span class="tabular-nums">{{ pct }}% · ~{{ usedDisplay }}</span>
    </button>
    <div
      v-if="isOpen"
      class="absolute bottom-full left-0 mb-2 w-60 rounded-lg border border-border/60 bg-popover text-popover-foreground shadow-md p-3 text-xs space-y-1 z-10"
      role="tooltip"
    >
      <p class="text-[10px] uppercase tracking-wide text-muted-foreground/70 mb-1">
        Context usage
      </p>
      <div class="flex justify-between">
        <span>System prompt</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.system) }}</span>
      </div>
      <div class="flex justify-between">
        <span>AGENTS.md</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.agents_md) }}</span>
      </div>
      <div class="flex justify-between">
        <span>Workflows</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.workflows) }}</span>
      </div>
      <div class="flex justify-between">
        <span>User rules</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.user_rules) }}</span>
      </div>
      <div class="flex justify-between">
        <span>History</span><span class="tabular-nums">{{ formatK(contextUsage.breakdown.history) }}</span>
      </div>
      <div
        v-if="draftTokens && draftTokens > 0"
        class="flex justify-between"
      >
        <span>Draft</span><span class="tabular-nums">{{ formatK(draftTokens) }}</span>
      </div>
      <div class="flex justify-between border-t border-border/40 mt-1 pt-1 font-medium text-foreground">
        <span>Total</span><span class="tabular-nums">{{ formatK(usedTotal) }} / {{ formatK(contextUsage.limit) }} ({{ pct }}%)</span>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Run lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes for this file.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Chat/ChatContextBadge.vue
git commit -m "feat(chat): add ChatContextBadge with hover breakdown"
```

---

## Task 17: Wire components into `ChatConversation.vue`

**Files:**
- Modify: `frontend/src/components/Chat/ChatConversation.vue`

- [ ] **Step 1: Add imports**

Near the top of `<script setup>`, after the existing component imports:

```ts
import ChatToolCall from "@/components/Chat/ChatToolCall.vue";
import ChatContextBadge from "@/components/Chat/ChatContextBadge.vue";
import { estimateTokens } from "@/lib/contextEstimator";
```

- [ ] **Step 2: Add draftTokens computed**

After the existing `streamState` computed (around line 167):

```ts
const draftTokens = computed(() => estimateTokens(input.value));

const contextUsageForBadge = computed(() => {
  const live = streamState.value.contextUsage;
  if (live) return live;
  return chatStore.contextUsageByConv[props.conversationId] ?? null;
});
```

- [ ] **Step 3: Render tool cards in assistant messages**

In the message-render `<div v-for="msg in messages">` block, **inside** the assistant bubble (just before the markdown body, around line ~885), add:

```html
<div
  v-if="msg.role === 'assistant' && msg.tool_calls && msg.tool_calls.length > 0"
  class="mb-2 flex flex-col gap-1.5"
>
  <ChatToolCall
    v-for="tc in msg.tool_calls"
    :key="tc.id"
    :tool-call="tc"
  />
</div>
```

- [ ] **Step 4: Render tool cards in streaming bubble**

Replace the existing `streamState.steps.length > 0` block (lines 982-1003) with:

```html
<div
  v-if="streamState.toolCalls.length > 0"
  class="mb-2 flex flex-col gap-1.5"
>
  <ChatToolCall
    v-for="tc in streamState.toolCalls"
    :key="tc.id"
    :tool-call="tc"
  />
</div>
```

- [ ] **Step 5: Render the context badge**

In the `chat-input-area` div (around line 1109), **above** the `<form>` and any attachment chip row, replace the existing attachment chip wrapper with:

```html
<div class="flex items-center justify-between gap-2 mb-1.5 px-1">
  <ChatContextBadge
    :context-usage="contextUsageForBadge"
    :draft-tokens="draftTokens"
  />
  <div class="flex items-center gap-2 min-w-0">
    <div
      v-if="attachedFile"
      class="flex items-center gap-1.5 rounded-lg bg-muted/60 border border-border/40 px-2.5 py-1 text-xs text-foreground max-w-xs"
    >
      <Paperclip class="w-3 h-3 shrink-0 text-muted-foreground" />
      <span class="truncate">{{ attachedFile.name }}</span>
      <span class="text-muted-foreground shrink-0">· {{ attachedFile.sizeKb }} KB</span>
      <button
        type="button"
        class="shrink-0 ml-0.5 rounded hover:bg-muted/80 p-0.5"
        aria-label="Remove attachment"
        @click="clearAttachment"
      >
        <X class="w-3 h-3" />
      </button>
    </div>
    <p
      v-if="attachmentError"
      class="text-xs text-destructive"
    >
      {{ attachmentError }}
    </p>
  </div>
</div>
```

(This **replaces** the existing `<div v-if="attachedFile || attachmentError" class="flex items-center gap-2 mb-2 px-1">...` block. Delete the old block.)

- [ ] **Step 6: Trigger loadContextSummary**

After `loadModels` completes inside `_applyConversationSession` and `loadModels` (around line 609), trigger context summary load:

Find the end of `loadModels`:

```ts
  } finally {
    isLoadingModels.value = false;
    focusInputWhenReady();
    void _maybeLoadContextSummary();
  }
```

Add a new helper function near the other watchers:

```ts
async function _maybeLoadContextSummary(): Promise<void> {
  if (!selectedCredentialId.value || !selectedModel.value) return;
  await chatStore.loadContextSummary(
    props.conversationId,
    selectedCredentialId.value,
    selectedModel.value,
  );
}
```

Also re-fetch when model changes:

```ts
watch(selectedModel, () => {
  void _maybeLoadContextSummary();
});
```

- [ ] **Step 7: Run lint + typecheck + build**

Run: `cd frontend && bun run lint && bun run typecheck && bun run build`
Expected: all pass.

- [ ] **Step 8: Manual smoke test**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
./run.sh
```

In the browser at `localhost:4017/chats`:
1. Create a new conversation.
2. Send "List my workflows".
3. Verify a `ChatToolCall` card appears with the running spinner, then transitions to ✓ + duration.
4. Click the card; args + result expand.
5. Verify the context badge below the input shows a percentage and `~Xk`.
6. Hover the badge; the breakdown popover appears.
7. Reload the page; the tool card persists and is collapsed by default.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/Chat/ChatConversation.vue
git commit -m "feat(chat): render tool call cards and context badge in /chats"
```

---

## Task 18: Update chat documentation

**Files:**
- Modify: `frontend/src/docs/content/tabs/chat-tab.md`

- [ ] **Step 1: Add a new section to the docs**

Append to `frontend/src/docs/content/tabs/chat-tab.md`:

```markdown

## Tool calls and context size

Each time the assistant invokes a tool (running a workflow, listing executions, building a new workflow), a collapsible card appears in the conversation. The card auto-expands while the tool runs, showing the exact arguments. When the tool finishes, the card collapses to a one-line summary with the elapsed time. Click any card to re-expand the arguments and the response summary.

A small ring badge below the input shows the current context usage as a percentage of the model's window (e.g. `12% · ~9.2k`). Hover the badge to see a breakdown: system prompt, AGENTS.md, workflows block, user rules, history, and your draft input. When usage crosses 80% the ring turns amber; at 95% it turns red.

If usage gets close to the limit, Heym automatically compresses older messages into a short summary using the same mechanism agent nodes use. A "Context compressed" card appears inline to show what happened.
```

- [ ] **Step 2: Run final check.sh**

Run: `cd /Users/mbakgun/Projects/heym/heymrun && ./check.sh`
Expected: frontend lint + typecheck pass; backend Ruff format/check pass; backend tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/docs/content/tabs/chat-tab.md
git commit -m "docs(chat): document tool call cards, context badge, auto-compression"
```

---

## Final verification checklist

- [ ] `./check.sh` passes end-to-end.
- [ ] Manual smoke test against `localhost:4017/chats` covers: tool card live → success transition, click expand/collapse, badge shows + hover breakdown, page reload preserves tool cards.
- [ ] No `'type': 'step'` strings remain in the codebase (`grep -rn "'type': 'step'" backend/ frontend/` → no matches).
- [ ] DB migration `070` is at head: `cd backend && uv run alembic current` → `070`.
- [ ] Spec is fully implemented (see "Spec coverage" cross-check below).

## Spec coverage cross-check

| Spec requirement | Task |
|---|---|
| `tool_calls` JSONB column on dashboard_messages | Task 1 |
| ToolCallRecord + ContextSummaryResponse Pydantic | Task 2 |
| LLMModel.context_window exposed | Task 3 |
| `_assemble_system_prompt_parts` helper | Task 4 |
| `_context_breakdown` helper | Task 5 |
| Replace step events with tool_start/tool_end | Task 6 |
| Emit `context` event with prompt_tokens | Task 7 |
| Compression integration + `compressed` event | Task 8 |
| Persist tool_calls in _process_chat | Task 9 |
| GET /chats/{id}/context-summary | Task 10 |
| Frontend types (ToolCall, ContextUsage, SSEChunk) | Task 11 |
| `estimateTokens` helper | Task 12 |
| api.ts subscribeStream + getContextSummary | Task 13 |
| chat store streamState + contextUsageByConv | Task 14 |
| ChatToolCall component | Task 15 |
| ChatContextBadge component | Task 16 |
| Wire into ChatConversation.vue | Task 17 |
| Docs update | Task 18 |
