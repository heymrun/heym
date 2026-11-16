"""A Playwright step field that is one `$` expression reads what the executor reads.

The step used to compile a whole-field reference into a plain `inputs.get(...)` chain over
the direct parents' outputs, which missed nodes further up, `$input`, indexes and methods,
and fell back to the generator's placeholder (navigate opened https://example.com).
"""

from __future__ import annotations

import re
import unittest
import uuid
from unittest.mock import patch

from app.services.node_execution.nodes import playwright_node
from app.services.playwright_code_generator import _heym_navigable_url
from app.services.workflow_executor import WorkflowExecutor

URL = "https://shop.example/orders/42"
BODY = {"link": URL, "padded": f"  {URL} ", "urls": [URL], "qty": 3}


class _CapturedError(Exception):
    pass


def _script(steps: list[dict], *, behind_set: bool) -> tuple[str, dict]:
    captured: dict = {}

    def build(code: str, inputs: dict, **_kw: object) -> str:
        captured["code"], captured["inputs"] = code, inputs
        raise _CapturedError

    start = {
        "id": "u",
        "type": "textInput",
        "position": {"x": 0, "y": 0},
        "data": {"label": "userInput", "inputFields": [{"key": "link"}]},
    }
    prep = {
        "id": "s",
        "type": "set",
        "position": {"x": 200, "y": 0},
        "data": {"label": "prep", "mappings": [{"key": "seen", "value": "yes"}]},
    }
    browser = {
        "id": "pw",
        "type": "playwright",
        "position": {"x": 400, "y": 0},
        "data": {"label": "browser", "playwrightSteps": steps},
    }
    if behind_set:
        nodes = [start, prep, browser]
        edges = [
            {"id": "e1", "source": "u", "target": "s"},
            {"id": "e2", "source": "s", "target": "pw"},
        ]
    else:
        nodes = [start, browser]
        edges = [{"id": "e1", "source": "u", "target": "pw"}]
    with patch.object(playwright_node, "_build_playwright_script", side_effect=build):
        WorkflowExecutor(nodes=nodes, edges=edges, actor_user_id=uuid.uuid4()).execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": BODY},
        )
    return captured["code"], captured["inputs"]


def _goto_target(url: str, *, behind_set: bool) -> str:
    code, inputs = _script([{"action": "navigate", "url": url}], behind_set=behind_set)
    (argument,) = re.findall(r"page\.goto\((.*?)(?:, wait_until=.*)?\)$", code, re.MULTILINE)
    scope = {"inputs": inputs, "_heym_navigable_url": _heym_navigable_url}
    return str(eval(argument, {"__builtins__": {}}, scope))  # noqa: S307


class PlaywrightWholeFieldReferenceTests(unittest.TestCase):
    def test_a_node_further_up_is_read(self) -> None:
        self.assertEqual(_goto_target("$userInput.body.link", behind_set=True), URL)

    def test_input_index_and_method_are_read(self) -> None:
        for field in ("$input.body.link", "$userInput.body.urls[0]", "$input.body.urls[0]"):
            with self.subTest(field=field):
                self.assertEqual(_goto_target(field, behind_set=False), URL)
        self.assertEqual(_goto_target("$userInput.body.padded.trim()", behind_set=True), URL)

    def test_a_direct_parent_reference_still_works(self) -> None:
        self.assertEqual(_goto_target("$userInput.body.link", behind_set=False), URL)

    def test_a_missing_value_still_falls_back_to_the_default(self) -> None:
        self.assertEqual(
            _goto_target("$userInput.body.nothing", behind_set=False), "https://example.com"
        )

    def test_a_number_is_typed_as_its_text(self) -> None:
        code, _inputs = _script(
            [
                {"action": "navigate", "url": URL},
                {"action": "fill", "selector": "#qty", "value": "$userInput.body.qty"},
            ],
            behind_set=True,
        )

        self.assertIn(".fill('3'", code)


if __name__ == "__main__":
    unittest.main()
