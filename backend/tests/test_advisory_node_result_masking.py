"""Credential values must be masked in every node result that reaches history.

Masking covered only each node's `output`. A node's `error` text (a throwError message,
an exception quoting a key) was stored as-is, and sub-workflow runs never passed through
execute_workflow(), so their history rows kept raw outputs and node results.
Global variable rows keep their output: later runs read the value persisted from them.
"""

import asyncio
import copy
import json
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.workflow_executor import (
    ExecutionResult,
    WorkflowExecutor,
    execute_workflow,
    mask_sub_workflow_result,
)

_SECRET = "sk-live-SUPERSECRET-1234567890"
_MASKED = _SECRET[:7] + "**"
_CREDENTIALS = {"apiKey": _SECRET}
_INPUTS = {"headers": {}, "query": {}, "body": {"text": "x"}}
_SUB_ID = str(uuid.uuid4())
_SUB_CACHE = {
    _SUB_ID: {
        "name": "Sub",
        "nodes": [
            {
                "id": "s1",
                "type": "textInput",
                "data": {"label": "input", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "s2",
                "type": "variable",
                "data": {
                    "label": "subVar",
                    "variableName": "k",
                    "variableValue": "$credentials.apiKey",
                    "variableType": "string",
                },
            },
            {"id": "s3", "type": "output", "data": {"label": "output", "message": "$subVar.value"}},
        ],
        "edges": [
            {"id": "se1", "source": "s1", "target": "s2"},
            {"id": "se2", "source": "s2", "target": "s3"},
        ],
    }
}


def _parent(do_not_wait: bool = False) -> tuple[list[dict], list[dict]]:
    execute_data: dict = {
        "label": "callWorkflow",
        "executeWorkflowId": _SUB_ID,
        "executeInput": "$userInput.body.text",
    }
    if do_not_wait:
        execute_data["executeDoNotWait"] = True
    nodes = [
        {
            "id": "n1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
        },
        {"id": "n2", "type": "execute", "data": execute_data},
        {
            "id": "n3",
            "type": "variable",
            "data": {"label": "after", "variableName": "after", "variableValue": "done"},
        },
    ]
    edges = [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "source": "n2", "target": "n3"},
    ]
    return nodes, edges


class NodeErrorMaskingTests(unittest.TestCase):
    def test_error_of_a_failed_node_is_masked(self) -> None:
        nodes = [
            {
                "id": "n1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "boom",
                "type": "throwError",
                "data": {"label": "boom", "errorMessage": "rejected key $credentials.apiKey"},
            },
        ]
        edges = [{"id": "e1", "source": "n1", "target": "boom"}]

        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs=_INPUTS,
            credentials_context=_CREDENTIALS,
        )

        rows = {row["node_id"]: row for row in result.node_results}
        self.assertEqual(result.status, "error")
        self.assertEqual(rows["boom"]["error"], f"rejected key {_MASKED}")
        self.assertNotIn(_SECRET, json.dumps(result.node_results))
        self.assertNotIn(_SECRET, json.dumps(result.outputs))


class SubWorkflowHistoryMaskingTests(unittest.TestCase):
    def test_sub_workflow_record_is_masked(self) -> None:
        nodes, edges = _parent()
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs=_INPUTS,
            workflow_cache=_SUB_CACHE,
            credentials_context=_CREDENTIALS,
        )

        (record,) = result.sub_workflow_executions
        self.assertEqual(record.outputs, {"output": {"result": _MASKED}})
        self.assertIn(_MASKED, json.dumps(record.node_results))
        self.assertNotIn(_SECRET, json.dumps(record.node_results))

    def test_parent_still_receives_the_raw_sub_workflow_outputs(self) -> None:
        nodes, edges = _parent()
        seen_inputs: list[str] = []
        real_logic = WorkflowExecutor._execute_node_logic

        def recording_logic(executor: WorkflowExecutor, node_id: str, inputs: dict, *args):
            if node_id == "n3":
                seen_inputs.append(json.dumps(inputs, default=str))
            return real_logic(executor, node_id, inputs, *args)

        with patch.object(WorkflowExecutor, "_execute_node_logic", recording_logic):
            result = execute_workflow(
                workflow_id=uuid.uuid4(),
                nodes=nodes,
                edges=edges,
                inputs=_INPUTS,
                workflow_cache=_SUB_CACHE,
                credentials_context=_CREDENTIALS,
            )

        self.assertEqual(result.status, "success")
        self.assertIn(_SECRET, seen_inputs[0])

    def test_background_sub_workflow_record_is_masked(self) -> None:
        nodes, edges = _parent(do_not_wait=True)
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs=_INPUTS,
            workflow_cache=_SUB_CACHE,
            credentials_context=_CREDENTIALS,
        )
        (_future, recorded, *_rest) = result._bg_pending[0]
        self.assertTrue(recorded.wait(timeout=5))

        (record,) = result.sub_workflow_executions
        self.assertEqual(record.outputs, {"output": {"result": _MASKED}})
        self.assertNotIn(_SECRET, json.dumps(record.node_results))


