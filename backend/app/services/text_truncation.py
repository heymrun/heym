"""Fit long text into a character budget by keeping both of its ends.

The start usually says what the text is and the end often says what to do with it, so
both survive; about two thirds of the room goes to the start. The context compressor,
the model router and persisted tool payloads all cut text this way.
"""

import re
from collections.abc import Callable

TRUNCATED_MARKER = "…[truncated]…"

Marker = str | Callable[[int], str]

_HEAD_SHARE = 0.65
_COUNTED_MARKER = re.compile(r" …\[(\d+) characters truncated\]… ")


def omitted_characters_marker(omitted: int) -> str:
    """Marker that names how many characters the cut left out."""
    return f" …[{omitted} characters truncated]… "


def keep_head_and_tail(text: str, max_chars: int, marker: Marker) -> str:
    """Fit text within max_chars by keeping its start and its end around a marker.

    ``marker`` is fixed text, or a function of how many characters were left out.
    """
    if len(text) <= max_chars:
        return text

    def left_out_earlier(start: int, end: int) -> int:
        # Cutting a text that was cut before: what its markers counted is gone as well.
        return sum(
            int(found.group(1)) - len(found.group(0))
            for found in _COUNTED_MARKER.finditer(text, start, end)
        )

    return _cut(text, text, len(text), max_chars, marker, left_out_earlier)


def keep_ends(head: str, tail: str, total_chars: int, max_chars: int, marker: Marker) -> str:
    """Cut like keep_head_and_tail, for a text known only by a prefix, a suffix and a length.

    Nothing but ``head`` and ``tail`` can reach the result, so a caller never has to read,
    or scan, the middle of a very long text.
    """
    return _cut(head, tail, total_chars, max_chars, marker, None)


def _cut(
    head: str,
    tail: str,
    total_chars: int,
    max_chars: int,
    marker: Marker,
    left_out_earlier: Callable[[int, int], int] | None,
) -> str:
    def label_for(omitted: int) -> str:
        return marker(omitted) if callable(marker) else marker

    label = label_for(max(0, total_chars - max_chars))
    while True:
        available = max_chars - len(label)
        if available < 2:
            # No room for both ends and the marker; a plain cut is all that fits.
            return head[: max(0, max_chars)]
        head_chars = max(1, int(available * _HEAD_SHARE))
        kept_head = head[:head_chars].rstrip()
        kept_tail = tail[-max(1, available - head_chars) :].lstrip()
        omitted = total_chars - len(kept_head) - len(kept_tail)
        if callable(marker) and left_out_earlier is not None:
            omitted += left_out_earlier(len(kept_head), total_chars - len(kept_tail))
        final = label_for(omitted)
        # A count that gained a digit needs one more character of room.
        if len(final) <= len(label):
            return kept_head + final + kept_tail
        label = final
