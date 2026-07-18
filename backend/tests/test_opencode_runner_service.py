import json
import tempfile
import unittest
from pathlib import Path

from app.services.opencode_runner_service import OpenCodeRunnerService, OpenCodeRunRequest

_WS = Path("/tmp/heym-oc-ws/run1")


def _request(**overrides) -> OpenCodeRunRequest:
    base = dict(
        repository_url="https://github.com/acme/app",
        base_branch="main",
        task_prompt="fix the tests",
        branch_name="opencode/run",
        publish_mode="diff_only",
        setup_command="",
        timeout_seconds=60.0,
        api_key="sk-secret",
        base_url="",
        github_config={"api_key": "ghp"},
        model="opencode/kimi-k3",
        variant="",
    )
    base.update(overrides)
    return OpenCodeRunRequest(**base)


class TestOpenCodeRunCommand(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(cli_command="opencode", workspace_root="/tmp/heym-oc-ws")

    def test_run_command_shape(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[0], "opencode")
        self.assertEqual(cmd[1], "run")
        self.assertIn("--format", cmd)
        self.assertEqual(cmd[cmd.index("--format") + 1], "json")
        self.assertEqual(cmd[cmd.index("--model") + 1], "opencode/kimi-k3")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "build")
        self.assertNotIn("--variant", cmd)
        self.assertIn("Task:", cmd[-1])

    def test_run_command_pins_workspace_dir(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[cmd.index("--dir") + 1], str(_WS))

    def test_run_command_includes_variant(self):
        cmd = self.svc.build_run_command("opencode/kimi-k3", _request(variant="high"), _WS)
        self.assertEqual(cmd[cmd.index("--variant") + 1], "high")

    def test_run_command_uses_wrapper_cli(self):
        svc = OpenCodeRunnerService(
            cli_command="/usr/local/bin/heym-opencode-docker", workspace_root="/tmp/x"
        )
        cmd = svc.build_run_command("opencode/kimi-k3", _request(), _WS)
        self.assertEqual(cmd[0], "/usr/local/bin/heym-opencode-docker")


class TestOpenCodeAuthConfig(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_write_config_writes_auth_and_opencode_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.svc._write_opencode_config(
                home,
                api_key="sk-secret",
                base_url="https://opencode.ai/zen/go/v1",
                model="opencode/kimi-k3",
            )
            auth = json.loads((home / ".local" / "share" / "opencode" / "auth.json").read_text())
            self.assertEqual(auth["opencode"], {"type": "api", "key": "sk-secret"})
            cfg = json.loads((home / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(cfg["permission"]["edit"], "allow")
            self.assertEqual(cfg["permission"]["bash"], "allow")
            self.assertEqual(cfg["model"], "opencode/kimi-k3")
            options = cfg["provider"]["opencode"]["options"]
            self.assertEqual(options["baseURL"], "https://opencode.ai/zen/go/v1")
            self.assertEqual(options["apiKey"], "sk-secret")

    def test_default_model_when_empty(self):
        self.assertEqual(self.svc._resolve_model(""), "opencode/kimi-k3")
        self.assertEqual(
            self.svc._resolve_model("opencode/deepseek-v4-pro"), "opencode/deepseek-v4-pro"
        )


class TestOpenCodeParser(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_parse_extracts_last_assistant_text(self):
        stdout = "\n".join(
            [
                json.dumps({"type": "message.updated", "role": "assistant", "text": "thinking"}),
                json.dumps({"role": "assistant", "text": "Implemented the change."}),
            ]
        )
        result = self.svc.parse_events(stdout)
        self.assertEqual(result.summary, "Implemented the change.")
        self.assertEqual(result.status, "completed")

    def test_parse_tolerates_non_json_lines(self):
        stdout = "not json\n" + json.dumps({"role": "assistant", "text": "Done."})
        self.assertEqual(self.svc.parse_events(stdout).summary, "Done.")

    def test_parse_ignores_user_role(self):
        stdout = json.dumps({"role": "user", "text": "the task"})
        self.assertNotEqual(self.svc.parse_events(stdout).summary, "the task")

    def test_parse_empty_gives_default_summary(self):
        result = self.svc.parse_events("")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.summary)
