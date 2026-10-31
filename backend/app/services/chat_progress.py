"""Short progress lines for a chat turn, shown while a step takes time.

Two moments in a turn used to show nothing: the model writing a tool call (a whole workflow for
`save_workflow`), and a tool running a workflow. While the model writes, the line names the
workflow and the nodes written so far. While a workflow runs, it names the running node, as the
MCP progress notifications do (`running_node_message`).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

TOOL_PROGRESS_POLL_SECONDS = 0.5
_SHOWN_NODE_LABELS = 3
_NAME_PATTERN = re.compile(r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"')

# What the model is about to do, while it writes a tool call whose arguments take a while.
_DRAFTING_MESSAGES = {
    "apply_skill": "Writing the skill",
    "create_workflow": "Planning a new workflow",
    "edit_workflow": "Planning the workflow changes",
    "run_workflow_test": "Preparing a test run",
    "execute_workflow": "Preparing the run",
    "save_prompt_suite": "Writing the eval suite",
    "save_agent_suite": "Writing the eval suite",
    "finish": "Wrapping up",
}


def _read_string(text: str, start: int) -> tuple[str | None, int]:
    """The JSON string that opens at `start`, and the index after it; None while unfinished."""
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            try:
                return json.loads(text[start : index + 1]), index + 1
            except ValueError:
                return None, index + 1
        index += 1
    return None, len(text)


def _workflow_name(text: str) -> str | None:
    """The workflow's name, written before its nodes, once the whole string has arrived."""
    match = _NAME_PATTERN.search(text)
    if match is None:
        return None
    try:
        return json.loads(f'"{match.group(1)}"') or None
    except ValueError:
        return None


def _node_labels(text: str) -> list[str | None]:
    """One entry per node object in the `nodes` array written so far, with its label if known."""
    marker = text.find('"nodes"')
    if marker < 0:
        return []
    start = text.find("[", marker)
    if start < 0:
        return []
    labels: list[str | None] = []
    depth = 0
    index = start + 1
    awaiting_label = False
    while index < len(text):
        char = text[index]
        if char == '"':
            value, end = _read_string(text, index)
            if value is None:
                break
            after = text[end : end + 3].lstrip()
            if after.startswith(":"):
                # A node's label sits in its `data` object, one level below the node.
                awaiting_label = value == "label" and depth == 2 and labels[-1:] == [None]
            elif awaiting_label:
                labels[-1] = value
                awaiting_label = False
            index = end
            continue
        if char in "{[":
            if char == "{" and depth == 0:
                labels.append(None)
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth < 0:
                break
        index += 1
    return labels


def workflow_draft_message(text: str) -> str:
    """`Writing "Lead intake" · 3 nodes (start, Agent, result)` for a workflow DSL being written."""
    nodes_at = text.find('"nodes"')
    name = _workflow_name(text[:nodes_at] if nodes_at >= 0 else text)
    subject = f'"{name}"' if name else "the workflow"
    labels = _node_labels(text)
    if not labels:
        return f"Writing {subject}"
    count = f"{len(labels)} node" + ("" if len(labels) == 1 else "s")
    named = [label for label in labels if label]
    if not named:
        return f"Writing {subject} · {count}"
    shown = ", ".join(named[-_SHOWN_NODE_LABELS:])
    if len(named) > _SHOWN_NODE_LABELS:
        shown = "…, " + shown
    return f"Writing {subject} · {count} ({shown})"


def tool_draft_message(name: str, arguments: str) -> str | None:
    """The progress line for a tool call the model is still writing, or None for quick ones."""
    if name == "save_workflow":
        return workflow_draft_message(arguments)
    return _DRAFTING_MESSAGES.get(name)


class ToolProgress:
    """What a running chat tool is doing now; the turn reads it while it waits for the tool."""

    def __init__(self) -> None:
        self.message: str | None = None
        # Asked on every poll when set, e.g. which node of a run is running.
        self.describe: Callable[[], str | None] | None = None

    def current(self) -> str | None:
        described = self.describe() if self.describe is not None else None
        return described or self.message


def tool_progress_event(call_id: str, message: str) -> str:
    return (
        "data: " + json.dumps({"type": "tool_progress", "id": call_id, "message": message}) + "\n\n"
    )


async def follow_tool(
    task: "asyncio.Future[Any]", call_id: str, progress: ToolProgress
) -> AsyncIterator[str]:
    """Wait for a tool task, yielding a `tool_progress` event whenever its line changes.

    The caller reads `task.result()` afterwards; a turn that stops here cancels the task.
    """
    shown: str | None = None
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=TOOL_PROGRESS_POLL_SECONDS)
            if task.done():
                break
            message = progress.current()
            if message and message != shown:
                shown = message
                yield tool_progress_event(call_id, message)
    finally:
        if not task.done():
            task.cancel()
