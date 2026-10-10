"""Tones for the status column of a Chart Output table.

A table widget can render one column as colored chips. Every value in that column
gets one of five tones: common words get one without configuration, and the node's
``statusTones`` map overrides or extends them. Heym's dashboard and Heym Work render
the resolved map as it comes, so both show the same colors.
"""

from collections.abc import Iterable
from typing import Any

STATUS_TONES = ("success", "attention", "failure", "waiting", "neutral")
DEFAULT_TONE = "neutral"

_DEFAULT_WORDS: dict[str, tuple[str, ...]] = {
    "success": (
        "success",
        "successful",
        "succeeded",
        "done",
        "complete",
        "completed",
        "approved",
        "active",
        "ok",
        "paid",
        "passed",
        "healthy",
        "resolved",
        "won",
        "delivered",
        "published",
    ),
    "attention": (
        "warning",
        "attention",
        "review",
        "needs review",
        "at risk",
        "partial",
        "degraded",
        "overdue",
        "unpaid",
        "expiring",
    ),
    "failure": (
        "failed",
        "failure",
        "error",
        "errored",
        "rejected",
        "declined",
        "blocked",
        "lost",
        "expired",
    ),
    "waiting": (
        "pending",
        "waiting",
        "queued",
        "running",
        "in progress",
        "processing",
        "scheduled",
        "draft",
        "new",
        "open",
    ),
}

_WORD_TONES = {word: tone for tone, words in _DEFAULT_WORDS.items() for word in words}


def _display(value: Any) -> str:
    """The text a table cell shows for ``value`` (booleans as the browser prints them)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _normalize(value: Any) -> str:
    return " ".join(_display(value).replace("_", " ").replace("-", " ").lower().split())


def default_tone(value: Any) -> str:
    """The tone a status value gets without configuration."""
    if value is None:
        return DEFAULT_TONE
    return _WORD_TONES.get(_normalize(value), DEFAULT_TONE)


def resolve_status_tones(values: Iterable[Any], overrides: Any = None) -> dict[str, str]:
    """Map every distinct value, as the table shows it, to a tone.

    ``overrides`` is the node's ``statusTones`` map (value -> tone). Its keys match
    without regard to case, ``_`` or ``-``; an entry with an unknown tone is ignored.
    """
    custom: dict[str, str] = {}
    if isinstance(overrides, dict):
        for key, tone in overrides.items():
            if tone in STATUS_TONES:
                custom[_normalize(key)] = tone

    tones: dict[str, str] = {}
    for value in values:
        if value is None:
            continue
        text = _display(value)
        if text not in tones:
            tones[text] = custom.get(_normalize(text)) or default_tone(value)
    return tones
