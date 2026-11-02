"""The single entry point every sandbox call site goes through."""

from __future__ import annotations

import logging
import os
import threading
from typing import Protocol

from app.services.sandbox.docker_backend import DockerBackend
from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.spec import ProcessCommand, SandboxResult, SandboxSpec

logger = logging.getLogger(__name__)


class SandboxBackend(Protocol):
    """What a backend provides. Docker and Kubernetes implement it."""

    name: str

    def available(self) -> bool: ...

    def resolve_image(self) -> str | None: ...

    def run(
        self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float
    ) -> SandboxResult: ...

    def process_command(self, spec: SandboxSpec) -> ProcessCommand: ...

    def force_remove(self, name: str | None) -> None: ...

    def uses_shared_workspace(self) -> bool: ...


class SandboxManager:
    """Delegates to the backend chosen once per process."""

    def __init__(self, backend: SandboxBackend) -> None:
        self._backend = backend

    @property
    def backend(self) -> SandboxBackend:
        """The backend in use."""
        return self._backend

    @property
    def backend_name(self) -> str:
        """``docker`` or ``kubernetes``."""
        return self._backend.name

    def available(self) -> bool:
        """True when the backend can start sandboxes right now."""
        return self._backend.available()

    def resolve_image(self, overrides: tuple[str, ...]) -> str | None:
        """First non-empty variable in ``overrides``, else the image the backend runs."""
        for name in overrides:
            value = (os.environ.get(name) or "").strip()
            if value:
                return value
        return self._backend.resolve_image()

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        """Run one sandbox to completion."""
        return self._backend.run(spec, stdin, timeout_seconds)

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        """Command for a caller that spawns and supervises the sandbox process."""
        return self._backend.process_command(spec)

    def force_remove(self, name: str | None) -> None:
        """Remove a sandbox that may have outlived its caller."""
        self._backend.force_remove(name)

    def uses_shared_workspace(self) -> bool:
        """True when sandbox workspaces must live on the shared workspace volume."""
        return self._backend.uses_shared_workspace()


BACKEND_ENV = "HEYM_SANDBOX_BACKEND"


class UnavailableBackend:
    """A backend that was asked for but cannot run. Every call fails closed."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    def available(self) -> bool:
        return False

    def resolve_image(self) -> str | None:
        return None

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        raise SandboxConfigError(self.reason)

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        raise SandboxConfigError(self.reason)

    def force_remove(self, name: str | None) -> None:
        return None

    def uses_shared_workspace(self) -> bool:
        return True


def backend_mode() -> str:
    """``auto`` (default), ``docker`` or ``kubernetes`` from HEYM_SANDBOX_BACKEND."""
    raw = (os.environ.get(BACKEND_ENV) or "auto").strip().lower()
    if raw not in ("auto", "docker", "kubernetes"):
        logger.warning("Unknown %s=%r; using 'auto'", BACKEND_ENV, raw)
        return "auto"
    return raw


def _kubernetes_backend(*, forced: bool) -> SandboxBackend:
    from app.services.sandbox.kubernetes import config as kube_config
    from app.services.sandbox.kubernetes.backend import KubernetesBackend

    try:
        if kube_config.in_cluster_available():
            config = kube_config.load_in_cluster()
        elif forced:
            config = kube_config.load_kubeconfig()
        else:
            return UnavailableBackend("kubernetes", "not running in a Kubernetes pod")
    except kube_config.KubeConfigError as exc:
        logger.warning("Kubernetes sandbox backend unavailable: %s", exc)
        return UnavailableBackend("kubernetes", str(exc))
    return KubernetesBackend(config)


def _build_manager() -> SandboxManager:
    mode = backend_mode()
    if mode == "docker":
        return SandboxManager(DockerBackend())
    if mode == "kubernetes":
        return SandboxManager(_kubernetes_backend(forced=True))
    docker = DockerBackend()
    if docker.available():
        return SandboxManager(docker)
    kubernetes = _kubernetes_backend(forced=False)
    if kubernetes.available():
        return SandboxManager(kubernetes)
    return SandboxManager(docker)


_manager: SandboxManager | None = None
_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """The process-wide manager, built on first use."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = _build_manager()
        return _manager


def reset_sandbox_manager() -> None:
    """Forget the manager so the next call selects again (tests, config reloads)."""
    global _manager
    with _manager_lock:
        _manager = None
