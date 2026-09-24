"""Context compression for agent tool-calling loops.

Detects when the accumulated messages list approaches the model's context
window limit and replaces the middle messages with a single LLM-generated
summary, while preserving the system prompt, first user message, and recent
tool iterations unchanged.
"""

import asyncio
import json
import logging
import time
from typing import Any

from app.services.text_truncation import keep_head_and_tail

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4

# Context window sizes by model name (substring match, case-insensitive).
# Sources: OpenAI API docs, Anthropic API docs, Google AI Studio — 2025-06.
# The provider API is always tried first; these are fallback values.
KNOWN_LIMITS: dict[str, int] = {
    # OpenAI
    "gpt-4.1": 1_047_576,
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4.5": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    # OpenAI reasoning
    "o4-mini": 200_000,
    "o3-mini": 200_000,
    "o1-mini": 128_000,
    "o3": 200_000,
    "o1": 200_000,
    # Anthropic Claude
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-3-7-sonnet": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-haiku": 200_000,
    "claude-haiku": 200_000,
    # Google Gemini
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
}

_DEFAULT_LIMIT = 128_000
_HARD_COMPRESSION_TARGET_TOKENS = 16_000
_HARD_COMPRESSION_MIN_TARGET_TOKENS = 2_000

# Number of trailing messages (after the first user message) to always keep
# intact when compressing a single-turn tool-calling loop.
_SINGLE_TURN_KEEP_TAIL = 4


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count from messages using a 4-chars-per-token heuristic."""
    total_chars = sum(len(json.dumps(m, default=str)) for m in messages)
    return total_chars // _CHARS_PER_TOKEN


def hard_compression_target_tokens(context_limit_tokens: int) -> int:
    """Return a conservative target for hard context compression."""
    if context_limit_tokens <= 0:
        return _HARD_COMPRESSION_TARGET_TOKENS
    return max(
        _HARD_COMPRESSION_MIN_TARGET_TOKENS,
        min(_HARD_COMPRESSION_TARGET_TOKENS, int(context_limit_tokens * 0.75)),
    )


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            split_at = text.rfind("\n\n", start, end)
            if split_at > start + max_chars // 2:
                end = split_at
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end, start + 1)
    return chunks


def _fit_text_to_token_budget(text: str, token_budget: int) -> str:
    max_chars = max(1, token_budget * _CHARS_PER_TOKEN)
    marker = "\n\n[... content omitted during hard context compression ...]\n\n"
    return keep_head_and_tail(text, max_chars, marker)


def _serialize_messages_for_summary(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "unknown")
        parts.append(f"[{index}] role={role}")
        if message.get("name"):
            parts.append(f"name={message['name']}")
        if message.get("tool_call_id"):
            parts.append(f"tool_call_id={message['tool_call_id']}")
        if message.get("tool_calls"):
            parts.append("tool_calls=" + json.dumps(message["tool_calls"], default=str))
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, default=str, ensure_ascii=False)
        parts.append(content)
    return "\n".join(parts)


async def _summarize_text_chunk(
    *,
    text: str,
    model: str,
    client: Any,
    max_tokens: int,
    part_label: str,
) -> str:
    prompt = [
        {
            "role": "system",
            "content": (
                "You are compressing oversized chat context. Preserve the user's request, "
                "important facts, tool results, IDs, decisions, and unresolved next steps. "
                "Do not invent information."
            ),
        },
        {
            "role": "user",
            "content": f"Compress this chat context section ({part_label}):\n\n{text}",
        },
    ]
    try:
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=prompt,
            max_tokens=max_tokens,
        )
        summary = (response.choices[0].message.content or "").strip()
        if summary:
            return summary
    except Exception as exc:
        logger.warning("Hard context compression chunk failed: %s", exc)

    return _fit_text_to_token_budget(text, max_tokens)


async def _summarize_text_to_budget(
    *,
    text: str,
    model: str,
    client: Any,
    target_tokens: int,
) -> str:
    chunk_token_budget = max(
        1_000,
        min(12_000, max(_HARD_COMPRESSION_MIN_TARGET_TOKENS, target_tokens - 2_000)),
    )
    max_chunk_chars = chunk_token_budget * _CHARS_PER_TOKEN
    summary = text

    for _pass_number in range(3):
        chunks = _chunk_text(summary, max_chunk_chars)
        if len(chunks) == 1 and len(summary) <= target_tokens * _CHARS_PER_TOKEN:
            break

        chunk_summary_tokens = max(256, min(1_024, target_tokens // max(len(chunks), 1)))
        summaries: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            summaries.append(
                await _summarize_text_chunk(
                    text=chunk,
                    model=model,
                    client=client,
                    max_tokens=chunk_summary_tokens,
                    part_label=f"{index}/{len(chunks)}",
                )
            )
        summary = "\n\n".join(summaries)
        if len(summary) <= target_tokens * _CHARS_PER_TOKEN:
            break

    return _fit_text_to_token_budget(summary, target_tokens)


def get_context_limit(model: str, client: Any) -> int:
    """Return the context window size for a model.

    Prefer ``KNOWN_LIMITS`` for common models so idle chat pages never block the
    asyncio event loop on a synchronous provider round-trip. Invalid API keys and
    provider 5xx retries can take tens of seconds; holding the loop that long
    stalls every other request on the worker (including conversation deletes).

    Unknown models still consult the provider ``/models`` API; on failure fall
    back to ``_DEFAULT_LIMIT`` (128K).
    """
    model_lower = model.lower()
    for key, limit in KNOWN_LIMITS.items():
        if key in model_lower:
            return limit

    try:
        model_info = client.models.retrieve(model)
        limit = getattr(model_info, "context_window", None)
        if isinstance(limit, int) and limit > 0:
            return limit
    except Exception:
        pass

    return _DEFAULT_LIMIT


async def maybe_compress_messages(
    messages: list[dict[str, Any]],
    model: str,
    client: Any,
    context_limit_tokens: int,
    threshold: float = 0.80,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Compress messages if estimated token usage exceeds threshold.

    Two compression strategies are applied depending on conversation shape:

    **Multi-turn** (≥2 user messages): compress everything between the first
    and last user messages. Both anchors are preserved verbatim.

    **Single-turn tool loop** (1 user message): keep system + user message,
    compress old tool iterations, and keep the most recent
    _SINGLE_TURN_KEEP_TAIL messages intact.

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

    # Locate user messages
    user_indices = [i for i, m in enumerate(non_system) if m.get("role") == "user"]
    if not user_indices:
        return messages, None

    first_user_idx = user_indices[0]
    first_user = non_system[first_user_idx]

    if len(user_indices) >= 2:
        # Multi-turn: compress the stretch between first and last user messages
        last_user_idx = user_indices[-1]
        middle = non_system[first_user_idx + 1 : last_user_idx]
        tail = non_system[last_user_idx:]
    else:
        # Single-turn tool loop: compress old iterations, keep recent tail
        after_first_user = non_system[first_user_idx + 1 :]
        if len(after_first_user) <= _SINGLE_TURN_KEEP_TAIL:
            return messages, None
        middle = after_first_user[:-_SINGLE_TURN_KEEP_TAIL]
        tail = after_first_user[-_SINGLE_TURN_KEEP_TAIL:]

    if not middle:
        return messages, None

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
            "content": (f"Summarize these {len(middle)} agent messages concisely:\n\n{serialized}"),
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
    result_messages.extend(tail)

    tokens_after = _estimate_tokens(result_messages)

    logger.info(
        "Context compressed: %d messages → %d messages, ~%d → ~%d tokens",
        len(messages),
        len(result_messages),
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


async def hard_compress_messages(
    messages: list[dict[str, Any]],
    model: str,
    client: Any,
    target_tokens: int = _HARD_COMPRESSION_TARGET_TOKENS,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Aggressively collapse all non-system context into one compact user message.

    This is used as a last-resort fallback when normal middle-message compression
    cannot make the request fit, such as a single oversized first user message.
    It intentionally does not preserve user/tool messages verbatim.
    """
    non_system = [message for message in messages if message.get("role") != "system"]
    if not non_system:
        return messages, None

    compress_start = time.time()
    tokens_before = _estimate_tokens(messages)
    system_msg = next((message for message in messages if message.get("role") == "system"), None)
    system_tokens = _estimate_tokens([system_msg]) if system_msg is not None else 0
    summary_token_budget = max(
        500,
        target_tokens - system_tokens - 250,
    )

    serialized = _serialize_messages_for_summary(non_system)
    summary = await _summarize_text_to_budget(
        text=serialized,
        model=model,
        client=client,
        target_tokens=summary_token_budget,
    )
    content = (
        f"[Context hard-compressed - {len(non_system)} messages summarized to fit the "
        "model limit]\n"
        f"{_fit_text_to_token_budget(summary, summary_token_budget)}"
    )

    result_messages: list[dict[str, Any]] = []
    if system_msg is not None:
        result_messages.append(system_msg)
    result_messages.append({"role": "user", "content": content})

    tokens_after = _estimate_tokens(result_messages)
    if tokens_after > target_tokens:
        overflow_budget = max(250, summary_token_budget - (tokens_after - target_tokens) - 250)
        result_messages[-1]["content"] = (
            f"[Context hard-compressed - {len(non_system)} messages summarized to fit the "
            "model limit]\n"
            f"{_fit_text_to_token_budget(summary, overflow_budget)}"
        )
        tokens_after = _estimate_tokens(result_messages)

    elapsed_ms = round((time.time() - compress_start) * 1000, 2)
    logger.info(
        "Hard context compressed: %d messages -> %d messages, ~%d -> ~%d tokens",
        len(messages),
        len(result_messages),
        tokens_before,
        tokens_after,
    )

    return result_messages, {
        "messages_compressed": len(non_system),
        "messages_before_count": len(messages),
        "messages_after_count": len(result_messages),
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "elapsed_ms": elapsed_ms,
        "mode": "hard",
    }
