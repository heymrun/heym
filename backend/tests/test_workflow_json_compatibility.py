import json
import unittest

from app.services.workflow_executor import (
    DotDict,
    DotList,
    NodeResult,
    SubWorkflowExecution,
    _serialize_node_result,
    _serialize_sub_workflow_executions,
    _to_json_compatible,
)


class WorkflowJsonCompatibilityTests(unittest.TestCase):
    def test_dot_wrappers_with_method_name_keys_serialize_to_json(self) -> None:
        wrapped = DotDict(
            {
                "items": DotList([DotDict({"value": 1})]),
                "keys": DotList(["a", "b"]),
            }
        )

        plain = _to_json_compatible(wrapped)

        self.assertEqual(plain, {"items": [{"value": 1}], "keys": ["a", "b"]})
        json.dumps(plain)

    def test_node_result_serialization_removes_dot_wrappers(self) -> None:
        result = NodeResult(
            node_id="node_1",
            node_label="node",
            node_type="set",
            status="success",
            output={"items": DotList([DotDict({"value": 1})])},
            execution_time_ms=1.0,
        )

        serialized = _serialize_node_result(result)

        self.assertEqual(serialized["output"], {"items": [{"value": 1}]})
        json.dumps(serialized)

    def test_subworkflow_serialization_removes_dot_wrappers(self) -> None:
        execution = SubWorkflowExecution(
            workflow_id="00000000-0000-0000-0000-000000000001",
            inputs={"items": DotList(["input"])},
            outputs={"items": DotList(["output"])},
            status="success",
            execution_time_ms=1.0,
            node_results=[
                {
                    "node_id": "node_1",
                    "output": {"items": DotList([DotDict({"value": 1})])},
                }
            ],
        )

        serialized = _serialize_sub_workflow_executions([execution])[0]

        self.assertEqual(serialized["outputs"], {"items": ["output"]})
        self.assertEqual(serialized["node_results"][0]["output"], {"items": [{"value": 1}]})
        json.dumps(serialized)


if __name__ == "__main__":
    unittest.main()
