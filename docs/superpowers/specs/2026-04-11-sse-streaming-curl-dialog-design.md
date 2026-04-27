# SSE Streaming in Curl Dialog — Design Spec

**Date:** 2026-04-11  
**Status:** Approved  
**Scope:** Medium feature — new DB columns, executor changes, curl dialog UI extension, docs update, unit tests

---

## 1. Overview

The curl dialog gains an **SSE Streaming** toggle. When enabled:

- The generated curl command targets `/execute/stream` (existing SSE endpoint) instead of `/execute`
- The backend enriches `node_start` events with a configurable per-node start message
- A new `node_complete` event is emitted for every node that finishes, carrying the full output
- Per-node configuration (start message text, send_start toggle) is persisted on the Workflow in the database
- All existing security features (auth_type, rate limiting, response caching) are fully respected — they already apply to `/execute/stream`

---

## 2. Architecture

```
curl dialog (SSE toggle ON)
        │
        ▼
POST /api/workflows/{id}/execute/stream   ← existing endpoint, extended
        │
        ├─ validate_workflow_auth()        ← unchanged (jwt / anon / header_auth)
        ├─ rate_limit check                ← unchanged
        ├─ cache check                     ← unchanged
        │
        └─ execute_workflow_streaming(sse_node_config=workflow.sse_node_config)
                │
                ├─ SSE: execution_started
                │
                ├─ per node:
                │     ├─ SSE: node_start  { message: "[START] LLM" }   ← if send_start true
                │     └─ SSE: node_complete { output: {...} }           ← always
                │
                └─ SSE: execution_complete
```

---

## 3. Data Model

### New Workflow columns

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `sse_enabled` | `Boolean` | `False` | Whether SSE mode is active for this workflow |
| `sse_node_config` | `JSON` | `{}` | Per-node SSE configuration, keyed by node_id |

### `sse_node_config` shape

```json
{
  "node-uuid-llm": {
    "send_start": true,
    "start_message": "[START] LLM"
  },
  "node-uuid-input": {
    "send_start": false,
    "start_message": null
  }
}
```

**Default behaviour** (node absent from config or config is null):
- `send_start: true`
- `start_message: "[START] {node_label}"`

### Pydantic schema changes (`models/schemas.py`)

- `WorkflowUpdate`: add `sse_enabled: bool | None = None`, `sse_node_config: dict | None = None`
- `WorkflowResponse`: add `sse_enabled: bool`, `sse_node_config: dict`

### TypeScript types (`types/workflow.ts`)

```typescript
interface SseNodeConfig {
  send_start: boolean;
  start_message: string | null;
}

interface Workflow {
  // ... existing fields ...
  sse_enabled: boolean;
  sse_node_config: Record<string, SseNodeConfig>;
}
```

---

## 4. SSE Event Protocol

### Existing events (unchanged)

```json
{ "type": "execution_started", "execution_id": "..." }
{ "type": "execution_complete", "status": "success", "outputs": {...}, "execution_time_ms": 123 }
```

### Extended `node_start`

`message` field is added only when `send_start: true` (or default):

```json
{ "type": "node_start", "node_id": "...", "node_label": "LLM", "message": "[START] LLM" }
```

When `send_start: false`, event is still emitted (for tracking) but without `message`:

```json
{ "type": "node_start", "node_id": "...", "node_label": "LLM" }
```

### New `node_complete`

Emitted by the **stream endpoint only** (`/execute/stream`) every time a node finishes successfully. The non-streaming `/execute` endpoint is unchanged. Always sent regardless of per-node SSE config:

```json
{
  "type": "node_complete",
  "node_id": "...",
  "node_label": "LLM",
  "output": { "text": "Hello world", ... }
}
```

---

## 5. Backend Changes

### 5.1 Alembic migration

File: `backend/alembic/versions/XXX_add_sse_config_to_workflows.py`

```python
op.add_column("workflows", sa.Column("sse_enabled", sa.Boolean(), nullable=False, server_default="false"))
op.add_column("workflows", sa.Column("sse_node_config", postgresql.JSON(), nullable=True))
```

### 5.2 DB model (`app/db/models.py`)

