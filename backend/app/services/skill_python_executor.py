"""
Execute skill Python scripts with uv, preserving directory structure.
"""

import base64
import json
import logging
import mimetypes
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Environment variables that must NOT be inherited by skill subprocesses.
# These contain application secrets that user-supplied skills must never see.
_SECRET_ENV_KEYS: frozenset[str] = frozenset(  # pragma: allowlist secret
    {
        "DATABASE_URL",
        "SECRET_KEY",
        "ENCRYPTION_KEY",
        "POSTGRES_PASSWORD",  # pragma: allowlist secret
        "POSTGRES_USER",  # pragma: allowlist secret
        "RABBITMQ_URL",
        "QDRANT_API_KEY",
    }
)

_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024  # 512 MB virtual memory cap
_OUTPUT_FILES_DIR = "_output_files"
_HITL_SENTINEL = "_hitl_request.json"


@dataclass
class SkillExecutionResult:
    """Rich result returned by execute_skill_python."""

    output: object = None
    generated_files: list[dict[str, Any]] = field(default_factory=list)
    hitl_request: dict[str, Any] | None = None


def _safe_env() -> dict[str, str]:
    """Return the current environment with all secret keys removed."""
    return {k: v for k, v in os.environ.items() if k not in _SECRET_ENV_KEYS}


ENTRY_POINT_PRIORITY = ("main.py", "run.py")


def _find_entry_point(files: list[dict[str, Any]]) -> str | None:
    """Return the best entry point path from skill files, or None if no .py files."""
    py_files = [f["path"] for f in files if f.get("path", "").endswith(".py")]
    if not py_files:
        return None
    for preferred in ENTRY_POINT_PRIORITY:
        for p in py_files:
            if p.endswith("/" + preferred) or p == preferred:
                return p
    return py_files[0]


def _collect_output_files(output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Scan _output_files/ for generated files and optional HITL sentinel.

    Returns (generated_files, hitl_request).
    """
    if not output_dir.exists():
        return [], None

    hitl_request: dict[str, Any] | None = None
    sentinel_path = output_dir / _HITL_SENTINEL
    if sentinel_path.exists():
        try:
            hitl_request = json.loads(sentinel_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse HITL sentinel file")

    if hitl_request is not None:
        return [], hitl_request

    generated_files: list[dict[str, Any]] = []
    for file_path in output_dir.iterdir():
        if file_path.name.startswith("_") or file_path.is_dir():
            continue
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        generated_files.append(
            {
                "filename": file_path.name,
                "file_bytes": file_path.read_bytes(),
                "mime_type": mime_type,
            }
        )

    return generated_files, None


def _write_skill_file(root: Path, file_data: dict[str, Any]) -> None:
    """Write a skill file to disk, decoding base64 payloads for binary assets."""
    path = root / file_data["path"]
    path.parent.mkdir(parents=True, exist_ok=True)

    encoding = str(file_data.get("encoding") or "text")
    content = file_data.get("content", "")

    if encoding == "base64":
        try:
            path.write_bytes(base64.b64decode(str(content)))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid base64 content for skill file: {file_data['path']}") from exc
        return

    path.write_text(str(content), encoding="utf-8")


def _serialize_skill_stdin(arguments: dict[str, Any]) -> str:
    """Serialize skill tool arguments to the stdin format expected by skills.

    Skill tools are exposed to models as a single `input` string field. When that
    shape is used, the raw string should be piped to stdin instead of the wrapper
    object `{"input": "..."}`. This preserves compatibility with existing skills
    that call `json.load(sys.stdin)` directly on the real payload.
    """
    if set(arguments.keys()) == {"input"}:
        raw_input = arguments.get("input")
        if isinstance(raw_input, str):
            return raw_input
        return json.dumps(raw_input, default=str)
    return json.dumps(arguments, default=str)


def execute_skill_python(
    skill_files: list[dict[str, Any]],
    arguments: dict[str, Any],
    timeout_seconds: float = 30.0,
) -> SkillExecutionResult:
    """
    Execute a skill's Python script using uv.

    Args:
        skill_files: List of {"path": str, "content": str}
        arguments: Dict of arguments to pass to the script (as JSON on stdin)
        timeout_seconds: Max execution time

    Returns:
        SkillExecutionResult with output, any generated files, and optional HITL request.
    """
    entry_point = _find_entry_point(skill_files)
    if not entry_point:
        raise ValueError("No Python file found in skill")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        for f in skill_files:
            _write_skill_file(root, f)

        output_dir = root / _OUTPUT_FILES_DIR
        output_dir.mkdir(exist_ok=True)

        args_json = _serialize_skill_stdin(arguments)

        env = _safe_env()
        env["_OUTPUT_DIR"] = str(output_dir)

        def _apply_resource_limits() -> None:
            """Apply OS-level resource limits inside the child process."""
            try:
                import resource  # noqa: PLC0415 (Unix-only)

                resource.setrlimit(resource.RLIMIT_AS, (_MEMORY_LIMIT_BYTES, _MEMORY_LIMIT_BYTES))
            except Exception:
                pass  # Non-fatal: best-effort on platforms that support it

        try:
            result = subprocess.run(
                ["uv", "run", "python", entry_point],
                cwd=str(root),
                input=args_json,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
                preexec_fn=_apply_resource_limits,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(
                f"Skill execution timed out after {timeout_seconds} seconds"
            ) from None

        if result.stderr:
            logger.warning("Skill stderr: %s", result.stderr)

        stdout = result.stdout.strip()
        if not stdout:
            output: object = {"output": "", "stderr": result.stderr or ""}
        else:
            try:
                output = json.loads(stdout)
            except json.JSONDecodeError:
                output = {"output": stdout, "stderr": result.stderr or ""}

        generated_files, hitl_request = _collect_output_files(output_dir)

        return SkillExecutionResult(
            output=output,
            generated_files=generated_files,
            hitl_request=hitl_request,
        )
