"""Format Code node Python with Ruff.

Ruff only parses and rewrites the source — it never executes it — so this runs
as a plain subprocess rather than in the Code node's container sandbox. The
input is still untrusted text, so it is size-capped and time-capped to keep a
pathological file from tying up a worker.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Generous next to any hand-written node body, small enough that a pasted blob
# cannot make Ruff chew through a worker.
MAX_SOURCE_BYTES = 200_000
_TIMEOUT_SECONDS = 10.0
_STDIN_FILENAME = "code.py"


def _ruff_command() -> list[str]:
    """Locate Ruff next to the running interpreter, falling back to PATH."""
    candidate = Path(sys.executable).with_name("ruff")
    executable = str(candidate) if candidate.exists() else "ruff"
    return [executable, "format", "--stdin-filename", _STDIN_FILENAME, "-"]


def format_python(source: str) -> str:
    """Return ``source`` formatted by Ruff, preserving comments.

    Raises:
        ValueError: The source is too large, or Ruff rejected it as invalid.
        RuntimeError: Ruff is unavailable or did not finish in time.
    """
    if not source.strip():
        return source
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"Code is too large to format (limit {MAX_SOURCE_BYTES:,} bytes).")

    try:
        result = subprocess.run(
            _ruff_command(),
            input=source,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("The ruff formatter is not installed on the backend.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Formatting timed out.") from exc
    except OSError as exc:
        raise RuntimeError(f"The ruff formatter could not be started: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        # Ruff prefixes parse failures with the stdin filename; drop that noise.
        detail = detail.replace(f"{_STDIN_FILENAME}:", "line ").strip()
        raise ValueError(detail or "The code could not be parsed as Python.")

    return result.stdout
