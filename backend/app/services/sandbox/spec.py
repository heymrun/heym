"""Backend-neutral description of one sandbox container run.

Every sandbox call site builds a ``SandboxSpec`` and hands it to the
``SandboxManager``. The Docker backend renders it as ``docker run`` argv and the
Kubernetes backend as a Pod. Standard library only: the wrapper shims import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Exit codes that mean the sandbox never started. Kubernetes reports such a pod as
# START_FAILURE_RETURNCODE, so callers keep one check for both backends.
START_FAILURE_CODES: frozenset[int] = frozenset({125, 126, 127})
START_FAILURE_RETURNCODE = 125
OOM_RETURNCODE = 137


@dataclass(frozen=True)
class Tmpfs:
    """Memory-backed scratch space: ``--tmpfs`` on Docker, a Memory emptyDir on Kubernetes."""

    path: str
    options: str
    size: str

    @classmethod
    def parse(cls, value: str) -> Tmpfs:
        """Parse a Docker ``--tmpfs`` value such as ``/tmp:rw,nosuid,size=64m``."""
        path, _, raw_options = value.partition(":")
        options: list[str] = []
        size = ""
        for option in raw_options.split(","):
            if option.startswith("size="):
                size = option.removeprefix("size=")
            elif option:
                options.append(option)
        if not size:
            raise ValueError(f"tmpfs value {value!r} has no size")
        return cls(path=path, options=",".join(options), size=size)

    def docker_value(self) -> str:
        """The ``--tmpfs`` value."""
        return f"{self.path}:{self.options},size={self.size}"


@dataclass(frozen=True)
class DockerVolumeSource:
    """How the Docker backend finds the shared volume behind a backend path.

    Order: a native backend binds the path itself; else the first set variable in
    ``volume_env`` names a volume, mounted with ``volume-subpath``; else
    ``host_root_env`` names the host directory behind ``mount_point``; else the
    backend container's own mount at ``mount_point`` is inspected.
    """

    mount_point: Path
    volume_env: tuple[str, ...]
    missing_message: str
    host_root_env: str | None = None
    native_bind: bool = False
    label: str = "Sandbox dir"


@dataclass(frozen=True)
class WorkspaceMount:
    """Expose one backend directory inside the sandbox, and nothing above it."""

    host_path: Path
    target: str
    readonly: bool
    docker: DockerVolumeSource


@dataclass(frozen=True)
class OperatorMount:
    """The MCP stdio files mount. Only an operator configures it, never a caller."""

    target: str
    writable: bool = False
    volume: str | None = None
    subpath: str | None = None
    host_dir: str | None = None


@dataclass(frozen=True)
class SandboxSpec:
    """One sandbox run, independent of the backend that executes it."""

    site: str
    name: str
    image: str
    entrypoint: str | None
    args: tuple[str, ...] = ()
    network: str = "none"
    user: str | None = "65534:65534"
    read_only_root: bool = True
    tmpfs: tuple[Tmpfs, ...] = ()
    shm_size: str | None = None
    memory: str | None = None
    memory_swap: str | None = None
    cpus: str | None = None
    pids: str | None = None
    cap_drop_all: bool = True
    no_new_privileges: bool = True
    env: tuple[str, ...] = ()
    workdir: str | None = None
    workspace_mounts: tuple[WorkspaceMount, ...] = ()
    operator_mount: OperatorMount | None = None
    docker_extra_args: tuple[str, ...] = ()
    deadline_seconds: float | None = None
    start_gate: bool = False

    @property
    def offline(self) -> bool:
        """True when the sandbox must have no network at all."""
        return self.network == "none"


@dataclass(frozen=True)
class SandboxResult:
    """Exit code and output of one finished sandbox."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def start_failed(self) -> bool:
        """The sandbox never started (image, mount, entrypoint or scheduling)."""
        return self.returncode in START_FAILURE_CODES

    @property
    def oom_killed(self) -> bool:
        """The sandbox was killed for exceeding its memory limit."""
        return self.returncode == OOM_RETURNCODE


@dataclass(frozen=True)
class ProcessCommand:
    """A command for callers that spawn the sandbox as their own child process."""

    argv: list[str]
    env: dict[str, str]
    name: str
