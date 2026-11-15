"""The Switch node routes on the value the way users see it written."""

import unittest
import uuid

from app.services.workflow_executor import execute_workflow


def _edge(source: str, target: str, handle: str) -> dict:
    return {
        "id": f"{source}-{target}-{handle}",
        "source": source,
        "target": target,
        "sourceHandle": handle,
    }


def _route(value: object, cases: list[str]) -> tuple[str, list[str]]:
    """Run textInput → Switch on body.value; return the branch and the paths that ran."""
    paths = [f"case{i}Path" for i in range(len(cases))] + ["defaultPath"]
    nodes = [
        {"id": "in", "type": "textInput", "data": {"label": "userInput"}},
        {
            "id": "sw",
            "type": "switch",
            "data": {"label": "route", "expression": "$userInput.body.value", "cases": cases},
        },
    ] + [
        {
            "id": label,
            "type": "set",
            "data": {"label": label, "mappings": [{"key": "x", "value": "1"}]},
        }
        for label in paths
    ]
    handles = [f"case-{i}" for i in range(len(cases))] + ["default"]
    edges = [{"id": "e0", "source": "in", "target": "sw"}] + [
        _edge("sw", label, handle) for label, handle in zip(paths, handles)
    ]
    result = execute_workflow(uuid.uuid4(), nodes, edges, {"body": {"value": value}})
    branch = next(r["output"]["branch"] for r in result.node_results if r["node_id"] == "sw")
    ran = [
        r["node_label"]
        for r in result.node_results
        if r["node_label"] in paths and r["status"] == "success"
    ]
    return branch, ran


class SwitchBooleanCaseTests(unittest.TestCase):
    def test_a_boolean_matches_the_cases_true_and_false(self) -> None:
        self.assertEqual(_route(True, ["true", "false"]), ("case-0", ["case0Path"]))
        self.assertEqual(_route(False, ["true", "false"]), ("case-1", ["case1Path"]))

    def test_existing_matches_are_unchanged(self) -> None:
        self.assertEqual(_route("true", ["true", "false"])[0], "case-0")
        self.assertEqual(_route(True, ["True", "False"])[0], "case-0")
        self.assertEqual(_route(2, ["1", "2"])[0], "case-1")
        self.assertEqual(_route("gold", ["silver", "gold"])[0], "case-1")
        self.assertEqual(_route("bronze", ["silver", "gold"]), ("default", ["defaultPath"]))


if __name__ == "__main__":
    unittest.main()
