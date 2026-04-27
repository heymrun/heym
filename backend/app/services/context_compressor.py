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

logger = logging.getLogger(__name__)

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

# Number of trailing messages (after the first user message) to always keep
# intact when compressing a single-turn tool-calling loop.
_SINGLE_TURN_KEEP_TAIL = 4


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
