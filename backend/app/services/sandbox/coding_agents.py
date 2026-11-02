"""Run scope and sandbox spec for the Codex and OpenCode runners.

A run sees exactly two directories of its workspace volume: its workspace
``<root>/<id>`` and its home ``<root>/<id><home_suffix>``. Never the volume root,
never another run. Standard library only: the wrapper shims import this module.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.services.sandbox.spec import DockerVolumeSource, SandboxSpec, Tmpfs, WorkspaceMount

_PROXY_AND_CA: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "all_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)
# The pod runs as 65534 against a tree the backend cloned as root.
_GIT_SAFE_DIRECTORY: tuple[str, ...] = (
    "GIT_CONFIG_COUNT=1",
    "GIT_CONFIG_KEY_0=safe.directory",
    "GIT_CONFIG_VALUE_0=*",
)
# Bubblewrap inside the Codex container needs these on Docker (see the wrapper's history).
_CODEX_DOCKER_PRIVILEGES: tuple[str, ...] = (
    "--cap-add",
    "SYS_ADMIN",
    "--security-opt",
    "seccomp=unconfined",
    "--security-opt",
    "apparmor=unconfined",
    "--security-opt",
    "systempaths=unconfined",
)
DEADLINE_ENV = "HEYM_SANDBOX_DEADLINE_SECONDS"


class RunScopeError(ValueError):
    """The runner was asked to start outside a single run's own directories."""


@dataclass(frozen=True)
class AgentProfile:
    """Everything that differs between the Codex and OpenCode runners."""

    agent: str
    label: str
    env_prefix: str
    default_root: str
    home_suffix: str
    home_env: str
    entrypoint: str
    run_id_env: str | None
    forward_env: tuple[str, ...]


CODEX = AgentProfile(
    agent="codex",
    label="Codex",
    env_prefix="HEYM_CODEX",
    default_root="/app/data/codex-workspaces",
    home_suffix=".codex-home",
    home_env="CODEX_HOME",
    entrypoint="codex",
    run_id_env=None,
    forward_env=("CODEX_ACCESS_TOKEN", *_PROXY_AND_CA, "CODEX_CA_CERTIFICATE"),
)
OPENCODE = AgentProfile(
    agent="opencode",
    label="OpenCode",
    env_prefix="HEYM_OPENCODE",
    default_root="/app/data/opencode-workspaces",
    home_suffix=".oc-home",
    home_env="HOME",
    entrypoint="opencode",
    run_id_env="HEYM_OPENCODE_RUN_ID",
    forward_env=_PROXY_AND_CA,
)
PROFILES: dict[str, AgentProfile] = {"codex": CODEX, "opencode": OPENCODE}


@dataclass(frozen=True)
class RunScope:
    """The two directories one run may see."""

    root: Path
    run_id: str
    workspace: Path
    home: Path


def _value(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def run_scope(profile: AgentProfile, cwd: Path, env: Mapping[str, str]) -> RunScope:
    """The run the runner was started for, or :class:`RunScopeError`."""
    root = Path(_value(env, f"{profile.env_prefix}_WORKSPACE_DIR") or profile.default_root).resolve()
    here = cwd.resolve()
    try:
        rel = here.relative_to(root)
    except ValueError:
        raise RunScopeError(
            f"{profile.label} runner cwd {here} is outside "
            f"{profile.env_prefix}_WORKSPACE_DIR {root}"
        ) from None
    if not rel.parts:
        raise RunScopeError(
            f"{profile.label} runner cwd is the workspace root {root}; a run starts in its own "
            "workspace"
        )
    run_id = rel.parts[0]
    if run_id.startswith(".") or run_id.endswith(profile.home_suffix):
        raise RunScopeError(f"{profile.label} runner cwd {here} is not a run workspace")
    workspace = root / run_id
    home = root / f"{run_id}{profile.home_suffix}"
    raw_home = _value(env, profile.home_env)
    if not raw_home:
        raise RunScopeError(
            f"{profile.home_env} is not set; the {profile.label} runner mounts only the run's "
            f"own home {home}"
        )
    if Path(raw_home).resolve() != home:
        raise RunScopeError(f"{profile.home_env}={raw_home} is not this run's home {home}")
    for directory in (workspace, home):
        if not directory.is_dir():
            raise RunScopeError(f"{directory} does not exist")
    return RunScope(root=root, run_id=run_id, workspace=workspace, home=home)
