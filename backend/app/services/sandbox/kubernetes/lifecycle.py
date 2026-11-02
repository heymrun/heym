"""Waiting for a sandbox pod to start and to finish."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.sandbox.kubernetes.client import CONTAINER, KubeClient
from app.services.sandbox.spec import OOM_RETURNCODE

STARTUP_TIMEOUT_SECONDS = 120.0
_POLL_SECONDS = 0.25
_FAILED_WAITING = frozenset(
    {
        "ErrImagePull",
        "ImagePullBackOff",
        "InvalidImageName",
        "ErrImageNeverPull",
        "CreateContainerConfigError",
        "CreateContainerError",
        "RunContainerError",
    }
)
_FAILED_TERMINATED = frozenset({"StartError", "ContainerCannotRun"})


@dataclass(frozen=True)
class PodStart:
    """``running``, ``terminated`` (finished before attach) or ``failed`` (never started)."""

    state: str
    reason: str = ""


@dataclass(frozen=True)
class PodExit:
    """Exit code of the sandbox container; None when it could not be read."""

    code: int | None
    reason: str = ""


def _state(pod: dict[str, Any]) -> dict[str, Any]:
    for status in (pod.get("status") or {}).get("containerStatuses") or []:
        if status.get("name") == CONTAINER:
            return status.get("state") or {}
    return {}


def wait_started(
    client: KubeClient,
    name: str,
    *,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PodStart:
    """Poll until the container runs, finishes, or provably cannot start."""
    deadline = clock() + timeout
    last_reason = "the pod was not scheduled"
    while clock() < deadline:
        pod = client.get_pod(name)
        if pod is None:
            return PodStart("failed", "the pod disappeared before it started")
        state = _state(pod)
        if "running" in state:
            return PodStart("running")
        terminated = state.get("terminated")
        if terminated is not None:
            reason = str(terminated.get("reason") or "")
            if reason in _FAILED_TERMINATED:
                return PodStart("failed", f"{reason}: {terminated.get('message', '')}".strip())
            return PodStart("terminated")
        waiting = state.get("waiting") or {}
        if waiting.get("reason") in _FAILED_WAITING:
            return PodStart("failed", f"{waiting['reason']}: {waiting.get('message', '')}".strip())
        status = pod.get("status") or {}
        if status.get("phase") == "Failed":
            return PodStart("failed", str(status.get("reason") or "the pod failed"))
        for condition in status.get("conditions") or []:
            if condition.get("type") == "PodScheduled" and condition.get("status") == "False":
                last_reason = (
                    f"{condition.get('reason', 'Unschedulable')}: {condition.get('message', '')}"
                ).strip()
        sleep(_POLL_SECONDS)
    return PodStart("failed", f"the pod did not start within {timeout:.0f} seconds ({last_reason})")


def wait_terminated(
    client: KubeClient,
    name: str,
    *,
    timeout: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> PodExit:
    """Poll until the container reports its exit code."""
    deadline = clock() + timeout
    while clock() < deadline:
        pod = client.get_pod(name)
        if pod is None:
            return PodExit(None, "the pod disappeared")
        terminated = _state(pod).get("terminated")
        if terminated is not None:
            reason = str(terminated.get("reason") or "")
            if reason == "OOMKilled":
                return PodExit(OOM_RETURNCODE, reason)
            code = terminated.get("exitCode")
            return PodExit(int(code) if code is not None else None, reason)
        sleep(_POLL_SECONDS)
    return PodExit(None, "the pod did not finish")
