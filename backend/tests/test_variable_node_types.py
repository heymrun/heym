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


if __name__ == "__main__":
    unittest.main()
