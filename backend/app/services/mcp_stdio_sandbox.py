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
import socket
import subprocess
import uuid
from dataclasses import dataclass, field

from app.config import settings

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

# Nobody:nogroup. Root in the sandbox is refused even if explicitly configured.
_DEFAULT_SANDBOX_USER = "65534:65534"

_docker_available_cache: bool | None = None


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


def _resolve_files_mount() -> list[str]:
    """Return the file mount for the sandbox, which is nothing unless configured.

    **No application storage is mounted by default.** An earlier revision fell
    back to the skill/Codex workspace volume so file-oriented MCP servers would
    keep working. That was wrong: those volumes hold *every* tenant's workspaces,
    and mounting the volume root gave one caller's MCP process read (and write)
    access to other users' data. Note the skill runner deliberately mounts only
    a per-run ``volume-subpath`` for exactly this reason; copying its volume
    lookup without that scoping removed the isolation it was built to provide.

    Heym's own ``FILE_STORAGE_DIR`` is not auto-mounted either, for the same
    reason: Drive uploads are per user and team, so the directory as a whole is
    cross-tenant.

    A mount therefore only happens when an operator names one explicitly, which
    is a deliberate act they can scope to an isolated volume or subpath. It is
    read-only unless they also opt into writes.
    """
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
        spec = f"type=volume,src={volume},dst={_FILES_MOUNT_PATH}"
        subpath = os.environ.get("HEYM_MCP_STDIO_FILES_SUBPATH", "").strip()
        if subpath:
            spec += f",volume-subpath={subpath}"
        if not writable:
            spec += ",readonly"
        return ["--mount", spec]

    host_dir = os.environ.get("HEYM_MCP_STDIO_FILES_HOST_DIR", "").strip()
    if host_dir:
        suffix = "" if writable else ":ro"
        return ["--volume", f"{host_dir}:{_FILES_MOUNT_PATH}{suffix}"]

    logger.debug("MCP stdio sandbox: no file mount configured; the server sees no Heym files")
    return []


def docker_available() -> bool:
    """Return True when a working Docker daemon is reachable (cached)."""
    global _docker_available_cache
    if _docker_available_cache is not None:
        return _docker_available_cache
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _docker_available_cache = result.returncode == 0 and bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        _docker_available_cache = False
    return _docker_available_cache


def reset_docker_available_cache() -> None:
    """Clear the cached Docker probe (used by tests)."""
    global _docker_available_cache
    _docker_available_cache = None


def _sandbox_image() -> str | None:
    """Resolve the image used for non-``docker`` commands (it ships node and uv).

    Mirrors the Playwright and Python tool runners so every deployment shape
    works: an explicit override first, then the Codex/OpenCode runner image
    (Compose and the GHCR release image both set ``HEYM_CODEX_DOCKER_IMAGE`` to
    the backend image), then ``docker inspect`` of this container. Hardcoding a
    Compose-only tag here would break the single GHCR image, where that tag does
    not exist. Returns None when nothing resolves, so the caller can fail with an
    explanation instead of running ``docker run`` against a missing image.
    """
    override = (
        (os.getenv("HEYM_MCP_STDIO_IMAGE") or "").strip()
        or (os.getenv("HEYM_PYTHON_TOOL_IMAGE") or "").strip()
        or (os.getenv("HEYM_CODEX_DOCKER_IMAGE") or "").strip()
    )
    if override:
        return override
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", socket.gethostname()],
            capture_output=True,
            text=True,
            timeout=5,
        )
        image = result.stdout.strip()
        if result.returncode == 0 and image:
            return image
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass
    return None


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


