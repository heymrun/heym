# SSE Streaming Curl Dialog — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an SSE toggle to the curl dialog that switches the command URL to `/execute/stream`, persists per-node start message config in the DB, and enriches `node_start` SSE events with configurable messages.

**Architecture:** New `sse_enabled` (bool) and `sse_node_config` (JSON) columns on `Workflow`. Backend helper `build_node_start_message` computes the per-node SSE start message and is injected into the existing `execute_and_report` closure inside `execute_workflow_streaming`. Frontend curl dialog grows an SSE Streaming section with a toggle and per-node rows. `node_complete` events already exist — no executor changes needed for those.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 + Alembic (backend); Vue 3 + TypeScript strict + Pinia (frontend); pytest + unittest for tests.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `backend/tests/test_sse_streaming.py` | **Create** | Unit tests for `build_node_start_message` |
| `backend/app/services/workflow_executor.py` | **Modify** | Add `build_node_start_message`, add `sse_node_config` param to `execute_workflow_streaming`, enrich `node_start` in `execute_and_report` |
| `backend/alembic/versions/054_add_sse_config_to_workflows.py` | **Create** | Migration: `sse_enabled` + `sse_node_config` on `workflows` |
| `backend/app/db/models.py` | **Modify** | Add `sse_enabled`, `sse_node_config` mapped columns to `Workflow` |
| `backend/app/models/schemas.py` | **Modify** | Add fields to `WorkflowUpdate` and `WorkflowResponse` |
| `backend/app/api/workflows.py` | **Modify** | Persist `sse_enabled`/`sse_node_config` in update handler; pass `sse_node_config` to `execute_workflow_streaming` |
| `frontend/src/types/workflow.ts` | **Modify** | Add `SseNodeConfig` interface, update `Workflow` type |
| `frontend/src/services/api.ts` | **Modify** | Add `sse_enabled`, `sse_node_config` to `workflowApi.update` Pick |
| `frontend/src/views/EditorView.vue` | **Modify** | Add SSE refs, save functions, curl command update, SSE UI section |
| `frontend/src/docs/content/reference/sse-streaming.md` | **Create** | New doc page |
| `frontend/src/docs/content/reference/webhooks.md` | **Modify** | Add SSE link |
| `frontend/src/docs/manifest.ts` | **Modify** | Register `sse-streaming` in reference section |

---

## Task 1: Backend unit tests for `build_node_start_message`

**Files:**
- Create: `backend/tests/test_sse_streaming.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sse_streaming.py`:

```python
"""Unit tests for SSE node_start message enrichment."""

import unittest

from app.services.workflow_executor import build_node_start_message


class BuildNodeStartMessageTests(unittest.TestCase):
    """Verify build_node_start_message returns correct message or None."""

    def test_default_message_when_no_config(self) -> None:
        result = build_node_start_message("node-1", "LLM", None)
        self.assertEqual(result, "[START] LLM")

    def test_default_message_when_empty_config(self) -> None:
        result = build_node_start_message("node-1", "LLM", {})
        self.assertEqual(result, "[START] LLM")

    def test_default_message_when_node_not_in_config(self) -> None:
        config = {"other-node": {"send_start": True, "start_message": "Hi"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "[START] LLM")

    def test_custom_message_from_config(self) -> None:
        config = {"node-1": {"send_start": True, "start_message": "Custom start"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "Custom start")

    def test_null_start_message_falls_back_to_default(self) -> None:
        config = {"node-1": {"send_start": True, "start_message": None}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "[START] LLM")

    def test_empty_start_message_falls_back_to_default(self) -> None:
        config = {"node-1": {"send_start": True, "start_message": ""}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "[START] LLM")

    def test_returns_none_when_send_start_false(self) -> None:
        config = {"node-1": {"send_start": False, "start_message": None}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertIsNone(result)

    def test_returns_none_when_send_start_false_even_with_message(self) -> None:
        config = {"node-1": {"send_start": False, "start_message": "Should not appear"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertIsNone(result)

    def test_default_send_start_is_true(self) -> None:
        # Node in config but send_start not set — should default to True
        config = {"node-1": {"start_message": "Hello"}}
        result = build_node_start_message("node-1", "LLM", config)
        self.assertEqual(result, "Hello")
```

- [ ] **Step 2: Run tests to verify they fail (function not defined yet)**

```bash
cd backend && uv run pytest tests/test_sse_streaming.py -v
```

