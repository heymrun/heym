"""Run one file-sandbox call in a fresh, hardened, network-less container.

The container gets the Code node's hardening (non-root, no capabilities,
read-only root, env allowlist, no Docker socket), the file sandbox's larger
limits, ``/input`` read-only and ``/work`` read-write. There is no subprocess
fallback: without Docker the call fails closed.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.code_python_executor import (
    _DOCKER_START_FAILURE_CODES,
    docker_available,
    hardening_args,
    resolve_mount,
    resolve_sandbox_image,
    run_sandbox_container,
)
from app.services.file_sandbox.limits import (
    CALL_TIMEOUT_SECONDS,
    CPU_LIMIT,
    MAX_CONCURRENT_CONTAINERS,
    MEMORY_LIMIT,
    TMPFS,
)
from app.services.file_sandbox.workspace import INPUT_MOUNT, WORK_MOUNT, FileWorkspace

logger = logging.getLogger(__name__)

_BOOTSTRAP = (
    "import sys,json;"
    "p=json.loads(sys.stdin.read());"
    "g={'__name__':'__heym_file_runner__'};"
    "exec(compile(p['runner'],'file_runner.py','exec'),g);"
    "g['run'](p)"
)
_OOM_EXIT_CODE = 137
_HERE = Path(__file__).parent

_containers = threading.BoundedSemaphore(MAX_CONCURRENT_CONTAINERS)


@dataclass
class SandboxOutcome:
    """The envelope of one call."""

    success: bool
    result: Any = None
    stdout: str = ""
    error: str | None = None
    stdout_dropped_chars: int = 0
    logs: str = ""


def _source(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def module_sources() -> dict[str, str]:
    """Modules registered inside the sandbox before the call runs.

    ``heym_ocr`` is the Converter node's OCR (``ocr_service.py``, stdlib only), so a
    scanned page reads the same in Chat, an agent, a Code node and the Converter.
    """
    return {
        "heym_files": _source("heym_files.py"),
        "heym_inspector": _source("inspector.py"),
        "heym_ocr": (_HERE.parent / "ocr_service.py").read_text(encoding="utf-8"),
    }


def build_payload(mode: str, **fields: Any) -> dict[str, Any]:
    """The stdin payload: runner source, sandbox modules, and the call itself."""
    return {"runner": _source("runner.py"), "modules": module_sources(), "mode": mode, **fields}


def build_command(image: str, name: str, workspace: FileWorkspace) -> list[str]:
    """The ``docker run`` command for one call."""
    cmd = hardening_args(name, "none", TMPFS, memory=MEMORY_LIMIT, cpus=CPU_LIMIT)
    cmd.extend(resolve_mount(workspace.in_dir, INPUT_MOUNT, readonly=True))
    cmd.extend(resolve_mount(workspace.work_dir, WORK_MOUNT, readonly=False))
    cmd.extend(["--workdir", WORK_MOUNT, "--entrypoint", "python", image, "-c", _BOOTSTRAP])
    return cmd


def run_in_sandbox(workspace: FileWorkspace, payload: dict[str, Any]) -> SandboxOutcome:
    """Run one call and parse its envelope.

    Raises:
        RuntimeError: no Docker, no image, the container never started, or it died
            without an envelope (out of memory included).
        TimeoutError: the call ran past its limit.
    """
    if not docker_available():
        raise RuntimeError(
            "File analysis needs Docker to open files in an isolated sandbox, and no "
            "working Docker daemon is reachable. Files are never opened in the backend."
        )
    image = resolve_sandbox_image()
    if image is None:
        raise RuntimeError(
            "The file sandbox image could not be resolved. Set HEYM_PYTHON_TOOL_IMAGE to "
            "the backend image."
        )
    name = f"heym-files-{uuid.uuid4().hex}"
    cmd = build_command(image, name, workspace)
    with _containers:
        try:
            returncode, stdout, stderr = run_sandbox_container(
                cmd, json.dumps(payload, default=str), CALL_TIMEOUT_SECONDS, name, "file call"
            )
        except TimeoutError:
            raise TimeoutError(
                f"The sandbox call ran past {CALL_TIMEOUT_SECONDS:.0f} seconds. Read less at "
                "once (nrows, a page range, chunks) and save intermediate results under /work."
            ) from None
    if returncode in _DOCKER_START_FAILURE_CODES:
        raise RuntimeError(
            f"The file sandbox failed to start (docker exit {returncode}): {stderr.strip()[:500]}"
        )
    return parse_envelope(returncode, stdout, stderr)


def parse_envelope(returncode: int, stdout: str, stderr: str) -> SandboxOutcome:
    """Turn the container's stdout into an outcome; stderr is kept as logs."""
    logs = stderr.strip()[-4000:]
    try:
        envelope = json.loads(stdout.strip())
    except json.JSONDecodeError:
        envelope = None
    if not isinstance(envelope, dict):
        if returncode == _OOM_EXIT_CODE:
            raise RuntimeError(
                "The sandbox ran out of memory (2 GB). Read the file in chunks, select fewer "
                "columns, or use read_only / nrows options."
            )
        raise RuntimeError(f"The sandbox returned no result (exit {returncode}). {logs[-500:]}")
    return SandboxOutcome(
        success=bool(envelope.get("success")),
        result=envelope.get("result"),
        stdout=str(envelope.get("stdout") or envelope.get("logs") or ""),
        error=envelope.get("error"),
        stdout_dropped_chars=int(envelope.get("stdout_dropped_chars") or 0),
        logs=logs,
    )
