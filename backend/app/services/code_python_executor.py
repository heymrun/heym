"""Execute Code node Python in a disposable, hardened sandbox.

Unlike the Agent tool sandbox (``python_tool_executor``) and the skill sandbox
(``skill_python_executor``), this path has **no subprocess fallback and reads
no sandbox-mode environment variable**. When no sandbox backend is reachable the
Code node fails closed, because the code it runs is arbitrary user Python with
arbitrary third-party dependencies.

Execution is one or two throwaway sandboxes (Docker containers or Kubernetes
pods, see ``app.services.sandbox``):

* With no dependencies, a single offline sandbox runs the code. The runner
  source travels in the stdin payload, so nothing is mounted.
* With dependencies, a network-enabled sandbox installs them into a per-run
  ``.deps`` directory on the shared workspace volume (``uv`` first, ``pip`` as
  a compatibility retry), then a second sandbox mounts that subtree
  ``readonly`` and runs the code with ``PYTHONPATH`` pointing at it.

Neither sandbox receives the Docker socket, a ServiceAccount token or any backend
secret, and the run directory is deleted on every exit path.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.sandbox import (
    DockerVolumeSource,
    SandboxSpec,
    Tmpfs,
    WorkspaceMount,
    get_sandbox_manager,
)
from app.services.sandbox.docker_backend import render_docker_argv
from app.services.sandbox.env import CODE_FORWARD_PREFIXES, forwarded_env
from app.services.sandbox.errors import SandboxTimeoutError
from app.services.sandbox.spec import START_FAILURE_CODES

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

# Old name kept: the file sandbox imports it.
_DOCKER_START_FAILURE_CODES: frozenset[int] = START_FAILURE_CODES

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
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def resolve_sandbox_image() -> str | None:
    """``HEYM_PYTHON_TOOL_IMAGE``, ``HEYM_CODEX_DOCKER_IMAGE``, else the backend's own image."""
    return get_sandbox_manager().resolve_image(
        ("HEYM_PYTHON_TOOL_IMAGE", "HEYM_CODEX_DOCKER_IMAGE")
    )


def _runner_source() -> str:
    """Return the source of ``code_runner.py`` to ship in the stdin payload."""
    return Path(__file__).with_name("code_runner.py").read_text(encoding="utf-8")


def _workspace_mount_point() -> Path:
    """Absolute path where the shared workspace volume is mounted in the backend."""
    return Path(os.environ.get("HEYM_CODEX_WORKSPACE_DIR", "").strip() or _DEFAULT_WORKSPACE_MOUNT)


def _is_containerized() -> bool:
    """True when sandbox workspaces must live on the volume shared with the sandbox."""
    return get_sandbox_manager().uses_shared_workspace()


def _code_run_root() -> Path:
    """Directory that holds per-run Code node directories.

    Inside a container this must live on the volume shared with the sibling.
    On a native backend (``run.sh``) there is no such volume, but there is also
    no need for one: a host path can be bind-mounted straight into the sibling.
    """
    if not _is_containerized():
        return Path(tempfile.gettempdir()) / "heym-code-runs"
    return _workspace_mount_point() / _CODE_RUN_SUBDIR


def workspace_mount(
    host_path: Path,
    container_path: str,
    readonly: bool,
    *,
    missing_volume_hint: str = "The sandbox needs a shared workspace volume.",
    fallback_hint: str = "",
) -> WorkspaceMount:
    """Expose only ``host_path`` at ``container_path``.

    ``host_path`` must live under the workspace mount when the backend runs in a
    container; a native backend binds it straight through.
    """
    mount_point = _workspace_mount_point()
    return WorkspaceMount(
        host_path=host_path,
        target=container_path,
        readonly=readonly,
        docker=DockerVolumeSource(
            mount_point=mount_point,
            volume_env=("HEYM_CODEX_DOCKER_WORKSPACE_VOLUME",),
            missing_message=(
                f"{missing_volume_hint} Set HEYM_CODEX_DOCKER_WORKSPACE_VOLUME to the named "
                f"volume mounted at {mount_point}.{fallback_hint}"
            ),
            native_bind=not _is_containerized(),
        ),
    )


def _code_workspace_mount(run_dir: Path, readonly: bool) -> WorkspaceMount:
    return workspace_mount(
        run_dir,
        str(run_dir),
        readonly,
        missing_volume_hint="The Code node needs a shared workspace volume to install "
        "dependencies.",
        fallback_hint=" Or leave requirements.txt empty to run without dependencies.",
    )


