# Agent Context Compression — Design Spec

**Date:** 2026-04-07  
**Status:** Approved  
**Scope:** Backend (llm_service, new context_compressor service, llm_trace) + frontend observability

---

## Problem

The AI agent node accumulates all messages (assistant reasoning + tool call results) across tool
iterations with no pruning. With up to 30 iterations and large tool results (web scraping, document
reads, sub-workflow outputs), the `messages` list easily exceeds model context limits, causing
API-level errors or silent quality degradation.

There is currently no compression, summarization, or truncation mechanism anywhere in the stack.

---

## Goal

Automatically compress agent conversation history mid-run when token usage approaches the model's
context window limit, preserving the most task-relevant messages and making compression events
visible in execution logs, history, and traces.

---

## Design

### Core preservation rule

When compression triggers, always keep:

| Position | Message | Reason |
|----------|---------|--------|
| First | `system` prompt | Agent identity and instructions |
| Second | First `user` message | Original task |
| Last | Most recent `user` message | Current / latest instruction |

Everything in between (assistant reasoning turns, tool call messages, tool result messages) is
replaced with a single LLM-generated summary block.

Compression is skipped if there are ≤ 3 messages total (nothing to summarize between anchors).

---

### 1. New service: `backend/app/services/context_compressor.py`

```python
async def maybe_compress_messages(
    messages: list[dict],
    model: str,
    client: Any,
    context_limit_tokens: int,
    threshold: float = 0.80,
    on_compressed: Callable[[dict], None] | None = None,
) -> list[dict]:
```

**Internal flow:**

1. `_estimate_tokens(messages)` — rough char-based estimate: `total_chars / 4`
2. If `estimated_tokens < context_limit * threshold` → return messages unchanged
3. Extract anchors: `system_msg`, `first_user_msg`, `last_user_msg`
4. Collect middle messages (everything between first and last user)
5. Build a summarization prompt from the middle messages
6. Call the same model/client: _"You are summarizing an AI agent's internal reasoning and tool
   results. Produce a concise factual summary preserving key findings, decisions, and tool outputs.
   Do not invent facts."_
7. Return: `[system_msg, first_user_msg, compressed_assistant_msg, last_user_msg]`
   where `compressed_assistant_msg` is:
   ```
   [Context compressed — N messages summarized]
   <LLM summary>
   ```

**`get_context_limit(model, client) -> int`:**

1. Try `client.models.retrieve(model)` → read `context_window` field
2. On any exception, fall back to `KNOWN_LIMITS` dict:
   ```python
   KNOWN_LIMITS = {
       "gpt-4o": 128_000,
       "gpt-4o-mini": 128_000,
       "gpt-4-turbo": 128_000,
       "claude-3-5-sonnet-20241022": 200_000,
       "claude-3-7-sonnet-20250219": 200_000,
       "claude-opus-4-6": 200_000,
       "gemini-1.5-pro": 1_000_000,
       "gemini-2.0-flash": 1_000_000,
       # default fallback
       "_default": 128_000,
   }
   ```
3. Match by substring (e.g. `"gpt-4o"` matches `"gpt-4o-2024-11-20"`)

---

### 2. Integration point: `backend/app/services/llm_service.py`

Inside `execute_llm_with_tools`, at the top of the `for iteration in range(max_tool_iterations)`
loop, before building `kwargs`:

```python
context_limit = await get_context_limit(model, client)
messages = await maybe_compress_messages(
    messages,
    model=model,
    client=client,
    context_limit_tokens=context_limit,
    threshold=0.80,
    on_compressed=_on_compression_event,
)
```

`_on_compression_event` is a local closure that:
- Calls `on_tool_call({"name": "_context_compression", "phase": "compression", ...})` for frontend
- Appends a `_compression` entry to `tool_calls_collected` for run history visibility

---

### 3. Observability

#### Execution trace (`llm_trace.py`)
A new trace entry with `request_type="context.compression"` is recorded whenever compression runs:
```json
{
  "request_type": "context.compression",
  "model": "<model>",
  "messages_before": N,
  "messages_after": 4,
  "tokens_estimated_before": X,
  "tokens_estimated_after": Y,
  "elapsed_ms": Z
}
```

#### Debug panel / execution history (frontend)
The `on_tool_call` callback receives a compression event:
```json
{
  "name": "_context_compression",
  "phase": "compression",
  "arguments": {
    "messages_compressed": N,
    "tokens_before": X,
    "tokens_after": Y
  },
  "result": "Context compressed successfully",
  "elapsed_ms": Z
}
```
This surfaces as a distinct row in the DebugPanel tool call list and execution run history,
labelled "Context compressed (N messages → summary)".

#### tool_calls_collected entry
A `_compression` dict is appended to `tool_calls_collected` so it persists in run history:
```json
{
  "name": "_context_compression",
  "arguments": { "messages_compressed": N },
  "result": { "summary_length": M },
  "elapsed_ms": Z
}
```

---

### 4. Tests: `backend/tests/test_context_compressor.py`

| Test | Expectation |
|------|-------------|
| Below threshold | Messages returned unchanged |
| Above threshold | system + first_user + compressed_assistant + last_user |
| ≤ 3 messages | No compression (nothing between anchors) |
| API limit fetch success | Uses API value |
| API limit fetch failure | Falls back to KNOWN_LIMITS, then 128K default |
| Summary prompt content | Middle messages included in summarization call |

---

### 5. Documentation

- This spec: `docs/superpowers/specs/2026-04-07-agent-context-compression-design.md`
- User-facing feature doc updated via `heym-documentation` skill after implementation

---

## Constraints

- Compression uses the **same model and client** as the agent — no extra credentials needed
- Compression is **always active** (not opt-in) — protects all users from context overflow
- System prompt, first user message, and last user message are **never summarized**
- Compression only triggers when `messages > 3` (anchors must be distinct)
- Token estimation is char-based (`chars / 4`) — intentionally approximate, fast, no tiktoken dep

---

## Out of Scope

- Per-node enable/disable toggle (can be added later)
- Streaming compression progress to frontend in real-time
- Compression of `conversation_history` passed in from outside the agent loop
