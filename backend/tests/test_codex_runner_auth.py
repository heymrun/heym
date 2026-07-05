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
        auth_path = self.workspace / ".codex-home" / "auth.json"
        self.assertTrue(auth_path.exists())
        payload = json.loads(auth_path.read_text())
        self.assertIsNone(payload["OPENAI_API_KEY"])
        self.assertEqual(payload["tokens"]["access_token"], "at-1")
        self.assertEqual(payload["tokens"]["refresh_token"], "rt-1")
        self.assertEqual(payload["tokens"]["account_id"], "acct-1")

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

    def _capture_exec_cmd(self, model: str) -> list[str]:
        import subprocess

        captured: dict[str, list[str]] = {}

        def fake_run_command(cmd: list[str], **_kw: object) -> subprocess.CompletedProcess:
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

        self.runner._run_command = fake_run_command  # type: ignore[method-assign]
        self.runner._run_codex_exec(
            workspace=self.workspace,
            prompt="do it",
            timeout_seconds=60.0,
            resume_thread_id=None,
            codex_access_token="",
            model=model,
        )
        return captured["cmd"]

    def test_model_flag_added_when_set(self) -> None:
        cmd = self._capture_exec_cmd("gpt-5.4")
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-5.4")

    def test_model_flag_omitted_when_empty(self) -> None:
        self.assertNotIn("--model", self._capture_exec_cmd(""))

    def test_exec_uses_valid_flags(self) -> None:
        # codex exec has no --ask-for-approval flag; approval is set via config override.
        cmd = self._capture_exec_cmd("")
        self.assertNotIn("--ask-for-approval", cmd)
        self.assertIn("-c", cmd)
        self.assertIn('approval_policy="never"', cmd)
        self.assertIn("--sandbox", cmd)


if __name__ == "__main__":
    unittest.main()
