"""The Variable node's type coercion, as the DSL prompt documents it."""

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor


def _run(steps: list[tuple[str, str, str]], body: dict) -> list[object]:
    """Run textInput -> one Variable node per (name, value, type); return each node's value."""
    nodes = [{"id": "in", "type": "textInput", "data": {"label": "userInput"}}]
    edges = []
    previous = "in"
    for index, (name, value, variable_type) in enumerate(steps):
        node_id = f"v{index}"
        nodes.append(
            {
                "id": node_id,
                "type": "variable",
                "data": {
                    "label": f"step{index}",
                    "variableName": name,
                    "variableValue": value,
                    "variableType": variable_type,
                },
            }
        )
        edges.append({"id": f"e{index}", "source": previous, "target": node_id})
        previous = node_id
    result = WorkflowExecutor(nodes=nodes, edges=edges).execute(
        workflow_id=uuid.uuid4(), initial_inputs={"body": body}
    )
    by_id = {row["node_id"]: row for row in result.node_results}
    return [by_id[f"v{index}"]["output"]["value"] for index in range(len(steps))]


class VariableArrayTypeTests(unittest.TestCase):
    def test_a_single_value_is_wrapped_and_can_be_appended_to(self) -> None:
        values = _run(
            [
                ("tags", "$userInput.body.tag", "array"),
                ("tags", "$vars.tags.add(userInput.body.tag2)", "array"),
            ],
            {"tag": "vip", "tag2": "beta"},
        )

        self.assertEqual(values, [["vip"], ["vip", "beta"]])

    def test_a_list_stays_the_same_list(self) -> None:
        (value,) = _run([("tags", "$userInput.body.tags", "array")], {"tags": ["a", "b"]})

        self.assertEqual(value, ["a", "b"])

    def test_a_plain_text_value_is_wrapped(self) -> None:
        (value,) = _run([("tags", "hello", "array")], {})

        self.assertEqual(value, ["hello"])

    def test_a_null_or_missing_value_is_an_empty_list(self) -> None:
        values = _run(
            [("tags", "$userInput.body.tag", "array"), ("more", "$userInput.body.none", "array")],
            {"tag": None},
        )

        self.assertEqual(values, [[], []])


class VariableStringTypeTests(unittest.TestCase):
    def test_booleans_null_objects_and_lists_become_json_text(self) -> None:
        cases = [
            (True, "true"),
            (False, "false"),
            (None, "null"),
            ({"a": 1, "city": "Zürich"}, '{"a": 1, "city": "Zürich"}'),
            ([1, "b"], '[1, "b"]'),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                (text,) = _run([("x", "$userInput.body.v", "string")], {"v": value})

                self.assertEqual(text, expected)

    def test_numbers_and_text_are_unchanged(self) -> None:
        for value, expected in ((5, "5"), (2.5, "2.5"), ("vip", "vip")):
            with self.subTest(value=value):
                (text,) = _run([("x", "$userInput.body.v", "string")], {"v": value})

                self.assertEqual(text, expected)


if __name__ == "__main__":
    unittest.main()
