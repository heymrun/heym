"""Run MCP ``stdio`` servers inside a hardened, throwaway sibling container.

The MCP ``stdio`` transport starts a local process from a caller-supplied command
and speaks JSON-RPC over its stdin/stdout. Unlike the http(s) transports there is
nothing to validate about the target before starting it: the MCP handshake runs
over the child's pipes, so the process must already exist before the protocol can
reject it, and any side effect of the command has fired by then. "Is this really
an MCP server?" can therefore never be a security control (GHSA-378x-q589-34mv).

Heym has no role model, so every caller who can reach the API is equal. Rather
than gating stdio behind a privilege tier that does not exist, this module keeps
the feature fully available and moves the execution into a container:

* the child runs as a throwaway sibling container: non-root, all capabilities
  dropped, ``no-new-privileges``, read-only root filesystem, CPU/memory/PID caps
* **the Docker socket is never exposed to the child**, which is what turned a
  command execution into host root on the socket-mounting compose setup
* only the caller's own env vars reach the child (never ``os.environ``, so
  ``SECRET_KEY`` / ``ENCRYPTION_KEY`` / ``DATABASE_URL`` stay in the backend)

Network access **is** allowed, unlike the Python tool sandbox. MCP servers exist
to reach APIs, and ``npx`` / ``uvx`` must fetch their package to start at all, so
``--network none`` would break every real server rather than harden it. The
boundary here is the container and the missing socket, not egress.

Two command shapes are supported so no existing configuration is lost:

* ``docker run [flags] IMAGE [args]`` - the caller is already asking for a
  container, so we honour that intent by starting ``IMAGE`` ourselves with
  hardened flags, carrying over ``-e`` / ``-w`` / ``--entrypoint``. Flags that
  would dissolve the boundary (``--privileged``, ``--cap-add``, ``--device``,
  ``--security-opt``, ``--network host``, ``--pid/--ipc/--uts host``,
  ``--env-file``, ``--volumes-from``) are refused with a clear message.
* anything else (``npx``, ``uvx``, ``node``, ``python``, a plain binary) - run
  inside a sibling of the backend image, which ships node/npm and uv.

**Caller-supplied mounts are refused outright** (``-v``, ``--volume``,
``--mount``, ``--volumes-from``). Validating a mount source is a losing game:
``//var/run/docker.sock`` survives ``os.path.normpath`` because POSIX preserves
exactly two leading slashes, and relative paths, symlinks and parent directories
each defeat a denylist in their own way. A denylist that has to be right every
time against an attacker who only has to be right once is not a boundary, so
there is no path-comparison surface here at all.

**Nothing is mounted in its place by default either.** The sandbox sees no Heym
storage unless an operator names a volume or directory explicitly, and that mount
is read-only unless they also opt into writes. Auto-mounting application storage
was tried and reverted: the skill/Codex workspace volume holds every tenant's
workspaces, so exposing it to one caller's MCP process is a cross-tenant read.

Mode selection uses ``HEYM_MCP_STDIO_SANDBOX`` and deliberately **not** the
Python tool setting: an operator who selects ``subprocess`` there for Python tool
compatibility must not silently lose MCP stdio isolation as a side effect.
``auto`` (default) requires Docker and fails closed without it, ``docker`` forces
the sandbox, and ``subprocess`` is the explicit trusted/single-user opt-out.
"""

import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field

from app.config import settings
from app.services.sandbox import (
    OperatorMount,
    SandboxSpec,
    Tmpfs,
    get_sandbox_manager,
    reset_sandbox_manager,
)

logger = logging.getLogger(__name__)

# `docker run` flags that take a separate value argument, so the parser knows to
# skip that value when looking for the image name.
_DOCKER_VALUE_FLAGS = frozenset(
    {
        "-e",
        "--env",
        "-v",
        "--volume",
        "-w",
        "--workdir",
        "--name",
        "--entrypoint",
        "--network",
        "--net",
        "--user",
        "-u",
        "--memory",
        "-m",
        "--cpus",
        "--pids-limit",
        "--env-file",
        "--mount",
        "--label",
        "-l",
        "--platform",
        "--add-host",
        "--dns",
        "--cap-add",
        "--cap-drop",
        "--device",
        "--security-opt",
        "--tmpfs",
        "--ulimit",
        "--pid",
        "--ipc",
        "--uts",
        "--privileged",
    }
)

