"""
Execute skill Python scripts with the backend interpreter, preserving directory structure.

Skill Python code is **untrusted** (it can arrive verbatim inside a shared
workflow / ``everyone``-visibility template), so it is treated exactly like the
user-defined Python *tool* path: a sandbox backend is selected by the shared
``HEYM_PYTHON_TOOL_SANDBOX`` environment variable.

* ``docker`` / ``auto`` (default) - run the skill inside a throwaway, hardened
  **sibling** container: non-root, all Linux capabilities dropped,
  ``no-new-privileges``, read-only root filesystem, strict CPU / memory / PID
  limits, and crucially **no** Docker socket -- so skill code can never reach
  the host Docker daemon or the backend's secrets. Unlike the tool sandbox,
  skills keep network egress and a writable workspace (skills legitimately
  generate output files and read Heym Drive files). ``auto`` fails **closed**
  (raises) when Docker is unavailable instead of silently running untrusted
  code in the backend process.
* ``subprocess`` - run the skill in a local subprocess with an allowlisted
  environment and an RLIMIT memory cap. This is **NOT a security boundary**
  (the skill runs in the backend execution context); it exists only for
  trusted single-user / local development and must be selected explicitly.
  ``run.sh`` sets it for native dev.

The workspace is shared with the sibling container through the same named
Docker volume the Codex runner uses (``HEYM_CODEX_DOCKER_WORKSPACE_VOLUME`` /
the mount at ``HEYM_SKILL_WORKSPACE_DIR``), so no extra deployment wiring is
required for the Docker Compose or single-container image setups.
"""

import base64
import json
import logging
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Environment allowlist: only these operational (non-secret) variables are
# exposed to untrusted skill code. Everything else -- database URLs, the app
# SECRET_KEY / ENCRYPTION_KEY, provider API keys, OAuth client secrets, etc. --
# is dropped. An allowlist (vs. the previous 7-key denylist) fails safe: a new
# secret added to the backend environment is withheld by default rather than
# leaked until someone remembers to extend a denylist.
_ENV_ALLOWLIST_EXACT: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LANGUAGE",
        "TZ",
        "TERM",
        "TMPDIR",
        "PWD",
    }
)
# Whole prefixes that are safe to pass through: the Python/uv toolchain needs
# these, and the proxy / CA-bundle families must survive so skill network
# egress keeps working behind a corporate proxy.
_ENV_ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "PYTHON",
    "UV_",
    "XDG_",
    "LC_",
    "SSL_",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)

_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024  # 512 MB virtual memory cap
_OUTPUT_FILES_DIR = "_output_files"
_HITL_SENTINEL = "_hitl_request.json"
_DRIVE_FILES_DIR = "_drive_files"
_DRIVE_MANIFEST = "_drive_files_manifest.json"
_DRIVE_HELPER = "heym_drive.py"

# Mount point (inside the backend container) of the shared volume that skill
# workspaces live on. Every Docker deployment (compose + single-image) already
# mounts the Codex workspace volume here, so skills ride it with no extra wiring.
_DEFAULT_SKILL_VOLUME_MOUNT = "/app/data/codex-workspaces"
# Per-run skill workspaces are created under this subdirectory of the mount so
# they never collide with Codex's own run directories.
_SKILL_WORKSPACE_SUBDIR = "_skill-workspaces"

# Docker exit codes that mean the *container never started* (as opposed to the
# skill process itself exiting non-zero). These must fail closed so a sandbox
# that cannot launch is never mistaken for a completed skill run.
_DOCKER_START_FAILURE_CODES: frozenset[int] = frozenset({125, 126, 127})

_docker_available_cache: bool | None = None


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


def _env_is_allowed(key: str) -> bool:
    """True when an environment variable is safe to expose to untrusted skills."""
    if key in _ENV_ALLOWLIST_EXACT:
        return True
    return any(key.startswith(prefix) for prefix in _ENV_ALLOWLIST_PREFIXES)


def _safe_env() -> dict[str, str]:
    """Return only the allowlisted (non-secret) subset of the environment."""
    return {k: v for k, v in os.environ.items() if _env_is_allowed(k)}


