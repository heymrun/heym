# Workflow Analysis Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a left-side "Analyze my workflow" panel holding one shared, persistent, editable markdown doc per workflow that AI can seed/regenerate and any workflow-accessor can read and edit.

**Architecture:** A new 1:1 `workflow_analysis_notes` table (cascade-deletes with the workflow) backs GET/PUT endpoints on the workflows router with optimistic-concurrency (revision + 409 on stale). A thin SSE `/ai/analyze-workflow` endpoint reuses existing assistant plumbing to stream a markdown analysis. A new `AnalysisPanel.vue` renders in the left slot (replacing NodePanel), with an edit/preview markdown editor, Analyze/Reanalyze, and concurrency-safe save.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic (backend); Vue 3 `<script setup>` + Pinia + axios + `marked`/`DOMPurify` (frontend).

**Reference spec:** `docs/superpowers/specs/2026-06-19-workflow-analysis-notes-design.md`

---

## File Structure

**Backend**
- Create: `backend/alembic/versions/081_add_workflow_analysis_notes.py` — migration for the new table.
- Modify: `backend/app/db/models.py` — add `WorkflowAnalysisNote` model + `Workflow.analysis_note` relationship.
- Modify: `backend/app/models/schemas.py` — Pydantic request/response schemas for the note.
- Modify: `backend/app/api/workflows.py` — `GET`/`PUT` note endpoints.
- Modify: `backend/app/api/ai_assistant.py` — `POST /ai/analyze-workflow` SSE endpoint + analyze prompt.
- Create: `backend/tests/test_workflow_analysis_notes.py` — endpoint tests.

**Frontend**
- Modify: `frontend/src/services/api.ts` — `getWorkflowAnalysisNote`, `saveWorkflowAnalysisNote`, `analyzeWorkflowStream`.
- Modify: `frontend/src/stores/workflow.ts` — `analysisPanelOpen` state + toggle.
- Create: `frontend/src/components/Panels/AnalysisPanel.vue` — the panel (editor + preview + analyze + save).
- Modify: `frontend/src/views/EditorView.vue` — toolbar button + render panel in left slot, close NodePanel when open.

---

## Task 1: Database model for `workflow_analysis_notes`

**Files:**
- Modify: `backend/app/db/models.py` (add model near `WorkflowVersion`, ~line 322)

- [ ] **Step 1: Add the `WorkflowAnalysisNote` model**

Add after the `Workflow` class block (after line ~319, before `class WorkflowVersion`):

```python
class WorkflowAnalysisNote(Base):
    __tablename__ = "workflow_analysis_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="analysis_note")
    updated_by: Mapped["User | None"] = relationship("User")
```

- [ ] **Step 2: Add the relationship on `Workflow`**

In `class Workflow`, after the `versions` relationship (line ~315), add:

```python
    analysis_note: Mapped["WorkflowAnalysisNote | None"] = relationship(
        "WorkflowAnalysisNote",
        back_populates="workflow",
        cascade="all, delete-orphan",
        uselist=False,
    )
```

- [ ] **Step 3: Verify imports exist**