# Flags that would defeat the sandbox. `--privileged` takes no value but is
# listed above too; it is rejected before the value-skipping logic matters.
_DOCKER_REFUSED_FLAGS = {
    "--privileged": "grants the container full host access",
    "--cap-add": "restores Linux capabilities the sandbox drops",
    "--device": "exposes host devices to the container",
    "--security-opt": "can disable the sandbox's seccomp/no-new-privileges settings",
    "--userns": "can map the container back to host root",
    "--pid": "can join the host PID namespace",
    "--ipc": "can join the host IPC namespace",
    "--uts": "can join the host UTS namespace",
    "--mount": "caller-controlled mounts are not accepted; see the -v message",
    "--env-file": "reads a file from the backend host; pass env values explicitly",
    "-v": "caller-controlled bind mounts are not accepted",
    "--volume": "caller-controlled bind mounts are not accepted",
    "--volumes-from": "would inherit another container's mounts, including the socket",
}

# Mount point for the optional, operator-configured file mount. Nothing is
# mounted here unless an operator names a volume or host directory explicitly.
_FILES_MOUNT_PATH = (os.getenv("HEYM_MCP_STDIO_FILES_PATH") or "").strip() or "/mnt/heym-files"

# The only writable path in the sandbox, so also the only usable working directory.
_SANDBOX_TMPFS_PATH = "/tmp"

# Nobody:nogroup. Root in the sandbox is refused even if explicitly configured.
_DEFAULT_SANDBOX_USER = "65534:65534"


class MCPStdioSandboxError(ValueError):
    """Raised when an MCP stdio command cannot be run safely."""


@dataclass
class SandboxedCommand:
    """A rewritten command plus the environment the child should receive."""

    argv: list[str]
    env: dict[str, str] | None
    container_name: str | None = None
    notes: list[str] = field(default_factory=list)


def sandbox_mode() -> str:
    """Resolve the MCP stdio sandbox mode.

    Deliberately reads its own ``HEYM_MCP_STDIO_SANDBOX`` rather than the Python
    tool setting: an operator who selects ``subprocess`` there for Python tool
    compatibility must not silently lose MCP stdio isolation with it. Unknown
    values fall back to ``auto`` (fail-closed) rather than to host execution.
    """
    raw = (
        os.environ.get("HEYM_MCP_STDIO_SANDBOX")
        or getattr(settings, "mcp_stdio_sandbox", "auto")
        or "auto"
    )
    raw = str(raw).strip().lower()
    if raw not in ("auto", "docker", "subprocess"):
        logger.warning("Unknown HEYM_MCP_STDIO_SANDBOX=%r; defaulting to 'auto'", raw)
        return "auto"
    return raw


# Application volumes that must never be auto-mounted into an MCP server. They
# hold every tenant's data, so exposing them to one caller's MCP process is a
# cross-tenant read (and, unmounted read-write, a cross-tenant write).
_NEVER_AUTO_MOUNTED_VOLUME_VARS = (
    "HEYM_SKILL_DOCKER_WORKSPACE_VOLUME",
    "HEYM_CODEX_DOCKER_WORKSPACE_VOLUME",
    "HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME",
)


@dataclass
class _CarriedFlags:
    """What a caller's ``docker run`` may keep: env, workdir and entrypoint."""

    env: list[str] = field(default_factory=list)
    workdir: str | None = None
    entrypoint: str | None = None


