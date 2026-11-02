"""Run custom Playwright scripts in an isolated, throwaway sibling container.

Custom ``playwrightCode`` is untrusted Python. Running it in the backend process is
equivalent to backend RCE (GHSA-mp23-7m6r-jfw4): even with a scrubbed environment the
code shares the backend's uid, ``/proc``, filesystem and the mounted Docker socket, so it
can recover secrets and escape to the host. This module runs that code inside a
hardened, single-use container instead.

Modes are selected by ``HEYM_PLAYWRIGHT_SANDBOX``:

* ``docker`` / ``auto`` (default) - run the script inside a throwaway sibling container
  of the backend image: no Docker socket, no backend bind mounts, no backend secrets in
  the environment, ``no-new-privileges``, dropped capabilities, and strict CPU / memory /
  PID limits. Network is left enabled (``bridge``) because browser automation needs it;
  tighten egress at the network layer if required. If Docker is unavailable the call
  **fails closed** (raises) rather than silently running untrusted code in-process.
* ``subprocess`` - run the script in the backend process (the legacy path). This is NOT a
  security boundary and must be selected explicitly, for trusted single-user or local dev
  only.

The script is streamed to ``python`` over stdin, never bind-mounted, so it works under
Docker-in-Docker where the backend's temp paths do not exist on the host daemon.

The bundled Chromium in the backend image is installed under root's home, so the sandbox
runs as root **inside the isolated container** by default. That is safe here: the
container has no socket, no mounts and no secrets, so "root" only owns a throwaway
sandbox. Chromium refuses to run as root without ``--no-sandbox``; custom code that drives
Chromium should launch it with ``args=["--no-sandbox"]`` (documented on the node page), or
the operator can point ``HEYM_PLAYWRIGHT_SANDBOX_USER`` at a non-root uid on a suitably
built image.
"""

import logging
import os
import sys
import uuid

from app.services.sandbox import SandboxSpec, Tmpfs, get_sandbox_manager
from app.services.sandbox.docker_backend import render_docker_argv
from app.services.sandbox.errors import SandboxTimeoutError

logger = logging.getLogger(__name__)

# Compose backend image layout vs single-container GHCR release layout.
_DEFAULT_SANDBOX_PYTHONS = (
    "/app/backend/.venv/bin/python",
    "/app/.venv/bin/python",
)


class PlaywrightSandboxUnavailableError(RuntimeError):
    """Raised when the Docker sandbox is required but cannot be used (fail closed)."""


def sandbox_mode() -> str:
    raw = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX", "auto").strip().lower()
    if raw not in ("auto", "docker", "subprocess"):
        logger.warning("Unknown HEYM_PLAYWRIGHT_SANDBOX=%r; defaulting to 'auto'", raw)
        return "auto"
    return raw


def _sandbox_python() -> str:
    """Python interpreter path inside the sibling sandbox image.

    Compose backend images use ``/app/.venv/...``; the single GHCR release image
    keeps the backend under ``/app/backend/.venv/...``. Prefer an explicit
    override, then any ``/app/...`` interpreter that exists in *this* container
    (same layout as the sibling), then known defaults.
    """
    override = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_PYTHON", "").strip()
    if override:
        return override
    exe = (sys.executable or "").strip()
    if exe.startswith("/app/") and os.path.isfile(exe):
        return exe
    for candidate in _DEFAULT_SANDBOX_PYTHONS:
        if os.path.isfile(candidate):
            return candidate
    return _DEFAULT_SANDBOX_PYTHONS[-1]


def require_image() -> str:
    """Resolve the sandbox image, failing closed if Docker or the image is unavailable."""
    if not _docker_available():
        raise PlaywrightSandboxUnavailableError(
            "Custom Playwright code requires a Docker sandbox but no working Docker daemon "
            "is reachable. Run with Docker available, or set HEYM_PLAYWRIGHT_SANDBOX="
            "subprocess to explicitly allow the insecure in-process fallback "
            "(trusted / local dev only)."
        )
    image = _resolve_image()
    if not image:
        raise PlaywrightSandboxUnavailableError(
            "Custom Playwright code Docker sandbox is enabled but the runner image could "
            "not be resolved. Set HEYM_PLAYWRIGHT_SANDBOX_IMAGE to the backend image "
            "(e.g. heym-backend:local), or set HEYM_PLAYWRIGHT_SANDBOX=subprocess for "
            "trusted / local native development (run.sh does this automatically)."
        )
    return image


def _docker_available() -> bool:
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def _resolve_image() -> str | None:
    """``HEYM_PLAYWRIGHT_SANDBOX_IMAGE``, ``HEYM_CODEX_DOCKER_IMAGE``, else the backend's own image."""
    return get_sandbox_manager().resolve_image(
        ("HEYM_PLAYWRIGHT_SANDBOX_IMAGE", "HEYM_CODEX_DOCKER_IMAGE")
    )


def _playwright_spec(image: str, name: str) -> SandboxSpec:
    """Throwaway sandbox that reads the script on stdin. Network stays on for browsing."""
    memory = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_MEMORY", "1g")
    user = os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_USER", "").strip()
    return SandboxSpec(
        site="playwright",
        name=name,
        image=image,
        entrypoint=_sandbox_python(),
        args=("-",),
        network=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_NETWORK", "bridge"),
        user=user or None,
        read_only_root=False,
        tmpfs=(Tmpfs("/tmp", "rw,nosuid", "256m"),),
        shm_size=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_SHM_SIZE", "1g"),
        pids=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_PIDS", "512"),
        memory=memory,
        memory_swap=memory,
        cpus=os.environ.get("HEYM_PLAYWRIGHT_SANDBOX_CPUS", "2"),
        env=("PYTHONIOENCODING=utf-8", "PYTHONDONTWRITEBYTECODE=1"),
    )


def build_docker_command(image: str, name: str) -> list[str]:
    """Build a hardened, throwaway ``docker run`` invocation that reads the script on stdin."""
    return render_docker_argv(_playwright_spec(image, name))


def run_script(
    script_content: str,
    timeout_seconds: float,
    image: str | None = None,
) -> tuple[int, str, str]:
    """Run ``script_content`` in a hardened throwaway sandbox; return ``(returncode, stdout, stderr)``.

    Raises :class:`TimeoutError` past ``timeout_seconds`` and
    :class:`PlaywrightSandboxUnavailableError` when the sandbox cannot be established.
    """
    image = image or require_image()
    name = f"heym-pw-{uuid.uuid4().hex}"
    try:
        result = get_sandbox_manager().run(
            _playwright_spec(image, name), script_content, timeout_seconds
        )
    except SandboxTimeoutError:
        raise TimeoutError(
            f"Playwright script timed out after {timeout_seconds:.1f} seconds"
        ) from None
    return result.returncode, result.stdout, result.stderr
