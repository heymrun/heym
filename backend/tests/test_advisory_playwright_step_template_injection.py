"""Security regression tests: Playwright step field values must never become Python code.

Follow-up to GHSA-mp23-7m6r-jfw4. A ``$`` reference embedded in a step string field used
to be resolved by a second pass over the already generated script, which spliced the
resolved value into the Python source. A crafted value could close the surrounding string
literal and run code in the backend. Embedded templates are now resolved before code
generation and each final value is written once as a literal. Whole-field references keep
their runtime lookup through ``inputs``.
"""

import ast
import io
import tokenize
import unittest
import uuid
import warnings
from unittest.mock import patch

from app.config import settings
from app.services import playwright_sandbox
from app.services.node_execution.nodes.playwright_node import (
    _execute_playwright_node,
    _resolve_step_templates,
)
from app.services.playwright_code_generator import ResolvedStepValue, _expr_to_python
from app.services.workflow_executor import WorkflowExecutor

# Under the old second pass this value broke out of the generated string literal.
_PAYLOAD = '+(__import__("builtins").print("PWNED_MARKER") or "x")+'


class _ScriptCapturedError(Exception):
    def __init__(self, script: str) -> None:
        super().__init__("script captured")
        self.script = script


def _capture_popen(args: list[str], **_kwargs: object) -> None:
    with open(args[1], encoding="utf-8") as script_file:
        raise _ScriptCapturedError(script_file.read())


def _executor(
    node_data: dict, global_variables_context: dict[str, object] | None = None
) -> WorkflowExecutor:
    executor = WorkflowExecutor(
        nodes=[{"id": "pw1", "type": "playwright", "data": node_data}],
        edges=[],
        global_variables_context=global_variables_context,
    )
    executor.trace_user_id = uuid.uuid4()
    return executor


def _run_and_capture(
    node_data: dict,
    inputs: dict | None = None,
    global_variables_context: dict[str, object] | None = None,
) -> str:
    """Execute the node up to the subprocess sink and return the script it would run."""
    node_data = {"label": "pw", **node_data}
    executor = _executor(node_data, global_variables_context)
    with (
        patch.object(settings, "playwright_custom_code_enabled", False),
        patch("subprocess.Popen", side_effect=_capture_popen),
    ):
        try:
            _execute_playwright_node(executor, node_data, inputs or {}, "pw1", "pw")
        except _ScriptCapturedError as captured:
            return captured.script
    raise AssertionError("the Playwright script never reached the subprocess sink")


