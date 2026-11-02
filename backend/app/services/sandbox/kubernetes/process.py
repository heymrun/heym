"""Bridge this process's stdin/stdout/stderr to a sandbox pod.

MCP stdio on Kubernetes spawns ``python -m app.services.sandbox.kubernetes.process``
with the pod manifest and API connection in ``HEYM_SANDBOX_PROCESS_SPEC``. The Codex
and OpenCode wrapper calls :func:`run_attached` directly.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from typing import Any, BinaryIO

from websockets.exceptions import ConnectionClosed

from app.services.sandbox.kubernetes.attach import (
    STATUS,
    STDERR,
    STDOUT,
    AttachSession,
    exit_code_from_status,
    open_attach,
)
from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig
from app.services.sandbox.kubernetes.lifecycle import wait_started, wait_terminated
from app.services.sandbox.spec import START_FAILURE_RETURNCODE

PROCESS_SPEC_ENV = "HEYM_SANDBOX_PROCESS_SPEC"
_pump: threading.Thread | None = None


def _delete(client: KubeClient, name: str) -> None:
    try:
        client.delete_pod(name)
    except (KubeApiError, OSError):
        pass


def _pump_stdin(stdin: BinaryIO, session: AttachSession) -> None:
    try:
        while True:
            chunk = stdin.read1(65536) if hasattr(stdin, "read1") else stdin.read(65536)
            if not chunk:
                break
            session.send_stdin(chunk)
        session.close_stdin()
    except (OSError, ConnectionClosed):
        pass


def join_stdin_pump(timeout: float = 5.0) -> None:
    """Wait for the stdin pump (tests)."""
    if _pump is not None:
        _pump.join(timeout)


def run_attached(
    client: KubeClient,
    manifest: dict[str, Any],
    *,
    start_gate: bool,
    stdin: BinaryIO,
    stdout: BinaryIO,
    stderr: BinaryIO,
) -> int:
    """Create the pod, bridge stdio until it exits, delete it; return its exit code."""
    global _pump
    name = str(manifest["metadata"]["name"])

    def _stop(signum: int, _frame: object) -> None:
        _delete(client, name)
        raise SystemExit(128 + signum)

    for caught in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(caught, _stop)
        except (OSError, ValueError):
            pass

    client.create_pod(manifest)
    try:
        started = wait_started(client, name)
        if started.state == "failed":
            stderr.write(f"kubernetes: {started.reason}\n".encode())
            stderr.flush()
            return START_FAILURE_RETURNCODE
        status_code: int | None = None
        if started.state == "running":
            session = open_attach(client, name)
            try:
                if start_gate:
                    session.send_stdin(b"\n")
                _pump = threading.Thread(target=_pump_stdin, args=(stdin, session), daemon=True)
                _pump.start()
                while True:
                    frame = session.receive(timeout=None)
                    if frame is None:
                        break
                    channel, payload = frame
                    if channel == STDOUT:
                        stdout.write(payload)
                        stdout.flush()
                    elif channel == STDERR:
                        stderr.write(payload)
                        stderr.flush()
                    elif channel == STATUS:
                        status_code = exit_code_from_status(payload)
            finally:
                session.close()
        finished = wait_terminated(client, name)
        code = finished.code if finished.code is not None else status_code
        return code if code is not None else 1
    finally:
        _delete(client, name)


def main() -> int:
    """Entry point of ``python -m app.services.sandbox.kubernetes.process``."""
    payload = json.loads(os.environ[PROCESS_SPEC_ENV])
    client = KubeClient(KubeConfig.from_dict(payload["kube"]))
    return run_attached(
        client,
        payload["manifest"],
        start_gate=bool(payload.get("start_gate")),
        stdin=sys.stdin.buffer,
        stdout=sys.stdout.buffer,
        stderr=sys.stderr.buffer,
    )


if __name__ == "__main__":
    raise SystemExit(main())
