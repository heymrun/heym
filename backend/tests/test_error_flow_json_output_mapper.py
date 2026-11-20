"""A jsonOutputMapper at the end of the error flow gives the response body.

`/execute` only took an output node as the error flow's final output, so a mapper there
ran and was then replaced by the raw error message. `/execute/stream` took it, wrapped
under its label. Both now return the mapper's object, as the success path does.
"""

import unittest
import uuid

from app.services.workflow_executor import execute_workflow, execute_workflow_streaming


def _graph(error_terminal: dict) -> tuple[list[dict], list[dict]]:
    nodes = [
        {
            "id": "in_1",
            "type": "textInput",
            "data": {"label": "userInput", "inputFields": [{"key": "xml"}]},
        },
        {
            "id": "c1",
            "type": "converter",
            "data": {"label": "parseXml", "conversion": "xmlToJson", "source": "$userInput.xml"},
        },
        {
            "id": "j1",
            "type": "jsonOutputMapper",
            "data": {
                "label": "okBody",
                "mappings": [
                    {"key": "ok", "value": "$true"},
                    {"key": "order", "value": "$parseXml"},
                ],
            },
        },
        {"id": "eh", "type": "errorHandler", "data": {"label": "errorHandler"}},
        {"id": "m1", **error_terminal},
    ]
    edges = [
        {"id": "e1", "source": "in_1", "target": "c1"},
        {"id": "e2", "source": "c1", "target": "j1"},
        {"id": "e3", "source": "eh", "target": "m1"},
    ]
    return nodes, edges


_MAPPER = {
    "type": "jsonOutputMapper",
    "data": {
        "label": "errorBody",
        "mappings": [{"key": "ok", "value": "$false"}, {"key": "reason", "value": "bad request"}],
    },
}
_OUTPUT = {"type": "output", "data": {"label": "errorBody", "message": "bad request"}}
_HTML = {
    "type": "htmlOutputMapper",
    "data": {"label": "errorPage", "html": "<p>Bad request</p>", "statusCode": 400},
}
_BAD_XML = {"xml": "<order><id>"}


class ErrorFlowJsonOutputMapperTests(unittest.TestCase):
    def test_execute_returns_the_mapper_object(self) -> None:
        nodes, edges = _graph(_MAPPER)

        result = execute_workflow(
            workflow_id=uuid.uuid4(), nodes=nodes, edges=edges, inputs=_BAD_XML, test_run=True
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.outputs, {"ok": False, "reason": "bad request"})

    def test_stream_returns_the_same_object(self) -> None:
        nodes, edges = _graph(_MAPPER)

        events = list(
            execute_workflow_streaming(
                workflow_id=uuid.uuid4(), nodes=nodes, edges=edges, inputs=_BAD_XML, test_run=True
            )
        )

        complete = next(e for e in events if e.get("type") == "execution_complete")
        self.assertEqual(complete["outputs"], {"ok": False, "reason": "bad request"})

    def test_an_output_node_still_answers_under_its_label(self) -> None:
        nodes, edges = _graph(_OUTPUT)

        result = execute_workflow(
            workflow_id=uuid.uuid4(), nodes=nodes, edges=edges, inputs=_BAD_XML, test_run=True
        )

        self.assertEqual(result.outputs, {"errorBody": {"result": "bad request"}})

    def test_an_html_output_mapper_still_ends_with_the_error(self) -> None:
        # Unchanged from before: only output and jsonOutputMapper give the error response.
        nodes, edges = _graph(_HTML)

        result = execute_workflow(
            workflow_id=uuid.uuid4(), nodes=nodes, edges=edges, inputs=_BAD_XML, test_run=True
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(list(result.outputs), ["error"])
        self.assertIn("invalid XML input", result.outputs["error"])

    def test_the_success_path_is_unchanged(self) -> None:
        nodes, edges = _graph(_MAPPER)

        result = execute_workflow(
            workflow_id=uuid.uuid4(),
            nodes=nodes,
            edges=edges,
            inputs={"xml": "<order><id>7</id></order>"},
            test_run=True,
        )

        self.assertEqual(result.status, "success")
        self.assertEqual(result.outputs["ok"], True)


if __name__ == "__main__":
    unittest.main()