def _sub_result(outputs: dict, rows: list, global_ids: frozenset[str] = frozenset()):
    return ExecutionResult(
        workflow_id=uuid.uuid4(),
        status="success",
        outputs=outputs,
        execution_time_ms=1.0,
        node_results=rows,
        _global_variable_node_ids=global_ids,
    )


class MaskSubWorkflowResultTests(unittest.TestCase):
    def test_the_original_values_are_left_untouched(self) -> None:
        outputs = {"output": {"result": _SECRET}}
        rows = [{"node_id": "s2", "output": {"value": _SECRET}, "error": f"bad {_SECRET}"}]

        masked_outputs, masked_rows = mask_sub_workflow_result(
            _sub_result(outputs, rows), _CREDENTIALS
        )

        self.assertEqual(masked_outputs, {"output": {"result": _MASKED}})
        self.assertEqual(masked_rows[0]["output"], {"value": _MASKED})
        self.assertEqual(masked_rows[0]["error"], f"bad {_MASKED}")
        self.assertEqual(outputs["output"]["result"], _SECRET)
        self.assertEqual(rows[0]["output"]["value"], _SECRET)
        self.assertEqual(rows[0]["error"], f"bad {_SECRET}")

    def test_global_variable_rows_keep_their_output(self) -> None:
        rows = [
            {"node_id": "g1", "output": {"value": _SECRET}, "error": f"bad {_SECRET}"},
            {"node_id": "s2", "output": {"value": _SECRET}},
        ]

        _, masked_rows = mask_sub_workflow_result(
            _sub_result({}, rows, frozenset({"g1"})), _CREDENTIALS
        )

        self.assertEqual(masked_rows[0]["output"], {"value": _SECRET})
        self.assertEqual(masked_rows[0]["error"], f"bad {_MASKED}")
        self.assertEqual(masked_rows[1]["output"], {"value": _MASKED})

    def test_without_credentials_nothing_is_copied(self) -> None:
        outputs = {"output": {"result": "plain"}}
        rows = [{"node_id": "s2", "output": {"value": "plain"}}]

        masked_outputs, masked_rows = mask_sub_workflow_result(_sub_result(outputs, rows), {})

        self.assertIs(masked_outputs, outputs)
        self.assertIs(masked_rows, rows)


def _persisted_globals(nodes: list[dict], cache: dict, result: ExecutionResult) -> dict:
    """Run the real global-variable persistence and return what it would store."""
    from app.api.workflows import _persist_global_variables_from_execution

    upsert = AsyncMock()
    with patch("app.api.workflows.upsert_global_variable", upsert):
        asyncio.run(
            _persist_global_variables_from_execution(
                MagicMock(),
                uuid.uuid4(),
                nodes,
                cache,
                result.node_results,
                result.sub_workflow_executions,
            )
        )
    return {call.args[2]: call.args[3] for call in upsert.await_args_list}


class GlobalVariableCompatibilityTests(unittest.TestCase):
    """Masking history must not change what a global variable stores for later runs."""

    def test_a_sub_workflow_global_keeps_the_raw_value(self) -> None:
        cache = copy.deepcopy(_SUB_CACHE)
        cache[_SUB_ID]["nodes"][1]["data"]["isGlobal"] = True
        nodes, edges = _parent()
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs=_INPUTS,
            workflow_cache=cache,
            credentials_context=_CREDENTIALS,
        )

        self.assertEqual(_persisted_globals(nodes, cache, result), {"k": _SECRET})
        (record,) = result.sub_workflow_executions
        self.assertEqual(record.outputs, {"output": {"result": _MASKED}})

    def test_a_top_level_global_is_stored_as_before(self) -> None:
        nodes = [
            {
                "id": "n1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "g1",
                "type": "variable",
                "data": {
                    "label": "g1",
                    "variableName": "g1",
                    "variableValue": "$credentials.apiKey",
                    "variableType": "string",
                    "isGlobal": True,
                },
            },
        ]
        edges = [{"id": "e1", "source": "n1", "target": "g1"}]
        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs=_INPUTS,
            credentials_context=_CREDENTIALS,
        )

        self.assertEqual(_persisted_globals(nodes, {}, result), {"g1": _MASKED})


if __name__ == "__main__":
    unittest.main()
