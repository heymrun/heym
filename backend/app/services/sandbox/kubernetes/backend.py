"""Kubernetes backend: one restricted pod per sandbox run, through the API."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from websockets.exceptions import InvalidHandshake

from app.services.sandbox.errors import SandboxConfigError, SandboxTimeoutError
from app.services.sandbox.kubernetes.attach import AttachSession, exchange, open_attach
from app.services.sandbox.kubernetes.client import KubeApiError, KubeClient
from app.services.sandbox.kubernetes.config import KubeConfig, KubeConfigError
from app.services.sandbox.kubernetes.lifecycle import wait_started, wait_terminated
from app.services.sandbox.kubernetes.network import OfflineCheck
from app.services.sandbox.kubernetes.pod import (
    OVERRIDES_ENV,
    PodContext,
    PodVolume,
    build_pod,
    parse_overrides,
)
from app.services.sandbox.kubernetes.workspace import (
    claim_mounts,
    operator_volume,
    placement_node,
    resolve_volume,
)
from app.services.sandbox.spec import (
    START_FAILURE_RETURNCODE,
    ProcessCommand,
    SandboxResult,
    SandboxSpec,
)

logger = logging.getLogger(__name__)

MIN_MINOR_VERSION = 30
ONE_SHOT_DEADLINE_GRACE_SECONDS = 30
BACKEND_ROOT = Path(__file__).resolve().parents[4]
PROCESS_SPEC_ENV = "HEYM_SANDBOX_PROCESS_SPEC"
_REQUIRED_ACCESS = (
    ("create", "pods", ""),
    ("get", "pods", ""),
    ("delete", "pods", ""),
    ("create", "pods", "attach"),
)


class KubernetesBackend:
    """Runs each sandbox as a pod in the sandbox namespace."""

    name = "kubernetes"

    def __init__(
        self, config: KubeConfig, *, client: KubeClient | None = None, instance: str | None = None
    ) -> None:
        self.config = config
        self._client = client or KubeClient(config)
        self._instance = instance or socket.gethostname()
        self._lock = threading.Lock()
        self._available: bool | None = None
        self._context: PodContext | None = None
        self._self_pod: dict[str, Any] | None = None
        self._offline = OfflineCheck(self._run_pod)
        self._placements: dict[frozenset[str], str | None] = {}
        self.unavailable_reason = ""

    @property
    def client(self) -> KubeClient:
        """The API client (the janitor uses it)."""
        return self._client

    def available(self) -> bool:
        """API reachable, version 1.30+, RBAC in place, overrides valid (probed once)."""
        with self._lock:
            if self._available is None:
                self._available = self._probe()
            return self._available

    def _probe(self) -> bool:
        try:
            major, minor = self._client.server_version()
            if (major, minor) < (1, MIN_MINOR_VERSION):
                return self._unavailable(
                    f"Kubernetes {major}.{minor} is too old; sandbox attach needs "
                    f"1.{MIN_MINOR_VERSION} or newer"
                )
            for verb, resource, subresource in _REQUIRED_ACCESS:
                if not self._client.can_i(verb, resource, subresource):
                    target = f"{resource}/{subresource}" if subresource else resource
                    return self._unavailable(
                        f"the backend's ServiceAccount may not {verb} {target} in namespace "
                        f"{self._client.namespace}"
                    )
            self._context = self._build_context()
        except (KubeApiError, KubeConfigError, SandboxConfigError, httpx.HTTPError, OSError) as exc:
            return self._unavailable(str(exc))
        return True

    def _unavailable(self, reason: str) -> bool:
        self.unavailable_reason = reason
        logger.warning("Kubernetes sandbox backend unavailable: %s", reason)
        return False

    def _build_context(self) -> PodContext:
        return PodContext(
            instance=self._instance,
            openshift=self._client.has_api_group("security.openshift.io"),
            overrides=parse_overrides(os.environ.get(OVERRIDES_ENV)),
        )

    def pod_context(self) -> PodContext:
        """Instance, OpenShift detection and validated overrides."""
        if self._context is None:
            self._context = self._build_context()
        return self._context

    def self_pod(self) -> dict[str, Any] | None:
        """The backend's own pod (in-cluster only)."""
        if not self.config.in_cluster:
            return None
        if self._self_pod is None:
            self._self_pod = self._client.get_pod(
                self._instance, namespace=self.config.own_namespace
            )
        return self._self_pod

    def resolve_image(self) -> str | None:
        """The backend pod's image, when the pod has exactly one container."""
        containers = ((self.self_pod() or {}).get("spec") or {}).get("containers") or []
        if len(containers) == 1:
            return containers[0].get("image")
        return None

    def pod_volumes(self, spec: SandboxSpec) -> tuple[tuple[PodVolume, ...], str | None]:
        """Workspace and operator mounts as PVC subPaths, plus the node to pin to (if any)."""
        volumes: list[PodVolume] = []
        if spec.workspace_mounts:
            mounts = claim_mounts(self.self_pod() or {})
            volumes.extend(
                resolve_volume(mounts, mount.host_path, mount.target, mount.readonly)
                for mount in spec.workspace_mounts
            )
        if spec.operator_mount is not None:
            volumes.append(operator_volume(spec.operator_mount))
        if not volumes:
            return (), None
        claims = frozenset(volume.claim for volume in volumes)
        if claims not in self._placements:
            self._placements[claims] = placement_node(self._client, set(claims), self.self_pod())
        return tuple(volumes), self._placements[claims]

    def manifest(self, spec: SandboxSpec, timeout_seconds: float | None) -> dict[str, Any]:
        """The pod manifest for ``spec``; one-shot runs get a deadline from their timeout."""
        if spec.deadline_seconds is None and timeout_seconds is not None:
            spec = replace(spec, deadline_seconds=timeout_seconds + ONE_SHOT_DEADLINE_GRACE_SECONDS)
        volumes, node = self.pod_volumes(spec)
        context = self.pod_context()
        if node:
            context = replace(context, node_name=node)
        return build_pod(spec, context, volumes)

    def run(self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float) -> SandboxResult:
        """Run one pod to completion. Offline specs need a passing network canary first."""
        if spec.offline:
            self._offline.ensure(spec.image)
        return self._run_pod(spec, stdin, timeout_seconds)

    def _run_pod(
        self, spec: SandboxSpec, stdin: str | None, timeout_seconds: float
    ) -> SandboxResult:
        manifest = self.manifest(spec, timeout_seconds)
        self._client.create_pod(manifest)
        try:
            started = wait_started(self._client, spec.name)
            if started.state == "failed":
                return SandboxResult(START_FAILURE_RETURNCODE, "", f"kubernetes: {started.reason}")
            stdout, stderr, status_code = b"", b"", None
            attached = False
            if started.state == "running":
                session = self._attach(spec.name)
                if session is not None:
                    attached = True
                    try:
                        stdout, stderr, status_code = exchange(
                            session,
                            stdin.encode("utf-8") if stdin is not None else None,
                            time.monotonic() + timeout_seconds,
                        )
                    except TimeoutError:
                        raise SandboxTimeoutError(
                            f"sandbox pod {spec.name} ran past {timeout_seconds:.0f} seconds"
                        ) from None
                    finally:
                        session.close()
            finished = wait_terminated(self._client, spec.name)
            if not attached and not stdout:
                stdout = self._client.pod_log(spec.name).encode("utf-8")
            code = finished.code if finished.code is not None else status_code
            if code is None:
                raise RuntimeError(
                    f"sandbox pod {spec.name} finished without an exit status ({finished.reason})"
                )
            return SandboxResult(
                code,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        finally:
            self.force_remove(spec.name)

    def _attach(self, name: str) -> AttachSession | None:
        """Attach, or None when the container finished before the attach arrived."""
        try:
            return open_attach(self._client, name)
        except (InvalidHandshake, OSError) as exc:
            logger.info("Attach to sandbox pod %s failed (%s); reading its log instead", name, exc)
            return None

    def process_command(self, spec: SandboxSpec) -> ProcessCommand:
        """The bridge command for callers that spawn the sandbox (MCP stdio)."""
        if spec.offline:
            self._offline.ensure(spec.image)
        payload = {
            "kube": self.config.to_dict(),
            "manifest": self.manifest(spec, None),
            "start_gate": spec.start_gate,
        }
        return ProcessCommand(
            argv=[sys.executable, "-m", "app.services.sandbox.kubernetes.process"],
            env={PROCESS_SPEC_ENV: json.dumps(payload), "PYTHONPATH": str(BACKEND_ROOT)},
            name=spec.name,
        )

    def force_remove(self, name: str | None) -> None:
        """Delete a sandbox pod now; failures are logged, never raised."""
        if not name:
            return
        try:
            self._client.delete_pod(name)
        except (KubeApiError, httpx.HTTPError, OSError) as exc:
            logger.warning("Could not delete sandbox pod %s: %s", name, exc)

    def uses_shared_workspace(self) -> bool:
        """Workspaces always live on the shared PVC on Kubernetes."""
        return True