# Variables forwarded into the sibling container. Deliberately narrower than the
# subprocess allowlist: host-specific values (PATH, HOME, PWD, TMPDIR, UV_*) must
# NOT override the container's own correct values, but proxy / CA / locale
# settings must survive so skill network egress keeps working.
_DOCKER_ENV_FORWARD_PREFIXES: tuple[str, ...] = (
    "LANG",
    "LANGUAGE",
    "TZ",
    "LC_",
    "SSL_",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)


def _docker_forward_env() -> dict[str, str]:
    """Environment to forward as ``--env`` into the sibling container (non-secret, portable)."""
    return {
        k: v
        for k, v in os.environ.items()
        if any(k.startswith(prefix) for prefix in _DOCKER_ENV_FORWARD_PREFIXES)
    }


def _sandbox_mode() -> str:
    """Select the skill sandbox backend, sharing the Python-tool sandbox switch."""
    raw = os.environ.get("HEYM_PYTHON_TOOL_SANDBOX", "auto").strip().lower()
    if raw not in ("auto", "docker", "subprocess"):
        logger.warning("Unknown HEYM_PYTHON_TOOL_SANDBOX=%r; defaulting to 'auto'", raw)
        return "auto"
    return raw


def _docker_available() -> bool:
    """Return True when a working Docker daemon is reachable (cached)."""
    global _docker_available_cache
    if _docker_available_cache is not None:
        return _docker_available_cache
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _docker_available_cache = result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        _docker_available_cache = False
    return _docker_available_cache


def _resolve_image() -> str | None:
    """Resolve the image to run skills in.

    Prefers an explicit override, then the Codex runner image (both the single
    container release image and Docker Compose already set
    ``HEYM_CODEX_DOCKER_IMAGE`` to the backend image, and it always carries uv),
    and finally falls back to inspecting this container's own image. The env
    fallbacks matter because ``docker inspect <hostname>`` is not reliable in
    every deployment (e.g. a custom hostname, or an image referenced by digest).
    """
    import socket  # noqa: PLC0415 (only needed for the Docker sandbox path)

    override = (
        os.environ.get("HEYM_SKILL_IMAGE", "").strip()
        or os.environ.get("HEYM_PYTHON_TOOL_IMAGE", "").strip()
        or os.environ.get("HEYM_CODEX_DOCKER_IMAGE", "").strip()
    )
    if override:
        return override
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", socket.gethostname()],
            capture_output=True,
            text=True,
            timeout=5,
        )
        image = result.stdout.strip()
        if result.returncode == 0 and image:
            return image
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass
    return None


def _skill_interpreter() -> str:
    """Python interpreter used to run skills.

    Skills rely on the backend's installed packages (python-docx, pypdf, etc.),
    so they run with the backend's own venv interpreter rather than an isolated
    uv environment. In the Docker sandbox the sibling uses the backend image, so
    ``sys.executable`` (e.g. ``/app/backend/.venv/bin/python``) is a valid path
    there too. Override with ``HEYM_SKILL_PYTHON`` for a custom skill image.
    """
    return os.environ.get("HEYM_SKILL_PYTHON", "").strip() or sys.executable


def _skill_volume_mount_point() -> Path:
    """Absolute path where the shared workspace volume is mounted in the backend."""
    return Path(
        os.environ.get("HEYM_SKILL_WORKSPACE_MOUNT", "").strip()
        or os.environ.get("HEYM_CODEX_WORKSPACE_DIR", "").strip()
        or _DEFAULT_SKILL_VOLUME_MOUNT
    )


def _skill_workspace_root() -> Path:
    """Directory (inside the shared volume) that holds per-run skill workspaces."""
    override = os.environ.get("HEYM_SKILL_WORKSPACE_DIR", "").strip()
    if override:
        return Path(override)
    return _skill_volume_mount_point() / _SKILL_WORKSPACE_SUBDIR


