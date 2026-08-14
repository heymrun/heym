"""Execute Code node Python in a disposable, hardened Docker sandbox.

Unlike the Agent tool sandbox (``python_tool_executor``) and the skill sandbox
(``skill_python_executor``), this path has **no subprocess fallback and reads
no sandbox-mode environment variable**. When no Docker daemon is reachable the
Code node fails closed, because the code it runs is arbitrary user Python with
arbitrary third-party dependencies.

Execution is one or two throwaway containers:

* With no dependencies, a single ``--network none`` container runs the code.
  The runner source travels in the stdin payload, so nothing is mounted.
* With dependencies, a network-enabled container installs them into a per-run
  ``.deps`` directory on the shared workspace volume (``uv`` first, ``pip`` as
  a compatibility retry), then a second container mounts that subtree
  ``readonly`` and runs the code with ``PYTHONPATH`` pointing at it.

Neither container receives the Docker socket or any backend secret, and the
run directory is deleted on every exit path.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Limits are constants rather than environment variables: they are platform
# properties of the sandbox, not deployment configuration.
_MEMORY_LIMIT = "512m"
_CPU_LIMIT = "1"
_PIDS_LIMIT = "256"
_SANDBOX_USER = "65534:65534"
_INSTALL_TIMEOUT_SECONDS = 120.0
_RUN_TIMEOUT_SECONDS = 60.0
_INSTALL_TMPFS = "/tmp:rw,nosuid,size=512m"
_RUN_TMPFS = "/tmp:rw,nosuid,size=256m"
_MAX_INSTALL_LOG_CHARS = 8000

_DEFAULT_WORKSPACE_MOUNT = "/app/data/codex-workspaces"
_CODE_RUN_SUBDIR = "_code-runs"
_DEPS_DIRNAME = ".deps"
_REQUIREMENTS_FILENAME = "requirements.txt"

# Docker exit codes that mean the container never started. These must fail
# closed so an unstartable sandbox is never mistaken for a completed run.
_DOCKER_START_FAILURE_CODES: frozenset[int] = frozenset({125, 126, 127})

# Reads the stdin payload, executes the shipped runner source, and hands the
# payload to its ``run``. Keeping the runner out of the image sidesteps the
# path difference between backend/Dockerfile (/app) and release.Dockerfile
# (/app/backend) without adding an environment variable.
_BOOTSTRAP = (
    "import sys,json;"
    "p=json.loads(sys.stdin.read());"
    "g={'__name__':'__heym_runner__'};"
    "exec(compile(p['runner'],'code_runner.py','exec'),g);"
    "g['run'](p)"
)

_docker_available_cache: bool | None = None


@dataclass
class CodeExecutionResult:
    """Outcome of one Code node execution."""

    result: object = None
    logs: str = ""
    install_ok: bool = True
    install_tool: str = "none"
    install_log: str = ""


def _truncate(text: str, limit: int = _MAX_INSTALL_LOG_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated, {len(text) - limit} more characters"


def docker_available() -> bool:
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


def resolve_sandbox_image() -> str | None:
    """Resolve the sandbox image without introducing a new variable."""
    override = (
        os.environ.get("HEYM_PYTHON_TOOL_IMAGE", "").strip()
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


def _runner_source() -> str:
    """Return the source of ``code_runner.py`` to ship in the stdin payload."""
    return Path(__file__).with_name("code_runner.py").read_text(encoding="utf-8")


def _workspace_mount_point() -> Path:
    """Absolute path where the shared workspace volume is mounted in the backend."""
    return Path(os.environ.get("HEYM_CODEX_WORKSPACE_DIR", "").strip() or _DEFAULT_WORKSPACE_MOUNT)


def _is_containerized() -> bool:
    """True when the backend itself runs inside a container."""
    return Path("/.dockerenv").exists()


def _code_run_root() -> Path:
    """Directory that holds per-run Code node directories.

    Inside a container this must live on the volume shared with the sibling.
    On a native backend (``run.sh``) there is no such volume, but there is also
    no need for one: a host path can be bind-mounted straight into the sibling.
    """
    if not _is_containerized():
        return Path(tempfile.gettempdir()) / "heym-code-runs"
    return _workspace_mount_point() / _CODE_RUN_SUBDIR


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
            ["docker", "inspect", hostname], capture_output=True, text=True, timeout=5
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


def _resolve_workspace_mount(run_dir: Path, readonly: bool) -> list[str]:
    """Return ``docker run`` mount args exposing only ``run_dir`` to the sibling."""
    suffix = ",readonly" if readonly else ""

    # A native backend already holds a real host path, so bind it straight
    # through at the same location. No shared volume is involved.
    if not _is_containerized():
        return ["--mount", f"type=bind,src={run_dir},dst={run_dir}{suffix}"]

    mount_point = _workspace_mount_point()
    try:
        rel = run_dir.relative_to(mount_point)
    except ValueError as exc:
        raise RuntimeError(
            f"Code run dir {run_dir} is not under the workspace volume mount {mount_point}"
        ) from exc

    volume = os.environ.get("HEYM_CODEX_DOCKER_WORKSPACE_VOLUME", "").strip()
    if volume:
        return [
            "--mount",
            f"type=volume,src={volume},dst={run_dir},volume-subpath={rel.as_posix()}{suffix}",
        ]

    for mount in _current_container_mounts():
        if str(mount.get("Destination") or "") != str(mount_point):
            continue
        if mount.get("Type") == "volume" and mount.get("Name"):
            return [
                "--mount",
                f"type=volume,src={mount['Name']},dst={run_dir},"
                f"volume-subpath={rel.as_posix()}{suffix}",
            ]
        if mount.get("Type") == "bind" and mount.get("Source"):
            host_run_dir = Path(str(mount["Source"])) / rel
            return ["--mount", f"type=bind,src={host_run_dir},dst={run_dir}{suffix}"]

    raise RuntimeError(
        "The Code node needs a shared workspace volume to install dependencies. Set "
        "HEYM_CODEX_DOCKER_WORKSPACE_VOLUME to the named volume mounted at "
        f"{mount_point}, or leave requirements.txt empty to run without dependencies."
    )


# Non-secret, portable settings forwarded into both phases. Dependency install
# has to reach PyPI, which fails behind a corporate proxy or a custom CA bundle
# unless these survive. Everything else -- database URLs, SECRET_KEY /
# ENCRYPTION_KEY, provider API keys -- is withheld by this allowlist, which
# fails safe: a new backend secret is dropped by default.
_ENV_FORWARD_PREFIXES: tuple[str, ...] = (
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
)


def _forwarded_env() -> dict[str, str]:
    """Return the allowlisted, non-secret environment to pass into the sandbox."""
    return {
        key: value
        for key, value in os.environ.items()
        # HOME is set explicitly to a writable tmpfs path; the backend's value
        # must never override it.
        if key != "HOME" and key.startswith(_ENV_FORWARD_PREFIXES)
    }


def hardening_args(name: str, network: str, tmpfs: str) -> list[str]:
    """Flags shared by both sandbox phases. No Docker socket, no backend secrets."""
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--network",
        network,
        "--read-only",
        "--tmpfs",
        tmpfs,
        "--user",
        _SANDBOX_USER,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        _PIDS_LIMIT,
        "--memory",
        _MEMORY_LIMIT,
        "--memory-swap",
        _MEMORY_LIMIT,
        "--cpus",
        _CPU_LIMIT,
        "--env",
        "HOME=/tmp",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--env",
        "PYTHONIOENCODING=utf-8",
    ]
    for key, value in _forwarded_env().items():
        args.extend(["--env", f"{key}={value}"])
    return args


def _build_install_command(
    image: str,
    name: str,
    mount_args: list[str],
    run_dir: Path,
    tool: str,
) -> list[str]:
    """Build the dependency install container command for ``uv`` or ``pip``."""
    target = str(run_dir / _DEPS_DIRNAME)
    requirements = str(run_dir / _REQUIREMENTS_FILENAME)
    cmd = hardening_args(name, "bridge", _INSTALL_TMPFS)
    cmd.extend(mount_args)
    cmd.extend(["--workdir", "/tmp", "--entrypoint", tool, image])
    if tool == "uv":
        cmd.extend(["pip", "install", "--no-cache", "--target", target, "-r", requirements])
    else:
        cmd.extend(["install", "--no-cache-dir", "--target", target, "-r", requirements])
    return cmd


def _build_run_command(
    image: str,
    name: str,
    allow_network: bool,
    mount_args: list[str],
    deps_path: Path | None,
) -> list[str]:
    """Build the code execution container command."""
    cmd = hardening_args(name, "bridge" if allow_network else "none", _RUN_TMPFS)
    cmd.extend(mount_args)
    if deps_path is not None:
        cmd.extend(["--env", f"PYTHONPATH={deps_path}"])
    cmd.extend(["--workdir", "/tmp", "--entrypoint", "python", image, "-c", _BOOTSTRAP])
    return cmd


def _force_remove_container(name: str) -> None:
    try:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass


def run_sandbox_container(
    cmd: list[str],
    stdin_text: str | None,
    timeout_seconds: float,
    name: str,
    phase: str,
) -> tuple[int, str, str]:
    """Run one sandbox container and return ``(returncode, stdout, stderr)``."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(input=stdin_text, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        _force_remove_container(name)
        raise TimeoutError(
            f"Code node {phase} timed out after {timeout_seconds:.0f} seconds"
        ) from None
    return proc.returncode, stdout or "", stderr or ""


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _install_dependencies(image: str, run_dir: Path, requirements: str) -> tuple[str, str]:
    """Install requirements into ``run_dir/.deps``; return ``(tool, log)``."""
    (run_dir / _REQUIREMENTS_FILENAME).write_text(requirements, encoding="utf-8")
    deps_dir = run_dir / _DEPS_DIRNAME
    deps_dir.mkdir(parents=True, exist_ok=True)
    _chmod_best_effort(deps_dir, 0o777)

    mount_args = _resolve_workspace_mount(run_dir, readonly=False)
    attempts: list[str] = []
    for tool in ("uv", "pip"):
        name = f"heym-code-install-{uuid.uuid4().hex}"
        cmd = _build_install_command(image, name, mount_args, run_dir, tool)
        returncode, stdout, stderr = run_sandbox_container(
            cmd, None, _INSTALL_TIMEOUT_SECONDS, name, "dependency install"
        )
        attempts.append(f"[{tool}] exit {returncode}\n{stdout}{stderr}".strip())
        if returncode == 0:
            return tool, _truncate("\n\n".join(attempts))
        logger.warning("Code node %s install failed (exit %s)", tool, returncode)

    raise RuntimeError(
        "Code node dependency install failed with both uv and pip.\n\n"
        + _truncate("\n\n".join(attempts))
    )


