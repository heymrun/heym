import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.services.codex_runner_service import CodexRunnerService


class TestCodexRunnerAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.runner = CodexRunnerService(cli_command="codex", workspace_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_chatgpt_auth_creates_auth_json(self) -> None:
        self.runner._write_chatgpt_auth(
            self.workspace,
            {
                "auth_mode": "chatgpt",
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "id_token": "idt-1",
                "account_id": "acct-1",
            },
        )
        auth_path = self.runner._codex_home_dir(self.workspace) / "auth.json"
        self.assertTrue(auth_path.exists())
        payload = json.loads(auth_path.read_text())
        self.assertEqual(payload["auth_mode"], "chatgpt")
        self.assertIsNone(payload["OPENAI_API_KEY"])
        self.assertEqual(payload["tokens"]["access_token"], "at-1")
        self.assertEqual(payload["tokens"]["refresh_token"], "rt-1")
        self.assertEqual(payload["tokens"]["account_id"], "acct-1")

    def test_codex_home_is_outside_repo_workspace(self) -> None:
        # CODEX_HOME (auth.json token bundle) must never live inside the cloned repo.
        home = self.runner._codex_home_dir(self.workspace)
        self.assertFalse(str(home).startswith(str(self.workspace) + "/"))
        env = self.runner._codex_env(self.workspace, "")
        self.assertFalse(env["CODEX_HOME"].startswith(str(self.workspace) + "/"))

    def test_write_chatgpt_auth_requires_tokens(self) -> None:
        with self.assertRaises(ValueError):
            self.runner._write_chatgpt_auth(self.workspace, {"auth_mode": "chatgpt"})

    def test_authenticate_chatgpt_skips_cli_login(self) -> None:
        self.runner._codex_login = MagicMock()  # type: ignore[method-assign]
        self.runner._write_chatgpt_auth = MagicMock()  # type: ignore[method-assign]
        self.runner._authenticate(
            self.workspace,
            {"auth_mode": "chatgpt", "access_token": "at"},
            "at",
            60.0,
        )
        self.runner._write_chatgpt_auth.assert_called_once()
        self.runner._codex_login.assert_not_called()

    def test_authenticate_access_token_uses_cli_login(self) -> None:
        self.runner._codex_login = MagicMock()  # type: ignore[method-assign]
        self.runner._write_chatgpt_auth = MagicMock()  # type: ignore[method-assign]
        self.runner._authenticate(self.workspace, {}, "raw-token", 60.0)
        self.runner._codex_login.assert_called_once()
        self.runner._write_chatgpt_auth.assert_not_called()

    def test_exec_token_empty_for_chatgpt(self) -> None:
        self.assertEqual(CodexRunnerService._exec_token({"auth_mode": "chatgpt"}, "at"), "")
        self.assertEqual(CodexRunnerService._exec_token({}, "raw"), "raw")

    def test_codex_env_omits_empty_token(self) -> None:
        env = self.runner._codex_env(self.workspace, "")
        self.assertNotIn("CODEX_ACCESS_TOKEN", env)
        env_with = self.runner._codex_env(self.workspace, "tok")
        self.assertEqual(env_with["CODEX_ACCESS_TOKEN"], "tok")

    def test_missing_codex_cli_gives_clear_error(self) -> None:
        runner = CodexRunnerService(cli_command="definitely-not-a-real-codex-binary")
        with self.assertRaises(ValueError) as ctx:
            runner._run_command([runner.cli_command, "exec"], cwd=self.workspace)
        self.assertIn("Codex CLI is not installed", str(ctx.exception))

    def test_missing_other_binary_names_the_binary(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.runner._run_command(["definitely-not-git-xyz", "status"], cwd=self.workspace)
        self.assertIn("definitely-not-git-xyz", str(ctx.exception))

    def _run_exec_with(
        self,
        model: str = "",
        *,
        returncode: int = 0,
        stdout: str = "{}",
        stderr: str = "",
        resume_thread_id: str | None = None,
    ) -> list[str]:
        import subprocess
        from unittest.mock import patch

        captured: dict[str, list[str]] = {}

        def fake_run(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess:
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

        with patch("app.services.codex_runner_service.subprocess.run", side_effect=fake_run):
            self.runner._run_codex_exec(
                workspace=self.workspace,
                prompt="do it",
                timeout_seconds=60.0,
                resume_thread_id=resume_thread_id,
                codex_access_token="",
                model=model,
            )
        return captured["cmd"]

    def test_resume_command_uses_valid_flags(self) -> None:
        # `codex exec resume` has no --sandbox flag; sandbox is set via config, and the session id
        # is a positional before the prompt.
        cmd = self._run_exec_with("gpt-5.4", resume_thread_id="sess-123")
        self.assertEqual(cmd[:3], [self.runner.cli_command, "exec", "resume"])
        self.assertNotIn("--sandbox", cmd)
        self.assertIn('sandbox_mode="workspace-write"', cmd)
        self.assertIn("sess-123", cmd)
        self.assertLess(cmd.index("sess-123"), cmd.index("do it"))

    def test_model_flag_added_when_set(self) -> None:
        cmd = self._run_exec_with("gpt-5.4")
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-5.4")

    def test_model_flag_omitted_when_empty(self) -> None:
        self.assertNotIn("--model", self._run_exec_with(""))

    def test_exec_uses_valid_flags(self) -> None:
        # codex exec has no --ask-for-approval flag; approval is set via config override.
        cmd = self._run_exec_with("")
        self.assertNotIn("--ask-for-approval", cmd)
        self.assertIn("-c", cmd)
        self.assertIn('approval_policy="never"', cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("--disable", cmd)
        self.assertEqual(cmd[cmd.index("--disable") + 1], "plugins")

    def test_exec_surfaces_stdout_error_over_stdin_noise(self) -> None:
        stdout = '{"type":"error","message":"401 Unauthorized"}'
        with self.assertRaises(ValueError) as ctx:
            self._run_exec_with(
                returncode=1, stdout=stdout, stderr="Reading additional input from stdin...\n"
            )
        self.assertIn("401 Unauthorized", str(ctx.exception))
        self.assertNotIn("Reading additional input", str(ctx.exception))

    def test_runner_scaffolding_excluded_from_git(self) -> None:
        import subprocess

        ws = self.workspace
        subprocess.run(["git", "init", "-q", str(ws)], check=True)
        (ws / ".codex-home").mkdir()
        (ws / ".codex-home" / "auth.json").write_text("secret-token")
        (ws / ".codex-output-schema.json").write_text("{}")
        (ws / "real.txt").write_text("x")
        self.runner._exclude_runner_files(ws)
        status = subprocess.run(
            ["git", "-C", str(ws), "status", "--porcelain"],
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn("real.txt", status)
        self.assertNotIn(".codex-home", status)
        self.assertNotIn(".codex-output-schema.json", status)

    def test_exec_strips_stdin_noise_from_stderr(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run_exec_with(
                returncode=1,
                stdout="",
                stderr="Reading additional input from stdin...\nboom: real failure\n",
            )
        self.assertIn("real failure", str(ctx.exception))
        self.assertNotIn("Reading additional input", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
