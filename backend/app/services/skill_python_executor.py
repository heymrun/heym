"""
Execute skill Python scripts with uv, preserving directory structure.
"""

import base64
import json
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
_DRIVE_FILES_DIR = "_drive_files"
_DRIVE_MANIFEST = "_drive_files_manifest.json"
_DRIVE_HELPER = "heym_drive.py"


_DRIVE_HELPER_SOURCE = r'''"""Read Heym Drive files exposed to this skill run."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_MANIFEST_PATH = _ROOT / "_drive_files_manifest.json"


def _load_manifest() -> list[dict[str, Any]]:
    if not _MANIFEST_PATH.exists():
        raise RuntimeError("Drive files are not enabled for this skill.")
    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    rows = [row for row in data if isinstance(row, dict)]
    return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)


def _public_metadata(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "filename": row.get("filename"),
        "mime_type": row.get("mime_type"),
        "size_bytes": row.get("size_bytes"),
        "workflow_id": row.get("workflow_id"),
        "source_node_label": row.get("source_node_label"),
        "created_at": row.get("created_at"),
        "path": row.get("path"),
    }


def list_drive_files(filename: str | None = None) -> list[dict[str, Any]]:
    """Return accessible Drive file metadata, optionally filtered by exact filename."""
    rows = _load_manifest()
    if filename is not None:
        rows = [row for row in rows if row.get("filename") == filename]
    return [_public_metadata(row) for row in rows]


def get_drive_file(
    file_id: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Return metadata for an accessible Drive file by id or newest exact filename match."""
    if not file_id and not filename:
        raise ValueError("Provide file_id or filename.")
    all_rows = _load_manifest()
    rows = all_rows
    if file_id:
        rows = [row for row in rows if str(row.get("id") or "") == str(file_id)]
        if not rows and not filename:
            rows = [row for row in all_rows if row.get("filename") == file_id]
    if filename:
        rows = [row for row in rows if row.get("filename") == filename]
    if not rows:
        raise FileNotFoundError("Drive file not found or not accessible.")
    return _public_metadata(rows[0])


def get_drive_file_path(
    file_id: str | None = None,
    filename: str | None = None,
) -> str:
    """Return the local copied path for a Drive file."""
    metadata = get_drive_file(file_id=file_id, filename=filename)
    path = metadata.get("path")
    if not isinstance(path, str) or not path:
        raise FileNotFoundError("Drive file copy is unavailable.")
    return path


def read_drive_file(
    file_id: str | None = None,
    filename: str | None = None,
    encoding: str | None = None,
) -> bytes | str:
    """Read a Drive file. With no encoding, returns bytes; use encoding='base64' for base64."""
    data = Path(get_drive_file_path(file_id=file_id, filename=filename)).read_bytes()
    if encoding is None or encoding in {"bytes", "binary"}:
        return data
    if encoding == "base64":
        return base64.b64encode(data).decode("ascii")
    return data.decode(encoding)


def read_drive_text(
    file_id: str | None = None,
    filename: str | None = None,
    encoding: str = "utf-8",
) -> str:
    """Read a Drive file as text."""
    value = read_drive_file(file_id=file_id, filename=filename, encoding=encoding)
    if not isinstance(value, str):
        return value.decode(encoding)
    return value


def read_drive_base64(file_id: str | None = None, filename: str | None = None) -> str:
    """Read a Drive file and return base64 text."""
    value = read_drive_file(file_id=file_id, filename=filename, encoding="base64")
    if not isinstance(value, str):
        raise TypeError("Expected base64 text.")
    return value
'''


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


def _drive_created_at_sort_key(file_data: dict[str, Any]) -> str:
    """Return a stable descending sort key for Drive file creation time."""

    created_at = file_data.get("created_at")
    if isinstance(created_at, datetime):
        return created_at.astimezone(timezone.utc).isoformat()
    return str(created_at or "")


def _safe_drive_copy_filename(filename: object) -> str:
    """Return a path-safe filename for a Drive file copy."""

    raw = str(filename or "drive-file").strip() or "drive-file"
    sanitized = raw.replace("\\", "_").replace("/", "_").replace("\x00", "")
    return sanitized or "drive-file"


def _prepare_drive_files(root: Path, drive_files: list[dict[str, Any]]) -> None:
    """Copy accessible Drive files into the skill workspace and write the helper module."""

    drive_root = root / _DRIVE_FILES_DIR
    drive_root.mkdir(exist_ok=True)
    manifest: list[dict[str, Any]] = []

    sorted_files = sorted(drive_files, key=_drive_created_at_sort_key, reverse=True)
    for file_data in sorted_files:
        file_id = str(file_data.get("id") or "").strip()
        source_path_value = file_data.get("source_path")
        if not file_id or not source_path_value:
            continue

        source_path = Path(str(source_path_value))
        if not source_path.exists() or not source_path.is_file():
            continue

        filename = str(file_data.get("filename") or "drive-file")
        copy_path = drive_root / file_id / _safe_drive_copy_filename(filename)
        copy_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, copy_path)

        created_at = file_data.get("created_at")
        if isinstance(created_at, datetime):
            created_at_value: str | None = created_at.astimezone(timezone.utc).isoformat()
        elif created_at is None:
            created_at_value = None
        else:
            created_at_value = str(created_at)

        workflow_id = file_data.get("workflow_id")
        manifest.append(
            {
                "id": file_id,
                "filename": filename,
                "mime_type": str(file_data.get("mime_type") or "application/octet-stream"),
                "size_bytes": int(file_data.get("size_bytes") or copy_path.stat().st_size),
                "workflow_id": str(workflow_id) if workflow_id else None,
                "source_node_label": file_data.get("source_node_label"),
                "created_at": created_at_value,
                "path": str(copy_path),
            }
        )

    (root / _DRIVE_MANIFEST).write_text(json.dumps(manifest, default=str), encoding="utf-8")
    (root / _DRIVE_HELPER).write_text(_DRIVE_HELPER_SOURCE, encoding="utf-8")


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
    drive_files: list[dict[str, Any]] | None = None,
) -> SkillExecutionResult:
    """
    Execute a skill's Python script using uv.

    Args:
        skill_files: List of {"path": str, "content": str}
        arguments: Dict of arguments to pass to the script (as JSON on stdin)
        timeout_seconds: Max execution time
        drive_files: Optional accessible Drive file metadata with source_path values

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
        if drive_files is not None:
            _prepare_drive_files(root, drive_files)

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
