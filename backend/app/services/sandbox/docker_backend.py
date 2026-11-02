"""Docker backend: hardened sibling containers through the ``docker`` CLI."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

from app.services.sandbox.errors import SandboxTimeoutError
from app.services.sandbox.spec import (
    OperatorMount,
    ProcessCommand,
    SandboxResult,
    SandboxSpec,
    WorkspaceMount,
)

logger = logging.getLogger(__name__)


def render_docker_argv(spec: SandboxSpec) -> list[str]:
    """The ``docker run`` argv for ``spec``. No Docker socket is ever mounted."""
    argv = ["docker", "run", "--rm", "-i", "--name", spec.name, "--network", spec.network]
    if spec.read_only_root:
        argv.append("--read-only")
    for tmpfs in spec.tmpfs:
        argv.extend(["--tmpfs", tmpfs.docker_value()])
    if spec.shm_size:
        argv.extend(["--shm-size", spec.shm_size])
    if spec.workdir:
        argv.extend(["--workdir", spec.workdir])
    if spec.user:
        argv.extend(["--user", spec.user])
    if spec.cap_drop_all:
        argv.extend(["--cap-drop", "ALL"])
    if spec.no_new_privileges:
        argv.extend(["--security-opt", "no-new-privileges"])
    if spec.pids:
        argv.extend(["--pids-limit", spec.pids])
    if spec.memory:
        argv.extend(["--memory", spec.memory])
    if spec.memory_swap:
        argv.extend(["--memory-swap", spec.memory_swap])
    if spec.cpus:
        argv.extend(["--cpus", spec.cpus])
    for mount in spec.workspace_mounts:
        argv.extend(docker_mount_args(mount))
    if spec.operator_mount is not None:
        argv.extend(operator_mount_args(spec.operator_mount))
    argv.extend(spec.docker_extra_args)
    for item in spec.env:
        argv.extend(["--env", item])
    if spec.entrypoint is not None:
        argv.extend(["--entrypoint", spec.entrypoint])
    argv.append(spec.image)
    argv.extend(spec.args)
    return argv


def _first_set(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def docker_mount_args(mount: WorkspaceMount) -> list[str]:
    """``--mount`` args exposing only ``mount.host_path`` at ``mount.target``."""
    source = mount.docker
    suffix = ",readonly" if mount.readonly else ""
    if source.native_bind:
        return ["--mount", f"type=bind,src={mount.host_path},dst={mount.target}{suffix}"]
    try:
        rel = mount.host_path.relative_to(source.mount_point)
    except ValueError as exc:
        raise RuntimeError(
            f"{source.label} {mount.host_path} is not under the workspace volume mount "
            f"{source.mount_point}"
        ) from exc
    rel_str = rel.as_posix()
    volume = _first_set(source.volume_env)
    if volume:
        return [
            "--mount",
            f"type=volume,src={volume},dst={mount.target},volume-subpath={rel_str}{suffix}",
        ]
    host_root = os.environ.get(source.host_root_env, "").strip() if source.host_root_env else ""
    if not host_root:
        for entry in current_container_mounts():
            if str(entry.get("Destination") or "") != str(source.mount_point):
                continue
            if entry.get("Type") == "volume" and entry.get("Name"):
                return [
                    "--mount",
                    f"type=volume,src={entry['Name']},dst={mount.target},"
                    f"volume-subpath={rel_str}{suffix}",
                ]
            if entry.get("Type") == "bind" and entry.get("Source"):
                host_root = str(entry["Source"])
                break
    if host_root:
        return ["--mount", f"type=bind,src={Path(host_root) / rel},dst={mount.target}{suffix}"]
    raise RuntimeError(source.missing_message)


def operator_mount_args(mount: OperatorMount) -> list[str]:
    """Args for the operator-configured MCP files mount; read-only unless writable."""
    if mount.volume:
        value = f"type=volume,src={mount.volume},dst={mount.target}"
        if mount.subpath:
            value += f",volume-subpath={mount.subpath}"
        if not mount.writable:
            value += ",readonly"
        return ["--mount", value]
    if mount.host_dir:
        return ["--volume", f"{mount.host_dir}:{mount.target}{'' if mount.writable else ':ro'}"]
    return []


def current_container_mounts() -> list[dict[str, Any]]:
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


def _docker_rm(name: str) -> None:
    try:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass


def _probe_docker() -> bool:
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


class DockerBackend:
    """Sibling containers on the Docker daemon behind ``/var/run/docker.sock``."""

    name = "docker"

    def __init__(self) -> None:
        self._available: bool | None = None
        self._lock = threading.Lock()

    def available(self) -> bool:
        """True when a working Docker daemon answers (probed once per process)."""
        with self._lock:
            if self._available is None:
                self._available = _probe_docker()
            return self._available

    def resolve_image(self) -> str | None:
        """The image this backend container runs, from ``docker inspect``."""
        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.Config.Image}}", socket.gethostname()],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return None
        image = result.stdout.strip()
        return image if result.returncode == 0 and image else None

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        """Run one container to completion; remove it and raise on timeout."""
        proc = subprocess.Popen(
            render_docker_argv(spec),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(input=stdin, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            _docker_rm(spec.name)
            raise SandboxTimeoutError(
                f"sandbox {spec.name} ran past {timeout_seconds:.0f} seconds"
            ) from None
        return SandboxResult(proc.returncode, stdout or "", stderr or "")

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        """``docker run`` argv for callers that spawn and supervise the process."""
        return ProcessCommand(argv=render_docker_argv(spec), env={}, name=spec.name)

    def force_remove(self, name: str | None) -> None:
        """Remove a container that may have outlived its client."""
        if name:
            _docker_rm(name)

    def uses_shared_workspace(self) -> bool:
        """Inside a container, workspaces must live on the volume shared with siblings."""
        return Path("/.dockerenv").exists()
