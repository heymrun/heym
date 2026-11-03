"""Carry the CA files the backend trusts into a sandbox, read-only at the same path.

The CA variables already cross into sandboxes (``env.py``), but the file they name
usually exists only in the backend (a Secret or ConfigMap mount, or a host file).
A containerized backend copies it onto the shared workspace volume, where the
sandbox can mount it; a backend on the host binds the file itself.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from pathlib import Path

from app.services.sandbox.spec import DockerVolumeSource, SandboxSpec, WorkspaceMount

logger = logging.getLogger(__name__)

CA_FILE_VARIABLES = frozenset(
    {
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "CODEX_CA_CERTIFICATE",
    }
)
_CA_SUBDIR = "_ca"
_DEFAULT_WORKSPACE_ROOT = "/app/data/codex-workspaces"


def ca_files(env: tuple[str, ...]) -> list[str]:
    """Existing absolute files named by the CA variables in ``env``, without repeats."""
    paths: list[str] = []
    for item in env:
        key, sep, value = item.partition("=")
        if not sep or key not in CA_FILE_VARIABLES or not value.startswith("/"):
            continue
        if value not in paths and os.path.isfile(value):
            paths.append(value)
    return paths


def workspace_root() -> Path:
    """Where the shared workspace volume is mounted in the backend."""
    return Path(os.environ.get("HEYM_CODEX_WORKSPACE_DIR", "").strip() or _DEFAULT_WORKSPACE_ROOT)


def _copy_to_workspace(path: str) -> Path:
    data = Path(path).read_bytes()
    directory = workspace_root() / _CA_SUBDIR / hashlib.sha256(data).hexdigest()[:16]
    target = directory / Path(path).name
    if target.is_file():
        return target
    directory.mkdir(parents=True, exist_ok=True)
    for folder in (directory.parent, directory):
        os.chmod(folder, 0o755)
    partial = directory / f".{uuid.uuid4().hex}.partial"
    partial.write_bytes(data)
    os.chmod(partial, 0o644)
    os.replace(partial, target)
    return target


def ca_mounts(spec: SandboxSpec, *, shared_workspace: bool) -> list[WorkspaceMount]:
    """One read-only mount per CA file the spec's environment names."""
    taken = {mount.target for mount in spec.workspace_mounts}
    root = workspace_root()
    mounts: list[WorkspaceMount] = []
    for path in ca_files(spec.env):
        if path in taken:
            continue
        try:
            source = _copy_to_workspace(path) if shared_workspace else Path(path)
        except OSError as exc:
            logger.warning("CA file %s stays out of sandbox %s: %s", path, spec.name, exc)
            continue
        mounts.append(
            WorkspaceMount(
                host_path=source,
                target=path,
                readonly=True,
                docker=DockerVolumeSource(
                    mount_point=root,
                    volume_env=("HEYM_CODEX_DOCKER_WORKSPACE_VOLUME",),
                    missing_message=(
                        f"CA files reach sandboxes through the workspace volume at {root}."
                    ),
                    native_bind=not shared_workspace,
                    label="CA file",
                ),
            )
        )
    return mounts
