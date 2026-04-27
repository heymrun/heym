# Agent Context Compression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically compress agent conversation history mid-run when token usage reaches 80% of the model's context window, preserving system + first-user + last-user messages and summarizing everything in between using the same model.

**Architecture:** A new `context_compressor.py` service provides `get_context_limit()` (API → KNOWN_LIMITS → default 128K) and `maybe_compress_messages()` (char-based estimate → LLM summarization). `execute_llm_with_tools` in `llm_service.py` calls these at the top of each iteration and emits compression events to traces, run history, and the frontend debug panel.

**Tech Stack:** Python 3.11+, asyncio, OpenAI-compatible sync client (`asyncio.to_thread`), pytest + unittest.IsolatedAsyncioTestCase, TypeScript (Vue 3 DebugPanel)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `backend/app/services/context_compressor.py` | `KNOWN_LIMITS`, `_estimate_tokens`, `get_context_limit`, `maybe_compress_messages` |
| **Create** | `backend/tests/test_context_compressor.py` | Unit tests for all compressor functions |
| **Modify** | `backend/app/services/llm_service.py` | Import compressor, call before loop + inside loop, emit trace/on_tool_call/tool_calls_collected |
| **Modify** | `frontend/src/components/Panels/DebugPanel.vue` | Special label for `_context_compression` in `formatToolCallTitle` |

---

## Task 1: Write failing tests for context_compressor.py

**Files:**
- Create: `backend/tests/test_context_compressor.py`

- [ ] **Step 1: Create the test file**

