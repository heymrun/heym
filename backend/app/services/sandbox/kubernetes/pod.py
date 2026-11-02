"""``SandboxSpec`` -> Pod manifest. Pure: no I/O.

Whatever the spec asks for, the pod is Pod Security ``restricted``: non-root, no
capabilities, no privilege escalation, RuntimeDefault seccomp, and no
ServiceAccount token. Docker-only fields (``docker_extra_args``, ``cap_drop_all``,
``no_new_privileges``) are ignored here on purpose.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.client import CONTAINER
from app.services.sandbox.spec import SandboxSpec

LABEL_MANAGED_BY = "app.kubernetes.io/managed-by"
LABEL_SITE = "heym.run/sandbox"
LABEL_NETWORK = "heym.run/network"
LABEL_INSTANCE = "heym.run/instance"
MANAGED_BY = "heym"
DEFAULT_UID = 65534
PROCESS_DEADLINE_SECONDS = 24 * 3600
OVERRIDES_ENV = "HEYM_SANDBOX_K8S_POD_OVERRIDES"
START_GATE_SCRIPT = 'head -c1 >/dev/null; exec "$@"'
_ALLOWED_OVERRIDES = frozenset(
    {"nodeSelector", "tolerations", "runtimeClassName", "imagePullSecrets", "priorityClassName"}
)
_LABEL_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_SIZE = re.compile(r"(\d+(?:\.\d+)?)([bkmgBKMG]?)")


@dataclass(frozen=True)
class PodVolume:
    """One path inside a PersistentVolumeClaim, mounted at ``target``."""

    claim: str
    sub_path: str
    target: str
    readonly: bool


@dataclass(frozen=True)
class PodContext:
    """Per-backend facts every pod needs."""

    instance: str
    openshift: bool = False
    overrides: dict[str, Any] = field(default_factory=dict, hash=False)
    node_name: str | None = None


def parse_overrides(raw: str | None) -> dict[str, Any]:
    """Validate ``HEYM_SANDBOX_K8S_POD_OVERRIDES``: scheduling keys only."""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SandboxConfigError(f"{OVERRIDES_ENV} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SandboxConfigError(f"{OVERRIDES_ENV} must be a JSON object")
    refused = sorted(set(data) - _ALLOWED_OVERRIDES)
    if refused:
        raise SandboxConfigError(
            f"{OVERRIDES_ENV} may only set {', '.join(sorted(_ALLOWED_OVERRIDES))}; "
            f"refused: {', '.join(refused)}"
        )
    return data


def quantity(docker_size: str) -> str:
    """Docker size (``512m``, ``1g``, ``64k``, ``1024``) as a Kubernetes quantity."""
    match = _SIZE.fullmatch(docker_size.strip())
    if not match:
        raise SandboxConfigError(f"cannot convert size {docker_size!r} to a Kubernetes quantity")
    number, unit = match.groups()
    return number + {"": "", "b": "", "k": "Ki", "m": "Mi", "g": "Gi"}[unit.lower()]


def run_as(user: str | None) -> tuple[int, int]:
    """``UID[:GID]`` as numbers; anything else, and root, becomes 65534."""
    if not user:
        return DEFAULT_UID, DEFAULT_UID
    uid_text, _, gid_text = user.partition(":")
    try:
        uid = int(uid_text)
        gid = int(gid_text) if gid_text else uid
    except ValueError:
        return DEFAULT_UID, DEFAULT_UID
    if uid <= 0 or gid <= 0:
        return DEFAULT_UID, DEFAULT_UID
    return uid, gid


def env_entries(items: tuple[str, ...]) -> list[dict[str, str]]:
    """``KEY=value`` items as pod env. Bare keys are dropped and the last value wins, as in Docker."""
    values: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            continue
        values.pop(key, None)
        values[key] = value
    if "HOME" not in values:
        values["HOME"] = "/tmp"
    return [{"name": key, "value": value} for key, value in values.items()]


def _label(value: str) -> str:
    return _LABEL_UNSAFE.sub("-", value)[:63].strip("-.") or "unknown"


def _command(spec: SandboxSpec) -> tuple[list[str] | None, list[str]]:
    if spec.start_gate:
        if spec.entrypoint is None:
            raise SandboxConfigError("a start gate needs an explicit entrypoint")
        return ["sh", "-c", START_GATE_SCRIPT, "--", spec.entrypoint], list(spec.args)
    if spec.entrypoint is None:
        return None, list(spec.args)
    return [spec.entrypoint], list(spec.args)


def _resources(spec: SandboxSpec) -> dict[str, dict[str, str]]:
    limits: dict[str, str] = {}
    requests: dict[str, str] = {}
    if spec.memory:
        limits["memory"] = requests["memory"] = quantity(spec.memory)
    if spec.cpus:
        limits["cpu"] = spec.cpus
        requests["cpu"] = "100m"
    return {"limits": limits, "requests": requests} if limits else {}


def build_pod(
    spec: SandboxSpec, ctx: PodContext, volumes: tuple[PodVolume, ...] = ()
) -> dict[str, Any]:
    """The Pod manifest for ``spec``."""
    uid, gid = run_as(spec.user)
    pod_security: dict[str, Any] = {
        "runAsNonRoot": True,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    if not ctx.openshift:
        pod_security.update(runAsUser=uid, runAsGroup=gid)

    pod_volumes: list[dict[str, Any]] = []
    mounts: list[dict[str, Any]] = []
    for index, tmpfs in enumerate(spec.tmpfs):
        name = f"tmpfs-{index}"
        pod_volumes.append(
            {"name": name, "emptyDir": {"medium": "Memory", "sizeLimit": quantity(tmpfs.size)}}
        )
        mounts.append({"name": name, "mountPath": tmpfs.path})
    if spec.shm_size:
        pod_volumes.append(
            {"name": "shm", "emptyDir": {"medium": "Memory", "sizeLimit": quantity(spec.shm_size)}}
        )
        mounts.append({"name": "shm", "mountPath": "/dev/shm"})
    claims: dict[str, str] = {}
    for volume in volumes:
        name = claims.get(volume.claim)
        if name is None:
            name = f"ws-{len(claims)}"
            claims[volume.claim] = name
            pod_volumes.append({"name": name, "persistentVolumeClaim": {"claimName": volume.claim}})
        mount: dict[str, Any] = {"name": name, "mountPath": volume.target}
        if volume.sub_path:
            mount["subPath"] = volume.sub_path
        mount["readOnly"] = volume.readonly
        mounts.append(mount)

    command, args = _command(spec)
    container: dict[str, Any] = {
        "name": CONTAINER,
        "image": spec.image,
        "imagePullPolicy": "IfNotPresent",
        "stdin": True,
        "stdinOnce": True,
        "tty": False,
        "env": env_entries(spec.env),
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": spec.read_only_root,
            "runAsNonRoot": True,
            "capabilities": {"drop": ["ALL"]},
        },
        "volumeMounts": mounts,
    }
    if command is not None:
        container["command"] = command
    if args:
        container["args"] = args
    if spec.workdir:
        container["workingDir"] = spec.workdir
    resources = _resources(spec)
    if resources:
        container["resources"] = resources

    deadline = spec.deadline_seconds or PROCESS_DEADLINE_SECONDS
    pod_spec: dict[str, Any] = {
        "restartPolicy": "Never",
        "automountServiceAccountToken": False,
        "enableServiceLinks": False,
        "activeDeadlineSeconds": int(math.ceil(deadline)),
        "securityContext": pod_security,
        "containers": [container],
        "volumes": pod_volumes,
    }
    pod_spec.update(ctx.overrides)
    if ctx.node_name:
        pod_spec["nodeName"] = ctx.node_name
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": spec.name,
            "labels": {
                LABEL_MANAGED_BY: MANAGED_BY,
                LABEL_SITE: _label(spec.site),
                LABEL_NETWORK: "none" if spec.offline else "egress",
                LABEL_INSTANCE: _label(ctx.instance),
            },
        },
        "spec": pod_spec,
    }
