"""An Input field's default value fills the request body when the caller leaves it out.

The editor and the chat portal prefilled defaults in the browser, and the agent's
sub-workflow tool filled them on the server, but an API or webhook call that left a field
out got null for it.
"""

import unittest
import uuid

from app.services.workflow_executor import execute_workflow

_NODES = [
    {
        "id": "in_1",
        "type": "textInput",
        "data": {
            "label": "userInput",
            "inputFields": [
                {"key": "text"},
                {"key": "userId", "defaultValue": "anonymous"},
                {"key": "lang", "defaultValue": ""},
            ],
        },
    },
    {
        "id": "set_1",
        "type": "set",
        "data": {
            "label": "who",
            "mappings": [
                {"key": "user", "value": "$userInput.body.userId"},
                {"key": "top", "value": "$userInput.userId"},
                {"key": "text", "value": "$userInput.body.text"},
            ],
        },
    },
]
_EDGES = [{"id": "e1", "source": "in_1", "target": "set_1"}]


def _run(body: dict) -> tuple[dict, dict]:
    result = execute_workflow(
        workflow_id=uuid.uuid4(),
        nodes=_NODES,
        edges=_EDGES,
        inputs={"headers": {}, "query": {}, "body": body},
    )
    rows = {row["node_label"]: row["output"] for row in result.node_results}
    return rows["userInput"], rows["who"]


class InputFieldDefaultValueTests(unittest.TestCase):
    def test_a_left_out_field_gets_its_default(self) -> None:
        user_input, who = _run({"text": "Bonjour"})

        self.assertEqual(who, {"user": "anonymous", "top": "anonymous", "text": "Bonjour"})
        self.assertEqual(user_input["body"], {"text": "Bonjour", "userId": "anonymous"})

    def test_a_sent_value_wins_even_when_empty(self) -> None:
        _, who = _run({"text": "Bonjour", "userId": "u7"})
        _, who_empty = _run({"text": "Bonjour", "userId": ""})

        self.assertEqual(who["user"], "u7")
        self.assertEqual(who_empty["user"], "")

    def test_a_field_without_a_default_stays_out(self) -> None:
        user_input, _ = _run({"text": "Bonjour"})

        self.assertNotIn("lang", user_input["body"])


if __name__ == "__main__":
    unittest.main()
