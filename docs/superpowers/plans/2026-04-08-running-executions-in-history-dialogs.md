# Running Executions in History Dialogs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show currently-running workflow executions at the top of both history dialogs, each with a Cancel button.

**Architecture:** Backend exposes `GET /workflows/executions/active` that reads the in-memory `_ACTIVE_EXECUTIONS` dict and filters to the authenticated user's workflows. Both frontend dialogs fetch this on open and render running entries above completed history entries. Cancel button calls the existing `POST /workflows/{wf}/executions/{ex}/cancel` endpoint using the runtime `execution_id` (not the DB history ID).

**Tech Stack:** Python/FastAPI (backend), Vue 3 Composition API + TypeScript strict (frontend), Pinia (store), Axios (HTTP).

---

## File Map

| File | Change |
|------|--------|
| `backend/app/services/execution_cancellation.py` | Add `started_at` to handle dataclass; add `list_active_executions()` |
| `backend/app/models/schemas.py` | Add `ActiveExecutionItem` Pydantic model |
| `backend/app/api/workflows.py` | Add `GET /executions/active` endpoint + import |
| `backend/tests/test_execution_cancellation.py` | Tests for `list_active_executions()` |
| `frontend/src/types/workflow.ts` | Add `ActiveExecutionItem` interface |
| `frontend/src/services/api.ts` | Add `getActiveExecutions()` method |
| `frontend/src/components/Panels/ExecutionHistoryDialog.vue` | Fetch + render running entries at top |
| `frontend/src/components/Panels/ExecutionHistoryAllDialog.vue` | Fetch + render running entries at top |

---

## Task 1: Extend `ExecutionCancellationHandle` with `started_at`

**Files:**
- Modify: `backend/app/services/execution_cancellation.py`
- Modify (tests): `backend/tests/test_execution_cancellation.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_execution_cancellation.py` inside the `RegisterExecutionTests` class and a new `ListActiveExecutionsTests` class:

```python
import datetime
from app.services.execution_cancellation import list_active_executions

# Inside RegisterExecutionTests:
def test_handle_has_started_at(self) -> None:
    before = datetime.datetime.utcnow()
    wf_id = uuid.uuid4()
    ex_id = uuid.uuid4()
    register_execution(workflow_id=wf_id, execution_id=ex_id)
    handle = _ACTIVE_EXECUTIONS[ex_id]
    after = datetime.datetime.utcnow()
    self.assertGreaterEqual(handle.started_at, before)
    self.assertLessEqual(handle.started_at, after)


class ListActiveExecutionsTests(unittest.TestCase):
    def setUp(self) -> None:
        _flush()

    def test_empty_when_no_executions(self) -> None:
        result = list_active_executions()
        self.assertEqual(result, [])

    def test_returns_all_registered_handles(self) -> None:
        wf_id = uuid.uuid4()
        ex1 = uuid.uuid4()
        ex2 = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex1)
        register_execution(workflow_id=wf_id, execution_id=ex2)
        result = list_active_executions()
        execution_ids = {h.execution_id for h in result}
        self.assertEqual(execution_ids, {ex1, ex2})

    def test_does_not_return_cleared_execution(self) -> None:
        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        register_execution(workflow_id=wf_id, execution_id=ex_id)
        clear_execution(ex_id)
        result = list_active_executions()
        self.assertEqual(result, [])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_execution_cancellation.py -v 2>&1 | tail -20
```

Expected: failures on `test_handle_has_started_at` and all `ListActiveExecutionsTests` tests.

- [ ] **Step 3: Implement changes in `execution_cancellation.py`**

Replace the entire file content:

