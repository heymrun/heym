# Chat Tab: Tool Call Collapse, Context Badge & Auto-Compression — Design

**Date:** 2026-05-27
**Scope:** `/chats` (Dashboard Chat Assistant) tab — Heymrun frontend + backend
**Owner:** burak@mbakgun.com

## Goals

Four user-facing improvements to the `/chats` tab, requested in Turkish:

1. **Tool call cards:** While an LLM tool call is running, show the tool's input arguments below the tool label until the response arrives. After completion, collapse to a one-line summary; click to re-expand args + response summary.
2. **Context size badge:** A Cursor-style filled ring (small pill) below the input textarea, always visible, showing current context usage. Hover reveals a per-segment breakdown.
3. **Auto context compression:** Apply the same context-compression mechanism agent nodes already use (`maybe_compress_messages`, threshold 0.80). Surface compression as an inline tool-card with a special `_context_compression` status.
4. **Persisted, clickable tool history:** Tool call cards survive page reloads (persisted per assistant message). Click any past tool call to expand/collapse args + response.

## Non-Goals

- Backfilling tool history into previously-saved messages (`tool_calls=null` stays null).
- Exact tokenization (e.g. `tiktoken`). The 4-chars-per-token heuristic from `app/services/context_compressor.py:_estimate_tokens` is reused everywhere.
- Persisting compression summaries to DB as separate system messages — `maybe_compress_messages` re-runs each turn (idempotent), matching agent-node behavior.
- Context badge on conversation list / sidebar.
- Multi-tenant or per-team context window overrides.

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│ Browser (Vue.js / Pinia)                                           │
│                                                                    │
│ ChatConversation.vue                                               │
│  ├── ChatToolCall.vue  (per tool call, live + persisted)           │
│  ├── ChatContextBadge.vue  (bottom-left, hover popover)            │
│  └── chat store: streamState{toolCalls, contextUsage}              │
│         contextUsageByConv: Record<convId, ContextUsage>           │
└──────────────┬─────────────────────────────────────────────────────┘
               │ SSE: tool_start, tool_end, compressed, context,
               │      content, tool_output, workflow_created, title, done, error
