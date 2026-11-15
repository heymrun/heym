"""A variable typed "number" keeps a whole number whole, so templates render 5, not 5.0."""

import unittest
import uuid

from app.api import global_variables as global_variables_api
from app.services.workflow_executor import execute_workflow

URL = "https://api.example.com/items?page="


def _render_page(variable_type: str, value: str, global_page: object) -> str:
    nodes = [
        {"id": "s", "type": "textInput", "data": {"label": "start"}},
        {
            "id": "v",
            "type": "variable",
            "data": {
                "label": "setPage",
                "variableName": "page",
                "variableValue": value,
                "variableType": variable_type,
            },
        },
        {"id": "o", "type": "output", "data": {"label": "result", "message": f"{URL}$vars.page"}},
    ]
    edges = [{"id": "e1", "source": "s", "target": "v"}, {"id": "e2", "source": "v", "target": "o"}]
    result = execute_workflow(
        uuid.uuid4(),
        nodes,
        edges,
        {"text": "x"},
        global_variables_context={"page": global_page},
    )
    return result.outputs["result"]["result"]


class GlobalVariableNumberTests(unittest.TestCase):
    def test_a_whole_number_from_the_panel_stays_an_int(self) -> None:
        # GlobalVariablesPanel sends JSON.parse("5") -> 5.
        for value_type in ("number", global_variables_api._infer_type(5)):
            with self.subTest(value_type=value_type):
                result = global_variables_api._coerce_value(5, value_type)
                self.assertIs(type(result), int)
                self.assertEqual(result, 5)

    def test_a_fraction_and_a_boolean_keep_their_coercion(self) -> None:
        self.assertEqual(global_variables_api._coerce_value(2.5, "number"), 2.5)
        result = global_variables_api._coerce_value(True, "number")
        self.assertIs(type(result), float)
        self.assertEqual(result, 1.0)


class VariableNodeNumberTests(unittest.TestCase):
    def test_a_whole_number_expression_renders_without_a_fraction(self) -> None:
        self.assertEqual(_render_page("number", "$global.page + 1", 5), f"{URL}6")
        self.assertEqual(_render_page("number", "$global.page", 5), f"{URL}5")

    def test_text_fractions_and_auto_typing_are_unchanged(self) -> None:
        self.assertEqual(_render_page("number", "6", 5), f"{URL}6")
        self.assertEqual(_render_page("number", "$global.page", 2.5), f"{URL}2.5")
        self.assertEqual(_render_page("auto", "$global.page + 1", 5), f"{URL}6")


if __name__ == "__main__":
    unittest.main()
