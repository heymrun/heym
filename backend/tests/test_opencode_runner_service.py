import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.opencode_runner_service import OpenCodeRunnerService


class TestOpenCodeDockerCommand(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_docker_command_is_hardened_with_egress(self):
        cmd = self.svc.build_docker_command(
            image="heym-backend:latest",
            name="heym-oc-abc",
            workspace="/tmp/heym-oc-ws/run1",
            config_dir="/tmp/heym-oc-ws/run1.oc-home",
        )
        joined = " ".join(cmd)
        self.assertIn("--rm", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("ALL", cmd)  # --cap-drop ALL
        self.assertIn("no-new-privileges", joined)
        self.assertIn("--network", cmd)
        idx = cmd.index("--network")
        self.assertEqual(cmd[idx + 1], "bridge")  # egress allowed (NOT "none")
        self.assertTrue(any("dst=/workspace" in a for a in cmd))
        self.assertNotIn("/var/run/docker.sock", joined)

    def test_sandbox_fail_closed_when_docker_unavailable(self):
        with (
            patch.object(self.svc, "_docker_available", return_value=False),
            patch.object(self.svc, "_resolve_image", return_value=None),
        ):
            with self.assertRaises(ValueError) as ctx:
                self.svc._resolve_execution_mode()
            self.assertIn("Docker", str(ctx.exception))

    def test_subprocess_mode_opt_in(self):
        svc = OpenCodeRunnerService(workspace_root="/tmp/x", sandbox_mode="subprocess")
        self.assertEqual(svc._resolve_execution_mode(), "subprocess")


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