```python
# backend/tests/test_context_compressor.py
import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _make_messages(n_middle: int = 3) -> list[dict[str, Any]]:
    """Build [system, user, <n_middle assistant/tool pairs>, user_last]."""
    msgs: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a helpful agent."},
        {"role": "user", "content": "Do the task."},
    ]
    for i in range(n_middle):
        msgs.append({"role": "assistant", "content": f"Calling tool {i}", "tool_calls": []})
        msgs.append({"role": "tool", "content": f"Tool result {i}", "tool_call_id": f"tc_{i}"})
    msgs.append({"role": "user", "content": "Continue from here."})
    return msgs


class TestEstimateTokens(unittest.TestCase):
    def test_empty(self) -> None:
        from app.services.context_compressor import _estimate_tokens
        self.assertEqual(_estimate_tokens([]), 0)

    def test_single_short_message(self) -> None:
        from app.services.context_compressor import _estimate_tokens
        msgs = [{"role": "user", "content": "hi"}]
        tokens = _estimate_tokens(msgs)
        self.assertGreater(tokens, 0)

    def test_longer_messages_yield_more_tokens(self) -> None:
        from app.services.context_compressor import _estimate_tokens
        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "hi " * 500}]
        self.assertGreater(_estimate_tokens(long), _estimate_tokens(short))


class TestGetContextLimit(unittest.TestCase):
    def test_api_success_returns_api_value(self) -> None:
        from app.services.context_compressor import get_context_limit
        mock_model_info = MagicMock()
        mock_model_info.context_window = 200_000
        mock_client = MagicMock()
        mock_client.models.retrieve.return_value = mock_model_info
        result = get_context_limit("claude-3-5-sonnet-20241022", mock_client)
        self.assertEqual(result, 200_000)

    def test_api_failure_falls_back_to_known_limits(self) -> None:
        from app.services.context_compressor import get_context_limit
        mock_client = MagicMock()
        mock_client.models.retrieve.side_effect = Exception("API error")
        result = get_context_limit("gpt-4o-2024-11-20", mock_client)
        self.assertEqual(result, 128_000)

    def test_unknown_model_returns_default(self) -> None:
        from app.services.context_compressor import get_context_limit
        mock_client = MagicMock()
        mock_client.models.retrieve.side_effect = Exception("API error")
        result = get_context_limit("some-totally-unknown-model-xyz", mock_client)
        self.assertEqual(result, 128_000)

    def test_api_returns_non_int_falls_back_to_known_limits(self) -> None:
        from app.services.context_compressor import get_context_limit
        mock_model_info = MagicMock()
        mock_model_info.context_window = None
        mock_client = MagicMock()
        mock_client.models.retrieve.return_value = mock_model_info
        result = get_context_limit("gpt-4o", mock_client)
        self.assertEqual(result, 128_000)

    def test_gemini_model_matched_by_substring(self) -> None:
        from app.services.context_compressor import get_context_limit
        mock_client = MagicMock()
        mock_client.models.retrieve.side_effect = Exception("API error")
        result = get_context_limit("gemini-2.0-flash-001", mock_client)
        self.assertEqual(result, 1_000_000)


class TestMaybeCompressMessages(unittest.IsolatedAsyncioTestCase):
    def _make_mock_client(self, summary: str = "Summary of tool results.") -> MagicMock:
        mock_choice = MagicMock()
        mock_choice.message.content = summary
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    async def test_below_threshold_returns_unchanged(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=1)
        client = self._make_mock_client()
        # context_limit is huge so threshold not reached
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=10_000_000
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)
        client.chat.completions.create.assert_not_called()

    async def test_above_threshold_compresses(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client("Key findings: tool 0,1,2 ran successfully.")
        # context_limit tiny so threshold always exceeded
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertIsNotNone(info)
        self.assertLess(len(result), len(msgs))

    async def test_system_preserved_after_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[0]["content"], "You are a helpful agent.")

    async def test_first_user_preserved_after_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        user_msgs = [m for m in result if m["role"] == "user"]
        self.assertEqual(user_msgs[0]["content"], "Do the task.")

    async def test_last_user_preserved_after_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertEqual(result[-1]["role"], "user")
        self.assertEqual(result[-1]["content"], "Continue from here.")

    async def test_compressed_message_is_assistant_role(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client("Summary here.")
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        # result: [system, user_first, assistant(compressed), user_last]
        self.assertEqual(result[2]["role"], "assistant")
        self.assertIn("[Context compressed", result[2]["content"])

    async def test_info_dict_has_expected_keys(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=3)
        client = self._make_mock_client()
        _, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertIsNotNone(info)
        assert info is not None
        for key in ("messages_compressed", "messages_before_count", "messages_after_count",
                    "tokens_before", "tokens_after", "elapsed_ms"):
            self.assertIn(key, info)

    async def test_too_few_messages_skips_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        # Only system + one user = no middle to compress
        msgs = [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "Do the task."},
        ]
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)

    async def test_single_user_no_middle_skips_compression(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        # No last_user distinct from first_user — cannot compress
        msgs = [
            {"role": "system", "content": "System."},
            {"role": "user", "content": "Only user message."},
            {"role": "assistant", "content": "Assistant reply."},
        ]
        client = self._make_mock_client()
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)

    async def test_llm_failure_returns_original_messages(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        msgs = _make_messages(n_middle=3)
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("LLM error")
        result, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=mock_client, context_limit_tokens=1
        )
        self.assertEqual(result, msgs)
        self.assertIsNone(info)

    async def test_messages_compressed_count_matches_middle(self) -> None:
        from app.services.context_compressor import maybe_compress_messages
        n_middle = 4  # 4 messages in the middle (2 assistant + 2 tool)
        msgs = _make_messages(n_middle=2)  # 2 pairs = 4 messages
        client = self._make_mock_client()
        _, info = await maybe_compress_messages(
            msgs, model="gpt-4o", client=client, context_limit_tokens=1
        )
        assert info is not None
        self.assertEqual(info["messages_compressed"], n_middle)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and verify they ALL fail with ImportError**

```bash
cd backend && uv run pytest tests/test_context_compressor.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'app.services.context_compressor'`

---

## Task 2: Implement context_compressor.py

**Files:**
- Create: `backend/app/services/context_compressor.py`

- [ ] **Step 1: Create the implementation**

```python
# backend/app/services/context_compressor.py
"""Context compression for agent tool-calling loops.

Detects when the accumulated messages list approaches the model's context
window limit and replaces the middle messages with a single LLM-generated
summary, while preserving the system prompt, first user message, and last
user message unchanged.
"""
import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