```python
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ExecutionCancellationHandle:
    workflow_id: uuid.UUID
    execution_id: uuid.UUID
    event: threading.Event
    started_at: datetime = field(default_factory=datetime.utcnow)


_ACTIVE_EXECUTIONS: dict[uuid.UUID, ExecutionCancellationHandle] = {}
_LOCK = threading.Lock()


def register_execution(
    *,
    workflow_id: uuid.UUID,
    execution_id: uuid.UUID,
) -> threading.Event:
    event = threading.Event()
    handle = ExecutionCancellationHandle(
        workflow_id=workflow_id,
        execution_id=execution_id,
        event=event,
    )
    with _LOCK:
        _ACTIVE_EXECUTIONS[execution_id] = handle
    return event


def cancel_execution(*, workflow_id: uuid.UUID, execution_id: uuid.UUID) -> bool:
    with _LOCK:
        handle = _ACTIVE_EXECUTIONS.get(execution_id)
    if handle is None or handle.workflow_id != workflow_id:
        return False
    handle.event.set()
    return True


def clear_execution(execution_id: uuid.UUID) -> None:
    with _LOCK:
        _ACTIVE_EXECUTIONS.pop(execution_id, None)


def list_active_executions() -> list[ExecutionCancellationHandle]:
    """Return a snapshot of all currently active executions."""
    with _LOCK:
        return list(_ACTIVE_EXECUTIONS.values())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_execution_cancellation.py -v 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/execution_cancellation.py backend/tests/test_execution_cancellation.py
git commit -m "feat: add started_at and list_active_executions to cancellation service"
```

---

## Task 2: Add `ActiveExecutionItem` Pydantic schema

**Files:**
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: Add schema after `HistoryListResponse` (line ~371)**

Open `backend/app/models/schemas.py`. After the `HistoryListResponse` class, add:

```python
class ActiveExecutionItem(BaseModel):
    """Single currently-running execution visible to the requesting user."""

    execution_id: str
    workflow_id: str
    workflow_name: str
    started_at: datetime
```

- [ ] **Step 2: Verify linting**

```bash
cd backend && uv run ruff check app/models/schemas.py
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat: add ActiveExecutionItem schema"
```

---

## Task 3: Add `GET /workflows/executions/active` endpoint

**Files:**
- Modify: `backend/app/api/workflows.py`

- [ ] **Step 1: Add import for `list_active_executions` and `ActiveExecutionItem`**

In `backend/app/api/workflows.py`, find the existing import block for `execution_cancellation` (around line 53-60). Add the new import:

```python
from app.services.execution_cancellation import (
    list_active_executions,
)
```

Also add `ActiveExecutionItem` to the `app.models.schemas` import block:

```python
from app.models.schemas import (
    ActiveExecutionItem,
    ExecutionHistoryListResponse,
    ...  # rest unchanged
)
```

- [ ] **Step 2: Add the endpoint**

Insert the following endpoint BEFORE the `@router.post("")` route that creates a workflow (around line 831 — this ensures it is registered before `/{workflow_id}` parameterised routes):

```python
@router.get("/executions/active", response_model=list[ActiveExecutionItem])
async def list_active_workflow_executions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ActiveExecutionItem]:
    """Return all currently running executions belonging to the authenticated user."""
    handles = list_active_executions()
    if not handles:
        return []

    workflow_ids = list({h.workflow_id for h in handles})
    result = await db.execute(
        select(Workflow).where(
            Workflow.id.in_(workflow_ids),
            or_(
                Workflow.owner_id == current_user.id,
                Workflow.id.in_(
                    select(WorkflowShare.workflow_id).where(
                        WorkflowShare.user_id == current_user.id
                    )
                ),
            ),
        )
    )
    accessible: dict[uuid.UUID, str] = {
        w.id: w.name for w in result.scalars().all()
    }

    return [
        ActiveExecutionItem(
            execution_id=str(h.execution_id),
            workflow_id=str(h.workflow_id),
            workflow_name=accessible[h.workflow_id],
            started_at=h.started_at,
        )
        for h in handles
        if h.workflow_id in accessible
    ]
```

- [ ] **Step 3: Verify linting and formatting**

```bash
cd backend && uv run ruff check app/api/workflows.py && uv run ruff format app/api/workflows.py
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/workflows.py
git commit -m "feat: add GET /workflows/executions/active endpoint"
```

---

## Task 4: Frontend type + API client

**Files:**
- Modify: `frontend/src/types/workflow.ts`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add `ActiveExecutionItem` interface to `workflow.ts`**

In `frontend/src/types/workflow.ts`, after the `HistoryListResponse` interface (around line 460), add:

```typescript
export interface ActiveExecutionItem {
  execution_id: string;
  workflow_id: string;
  workflow_name: string;
  started_at: string;
}
```

- [ ] **Step 2: Add `getActiveExecutions` to `api.ts`**

In `frontend/src/services/api.ts`, add the import at the top of the file where other workflow types are imported:

```typescript
import type { ..., ActiveExecutionItem } from "@/types/workflow";
```

Then inside `workflowApi`, after `cancelExecution` (around line 576), add:

```typescript
  getActiveExecutions: async (): Promise<ActiveExecutionItem[]> => {
    const response = await api.get<ActiveExecutionItem[]>(
      "/workflows/executions/active",
    );
    return response.data;
  },
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/services/api.ts
git commit -m "feat: add ActiveExecutionItem type and getActiveExecutions API method"
```

---

## Task 5: Running entries in `ExecutionHistoryDialog.vue`

**Files:**
- Modify: `frontend/src/components/Panels/ExecutionHistoryDialog.vue`

- [ ] **Step 1: Add state and fetch logic**

In the `<script setup>` section, add imports and new reactive state after existing imports:

```typescript
import { Loader2, XCircle as XCircleIcon } from "lucide-vue-next";
import type { ActiveExecutionItem } from "@/types/workflow";
import { workflowApi } from "@/services/api";

const activeExecutions = ref<ActiveExecutionItem[]>([]);
const isCancellingId = ref<string | null>(null);

// Inject workflowId prop (already available via workflowStore.currentWorkflowId)
// workflowStore.currentWorkflow?.id is the active workflow UUID string
```

Replace the `watch` on `props.open` to also fetch active executions in parallel:

```typescript
watch(
  () => props.open,
  async (open) => {
    if (open) {
      capturedMinHeight.value = null;
      activeExecutions.value = [];
      const currentId = workflowStore.currentWorkflow?.id ?? null;
      const [, allActive] = await Promise.allSettled([
        workflowStore.fetchExecutionHistory(),
        workflowApi.getActiveExecutions(),
      ]);
      if (allActive.status === "fulfilled") {
        activeExecutions.value = currentId
          ? allActive.value.filter((e) => e.workflow_id === currentId)
          : [];
      }
      const firstId = executionHistoryList.value[0]?.id ?? null;
      selectedId.value = firstId;
      expandedNodes.value = new Set();
      if (firstId) {
        await workflowStore.fetchExecutionHistoryEntry(firstId);
      }
    }
  }
);
```

Add cancel handler function:

```typescript
async function cancelActiveExecution(item: ActiveExecutionItem): Promise<void> {
  isCancellingId.value = item.execution_id;
  try {
    await workflowApi.cancelExecution(item.workflow_id, item.execution_id);
  } catch {
    // 404 = already finished, treat as success
  } finally {
    isCancellingId.value = null;
    // Re-fetch both
    const currentId = workflowStore.currentWorkflow?.id ?? null;
    activeExecutions.value = [];
    const [, allActive] = await Promise.allSettled([
      workflowStore.fetchExecutionHistory(),
      workflowApi.getActiveExecutions(),
    ]);
    if (allActive.status === "fulfilled") {
      activeExecutions.value = currentId
        ? allActive.value.filter((e) => e.workflow_id === currentId)
        : [];
    }
  }
}
```

- [ ] **Step 2: Add running entries section to template**

In the `<template>`, inside the `<div v-else class="grid gap-4">` block, add this BEFORE the `<div class="space-y-2 max-h-48 overflow-auto pr-2">` that renders `executionHistoryList`:

```html
<!-- Running executions -->
<div
  v-if="activeExecutions.length > 0"
  class="space-y-1"
>
  <div
    v-for="active in activeExecutions"
    :key="active.execution_id"
    class="w-full text-left p-3 rounded-md border border-blue-500/30 bg-blue-500/10"
  >
    <div class="flex items-center justify-between gap-2">
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <Loader2 class="w-4 h-4 text-blue-400 animate-spin shrink-0" />
        <span class="text-sm font-medium text-blue-400">Running</span>
        <span class="text-sm text-muted-foreground truncate">
          {{ formatTime(active.started_at) }}
        </span>
      </div>
      <Button
        variant="ghost"
        size="sm"
        class="h-6 px-2 gap-1 text-red-400 hover:text-red-300 shrink-0"
        :disabled="isCancellingId === active.execution_id"
        @click="cancelActiveExecution(active)"
      >
        <Loader2
          v-if="isCancellingId === active.execution_id"
          class="w-3 h-3 animate-spin"
        />
        <XCircleIcon
          v-else
          class="w-3 h-3"
        />
        <span class="text-xs">Cancel</span>
      </Button>
    </div>
    <div class="text-xs text-muted-foreground mt-1">
      In progress...
    </div>
  </div>
  <div
    v-if="executionHistoryTotal > 0"
    class="border-t border-border/40 my-1"
  />
</div>
```