def _string_constants(script: str) -> set[str]:
    return {
        node.value
        for node in ast.walk(ast.parse(script))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _code_names(script: str) -> set[str]:
    """Every identifier in the script's code, ignoring the contents of string literals."""
    tokens = tokenize.generate_tokens(io.StringIO(script).readline)
    names = {token.string for token in tokens if token.type == tokenize.NAME}
    # The AST also sees normalized Unicode identifiers and f-string replacement fields.
    for node in ast.walk(ast.parse(script)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


class StepFieldInjectionTests(unittest.TestCase):
    """Every step string field: an embedded reference resolves to inert literal data."""

    inputs = {"src": {"p": _PAYLOAD}}

    def assert_inert(self, script: str, expected_literal: str) -> None:
        self.assertNotIn("__import__", _code_names(script))
        self.assertIn(expected_literal, _string_constants(script))

    def run_step(self, step: dict) -> str:
        return _run_and_capture({"playwrightSteps": [step]}, self.inputs)

    def test_a_reference_in_the_navigate_url_stays_data(self) -> None:
        script = self.run_step({"action": "navigate", "url": "http://x/$src.p"})
        self.assert_inert(script, "http://x/" + _PAYLOAD)

    def test_a_reference_in_any_selector_stays_data(self) -> None:
        for action in ("click", "type", "fill", "getText", "getAttribute", "getHTML", "hover"):
            with self.subTest(action=action):
                script = self.run_step({"action": action, "selector": "#id-$src.p"})
                self.assert_inert(script, "#id-" + _PAYLOAD)
        script = self.run_step({"action": "selectOption", "selector": "#s-$src.p", "value": "v"})
        self.assert_inert(script, "#s-" + _PAYLOAD)

    def test_a_reference_in_typed_text_stays_data(self) -> None:
        script = self.run_step({"action": "type", "selector": "#q", "text": "hi $src.p"})
        self.assert_inert(script, "hi " + _PAYLOAD)

    def test_a_reference_in_a_fill_or_select_value_stays_data(self) -> None:
        for action in ("fill", "selectOption"):
            with self.subTest(action=action):
                script = self.run_step({"action": action, "selector": "#q", "value": "v $src.p"})
                self.assert_inert(script, "v " + _PAYLOAD)

    def test_a_reference_in_the_attribute_name_stays_data(self) -> None:
        script = self.run_step(
            {"action": "getAttribute", "selector": "a", "attribute": "data-$src.p"}
        )
        self.assert_inert(script, "data-" + _PAYLOAD)

    def test_a_reference_in_any_output_key_stays_data(self) -> None:
        for action in ("screenshot", "getText", "getAttribute", "getHTML", "getVisibleTextOnPage"):
            with self.subTest(action=action):
                script = self.run_step(
                    {"action": action, "selector": "body", "outputKey": "k_$src.p"}
                )
                self.assert_inert(script, "k_" + _PAYLOAD)

    def test_a_whole_field_output_key_stays_data(self) -> None:
        script = self.run_step({"action": "getText", "selector": "body", "outputKey": "$src.p"})

        self.assertNotIn("__import__", _code_names(script))
        self.assertIn(f"results[{_PAYLOAD!r}]", script)

    def test_a_template_split_by_a_tab_or_newline_stays_data(self) -> None:
        for separator in ("\t", "\n"):
            # The executor hands a template with no plain space to its expression evaluator,
            # which warns about the second expression. Only the generated script matters here.
            with self.subTest(separator=repr(separator)), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                script = _run_and_capture(
                    {
                        "playwrightSteps": [
                            {"action": "type", "selector": "#q", "text": f"$src.p{separator}$src.q"}
                        ]
                    },
                    {"src": {"p": _PAYLOAD, "q": "tail"}},
                )
                self.assertNotIn("__import__", _code_names(script))

    def test_references_in_ai_step_fields_stay_data(self) -> None:
        for field in ("instructions", "credentialId", "model"):
            with self.subTest(field=field):
                script = self.run_step({"action": "aiStep", field: "ai $src.p"})
                self.assert_inert(script, "ai " + _PAYLOAD)

    def test_references_in_auth_fallback_steps_stay_data(self) -> None:
        node_data = {
            "playwrightAuthEnabled": True,
            "playwrightAuthCheckSelector": "#logged-in",
            "playwrightSteps": [{"action": "navigate", "url": "https://heym.run/login"}],
            "playwrightAuthFallbackSteps": [
                {"action": "navigate", "url": "http://x/$src.p"},
                {"action": "fill", "selector": "#user", "value": "u $src.p"},
                {"action": "aiStep", "instructions": "log in $src.p"},
            ],
        }
        script = _run_and_capture(node_data, self.inputs)
        self.assert_inert(script, "http://x/" + _PAYLOAD)
        self.assert_inert(script, "u " + _PAYLOAD)
        self.assert_inert(script, "log in " + _PAYLOAD)

    def test_a_global_variable_reference_stays_data(self) -> None:
        script = _run_and_capture(
            {"playwrightSteps": [{"action": "navigate", "url": "http://x/$global.page"}]},
            global_variables_context={"page": _PAYLOAD},
        )
        self.assert_inert(script, "http://x/" + _PAYLOAD)

    def test_a_template_that_starts_with_a_reference_is_resolved_first(self) -> None:
        script = _run_and_capture(
            {"playwrightSteps": [{"action": "type", "selector": "#q", "text": "$src.p $src.q"}]},
            {"src": {"p": _PAYLOAD, "q": "tail"}},
        )
        self.assert_inert(script, _PAYLOAD + " tail")

    def test_a_whole_field_reference_to_a_crafted_value_stays_runtime_data(self) -> None:
        script = self.run_step({"action": "navigate", "url": "$src.p"})
        self.assertNotIn("__import__", _code_names(script))
        self.assertIn("page.goto((inputs.get('src', {})).get('p',", script)

    def test_a_reference_in_the_auth_check_selector_stays_data(self) -> None:
        node_data = {
            "playwrightAuthEnabled": True,
            "playwrightAuthCheckSelector": "#ok-$src.p",
            "playwrightSteps": [{"action": "navigate", "url": "https://heym.run/login"}],
        }
        script = _run_and_capture(node_data, self.inputs)
        self.assert_inert(script, "#ok-" + _PAYLOAD)

    def test_saved_ai_steps_and_auth_cookies_are_never_resolved(self) -> None:
        cookies = [{"name": "sid", "value": "$src.cookie", "domain": "heym.run", "path": "/"}]
        node_data = {
            "playwrightAuthEnabled": True,
            "playwrightAuthCheckSelector": "#ok",
            "playwrightAuthStateExpression": "$global.cookies",
            "playwrightSteps": [
                {"action": "navigate", "url": "https://heym.run/login"},
                {
                    "action": "aiStep",
                    "instructions": "go",
                    "savedSteps": [{"action": "click", "selector": "$src.saved"}],
                },
            ],
        }
        inputs = {"src": {"cookie": _PAYLOAD, "saved": _PAYLOAD}}
        script = _run_and_capture(node_data, inputs, global_variables_context={"cookies": cookies})

        self.assertNotIn("__import__", _code_names(script))
        self.assertIn("$src.cookie", _string_constants(script))
        self.assertIn("$src.saved", _string_constants(script))

    def test_a_resolved_value_is_not_resolved_again(self) -> None:
        # A value that itself contains a reference is data: no second resolution.
        script = _run_and_capture(
            {"playwrightSteps": [{"action": "navigate", "url": "http://x/$src.p"}]},
            {"src": {"p": "$global.secret"}},
            global_variables_context={"secret": "LEAKED"},
        )
        self.assertIn("http://x/$global.secret", _string_constants(script))
        self.assertNotIn("http://x/LEAKED", _string_constants(script))


class LegitimateTemplateTests(unittest.TestCase):
    """The fix must keep normal references working."""

    def test_an_embedded_reference_resolves_to_its_value(self) -> None:
        script = _run_and_capture(
            {"playwrightSteps": [{"action": "navigate", "url": "https://heym.run/$src.path"}]},
            {"src": {"path": "pricing"}},
        )
        self.assertIn("https://heym.run/pricing", _string_constants(script))

    def test_an_embedded_global_reference_resolves(self) -> None:
        script = _run_and_capture(
            {"playwrightSteps": [{"action": "fill", "selector": "#q", "value": "q=$global.term"}]},
            global_variables_context={"term": "agents"},
        )
        self.assertIn("q=agents", _string_constants(script))

    def test_a_reference_led_template_without_spaces_resolves(self) -> None:
        # A value that starts with a reference and has no space, such as
        # $src.base?q=$src.q, used to be read as one expression, fail, and resolve
        # to "", so the navigate step fell back to the generator default
        # https://example.com. Each embedded reference must resolve instead.
        script = _run_and_capture(
            {"playwrightSteps": [{"action": "navigate", "url": "$src.base?q=$src.q"}]},
            {"src": {"base": "https://heym.run/search", "q": "agents"}},
        )
        self.assertIn("https://heym.run/search?q=agents", _string_constants(script))
        self.assertNotIn("https://example.com", _string_constants(script))

    def test_a_whole_field_reference_keeps_its_runtime_lookup(self) -> None:
        script = _run_and_capture(
            {"playwrightSteps": [{"action": "navigate", "url": "$global.page"}]},
            global_variables_context={"page": "https://heym.run/docs"},
        )
        self.assertIn("page.goto((inputs.get('global', {})).get('page',", script)

    def test_disabled_steps_are_left_untouched(self) -> None:
        disabled = {"action": "navigate", "url": "http://x/$src.p", "disabled": True}
        executor = _executor({})
        with patch.object(executor, "_resolve_template", side_effect=AssertionError("resolved")):
            resolved = _resolve_step_templates(executor, [disabled], {}, "pw1")

        self.assertIs(resolved[0], disabled)


class SecondPassScopeTests(unittest.TestCase):
    def test_custom_code_still_resolves_expressions(self) -> None:
        node_data = {"label": "pw", "playwrightCode": "target = $src.p"}
        executor = _executor(node_data)
        with (
            patch.object(settings, "playwright_custom_code_enabled", True),
            patch.object(playwright_sandbox, "run_script", return_value=(0, "{}", "")) as mock_run,
        ):
            _execute_playwright_node(executor, node_data, {"src": {"p": "value"}}, "pw1", "pw")
        self.assertIn("target = 'value'", mock_run.call_args.args[0])

    def test_generator_writes_resolved_values_as_literals(self) -> None:
        self.assertEqual(_expr_to_python(ResolvedStepValue("$src.p")), "'$src.p'")
        self.assertEqual(_expr_to_python("$src.p"), "(inputs.get('src', {})).get('p', \"\")")
        self.assertEqual(_expr_to_python("plain"), "'plain'")


if __name__ == "__main__":
    unittest.main()
