"""Live sandbox runs against a real cluster. Skipped unless HEYM_K8S_LIVE_CONTEXT is set.

    docker compose build backend
    HEYM_K8S_LIVE_CONTEXT=orbstack uv run pytest tests/live/test_k8s_sandbox_live.py -v

Runs from the host with the current kubeconfig context, so it covers the sites
without a workspace. Milestone 4's smoke script covers the rest in-cluster.
"""

import json
import os
import subprocess
import unittest
import uuid
from unittest.mock import patch

LIVE = os.environ.get("HEYM_K8S_LIVE_CONTEXT", "")
IMAGE = os.environ.get("HEYM_K8S_LIVE_IMAGE", "heym-backend:local")
_DENY_OFFLINE = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "heym-sandbox-offline"},
    "spec": {
        "podSelector": {"matchLabels": {"heym.run/network": "none"}},
        "policyTypes": ["Egress"],
        "egress": [],
    },
}


def _kubectl(*args: str) -> None:
    subprocess.run(["kubectl", "--context", LIVE, *args], check=True, capture_output=True)


@unittest.skipUnless(LIVE, "set HEYM_K8S_LIVE_CONTEXT to run live Kubernetes sandbox tests")
class LiveSandboxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        current = subprocess.run(
            ["kubectl", "config", "current-context"], capture_output=True, text=True
        ).stdout.strip()
        if current != LIVE:
            # The backend reads the kubeconfig's current context, so it must be the named one.
            raise unittest.SkipTest(f"current kubectl context is {current!r}, not {LIVE!r}")

    def _namespace(self, *, deny_offline: bool) -> str:
        name = f"heym-sb-live-{uuid.uuid4().hex[:8]}"
        _kubectl("create", "namespace", name)
        self.addCleanup(_kubectl, "delete", "namespace", name, "--wait=false")
        _kubectl("label", "namespace", name, "pod-security.kubernetes.io/enforce=restricted")
        if deny_offline:
            subprocess.run(
                ["kubectl", "--context", LIVE, "-n", name, "apply", "-f", "-"],
                input=json.dumps(_DENY_OFFLINE),
                text=True,
                check=True,
                capture_output=True,
            )
        return name

    def _use(self, namespace: str) -> None:
        from app.services.sandbox import reset_sandbox_manager

        env = {
            "HEYM_SANDBOX_BACKEND": "kubernetes",
            "HEYM_SANDBOX_K8S_NAMESPACE": namespace,
            "HEYM_PYTHON_TOOL_IMAGE": IMAGE,
            "HEYM_PLAYWRIGHT_SANDBOX_IMAGE": IMAGE,
            "HEYM_MCP_STDIO_IMAGE": IMAGE,
            "HEYM_PYTHON_TOOL_SANDBOX": "auto",
            "HEYM_MCP_STDIO_SANDBOX": "auto",
            "HEYM_PLAYWRIGHT_SANDBOX_PYTHON": "/app/.venv/bin/python",
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        reset_sandbox_manager()
        self.addCleanup(reset_sandbox_manager)

    def test_one_shot_sites_under_restricted(self) -> None:
        from app.services.code_formatter import format_python
        from app.services.code_python_executor import execute_code
        from app.services.python_tool_executor import execute_tool

        self._use(self._namespace(deny_offline=True))
        self.assertEqual(execute_tool("def f(a):\n    return a * 2\n", "f", {"a": 21}, 60), 42)
        self.assertEqual(format_python("x=1\n"), "x = 1\n")
        result = execute_code(
            "def main(params):\n    return params['n'] + 1\n", "", {"n": 1}, False
        )
        self.assertEqual(result.result, 2)

    def test_offline_sites_fail_closed_without_a_policy(self) -> None:
        from app.services.python_tool_executor import execute_tool
        from app.services.sandbox.errors import SandboxConfigError

        self._use(self._namespace(deny_offline=False))
        with self.assertRaisesRegex(SandboxConfigError, "NetworkPolicy"):
            execute_tool("def f():\n    return 1\n", "f", {}, 60)

    def test_playwright_runs_as_non_root(self) -> None:
        from app.services.playwright_sandbox import run_script

        self._use(self._namespace(deny_offline=True))
        code, out, err = run_script("import os\nprint(os.getuid())\n", 120)
        self.assertEqual((code, out.strip()), (0, "65534"), err)

    def test_mcp_stdio_bridge_round_trip(self) -> None:
        from app.services.mcp_stdio_sandbox import build_sandboxed_command

        self._use(self._namespace(deny_offline=True))
        echo = "import sys\nfor line in sys.stdin:\n    sys.stdout.write(line.upper()); sys.stdout.flush()\n"
        command = build_sandboxed_command("python", ["-c", echo], {"K": "v"})
        result = subprocess.run(
            command.argv,
            input="ping\n",
            env={**os.environ, **command.env},
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(result.stdout, "PING\n", result.stderr)
