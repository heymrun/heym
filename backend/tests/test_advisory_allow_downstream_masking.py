"""Credential values in allowDownstream results must be masked before they are persisted.

execute_workflow() masks the early result, but nodes that finish after an output node
with allowDownstream are appended later by join_allow_downstream(). Every caller persists
node_results after that join, so those rows reached history with raw credential values.
"""

import json
import threading
import unittest
import uuid
from unittest.mock import patch

from app.services.workflow_executor import ExecutionResult, WorkflowExecutor, execute_workflow

_SECRET = "sk-live-SUPERSECRET-1234567890"
_MASKED = _SECRET[:7] + "**"


def _variable(node_id: str, value: str) -> dict:
    return {
        "id": node_id,
        "type": "variable",
        "data": {
            "label": node_id,
            "variableName": node_id,
            "variableValue": value,
            "variableType": "string",
        },
    }


_NODES = [
    {
        "id": "in1",
        "type": "textInput",
        "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
    },
    _variable("pre", "$credentials.apiKey"),
    {
        "id": "out1",
        "type": "output",
        "data": {"label": "output", "message": "ok", "allowDownstream": True},
    },
    _variable("gate", "released"),
    _variable("post", "$credentials.apiKey"),
]
_EDGES = [
    {"id": "e1", "source": "in1", "target": "pre"},
    {"id": "e2", "source": "pre", "target": "out1"},
    {"id": "e3", "source": "out1", "target": "gate"},
    {"id": "e4", "source": "gate", "target": "post"},
]


_THROW_NODES = [
    *_NODES[:3],
    _variable("gate", "released"),
    {
        "id": "boom",
        "type": "throwError",
        "data": {"label": "boom", "errorMessage": "rejected key $credentials.apiKey"},
    },
]
_THROW_EDGES = [*_EDGES[:3], {"id": "e4", "source": "gate", "target": "boom"}]


class AllowDownstreamJoinMaskingTests(unittest.TestCase):
    def _run(
        self,
        credentials_context: dict[str, str] | None,
        nodes: list[dict] = _NODES,
        edges: list[dict] = _EDGES,
    ) -> tuple[ExecutionResult, list]:
        """Run the workflow, holding the downstream branch until the early result exists."""
        release = threading.Event()
        real_logic = WorkflowExecutor._execute_node_logic

        def gated_logic(executor: WorkflowExecutor, node_id: str, *args, **kwargs):
            if node_id == "gate" and not release.wait(timeout=5):
                raise AssertionError("downstream gate was never released")
            return real_logic(executor, node_id, *args, **kwargs)

        with patch.object(WorkflowExecutor, "_execute_node_logic", gated_logic):
            result = execute_workflow(
                workflow_id=uuid.uuid4(),
                nodes=nodes,
                edges=edges,
                inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
                credentials_context=credentials_context,
            )
            self.assertTrue(result.allow_downstream_pending)
            early_ids = [row["node_id"] for row in result.node_results]
            release.set()
            result.join_allow_downstream()
        return result, early_ids

    def test_rows_added_by_the_join_are_masked(self) -> None:
        result, early_ids = self._run({"apiKey": _SECRET})

        self.assertNotIn("post", early_ids)
        rows = {row["node_id"]: row for row in result.node_results}
        self.assertEqual(rows["post"]["output"]["value"], _MASKED)
        self.assertNotIn(_SECRET, json.dumps(result.node_results))

    def test_error_of_a_row_added_by_the_join_is_masked(self) -> None:
        result, early_ids = self._run({"apiKey": _SECRET}, _THROW_NODES, _THROW_EDGES)

        self.assertNotIn("boom", early_ids)
        rows = {row["node_id"]: row for row in result.node_results}
        self.assertEqual(rows["boom"]["error"], f"rejected key {_MASKED}")
        self.assertNotIn(_SECRET, json.dumps(result.node_results))

    def test_early_rows_stay_masked(self) -> None:
        result, _ = self._run({"apiKey": _SECRET})

        rows = {row["node_id"]: row for row in result.node_results}
        self.assertEqual(rows["pre"]["output"]["value"], _MASKED)

    def test_a_run_without_credentials_still_joins_its_rows(self) -> None:
        result, _ = self._run(None)

        self.assertEqual(result._credentials_context, {})
        self.assertIn("post", [row["node_id"] for row in result.node_results])


if __name__ == "__main__":
    unittest.main()