def _resolve_workspace_mount(mount_point: Path, run_dir: Path) -> list[str]:
    """Return the ``docker run`` mount args that expose only ``run_dir`` to the sibling.

    A Docker named-volume mount places the volume **root** at the destination, so
    the backend and sibling must agree on where that root lives. We mount just
    this run's subtree at ``run_dir`` (``volume-subpath`` for a named volume, the
    resolved host path for a bind), which both fixes that path alignment and
    isolates each run: a skill never sees other runs' or Codex's workspace data.
    """
    try:
        rel = run_dir.relative_to(mount_point)
    except ValueError as exc:
        raise RuntimeError(
            f"Skill run dir {run_dir} is not under the workspace volume mount {mount_point}"
        ) from exc
    rel_str = rel.as_posix()

    volume = (
        os.environ.get("HEYM_SKILL_DOCKER_WORKSPACE_VOLUME", "").strip()
        or os.environ.get("HEYM_CODEX_DOCKER_WORKSPACE_VOLUME", "").strip()
    )
    if volume:
        return ["--mount", f"type=volume,src={volume},dst={run_dir},volume-subpath={rel_str}"]

    host_root = os.environ.get("HEYM_SKILL_HOST_WORKSPACE_DIR", "").strip()
    if not host_root:
        for mount in _current_container_mounts():
            if str(mount.get("Destination") or "") != str(mount_point):
                continue
            if mount.get("Type") == "volume" and mount.get("Name"):
                return [
                    "--mount",
                    f"type=volume,src={mount['Name']},dst={run_dir},volume-subpath={rel_str}",
                ]
            if mount.get("Type") == "bind" and mount.get("Source"):
                host_root = str(mount["Source"])
                break
    if not host_root:
        raise RuntimeError(
            "Skill Docker sandbox needs a shared workspace: set "
            "HEYM_SKILL_DOCKER_WORKSPACE_VOLUME (or HEYM_CODEX_DOCKER_WORKSPACE_VOLUME) to the "
            "named volume mounted at the workspace volume mount point, or run with "
            "HEYM_PYTHON_TOOL_SANDBOX=subprocess for trusted/dev use only."
        )
    host_run_dir = Path(host_root) / rel
    return ["--mount", f"type=bind,src={host_run_dir},dst={run_dir}"]