Run: `grep -nE "^from|^import" backend/app/db/models.py | grep -E "Integer|Text|ForeignKey|func|datetime"`
Expected: `Integer`, `Text`, `ForeignKey`, `func` are already imported (they are used elsewhere in the file). If `Integer` is missing from the `sqlalchemy` import line, add it.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add WorkflowAnalysisNote model"
```

---

## Task 2: Alembic migration

**Files:**
- Create: `backend/alembic/versions/081_add_workflow_analysis_notes.py`

- [ ] **Step 1: Write the migration**

```python
"""add workflow analysis notes

Revision ID: 081_add_workflow_analysis_notes
Revises: 080_merge_github_supabase_heads
Create Date: 2026-06-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "081_add_workflow_analysis_notes"
down_revision: str | Sequence[str] | None = "080_merge_github_supabase_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_analysis_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_workflow_analysis_notes_workflow_id",
        "workflow_analysis_notes",
        ["workflow_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_analysis_notes_workflow_id", table_name="workflow_analysis_notes")
    op.drop_table("workflow_analysis_notes")
```

- [ ] **Step 2: Run the migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: applies `081_add_workflow_analysis_notes` with no errors.

- [ ] **Step 3: Verify head**

Run: `cd backend && uv run alembic current`
Expected: shows `081_add_workflow_analysis_notes`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/081_add_workflow_analysis_notes.py
git commit -m "feat: migration for workflow_analysis_notes"
```

---

## Task 3: Pydantic schemas

**Files:**
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: Add schemas**

Append to `backend/app/models/schemas.py`:

```python
class AnalysisNoteEditor(BaseModel):
    id: uuid.UUID
    name: str


class AnalysisNoteResponse(BaseModel):
    content: str
    revision: int
    updated_by: AnalysisNoteEditor | None = None
    updated_at: datetime | None = None


class AnalysisNoteSaveRequest(BaseModel):
    content: str
    base_revision: int
```

- [ ] **Step 2: Verify imports**

Run: `grep -nE "^import uuid|^from datetime|BaseModel" backend/app/models/schemas.py | head`
Expected: `uuid`, `datetime`, and `BaseModel` are already imported. If `datetime` is missing, add `from datetime import datetime`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat: schemas for workflow analysis note"
```

---

## Task 4: GET endpoint (test-first)

**Files:**
- Modify: `backend/app/api/workflows.py`
- Test: `backend/tests/test_workflow_analysis_notes.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_workflow_analysis_notes.py`:

```python
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException, status

from app.api.workflows import get_workflow_analysis_note, save_workflow_analysis_note
from app.models.schemas import AnalysisNoteSaveRequest


def _db_with_workflow_and_note(workflow, note):
    """db.execute returns workflow on first call, note on second."""
    db = AsyncMock()
    results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=note)),
    ]
    db.execute = AsyncMock(side_effect=results)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


class GetAnalysisNoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_default_when_no_note(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        db = _db_with_workflow_and_note(workflow, None)

        result = await get_workflow_analysis_note(workflow.id, current_user=user, db=db)

        self.assertEqual(result.content, "")
        self.assertEqual(result.revision, 0)
        self.assertIsNone(result.updated_by)

    async def test_404_when_no_access(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with self.assertRaises(HTTPException) as ctx:
            await get_workflow_analysis_note(uuid.uuid4(), current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)

    async def test_returns_existing_note(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        editor = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        note = SimpleNamespace(
            content="hello", revision=2, updated_by=editor, updated_at=None
        )
        db = _db_with_workflow_and_note(workflow, note)

        result = await get_workflow_analysis_note(workflow.id, current_user=user, db=db)

        self.assertEqual(result.content, "hello")
        self.assertEqual(result.revision, 2)
        self.assertEqual(result.updated_by.name, "Burak")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analysis_notes.py::GetAnalysisNoteTests -v`
Expected: FAIL with `ImportError: cannot import name 'get_workflow_analysis_note'`.

- [ ] **Step 3: Implement the GET endpoint**

In `backend/app/api/workflows.py`, add these imports if missing (check the existing import block):
```python
from app.db.models import WorkflowAnalysisNote
from app.models.schemas import (
    AnalysisNoteEditor,
    AnalysisNoteResponse,
    AnalysisNoteSaveRequest,
)
```

Add a helper and the endpoint (place near other `@router` workflow endpoints):

```python
def _serialize_analysis_note(note: WorkflowAnalysisNote | None) -> AnalysisNoteResponse:
    if note is None:
        return AnalysisNoteResponse(content="", revision=0, updated_by=None, updated_at=None)
    editor = None
    if note.updated_by is not None:
        editor = AnalysisNoteEditor(id=note.updated_by.id, name=note.updated_by.name)
    return AnalysisNoteResponse(
        content=note.content,
        revision=note.revision,
        updated_by=editor,
        updated_at=note.updated_at,
    )


@router.get("/{workflow_id}/analysis-note", response_model=AnalysisNoteResponse)
async def get_workflow_analysis_note(
    workflow_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisNoteResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    result = await db.execute(
        select(WorkflowAnalysisNote)
        .options(selectinload(WorkflowAnalysisNote.updated_by))
        .where(WorkflowAnalysisNote.workflow_id == workflow_id)
    )
    note = result.scalar_one_or_none()
    return _serialize_analysis_note(note)
```

Verify `selectinload` is imported (`from sqlalchemy.orm import selectinload`); add it if missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analysis_notes.py::GetAnalysisNoteTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/workflows.py backend/tests/test_workflow_analysis_notes.py
git commit -m "feat: GET workflow analysis note endpoint"
```

---

## Task 5: PUT endpoint with optimistic concurrency (test-first)

**Files:**
- Modify: `backend/app/api/workflows.py`
- Test: `backend/tests/test_workflow_analysis_notes.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_workflow_analysis_notes.py`:

```python
class SaveAnalysisNoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_note_when_none_exists(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        db = _db_with_workflow_and_note(workflow, None)

        body = AnalysisNoteSaveRequest(content="new doc", base_revision=0)
        result = await save_workflow_analysis_note(
            workflow.id, body, current_user=user, db=db
        )

        self.assertEqual(result.content, "new doc")
        self.assertEqual(result.revision, 1)
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    async def test_updates_existing_and_increments_revision(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        note = SimpleNamespace(
            content="old", revision=3, updated_by=None, updated_at=None, updated_by_id=None
        )
        db = _db_with_workflow_and_note(workflow, note)

        body = AnalysisNoteSaveRequest(content="edited", base_revision=3)
        result = await save_workflow_analysis_note(
            workflow.id, body, current_user=user, db=db
        )

        self.assertEqual(result.content, "edited")
        self.assertEqual(result.revision, 4)
        self.assertEqual(note.updated_by_id, user.id)

    async def test_stale_base_revision_returns_409(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        workflow = SimpleNamespace(id=uuid.uuid4(), owner_id=user.id)
        editor = SimpleNamespace(id=uuid.uuid4(), name="Ceren")
        note = SimpleNamespace(
            content="server version", revision=5, updated_by=editor, updated_at=None
        )
        db = _db_with_workflow_and_note(workflow, note)

        body = AnalysisNoteSaveRequest(content="mine", base_revision=2)
        with self.assertRaises(HTTPException) as ctx:
            await save_workflow_analysis_note(workflow.id, body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(ctx.exception.detail["revision"], 5)
        self.assertEqual(ctx.exception.detail["content"], "server version")

    async def test_404_when_no_access(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), name="Burak")
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        body = AnalysisNoteSaveRequest(content="x", base_revision=0)
        with self.assertRaises(HTTPException) as ctx:
            await save_workflow_analysis_note(uuid.uuid4(), body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analysis_notes.py::SaveAnalysisNoteTests -v`
Expected: FAIL with `ImportError: cannot import name 'save_workflow_analysis_note'`.

- [ ] **Step 3: Implement the PUT endpoint**

In `backend/app/api/workflows.py`, add after the GET endpoint:

```python
@router.put("/{workflow_id}/analysis-note", response_model=AnalysisNoteResponse)
async def save_workflow_analysis_note(
    workflow_id: uuid.UUID,
    body: AnalysisNoteSaveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisNoteResponse:
    workflow = await get_workflow_for_user(db, workflow_id, current_user.id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

    result = await db.execute(
        select(WorkflowAnalysisNote)
        .options(selectinload(WorkflowAnalysisNote.updated_by))
        .where(WorkflowAnalysisNote.workflow_id == workflow_id)
    )
    note = result.scalar_one_or_none()
    current_revision = note.revision if note is not None else 0

    if body.base_revision != current_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_serialize_analysis_note(note).model_dump(mode="json"),
        )

    if note is None:
        note = WorkflowAnalysisNote(
            workflow_id=workflow_id,
            content=body.content,
            revision=1,
            updated_by_id=current_user.id,
        )
        db.add(note)
    else:
        note.content = body.content
        note.revision = current_revision + 1
        note.updated_by_id = current_user.id

    await db.commit()
    return AnalysisNoteResponse(
        content=body.content,
        revision=current_revision + 1,
        updated_by=AnalysisNoteEditor(id=current_user.id, name=current_user.name),
        updated_at=None,
    )
```

Note: the response is built directly (not via `_serialize_analysis_note`) to avoid a post-commit refresh; the client uses the returned `revision` as its new `base_revision`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analysis_notes.py -v`
Expected: PASS (all GET + SAVE tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/workflows.py backend/tests/test_workflow_analysis_notes.py
git commit -m "feat: PUT workflow analysis note with optimistic concurrency"
```

---

## Task 6: `/ai/analyze-workflow` SSE endpoint (test-first)

**Files:**
- Modify: `backend/app/api/ai_assistant.py`
- Test: `backend/tests/test_workflow_analysis_notes.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_workflow_analysis_notes.py`:

```python
class AnalyzeWorkflowEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_llm_credential(self) -> None:
        from app.api.ai_assistant import AnalyzeWorkflowRequest, analyze_workflow_stream
        from app.db.models import CredentialType

        user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        credential = SimpleNamespace(
            id=uuid.uuid4(), type=CredentialType.slack, encrypted_config={}
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=credential))
        )

        body = AnalyzeWorkflowRequest(
            credential_id=credential.id, model="gpt-4o", current_workflow={"id": str(uuid.uuid4())}
        )
        with self.assertRaises(HTTPException) as ctx:
            await analyze_workflow_stream(body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_400_BAD_REQUEST)

    async def test_404_when_credential_missing(self) -> None:
        from app.api.ai_assistant import AnalyzeWorkflowRequest, analyze_workflow_stream

        user = SimpleNamespace(id=uuid.uuid4(), user_rules=None)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        body = AnalyzeWorkflowRequest(
            credential_id=uuid.uuid4(), model="gpt-4o", current_workflow={"id": str(uuid.uuid4())}
        )
        with self.assertRaises(HTTPException) as ctx:
            await analyze_workflow_stream(body, current_user=user, db=db)

        self.assertEqual(ctx.exception.status_code, status.HTTP_404_NOT_FOUND)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analysis_notes.py::AnalyzeWorkflowEndpointTests -v`
Expected: FAIL with `ImportError: cannot import name 'AnalyzeWorkflowRequest'`.

- [ ] **Step 3: Implement the analyze endpoint**

In `backend/app/api/ai_assistant.py`, add the request model near `AIAssistantRequest` (~line 98):

```python
class AnalyzeWorkflowRequest(BaseModel):
    credential_id: uuid.UUID
    model: str
    current_workflow: dict | None = None
    execution_log: dict | None = None
```

Add the analyze prompt constant near other prompt constants (e.g. by `CANVAS_ASK_SYSTEM_PROMPT`):

```python
WORKFLOW_ANALYZE_SYSTEM_PROMPT = """You analyze an automation workflow and produce a clear Markdown report.

