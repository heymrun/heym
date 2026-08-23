"""Regression tests: ``$global.*`` in Playwright step fields must resolve at run time.

Step fields are compiled by ``playwright_code_generator`` into lookups against the flat
``inputs`` dict handed to the Playwright runner, so every expression namespace a user can
reference must be present in that dict. ``vars`` was already injected; ``global`` was not,
so ``$global.secondPage`` silently fell back to the generator's ``https://example.com``
placeholder instead of navigating to the configured URL.
"""

import re
import unittest

from app.services.node_execution.nodes.playwright_node import (
    _build_playwright_script,
    _playwright_subprocess_inputs,
)
from app.services.playwright_code_generator import generate_playwright_code
from app.services.workflow_executor import WorkflowExecutor


def _executor(global_variables_context: dict[str, object] | None = None) -> WorkflowExecutor:
    return WorkflowExecutor(
        nodes=[{"id": "pw1", "type": "playwright", "data": {"label": "playwright"}}],
        edges=[],
        global_variables_context=global_variables_context,
    )


def _resolved_goto_urls(steps: list[dict], inputs: dict) -> list[object]:
    """Evaluate every generated ``page.goto(...)`` argument against the runner inputs."""
    code = generate_playwright_code(steps)
    args = re.findall(r"^\s*page\.goto\((.*)\)$", code, re.MULTILINE)
    return [eval(arg, {"__builtins__": {}}, {"inputs": inputs}) for arg in args]  # noqa: S307


class PlaywrightGlobalNamespaceTests(unittest.TestCase):
    def test_global_namespace_is_injected_into_runner_inputs(self) -> None:
        executor = _executor({"secondPage": "https://heym.run/pricing"})
        runner_inputs = _playwright_subprocess_inputs(executor, {})
        self.assertEqual(runner_inputs["global"]["secondPage"], "https://heym.run/pricing")

    def test_variable_node_values_are_merged_into_global(self) -> None:
        # `$global` mirrors `_build_context`: global variables first, variable-node values win.
        executor = _executor({"secondPage": "https://heym.run/pricing", "keep": "kept"})
        executor.vars = {"secondPage": "https://heym.run/solutions"}
        executor._mark_vars_context_dirty()
        runner_inputs = _playwright_subprocess_inputs(executor, {})
        self.assertEqual(runner_inputs["global"]["secondPage"], "https://heym.run/solutions")
        self.assertEqual(runner_inputs["global"]["keep"], "kept")

    def test_navigate_step_uses_global_url_not_placeholder(self) -> None:
        executor = _executor({"secondPage": "https://heym.run/pricing"})
        runner_inputs = _playwright_subprocess_inputs(executor, {})
        steps = [
            {"action": "navigate", "url": "https://heym.run/solutions"},
            {"action": "navigate", "url": "$global.secondPage"},
        ]
        self.assertEqual(
            _resolved_goto_urls(steps, runner_inputs),
            ["https://heym.run/solutions", "https://heym.run/pricing"],
        )

    def test_upstream_node_named_global_is_not_clobbered(self) -> None:
        executor = _executor({"secondPage": "https://heym.run/pricing"})
        runner_inputs = _playwright_subprocess_inputs(
            executor, {"global": {"ownField": "from-upstream"}}
        )
        self.assertEqual(runner_inputs["global"]["ownField"], "from-upstream")
        self.assertEqual(runner_inputs["global"]["secondPage"], "https://heym.run/pricing")

    def test_vars_namespace_still_resolves(self) -> None:
        executor = _executor()
        executor.vars = {"searchUrl": "https://heym.run/docs"}
        executor._mark_vars_context_dirty()
        runner_inputs = _playwright_subprocess_inputs(executor, {})
        steps = [{"action": "navigate", "url": "$vars.searchUrl"}]
        self.assertEqual(_resolved_goto_urls(steps, runner_inputs), ["https://heym.run/docs"])


if __name__ == "__main__":
    unittest.main()


class PlaywrightScriptInputsLiteralTests(unittest.TestCase):
    """``inputs`` is baked into the generated script as source text, so it has to be a
    Python literal. ``json.dumps`` emits ``true``/``false``/``null``, which parse fine and
    then raise ``NameError`` the moment the script runs. A ``cookies.json`` value held in a
    global variable is full of booleans, so storing one broke every run that used it.
    """

    def _inputs_line(self, inputs: dict) -> str:
        script = _build_playwright_script("pass", inputs)
        line = next(ln for ln in script.splitlines() if ln.startswith("inputs = "))
        return line

    def _roundtrip(self, inputs: dict) -> object:
        namespace: dict[str, object] = {}
        exec(self._inputs_line(inputs), namespace)  # noqa: S102
        return namespace["inputs"]

    def test_booleans_and_null_in_inputs_do_not_raise_name_error(self) -> None:
        cookies = [
            {
                "name": "session",
                "value": "redacted",
                "domain": ".example.com",
                "httpOnly": True,
                "secure": True,
                "sameSite": None,
                "expires": 1787425345.00176,
            }
        ]
        inputs = {"vars": {}, "global": {"exchangeAuth": cookies}}
        self.assertEqual(self._roundtrip(inputs), inputs)

    def test_generated_literal_contains_no_json_keywords(self) -> None:
        line = self._inputs_line({"global": {"a": True, "b": False, "c": None}})
        for json_keyword in ("true", "false", "null"):
            self.assertNotIn(json_keyword, line)
        for python_literal in ("True", "False", "None"):
            self.assertIn(python_literal, line)

    def test_nested_booleans_survive_at_every_depth(self) -> None:
        inputs = {"global": {"a": [{"b": {"c": [True, None, False]}}]}}
        self.assertEqual(self._roundtrip(inputs), inputs)

    def test_script_stays_ascii_so_the_temp_file_write_cannot_fail(self) -> None:
        # The script is written with tempfile's default encoding, so the inputs literal
        # must not be the thing that introduces non-ASCII bytes.
        script = _build_playwright_script(
            "pass", {"global": {"note": "calisti mi \u00e7\u015f\u011f"}}
        )
        script.encode("ascii")

    def test_non_ascii_values_still_round_trip(self) -> None:
        inputs = {"global": {"note": "\u00e7\u015f\u011f\u0131\u00f6\u00fc"}}
        self.assertEqual(self._roundtrip(inputs), inputs)
