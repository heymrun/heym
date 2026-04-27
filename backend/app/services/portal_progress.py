"""Helpers for compact portal execution progress summaries."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RepeatSpan:
    """A contiguous repeated block within a node label sequence."""

    block_length: int
    repeats: int


def _blocks_match(node_labels: list[str], start: int, block_length: int, repeat_index: int) -> bool:
    left_start = start
    right_start = start + (repeat_index * block_length)

    for offset in range(block_length):
        if node_labels[left_start + offset] != node_labels[right_start + offset]:
            return False
    return True


def _find_repeat_span(node_labels: list[str], start: int) -> RepeatSpan | None:
    remaining = len(node_labels) - start
    max_block_length = remaining // 2
    best_span: RepeatSpan | None = None
    best_savings = 0

    for block_length in range(1, max_block_length + 1):
        repeats = 1
        while start + ((repeats + 1) * block_length) <= len(node_labels) and _blocks_match(
            node_labels, start, block_length, repeats
        ):
            repeats += 1

        if repeats <= 1:
            continue

        savings = (block_length * repeats) - block_length
        if savings > best_savings or (
            savings == best_savings
            and best_span is not None
            and block_length > best_span.block_length
        ):
            best_span = RepeatSpan(block_length=block_length, repeats=repeats)
            best_savings = savings

    return best_span


def compact_portal_progress_path(node_labels: list[str]) -> list[str]:
    """Collapse contiguous loop cycles into `Node(count)` progress labels."""

    compact_labels: list[str] = []
    index = 0

    while index < len(node_labels):
        repeat_span = _find_repeat_span(node_labels, index)
        if repeat_span is None:
            compact_labels.append(node_labels[index])
            index += 1
            continue

        for offset in range(repeat_span.block_length):
            compact_labels.append(f"{node_labels[index + offset]}({repeat_span.repeats})")
        index += repeat_span.block_length * repeat_span.repeats

    return compact_labels


@dataclass
class PortalProgressTracker:
    """Track streamed portal node starts and expose a compact progress path."""

    node_labels: list[str] = field(default_factory=list)

    def observe_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Attach a compact `progress_path` to portal `node_start` events."""

        if event.get("type") != "node_start":
            return event

        node_label = event.get("node_label")
        if not isinstance(node_label, str) or not node_label:
            return event

        self.node_labels.append(node_label)
        enriched_event = dict(event)
        enriched_event["progress_path"] = compact_portal_progress_path(self.node_labels)
        return enriched_event
