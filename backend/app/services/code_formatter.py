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


def _build_format_command(image: str, name: str) -> list[str]:
    """Build the hardened, offline ``docker run`` invocation for Ruff."""
    cmd = hardening_args(name, "none", _FORMAT_TMPFS)
    cmd.extend(["--workdir", "/tmp", "--entrypoint", "sh", image, "-c", _PROBE_SCRIPT])
    return cmd


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

    name = f"heym-code-format-{uuid.uuid4().hex}"
    try:
        returncode, stdout, stderr = run_sandbox_container(
            _build_format_command(image, name), source, _TIMEOUT_SECONDS, name, "formatting"
        )
    except TimeoutError as exc:
        raise RuntimeError(str(exc)) from exc

    if returncode == 127:
        raise RuntimeError("The ruff formatter is not installed in the sandbox image.")
    if returncode != 0:
        detail = (stderr or stdout or "").strip()
        detail = detail.replace(f"{_STDIN_FILENAME}:", "line ").strip()
        raise ValueError(detail or "The code could not be parsed as Python.")

    return stdout