def _files_mount() -> OperatorMount | None:
    """The operator-configured files mount, or None. See the module docstring."""
    for var in _NEVER_AUTO_MOUNTED_VOLUME_VARS:
        if os.environ.get(var, "").strip():
            logger.debug(
                "MCP stdio sandbox: ignoring %s; application volumes are never auto-mounted",
                var,
            )
    writable = os.environ.get("HEYM_MCP_STDIO_FILES_WRITABLE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    volume = os.environ.get("HEYM_MCP_STDIO_FILES_VOLUME", "").strip()
    if volume:
        subpath = os.environ.get("HEYM_MCP_STDIO_FILES_SUBPATH", "").strip() or None
        return OperatorMount(
            target=_FILES_MOUNT_PATH, volume=volume, subpath=subpath, writable=writable
        )
    host_dir = os.environ.get("HEYM_MCP_STDIO_FILES_HOST_DIR", "").strip()
    if host_dir:
        return OperatorMount(target=_FILES_MOUNT_PATH, host_dir=host_dir, writable=writable)
    logger.debug("MCP stdio sandbox: no file mount configured; the server sees no Heym files")
    return None


def docker_available() -> bool:
    """True when the sandbox backend (Docker or Kubernetes) can start sandboxes."""
    return get_sandbox_manager().available()


def reset_docker_available_cache() -> None:
    """Forget the selected sandbox backend (used by tests)."""
    reset_sandbox_manager()


def _sandbox_image() -> str | None:
    """Image for non-``docker`` commands (it ships node and uv); None fails closed."""
    return get_sandbox_manager().resolve_image(
        ("HEYM_MCP_STDIO_IMAGE", "HEYM_PYTHON_TOOL_IMAGE", "HEYM_CODEX_DOCKER_IMAGE")
    )


def _mcp_spec(
    *,
    name: str,
    image: str,
    entrypoint: str | None,
    args: list[str],
    workdir: str | None,
    extra_env: list[str],
) -> SandboxSpec:
    """Flags shared by every sandboxed MCP server. ``-i`` carries the protocol.

    The tmpfs at ``/tmp`` is the only writable path. It is ``exec`` so npx/uvx can
    run what they install, and ``HOME`` plus the npm/uv/XDG caches point into it,
    because uid 65534's passwd home does not exist. See the git history of
    ``_hardening_flags`` for why each one was needed.
    """
    return SandboxSpec(
        site="mcp-stdio",
        name=name,
        image=image,
        entrypoint=entrypoint,
        args=tuple(args),
        network="bridge",
        user=_sandbox_user(),
        tmpfs=(
            Tmpfs(
                _SANDBOX_TMPFS_PATH, "rw,exec,nosuid", _tunable("HEYM_MCP_STDIO_TMPFS_SIZE", "512m")
            ),
        ),
        workdir=workdir,
        pids=_tunable("HEYM_MCP_STDIO_PIDS", "256"),
        memory=_tunable("HEYM_MCP_STDIO_MEMORY", "512m"),
        cpus=_tunable("HEYM_MCP_STDIO_CPUS", "2"),
        env=(
            "HOME=/tmp",
            "NPM_CONFIG_CACHE=/tmp/.npm",
            "NPM_CONFIG_UPDATE_NOTIFIER=false",
            "XDG_CACHE_HOME=/tmp/.cache",
            "XDG_DATA_HOME=/tmp/.local/share",
            "UV_CACHE_DIR=/tmp/.uv",
            *extra_env,
        ),
        operator_mount=_files_mount(),
    )


def _tunable(var: str, default: str) -> str:
    """Read a container tuning value, treating set-but-empty as unset.

    ``os.environ.get(var, default)`` returns ``""`` when the variable is present
    but empty, and an empty value is not inert on the docker CLI: ``--user ""``
    starts the container as **uid 0**. Every tunable therefore falls back on
    falsiness, not just on absence.
    """
    return (os.getenv(var) or "").strip() or default


def _parse_nonroot_id(part: str) -> int | None:
    """Parse a plain ASCII decimal id, or return None if it is not one or is 0.

    Validates the string exactly as given: no stripping, no sign, no separators.
    What gets validated has to be what Docker receives, otherwise the two
    disagree. ``isascii()`` matters as well as ``isdigit()``, because
    ``"٠".isdigit()`` is true and ``int("٠")`` is 0, so a non-ASCII digit would
    otherwise pass as a "numeric" non-root id.
    """
    if not part or not part.isascii() or not part.isdigit():
        return None
    value = int(part)
    return value if value > 0 else None


def _sandbox_user() -> str:
    """Resolve the container user, refusing anything Docker could treat as root.

    Only a canonical, fully qualified ``UID:GID`` of two positive ASCII decimal
    numbers is accepted, and the value handed to Docker is re-rendered from the
    parsed integers rather than passed through. Everything else falls back to the
    default. In particular:

    * ``UID`` alone is refused. Docker resolves a bare numeric uid with no
      matching passwd entry to **gid 0**, so ``--user 1000`` yields
      ``uid=1000 gid=0(root)``, which is not the non-root sandbox this promises.
    * any whitespace, sign or extra field is refused rather than trimmed. The
      earlier version validated ``part.strip()`` but forwarded the raw string, so
      ``"1000 :1000"`` passed validation while Docker saw a *user name* of
      ``"1000 "`` and resolved it against the image's ``/etc/passwd`` -- and the
      image can be attacker-chosen.
    * names are refused for that same reason: a name promises nothing about the
      uid the image maps it to.
    * a zero uid or gid is refused in every spelling (``00``, ``+0``, ``:0``).
    """
    value = _tunable("HEYM_MCP_STDIO_USER", _DEFAULT_SANDBOX_USER)
    parts = value.split(":")
    uid = _parse_nonroot_id(parts[0]) if len(parts) == 2 else None
    gid = _parse_nonroot_id(parts[1]) if len(parts) == 2 else None
    if uid is None or gid is None:
        logger.warning(
            "HEYM_MCP_STDIO_USER=%r is not a canonical non-root UID:GID of two positive "
            "numbers (a bare UID leaves the container in group root, and names, signs or "
            "whitespace are resolved against the image's passwd file); falling back to %s",
            value,
            _DEFAULT_SANDBOX_USER,
        )
        return _DEFAULT_SANDBOX_USER
    # Re-render from the parsed integers so what was validated is what Docker gets.
    return f"{uid}:{gid}"


def _parse_docker_run(argv: list[str]) -> tuple[_CarriedFlags, list[str], str, list[str]]:
    """Split a caller's ``docker run`` invocation.

    Returns ``(carried_flags, notes, image, image_args)``. Raises when a flag
    would dissolve the sandbox boundary.
    """
    if len(argv) < 2 or argv[1] != "run":
        raise MCPStdioSandboxError(
            "Only 'docker run' is supported for MCP stdio commands. "
            f"Received: {' '.join(argv[:2]) or 'docker'}"
        )

    carried = _CarriedFlags()
    notes: list[str] = []
    index = 2
    image = ""

    while index < len(argv):
        token = argv[index]
        if not token.startswith("-"):
            image = token
            index += 1
            break

        # Normalize --flag=value into (flag, value).
        if "=" in token and token.startswith("--"):
            flag, _, inline_value = token.partition("=")
            value: str | None = inline_value
            consumed = 1
        else:
            flag = token
            value = argv[index + 1] if index + 1 < len(argv) else None
            consumed = 2 if flag in _DOCKER_VALUE_FLAGS and flag != "--privileged" else 1

        if flag in _DOCKER_REFUSED_FLAGS:
            raise MCPStdioSandboxError(
                f"MCP stdio option '{flag}' is not allowed: {_DOCKER_REFUSED_FLAGS[flag]}. "
                "Remove it from the command, or use the sse/streamable_http transport."
            )

        if flag in ("--network", "--net"):
            if value in ("host", "container"):
                raise MCPStdioSandboxError(
                    f"MCP stdio option '--network {value}' is not allowed: it would place "
                    "the MCP server on the backend's own network namespace."
                )
            notes.append("network flag ignored; the sandbox manages networking")
        elif flag in ("-e", "--env"):
            if value:
                carried.env.append(value)
        elif flag in ("-v", "--volume"):
            raise MCPStdioSandboxError(
                f"MCP stdio option '{flag}' is not allowed: "
                "user-supplied bind mounts cannot be made safe. Validating the source "
                "path is a losing game (`//var/run/docker.sock`, relative paths, "
                "symlinks and parent directories all defeat a denylist), so no "
                "caller-controlled mount is accepted. If this server needs data, ask "
                "the deployment operator to expose it: they can point "
                "HEYM_MCP_STDIO_FILES_VOLUME at a volume they scope themselves, which "
                "then appears at HEYM_MCP_STDIO_FILES_PATH."
            )
        elif flag in ("-w", "--workdir"):
            if value:
                carried.workdir = value
        elif flag == "--entrypoint":
            if value:
                carried.entrypoint = value
        elif flag in ("-u", "--user"):
            notes.append("user flag ignored; the sandbox runs as a non-root user")
        elif flag in ("-i", "-t", "-it", "-ti", "--interactive", "--tty", "--rm", "--init"):
            pass  # Already implied or irrelevant; the sandbox sets its own.
        elif flag in ("--name",):
            notes.append("name flag ignored; the sandbox assigns a throwaway name")
        else:
            notes.append(f"flag '{flag}' ignored by the sandbox")

        index += consumed

    if not image:
        raise MCPStdioSandboxError(
            "Could not determine the image from the MCP stdio 'docker run' command."
        )

    return carried, notes, image, argv[index:]


def build_sandboxed_command(
    command: str,
    args: list[str],
    user_env: dict[str, str] | None,
) -> SandboxedCommand:
    """Rewrite an MCP stdio command so it runs inside a hardened container.

    Raises ``MCPStdioSandboxError`` when the sandbox is required but unavailable,
    or when the command asks for something the sandbox cannot grant safely.
    """
    mode = sandbox_mode()
    env = {str(k): str(v) for k, v in (user_env or {}).items()} or None

    if mode == "subprocess":
        # Explicit trusted / single-user opt-out. Still never leaks os.environ.
        logger.warning(
            "HEYM_MCP_STDIO_SANDBOX=subprocess: starting MCP stdio server %r on the "
            "backend host without container isolation. Trusted/dev use only.",
            command,
        )
        resolved = shutil.which(command) or command
        return SandboxedCommand(argv=[resolved, *args], env=env)

    if not docker_available():
        if mode == "docker":
            raise MCPStdioSandboxError(
                "HEYM_MCP_STDIO_SANDBOX=docker but no Docker daemon is reachable, so the "
                "MCP stdio server cannot be isolated. Start Docker, or set "
                "HEYM_MCP_STDIO_SANDBOX=subprocess to run it on the host (trusted single-user setups only)."
            )
        raise MCPStdioSandboxError(
            "MCP stdio servers run inside a Docker sandbox, but no Docker daemon is "
            "reachable. Start Docker, or set HEYM_MCP_STDIO_SANDBOX=subprocess to run the "
            "server directly on the backend host (trusted/single-user setups only)."
        )

    name = f"heym-mcp-stdio-{uuid.uuid4().hex[:12]}"
    basename = os.path.basename((command or "").strip()).lower()
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    user_env = [f"{key}={value}" for key, value in (env or {}).items()]

    if stem == "docker":
        carried, notes, image, image_args = _parse_docker_run([command, *args])
        spec = _mcp_spec(
            name=name,
            image=image,
            entrypoint=carried.entrypoint,
            args=image_args,
            workdir=carried.workdir,
            extra_env=[*carried.env, *user_env],
        )
    else:
        notes = []
        image = _sandbox_image()
        if not image:
            raise MCPStdioSandboxError(
                f"Cannot isolate the MCP stdio command '{command}': the sandbox image could "
                "not be resolved. Set HEYM_MCP_STDIO_IMAGE (or HEYM_PYTHON_TOOL_IMAGE) to the "
                "backend image, or use the `docker run <image>` form, which names its own image."
            )
        spec = _mcp_spec(
            name=name,
            image=image,
            entrypoint=command,
            args=list(args),
            workdir=_SANDBOX_TMPFS_PATH,
            extra_env=user_env,
        )
    # Env travels inside the command; the spawning client inherits nothing of ours.
    process = get_sandbox_manager().process_command(spec)
    return SandboxedCommand(
        argv=process.argv, env=process.env, container_name=process.name, notes=notes
    )


def force_remove_container(name: str | None) -> None:
    """Best-effort cleanup for a sandbox that outlived its session."""
    get_sandbox_manager().force_remove(name)