Given the workflow's nodes and edges, write Markdown with these sections:

## Purpose
One or two sentences on what this workflow is for.

## What it does
A numbered, step-by-step walk through the nodes in execution order, in plain language.

## Improvement areas
A bulleted list of concrete, actionable suggestions (reliability, error handling, missing validation, cost, clarity). If the workflow already looks solid, say so and suggest small refinements.

Output ONLY Markdown. Do not include JSON, code fences around the whole document, or tool calls. Be concise and specific to THIS workflow."""
```

Add the endpoint near `workflow_assistant_stream` (~line 3488):

```python
@router.post("/analyze-workflow")
async def analyze_workflow_stream(
    request: AnalyzeWorkflowRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    credential = await get_credential_for_user(request.credential_id, current_user, db)
    if not credential:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found"
        )
    if credential.type not in (CredentialType.openai, CredentialType.google, CredentialType.custom):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an LLM type (OpenAI, Google, or Custom)",
        )

    config = decrypt_config(credential.encrypted_config)
    client, provider = get_openai_client(credential.type, config)

    system_prompt = WORKFLOW_ANALYZE_SYSTEM_PROMPT
    if request.current_workflow:
        wf_summary = json.dumps(request.current_workflow, ensure_ascii=False)
        system_prompt += f"\n\nWorkflow:\n```json\n{wf_summary}\n```"
    system_prompt = _append_execution_log_to_prompt(system_prompt, request.execution_log)

    workflow_id = None
    if request.current_workflow:
        wf_id = request.current_workflow.get("id")
        if wf_id:
            workflow_id = uuid.UUID(wf_id) if isinstance(wf_id, str) else wf_id

    trace_context = LLMTraceContext(
        user_id=current_user.id,
        credential_id=credential.id,
        workflow_id=workflow_id,
        node_label="Workflow Analyze",
        source="assistant",
    )

    messages = [{"role": "user", "content": "Analyze this workflow."}]
    assistant_stream = stream_llm_response(
        client,
        request.model,
        system_prompt,
        messages,
        provider,
        trace_context,
        run_type="workflow_assistant",
    )

    return StreamingResponse(
        _stream_sse_with_heartbeat(
            assistant_stream,
            heartbeat_seconds=WORKFLOW_ASSISTANT_SSE_HEARTBEAT_SECONDS,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analysis_notes.py::AnalyzeWorkflowEndpointTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/ai_assistant.py backend/tests/test_workflow_analysis_notes.py
git commit -m "feat: /ai/analyze-workflow SSE endpoint"
```

---

## Task 7: Backend lint + full test sweep

**Files:** none (verification)

- [ ] **Step 1: Format + lint**

Run: `cd backend && uv run ruff format . && uv run ruff check . --fix`
Expected: no remaining errors.

- [ ] **Step 2: Run the new tests + assistant tests**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_workflow_analysis_notes.py tests/test_workflow_assistant_stream.py -v`
Expected: all PASS.

- [ ] **Step 3: Commit any formatting changes**

```bash
git add -A backend
git commit -m "chore: ruff format analysis note backend" || echo "nothing to commit"
```

---

## Task 8: Frontend API client methods

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Inspect existing patterns**

Run: `grep -n "export async function\|api.get(\|api.put(\|fetch(\|EventSource\|getAuthToken\|API_BASE\|baseURL" frontend/src/services/api.ts | head -30`
Expected: shows the axios `api` instance, how the base URL/token are obtained, and any existing SSE/`fetch` streaming helper (the assistant uses a `fetch`-based SSE call — reuse its auth-header approach).

- [ ] **Step 2: Add the note types + REST methods**

Add near other workflow API functions in `frontend/src/services/api.ts`:

```typescript
export interface AnalysisNoteEditor {
  id: string;
  name: string;
}

export interface AnalysisNoteResponse {
  content: string;
  revision: number;
  updated_by: AnalysisNoteEditor | null;
  updated_at: string | null;
}

export async function getWorkflowAnalysisNote(
  workflowId: string,
): Promise<AnalysisNoteResponse> {
  const { data } = await api.get<AnalysisNoteResponse>(
    `/api/workflows/${workflowId}/analysis-note`,
  );
  return data;
}

export async function saveWorkflowAnalysisNote(
  workflowId: string,
  content: string,
  baseRevision: number,
): Promise<AnalysisNoteResponse> {
  const { data } = await api.put<AnalysisNoteResponse>(
    `/api/workflows/${workflowId}/analysis-note`,
    { content, base_revision: baseRevision },
  );
  return data;
}
```

Match the exact axios instance name and path prefix found in Step 1 (the file may use a relative `/api` base or a configured `baseURL`; mirror the neighbouring workflow calls).

- [ ] **Step 3: Add the streaming analyze method**

Mirror the existing assistant SSE caller found in Step 1 (search `analyze` siblings: `grep -n "workflow-assistant\|text/event-stream\|getReader" frontend/src/services/api.ts`). Add a function with the same auth/streaming shape, posting to `/api/ai/analyze-workflow`:

```typescript
export async function analyzeWorkflowStream(
  payload: { credential_id: string; model: string; current_workflow: unknown },
  onChunk: (text: string) => void,
  signal: AbortSignal,
): Promise<void> {
  // Reuse the same fetch + ReadableStream SSE parsing the AI assistant uses
  // (copy the assistant's stream loop; endpoint = `/api/ai/analyze-workflow`).
  // Call onChunk(text) for each streamed content delta; respect `signal`.
}
```

If the existing assistant streaming logic lives in a component rather than `api.ts`, instead export a small shared helper here and have `AnalysisPanel.vue` consume it. Keep the SSE parsing identical to the assistant's so heartbeat/`[DONE]` framing matches.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat: frontend API client for workflow analysis note"
```

---

## Task 9: Pinia store state for panel

**Files:**
- Modify: `frontend/src/stores/workflow.ts`

- [ ] **Step 1: Add panel open state**

In `frontend/src/stores/workflow.ts`, alongside `propertiesPanelOpen` (search for it), add:

```typescript
const analysisPanelOpen = ref(false);
```

And export it in the store's return object next to `propertiesPanelOpen`:

```typescript
    analysisPanelOpen,
```

Run: `grep -n "propertiesPanelOpen" frontend/src/stores/workflow.ts` first to find the exact `ref(...)` declaration and the return block, then place the new lines beside them.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/workflow.ts
git commit -m "feat: analysisPanelOpen store state"
```

---

## Task 10: `AnalysisPanel.vue`

**Files:**
- Create: `frontend/src/components/Panels/AnalysisPanel.vue`

- [ ] **Step 1: Inspect markdown render + credential-picker patterns**

Run these to copy real patterns:
```bash
grep -n "renderHtml\|marked(\|DOMPurify\|@/lib/markdown" frontend/src/components/Dashboards/MarkdownTextContent.vue
grep -rn "credential\|model" frontend/src/components/Panels/DebugPanel.vue | grep -i "ai\|assistant\|credential" | head
```
Expected: shows the `marked + DOMPurify` render helper to reuse, and how the AI assistant chooses a credential/model (reuse that selection UI or its source-of-truth so Analyze can pass `credential_id` + `model`).

- [ ] **Step 2: Create the component**

Create `frontend/src/components/Panels/AnalysisPanel.vue` (`<script setup lang="ts">`, ≤300 lines). It must implement:

- On mount (and when `workflowId` changes): call `getWorkflowAnalysisNote(workflowId)`, store `content`, `revision`, `updatedBy`, `updatedAt`. Start in **Preview** mode if content is non-empty, else **Edit**.
- Header: title "Workflow Analysis", "last edited by {name} · {relative time}" when `updatedBy`, an **Edit | Preview** toggle, a **Save** button (disabled unless `dirty`), an **Analyze**/**Reanalyze** button (label = "Reanalyze" when current saved content is non-empty), and a close (X) button that sets `workflowStore.analysisPanelOpen = false`.
- Editor: `<textarea v-model="draft">` in Edit mode; Preview mode renders `renderHtml(draft)` via `marked` + `DOMPurify` (reuse the helper from `MarkdownTextContent.vue`). `dirty = draft !== savedContent`.
- **Analyze** (when saved content is empty): call `analyzeWorkflowStream(...)`, append streamed chunks into `draft`, switch to Edit mode so the user can refine, leave unsaved.
- **Reanalyze** (when saved content non-empty): stream into a separate `reanalyzePreview` ref shown in an overlay/section with **Accept** (sets `draft = reanalyzePreview`, clears overlay) and **Discard** (clears overlay, keeps `draft`). Never auto-overwrite `draft`.
- **Save**: call `saveWorkflowAnalysisNote(workflowId, draft, revision)`. On success update `savedContent`, `revision`, `updatedBy`. On 409 (`error.response.status === 409`): show a stale-warning banner using `error.response.data` (the server `content`/`revision`/`updated_by`), offering **Reload** (set `draft`/`savedContent`/`revision` to server values) and **Overwrite** (re-call save with `baseRevision = serverRevision`).
- Disable Analyze with a tooltip when no LLM credential is configured (reuse the assistant's credential-availability check).
- If `workflowId` is empty/unsaved, show "Save the workflow first to analyze it" and disable Analyze + Save.
- Use an `AbortController`; abort the in-flight stream in `onBeforeUnmount` and when the panel closes.

Match Tailwind/shadcn styling and panel width to `NodePanel.vue` so it occupies the same left slot.

- [ ] **Step 3: Typecheck + lint**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Panels/AnalysisPanel.vue
git commit -m "feat: AnalysisPanel component"
```

---

## Task 11: Wire panel + toolbar button into EditorView

**Files:**
- Modify: `frontend/src/views/EditorView.vue`

- [ ] **Step 1: Import + state**

Add the import near the other panel imports (line ~30):
```typescript
import AnalysisPanel from "@/components/Panels/AnalysisPanel.vue";
```
Pull the store flag in where `propertiesPanelOpen` is consumed:
```typescript
const { analysisPanelOpen } = storeToRefs(workflowStore);
```
(Confirm `workflowStore` and `storeToRefs` are already in scope — they are, per existing usage around line 248.)

- [ ] **Step 2: Open/close coordination**

Add a handler so opening the analysis panel closes NodePanel and closing returns to it:
```typescript
function toggleAnalysisPanel(): void {
  analysisPanelOpen.value = !analysisPanelOpen.value;
  if (analysisPanelOpen.value) {
    leftPanelOpen.value = false;
  }
}
```
Add a watcher so that re-opening NodePanel hides the analysis panel (mutually exclusive in the left slot):
```typescript
watch(leftPanelOpen, (open) => {
  if (open && analysisPanelOpen.value) {
    analysisPanelOpen.value = false;
  }
});
```
(`watch` is already imported in this file; verify with `grep -n "watch" frontend/src/views/EditorView.vue`.)

- [ ] **Step 3: Render the panel in the left slot**

Where `<NodePanel v-show="leftPanelOpen" />` is (line ~2036), add the analysis panel as the alternative in the same slot so it pushes the canvas identically:
```vue
<NodePanel v-show="leftPanelOpen && !analysisPanelOpen" />
<AnalysisPanel
  v-if="analysisPanelOpen"
  :workflow-id="workflowStore.workflowId ?? ''"
  :current-workflow="workflowStore.currentWorkflowPayload"
/>
```
Use the store's actual workflow id accessor and serialized-workflow getter — find them with:
`grep -n "workflowId\|currentWorkflow\|toPayload\|serialize" frontend/src/stores/workflow.ts | head`. Pass the same workflow object shape the AI assistant already sends as `current_workflow` (search how DebugPanel builds it) so the analyze endpoint gets identical input.

- [ ] **Step 4: Add the toolbar button**

Add an "Analyze my workflow" button to the canvas toolbar near the Ask AI / run controls. Locate the toolbar with `grep -n "Ask AI\|Run with cURL\|toolbar" frontend/src/views/EditorView.vue`, then add a button that calls `toggleAnalysisPanel()` with an icon (e.g. `Sparkles` or `FileText` from `lucide-vue-next`) and active styling when `analysisPanelOpen`:
```vue
<button
  class="toolbar-btn"
  :class="{ active: analysisPanelOpen }"
  title="Analyze my workflow"
  @click="toggleAnalysisPanel"
>
  <Sparkles class="w-4 h-4" />
</button>
```
Match the existing toolbar button markup/classes you found rather than inventing new ones; ensure the icon is imported from `lucide-vue-next`.

- [ ] **Step 5: Typecheck + lint + build**

Run: `cd frontend && bun run typecheck && bun run lint && bun run build`
Expected: all succeed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/views/EditorView.vue
git commit -m "feat: wire analysis panel + toolbar button into editor"
```

---

## Task 12: Full verification + docs

**Files:** docs via skill

- [ ] **Step 1: Run the repo check script**

Run: `cd /Users/mbakgun/Projects/heym/heymrun && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: frontend lint+typecheck PASS, backend ruff PASS, backend tests PASS. Fix anything that fails before continuing.

- [ ] **Step 2: Manual smoke test (local app)**

Run `./run.sh`, open a workflow, click "Analyze my workflow":
- Panel opens on the left, NodePanel closes, canvas shifts.
- Analyze streams markdown into the editor; Save persists; reopening shows it in Preview.
- Edit + Save updates "last edited by".
- Reanalyze streams a preview with Accept/Discard.
- In a second session/user with shared access, edit + save → first session's stale save shows the 409 warning.

- [ ] **Step 3: Update documentation**

Use the `heym-documentation` skill to document the "Analyze my workflow" panel (what it does, AI analysis, shared editable notes, edit/preview, concurrency behavior).

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "docs: workflow analysis notes panel" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** one shared markdown doc (Tasks 1–5, 10) ✓; AI seed + Reanalyze (Task 6, 10) ✓; edit+preview (Task 10) ✓; shared read+write via `get_workflow_for_user` (Tasks 4–5) ✓; cascade delete (Tasks 1–2) ✓; left panel pushes canvas + closes NodePanel (Tasks 9, 11) ✓; last-write-wins + stale 409 warning (Task 5, 10) ✓; no-credential / unsaved-workflow edge cases (Task 10) ✓; backend tests (Tasks 4–6) ✓; docs (Task 12) ✓.
- **No frontend tests** per repo policy — verification via typecheck/lint/build + manual smoke.
- **Type consistency:** `AnalysisNoteResponse`/`AnalysisNoteEditor`/`AnalysisNoteSaveRequest` names match across backend schemas, endpoints, and frontend interfaces; `revision`/`base_revision` naming consistent end to end.
