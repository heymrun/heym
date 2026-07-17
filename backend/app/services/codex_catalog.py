"""Codex CLI model and reasoning-effort catalog (learn.chatgpt.com/docs/models)."""

from __future__ import annotations

# Recommended and other ChatGPT-sign-in models; deprecated ids omitted (gpt-5.2, gpt-5.3-codex).
CODEX_MODEL_SUGGESTIONS: tuple[str, ...] = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.6",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex-spark",
)

# Codex CLI `model_reasoning_effort` values (GPT-5.6 adds xhigh/max/ultra on supported plans).
CODEX_REASONING_EFFORTS: frozenset[str] = frozenset(
    {"low", "medium", "high", "xhigh", "max", "ultra"}
)