┌──────────────▼─────────────────────────────────────────────────────┐
│ FastAPI backend                                                    │
│                                                                    │
│ chats.py::_process_chat                                            │
│  └─→ ai_assistant.py::stream_dashboard_chat                        │
│        ├─→ maybe_compress_messages() before each round             │
│        ├─→ yield {type:'tool_start', ...} / {type:'tool_end', ...} │
│        ├─→ yield {type:'compressed', ...} when compression fires   │
│        ├─→ yield {type:'context', used, limit, breakdown}          │
│        └─→ persist tool_calls list on assistant DashboardMessage   │
│                                                                    │
│ chats.py: GET /chats/{id}/context-summary  (idle/static state)     │
└────────────────────────────────────────────────────────────────────┘
```

## Data Model

### `DashboardMessage.tool_calls` (new column)

Alembic migration adds a single nullable column on `dashboard_messages`:

```python
op.add_column(
    "dashboard_messages",
    sa.Column("tool_calls", postgresql.JSONB, nullable=True),
)
```

**Shape** (mirrors `llm_service.py:1077-1103` agent-node pattern):

```jsonc
[
  {
    "id": "tc_abc123",
    "name": "execute_workflow",
    "label": "Running workflow \"Foo\"",
    "args": { "workflow_id": "...", "inputs": { /* ... */ } },
    "response_summary": "Completed in 1.2s · 3 nodes",
    "elapsed_ms": 1234,
    "status": "success"
  },
  {
    "id": "cmp_1",
    "name": "_context_compression",
    "label": "Context compressed",
    "args": { "messages_compressed": 18 },
    "response_summary": "~98k → ~12k tokens",
    "elapsed_ms": 412,
    "status": "compressed"
  }
]
```

Old rows: `tool_calls = NULL`; serializer maps to `[]` for API consumers.

### Existing tables unchanged

`DashboardConversation`, `User`, `Credential`, etc. — no schema changes.

## SSE Contract

`stream_dashboard_chat` currently yields: `content`, `step`, `tool_output`, `workflow_created`, `title`, `done`, `error`.

**Add** (replace `step`):

- `{ "type": "tool_start", "id": str, "name": str, "label": str, "args": object }`
  Emitted immediately before invoking a tool. `id` is a server-assigned monotonic string (e.g. `tc_{round}_{idx}`).

- `{ "type": "tool_end", "id": str, "response_summary": str, "elapsed_ms": float, "status": "success" | "error" }`
  Emitted after the tool returns (or fails). Frontend matches by `id`.

- `{ "type": "compressed", "messages_compressed": int, "tokens_before": int, "tokens_after": int, "elapsed_ms": float }`
  Emitted by `maybe_compress_messages` integration when compression runs in a round.

- `{ "type": "context", "used": int, "limit": int, "breakdown": { "system": int, "agents_md": int, "workflows": int, "user_rules": int, "history": int, "attachment": int } }`
  Emitted after each LLM round, sourced from `response.usage.prompt_tokens` (`used`) and `get_context_limit(model, client)` (`limit`). Breakdown computed at round start over the assembled `messages_to_use`.

**Remove:** `{type:'step', label}` events. The information is fully carried by `tool_start.label`. (Backward compat note: the only consumer is the chat frontend; no public API surface.)

`tool_output`, `workflow_created`, `title`, `content`, `done`, `error` remain unchanged.

## Backend Changes

### `backend/app/services/context_compressor.py`

No changes. Reused as-is.

### `backend/app/api/ai_assistant.py::stream_dashboard_chat`

1. Import `get_context_limit`, `maybe_compress_messages` (already imported by `llm_service.py:1006`).
2. At the start of the function, compute `_context_limit = get_context_limit(model, client)`.
3. At the **start of each round** (before the `client.chat.completions.create` call):
   - Call `messages_to_use, info = await maybe_compress_messages(messages_to_use, model, client, _context_limit)`.
   - If `info is not None`: yield a `compressed` SSE event and append a `_context_compression` entry to `tool_calls_collected` (new module-level list, see below).
   - Compute `breakdown` (see helper below) and yield `{type:'context', used: _estimate_tokens(messages_to_use), limit: _context_limit, breakdown}`. (Pre-call estimate.)
4. After the LLM call returns, if `response.usage` is present, yield `{type:'context', used: response.usage.prompt_tokens, limit: _context_limit, breakdown}` again with the authoritative number.
5. **Replace** every `yield f"data: {json.dumps({'type': 'step', 'label': step_label})}\n\n"` site with:
   - `tool_id = f"tc_{rounds}_{tc_idx}"` (use the iteration index in the `for tc in msg.tool_calls:` loop).
   - `yield {type:'tool_start', id: tool_id, name: tc.function.name, label: step_label, args: parsed_args}`.
   - After the tool returns, `yield {type:'tool_end', id: tool_id, response_summary: <derived>, elapsed_ms: step_ms, status: "success" | "error"}`.
6. The SSE event stream is the source of truth for persistence: `_process_chat` already parses every chunk (line 201-216). It maintains a `tool_calls_for_message: list[dict]` and updates it inline:
   - On `tool_start`: append a dict with `id, name, label, args, status='running'`.
   - On `tool_end`: find by `id`, set `response_summary, elapsed_ms, status`.
   - On `compressed`: append `_context_compression` entry with status=`compressed`.

   No additional SSE event types are introduced for persistence — the existing event stream carries enough data. `stream_dashboard_chat` does not need a new return value.

**Breakdown helper** (new module-level fn):

```python
def _context_breakdown(
    system_prompt: str,
    workflows_block: str,
    agents_md: str,
    user_rules: str,
    history: list[dict],
    attachment: FileAttachment | None,
) -> dict[str, int]:
    return {
        "system": _estimate_tokens([{"role": "system", "content": system_prompt}]) - _estimate_tokens([{"role": "system", "content": ""}]),
        "agents_md": _estimate_tokens([{"content": agents_md}]) if agents_md else 0,
        "workflows": _estimate_tokens([{"content": workflows_block}]) if workflows_block else 0,
        "user_rules": _estimate_tokens([{"content": user_rules}]) if user_rules else 0,
        "history": _estimate_tokens(history),
        "attachment": _estimate_tokens([{"content": attachment.content}]) if attachment else 0,
    }