def _parse_envelope(stdout: str) -> tuple[object, str]:
    """Parse the runner envelope; return ``(result, logs)`` or raise."""
    try:
        envelope = json.loads(stdout.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Code node produced unreadable output: {stdout.strip()[:500]}") from exc
    if not isinstance(envelope, dict):
        raise ValueError(f"Code node produced unreadable output: {stdout.strip()[:500]}")
    if not envelope.get("success"):
        error = str(envelope.get("error") or "Code execution failed")
        logs = str(envelope.get("logs") or "")
        raise ValueError(f"{error}\n\nOutput before the error:\n{logs}" if logs else error)
    return envelope.get("result"), str(envelope.get("logs") or "")


def execute_code(
    code: str,
    requirements: str,
    params: dict,
    allow_network: bool,
) -> CodeExecutionResult:
    """Run Code node Python in a disposable sandbox and return its result.

    Args:
        code: User Python source that must define ``main(params)``.
        requirements: ``requirements.txt`` contents; blank skips the install phase.
        params: Already-resolved parameters exposed to the code as ``params``.
        allow_network: Whether the execution phase gets network egress.

    Raises:
        RuntimeError: Docker unreachable, image unresolvable, install failed, or
            the sandbox container never started.
        TimeoutError: Install or execution exceeded its limit.
        ValueError: The code raised, or produced unreadable output.
    """
    if not docker_available():
        raise RuntimeError(
            "The Code node requires Docker to run Python in an isolated sandbox, but no "
            "working Docker daemon is reachable. No fallback exists for this node: user "
            "code is never executed in the backend process."
        )
    image = resolve_sandbox_image()
    if image is None:
        raise RuntimeError(
            "The Code node sandbox image could not be resolved. Set HEYM_PYTHON_TOOL_IMAGE "
            "to the backend image."
        )

    payload = json.dumps({"runner": _runner_source(), "code": code, "params": params}, default=str)
    needs_install = bool((requirements or "").strip())
    run_dir: Path | None = None
    install_tool = "none"
    install_log = ""

    try:
        mount_args: list[str] = []
        deps_path: Path | None = None
        if needs_install:
            run_dir = _code_run_root() / uuid.uuid4().hex
            run_dir.mkdir(parents=True, exist_ok=True)
            _chmod_best_effort(run_dir, 0o777)
            install_tool, install_log = _install_dependencies(image, run_dir, requirements)
            mount_args = _resolve_workspace_mount(run_dir, readonly=True)
            deps_path = run_dir / _DEPS_DIRNAME

        name = f"heym-code-{uuid.uuid4().hex}"
        cmd = _build_run_command(image, name, allow_network, mount_args, deps_path)
        returncode, stdout, stderr = run_sandbox_container(
            cmd, payload, _RUN_TIMEOUT_SECONDS, name, "execution"
        )
        if returncode in _DOCKER_START_FAILURE_CODES:
            raise RuntimeError(
                f"Code node sandbox failed to start (docker exit {returncode}): "
                f"{stderr.strip()[:500]}"
            )
        if stderr.strip():
            logger.warning("Code node sandbox stderr: %s", stderr.strip()[:2000])

        result, logs = _parse_envelope(stdout)
        return CodeExecutionResult(
            result=result,
            logs=logs,
            install_ok=True,
            install_tool=install_tool,
            install_log=install_log,
        )
    finally:
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
