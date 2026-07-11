"""Security tests for the skill Python sandbox (GHSA-hcv7-mg77-pg73).

Skill Python code is untrusted, so it must run through the same fail-closed,
Docker-mandated path as user-defined Python tools -- with no Docker socket, no
backend secrets, and no ability to write outside its throwaway workspace -- while
keeping the features skills legitimately use (network egress, generated output
files, Heym Drive access).
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app.services.skill_python_executor as executor
from app.services.skill_python_executor import (
    SkillExecutionResult,
    execute_skill_python,
)


def _skill(source: str) -> list[dict[str, str]]:
    return [{"path": "main.py", "content": source}]


class SkillSandboxModeTest(unittest.TestCase):
    """Backend selection logic: auto fails closed, docker required, subprocess opt-in."""

    def setUp(self) -> None:
        # The cached docker probe must not leak between tests.
        executor._docker_available_cache = None

    def tearDown(self) -> None:
        executor._docker_available_cache = None

    def test_auto_fails_closed_when_docker_unavailable(self) -> None:
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "auto"}),
            mock.patch.object(executor, "_docker_available", return_value=False),
            mock.patch.object(
                executor, "_execute_skill_subprocess", side_effect=AssertionError
            ) as sub,
            mock.patch.object(
                executor, "_execute_skill_docker", side_effect=AssertionError
            ) as dock,
        ):
            with self.assertRaises(RuntimeError):
                execute_skill_python(_skill("print('{}')"), {})
            sub.assert_not_called()
            dock.assert_not_called()

    def test_auto_uses_docker_when_available(self) -> None:
        sentinel = SkillExecutionResult(output={"ok": True})
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "auto"}),
            mock.patch.object(executor, "_docker_available", return_value=True),
            mock.patch.object(executor, "_resolve_image", return_value="heym-backend"),
            mock.patch.object(executor, "_execute_skill_docker", return_value=sentinel) as dock,
            mock.patch.object(
                executor, "_execute_skill_subprocess", side_effect=AssertionError
            ) as sub,
        ):
            self.assertIs(execute_skill_python(_skill("print('{}')"), {}), sentinel)
            dock.assert_called_once()
            sub.assert_not_called()

    def test_docker_mode_requires_docker(self) -> None:
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "docker"}),
            mock.patch.object(executor, "_docker_available", return_value=False),
        ):
            with self.assertRaises(RuntimeError):
                execute_skill_python(_skill("print('{}')"), {})

    def test_subprocess_mode_never_touches_docker(self) -> None:
        sentinel = SkillExecutionResult(output={"ok": True})
        with (
            mock.patch.dict(os.environ, {"HEYM_PYTHON_TOOL_SANDBOX": "subprocess"}),
            mock.patch.object(executor, "_execute_skill_subprocess", return_value=sentinel) as sub,
            mock.patch.object(
                executor, "_execute_skill_docker", side_effect=AssertionError
            ) as dock,
            mock.patch.object(executor, "_docker_available", side_effect=AssertionError),
        ):
            self.assertIs(execute_skill_python(_skill("print('{}')"), {}), sentinel)
            sub.assert_called_once()
            dock.assert_not_called()


class SkillDockerCommandTest(unittest.TestCase):
    """The skill container must be hardened, socket-free, yet keep egress + a workspace."""

    MOUNT_POINT = Path("/app/data/codex-workspaces")
    RUN_DIR = Path("/app/data/codex-workspaces/_skill-workspaces/_skills/abc")
    REL = "_skill-workspaces/_skills/abc"

    def _build(self) -> list[str]:
        with mock.patch.dict(
            os.environ, {"HEYM_SKILL_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces"}
        ):
            return executor._build_skill_docker_command(
                "heym-backend",
                "heym-skill-test",
                self.MOUNT_POINT,
                self.RUN_DIR,
                "main.py",
            )

    def test_isolation_flags_present(self) -> None:
        cmd = self._build()
        for flag in (
            "--rm",
            "--read-only",
            "--cap-drop",
            "--security-opt",
            "--pids-limit",
            "--memory",
            "--cpus",
            "--user",
        ):
            self.assertIn(flag, cmd)
        self.assertIn("ALL", cmd)
        self.assertIn("no-new-privileges", cmd)
        # Non-root by default.
        self.assertEqual(cmd[cmd.index("--user") + 1], "65534:65534")

    def test_no_docker_socket_exposed(self) -> None:
        cmd = self._build()
        joined = " ".join(cmd)
        self.assertNotIn("docker.sock", joined)
        self.assertNotIn("/var/run", joined)
        self.assertNotIn("-v", cmd)
        self.assertNotIn("--volume", cmd)

    def test_network_egress_preserved(self) -> None:
        # Unlike the Python-tool sandbox (network none), skills keep egress.
        cmd = self._build()
        self.assertEqual(cmd[cmd.index("--network") + 1], "bridge")

    def test_workspace_mounted_via_shared_volume_subpath(self) -> None:
        # A named volume mount places the volume root at the destination, so the
        # sibling must mount only this run's subpath at the run dir (per-run
        # isolation + correct path alignment), not the whole codex volume.
        cmd = self._build()
        self.assertIn("--mount", cmd)
        mount_spec = cmd[cmd.index("--mount") + 1]
        self.assertIn("type=volume", mount_spec)
        self.assertIn("src=heym-codex-workspaces", mount_spec)
        self.assertIn(f"dst={self.RUN_DIR}", mount_spec)
        self.assertIn(f"volume-subpath={self.REL}", mount_spec)
        # Workdir is the per-run subdir, matching the mount destination.
        self.assertEqual(cmd[cmd.index("--workdir") + 1], str(self.RUN_DIR))

    def test_run_dir_outside_mount_point_is_rejected(self) -> None:
        with mock.patch.dict(
            os.environ, {"HEYM_SKILL_DOCKER_WORKSPACE_VOLUME": "heym-codex-workspaces"}
        ):
            with self.assertRaises(RuntimeError):
                executor._build_skill_docker_command(
                    "heym-backend",
                    "heym-skill-test",
                    Path("/app/data/codex-workspaces"),
                    Path("/elsewhere/_skills/abc"),
                    "main.py",
                )

    def test_entrypoint_runs_skill_with_backend_interpreter(self) -> None:
        cmd = self._build()
        # The skill runs with the backend's own venv interpreter (so backend
        # packages like python-docx are available), not uvicorn and not uv.
        self.assertEqual(cmd[cmd.index("--entrypoint") + 1], executor._skill_interpreter())
        self.assertNotIn("uv", cmd)
        self.assertEqual(cmd[-2:], ["heym-backend", "main.py"])

    def test_backend_secrets_not_forwarded_as_env(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "SECRET_KEY": "app-secret",  # pragma: allowlist secret
                "DATABASE_URL": "postgres://x",  # pragma: allowlist secret
                "OPENAI_API_KEY": "sk-leak",  # pragma: allowlist secret
                "OAUTH_GOOGLE_CLIENT_SECRET": "goog-leak",  # pragma: allowlist secret
            },
        ):
            cmd = self._build()
        joined = " ".join(cmd)
        for secret in ("app-secret", "postgres://x", "sk-leak", "goog-leak"):
            self.assertNotIn(secret, joined)


class SkillEnvAllowlistTest(unittest.TestCase):
    """Only non-secret operational vars reach the skill; proxies survive for egress."""

    def test_denies_secrets_allows_toolchain_and_proxy(self) -> None:
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/x",
            "LANG": "en_US.UTF-8",
            "PYTHONPATH": "/x",
            "UV_CACHE_DIR": "/c",
            "HTTPS_PROXY": "http://proxy:8080",
            "REQUESTS_CA_BUNDLE": "/etc/ca.pem",
            "SECRET_KEY": "app-secret",  # pragma: allowlist secret
            "DATABASE_URL": "postgres://x",  # pragma: allowlist secret
            "ENCRYPTION_KEY": "enc",  # pragma: allowlist secret
            "OPENAI_API_KEY": "sk-leak",  # pragma: allowlist secret
            "OAUTH_GOOGLE_CLIENT_SECRET": "goog",  # pragma: allowlist secret
            "AWS_SECRET_ACCESS_KEY": "aws",  # pragma: allowlist secret
        }
        with mock.patch.dict(os.environ, env, clear=True):
            safe = executor._safe_env()
        for key in (
            "PATH",
            "HOME",
            "LANG",
            "PYTHONPATH",
            "UV_CACHE_DIR",
            "HTTPS_PROXY",
            "REQUESTS_CA_BUNDLE",
        ):
            self.assertIn(key, safe)
        for key in (
            "SECRET_KEY",
            "DATABASE_URL",
            "ENCRYPTION_KEY",
            "OPENAI_API_KEY",
            "OAUTH_GOOGLE_CLIENT_SECRET",
            "AWS_SECRET_ACCESS_KEY",
        ):
            self.assertNotIn(key, safe)


class SkillPathTraversalTest(unittest.TestCase):
    """Skill file paths come verbatim from node data and must not escape the workspace."""

    def test_absolute_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                executor._write_skill_file(Path(tmp), {"path": "/etc/evil.py", "content": "x"})
            self.assertFalse((Path(tmp) / "etc").exists())

    def test_parent_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            with self.assertRaises(ValueError):
                executor._write_skill_file(root, {"path": "../escape.py", "content": "x"})
            self.assertFalse((Path(tmp) / "escape.py").exists())

    def test_nul_and_empty_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("", "  ", "a\x00b.py"):
                with self.assertRaises(ValueError):
                    executor._write_skill_file(Path(tmp), {"path": bad, "content": "x"})

    def test_nested_relative_path_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor._write_skill_file(root, {"path": "pkg/util.py", "content": "ok"})
            self.assertEqual((root / "pkg" / "util.py").read_text(), "ok")


class SkillOutputCollectionTest(unittest.TestCase):
    """The backend collects output files; a skill-planted symlink must not be followed."""

    def test_symlink_in_output_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "_output_files"
            output_dir.mkdir()
            secret = root / "host_secret.txt"
            secret.write_text("HOST-FILESYSTEM-SECRET")
            (output_dir / "leak.txt").symlink_to(secret)
            (output_dir / "real.txt").write_text("generated")

            generated, hitl = executor._collect_output_files(output_dir)
            self.assertIsNone(hitl)
            names = {f["filename"] for f in generated}
            self.assertIn("real.txt", names)
            self.assertNotIn("leak.txt", names)
            for f in generated:
                self.assertNotIn(b"HOST-FILESYSTEM-SECRET", f["file_bytes"])

    def test_symlinked_hitl_sentinel_is_not_followed(self) -> None:
        # The HITL sentinel is read by the backend too, so a symlinked
        # _hitl_request.json must not be followed to read a host file.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "_output_files"
            output_dir.mkdir()
            secret = root / "host_secret.json"
            secret.write_text('{"draft_text": "HOST-SECRET", "summary": "leak"}')
            (output_dir / "_hitl_request.json").symlink_to(secret)

            generated, hitl = executor._collect_output_files(output_dir)
            self.assertIsNone(hitl)  # symlinked sentinel ignored, not honored

    def test_real_hitl_sentinel_is_honored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "_output_files"
            output_dir.mkdir()
            (output_dir / "_hitl_request.json").write_text(
                '{"draft_text": "please review", "summary": "s"}'
            )
            generated, hitl = executor._collect_output_files(output_dir)
            self.assertIsNotNone(hitl)
            self.assertEqual(hitl["draft_text"], "please review")


class SkillSubprocessFeatureTest(unittest.TestCase):
    """The local subprocess path still executes skills and returns generated files."""

    def setUp(self) -> None:
        self._prev = os.environ.get("HEYM_PYTHON_TOOL_SANDBOX")
        os.environ["HEYM_PYTHON_TOOL_SANDBOX"] = "subprocess"

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("HEYM_PYTHON_TOOL_SANDBOX", None)
        else:
            os.environ["HEYM_PYTHON_TOOL_SANDBOX"] = self._prev

    def test_executes_and_returns_json_output(self) -> None:
        script = (
            "import json, sys\n"
            "data = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'doubled': data.get('n', 0) * 2}))\n"
        )
        result = execute_skill_python(_skill(script), {"n": 21})
        self.assertEqual(result.output["doubled"], 42)

    def test_collects_generated_output_file(self) -> None:
        script = (
            "import os\n"
            "with open(os.path.join(os.environ['_OUTPUT_DIR'], 'note.txt'), 'w') as fh:\n"
            "    fh.write('hello')\n"
            "print('{}')\n"
        )
        result = execute_skill_python(_skill(script), {})
        files = {f["filename"]: f["file_bytes"] for f in result.generated_files}
        self.assertEqual(files.get("note.txt"), b"hello")


class SkillDockerFailClosedTest(unittest.TestCase):
    """A sandbox that cannot start must fail closed, not return a docker error as a result."""

    def _env(self, tmp: str) -> dict[str, str]:
        return {
            "HEYM_SKILL_WORKSPACE_MOUNT": tmp,
            "HEYM_SKILL_WORKSPACE_DIR": str(Path(tmp) / "_skill-workspaces"),
            "HEYM_SKILL_DOCKER_WORKSPACE_VOLUME": "testvol",
        }

    def _fake_proc(self, returncode: int, stdout: str, stderr: str) -> mock.Mock:
        proc = mock.Mock()
        proc.communicate.return_value = (stdout, stderr)
        proc.returncode = returncode
        return proc

    def test_container_start_failure_fails_closed(self) -> None:
        # 125 = docker daemon / `docker run` error (e.g. missing workspace volume),
        # 126 = entrypoint not executable, 127 = entrypoint not found.
        for code in (125, 126, 127):
            with tempfile.TemporaryDirectory() as tmp:
                proc = self._fake_proc(
                    code, "", "docker: Error response from daemon: no such volume"
                )
                build = mock.Mock()
                with (
                    mock.patch.dict(os.environ, self._env(tmp)),
                    mock.patch.object(executor.subprocess, "Popen", return_value=proc),
                    mock.patch.object(executor, "_build_result", build),
                ):
                    with self.assertRaises(RuntimeError):
                        executor._execute_skill_docker(
                            _skill("print('{}')"), {}, 30.0, None, "main.py", "img"
                        )
                    # A start failure must never be packaged as a normal skill result.
                    build.assert_not_called()

    def test_skill_process_nonzero_exit_is_soft_result(self) -> None:
        # The container started and the skill process exited non-zero; that stays
        # a soft result (with stderr), matching the subprocess path.
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._fake_proc(1, '{"partial": true}', "Traceback...")
            with (
                mock.patch.dict(os.environ, self._env(tmp)),
                mock.patch.object(executor.subprocess, "Popen", return_value=proc),
            ):
                result = executor._execute_skill_docker(
                    _skill("print('{}')"), {}, 30.0, None, "main.py", "img"
                )
        self.assertEqual(result.output, {"partial": True})


class SkillImageResolutionTest(unittest.TestCase):
    """The sandbox image must resolve without relying on `docker inspect`."""

    def test_resolves_from_codex_docker_image_when_no_dedicated_image(self) -> None:
        # The single-container release image and Compose set HEYM_CODEX_DOCKER_IMAGE
        # to the backend image; skills reuse it so resolution never depends on the
        # (unreliable) container self-inspection.
        with mock.patch.dict(
            os.environ,
            {
                "HEYM_SKILL_IMAGE": "",
                "HEYM_PYTHON_TOOL_IMAGE": "",
                "HEYM_CODEX_DOCKER_IMAGE": "ghcr.io/heymrun/heym:1.2.3",
            },
        ):
            self.assertEqual(executor._resolve_image(), "ghcr.io/heymrun/heym:1.2.3")

    def test_dedicated_skill_image_takes_precedence(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "HEYM_SKILL_IMAGE": "explicit:image",
                "HEYM_PYTHON_TOOL_IMAGE": "",
                "HEYM_CODEX_DOCKER_IMAGE": "codex:image",
            },
        ):
            self.assertEqual(executor._resolve_image(), "explicit:image")


if __name__ == "__main__":
    unittest.main()
