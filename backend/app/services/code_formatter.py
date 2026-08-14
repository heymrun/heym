"""Format Code node Python with Ruff, inside the same sandbox the node runs in.

Ruff parses and rewrites the source rather than executing it, so formatting is
not obviously dangerous on its own. It is still containerised for the same
reason the node is: the source is untrusted, and a host subprocess would
inherit the backend's whole environment — ``SECRET_KEY``, ``DATABASE_URL``,
provider keys. In the sandbox there is nothing to reach: no network, no Docker
socket, no backend secrets, a read-only root filesystem, and a non-root user.

Like the node itself, this fails closed when Docker is unavailable rather than
falling back to the host.
"""

from __future__ import annotations

import logging
import re
import textwrap
import uuid

from app.services.code_python_executor import (
    docker_available,
    hardening_args,
    resolve_sandbox_image,
    run_sandbox_container,
)

logger = logging.getLogger(__name__)

# Generous next to any hand-written node body, small enough that a pasted blob
# cannot make Ruff chew through a container.
MAX_SOURCE_BYTES = 200_000
_TIMEOUT_SECONDS = 20.0
_FORMAT_TMPFS = "/tmp:rw,nosuid,size=64m"
_STDIN_FILENAME = "code.py"

# The venv lives at a different path in each image (backend/Dockerfile -> /app,
# docker/release.Dockerfile -> /app/backend) and its bin directory is not on
# PATH, so probe both rather than adding an environment variable.
_RUFF_CANDIDATES = ("/app/.venv/bin/ruff", "/app/backend/.venv/bin/ruff")

# --isolated makes the result independent of any pyproject.toml that happens to
# be visible, so the same source always formats the same way.
_PROBE_SCRIPT = (
    "for p in " + " ".join(_RUFF_CANDIDATES) + "; do "
    'if [ -x "$p" ]; then '
    f'exec "$p" format --isolated --stdin-filename {_STDIN_FILENAME} -; '
    "fi; done; "
    'echo "ruff not found in the sandbox image" >&2; exit 127'
)


_TAB_WIDTH = 4


def _expand_leading_tabs(line: str) -> str:
    """Turn tabs in a line's indentation into spaces, leaving the body untouched.

    Expanding the whole line would rewrite tabs inside string literals, which
    silently changes what the code does.
    """
    stripped = line.lstrip("\t ")
    indent = line[: len(line) - len(stripped)]
    return indent.expandtabs(_TAB_WIDTH) + stripped


def _normalize_source(source: str) -> str:
    """Repair the indentation damage that pasting code usually causes.

    A block copied out of a document arrives uniformly indented, and mixing
    tabs with spaces is a parse error rather than a formatting problem. Both
    are mechanical to fix, so fix them instead of refusing to format. Nothing
    here changes well-formed code: ``dedent`` finds no common prefix when the
    first line already starts at column zero.
    """
    text = source.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_expand_leading_tabs(line) for line in text.split("\n"))
    text = text.strip("\n")
    if not text:
        return source
    text = textwrap.dedent(text)
    return text + "\n"


# How far an indent may sit from an established level and still count as a typo
# rather than a deliberate (if broken) structure.
_MAX_SNAP_SPACES = 3
_OPENERS = "([{"
_CLOSERS = ")]}"


def _scan_line(text: str, triple: str | None, depth: int) -> tuple[str | None, int]:
    """Track open triple-quoted strings and bracket depth across a line."""
    i = 0
    while i < len(text):
        if triple:
            if text.startswith(triple, i):
                triple, i = None, i + 3
                continue
            i += 1
            continue
        chunk = text[i : i + 3]
        if chunk in ('"""', "'''"):
            triple, i = chunk, i + 3
            continue
        char = text[i]
        if char == "#":
            break
        if char in ("'", '"'):
            quote, i = char, i + 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth = max(0, depth - 1)
        i += 1
    return triple, depth


