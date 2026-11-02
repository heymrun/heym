"""Map a backend path to the PersistentVolumeClaim behind it.

The Kubernetes counterpart of inspecting the backend container's Docker mounts: the
backend pod's own volumeMounts say which claim holds a path, so a sandbox pod can
mount exactly that subPath and nothing above it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.services.sandbox.errors import SandboxConfigError
from app.services.sandbox.kubernetes.client import KubeClient
from app.services.sandbox.kubernetes.pod import PodVolume
from app.services.sandbox.spec import OperatorMount


@dataclass(frozen=True)
class ClaimMount:
    """One PVC mount of the backend pod."""

    mount_path: str
    claim: str
    sub_path: str


def claim_mounts(pod: dict[str, Any]) -> list[ClaimMount]:
    """Every PVC the backend pod mounts, with where and which subPath."""
    spec = pod.get("spec") or {}
    claims = {
        volume.get("name"): (volume.get("persistentVolumeClaim") or {}).get("claimName")
        for volume in spec.get("volumes") or []
        if volume.get("persistentVolumeClaim")
    }
    mounts: list[ClaimMount] = []
    for container in spec.get("containers") or []:
        for mount in container.get("volumeMounts") or []:
            claim = claims.get(mount.get("name"))
            if claim:
                mounts.append(
                    ClaimMount(
                        mount_path=str(mount.get("mountPath") or "").rstrip("/") or "/",
                        claim=str(claim),
                        sub_path=str(mount.get("subPath") or "").strip("/"),
                    )
                )
    return mounts


def resolve_volume(
    mounts: list[ClaimMount], host_path: Path, target: str, readonly: bool
) -> PodVolume:
    """The claim and subPath holding ``host_path``; never a whole claim."""
    host = PurePosixPath(host_path).as_posix()
    best: ClaimMount | None = None
    for mount in mounts:
        prefix = mount.mount_path.rstrip("/") + "/"
        if host == mount.mount_path or host.startswith(prefix):
            if best is None or len(mount.mount_path) > len(best.mount_path):
                best = mount
    if best is None:
        raise SandboxConfigError(
            f"{host} is not on a PersistentVolumeClaim the backend pod mounts, so a sandbox pod "
            "cannot see it. Mount a claim at the workspace directory (see deploy/kubernetes)."
        )
    rel = host[len(best.mount_path) :].strip("/")
    if not rel:
        raise SandboxConfigError(f"refusing to mount the whole claim {best.claim} into a sandbox")
    if ".." in PurePosixPath(rel).parts:
        raise SandboxConfigError(f"{host} escapes its claim")
    sub_path = "/".join(part for part in (best.sub_path, rel) if part)
    return PodVolume(claim=best.claim, sub_path=sub_path, target=target, readonly=readonly)


def operator_volume(mount: OperatorMount) -> PodVolume:
    """The MCP files mount on Kubernetes: a claim, never a host path."""
    if mount.host_dir or not mount.volume:
        raise SandboxConfigError(
            "HEYM_MCP_STDIO_FILES_HOST_DIR names a host directory, and Kubernetes sandboxes never "
            "mount host paths. Set HEYM_MCP_STDIO_FILES_VOLUME to a PersistentVolumeClaim name."
        )
    return PodVolume(
        claim=mount.volume,
        sub_path=(mount.subpath or "").strip("/"),
        target=mount.target,
        readonly=not mount.writable,
    )


def placement_node(
    client: KubeClient, claims: set[str], self_pod: dict[str, Any] | None
) -> str | None:
    """None when every claim is ReadWriteMany; else the backend's node (ReadWriteOnce)."""
    node: str | None = None
    for claim in sorted(claims):
        pvc = client.get_pvc(claim)
        if pvc is None:
            raise SandboxConfigError(
                f"PersistentVolumeClaim {claim} does not exist in namespace {client.namespace}. "
                "A separate sandbox namespace needs its own claim on the same share "
                "(see deploy/kubernetes/README.md)."
            )
        modes = set(
            (pvc.get("status") or {}).get("accessModes")
            or (pvc.get("spec") or {}).get("accessModes")
            or []
        )
        if "ReadWriteMany" in modes:
            continue
        if "ReadWriteOncePod" in modes:
            raise SandboxConfigError(
                f"PersistentVolumeClaim {claim} is ReadWriteOncePod, so no sandbox pod can mount "
                "it next to the backend. Use ReadWriteMany, or ReadWriteOnce on one node."
            )
        node = ((self_pod or {}).get("spec") or {}).get("nodeName")
        if not node:
            raise SandboxConfigError(
                f"PersistentVolumeClaim {claim} is ReadWriteOnce, so sandboxes must run on the "
                "backend's node, and that node is unknown."
            )
    return node