- [ ] **Step 3: Verify `currentWorkflow` is accessible**

The store exports `currentWorkflow` (a `ref<Workflow | null>`). The workflow's UUID is `workflowStore.currentWorkflow?.id`. No additional lookup required.

- [ ] **Step 4: Lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck 2>&1 | tail -30
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/ExecutionHistoryDialog.vue
git commit -m "feat: show running executions at top of ExecutionHistoryDialog with cancel"
```

---

## Task 6: Running entries in `ExecutionHistoryAllDialog.vue`

**Files:**
- Modify: `frontend/src/components/Panels/ExecutionHistoryAllDialog.vue`

- [ ] **Step 1: Add state and fetch logic**

In `<script setup>`, add after existing imports:

```typescript
import type { ActiveExecutionItem } from "@/types/workflow";

const activeExecutions = ref<ActiveExecutionItem[]>([]);
const isCancellingId = ref<string | null>(null);
```

Update `loadHistory()` to also fetch active executions in parallel:

```typescript
async function loadHistory(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [historyResult, activeResult] = await Promise.allSettled([
      workflowApi.getAllHistory(50, 0, searchQuery.value || undefined),
      workflowApi.getActiveExecutions(),
    ]);
    if (historyResult.status === "fulfilled") {
      executionHistory.value = historyResult.value.items;
      totalCount.value = historyResult.value.total;
      selectedId.value = historyResult.value.items[0]?.id ?? null;
      if (selectedId.value) {
        await ensureEntryLoaded(selectedId.value);
      }
    } else {
      executionHistory.value = [];
      totalCount.value = 0;
      error.value = "Failed to load history";
    }
    activeExecutions.value =
      activeResult.status === "fulfilled" ? activeResult.value : [];
  } finally {
    loading.value = false;
  }
}
```

Add cancel handler:

```typescript
async function cancelActiveExecution(item: ActiveExecutionItem): Promise<void> {
  isCancellingId.value = item.execution_id;
  try {
    await workflowApi.cancelExecution(item.workflow_id, item.execution_id);
  } catch {
    // 404 = already finished
  } finally {
    isCancellingId.value = null;
    await loadHistory();
  }
}
```

- [ ] **Step 2: Add missing imports in script**

At the top of `<script setup>`, `Loader2` and `XCircle` should already be in the lucide imports. If not, add them:

```typescript
import {
  ...,
  Loader2,
  XCircle as XCircleIcon,
} from "lucide-vue-next";
```

- [ ] **Step 3: Add running entries section to template**

In the `<template>`, inside the `v-else` block (after `v-else-if="totalCount === 0"`), BEFORE the `<div class="space-y-2 max-h-48 overflow-auto pr-2">`, add:

```html
<!-- Running executions -->
<div
  v-if="activeExecutions.length > 0"
  class="space-y-1"
>
  <div
    v-for="active in activeExecutions"
    :key="active.execution_id"
    class="w-full text-left p-3 rounded-md border border-blue-500/30 bg-blue-500/10"
  >
    <div class="flex items-center justify-between gap-2">
      <div class="flex items-center gap-2 min-w-0 flex-1">
        <Loader2 class="w-4 h-4 text-blue-400 animate-spin shrink-0" />
        <span class="text-sm font-medium text-blue-400">Running</span>
        <span class="text-sm text-muted-foreground truncate">
          {{ formatTime(active.started_at) }}
        </span>
      </div>
      <Button
        variant="ghost"
        size="sm"
        class="h-6 px-2 gap-1 text-red-400 hover:text-red-300 shrink-0"
        :disabled="isCancellingId === active.execution_id"
        @click="cancelActiveExecution(active)"
      >
        <Loader2
          v-if="isCancellingId === active.execution_id"
          class="w-3 h-3 animate-spin"
        />
        <XCircleIcon
          v-else
          class="w-3 h-3"
        />
        <span class="text-xs">Cancel</span>
      </Button>
    </div>
    <div class="text-xs text-muted-foreground mt-1">
      {{ active.workflow_name }} · In progress...
    </div>
  </div>
  <div
    v-if="totalCount > 0 || executionHistory.length > 0"
    class="border-t border-border/40 my-1"
  />