def _repair_indentation(source: str) -> str | None:
    """Snap near-miss indents onto established levels.

    Returns ``None`` when nothing needed fixing, or when the indentation is too
    far off to guess at safely — a wrong guess would silently move a statement
    into a different block, which is worse than refusing. Continuation lines
    inside brackets and the bodies of triple-quoted strings are never touched,
    because Python lets those sit at any indent and rewriting them would change
    what the code means.
    """
    levels = [0]
    triple: str | None = None
    depth = 0
    out: list[str] = []
    changed = False

    for line in source.split("\n"):
        if triple is not None or depth > 0:
            out.append(line)
            triple, depth = _scan_line(line, triple, depth)
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue

        indent = len(line) - len(line.lstrip(" "))
        body = line[indent:]

        if indent > levels[-1]:
            levels.append(indent)
        elif indent in levels:
            while levels[-1] > indent:
                levels.pop()
        else:
            ranked = sorted(levels, key=lambda level: abs(level - indent))
            nearest = ranked[0]
            distance = abs(nearest - indent)
            tied = len(ranked) > 1 and abs(ranked[1] - indent) == distance
            # A tie means two blocks are equally plausible homes for the line.
            # Guessing there could silently move a statement, so refuse.
            if distance > _MAX_SNAP_SPACES or tied:
                return None
            while levels[-1] > nearest:
                levels.pop()
            indent = nearest
            changed = True

        out.append(" " * indent + body)
        triple, depth = _scan_line(body, triple, depth)

    return "\n".join(out) if changed else None


def _parse_error_message(raw: str) -> str:
    """Turn Ruff's stderr into something worth showing above the editor."""
    first = next((line.strip() for line in raw.splitlines() if line.strip()), "")
    match = re.search(rf"{_STDIN_FILENAME}:(\d+):(\d+):\s*(.+)$", first)
    if match:
        line, column, reason = match.groups()
        return f"Line {line}, column {column}: {reason.rstrip('.')}"
    if first:
        return first.removeprefix("error: ").strip()
    return "The code could not be parsed as Python."


def _build_format_command(image: str, name: str) -> list[str]:
    """Build the hardened, offline ``docker run`` invocation for Ruff."""
    cmd = hardening_args(name, "none", _FORMAT_TMPFS)
    cmd.extend(["--workdir", "/tmp", "--entrypoint", "sh", image, "-c", _PROBE_SCRIPT])
    return cmd


def _run_ruff(image: str, source: str) -> tuple[int, str, str]:
    """Run one throwaway Ruff container over ``source``."""
    name = f"heym-code-format-{uuid.uuid4().hex}"
    try:
        return run_sandbox_container(
            _build_format_command(image, name), source, _TIMEOUT_SECONDS, name, "formatting"
        )
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc


def format_python(source: str) -> str:
    """Return ``source`` formatted by Ruff, preserving comments.

    Raises:
        ValueError: The source is too large, or Ruff rejected it as invalid.
        RuntimeError: The sandbox is unavailable or did not finish in time.
    """
    if not source.strip():
        return source
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"Code is too large to format (limit {MAX_SOURCE_BYTES:,} bytes).")
    source = _normalize_source(source)

    if not docker_available():
        raise RuntimeError(
            "Formatting requires Docker: the formatter runs in the same isolated sandbox as "
            "the Code node and is never run on the backend host."
        )
    image = resolve_sandbox_image()
    if image is None:
        raise RuntimeError(
            "The Code node sandbox image could not be resolved. Set HEYM_PYTHON_TOOL_IMAGE "
            "to the backend image."
        )

    returncode, stdout, stderr = _run_ruff(image, source)
    if returncode == 0:
        return stdout

    # An indentation typo is mechanical to fix, so try once more with the
    # near-miss lines snapped onto the levels around them. Ruff validates the
    # attempt: a repair that does not parse is discarded for the real error.
    repaired = _repair_indentation(source)
    if repaired is not None:
        retry_code, retry_stdout, _ = _run_ruff(image, repaired)
        if retry_code == 0:
            return retry_stdout

    if returncode == 127:
        raise RuntimeError("The ruff formatter is not installed in the sandbox image.")
    raise ValueError(_parse_error_message(stderr or stdout or ""))