```python
sse_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
sse_node_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

### 5.3 `execute_workflow_streaming` — new `sse_node_config` parameter

```python
def execute_workflow_streaming(
    ...
    sse_node_config: dict | None = None,
) -> Generator[dict, None, None]:
    ...
    # node_start enrichment
    config = (sse_node_config or {}).get(node_id, {})
    send_start = config.get("send_start", True)
    message = config.get("start_message") or f"[START] {node_label}"
    event = {"type": "node_start", "node_id": node_id, "node_label": node_label}
    if send_start:
        event["message"] = message
    yield event

    # ... node executes ...

    # node_complete — always emitted
    yield {
        "type": "node_complete",
        "node_id": node_id,
        "node_label": node_label,
        "output": node_output,
    }
```

### 5.4 `execute_workflow_stream` endpoint (`app/api/workflows.py`)

Pass `workflow.sse_node_config` to `execute_workflow_streaming`:

```python
for event in execute_workflow_streaming(
    ...
    sse_node_config=workflow.sse_node_config or {},
):
```

### 5.5 Workflow update endpoint

Accept and persist `sse_enabled` and `sse_node_config` in the existing `PATCH /workflows/{id}` handler.

---

## 6. Frontend Changes

### 6.1 Curl dialog UI (`frontend/src/views/EditorView.vue`)

New **SSE Streaming** section placed between Rate Limit and Body:

```
[ Request Body Mode ]  [ Authentication ]          [ Copy cURL ]
──────────────────────────────────────────────────────────────────
  Response Cache  |  Rate Limit
──────────────────────────────────────────────────────────────────
  SSE Streaming   [  ●  ON  ]

  ┌─ Nodes ─────────────────────────────────────────────────────┐
  │  LLM          [✓] Send start   "[START] LLM"           ✎   │
  │  HTTP Request  [ ] Send start   "[START] HTTP Request"  ✎   │
  │  Output       [✓] Send start   "[START] Output"         ✎   │
  └─────────────────────────────────────────────────────────────┘
──────────────────────────────────────────────────────────────────
  Raw JSON Body / Command
```

**Interaction:**
- SSE toggle change → `PATCH /workflows/{id}` with `{ sse_enabled: bool }`, immediate
- Send start toggle change → `PATCH /workflows/{id}` with updated `sse_node_config`, immediate
- Pencil icon → inline input opens, saves on blur/Enter
- If `start_message` is null, input shows `[START] {nodeName}` as placeholder; editing sets a custom value

### 6.2 Curl command generation

**SSE OFF (existing):**
```bash
curl -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ..." \
  "https://app.heym.ai/api/workflows/{id}/execute" \
  -d '{"message": "Hello"}'
```

**SSE ON:**
```bash
curl -X POST --no-buffer \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "Authorization: Bearer ..." \
  "https://app.heym.ai/api/workflows/{id}/execute/stream" \
  -d '{"message": "Hello"}'
```

### 6.3 Reactive state additions (`EditorView.vue`)

```typescript
const sseEnabled = ref(false)               // synced from workflow
const sseNodeConfig = ref<Record<string, SseNodeConfig>>({})  // synced from workflow
const editingNodeMessage = ref<string | null>(null)  // node_id being edited
```

---

## 7. Unit Tests (`backend/tests/test_sse_streaming.py`)

| Test | Assertion |
|------|-----------|
| `test_node_start_message_from_config` | Custom message from config appears in `node_start` |
| `test_node_start_default_message_when_no_config` | No config → `[START] {label}` default |
| `test_node_start_no_message_when_send_start_false` | `send_start: false` → no `message` field |
| `test_node_complete_always_emitted` | `node_complete` event present for each finished node |
| `test_node_complete_contains_full_output` | `output` field matches node's full output dict |
| `test_sse_config_missing_node_uses_default` | Node absent from config → default send_start/message |

---

## 8. Documentation Updates

Via `heym-documentation` skill:

- **Update** `frontend/src/docs/content/reference/webhooks.md` — new SSE Streaming section under "Run with cURL Dialog"
- **Create** `frontend/src/docs/content/reference/sse-streaming.md` — dedicated reference page covering:
  - Event protocol (`execution_started`, `node_start`, `node_complete`, `execution_complete`)
  - Per-node configuration
  - curl command example with `--no-buffer`
  - Security notes (auth/rate-limit/cache still apply)
- **Update** `frontend/src/docs/manifest.ts` — add new doc to reference section

---

## 9. Out of Scope

- WebSocket support (SSE is sufficient for server-push)
- Per-node end messages (only node output is sent, automatically)
- Distributed SSE (SSE is per-connection, single instance)
- Frontend SSE client / EventSource API (this is external curl tooling only)