def code_spec(
    *,
    site: str,
    name: str,
    image: str,
    network: str,
    tmpfs: str,
    entrypoint: str,
    args: tuple[str, ...],
    workdir: str,
    mounts: tuple[WorkspaceMount, ...] = (),
    extra_env: tuple[str, ...] = (),
    memory: str = _MEMORY_LIMIT,
    cpus: str = _CPU_LIMIT,
) -> SandboxSpec:
    """The Code node sandbox: non-root, no capabilities, read-only root, allowlisted env."""
    return SandboxSpec(
        site=site,
        name=name,
        image=image,
        entrypoint=entrypoint,
        args=args,
        network=network,
        user=_SANDBOX_USER,
        tmpfs=(Tmpfs.parse(tmpfs),),
        workdir=workdir,
        pids=_PIDS_LIMIT,
        memory=memory,
        memory_swap=memory,
        cpus=cpus,
        env=(
            "HOME=/tmp",
            "PYTHONDONTWRITEBYTECODE=1",
            "PYTHONIOENCODING=utf-8",
            *forwarded_env(CODE_FORWARD_PREFIXES),
            *extra_env,
        ),
        workspace_mounts=mounts,
    )


def _install_spec(
    image: str, name: str, mounts: tuple[WorkspaceMount, ...], run_dir: Path, tool: str
) -> SandboxSpec:
    target = str(run_dir / _DEPS_DIRNAME)
    requirements = str(run_dir / _REQUIREMENTS_FILENAME)
    if tool == "uv":
        args = ("pip", "install", "--no-cache", "--target", target, "-r", requirements)
    else:
        args = ("install", "--no-cache-dir", "--target", target, "-r", requirements)
    return code_spec(
        site="code-install",
        name=name,
        image=image,
        network="bridge",
        tmpfs=_INSTALL_TMPFS,
        entrypoint=tool,
        args=args,
        workdir="/tmp",
        mounts=mounts,
    )


def _run_spec(
    image: str,
    name: str,
    allow_network: bool,
    mounts: tuple[WorkspaceMount, ...],
    deps_path: Path | None,
) -> SandboxSpec:
    return code_spec(
        site="code-run",
        name=name,
        image=image,
        network="bridge" if allow_network else "none",
        tmpfs=_RUN_TMPFS,
        entrypoint="python",
        args=("-c", _BOOTSTRAP),
        workdir="/tmp",
        mounts=mounts,
        extra_env=(f"PYTHONPATH={deps_path}",) if deps_path is not None else (),
    )


def _build_install_command(
    image: str, name: str, mounts: tuple[WorkspaceMount, ...], run_dir: Path, tool: str
) -> list[str]:
    """The install sandbox as ``docker run`` argv (``uv`` or ``pip``)."""
    return render_docker_argv(_install_spec(image, name, mounts, run_dir, tool))


def _build_run_command(
    image: str,
    name: str,
    allow_network: bool,
    mounts: tuple[WorkspaceMount, ...],
    deps_path: Path | None,
) -> list[str]:
    """The execution sandbox as ``docker run`` argv."""
    return render_docker_argv(_run_spec(image, name, allow_network, mounts, deps_path))


def run_sandbox_container(
    spec: SandboxSpec,
    stdin_text: str | None,
    timeout_seconds: float,
    phase: str,
) -> tuple[int, str, str]:
    """Run one sandbox and return ``(returncode, stdout, stderr)``."""
    try:
        result = get_sandbox_manager().run(spec, stdin_text, timeout_seconds)
    except SandboxTimeoutError:
        raise TimeoutError(
            f"Code node {phase} timed out after {timeout_seconds:.0f} seconds"
        ) from None
    return result.returncode, result.stdout, result.stderr


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

    mounts = (_code_workspace_mount(run_dir, readonly=False),)
    attempts: list[str] = []
    for tool in ("uv", "pip"):
        name = f"heym-code-install-{uuid.uuid4().hex}"
        returncode, stdout, stderr = run_sandbox_container(
            _install_spec(image, name, mounts, run_dir, tool),
            None,
            _INSTALL_TIMEOUT_SECONDS,
            "dependency install",
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
        mounts: tuple[WorkspaceMount, ...] = ()
        deps_path: Path | None = None
        if needs_install:
            run_dir = _code_run_root() / uuid.uuid4().hex
            run_dir.mkdir(parents=True, exist_ok=True)
            _chmod_best_effort(run_dir, 0o777)
            install_tool, install_log = _install_dependencies(image, run_dir, requirements)
            mounts = (_code_workspace_mount(run_dir, readonly=True),)
            deps_path = run_dir / _DEPS_DIRNAME

        name = f"heym-code-{uuid.uuid4().hex}"
        returncode, stdout, stderr = run_sandbox_container(
            _run_spec(image, name, allow_network, mounts, deps_path),
            payload,
            _RUN_TIMEOUT_SECONDS,
            "execution",
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
