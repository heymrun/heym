"""Regression tests for the MCP stdio sandbox (GHSA-378x-q589-34mv).

The stdio transport starts a caller-supplied command. These tests pin the
properties that keep that from being host command execution:

* the command is rewritten into a hardened, throwaway container
* the Docker socket never reaches the child, directly or via a bind mount
* backend secrets never reach the child
* `docker run` keeps working, with its dangerous flags refused
* the gate lives in _open_transport, so every caller is covered
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.mcp_stdio_sandbox import (
    MCPStdioSandboxError,
    _sandbox_image,
    build_sandboxed_command,
    reset_docker_available_cache,
    sandbox_mode,
)
from app.services.mcp_tool_executor import _open_transport


def _flag_value(argv: list[str], flag: str) -> str | None:
    for index, token in enumerate(argv):
        if token == flag and index + 1 < len(argv):
            return argv[index + 1]
    return None


class SandboxModeTests(unittest.TestCase):
    def test_defaults_to_auto(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HEYM_MCP_STDIO_SANDBOX", None)
            self.assertEqual(sandbox_mode(), "auto")

    def test_unknown_mode_falls_back_to_auto(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "nonsense"}):
            self.assertEqual(sandbox_mode(), "auto")

    def test_no_new_env_var_is_required(self) -> None:
        """The sandbox reuses the existing knob rather than adding one."""
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "docker"}):
            self.assertEqual(sandbox_mode(), "docker")


class SandboxDecouplingTests(unittest.TestCase):
    """MCP stdio isolation must not follow the Python tool setting.

    An operator who selects HEYM_PYTHON_TOOL_SANDBOX=subprocess for Python tool
    compatibility (and run.sh, which does it automatically for native dev) must
    not silently lose MCP stdio isolation with it.
    """

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)

    def test_python_tool_subprocess_does_not_downgrade_mcp_stdio(self) -> None:
        with patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "subprocess"}):
            os.environ.pop("HEYM_MCP_STDIO_SANDBOX", None)
            self.assertEqual(sandbox_mode(), "auto")

    def test_python_tool_subprocess_still_fails_closed_without_docker(self) -> None:
        with (
            patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "subprocess"}),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=False),
        ):
            os.environ.pop("HEYM_MCP_STDIO_SANDBOX", None)
            with self.assertRaises(MCPStdioSandboxError):
                build_sandboxed_command("/bin/sh", ["-c", "id"], None)

    def test_unknown_value_fails_closed_to_auto_not_host(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "nonsense"}):
            self.assertEqual(sandbox_mode(), "auto")


class FilesMountTests(unittest.TestCase):
    """No application storage may be auto-mounted into an MCP server.

    An earlier revision fell back to the skill/Codex workspace volume so
    file-oriented MCP servers would keep working. In the default Compose setup
    that mounted the whole `heym-codex-workspaces` volume read-write, giving any
    authenticated caller's MCP process access to every other tenant's workspace
    data. These tests pin that it cannot come back.
    """

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)
        self._patches = [
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        for var in (
            "HEYM_MCP_STDIO_FILES_VOLUME",
            "HEYM_MCP_STDIO_FILES_HOST_DIR",
            "HEYM_MCP_STDIO_FILES_WRITABLE",
            "HEYM_MCP_STDIO_FILES_SUBPATH",
        ):
            os.environ.pop(var, None)

    def test_nothing_is_mounted_by_default(self) -> None:
        argv = build_sandboxed_command("npx", [], None).argv
        self.assertNotIn("--mount", argv)
        self.assertNotIn("--volume", argv)

    def test_codex_workspace_volume_is_never_auto_mounted(self) -> None:
        """The regression: Compose sets this, and it holds every tenant's data."""
        with patch.dict(
            os.environ, {"HEYM_CODEX_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces"}
        ):
            argv = build_sandboxed_command("npx", [], None).argv
        joined = " ".join(argv)
        self.assertNotIn("heym-codex-workspaces", joined)
        self.assertNotIn("--mount", argv)

    def test_skill_workspace_volume_is_never_auto_mounted(self) -> None:
        with patch.dict(os.environ, {"HEYM_SKILL_DOCKER_WORKSPACE_VOLUME": "heym-skills"}):
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertNotIn("heym-skills", " ".join(argv))

    def test_opencode_workspace_volume_is_never_auto_mounted(self) -> None:
        with patch.dict(
            os.environ, {"HEYM_OPENCODE_DOCKER_WORKSPACE_VOLUME": "heym-opencode-workspaces"}
        ):
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertNotIn("heym-opencode-workspaces", " ".join(argv))

    def test_file_storage_dir_is_not_auto_mounted(self) -> None:
        """Drive uploads are per user and team, so the directory is cross-tenant."""
        with patch("app.services.mcp_stdio_sandbox.settings") as fake_settings:
            fake_settings.file_storage_dir = "/app/data/files"
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertNotIn("/app/data/files", " ".join(argv))

    def test_explicit_volume_is_mounted_read_only(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_FILES_VOLUME": "operator-chosen"}):
            argv = build_sandboxed_command("npx", [], None).argv
        joined = " ".join(argv)
        self.assertIn("src=operator-chosen", joined)
        self.assertIn("readonly", joined)

    def test_explicit_volume_supports_subpath_scoping(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HEYM_MCP_STDIO_FILES_VOLUME": "operator-chosen",
                "HEYM_MCP_STDIO_FILES_SUBPATH": "tenant-a",
            },
        ):
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertIn("volume-subpath=tenant-a", " ".join(argv))

    def test_explicit_host_dir_is_mounted_read_only(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_FILES_HOST_DIR": "/srv/shared"}):
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertIn("/srv/shared:/mnt/heym-files:ro", argv)

    def test_writes_require_an_explicit_opt_in(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HEYM_MCP_STDIO_FILES_HOST_DIR": "/srv/shared",
                "HEYM_MCP_STDIO_FILES_WRITABLE": "true",
            },
        ):
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertIn("/srv/shared:/mnt/heym-files", argv)
        self.assertNotIn("/srv/shared:/mnt/heym-files:ro", argv)


class SandboxRequiredTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)

    def test_auto_fails_closed_without_docker(self) -> None:
        with (
            patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "auto"}),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=False),
        ):
            with self.assertRaises(MCPStdioSandboxError) as ctx:
                build_sandboxed_command("/bin/sh", ["-c", "id"], None)
            self.assertIn("Docker", str(ctx.exception))

    def test_docker_mode_fails_closed_without_docker(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=False),
        ):
            with self.assertRaises(MCPStdioSandboxError):
                build_sandboxed_command("npx", ["-y", "server"], None)

    def test_subprocess_mode_is_explicit_opt_out(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "subprocess"}):
            result = build_sandboxed_command("npx", ["-y", "server"], {"K": "v"})
        self.assertNotIn("docker", result.argv[0])
        self.assertEqual(result.env, {"K": "v"})

    def test_subprocess_mode_still_never_leaks_os_environ(self) -> None:
        with patch.dict(
            os.environ,
            {"HEYM_MCP_STDIO_SANDBOX": "subprocess", "SECRET_KEY": "leak-me"},
        ):
            result = build_sandboxed_command("npx", [], {"K": "v"})
        self.assertEqual(result.env, {"K": "v"})
        self.assertNotIn("SECRET_KEY", result.env or {})


class HardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)
        self._patches = [
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_plain_command_runs_in_a_container(self) -> None:
        result = build_sandboxed_command("npx", ["-y", "@some/mcp-server"], None)
        self.assertEqual(result.argv[0], "docker")
        self.assertEqual(result.argv[1], "run")
        self.assertIn("--rm", result.argv)
        self.assertIn("-i", result.argv)  # MCP needs the stdin/stdout stream
        self.assertEqual(_flag_value(result.argv, "--entrypoint"), "npx")
        self.assertIn("@some/mcp-server", result.argv)

    def test_hardening_flags_present(self) -> None:
        argv = build_sandboxed_command("npx", [], None).argv
        self.assertEqual(_flag_value(argv, "--cap-drop"), "ALL")
        self.assertEqual(_flag_value(argv, "--security-opt"), "no-new-privileges")
        self.assertIn("--read-only", argv)
        self.assertNotEqual(_flag_value(argv, "--user"), "root")
        self.assertIsNotNone(_flag_value(argv, "--memory"))
        self.assertIsNotNone(_flag_value(argv, "--pids-limit"))

    def test_docker_socket_never_mounted(self) -> None:
        argv = build_sandboxed_command("npx", [], None).argv
        joined = " ".join(argv)
        self.assertNotIn("docker.sock", joined)
        self.assertNotIn("/var/run", joined)

    def test_child_env_is_only_user_supplied(self) -> None:
        with patch.dict(os.environ, {"SECRET_KEY": "leak-me", "DATABASE_URL": "postgres://x"}):
            result = build_sandboxed_command("npx", [], {"API_KEY": "user-value"})
        joined = " ".join(result.argv)
        self.assertIn("API_KEY=user-value", joined)
        self.assertNotIn("leak-me", joined)
        self.assertNotIn("postgres://x", joined)
        # The docker CLI process itself inherits nothing either.
        self.assertEqual(result.env, {})

    def test_each_run_gets_a_throwaway_name(self) -> None:
        first = build_sandboxed_command("npx", [], None)
        second = build_sandboxed_command("npx", [], None)
        self.assertIsNotNone(first.container_name)
        self.assertNotEqual(first.container_name, second.container_name)


class TunableFallbackTests(unittest.TestCase):
    """Set-but-empty tuning vars must fall back, not reach the docker CLI.

    `os.environ.get(var, default)` returns "" for a variable that is set but
    empty, and an empty value is not inert on the CLI: `docker run --user ""`
    starts the container as uid 0. Verified live.
    """

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)
        self._patches = [
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_empty_user_does_not_become_root(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_USER": ""}):
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertEqual(_flag_value(argv, "--user"), "65534:65534")

    def test_every_root_spelling_is_refused(self) -> None:
        """Docker resolves many strings to uid 0, so a == "0" check is not enough.

        Verified live against Docker: 00, 000:000, :0, +0 and -0 all produce
        uid 0. Named users are refused too, since the name resolves against the
        image's /etc/passwd and the image can be attacker-chosen.
        """
        root_spellings = [
            "0",
            "0:0",
            "00",  # leading zeros
            "000:000",
            "0000000",
            ":0",  # empty uid, docker defaults to root
            ":",
            "+0",  # signed
            "-0",
            " 0 ",  # padded
            "root",  # named
            "root:root",
            "someuser",  # any name: the image decides what it maps to
            "\u0660",  # Arabic-Indic zero: isdigit() is true, int() is 0
            "0x0",
            "1000:0",  # non-root uid but root group
        ]
        for value in root_spellings:
            with self.subTest(value=value):
                with patch.dict(os.environ, {"HEYM_MCP_STDIO_USER": value}):
                    argv = build_sandboxed_command("npx", [], None).argv
                self.assertEqual(
                    _flag_value(argv, "--user"),
                    "65534:65534",
                    f"{value!r} must not reach docker --user",
                )

    def test_canonical_non_root_user_is_honoured(self) -> None:
        for value, expected in (
            ("1000:1000", "1000:1000"),
            ("65534:65534", "65534:65534"),
            ("2000:3000", "2000:3000"),
            ("01000:01000", "1000:1000"),  # normalized from the parsed integers
        ):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"HEYM_MCP_STDIO_USER": value}):
                    argv = build_sandboxed_command("npx", [], None).argv
                self.assertEqual(_flag_value(argv, "--user"), expected)

    def test_forwarded_value_is_always_canonical(self) -> None:
        """What was validated must be what Docker receives, byte for byte."""
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_USER": "01000:02000"}):
            argv = build_sandboxed_command("npx", [], None).argv
        forwarded = _flag_value(argv, "--user")
        self.assertEqual(forwarded, "1000:2000")
        self.assertNotIn(" ", forwarded or "")

    def test_other_empty_tunables_fall_back(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HEYM_MCP_STDIO_PIDS": "",
                "HEYM_MCP_STDIO_MEMORY": "",
                "HEYM_MCP_STDIO_CPUS": "",
            },
        ):
            argv = build_sandboxed_command("npx", [], None).argv
        self.assertEqual(_flag_value(argv, "--pids-limit"), "256")
        self.assertEqual(_flag_value(argv, "--memory"), "512m")
        self.assertEqual(_flag_value(argv, "--cpus"), "2")
        self.assertNotIn("", argv)


class ErrorMessageTests(unittest.TestCase):
    """Errors must name the setting that actually governs MCP stdio."""

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)

    def test_fail_closed_message_names_the_mcp_setting(self) -> None:
        with (
            patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "auto"}),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=False),
        ):
            with self.assertRaises(MCPStdioSandboxError) as ctx:
                build_sandboxed_command("npx", [], None)
        message = str(ctx.exception)
        self.assertIn("HEYM_MCP_STDIO_SANDBOX", message)
        self.assertNotIn("HEYM_PYTHON_TOOL_SANDBOX", message)

    def test_docker_mode_message_names_the_mcp_setting(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=False),
        ):
            with self.assertRaises(MCPStdioSandboxError) as ctx:
                build_sandboxed_command("npx", [], None)
        message = str(ctx.exception)
        self.assertIn("HEYM_MCP_STDIO_SANDBOX", message)
        self.assertNotIn("HEYM_PYTHON_TOOL_SANDBOX", message)


class SandboxImageResolutionTests(unittest.TestCase):
    """The sandbox image must resolve in every deployment shape.

    Compose builds heym-backend:local, but the single GHCR image does not have
    that tag, so hardcoding it would break `docker run ghcr.io/heymrun/heym`
    deployments for npx/uvx servers. Mirrors the Playwright and Python tool
    runners: explicit override, then HEYM_CODEX_DOCKER_IMAGE (which Compose and
    the GHCR image both set), then docker inspect of this container.
    """

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)
        for var in (
            "HEYM_MCP_STDIO_IMAGE",
            "HEYM_PYTHON_TOOL_IMAGE",
            "HEYM_CODEX_DOCKER_IMAGE",
        ):
            os.environ.pop(var, None)

    def test_explicit_override_wins(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_IMAGE": "my/image:1"}):
            self.assertEqual(_sandbox_image(), "my/image:1")

    def test_python_tool_image_is_used(self) -> None:
        with patch.dict(os.environ, {"HEYM_PYTHON_TOOL_IMAGE": "heym-backend:local"}):
            self.assertEqual(_sandbox_image(), "heym-backend:local")

    def test_codex_image_is_used_for_the_ghcr_release_image(self) -> None:
        with patch.dict(os.environ, {"HEYM_CODEX_DOCKER_IMAGE": "ghcr.io/heymrun/heym:0.0.75"}):
            self.assertEqual(_sandbox_image(), "ghcr.io/heymrun/heym:0.0.75")

    def test_falls_back_to_container_inspect(self) -> None:
        with patch("app.services.mcp_stdio_sandbox.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout="inspected/image:2\n")
            self.assertEqual(_sandbox_image(), "inspected/image:2")

    def test_no_hardcoded_compose_tag(self) -> None:
        """Nothing resolvable must not silently become a Compose-only tag."""
        with patch("app.services.mcp_stdio_sandbox.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=1, stdout="")
            self.assertIsNone(_sandbox_image())

    def test_unresolvable_image_fails_closed(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
            patch("app.services.mcp_stdio_sandbox._sandbox_image", return_value=None),
        ):
            with self.assertRaises(MCPStdioSandboxError) as ctx:
                build_sandboxed_command("npx", [], None)
        self.assertIn("HEYM_MCP_STDIO_IMAGE", str(ctx.exception))

    def test_docker_run_form_needs_no_image_resolution(self) -> None:
        """`docker run IMAGE` names its own image, so it works even unresolved."""
        with (
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
            patch("app.services.mcp_stdio_sandbox._sandbox_image", return_value=None),
        ):
            result = build_sandboxed_command("docker", ["run", "mcp/fetch"], None)
        self.assertEqual(result.argv[-1], "mcp/fetch")


class ContainerRuntimeUsabilityTests(unittest.TestCase):
    """The hardened container must still be able to run a real MCP server.

    The first version of the sandbox was airtight and unusable: `npx` died with
    `mkdir /nonexistent` because uid 65534's passwd home does not exist, and once
    that was fixed the installed binary would not start because Docker silently
    applies `noexec` to every --tmpfs. The existing tests all asserted argv
    contents that looked correct, so none of them caught it. These pin the
    runtime preconditions instead.
    """

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)
        self._patches = [
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _tmpfs_spec(self, argv: list[str]) -> str:
        return _flag_value(argv, "--tmpfs") or ""

    def _envs(self, argv: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for index, token in enumerate(argv):
            if token == "--env" and index + 1 < len(argv) and "=" in argv[index + 1]:
                key, _, value = argv[index + 1].partition("=")
                out[key] = value
        return out

    def test_tmpfs_allows_exec(self) -> None:
        """Docker adds noexec unless exec is named, which blocks npx-installed bins."""
        spec = self._tmpfs_spec(build_sandboxed_command("npx", [], None).argv)
        self.assertIn("exec", spec.split(":")[-1].split(","))
        self.assertNotIn("noexec", spec)

    def test_tmpfs_still_drops_suid(self) -> None:
        spec = self._tmpfs_spec(build_sandboxed_command("npx", [], None).argv)
        self.assertIn("nosuid", spec)

    def test_home_points_at_a_writable_path(self) -> None:
        """uid 65534's passwd home is /nonexistent, so npm cannot even start."""
        envs = self._envs(build_sandboxed_command("npx", [], None).argv)
        self.assertEqual(envs.get("HOME"), "/tmp")

    def test_package_manager_caches_point_at_the_tmpfs(self) -> None:
        envs = self._envs(build_sandboxed_command("npx", [], None).argv)
        for key in ("NPM_CONFIG_CACHE", "XDG_CACHE_HOME", "UV_CACHE_DIR"):
            with self.subTest(key=key):
                self.assertTrue(
                    (envs.get(key) or "").startswith("/tmp"),
                    f"{key} must be writable, got {envs.get(key)!r}",
                )

    def test_rootfs_stays_read_only(self) -> None:
        """Making /tmp usable must not have loosened the rootfs."""
        argv = build_sandboxed_command("npx", [], None).argv
        self.assertIn("--read-only", argv)

    def test_hardening_is_unchanged_by_the_usability_fix(self) -> None:
        argv = build_sandboxed_command("npx", [], None).argv
        self.assertEqual(_flag_value(argv, "--cap-drop"), "ALL")
        self.assertEqual(_flag_value(argv, "--security-opt"), "no-new-privileges")
        self.assertEqual(_flag_value(argv, "--user"), "65534:65534")
        self.assertNotIn("docker.sock", " ".join(argv))

    def test_caller_env_can_override_our_defaults(self) -> None:
        """Caller vars come after ours, so docker resolves them last."""
        argv = build_sandboxed_command("npx", [], {"HOME": "/tmp/custom"}).argv
        positions = [i for i, t in enumerate(argv) if t == "--env"]
        values = [argv[i + 1] for i in positions]
        self.assertLess(values.index("HOME=/tmp"), values.index("HOME=/tmp/custom"))

    def test_docker_run_form_gets_the_same_runtime_env(self) -> None:
        argv = build_sandboxed_command("docker", ["run", "mcp/fetch"], None).argv
        envs = self._envs(argv)
        self.assertEqual(envs.get("HOME"), "/tmp")
        self.assertIn("exec", self._tmpfs_spec(argv).split(":")[-1].split(","))

    def test_tmpfs_size_is_tunable(self) -> None:
        with patch.dict(os.environ, {"HEYM_MCP_STDIO_TMPFS_SIZE": "1g"}):
            spec = self._tmpfs_spec(build_sandboxed_command("npx", [], None).argv)
        self.assertIn("size=1g", spec)


class DockerRunRewriteTests(unittest.TestCase):
    """`docker run` keeps working, but we start the image instead of the child."""

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)
        self._patches = [
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_image_is_preserved(self) -> None:
        result = build_sandboxed_command("docker", ["run", "-i", "--rm", "mcp/fetch"], None)
        self.assertEqual(result.argv[-1], "mcp/fetch")
        self.assertEqual(_flag_value(result.argv, "--cap-drop"), "ALL")

    def test_image_args_are_preserved(self) -> None:
        result = build_sandboxed_command(
            "docker", ["run", "-i", "--rm", "mcp/fetch", "--port", "9000"], None
        )
        self.assertEqual(result.argv[-3:], ["mcp/fetch", "--port", "9000"])

    def test_user_env_flags_are_carried_over(self) -> None:
        result = build_sandboxed_command(
            "docker", ["run", "-i", "--rm", "-e", "TOKEN=abc", "mcp/fetch"], None
        )
        self.assertIn("TOKEN=abc", result.argv)

    def test_inline_env_syntax_is_carried_over(self) -> None:
        result = build_sandboxed_command("docker", ["run", "--env=TOKEN=abc", "mcp/fetch"], None)
        self.assertIn("TOKEN=abc", result.argv)

    def test_privileged_is_refused(self) -> None:
        with self.assertRaises(MCPStdioSandboxError) as ctx:
            build_sandboxed_command("docker", ["run", "--privileged", "mcp/fetch"], None)
        self.assertIn("privileged", str(ctx.exception))

    def test_cap_add_is_refused(self) -> None:
        with self.assertRaises(MCPStdioSandboxError):
            build_sandboxed_command("docker", ["run", "--cap-add", "SYS_ADMIN", "mcp/x"], None)

    def test_host_network_is_refused(self) -> None:
        with self.assertRaises(MCPStdioSandboxError) as ctx:
            build_sandboxed_command("docker", ["run", "--network", "host", "mcp/x"], None)
        self.assertIn("network", str(ctx.exception))

    def test_mount_flag_syntax_is_refused(self) -> None:
        """--mount bypasses the -v source validation, so it is not accepted."""
        with self.assertRaises(MCPStdioSandboxError):
            build_sandboxed_command(
                "docker",
                ["run", "--mount", "type=bind,src=/,dst=/host", "mcp/x"],
                None,
            )

    def test_env_file_is_refused(self) -> None:
        """--env-file would read backend host files into the container."""
        with self.assertRaises(MCPStdioSandboxError):
            build_sandboxed_command("docker", ["run", "--env-file", "/app/.env", "mcp/x"], None)

    def test_user_flag_cannot_force_root(self) -> None:
        result = build_sandboxed_command("docker", ["run", "-u", "root", "mcp/x"], None)
        self.assertNotEqual(_flag_value(result.argv, "--user"), "root")

    def test_every_bind_mount_form_is_refused(self) -> None:
        """No caller-controlled mount is accepted, in any spelling.

        The previous design validated the source path against a denylist. That
        was bypassable: os.path.normpath preserves exactly two leading slashes
        (POSIX), so `//var/run/docker.sock` compared unequal to
        `/var/run/docker.sock` and reached the container. Rather than patching
        that one encoding, mounts are refused outright, so this test enumerates
        the bypasses that used to work and asserts none of them get through.
        """
        bypasses = [
            "//var/run/docker.sock:/sock",  # double slash: the reported bypass
            "///var/run/docker.sock:/sock",  # triple slash
            "/var/run/docker.sock:/sock",  # plain
            "//:/host",  # double-slash host root
            "/:/host",  # host root
            "//etc:/etc",  # double-slash /etc
            "/var/lib/../run/docker.sock:/sock",  # parent traversal
            "/var/run/./docker.sock:/sock",  # dot segment
            "../../var/run/docker.sock:/sock",  # relative
            "somevolume:/data",  # named volume
            "/srv/data:/data",  # innocuous host dir
            "/srv/link-to-sock:/sock",  # symlink target unknown to us
        ]
        for spec in bypasses:
            for flag in ("-v", "--volume"):
                with self.subTest(spec=spec, flag=flag):
                    with self.assertRaises(MCPStdioSandboxError):
                        build_sandboxed_command("docker", ["run", flag, spec, "alpine"], None)

    def test_volumes_from_is_refused(self) -> None:
        """--volumes-from would inherit the backend's own socket mount."""
        with self.assertRaises(MCPStdioSandboxError):
            build_sandboxed_command("docker", ["run", "--volumes-from", "heym", "x"], None)

    def test_no_user_path_reaches_the_argv(self) -> None:
        """Nothing the caller wrote may end up as a mount source."""
        with self.assertRaises(MCPStdioSandboxError):
            build_sandboxed_command(
                "docker", ["run", "-v", "/var/run/docker.sock:/s", "alpine"], None
            )

    def test_non_run_subcommand_is_refused(self) -> None:
        with self.assertRaises(MCPStdioSandboxError):
            build_sandboxed_command("docker", ["exec", "-i", "somectr", "sh"], None)

    def test_missing_image_is_refused(self) -> None:
        with self.assertRaises(MCPStdioSandboxError):
            build_sandboxed_command("docker", ["run", "-i", "--rm"], None)


class OpenTransportIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """The gate must sit in _open_transport so every caller is covered.

    /api/mcp/fetch-tools, agent MCP connections and the mcpCall node all reach
    the stdio branch through this one function, so a bypass in any of them would
    have to bypass this test too.
    """

    def setUp(self) -> None:
        reset_docker_available_cache()
        self.addCleanup(reset_docker_available_cache)

    async def test_shell_command_is_rewritten_into_a_container(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
            patch("app.services.mcp_tool_executor.StdioServerParameters") as mock_params,
            patch("app.services.mcp_tool_executor.stdio_client") as mock_stdio_client,
            patch("app.services.mcp_tool_executor.force_remove_container"),
        ):
            mock_stdio_client.return_value.__aenter__ = AsyncMock(return_value=(object(), object()))
            mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=None)

            conn = {
                "transport": "stdio",
                "command": "/bin/sh",
                "args": ["-c", "id > /tmp/pwned"],
            }
            try:
                async with _open_transport(conn, 5.0):
                    pass
            except Exception:
                pass

            mock_params.assert_called_once()
            command = mock_params.call_args.kwargs["command"]
            args = mock_params.call_args.kwargs["args"]
            self.assertEqual(command, "docker", "the payload must not run on the host")
            self.assertIn("--cap-drop", args)
            self.assertNotIn("/var/run/docker.sock", " ".join(args))

    async def test_fails_closed_when_docker_is_unavailable(self) -> None:
        with (
            patch.dict(os.environ, {"HEYM_MCP_STDIO_SANDBOX": "auto"}),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=False),
            patch("app.services.mcp_tool_executor.stdio_client") as mock_stdio_client,
        ):
            conn = {"transport": "stdio", "command": "/bin/sh", "args": ["-c", "id"]}
            with self.assertRaises(MCPStdioSandboxError):
                async with _open_transport(conn, 5.0):
                    pass
            mock_stdio_client.assert_not_called()

    async def test_container_is_removed_after_the_session(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "HEYM_MCP_STDIO_SANDBOX": "docker",
                    "HEYM_MCP_STDIO_IMAGE": "heym-backend:local",
                },
            ),
            patch("app.services.mcp_stdio_sandbox.docker_available", return_value=True),
            patch("app.services.mcp_tool_executor.StdioServerParameters"),
            patch("app.services.mcp_tool_executor.stdio_client") as mock_stdio_client,
            patch("app.services.mcp_tool_executor.force_remove_container") as mock_remove,
        ):
            mock_stdio_client.return_value.__aenter__ = AsyncMock(return_value=(object(), object()))
            mock_stdio_client.return_value.__aexit__ = AsyncMock(return_value=None)

            conn = {"transport": "stdio", "command": "npx", "args": ["-y", "server"]}
            try:
                async with _open_transport(conn, 5.0):
                    pass
            except Exception:
                pass

            mock_remove.assert_called_once()
            self.assertTrue(str(mock_remove.call_args.args[0]).startswith("heym-mcp-stdio-"))


if __name__ == "__main__":
    unittest.main()
