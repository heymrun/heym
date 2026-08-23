"""Steps toggled off in the editor stay in the workflow but never run."""

import unittest
from unittest.mock import patch

from app.services.playwright_code_generator import active_steps, generate_playwright_code
from app.services.workflow_executor import WorkflowExecutor


def _executor(node_data: dict) -> WorkflowExecutor:
    return WorkflowExecutor(
        nodes=[{"id": "pw1", "type": "playwright", "data": node_data}],
        edges=[],
    )


class ActiveStepsTests(unittest.TestCase):
    def test_missing_flag_keeps_the_step(self) -> None:
        steps = [{"action": "refresh"}, {"action": "wait", "timeout": 1}]
        self.assertEqual(active_steps(steps), steps)

    def test_disabled_steps_are_dropped(self) -> None:
        steps = [{"action": "refresh", "disabled": True}, {"action": "wait", "timeout": 1}]
        self.assertEqual(active_steps(steps), [{"action": "wait", "timeout": 1}])

    def test_none_is_empty(self) -> None:
        self.assertEqual(active_steps(None), [])


class DisabledStepCodegenTests(unittest.TestCase):
    def test_disabled_step_is_not_generated(self) -> None:
        code = generate_playwright_code(
            [
                {"action": "navigate", "url": "https://example.com"},
                {"action": "navigate", "url": "https://skipped.example", "disabled": True},
                {"action": "refresh"},
            ]
        )
        compile(code, "<generated>", "exec")
        self.assertIn("page.goto('https://example.com')", code)
        self.assertNotIn("skipped.example", code)
        self.assertIn("page.reload()", code)

    def test_disabled_ai_step_does_not_pull_in_the_ai_runtime(self) -> None:
        code = generate_playwright_code(
            [
                {"action": "wait", "timeout": 1},
                {
                    "action": "aiStep",
                    "instructions": "click login",
                    "credentialId": "cred-1",
                    "model": "gpt-4o-mini",
                    "disabled": True,
                },
            ]
        )
        compile(code, "<generated>", "exec")
        self.assertNotIn("click login", code)
        self.assertNotIn("_heym_urlopen_json", code)

    def test_disabled_auth_fallback_step_is_dropped(self) -> None:
        code = generate_playwright_code(
            [{"action": "navigate", "url": "https://example.com"}],
            auth_enabled=True,
            auth_check_selector="#profile",
            auth_fallback_steps=[
                {"action": "fill", "selector": "#user", "value": "someone"},
                {"action": "fill", "selector": "#skipme", "value": "x", "disabled": True},
            ],
        )
        compile(code, "<generated>", "exec")
        self.assertIn("#user", code)
        self.assertNotIn("#skipme", code)


class DisabledStepExecutionTests(unittest.TestCase):
    def _generated_code(self, node_data: dict) -> str:
        executor = _executor(node_data)
        captured: dict[str, str] = {}

        def fake_build(code: str, *args: object, **kwargs: object) -> str:
            captured["code"] = code
            return "print('noop')"

        with (
            patch("app.services.workflow_executor._build_playwright_script", fake_build),
            patch("subprocess.Popen") as popen,
        ):
            popen.return_value.communicate.return_value = ('{"status": "ok"}', "")
            popen.return_value.returncode = 0
            executor._execute_playwright_node(node_data, {}, "pw1", "browser")
        return captured["code"]

    def test_execution_skips_disabled_steps(self) -> None:
        node_data = {
            "label": "browser",
            "playwrightMode": "steps",
            "playwrightSteps": [
                {"action": "navigate", "url": "https://example.com"},
                {"action": "navigate", "url": "https://skipped.example", "disabled": True},
            ],
        }
        code = self._generated_code(node_data)
        self.assertIn("https://example.com", code)
        self.assertNotIn("skipped.example", code)

    def test_all_steps_disabled_reports_a_clear_error(self) -> None:
        node_data = {
            "label": "browser",
            "playwrightMode": "steps",
            "playwrightSteps": [
                {"action": "navigate", "url": "https://example.com", "disabled": True}
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            _executor(node_data)._execute_playwright_node(node_data, {}, "pw1", "browser")
        self.assertIn("disabled", str(ctx.exception).lower())

    def test_all_steps_disabled_does_not_fall_back_to_custom_code(self) -> None:
        # A legacy node carrying both steps and code must not start running the code
        # path just because every step was switched off.
        node_data = {
            "label": "browser",
            "playwrightSteps": [
                {"action": "navigate", "url": "https://example.com", "disabled": True}
            ],
            "playwrightCode": "print('legacy')",
        }
        with self.assertRaises(ValueError) as ctx:
            _executor(node_data)._execute_playwright_node(node_data, {}, "pw1", "browser")
        self.assertIn("disabled", str(ctx.exception).lower())

    def test_auth_first_step_check_uses_enabled_steps(self) -> None:
        # The disabled leading step must not satisfy (or break) the navigate-first rule.
        node_data = {
            "label": "browser",
            "playwrightMode": "steps",
            "playwrightAuthEnabled": True,
            "playwrightAuthCheckSelector": "#profile",
            "playwrightSteps": [
                {"action": "click", "selector": "#nope", "disabled": True},
                {"action": "navigate", "url": "https://example.com"},
            ],
        }
        code = self._generated_code(node_data)
        self.assertIn("https://example.com", code)
        self.assertNotIn("#nope", code)


if __name__ == "__main__":
    unittest.main()
