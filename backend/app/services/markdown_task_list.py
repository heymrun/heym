"""GFM task list helpers for dashboard markdown text widgets."""

import re

TASK_ITEM_RE = re.compile(r"^(\s*)([-*+])\s+\[([ xX])\]\s+(.*)$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def code_fence_lines(lines: list[str]) -> set[int]:
    """Indexes of the lines that belong to fenced code blocks (fences included).

    A ``- [ ] item`` line in a code sample is text, not a checkbox. Fences follow
    CommonMark: three or more backticks or tildes, closed by a fence of the same
    character that is at least as long and has nothing after it.
    """
    inside: set[int] = set()
    opening: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if opening is None:
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                opening = (match.group(1)[0], len(match.group(1)))
                inside.add(index)
            continue
        inside.add(index)
        fence = match.group(1) if match else ""
        if (
            fence
            and fence[0] == opening[0]
            and len(fence) >= opening[1]
            and not match.group(2).strip()
        ):
            opening = None
    return inside


def _task_match(lines: list[str], line_index: int) -> re.Match[str]:
    if line_index < 0 or line_index >= len(lines):
        raise ValueError(f"Invalid line_index: {line_index}")
    match = TASK_ITEM_RE.match(lines[line_index])
    if match is None or line_index in code_fence_lines(lines):
        raise ValueError(f"Line {line_index} is not a task list item")
    return match


def has_task_items(markdown: str) -> bool:
    """Return True when markdown contains at least one GFM task list line outside code blocks."""
    lines = markdown.split("\n")
    code = code_fence_lines(lines)
    return any(TASK_ITEM_RE.match(line) for i, line in enumerate(lines) if i not in code)


def toggle_task_item(markdown: str, line_index: int) -> str:
    """Flip `[ ]` ↔ `[x]` on the task list line at ``line_index``.

    Raises:
        ValueError: When the line index is out of range or not a task item.
    """
    lines = markdown.split("\n")
    match = _task_match(lines, line_index)
    indent, bullet, check, rest = match.groups()
    new_check = " " if check.lower() == "x" else "x"
    lines[line_index] = f"{indent}{bullet} [{new_check}] {rest}"
    return "\n".join(lines)


def update_task_item(markdown: str, line_index: int, text: str) -> str:
    """Replace the label text on a task list line, preserving checked state.

    Raises:
        ValueError: When the line index is out of range or not a task item.
    """
    lines = markdown.split("\n")
    match = _task_match(lines, line_index)
    indent, bullet, check, _rest = match.groups()
    lines[line_index] = f"{indent}{bullet} [{check}] {text}"
    return "\n".join(lines)


def remove_task_item(markdown: str, line_index: int) -> str:
    """Remove a task list line from markdown.

    Raises:
        ValueError: When the line index is out of range or not a task item.
    """
    lines = markdown.split("\n")
    _task_match(lines, line_index)
    del lines[line_index]
    if (
        line_index < len(lines)
        and lines[line_index].strip() == ""
        and line_index > 0
        and lines[line_index - 1].strip() == ""
    ):
        del lines[line_index]
    return "\n".join(lines)


def update_or_remove_task_item(markdown: str, line_index: int, text: str) -> str:
    """Update task item label text, or remove the line when text is blank."""
    if text.strip() == "":
        return remove_task_item(markdown, line_index)
    return update_task_item(markdown, line_index, text)