def _current_container_mounts() -> list[dict[str, Any]]:
    """Best-effort inspection of the backend container's own Docker mounts."""
    try:
        hostname = Path("/etc/hostname").read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not hostname:
        return []
    try:
        result = subprocess.run(
            ["docker", "inspect", hostname],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return []
    if result.returncode != 0:
        return []
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        mounts = parsed[0].get("Mounts")
        if isinstance(mounts, list):
            return [m for m in mounts if isinstance(m, dict)]
    return []


def _build_skill_docker_command(
    image: str,
    name: str,
    mount_point: Path,
    run_dir: Path,
    entry_point: str,
) -> list[str]:
    """Build a hardened, throwaway ``docker run`` invocation for a skill.

    Hardened like the Python-tool sandbox (non-root, cap-drop ALL,
    no-new-privileges, read-only root fs, resource limits, **no Docker
    socket**) but keeps a per-run writable workspace mount and network egress,
    which skills legitimately use.
    """
    memory = os.environ.get("HEYM_SKILL_MEMORY", "512m")
    home_dir = run_dir / ".home"
    cmd = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        # Egress preserved: skills call external APIs.
        "--network",
        os.environ.get("HEYM_SKILL_NETWORK", "bridge"),
        *_resolve_workspace_mount(mount_point, run_dir),
        "--workdir",
        str(run_dir),
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,size=64m",
        "--user",
        os.environ.get("HEYM_SKILL_USER", "65534:65534"),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        os.environ.get("HEYM_SKILL_PIDS", "256"),
        "--memory",
        memory,
        "--memory-swap",
        memory,
        "--cpus",
        os.environ.get("HEYM_SKILL_CPUS", "1"),
        "--env",
        f"HOME={home_dir}",
        "--env",
        f"_OUTPUT_DIR={run_dir / _OUTPUT_FILES_DIR}",
    ]
    for key, value in _docker_forward_env().items():
        # HOME is set explicitly above to point inside the writable workspace;
        # never let the backend's value (a read-only path) override it.
        if key == "HOME":
            continue
        cmd.extend(["--env", f"{key}={value}"])
    # Override the backend image ENTRYPOINT (uvicorn) and run the skill directly
    # with the backend's own venv interpreter so backend packages (python-docx,
    # pypdf, ...) are available. Running the interpreter directly also avoids uv
    # discovering / repairing the backend project on the read-only filesystem.
    cmd.extend(["--entrypoint", _skill_interpreter(), image, entry_point])
    return cmd


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

    output_dir_resolved = output_dir.resolve()

    hitl_request: dict[str, Any] | None = None
    sentinel_path = output_dir / _HITL_SENTINEL
    # The sentinel is read by the backend (outside the sandbox), so apply the
    # same symlink hardening as generated files: a skill must not be able to
    # point _hitl_request.json at a host file and have the backend read it.
    if (
        sentinel_path.exists()
        and not sentinel_path.is_symlink()
        and sentinel_path.resolve().parent == output_dir_resolved
    ):
        try:
            hitl_request = json.loads(sentinel_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse HITL sentinel file")
    elif sentinel_path.is_symlink():
        logger.warning("Skipping symlinked HITL sentinel in skill output")

    if hitl_request is not None:
        return [], hitl_request

    generated_files: list[dict[str, Any]] = []
    for file_path in output_dir.iterdir():
        if file_path.name.startswith("_") or file_path.is_dir():
            continue
        # A skill can drop a symlink in _output_files pointing at an arbitrary
        # host file (e.g. /etc/passwd or the backend's .env). The backend, not
        # the sandbox, collects these files, so following the link would
        # exfiltrate host data as a "generated file". Skip symlinks and anything
        # that resolves outside the output directory.
        if file_path.is_symlink():
            logger.warning("Skipping symlink in skill output: %s", file_path.name)
            continue
        if file_path.resolve().parent != output_dir_resolved:
            logger.warning("Skipping skill output file outside output dir: %s", file_path.name)
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


def _safe_skill_path(root: Path, rel_path: object) -> Path:
    """Resolve a skill-declared relative path, rejecting escapes outside ``root``.

    Skill files come verbatim from workflow / template node data, so an absolute
    path, a ``..`` segment, or a NUL byte must never be allowed to write outside
    the throwaway workspace (the ``.py``/``.md`` allowlist only constrains the
    LLM skill-builder assistant, not execution).
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise ValueError("Skill file path must be a non-empty string")
    if "\x00" in rel_path:
        raise ValueError("Skill file path must not contain NUL bytes")
    candidate = Path(rel_path)
    if candidate.is_absolute() or candidate.drive or candidate.anchor:
        raise ValueError(f"Skill file path must be relative: {rel_path!r}")
    root_resolved = root.resolve()
    resolved = (root_resolved / candidate).resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(f"Skill file path escapes the workspace: {rel_path!r}")
    return resolved


def _write_skill_file(root: Path, file_data: dict[str, Any]) -> None:
    """Write a skill file to disk, decoding base64 payloads for binary assets."""
    path = _safe_skill_path(root, file_data.get("path"))
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


def _populate_workspace(
    root: Path,
    skill_files: list[dict[str, Any]],
    drive_files: list[dict[str, Any]] | None,
) -> Path:
    """Write skill files + Drive files into ``root`` and return the output directory."""
    for f in skill_files:
        _write_skill_file(root, f)
    if drive_files is not None:
        _prepare_drive_files(root, drive_files)
    output_dir = root / _OUTPUT_FILES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _build_result(stdout: str, stderr: str, output_dir: Path) -> SkillExecutionResult:
    """Parse a skill's stdout/stderr and collect any generated files."""
    stdout = (stdout or "").strip()
    if not stdout:
        output: object = {"output": "", "stderr": stderr or ""}
    else:
        try:
            output = json.loads(stdout)
        except json.JSONDecodeError:
            output = {"output": stdout, "stderr": stderr or ""}
    generated_files, hitl_request = _collect_output_files(output_dir)
    return SkillExecutionResult(
        output=output,
        generated_files=generated_files,
        hitl_request=hitl_request,
    )


def _force_remove_container(name: str) -> None:
    try:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass


def _execute_skill_subprocess(
    skill_files: list[dict[str, Any]],
    arguments: dict[str, Any],
    timeout_seconds: float,
    drive_files: list[dict[str, Any]] | None,
    entry_point: str,
) -> SkillExecutionResult:
    """Run the skill in a local subprocess (NOT a security boundary; trusted/dev only)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        output_dir = _populate_workspace(root, skill_files, drive_files)
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
                # Run with the backend's own interpreter so backend packages
                # (python-docx, pypdf, ...) are available to the skill.
                [_skill_interpreter(), entry_point],
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
        return _build_result(result.stdout, result.stderr, output_dir)


def _execute_skill_docker(
    skill_files: list[dict[str, Any]],
    arguments: dict[str, Any],
    timeout_seconds: float,
    drive_files: list[dict[str, Any]] | None,
    entry_point: str,
    image: str,
) -> SkillExecutionResult:
    """Run the skill inside a hardened, throwaway sibling container (no Docker socket)."""
    mount_point = _skill_volume_mount_point()
    run_dir = _skill_workspace_root() / "_skills" / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        # The sandbox runs non-root against a root-owned volume, so the throwaway
        # run dir (and the dirs the sandbox user must write) are made writable.
        _chmod_best_effort(run_dir, 0o777)
        (run_dir / ".home").mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(run_dir / ".home", 0o777)

        output_dir = _populate_workspace(run_dir, skill_files, drive_files)
        _chmod_best_effort(output_dir, 0o777)

        args_json = _serialize_skill_stdin(arguments)
        name = f"heym-skill-{uuid.uuid4().hex}"
        cmd = _build_skill_docker_command(image, name, mount_point, run_dir, entry_point)

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(input=args_json, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            _force_remove_container(name)
            raise TimeoutError(
                f"Skill execution timed out after {timeout_seconds} seconds"
            ) from None

        if stderr:
            logger.warning("Skill docker stderr: %s", stderr)
        # Fail closed when the sandbox itself could not start. Docker uses 125
        # (daemon/`docker run` error, e.g. a missing workspace volume), 126
        # (entrypoint not executable), and 127 (entrypoint not found) for
        # container-start failures; any other exit code is the skill's own
        # process exiting, which stays a soft result like the subprocess path.
        if proc.returncode in _DOCKER_START_FAILURE_CODES:
            raise RuntimeError(
                "Skill Docker sandbox failed to start "
                f"(docker exit {proc.returncode}): {(stderr or '').strip()[:500]}"
            )
        return _build_result(stdout, stderr, output_dir)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def execute_skill_python(
    skill_files: list[dict[str, Any]],
    arguments: dict[str, Any],
    timeout_seconds: float = 30.0,
    drive_files: list[dict[str, Any]] | None = None,
) -> SkillExecutionResult:
    """
    Execute a skill's Python script in the configured sandbox.

    Skill code is untrusted, so a sandbox backend is selected by
    ``HEYM_PYTHON_TOOL_SANDBOX`` (see the module docstring): ``auto``/``docker``
    run it inside a hardened throwaway sibling container with no Docker socket,
    ``subprocess`` runs it locally (trusted/dev only). ``auto`` fails closed when
    Docker is unavailable rather than running untrusted code in the backend.

    Args:
        skill_files: List of {"path": str, "content": str}
        arguments: Dict of arguments to pass to the script (as JSON on stdin)
        timeout_seconds: Max execution time
        drive_files: Optional accessible Drive file metadata with source_path values

    Returns:
        SkillExecutionResult with output, any generated files, and optional HITL request.

    Raises:
        RuntimeError: If the configured Docker sandbox backend is unavailable.
    """
    entry_point = _find_entry_point(skill_files)
    if not entry_point:
        raise ValueError("No Python file found in skill")

    mode = _sandbox_mode()
    if mode == "subprocess":
        logger.warning(
            "HEYM_PYTHON_TOOL_SANDBOX=subprocess: executing the skill in a local subprocess. "
            "This is NOT a security boundary and must only be used for trusted code or local "
            "development."
        )
        return _execute_skill_subprocess(
            skill_files, arguments, timeout_seconds, drive_files, entry_point
        )

    # mode == "auto" or "docker": require a real Docker sandbox and fail closed
    # rather than silently running untrusted skill code in the backend context.
    if not _docker_available():
        raise RuntimeError(
            "Skill execution requires a Docker sandbox but no working Docker daemon is reachable. "
            "Run with Docker available, or set HEYM_PYTHON_TOOL_SANDBOX=subprocess to explicitly "
            "allow the insecure local fallback (trusted/dev use only)."
        )
    image = _resolve_image()
    if image is None:
        raise RuntimeError(
            "Skill Docker sandbox is enabled but the runner image could not be resolved. "
            "Set HEYM_SKILL_IMAGE (or HEYM_PYTHON_TOOL_IMAGE) to the backend image."
        )
    return _execute_skill_docker(
        skill_files, arguments, timeout_seconds, drive_files, entry_point, image
    )