Expected: `ImportError: cannot import name 'build_node_start_message' from 'app.services.workflow_executor'`

---

## Task 2: Add `build_node_start_message` to executor + enrich `node_start`

**Files:**
- Modify: `backend/app/services/workflow_executor.py`

- [ ] **Step 1: Add `build_node_start_message` as a module-level function**

Search for the line `def execute_workflow_streaming(` in `workflow_executor.py` (around line 8436). Add the following function **directly above it** (before `execute_workflow_streaming`):

```python
def build_node_start_message(
    node_id: str,
    node_label: str,
    sse_node_config: dict | None,
) -> str | None:
    """Return the SSE start message for a node, or None if send_start is False.

    Reads per-node config from sse_node_config keyed by node_id.
    Falls back to '[START] {node_label}' when start_message is absent/null/empty.
    Returns None when send_start is explicitly False.
    """
    config = (sse_node_config or {}).get(node_id, {})
    send_start = config.get("send_start", True)
    if not send_start:
        return None
    return config.get("start_message") or f"[START] {node_label}"
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_sse_streaming.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 3: Add `sse_node_config` parameter to `execute_workflow_streaming`**

Find `def execute_workflow_streaming(` (around line 8436+). Change the signature from:

```python
def execute_workflow_streaming(
    workflow_id: uuid.UUID,
    nodes: list[dict],
    edges: list[dict],
    inputs: dict,
    workflow_cache: dict[str, dict] | None = None,
    test_run: bool = False,
    credentials_context: dict[str, str] | None = None,
    global_variables_context: dict[str, object] | None = None,
    trace_user_id: uuid.UUID | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    cancel_event: Event | None = None,
    executor_holder: dict | None = None,
):
```

To:

```python
def execute_workflow_streaming(
    workflow_id: uuid.UUID,
    nodes: list[dict],
    edges: list[dict],
    inputs: dict,
    workflow_cache: dict[str, dict] | None = None,
    test_run: bool = False,
    credentials_context: dict[str, str] | None = None,
    global_variables_context: dict[str, object] | None = None,
    trace_user_id: uuid.UUID | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    cancel_event: Event | None = None,
    executor_holder: dict | None = None,
    sse_node_config: dict | None = None,
):
```

- [ ] **Step 4: Enrich `node_start` in `execute_and_report`**

Inside `execute_workflow_streaming`, find `def execute_and_report(node_id: str) -> NodeResult:` (around line 8531). Change the `event_queue.put` for `node_start` from:

```python
        event_queue.put(
            {
                "type": "node_start",
                "node_id": node_id,
                "node_label": node_label,
            }
        )
```

To:

```python
        _node_start_event: dict = {
            "type": "node_start",
            "node_id": node_id,
            "node_label": node_label,
        }
        _sse_message = build_node_start_message(node_id, node_label, sse_node_config)
        if _sse_message is not None:
            _node_start_event["message"] = _sse_message
        event_queue.put(_node_start_event)
```

- [ ] **Step 5: Run full backend tests to ensure nothing is broken**

```bash
cd backend && uv run pytest tests/test_sse_streaming.py tests/test_workflow_execution_api.py tests/test_cancellation_by_trigger.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/services/workflow_executor.py tests/test_sse_streaming.py
git commit -m "feat: add build_node_start_message helper and enrich node_start SSE events"
```

---

## Task 3: Alembic migration — add SSE columns to workflows

**Files:**
- Create: `backend/alembic/versions/054_add_sse_config_to_workflows.py`

- [ ] **Step 1: Create the migration file**

Create `backend/alembic/versions/054_add_sse_config_to_workflows.py`:

```python
"""Add sse_enabled and sse_node_config columns to workflows table.

Revision ID: 054
Revises: 053
Create Date: 2026-04-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "054"
down_revision: str | None = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column("sse_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "workflows",
        sa.Column("sse_node_config", postgresql.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflows", "sse_node_config")
    op.drop_column("workflows", "sse_enabled")
```

- [ ] **Step 2: Run the migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: `Running upgrade 053 -> 054, Add sse_enabled and sse_node_config columns to workflows table`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/054_add_sse_config_to_workflows.py
git commit -m "feat: migration 054 — add sse_enabled and sse_node_config to workflows"
```

---

## Task 4: DB model — add SSE columns to Workflow

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add SSE columns to the `Workflow` model**

In `backend/app/db/models.py`, find the `Workflow` class. Locate the existing column block containing `cache_ttl_seconds` and `rate_limit_requests`. Add the two new columns immediately after `rate_limit_window_seconds`:

```python
    sse_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sse_node_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

Make sure `Boolean` and `JSON` are already imported at the top of the file (they are — used by other columns).

- [ ] **Step 2: Verify the app starts cleanly**

```bash
cd backend && uv run python -c "from app.db.models import Workflow; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add sse_enabled and sse_node_config to Workflow DB model"
```

---

## Task 5: Pydantic schemas — expose SSE fields in API

**Files:**
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: Add SSE fields to `WorkflowUpdate`**

In `backend/app/models/schemas.py`, find `class WorkflowUpdate`. Add these two fields at the end of the class:

```python
    sse_enabled: bool | None = None
    sse_node_config: dict | None = None
```

- [ ] **Step 2: Add SSE fields to `WorkflowResponse`**

In the same file, find `class WorkflowResponse`. Add after `rate_limit_window_seconds`:

```python
    sse_enabled: bool
    sse_node_config: dict | None
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat: add sse_enabled and sse_node_config to Pydantic workflow schemas"
```

---

## Task 6: API changes — persist SSE config + pass to executor

**Files:**
- Modify: `backend/app/api/workflows.py`

- [ ] **Step 1: Persist SSE fields in the workflow update handler**

In `backend/app/api/workflows.py`, find the workflow update handler (the function containing `if workflow_data.auth_type is not None:` around line 959). Add the following block immediately after the `rate_limit_window_seconds` handling:

```python
    if workflow_data.sse_enabled is not None:
        workflow.sse_enabled = workflow_data.sse_enabled
    if workflow_data.sse_node_config is not None:
        workflow.sse_node_config = workflow_data.sse_node_config
```

- [ ] **Step 2: Pass `sse_node_config` to `execute_workflow_streaming` in the stream endpoint**

In `backend/app/api/workflows.py`, find `execute_workflow_stream` function (contains `@router.post("/{workflow_id}/execute/stream")`). Inside `run_executor()`, find the `for event in execute_workflow_streaming(` call. Add `sse_node_config=workflow.sse_node_config or {}` as a keyword argument:

```python
            for event in execute_workflow_streaming(
                workflow_id=workflow.id,
                nodes=workflow.nodes,
                edges=workflow.edges,
                inputs=enriched_inputs,
                workflow_cache=workflow_cache,
                test_run=test_run,
                credentials_context=credentials_context,
                global_variables_context=global_variables_context,
                trace_user_id=trace_user_id,
                cancel_event=cancel_event,
                executor_holder=executor_holder,
                sse_node_config=workflow.sse_node_config or {},
            ):
```

- [ ] **Step 3: Run backend checks**

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
```

Fix any formatting issues with `uv run ruff format .`

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/test_sse_streaming.py tests/test_workflow_execution_api.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/workflows.py
git commit -m "feat: persist SSE config in workflow update and pass sse_node_config to stream executor"
```

---

## Task 7: Frontend types + API client

**Files:**
- Modify: `frontend/src/types/workflow.ts`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Add `SseNodeConfig` interface and update `Workflow` in `types/workflow.ts`**

In `frontend/src/types/workflow.ts`, add the new interface immediately before the `Workflow` interface:

```typescript
export interface SseNodeConfig {
  send_start: boolean;
  start_message: string | null;
}
```

Then in the `Workflow` interface, add after `rate_limit_window_seconds`:

```typescript
  sse_enabled: boolean;
  sse_node_config: Record<string, SseNodeConfig>;
```

- [ ] **Step 2: Update `workflowApi.update` Pick in `services/api.ts`**

In `frontend/src/services/api.ts`, find the `update` function inside `workflowApi` (the `Pick<Workflow, ...>` block around line 349). Add `"sse_enabled"` and `"sse_node_config"` to the union:

```typescript
  update: async (
    id: string,
    data: Partial<
      Pick<
        Workflow,
        | "name"
        | "description"
        | "nodes"
        | "edges"
        | "auth_type"
        | "auth_header_key"
        | "auth_header_value"
        | "webhook_body_mode"
        | "cache_ttl_seconds"
        | "rate_limit_requests"
        | "rate_limit_window_seconds"
        | "sse_enabled"
        | "sse_node_config"
      >
    >,
  ): Promise<Workflow> => {
    const response = await api.put<Workflow>(`/workflows/${id}`, data);
    return response.data;
  },
```

- [ ] **Step 3: Run frontend typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/services/api.ts
git commit -m "feat: add SseNodeConfig type and expose sse fields in workflowApi.update"
```

---

## Task 8: Frontend curl dialog — SSE UI

**Files:**
- Modify: `frontend/src/views/EditorView.vue`

This task has many sub-steps. Read `EditorView.vue` before starting to orient yourself. The curl dialog lives between lines ~1135 and ~1303.

- [ ] **Step 1: Add SSE-related imports to `<script setup>`**

In `EditorView.vue`, find the existing import line for `SseNodeConfig` — it doesn't exist yet. Add the import in the types import block at the top of `<script setup>`:

```typescript
import type { SseNodeConfig } from "@/types/workflow";
```

Also add the `Pencil` icon from lucide-vue-next to the existing lucide imports block (find the line that imports other icons like `Copy`, `TerminalSquare`, etc.):

```typescript
import { ..., Pencil } from "lucide-vue-next";
```

- [ ] **Step 2: Add SSE reactive refs after the existing curl refs**

Find the block containing:
```typescript
const curlCopied = ref(false);
```

Immediately after, add:

```typescript
const sseEnabled = ref(false);
const sseNodeConfig = ref<Record<string, SseNodeConfig>>({});
const editingNodeId = ref<string | null>(null);
const editingNodeMessage = ref("");
```

- [ ] **Step 3: Sync SSE state when the dialog opens**

Find `watch(curlOpen, (open) => {`. Inside it, after `syncCurlInputFromWorkflow();`, add SSE state sync. The block currently looks like:

```typescript
watch(curlOpen, (open) => {
  if (!open) return;
  syncCurlInputFromWorkflow();
  const workflow = workflowStore.currentWorkflow;
  if (workflow) {
    cacheTtlMinutes.value = workflow.cache_ttl_seconds ? Math.round(workflow.cache_ttl_seconds / 60) : 0;
    // ... rateLimitRequests etc
  }
});
```

Inside the `if (workflow)` block, add at the end:

```typescript
    sseEnabled.value = workflow.sse_enabled ?? false;
    sseNodeConfig.value = { ...(workflow.sse_node_config ?? {}) };
    editingNodeId.value = null;
```

- [ ] **Step 4: Add SSE save functions**

After `saveRateLimitSettings()`, add:

```typescript
async function saveSseEnabled(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  await workflowApi.update(workflowId.value, { sse_enabled: sseEnabled.value });
  workflowStore.currentWorkflow.sse_enabled = sseEnabled.value;
}

async function saveSseNodeConfig(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  await workflowApi.update(workflowId.value, { sse_node_config: sseNodeConfig.value });
  workflowStore.currentWorkflow.sse_node_config = { ...sseNodeConfig.value };
}

function getNodeSseConfig(nodeId: string): SseNodeConfig {
  return sseNodeConfig.value[nodeId] ?? { send_start: true, start_message: null };
}

async function toggleNodeSendStart(nodeId: string): Promise<void> {
  const current = getNodeSseConfig(nodeId);
  sseNodeConfig.value = {
    ...sseNodeConfig.value,
    [nodeId]: { ...current, send_start: !current.send_start },
  };
  await saveSseNodeConfig();
}

function startEditingNodeMessage(nodeId: string): void {
  const current = getNodeSseConfig(nodeId);
  editingNodeId.value = nodeId;
  editingNodeMessage.value = current.start_message ?? "";
}

async function commitNodeMessage(nodeId: string): Promise<void> {
  const current = getNodeSseConfig(nodeId);
  const trimmed = editingNodeMessage.value.trim();
  sseNodeConfig.value = {
    ...sseNodeConfig.value,
    [nodeId]: { ...current, start_message: trimmed || null },
  };
  editingNodeId.value = null;
  await saveSseNodeConfig();
}
```

- [ ] **Step 5: Update `curlCommand` computed to switch URL and headers for SSE**

Find `const curlCommand = computed(() => {`. Replace the entire computed (it currently builds the `url` and returns the curl string). Change only the `url` line and add `--no-buffer` + `Accept` header:

```typescript
const curlCommand = computed(() => {
  if (curlBodyError.value) {
    return "Fix JSON body to generate the cURL command.";
  }

  const basePath = sseEnabled.value
    ? `/api/workflows/${workflowId.value}/execute/stream`
    : `/api/workflows/${workflowId.value}/execute`;
  const url = `${window.location.origin}${basePath}`;
  const payload = stringifyWebhookJson(curlPayload.value);
  const escapedPayload = payload.replace(/'/g, "'\\''");
  const indentedPayload = escapedPayload
    .split("\n")
    .join("\n  ");

  const noBuffer = sseEnabled.value ? "--no-buffer \\\n  " : "";
  const acceptHeader = sseEnabled.value ? '-H "Accept: text/event-stream" \\\n  ' : "";

  let authHeader = "";
  if (authType.value === "jwt") {
    authHeader = `-H "Authorization: Bearer <your-jwt-token>" \\\n  `;
  } else if (authType.value === "header_auth") {
    const key = authHeaderKey.value || "X-API-Key";
    const val = authHeaderValue.value || "your-secret-value";
    authHeader = `-H "${key}: ${val}" \\\n  `;
  }

  return `curl -X POST ${noBuffer}-H "Content-Type: application/json" \\
  ${acceptHeader}${authHeader}"${url}" \\
  -d '${indentedPayload}'`;
});
```

- [ ] **Step 6: Add SSE Streaming section to the dialog template**

In the dialog template (between the closing `</div>` of the Rate Limit section around line ~1267 and the body section starting `<div class="space-y-2">`), add:

```html
        <div class="border-t pt-4 space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <Label class="text-sm font-medium">SSE Streaming</Label>
              <p class="text-xs text-muted-foreground mt-0.5">
                Stream node events via Server-Sent Events. Switches endpoint to
                <code class="text-xs bg-muted px-1 rounded">/execute/stream</code>.
              </p>
            </div>
            <input
              id="sse-enabled"
              type="checkbox"
              class="h-4 w-4 rounded border-input bg-background cursor-pointer"
              :checked="sseEnabled"
              @change="sseEnabled = ($event.target as HTMLInputElement).checked; saveSseEnabled()"
            >
          </div>

          <div
            v-if="sseEnabled && workflowStore.nodes.length > 0"
            class="space-y-1"
          >
            <Label class="text-xs text-muted-foreground uppercase tracking-wide">Node Start Messages</Label>
            <div class="border rounded divide-y">
              <div
                v-for="node in workflowStore.nodes.filter(n => n.type !== 'sticky')"
                :key="node.id"
                class="flex items-center gap-2 px-3 py-2"
              >
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5 rounded border-input bg-background cursor-pointer shrink-0"
                  :checked="getNodeSseConfig(node.id).send_start"
                  @change="toggleNodeSendStart(node.id)"
                >
                <span class="text-sm font-medium min-w-[80px] truncate">
                  {{ node.data?.label || node.type }}
                </span>
                <template v-if="editingNodeId === node.id">
                  <input
                    v-model="editingNodeMessage"
                    class="flex-1 text-xs border rounded px-2 py-0.5 bg-background font-mono"
                    :placeholder="`[START] ${node.data?.label || node.type}`"
                    @keydown.enter="commitNodeMessage(node.id)"
                    @keydown.escape="editingNodeId = null"
                    @blur="commitNodeMessage(node.id)"
                  >
                </template>
                <template v-else>
                  <span class="flex-1 text-xs text-muted-foreground font-mono truncate">
                    {{ getNodeSseConfig(node.id).start_message || `[START] ${node.data?.label || node.type}` }}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-6 w-6 shrink-0"
                    :disabled="!getNodeSseConfig(node.id).send_start"
                    @click="startEditingNodeMessage(node.id)"
                  >
                    <Pencil class="h-3 w-3" />
                  </Button>
                </template>
              </div>
            </div>
          </div>
        </div>
```

- [ ] **Step 7: Run typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Fix any errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/views/EditorView.vue
git commit -m "feat: add SSE streaming toggle and per-node message config to curl dialog"
```

---

## Task 9: Documentation

**Files:**
- Create: `frontend/src/docs/content/reference/sse-streaming.md`
- Modify: `frontend/src/docs/content/reference/webhooks.md`
- Modify: `frontend/src/docs/manifest.ts`

- [ ] **Step 1: Create `sse-streaming.md`**

Create `frontend/src/docs/content/reference/sse-streaming.md`:

```markdown
# SSE Streaming

Workflows can stream execution events in real-time using Server-Sent Events (SSE).

## Endpoint

`POST /api/workflows/{workflow_id}/execute/stream`

Same authentication, rate limiting, and caching rules as the standard [`/execute`](./webhooks.md) endpoint.

## Enabling SSE in the cURL Dialog

Open the **Run with cURL** dialog and check **SSE Streaming**. The generated command switches to the `/execute/stream` endpoint and adds `--no-buffer` and `Accept: text/event-stream` headers automatically.

## Event Types

All events are newline-delimited JSON prefixed with `data: `.

| Event type | When | Key fields |
|------------|------|-----------|
| `execution_started` | Immediately on start | `execution_id` |
| `node_start` | Before a node runs | `node_id`, `node_label`, `message`* |
| `node_retry` | On retry attempt | `node_id`, `attempt`, `max_attempts` |
| `node_complete` | After a node finishes | `node_id`, `node_label`, `status`, `output`, `execution_time_ms` |
| `final_output` | When an Output node succeeds | `node_label`, `output` |
| `execution_complete` | After all nodes finish | `status`, `outputs`, `execution_time_ms` |

\* `message` is present only when **Send start** is enabled for that node.

## Per-Node Start Messages

When SSE Streaming is enabled in the cURL dialog, each non-sticky node shows a row with:

- **Send start checkbox** — toggle whether a `node_start` event includes a `message` field
- **Start message** — default is `[START] {nodeName}`. Click the pencil icon to customize.

Config is saved to the workflow immediately on change.

## cURL Example

```bash
curl -X POST --no-buffer \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer <token>" \
  "https://app.heym.ai/api/workflows/{workflow_id}/execute/stream" \
  -d '{"message": "Hello"}'
```

Sample output:

```
data: {"type":"execution_started","execution_id":"..."}

data: {"type":"node_start","node_id":"...","node_label":"LLM","message":"[START] LLM"}

data: {"type":"node_complete","node_id":"...","node_label":"LLM","status":"success","output":{"text":"Hello world"},"execution_time_ms":312}

data: {"type":"execution_complete","status":"success","outputs":{"LLM":{"text":"Hello world"}},"execution_time_ms":315}
```

## Related

- [Webhooks](./webhooks.md) — Standard JSON execute endpoint
- [Node Types](./node-types.md) — All node types and their outputs
- [Security](./security.md) — Auth, rate limiting, credentials
```

- [ ] **Step 2: Update `webhooks.md` — add SSE link**

In `frontend/src/docs/content/reference/webhooks.md`, find the `## Related` section at the bottom. Add the SSE streaming link:

```markdown
- [SSE Streaming](./sse-streaming.md) – Stream node events in real-time via Server-Sent Events
```

- [ ] **Step 3: Add to manifest**

In `frontend/src/docs/manifest.ts`, find the `reference` section and its `items` array. Add after the existing `webhooks` entry (or at the end of the reference items, before `user-settings`):

```typescript
{ slug: "sse-streaming", title: "SSE Streaming" },
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/docs/content/reference/sse-streaming.md \
        frontend/src/docs/content/reference/webhooks.md \
        frontend/src/docs/manifest.ts
git commit -m "docs: add SSE streaming reference page and update webhooks doc"
```

---

## Task 10: Final verification

- [ ] **Step 1: Run full check**

```bash
cd /path/to/heymrun && ./check.sh
```

Expected: all lint, typecheck, and backend tests pass.

- [ ] **Step 2: Manual smoke test (if services are running)**

```bash
# Replace WORKFLOW_ID and TOKEN with real values
curl -X POST --no-buffer \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer TOKEN" \
  "http://localhost:10105/api/workflows/WORKFLOW_ID/execute/stream" \
  -d '{}'
```

Expected output: stream of `execution_started`, `node_start` (with `message` field), `node_complete`, `execution_complete` events.

- [ ] **Step 3: Final commit (if any stray changes)**

```bash
git status
# commit any remaining changes
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 8 spec requirements have a task
  - SSE toggle in curl dialog → Task 8 (Step 6)
  - Security respected → no changes to `validate_workflow_auth` (already on stream endpoint)
  - SSE events sent → already exists, Task 2 enriches node_start
  - Start message (optional, default `[START] nodeName`) → Task 2 + Task 8
  - Start message editable → Task 8 (Step 6, pencil icon)
  - Start message disable → Task 8 (send_start checkbox)
  - Node output in SSE → `node_complete` already exists in executor
  - Node list in dialog → Task 8 (Step 6)
  - Docs updated → Task 9
  - Backend tests → Task 1 + Task 2
- [x] **No placeholders** — all steps have complete code
- [x] **Type consistency** — `SseNodeConfig` defined in Task 7, used in Task 8; `build_node_start_message` defined in Task 2, tested in Task 1; `sse_node_config` param name consistent throughout