KNOWN_LIMITS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "claude-3-5-sonnet": 200_000,
    "claude-3-7-sonnet": 200_000,
    "claude-opus-4": 200_000,
    "claude-haiku": 200_000,
    "gemini-1.5-pro": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
}

_DEFAULT_LIMIT = 128_000


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count from messages using a 4-chars-per-token heuristic."""
    total_chars = sum(len(json.dumps(m, default=str)) for m in messages)
    return total_chars // 4


def get_context_limit(model: str, client: Any) -> int:
    """Return the context window size for a model.

    Tries the provider's /models API first; falls back to KNOWN_LIMITS
    by substring match, then to _DEFAULT_LIMIT (128K) if unknown.
    """
    try:
        model_info = client.models.retrieve(model)
        limit = getattr(model_info, "context_window", None)
        if isinstance(limit, int) and limit > 0:
            return limit
    except Exception:
        pass

    model_lower = model.lower()
    for key, limit in KNOWN_LIMITS.items():
        if key in model_lower:
            return limit

    return _DEFAULT_LIMIT


async def maybe_compress_messages(
    messages: list[dict[str, Any]],
    model: str,
    client: Any,
    context_limit_tokens: int,
    threshold: float = 0.80,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Compress messages if estimated token usage exceeds threshold.

    Preservation rules:
      - First system message (if any) → always kept
      - First user message → always kept
      - Last user message → always kept
      - Everything else in between → replaced with a single LLM summary

    Returns:
        (messages, None) if no compression was performed.
        (compressed_messages, info_dict) if compression ran.

    info_dict keys: messages_compressed, messages_before_count,
                    messages_after_count, tokens_before, tokens_after,
                    elapsed_ms.

    On any LLM failure during summarization, returns the original messages
    unchanged (safe degradation).
    """
    tokens_before = _estimate_tokens(messages)
    if tokens_before < context_limit_tokens * threshold:
        return messages, None

    # Separate system message from the rest
    system_msg: dict[str, Any] | None = None
    non_system: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system" and system_msg is None:
            system_msg = m
        else:
            non_system.append(m)

    # Find first and last user message indices within non_system
    user_indices = [i for i, m in enumerate(non_system) if m.get("role") == "user"]
    if len(user_indices) < 2:
        # Only one (or zero) user messages — nothing between first and last to summarize
        return messages, None

    first_user_idx = user_indices[0]
    last_user_idx = user_indices[-1]
    middle = non_system[first_user_idx + 1 : last_user_idx]

    if not middle:
        return messages, None

    first_user = non_system[first_user_idx]
    last_user = non_system[last_user_idx]

    # Build summarization prompt
    serialized = json.dumps(middle, default=str, ensure_ascii=False)
    summarize_prompt = [
        {
            "role": "system",
            "content": (
                "You are summarizing an AI agent's internal reasoning and tool call results. "
                "Produce a concise factual summary preserving key findings, decisions, and tool "
                "outputs. Do not invent information."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Summarize these {len(middle)} agent messages concisely:\n\n{serialized}"
            ),
        },
    ]

    compress_start = time.time()
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=summarize_prompt,
            max_tokens=1024,
        )
        summary = response.choices[0].message.content or "(no summary)"
    except Exception as exc:
        logger.warning("Context compression LLM call failed: %s", exc)
        return messages, None
    compress_elapsed_ms = round((time.time() - compress_start) * 1000, 2)

    compressed_msg: dict[str, Any] = {
        "role": "assistant",
        "content": f"[Context compressed — {len(middle)} messages summarized]\n{summary}",
    }

    result_messages: list[dict[str, Any]] = []
    if system_msg is not None:
        result_messages.append(system_msg)
    result_messages.append(first_user)
    result_messages.append(compressed_msg)
    result_messages.append(last_user)

    tokens_after = _estimate_tokens(result_messages)

    logger.info(
        "Context compressed: %d messages → 4 messages, ~%d → ~%d tokens",
        len(messages),
        tokens_before,
        tokens_after,
    )

    info: dict[str, Any] = {
        "messages_compressed": len(middle),
        "messages_before_count": len(messages),
        "messages_after_count": len(result_messages),
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "elapsed_ms": compress_elapsed_ms,
    }
    return result_messages, info