def _hardening_flags(name: str, network: str = "bridge") -> list[str]:
    """Flags shared by every sandboxed MCP server container.

    ``-i`` is mandatory: the MCP protocol is a bidirectional stream over the
    child's stdin/stdout. No Docker socket is mounted, which is the difference
    between this and a host-side ``docker run``.

    The root filesystem is read-only, so the tmpfs at ``/tmp`` is the only place
    the server can write. Three details make that usable for ``npx`` / ``uvx``
    servers, all of which were missing at first and broke them outright:

    * ``exec`` on the tmpfs. Docker applies ``noexec`` to every ``--tmpfs`` unless
      it is named explicitly, so a package manager could install a server and
      then fail to run its binary. This does not weaken the boundary in practice:
      the caller already chooses the entrypoint, so running code inside the
      container is the premise, not the escalation. The boundary is the missing
      socket, the dropped capabilities and the non-root user.
    * ``HOME``. The container runs as uid 65534, whose passwd entry points at
      ``/nonexistent``, so npm's first action is ``mkdir /nonexistent`` and it
      dies with ENOENT before it ever reaches the registry.
    * cache directories. npm and uv both want to write under ``HOME`` or
      ``XDG_CACHE_HOME``; pointing them at the tmpfs keeps them off the
      read-only rootfs.
    """
    return [
        "--rm",
        "-i",
        "--name",
        name,
        "--network",
        network,
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,exec,nosuid,size={_tunable('HEYM_MCP_STDIO_TMPFS_SIZE', '512m')}",
        "--env",
        "HOME=/tmp",
        "--env",
        "NPM_CONFIG_CACHE=/tmp/.npm",
        "--env",
        "NPM_CONFIG_UPDATE_NOTIFIER=false",
        "--env",
        "XDG_CACHE_HOME=/tmp/.cache",
        "--env",
        "XDG_DATA_HOME=/tmp/.local/share",
        "--env",
        "UV_CACHE_DIR=/tmp/.uv",
        "--user",
        _sandbox_user(),
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        _tunable("HEYM_MCP_STDIO_PIDS", "256"),
        "--memory",
        _tunable("HEYM_MCP_STDIO_MEMORY", "512m"),
        "--cpus",
        _tunable("HEYM_MCP_STDIO_CPUS", "2"),
        *_resolve_files_mount(),
    ]


def _parse_docker_run(argv: list[str]) -> tuple[list[str], list[str], str, list[str]]:
    """Split a caller's ``docker run`` invocation.

    Returns ``(carried_flags, notes, image, image_args)``. Raises when a flag
    would dissolve the sandbox boundary.
    """
    if len(argv) < 2 or argv[1] != "run":
        raise MCPStdioSandboxError(
            "Only 'docker run' is supported for MCP stdio commands. "
            f"Received: {' '.join(argv[:2]) or 'docker'}"
        )

    carried: list[str] = []
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
                carried.extend(["--env", value])
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
                carried.extend(["--workdir", value])
        elif flag == "--entrypoint":
            if value:
                carried.extend(["--entrypoint", value])
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

    if stem == "docker":
        carried, notes, image, image_args = _parse_docker_run([command, *args])
        argv = ["docker", "run", *_hardening_flags(name), *carried]
        for key, value in (env or {}).items():
            argv.extend(["--env", f"{key}={value}"])
        argv.append(image)
        argv.extend(image_args)
        # Env is passed via --env flags, so the docker CLI itself inherits nothing.
        return SandboxedCommand(argv=argv, env={}, container_name=name, notes=notes)

    image = _sandbox_image()
    if not image:
        raise MCPStdioSandboxError(
            f"Cannot isolate the MCP stdio command '{command}': the sandbox image could not "
            "be resolved. Set HEYM_MCP_STDIO_IMAGE (or HEYM_PYTHON_TOOL_IMAGE) to the backend "
            "image, or use the `docker run <image>` form, which names its own image."
        )
    argv = ["docker", "run", *_hardening_flags(name), "--entrypoint", command]
    for key, value in (env or {}).items():
        argv.extend(["--env", f"{key}={value}"])
    argv.extend([image, *args])
    return SandboxedCommand(argv=argv, env={}, container_name=name)


def force_remove_container(name: str | None) -> None:
    """Best-effort cleanup for a sandbox container that outlived its session."""
    if not name:
        return
    try:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass
