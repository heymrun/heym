import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services import code_python_executor as executor


class BuildRunCommandTest(unittest.TestCase):
    def test_no_dependency_run_has_no_network_and_no_mount(self) -> None:
        cmd = executor._build_run_command(
            image="heym-backend:local",
            name="heym-code-abc",
            allow_network=False,
            mount_args=[],
            deps_path=None,
        )
        self.assertIn("--network", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        self.assertNotIn("--mount", cmd)
        self.assertNotIn("PYTHONPATH", " ".join(cmd))

    def test_allow_network_switches_the_run_phase_to_bridge(self) -> None:
        cmd = executor._build_run_command(
            image="heym-backend:local",
            name="heym-code-abc",
            allow_network=True,
            mount_args=[],
            deps_path=None,
        )
        self.assertEqual(cmd[cmd.index("--network") + 1], "bridge")

    def test_run_command_is_hardened(self) -> None:
        cmd = executor._build_run_command(
            image="heym-backend:local",
            name="heym-code-abc",
            allow_network=False,
            mount_args=[],
            deps_path=None,
        )
        joined = " ".join(cmd)
        self.assertIn("--rm", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("--cap-drop", cmd)
        self.assertEqual(cmd[cmd.index("--cap-drop") + 1], "ALL")
        self.assertEqual(cmd[cmd.index("--security-opt") + 1], "no-new-privileges")
        self.assertEqual(cmd[cmd.index("--user") + 1], "65534:65534")
        self.assertEqual(cmd[cmd.index("--memory") + 1], "512m")
        self.assertEqual(cmd[cmd.index("--memory-swap") + 1], "512m")
        self.assertEqual(cmd[cmd.index("--pids-limit") + 1], "256")
        self.assertNotIn("docker.sock", joined)
        self.assertEqual(cmd[cmd.index("--entrypoint") + 1], "python")

    def test_deps_path_is_exported_as_pythonpath(self) -> None:
        cmd = executor._build_run_command(
            image="heym-backend:local",
            name="heym-code-abc",
            allow_network=False,
            mount_args=["--mount", "type=volume,src=v,dst=/d,volume-subpath=x,readonly"],
            deps_path=Path("/d/.deps"),
        )
        self.assertIn("PYTHONPATH=/d/.deps", cmd)
        self.assertIn("--mount", cmd)


class BuildInstallCommandTest(unittest.TestCase):
    def test_uv_install_command(self) -> None:
        cmd = executor._build_install_command(
            image="heym-backend:local",
            name="heym-code-install-abc",
            mount_args=["--mount", "type=bind,src=/h/r,dst=/r"],
            run_dir=Path("/r"),
            tool="uv",
        )
        self.assertEqual(cmd[cmd.index("--network") + 1], "bridge")
        self.assertEqual(cmd[cmd.index("--entrypoint") + 1], "uv")
        tail = cmd[cmd.index("heym-backend:local") + 1 :]
        self.assertEqual(
            tail,
            ["pip", "install", "--no-cache", "--target", "/r/.deps", "-r", "/r/requirements.txt"],
        )

    def test_pip_install_command(self) -> None:
        cmd = executor._build_install_command(
            image="heym-backend:local",
            name="heym-code-install-abc",
            mount_args=[],
            run_dir=Path("/r"),
            tool="pip",
        )
        self.assertEqual(cmd[cmd.index("--entrypoint") + 1], "pip")
        tail = cmd[cmd.index("heym-backend:local") + 1 :]
        self.assertEqual(
            tail,
            ["install", "--no-cache-dir", "--target", "/r/.deps", "-r", "/r/requirements.txt"],
        )

    def test_install_command_is_hardened_too(self) -> None:
        cmd = executor._build_install_command(
            image="heym-backend:local",
            name="heym-code-install-abc",
            mount_args=[],
            run_dir=Path("/r"),
            tool="uv",
        )
        self.assertIn("--read-only", cmd)
        self.assertEqual(cmd[cmd.index("--cap-drop") + 1], "ALL")
        self.assertEqual(cmd[cmd.index("--user") + 1], "65534:65534")
        self.assertNotIn("docker.sock", " ".join(cmd))


class WorkspaceLocationTest(unittest.TestCase):
    """Native (non-containerised) backends bind-mount a local run dir directly."""

    def test_run_root_is_local_when_the_backend_is_not_containerised(self) -> None:
        with patch.object(executor, "_is_containerized", return_value=False):
            root = executor._code_run_root()
        self.assertTrue(str(root).startswith(tempfile.gettempdir()))

    def test_run_root_is_the_shared_volume_inside_a_container(self) -> None:
        with (
            patch.object(executor, "_is_containerized", return_value=True),
            patch.dict("os.environ", {"HEYM_CODEX_WORKSPACE_DIR": "/app/data/codex-workspaces"}),
        ):
            root = executor._code_run_root()
        self.assertEqual(str(root), "/app/data/codex-workspaces/_code-runs")

    def test_native_backend_binds_the_run_dir_at_the_same_path(self) -> None:
        run_dir = Path(tempfile.gettempdir()) / "heym-code-runs" / "abc"
        with (
            patch.object(executor, "_is_containerized", return_value=False),
            patch.dict("os.environ", {}, clear=False),
        ):
            args = executor._resolve_workspace_mount(run_dir, readonly=True)
        self.assertEqual(args, ["--mount", f"type=bind,src={run_dir},dst={run_dir},readonly"])

    def test_native_backend_bind_is_writable_for_the_install_phase(self) -> None:
        run_dir = Path(tempfile.gettempdir()) / "heym-code-runs" / "abc"
        with patch.object(executor, "_is_containerized", return_value=False):
            args = executor._resolve_workspace_mount(run_dir, readonly=False)
        self.assertEqual(args, ["--mount", f"type=bind,src={run_dir},dst={run_dir}"])

    def test_named_volume_still_wins_inside_a_container(self) -> None:
        with (
            patch.object(executor, "_is_containerized", return_value=True),
            patch.dict(
                "os.environ",
                {
                    "HEYM_CODEX_WORKSPACE_DIR": "/app/data/codex-workspaces",
                    "HEYM_CODEX_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces",
                },
            ),
        ):
            run_dir = Path("/app/data/codex-workspaces/_code-runs/abc")
            args = executor._resolve_workspace_mount(run_dir, readonly=True)
        self.assertEqual(
            args,
            [
                "--mount",
                f"type=volume,src=heym-codex-workspaces,dst={run_dir},"
                "volume-subpath=_code-runs/abc,readonly",
            ],
        )


class ForwardedEnvTest(unittest.TestCase):
    """Proxy/CA settings must survive, secrets must not."""

    def test_proxy_and_ca_settings_reach_the_install_container(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "HTTPS_PROXY": "http://corp:3128",
                "no_proxy": "localhost",
                "REQUESTS_CA_BUNDLE": "/etc/ssl/corp.pem",
                "LANG": "en_US.UTF-8",
            },
        ):
            cmd = executor._build_install_command(
                image="img", name="n", mount_args=[], run_dir=Path("/r"), tool="uv"
            )
        self.assertIn("HTTPS_PROXY=http://corp:3128", cmd)
        self.assertIn("no_proxy=localhost", cmd)
        self.assertIn("REQUESTS_CA_BUNDLE=/etc/ssl/corp.pem", cmd)
        self.assertIn("LANG=en_US.UTF-8", cmd)

    def test_secrets_are_never_forwarded(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SECRET_KEY": "jwt-signing-key",
                "ENCRYPTION_KEY": "credential-key",
                "DATABASE_URL": "postgresql://u:p@db/heym",
                "OPENAI_API_KEY": "sk-nope",
                "AWS_SECRET_ACCESS_KEY": "nope",
            },
        ):
            install = executor._build_install_command(
                image="img", name="n", mount_args=[], run_dir=Path("/r"), tool="uv"
            )
            run = executor._build_run_command(
                image="img", name="n", allow_network=True, mount_args=[], deps_path=None
            )
        for cmd in (install, run):
            joined = " ".join(cmd)
            for secret in ("jwt-signing-key", "credential-key", "postgresql://", "sk-nope", "nope"):
                self.assertNotIn(secret, joined)

    def test_host_home_never_overrides_the_sandbox_home(self) -> None:
        with patch.dict("os.environ", {"HOME": "/root"}):
            cmd = executor._build_run_command(
                image="img", name="n", allow_network=False, mount_args=[], deps_path=None
            )
        self.assertIn("HOME=/tmp", cmd)
        self.assertNotIn("HOME=/root", cmd)


class RunnerSourceTest(unittest.TestCase):
    def test_runner_source_is_the_module_on_disk(self) -> None:
        source = executor._runner_source()
        self.assertIn("def run(payload", source)
        self.assertIn("class DotDict", source)


def _fake_proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    """A Popen stand-in whose communicate() returns fixed output."""
    proc = MagicMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


_OK_ENVELOPE = json.dumps({"success": True, "result": {"ok": 1}, "logs": "hi\n"})


class ExecuteCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        executor._docker_available_cache = None

    def tearDown(self) -> None:
        executor._docker_available_cache = None

    def test_fails_closed_when_docker_is_unavailable(self) -> None:
        with patch.object(executor, "docker_available", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                executor.execute_code("def main(params):\n    return 1\n", "", {}, False)
        self.assertIn("requires Docker", str(ctx.exception))
        self.assertIn("No fallback", str(ctx.exception))

    def test_fails_when_the_image_cannot_be_resolved(self) -> None:
        with (
            patch.object(executor, "docker_available", return_value=True),
            patch.object(executor, "resolve_sandbox_image", return_value=None),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                executor.execute_code("def main(params):\n    return 1\n", "", {}, False)
        self.assertIn("image", str(ctx.exception).lower())

    def test_empty_requirements_runs_a_single_container(self) -> None:
        with (
            patch.object(executor, "docker_available", return_value=True),
            patch.object(executor, "resolve_sandbox_image", return_value="img"),
            patch.object(
                executor.subprocess, "Popen", return_value=_fake_proc(_OK_ENVELOPE)
            ) as popen,
        ):
            outcome = executor.execute_code("def main(params):\n    return 1\n", "   ", {}, False)

        self.assertEqual(popen.call_count, 1)
        cmd = popen.call_args_list[0].args[0]
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")
        self.assertNotIn("--mount", cmd)
        self.assertEqual(outcome.result, {"ok": 1})
        self.assertEqual(outcome.logs, "hi\n")
        self.assertEqual(outcome.install_tool, "none")
        self.assertTrue(outcome.install_ok)

    def test_payload_carries_the_runner_source_code_and_params(self) -> None:
        with (
            patch.object(executor, "docker_available", return_value=True),
            patch.object(executor, "resolve_sandbox_image", return_value="img"),
            patch.object(
                executor.subprocess, "Popen", return_value=_fake_proc(_OK_ENVELOPE)
            ) as popen,
        ):
            executor.execute_code("def main(params):\n    return 1\n", "", {"a": 1}, False)

        payload = json.loads(popen.return_value.communicate.call_args.kwargs["input"])
        self.assertIn("class DotDict", payload["runner"])
        self.assertEqual(payload["params"], {"a": 1})
        self.assertIn("def main", payload["code"])

    def test_requirements_trigger_install_then_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(executor, "docker_available", return_value=True),
                patch.object(executor, "resolve_sandbox_image", return_value="img"),
                patch.object(executor, "_code_run_root", return_value=Path(tmp)),
                patch.object(executor, "_resolve_workspace_mount", return_value=["--mount", "m"]),
                patch.object(
                    executor.subprocess,
                    "Popen",
                    side_effect=[_fake_proc("Installed 1 package"), _fake_proc(_OK_ENVELOPE)],
                ) as popen,
            ):
                outcome = executor.execute_code(
                    "def main(params):\n    return 1\n", "requests\n", {}, False
                )

        self.assertEqual(popen.call_count, 2)
        install_cmd = popen.call_args_list[0].args[0]
        run_cmd = popen.call_args_list[1].args[0]
        self.assertEqual(install_cmd[install_cmd.index("--entrypoint") + 1], "uv")
        self.assertEqual(install_cmd[install_cmd.index("--network") + 1], "bridge")
        self.assertEqual(run_cmd[run_cmd.index("--network") + 1], "none")
        self.assertEqual(outcome.install_tool, "uv")
        self.assertIn("Installed 1 package", outcome.install_log)

    def test_uv_failure_retries_with_pip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(executor, "docker_available", return_value=True),
                patch.object(executor, "resolve_sandbox_image", return_value="img"),
                patch.object(executor, "_code_run_root", return_value=Path(tmp)),
                patch.object(executor, "_resolve_workspace_mount", return_value=["--mount", "m"]),
                patch.object(
                    executor.subprocess,
                    "Popen",
                    side_effect=[
                        _fake_proc("", "uv exploded", returncode=1),
                        _fake_proc("Successfully installed requests"),
                        _fake_proc(_OK_ENVELOPE),
                    ],
                ) as popen,
            ):
                outcome = executor.execute_code(
                    "def main(params):\n    return 1\n", "requests\n", {}, False
                )

        self.assertEqual(popen.call_count, 3)
        retry_cmd = popen.call_args_list[1].args[0]
        self.assertEqual(retry_cmd[retry_cmd.index("--entrypoint") + 1], "pip")
        self.assertEqual(outcome.install_tool, "pip")
        self.assertIn("uv exploded", outcome.install_log)

    def test_install_failing_under_both_tools_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(executor, "docker_available", return_value=True),
                patch.object(executor, "resolve_sandbox_image", return_value="img"),
                patch.object(executor, "_code_run_root", return_value=Path(tmp)),
                patch.object(executor, "_resolve_workspace_mount", return_value=["--mount", "m"]),
                patch.object(
                    executor.subprocess,
                    "Popen",
                    side_effect=[
                        _fake_proc("", "uv failed", returncode=1),
                        _fake_proc("", "pip failed", returncode=1),
                    ],
                ),
            ):
                with self.assertRaises(RuntimeError) as ctx:
                    executor.execute_code(
                        "def main(params):\n    return 1\n", "nope-not-real\n", {}, False
                    )

        self.assertIn("pip failed", str(ctx.exception))

    def test_run_directory_is_removed_even_when_the_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(executor, "docker_available", return_value=True),
                patch.object(executor, "resolve_sandbox_image", return_value="img"),
                patch.object(executor, "_code_run_root", return_value=root),
                patch.object(executor, "_resolve_workspace_mount", return_value=["--mount", "m"]),
                patch.object(
                    executor.subprocess,
                    "Popen",
                    side_effect=[_fake_proc("ok"), _fake_proc("", "", returncode=125)],
                ),
            ):
                with self.assertRaises(RuntimeError):
                    executor.execute_code(
                        "def main(params):\n    return 1\n", "requests\n", {}, False
                    )
            self.assertEqual(list(root.iterdir()), [])

    def test_sandbox_start_failure_is_not_treated_as_a_result(self) -> None:
        with (
            patch.object(executor, "docker_available", return_value=True),
            patch.object(executor, "resolve_sandbox_image", return_value="img"),
            patch.object(
                executor.subprocess, "Popen", return_value=_fake_proc("", "no such image", 127)
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                executor.execute_code("def main(params):\n    return 1\n", "", {}, False)
        self.assertIn("failed to start", str(ctx.exception))

    def test_runner_error_envelope_becomes_a_value_error(self) -> None:
        envelope = json.dumps({"success": False, "error": "ValueError: boom", "logs": "before\n"})
        with (
            patch.object(executor, "docker_available", return_value=True),
            patch.object(executor, "resolve_sandbox_image", return_value="img"),
            patch.object(executor.subprocess, "Popen", return_value=_fake_proc(envelope)),
        ):
            with self.assertRaises(ValueError) as ctx:
                executor.execute_code("def main(params):\n    raise ValueError\n", "", {}, False)
        self.assertIn("ValueError: boom", str(ctx.exception))
        self.assertIn("before", str(ctx.exception))

    def test_run_timeout_kills_and_force_removes_the_container(self) -> None:
        proc = MagicMock()
        proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=60)
        with (
            patch.object(executor, "docker_available", return_value=True),
            patch.object(executor, "resolve_sandbox_image", return_value="img"),
            patch.object(executor.subprocess, "Popen", return_value=proc),
            patch.object(executor, "_force_remove_container") as force_remove,
        ):
            with self.assertRaises(TimeoutError):
                executor.execute_code("def main(params):\n    return 1\n", "", {}, False)
        proc.kill.assert_called_once()
        force_remove.assert_called_once()

    def test_unparseable_stdout_is_reported(self) -> None:
        with (
            patch.object(executor, "docker_available", return_value=True),
            patch.object(executor, "resolve_sandbox_image", return_value="img"),
            patch.object(executor.subprocess, "Popen", return_value=_fake_proc("not json")),
        ):
            with self.assertRaises(ValueError) as ctx:
                executor.execute_code("def main(params):\n    return 1\n", "", {}, False)
        self.assertIn("not json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
