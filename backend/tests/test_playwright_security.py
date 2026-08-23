"""Security regression tests for Playwright node code execution (GHSA-mp23-7m6r-jfw4).

Covers three defenses:
  1. Custom ``playwrightCode`` is off by default and rejected at the execution sink.
  2. Boolean step fields cannot inject Python into the generated step-based script.
  3. The Playwright subprocess does not inherit backend secrets.
"""

import os
import unittest
from unittest.mock import patch

from app.config import settings
from app.services import playwright_sandbox
from app.services.node_execution.nodes.playwright_node import (
    _execute_playwright_node,
    _scrubbed_playwright_subprocess_env,
)
from app.services.playwright_code_generator import generate_playwright_code
from app.services.workflow_executor import WorkflowExecutor

# A payload that would run at generation/exec time if interpolated as raw Python.
_INJECTION = '(__import__("builtins").print("PWNED_MARKER"), False)[1]'


def _executor(node_data: dict) -> WorkflowExecutor:
    return WorkflowExecutor(
        nodes=[{"id": "pw1", "type": "playwright", "data": node_data}],
        edges=[],
    )


class CustomCodeGateTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        self.assertFalse(settings.playwright_custom_code_enabled)

    def test_custom_code_rejected_when_disabled(self) -> None:
        node_data = {"label": "rce", "playwrightCode": "print('hi')"}
        executor = _executor(node_data)
        with patch.object(settings, "playwright_custom_code_enabled", False):
            with self.assertRaises(ValueError) as ctx:
                _execute_playwright_node(executor, node_data, {}, "pw1", "rce")
        self.assertIn("disabled", str(ctx.exception).lower())
        self.assertIn("HEYM_PLAYWRIGHT_CUSTOM_CODE_ENABLED", str(ctx.exception))

    def test_enabled_custom_code_runs_in_docker_sandbox_not_in_process(self) -> None:
        # When enabled with the default (auto) mode, custom code must go through the isolated
        # sandbox, never a bare in-process subprocess.
        node_data = {"label": "rce", "playwrightCode": "print('hi')"}
        executor = _executor(node_data)
        with (
            patch.object(settings, "playwright_custom_code_enabled", True),
            patch.dict(os.environ, {"HEYM_PLAYWRIGHT_SANDBOX": "auto"}),
            patch("subprocess.Popen", side_effect=AssertionError("must not run in-process")),
            patch.object(
                playwright_sandbox,
                "run_script",
                return_value=(0, '{"status": "ok", "results": {"x": 1}}', ""),
            ) as mock_run,
        ):
            result = _execute_playwright_node(executor, node_data, {}, "pw1", "rce")
        mock_run.assert_called_once()
        self.assertEqual(result["results"]["x"], 1)

    def test_enabled_custom_code_fails_closed_when_sandbox_unavailable(self) -> None:
        node_data = {"label": "rce", "playwrightCode": "print('hi')"}
        executor = _executor(node_data)
        with (
            patch.object(settings, "playwright_custom_code_enabled", True),
            patch.dict(os.environ, {"HEYM_PLAYWRIGHT_SANDBOX": "auto"}),
            patch.object(playwright_sandbox, "_docker_available", return_value=False),
            patch("subprocess.Popen", side_effect=AssertionError("must not run in-process")),
        ):
            with self.assertRaises(ValueError) as ctx:
                _execute_playwright_node(executor, node_data, {}, "pw1", "rce")
        self.assertIn("Docker sandbox", str(ctx.exception))

    def test_subprocess_mode_opts_custom_code_back_in_process(self) -> None:
        # Explicit subprocess mode is the trusted / local-dev escape hatch.
        node_data = {"label": "rce", "playwrightCode": "print('hi')"}
        executor = _executor(node_data)
        with (
            patch.object(settings, "playwright_custom_code_enabled", True),
            patch.dict(os.environ, {"HEYM_PLAYWRIGHT_SANDBOX": "subprocess"}),
            patch("subprocess.Popen", side_effect=RuntimeError("REACHED_SINK")),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                _execute_playwright_node(executor, node_data, {}, "pw1", "rce")
        self.assertIn("REACHED_SINK", str(ctx.exception))

    def test_step_based_node_is_not_gated(self) -> None:
        node_data = {
            "label": "safe",
            "playwrightSteps": [{"action": "navigate", "url": "https://example.com"}],
        }
        executor = _executor(node_data)
        with (
            patch.object(settings, "playwright_custom_code_enabled", False),
            patch("subprocess.Popen", side_effect=RuntimeError("REACHED_SINK")),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                _execute_playwright_node(executor, node_data, {}, "pw1", "safe")
        self.assertIn("REACHED_SINK", str(ctx.exception))

    def test_playwright_mode_code_uses_custom_code_even_when_steps_exist(self) -> None:
        """UI Mode=Run Code must prefer playwrightCode over leftover steps."""
        node_data = {
            "label": "rce",
            "playwrightMode": "code",
            "playwrightCode": "print('hi')",
            "playwrightSteps": [{"action": "navigate", "url": "https://example.com"}],
        }
        executor = _executor(node_data)
        with (
            patch.object(settings, "playwright_custom_code_enabled", True),
            patch.dict(os.environ, {"HEYM_PLAYWRIGHT_SANDBOX": "auto"}),
            patch("subprocess.Popen", side_effect=AssertionError("must not run in-process")),
            patch.object(
                playwright_sandbox,
                "run_script",
                return_value=(0, '{"status": "ok", "results": {"via": "code"}}', ""),
            ) as mock_run,
        ):
            result = _execute_playwright_node(executor, node_data, {}, "pw1", "rce")
        mock_run.assert_called_once()
        self.assertEqual(result["results"]["via"], "code")

    def test_playwright_mode_steps_ignores_playwright_code(self) -> None:
        node_data = {
            "label": "safe",
            "playwrightMode": "steps",
            "playwrightCode": "print('should not run')",
            "playwrightSteps": [{"action": "navigate", "url": "https://example.com"}],
        }
        executor = _executor(node_data)
        with (
            patch.object(settings, "playwright_custom_code_enabled", False),
            patch("subprocess.Popen", side_effect=RuntimeError("REACHED_SINK")),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                _execute_playwright_node(executor, node_data, {}, "pw1", "safe")
        self.assertIn("REACHED_SINK", str(ctx.exception))


class GeneratorInjectionTests(unittest.TestCase):
    def test_boolean_fields_cannot_inject_python(self) -> None:
        steps = [
            {
                "action": "aiStep",
                "instructions": "do a thing",
                "credentialId": "cred",
                "model": "gpt-test",
                "sendScreenshot": _INJECTION,
                "logStepsToConsole": _INJECTION,
                "saveStepsForFuture": _INJECTION,
                "autoHealMode": _INJECTION,
            }
        ]
        code = generate_playwright_code(steps)
        # The injection string must not survive into generated code, and the result must
        # still be syntactically valid Python.
        self.assertNotIn("PWNED_MARKER", code)
        self.assertNotIn("__import__", code)
        compile(code, "<generated>", "exec")
        # Coerced falsey values become literal `False`.
        self.assertIn("if False:", code)

    def test_boolean_true_is_preserved(self) -> None:
        steps = [
            {
                "action": "aiStep",
                "instructions": "do a thing",
                "sendScreenshot": True,
                "saveStepsForFuture": True,
            }
        ]
        code = generate_playwright_code(steps)
        compile(code, "<generated>", "exec")
        self.assertIn("if True:", code)


class SubprocessEnvScrubTests(unittest.TestCase):
    def test_secrets_are_stripped_browser_env_kept(self) -> None:
        fake_env = {
            "SECRET_KEY": "super-secret",
            "ENCRYPTION_KEY": "enc-secret",
            "DATABASE_URL": "postgresql://user:pass@db/heym",
            "OPENAI_API_KEY": "sk-live-xxx",
            "PATH": "/usr/bin:/bin",
            "HOME": "/home/heym",
            "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        }
        with patch.dict(os.environ, fake_env, clear=True):
            env = _scrubbed_playwright_subprocess_env()
        for secret in ("SECRET_KEY", "ENCRYPTION_KEY", "DATABASE_URL", "OPENAI_API_KEY"):
            self.assertNotIn(secret, env)
        self.assertEqual(env.get("PATH"), "/usr/bin:/bin")
        self.assertEqual(env.get("HOME"), "/home/heym")
        self.assertEqual(env.get("PLAYWRIGHT_BROWSERS_PATH"), "/ms-playwright")


class PlaywrightSandboxHardeningTests(unittest.TestCase):
    def test_docker_command_is_hardened_and_socketless(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            cmd = playwright_sandbox.build_docker_command("heym-backend:local", "heym-pw-test")
        joined = " ".join(cmd)
        # Throwaway, streamed over stdin, image runs python reading '-'.
        self.assertEqual(cmd[:2], ["docker", "run"])
        self.assertIn("--rm", cmd)
        self.assertEqual(cmd[-1], "-")
        self.assertIn("heym-backend:local", cmd)
        # Hardening flags present.
        self.assertIn("no-new-privileges", cmd)
        self.assertIn("--cap-drop", cmd)
        self.assertIn("ALL", cmd)
        self.assertIn("--pids-limit", cmd)
        self.assertIn("--memory", cmd)
        # No host escape surface: never mount anything, never the docker socket.
        self.assertNotIn("-v", cmd)
        self.assertNotIn("--volume", cmd)
        self.assertNotIn("docker.sock", joined)
        # Runs the venv python via overridden entrypoint (not uvicorn).
        self.assertIn("--entrypoint", cmd)
        entrypoint = cmd[cmd.index("--entrypoint") + 1]
        self.assertTrue(entrypoint.endswith("python"), entrypoint)

    def test_mode_parsing(self) -> None:
        for raw, expected in [
            ("", "auto"),
            ("auto", "auto"),
            ("docker", "docker"),
            ("subprocess", "subprocess"),
            ("bogus", "auto"),
        ]:
            with patch.dict(os.environ, {"HEYM_PLAYWRIGHT_SANDBOX": raw}):
                self.assertEqual(playwright_sandbox.sandbox_mode(), expected)

    def test_require_image_fails_closed_without_docker(self) -> None:
        with patch.object(playwright_sandbox, "_docker_available", return_value=False):
            with self.assertRaises(playwright_sandbox.PlaywrightSandboxUnavailableError):
                playwright_sandbox.require_image()

    def test_user_flag_only_when_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotIn("--user", playwright_sandbox.build_docker_command("img", "n"))
        with patch.dict(os.environ, {"HEYM_PLAYWRIGHT_SANDBOX_USER": "65534:65534"}):
            cmd = playwright_sandbox.build_docker_command("img", "n")
        self.assertIn("--user", cmd)
        self.assertIn("65534:65534", cmd)

    def test_resolve_image_falls_back_to_codex_docker_image(self) -> None:
        # Compose and the GHCR release image set HEYM_CODEX_DOCKER_IMAGE; Playwright
        # must reuse it so resolution does not depend on docker inspect.
        with patch.dict(
            os.environ,
            {
                "HEYM_PLAYWRIGHT_SANDBOX_IMAGE": "",
                "HEYM_CODEX_DOCKER_IMAGE": "ghcr.io/heymrun/heym:1.2.3",
            },
            clear=False,
        ):
            self.assertEqual(
                playwright_sandbox._resolve_image(),
                "ghcr.io/heymrun/heym:1.2.3",
            )

    def test_sandbox_python_prefers_release_layout_when_present(self) -> None:
        with (
            patch.dict(os.environ, {"HEYM_PLAYWRIGHT_SANDBOX_PYTHON": ""}, clear=False),
            patch.object(playwright_sandbox.sys, "executable", "/usr/bin/python3"),
            patch.object(
                playwright_sandbox.os.path,
                "isfile",
                side_effect=lambda p: p == "/app/backend/.venv/bin/python",
            ),
        ):
            self.assertEqual(
                playwright_sandbox._sandbox_python(),
                "/app/backend/.venv/bin/python",
            )


if __name__ == "__main__":
    unittest.main()