```

- [ ] **Step 2: Run tests and verify they pass**

```bash
cd backend && uv run pytest tests/test_context_compressor.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
cd backend && git add app/services/context_compressor.py tests/test_context_compressor.py
git commit -m "feat: add context_compressor service with tests"
```

---

## Task 3: Integrate compression into llm_service.py

**Files:**
- Modify: `backend/app/services/llm_service.py` (around lines 584–652)

The integration adds 3 things to `execute_llm_with_tools`:
1. One-time `get_context_limit` call before the loop
2. `maybe_compress_messages` call at the top of each iteration
3. On compression: emit `on_tool_call` event, append to `tool_calls_collected`, call `_record_trace`

- [ ] **Step 1: Add import and context_limit retrieval before the loop**

Find this block (around line 584–590):
```python
        tool_calls_collected: list[dict[str, Any]] = copy.deepcopy(initial_tool_calls or [])
        last_assistant_turn_had_tool_calls = False
```

Add after it (before the `def _trace_request` local function):
```python
        from app.services.context_compressor import get_context_limit, maybe_compress_messages

        _context_limit = get_context_limit(model, client)
```

- [ ] **Step 2: Add compression call inside the iteration loop**

Find this block at the top of the loop (around line 648–652):
```python
        for iteration in range(max_tool_iterations):
            if should_abort is not None:
                abort_reason = should_abort()
                if abort_reason:
                    return _build_error_result(abort_reason)
            kwargs: dict[str, Any] = {
```

Replace with:
```python
        for iteration in range(max_tool_iterations):
            if should_abort is not None:
                abort_reason = should_abort()
                if abort_reason:
                    return _build_error_result(abort_reason)

            messages, _compression_info = await maybe_compress_messages(
                messages, model=model, client=client, context_limit_tokens=_context_limit
            )
            if _compression_info is not None:
                _comp_entry: dict[str, Any] = {
                    "name": "_context_compression",
                    "arguments": {
                        "messages_compressed": _compression_info["messages_compressed"],
                    },
                    "result": {
                        "tokens_before": _compression_info["tokens_before"],
                        "tokens_after": _compression_info["tokens_after"],
                    },
                    "elapsed_ms": _compression_info["elapsed_ms"],
                }
                tool_calls_collected.append(_comp_entry)
                if on_tool_call:
                    on_tool_call(
                        {
                            "name": "_context_compression",
                            "arguments": {
                                "messages_compressed": _compression_info["messages_compressed"],
                                "tokens_before": _compression_info["tokens_before"],
                                "tokens_after": _compression_info["tokens_after"],
                            },
                            "result": "Context compressed successfully",
                            "elapsed_ms": _compression_info["elapsed_ms"],
                            "phase": "compression",
                            "timestamp": int(time.time() * 1000),
                        }
                    )
                self._record_trace(
                    request_type="context.compression",
                    provider=provider,
                    model=model,
                    request={
                        "messages_before": _compression_info["messages_before_count"],
                        "tokens_estimated_before": _compression_info["tokens_before"],
                    },
                    response={
                        "messages_after": _compression_info["messages_after_count"],
                        "tokens_estimated_after": _compression_info["tokens_after"],
                    },
                    error=None,
                    elapsed_ms=_compression_info["elapsed_ms"],
                )

            kwargs: dict[str, Any] = {
```

- [ ] **Step 3: Run the full backend test suite**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: All tests PASS (including the new context_compressor tests).

- [ ] **Step 4: Run ruff lint and format**

```bash
cd backend && uv run ruff check app/services/llm_service.py app/services/context_compressor.py --fix
uv run ruff format app/services/llm_service.py app/services/context_compressor.py
```

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/llm_service.py
git commit -m "feat: integrate context compression into agent tool-calling loop"
```

---

## Task 4: Frontend — label compression events in DebugPanel

**Files:**
- Modify: `frontend/src/components/Panels/DebugPanel.vue:299-312`

The `formatToolCallTitle` function already handles special cases (e.g. `call_sub_workflow`). Add a case for `_context_compression` so it shows a human-readable label instead of raw JSON arguments.

- [ ] **Step 1: Update formatToolCallTitle**

Find this function (around line 299):
```typescript
function formatToolCallTitle(tc: ToolCallEntry): string {
  if (tc.name === "call_sub_workflow") {
    const wn = tc.workflow_name;
    const wid =
      typeof tc.arguments?.workflow_id === "string" ? tc.arguments.workflow_id : "";
    if (wn && wid) {
      return `call_sub_workflow(${wn}, ${wid})`;
    }
    if (wn) {
      return `call_sub_workflow(${wn})`;
    }
  }
  return `${tc.name}(${JSON.stringify(tc.arguments)})`;
}
```

Replace with:
```typescript
function formatToolCallTitle(tc: ToolCallEntry): string {
  if (tc.name === "_context_compression") {
    const compressed = tc.arguments?.messages_compressed;
    return typeof compressed === "number"
      ? `Context compressed (${compressed} messages → summary)`
      : "Context compressed";
  }
  if (tc.name === "call_sub_workflow") {
    const wn = tc.workflow_name;
    const wid =
      typeof tc.arguments?.workflow_id === "string" ? tc.arguments.workflow_id : "";
    if (wn && wid) {
      return `call_sub_workflow(${wn}, ${wid})`;
    }
    if (wn) {
      return `call_sub_workflow(${wn})`;
    }
  }
  return `${tc.name}(${JSON.stringify(tc.arguments)})`;
}
```

- [ ] **Step 2: Run frontend lint and typecheck**

```bash
cd frontend && bun run lint && bun run typecheck
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/Panels/DebugPanel.vue
git commit -m "feat: show context compression events in debug panel"
```

---

## Task 5: Run full test suite and final checks

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && ./run_tests.sh
```

Expected: All suites pass.

- [ ] **Step 2: Run backend lint**

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
```

Expected: No errors.

- [ ] **Step 3: Run frontend full build check**

```bash
cd frontend && rm -rf dist && bun run build
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Update docs via heym-documentation skill**

Invoke the `heym-documentation` skill to update user-facing documentation for this feature (medium feature per AGENTS.md policy).

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `context_compressor.py` service | Task 2 |
| `_estimate_tokens` (char/4 heuristic) | Task 2 |
| `get_context_limit` (API → KNOWN_LIMITS → default) | Task 2 |
| `maybe_compress_messages` (80% threshold, same model) | Task 2 |
| System + first user + last user preserved | Task 2 (impl + Task 1 tests) |
| LLM failure → safe fallback (return original) | Task 1 test + Task 2 impl |
| Integration at top of `execute_llm_with_tools` loop | Task 3 |
| `_record_trace` with `request_type="context.compression"` | Task 3 |
| `on_tool_call` compression event for frontend | Task 3 |
| `tool_calls_collected` entry for run history | Task 3 |
| Frontend DebugPanel label | Task 4 |
| Tests: below/above threshold, ≤3 msgs, API success/fail | Task 1 |
| Docs update (medium feature) | Task 5 |

All spec requirements covered. No placeholders. Type signatures consistent across tasks.