</div>
```

- [ ] **Step 4: Handle the `v-else-if="totalCount === 0"` edge case**

The "No executions yet" empty state is shown when `totalCount === 0`. If there are active executions but no history, we still want to show the running section. Wrap the empty-state div with an additional condition:

```html
<div
  v-else-if="totalCount === 0 && activeExecutions.length === 0"
  class="text-sm text-muted-foreground text-center py-8"
>
  No executions yet.
</div>

<div
  v-else
  class="grid gap-4"
>
```

- [ ] **Step 5: Lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck 2>&1 | tail -30
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Panels/ExecutionHistoryAllDialog.vue
git commit -m "feat: show running executions at top of ExecutionHistoryAllDialog with cancel"
```

---

## Task 7: Backend integration test for new endpoint

**Files:**
- Create: `backend/tests/test_active_executions_api.py`

- [ ] **Step 1: Write the test**

```python
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.workflows import list_active_workflow_executions
from app.models.schemas import ActiveExecutionItem
from app.services.execution_cancellation import (
    ExecutionCancellationHandle,
)
import datetime
import threading


def _make_handle(workflow_id: uuid.UUID, execution_id: uuid.UUID) -> ExecutionCancellationHandle:
    return ExecutionCancellationHandle(
        workflow_id=workflow_id,
        execution_id=execution_id,
        event=threading.Event(),
        started_at=datetime.datetime(2025, 1, 1, 12, 0, 0),
    )


class ListActiveWorkflowExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_when_no_active_executions(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        db = AsyncMock()

        with patch(
            "app.api.workflows.list_active_executions", return_value=[]
        ):
            result = await list_active_workflow_executions(
                current_user=user, db=db
            )

        self.assertEqual(result, [])
        db.execute.assert_not_called()

    async def test_filters_to_accessible_workflows(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id_owned = uuid.uuid4()
        wf_id_other = uuid.uuid4()
        ex_id_owned = uuid.uuid4()
        ex_id_other = uuid.uuid4()

        handles = [
            _make_handle(wf_id_owned, ex_id_owned),
            _make_handle(wf_id_other, ex_id_other),
        ]

        owned_workflow = MagicMock()
        owned_workflow.id = wf_id_owned
        owned_workflow.name = "My Workflow"

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [owned_workflow]
        db.execute.return_value = db_result

        with patch(
            "app.api.workflows.list_active_executions", return_value=handles
        ):
            result = await list_active_workflow_executions(
                current_user=user, db=db
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].execution_id, str(ex_id_owned))
        self.assertEqual(result[0].workflow_id, str(wf_id_owned))
        self.assertEqual(result[0].workflow_name, "My Workflow")
        self.assertIsInstance(result[0], ActiveExecutionItem)

    async def test_returns_started_at_from_handle(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()

        wf_id = uuid.uuid4()
        ex_id = uuid.uuid4()
        handle = _make_handle(wf_id, ex_id)

        workflow = MagicMock()
        workflow.id = wf_id
        workflow.name = "Workflow A"

        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalars.return_value.all.return_value = [workflow]
        db.execute.return_value = db_result

        with patch(
            "app.api.workflows.list_active_executions", return_value=[handle]
        ):
            result = await list_active_workflow_executions(
                current_user=user, db=db
            )

        self.assertEqual(result[0].started_at, datetime.datetime(2025, 1, 1, 12, 0, 0))
```

- [ ] **Step 2: Run the test**

```bash
cd backend && uv run pytest tests/test_active_executions_api.py -v 2>&1 | tail -20
```

Expected: all 3 tests PASS.

- [ ] **Step 3: Run full test suite**

```bash
cd .. && ./run_tests.sh 2>&1 | tail -30
```

Expected: all suites pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_active_executions_api.py
git commit -m "test: add integration tests for list_active_workflow_executions endpoint"
```

---

## Task 8: Final lint, typecheck, and verify

- [ ] **Step 1: Backend lint**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . 2>&1 | tail -10
```

Expected: no errors.

- [ ] **Step 2: Frontend lint + typecheck**

```bash
cd frontend && rm -rf dist && bun run lint && bun run typecheck 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 3: Run all backend tests**

```bash
cd .. && ./run_tests.sh 2>&1 | tail -20
```

Expected: all suites pass.

- [ ] **Step 4: Final commit (if any stray changes)**

If there are any formatting changes from ruff format:

```bash
git add -p
git commit -m "style: apply ruff formatting"
```
