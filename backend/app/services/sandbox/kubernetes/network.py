"""Prove that pods labeled ``heym.run/network=none`` really have no network.

On Kubernetes "no network" is a NetworkPolicy, and a policy does nothing on a CNI
that does not enforce it. Before the first offline sandbox, a canary pod with the
same label tries to reach the API server and the internet. Any connection means the
policy is missing or not enforced, and offline sandboxes fail closed.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.spec import SandboxResult, SandboxSpec, Tmpfs

CANARY_SCRIPT = (
    "import os,socket,sys\n"
    "targets=[(os.environ.get('KUBERNETES_SERVICE_HOST',''),"
    "int(os.environ.get('KUBERNETES_SERVICE_PORT') or 443)),('1.1.1.1',443)]\n"
    "for host,port in targets:\n"
    "    if not host:\n"
    "        continue\n"
    "    try:\n"
    "        socket.create_connection((host,port),timeout=3).close()\n"
    "    except OSError:\n"
    "        continue\n"
    "    sys.exit(1)\n"
    "sys.exit(0)\n"
)
_CANARY_TIMEOUT_SECONDS = 30.0

Runner = Callable[[SandboxSpec, str | None, float], SandboxResult]


class OfflineCheck:
    """Runs the canary once per process; a failure is retried on the next offline run."""

    def __init__(self, run: Runner) -> None:
        self._run = run
        self._verified = False
        self._lock = threading.Lock()

    def ensure(self, image: str) -> None:
        """Return when offline pods are offline; raise SandboxConfigError otherwise."""
        with self._lock:
            if self._verified:
                return
            spec = SandboxSpec(
                site="network-canary",
                name=f"heym-netcheck-{uuid.uuid4().hex}",
                image=image,
                entrypoint="python",
                args=("-c", CANARY_SCRIPT),
                network="none",
                tmpfs=(Tmpfs("/tmp", "rw,nosuid", "16m"),),
                memory="64m",
                cpus="0.5",
            )
            result = self._run(spec, None, _CANARY_TIMEOUT_SECONDS)
            if result.returncode == 0:
                self._verified = True
                return
            if result.returncode == 1:
                raise SandboxConfigError(
                    "Sandbox pods labeled heym.run/network=none can still open network "
                    "connections, so the NetworkPolicy that denies their egress is missing or "
                    "not enforced. Apply deploy/kubernetes/base/networkpolicies.yaml on a CNI "
                    "that enforces NetworkPolicy; offline sandboxes stay off until then."
                )
            raise SandboxConfigError(
                f"The sandbox network check did not run (exit {result.returncode}): "
                f"{result.stderr.strip()[:300]}"
            )