```

Reuses `app.services.context_compressor._estimate_tokens` for consistency. The four sub-blocks (system, agents_md, workflows, user_rules) sum to ≈ the full system prompt; the breakdown shows them separately for transparency.

### `backend/app/api/chats.py`

#### `_process_chat` (line 94)

- Build `tool_calls_for_message` incrementally from the existing chunk-parse loop (line 201-216):
  ```python
  tool_calls_for_message: list[dict] = []
  async for chunk in stream_dashboard_chat(...):
      if chunk.startswith("data: "):
          try:
              payload = json.loads(chunk[6:].strip())
          except json.JSONDecodeError:
              payload = {}
          ptype = payload.get("type")
          if ptype == "tool_start":
              tool_calls_for_message.append({
                  "id": payload["id"], "name": payload["name"],
                  "label": payload["label"], "args": payload.get("args") or {},
                  "status": "running",
              })
          elif ptype == "tool_end":
              for entry in tool_calls_for_message:
                  if entry.get("id") == payload.get("id"):
                      entry["response_summary"] = payload.get("response_summary", "")
                      entry["elapsed_ms"] = payload.get("elapsed_ms")
                      entry["status"] = payload.get("status", "success")
                      break
          elif ptype == "compressed":
              tool_calls_for_message.append({
                  "id": f"cmp_{len(tool_calls_for_message)}",
                  "name": "_context_compression",
                  "label": "Context compressed",
                  "args": {"messages_compressed": payload.get("messages_compressed", 0)},
                  "response_summary": (
                      f"~{payload.get('tokens_before', 0)//1000}k → "
                      f"~{payload.get('tokens_after', 0)//1000}k tokens"
                  ),
                  "elapsed_ms": payload.get("elapsed_ms"),
                  "status": "compressed",
              })
          # existing handlers (content, workflow_created) continue here
      await registry.publish(conv_id, chunk)
  ```
- When persisting the assistant `DashboardMessage`, set `tool_calls = tool_calls_for_message or None`.

#### New endpoint: `GET /chats/{conversation_id}/context-summary`

```python
@router.get("/{conversation_id}/context-summary", response_model=ContextSummaryResponse)
async def get_context_summary(
    conversation_id: uuid.UUID,
    credential_id: uuid.UUID,
    model: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContextSummaryResponse:
    ...
```

Logic:
1. Load conversation + messages (same as `get_conversation`).
2. Load credential, decrypt config, build OpenAI client (same path as `_process_chat`).
3. Build `system_prompt`, `workflows_block`, `agents_md`, `user_rules` exactly as `_process_chat` does (extract into a private helper `_assemble_system_prompt_parts(user, db)` returning a tuple so both code paths share it; avoids drift).
4. Build `history = [{role, content} for m in messages]`, trimmed to `MAX_DASHBOARD_CHAT_HISTORY`.
5. `_context_limit = get_context_limit(model, client)`.
6. `breakdown = _context_breakdown(system_prompt, workflows_block, agents_md, user_rules, history, None)`.
7. `used = sum(breakdown.values())`.
8. Return `{used, limit: _context_limit, breakdown}`.

`MessageResponse` (in `chat_schemas.py`) gains `tool_calls: list[ToolCallRecord] | None = None`. New Pydantic model:

```python
class ToolCallRecord(BaseModel):
    id: str
    name: str
    label: str
    args: dict[str, Any] = Field(default_factory=dict)
    response_summary: str | None = None
    elapsed_ms: float | None = None
    status: Literal["running", "success", "error", "compressed"]
```

The `ConversationDetailResponse` includes these via the existing `messages` field.

### `backend/app/services/credentials_service.py` / `LLMModel` schema

`models/schemas.py:LLMModel` gains `context_window: int | None = None`. Populated by `credentials.get_models()` using `KNOWN_LIMITS` substring match (no provider API call here — cheap). Frontend uses this for the badge denominator when known.

This is a **light convenience**; the SSE `context.limit` from the backend remains authoritative.

## Frontend Changes

### `frontend/src/types/chat.ts`

Add:

```ts
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
```

Note: `ToolCall` fields stay snake_case to match the wire format (Pydantic default) and the existing convention for persisted fields in `types/chat.ts` (e.g. `Message.created_at`, `Conversation.is_pinned`). No mapping layer needed.

Extend `Message`:

```ts
export interface Message {
  /* existing */
  tool_calls?: ToolCall[]
}
```

Extend `SSEChunk` discriminated union with `tool_start`, `tool_end`, `compressed`, `context`. Remove `step` variant.

### `frontend/src/services/api.ts`

- `chatApi.subscribeStream` callback signature gains:
  - `onToolStart: (payload: ToolStartPayload) => void`
  - `onToolEnd: (payload: ToolEndPayload) => void`
  - `onCompressed: (payload: CompressedPayload) => void`
  - `onContext: (payload: ContextPayload) => void`
- Remove `onStep`.
- New: `chatApi.getContextSummary(conversationId, credentialId, model) → Promise<ContextUsage>`.

### `frontend/src/stores/chat.ts`

- `StreamState` shape:
  ```ts
  interface StreamState {
    content: string
    images: string[]
    toolCalls: ToolCall[]           // replaces steps
    contextUsage: ContextUsage | null
    workflowPreview: WorkflowPreview | null
    isStreaming: boolean
  }
  ```
- New state: `contextUsageByConv: Ref<Record<string, ContextUsage>>` (idle-state cache, populated by `loadContextSummary`).
- `subscribeStream` wiring:
  - `onToolStart` → push new `ToolCall` with `status:'running'`.
  - `onToolEnd` → find by `id`, set `responseSummary`, `elapsedMs`, `status`.
  - `onCompressed` → push synthetic `ToolCall` (`id:'cmp_{ts}'`, `name:'_context_compression'`, `status:'compressed'`, `label:'Context compressed'`, `args:{messages_compressed}`, `responseSummary: '~Xk → ~Yk tokens'`).
  - `onContext` → update `streamState.contextUsage` and `contextUsageByConv[conversationId]`.
- On `done`: copy `streamState.toolCalls` onto the new assistant `Message.toolCalls` before persisting.
- `loadConversation` hydrates `Message.toolCalls` from API.
- New action `loadContextSummary(conversationId, credentialId, model)`: fetches endpoint, updates `contextUsageByConv`.

### New component: `frontend/src/components/Chat/ChatToolCall.vue` (max 300 lines)

Props:
```ts
interface Props { toolCall: ToolCall }
```

Behavior:
- `isOpen = ref(props.toolCall.status === 'running')` — running auto-expands; others collapsed.
- Toggle on header click.
- Header layout:
  - `running`: `<Loader2 spin>` + label.
  - `success`: `✓` (green) + label + `· {elapsedMs}ms`.
  - `error`: `⚠` (red) + label.
  - `compressed`: `↯` (primary) + "Context compressed — N messages summarized".
- Body (when open):
  - `args`: pretty-printed JSON in `<pre class="max-h-64 overflow-auto">`.
  - `responseSummary`: paragraph below args.
- Stays under 300 lines per AGENTS.md TypeScript rules.

### New component: `frontend/src/components/Chat/ChatContextBadge.vue`

Props:
```ts
interface Props {
  contextUsage: ContextUsage | null
  draftTokens?: number
}
```

Layout:
- Compact pill, ~140px wide max.
- Conic-gradient ring (24px diameter) reflecting `(used + draftTokens) / limit`.
  - <0.80 → primary color; 0.80–0.95 → amber; ≥0.95 → red.
- Label: `{percentage}% · ~{used_k}k` (e.g. `12% · ~9.2k`).
- Hover (desktop) / tap (mobile) → popover with breakdown table. Use existing `Tooltip` pattern from `components/ui/`, or inline `absolute` div with `v-if="hovered"`.
- If `contextUsage === null`: render nothing (`v-if`) — no skeleton flicker.

### `frontend/src/components/Chat/ChatConversation.vue`

1. Replace persisted step rendering: in the assistant message block (line ~960), before the markdown body, render `<ChatToolCall v-for="tc in msg.toolCalls" :key="tc.id" :tool-call="tc" />`.
2. Replace streaming step rendering (lines 982–1003): replace the `streamState.steps.length > 0` block with `<ChatToolCall v-for="tc in streamState.toolCalls" :key="tc.id" :tool-call="tc" />`.
3. Add `<ChatContextBadge>` inside `.chat-input-area`, immediately above the `<form>`:
   ```html
   <div class="flex items-center justify-between gap-2 mb-1.5 px-1">
     <ChatContextBadge
       :context-usage="streamState.contextUsage ?? chatStore.contextUsageByConv[conversationId] ?? null"
       :draft-tokens="draftTokens"
     />
     <!-- existing attachment chip / error message moves here -->
   </div>
   ```
4. New computed: `draftTokens = computed(() => estimateTokens(input.value))`.
5. New helper `frontend/src/lib/contextEstimator.ts`:
   ```ts
   export function estimateTokens(payload: unknown): number {
     return Math.floor(JSON.stringify(payload).length / 4)
   }
   ```
6. Trigger `loadContextSummary` after `loadConversationForRoute` resolves and credentials are ready (i.e. in `_applyConversationSession`). Re-trigger when `selectedModel` or `selectedCredentialId` changes.

### `frontend/src/views/ChatsView.vue`

No changes (delegate UI to `ChatConversation.vue`).

## Behavioral Edge Cases

- **Background (non-active) stream:** `_subscribeToBackgroundStream` in `stores/chat.ts:123` currently ignores `step` payloads. Update it to ignore `tool_start`/`tool_end`/`compressed`/`context` similarly — these are only meaningful when foreground.
- **Stream cancellation:** When `cancelStreaming` aborts, in-flight tool cards with `status:'running'` should remain visible (they're already attached to the streamState). After cancel, `_clearStreamState` wipes them — that matches existing UX where cancel discards the partial assistant response.
- **No credentials:** Context badge: `contextUsage === null`, hidden. `loadContextSummary` only fires when both credential + model are set.
- **Empty conversation (no messages yet):** `loadContextSummary` returns breakdown with `history=0`. Badge shows ~system size only.
- **Compression during typing:** Not possible (compression fires only inside `_process_chat`). Draft tokens are estimated client-side and never trigger compression.
- **Migration backward compat:** Frontend handles `tool_calls: null` from the API by mapping to `undefined` / `[]` — no crash on old data.

## Testing

### Backend (`backend/tests/`)

1. `test_chats_api.py`:
   - Create conversation, send message, verify saved assistant `DashboardMessage` has `tool_calls` populated when tools fired.
   - `GET /chats/{id}/context-summary` returns `used`, `limit`, `breakdown` with `limit=128_000` for `gpt-4o-mini`.
   - Old assistant message with `tool_calls=NULL` is returned as `null` (or `[]`) without server error.
2. `test_ai_assistant_dashboard_chat.py`:
   - Mock LLM to return 1 tool call (`list_workflows`), assert SSE stream contains `tool_start` then `tool_end` with matching `id`.
   - Mock LLM `usage.prompt_tokens=42` → assert `context` event with `used=42`.
   - Force compression: set `MAX_DASHBOARD_CHAT_HISTORY` higher and feed bulky messages → assert `compressed` event yielded and `_context_compression` entry appears in final `tool_calls_final`.
3. `test_context_compressor.py`: no changes.

### Frontend

No automated tests (per AGENTS.md). Required pre-push checks:
- `cd frontend && bun run lint`
- `cd frontend && bun run typecheck`
- `cd frontend && bun run build`

### Manual verification (UI)

Documented in the rollout section below.

## Rollout

1. `backend/alembic/versions/<rev>_dashboard_message_tool_calls.py` migration.
2. Backend code changes (SSE events, endpoint, schema). `./check.sh` green.
3. Frontend changes. `bun run lint` + `bun run typecheck` + `bun run build` green.
4. `./run.sh` and verify:
   - "List my workflows" → tool card transitions `running → success`; click to expand args + result.
   - Reload page → card persists, collapsed by default.
   - Long session (force `MAX_DASHBOARD_CHAT_HISTORY` low for testing) → compression card appears in chat history; ring turns amber/red as usage rises.
   - Hover badge → breakdown numbers sum to `used`.
   - Mobile viewport: badge legible, tap opens popover, layout doesn't overflow.
5. Update `frontend/src/docs/content/tabs/chat-tab.md` via the `heym-documentation` skill (medium-size feature).

## Open Questions Resolved

- **Tool input semantics** → tool arguments (LLM-supplied `args`).
- **Collapsed vs expanded layout** → label + tool name + duration / args + response summary.
- **Persistence** → JSONB column, hydrated on conversation load.
- **Context metric** → tokens (4-chars-per-token heuristic).
- **Context window source** → agent-node `get_context_limit()` (provider API → KNOWN_LIMITS → 128K default).
- **Compression UX** → inline tool card with `_context_compression` status, persisted with the turn.
- **Badge placement** → bottom-left of `chat-input-area`, always visible.

## References

- Existing agent-node compression: `backend/app/services/llm_service.py:1006-1103`.
- Compression service: `backend/app/services/context_compressor.py`.
- Current chat SSE producer: `backend/app/api/ai_assistant.py::stream_dashboard_chat` (lines 1988-2769).
- Current frontend store: `frontend/src/stores/chat.ts`.
- Current view: `frontend/src/components/Chat/ChatConversation.vue`.
