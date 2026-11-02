"""Entry point behind the ``heym-codex-docker`` and ``heym-opencode-docker`` shims.

The runner services start the shim with the run's workspace as cwd and its home in
the environment. This module turns that into a sandbox that sees only the run's two
directories, on whichever backend the manager selected.
"""

from __future__ import annotations

import os
import signal
import stat
import subprocess
import sys
import uuid
from pathlib import Path

from app.services.sandbox.coding_agents import PROFILES, RunScopeError, agent_spec, run_scope
from app.services.sandbox.manager import SandboxManager, get_sandbox_manager
from app.services.sandbox.spec import SandboxSpec

_FALLBACK_IMAGE = "heym-backend:local"


def main(argv: list[str]) -> int:
    """Run ``codex``/``opencode`` with ``argv[1:]`` in the run's sandbox; return its exit code."""
    if not argv or argv[0] not in PROFILES:
        print(
            "usage: python -m app.services.sandbox.wrapper_cli codex|opencode [args...]",
            file=sys.stderr,
        )
        return 2
    profile = PROFILES[argv[0]]
    env = os.environ
    cwd = Path.cwd()
    try:
        scope = run_scope(profile, cwd, env)
    except RunScopeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    manager = get_sandbox_manager()
    kubernetes = manager.backend_name == "kubernetes"
    image = manager.resolve_image((f"{profile.env_prefix}_DOCKER_IMAGE",)) or _FALLBACK_IMAGE
    run_id = (env.get(profile.run_id_env) or "").strip() if profile.run_id_env else ""
    spec = agent_spec(
        profile,
        scope,
        argv[1:],
        env,
        image=image,
        name=f"heym-{profile.agent}-{run_id or uuid.uuid4().hex}",
        kubernetes=kubernetes,
        cwd=cwd,
    )
    if kubernetes:
        return _run_kubernetes(manager, spec, (scope.workspace, scope.home))
    return _run_docker(manager, spec)


def _run_docker(manager: SandboxManager, spec: SandboxSpec) -> int:
    command = manager.process_command(spec)
    try:
        process = subprocess.Popen(command.argv, stdin=sys.stdin)
    except FileNotFoundError:
        print("Docker CLI is not installed or not on PATH", file=sys.stderr)
        return 127

    # ``docker run`` is only a client: killing it leaves the container running.
    def _stop(signum: int, _frame: object) -> None:
        manager.force_remove(spec.name)
        process.terminate()
        raise SystemExit(128 + signum)

    for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(caught, _stop)
        except (OSError, ValueError):
            pass
    try:
        return process.wait()
    finally:
        manager.force_remove(spec.name)


def _open_to_sandbox_user(root: Path) -> None:
    """The pod runs as 65534 (or an OpenShift-assigned uid); the backend wrote these as root."""

    def widen(path: str, directory: bool) -> None:
        try:
            info = os.lstat(path)
        except OSError:
            return
        if stat.S_ISLNK(info.st_mode):
            return
        executable = directory or bool(info.st_mode & 0o111)
        mode = stat.S_IMODE(info.st_mode) | 0o666 | (0o111 if executable else 0)
        try:
            os.chmod(path, mode)
        except OSError:
            pass

    widen(str(root), True)
    for current, dirs, files in os.walk(root):
        for name in dirs:
            widen(os.path.join(current, name), True)
        for name in files:
            widen(os.path.join(current, name), False)


def _run_kubernetes(manager: SandboxManager, spec: SandboxSpec, run_dirs: tuple[Path, Path]) -> int:
    from app.services.sandbox.kubernetes import process

    if not manager.available():
        reason = getattr(manager.backend, "unavailable_reason", "") or "unknown reason"
        print(f"The Kubernetes sandbox backend is unavailable: {reason}", file=sys.stderr)
        return 127
    for directory in run_dirs:
        _open_to_sandbox_user(directory)
    backend = manager.backend
    return process.run_attached(
        backend.client,
        backend.manifest(spec, None),
        start_gate=spec.start_gate,
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
