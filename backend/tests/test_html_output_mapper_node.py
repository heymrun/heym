"""HTML output mapper: template rendering, defaults, and structured node output."""

import unittest
import uuid

from app.services.workflow_executor import WorkflowExecutor


def _run(nodes: list[dict], edges: list[dict], body: dict) -> dict:
    ex = WorkflowExecutor(nodes=nodes, edges=edges)
    result = ex.execute(
        workflow_id=uuid.uuid4(),
        initial_inputs={"headers": {}, "query": {}, "body": body},
    )
    assert result.status == "success", result.node_results
    return {r["node_id"]: r["output"] for r in result.node_results}


class HtmlOutputMapperNodeTests(unittest.TestCase):
    EDGES = [{"id": "e1", "source": "in1", "target": "html1"}]

    def _nodes(self, data: dict) -> list[dict]:
        return [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {"id": "html1", "type": "htmlOutputMapper", "data": data},
        ]

    def test_interpolates_expressions_into_the_body(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<h1>$userInput.text</h1>"})
        outputs = _run(nodes, self.EDGES, {"text": "Hello"})
        self.assertEqual(outputs["html1"]["html"], "<h1>Hello</h1>")

    def test_resolves_several_spans_in_one_body(self) -> None:
        nodes = self._nodes(
            {
                "label": "page",
                "html": "<title>$userInput.text</title><p>$userInput.text!</p>",
            },
        )
        outputs = _run(nodes, self.EDGES, {"text": "Hi"})
        self.assertEqual(outputs["html1"]["html"], "<title>Hi</title><p>Hi!</p>")

    def test_defaults_status_and_content_type(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>ok</p>"})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 200)
        self.assertEqual(outputs["html1"]["contentType"], "text/html; charset=utf-8")

    def test_honours_configured_status_and_content_type(self) -> None:
        nodes = self._nodes(
            {
                "label": "page",
                "html": "<p>gone</p>",
                "statusCode": 404,
                "contentType": "text/plain; charset=utf-8",
            },
        )
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 404)
        self.assertEqual(outputs["html1"]["contentType"], "text/plain; charset=utf-8")

    def test_status_code_arrives_as_int_when_stored_as_string(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>x</p>", "statusCode": "201"})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 201)

    def test_out_of_range_status_falls_back_to_200(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>x</p>", "statusCode": 99})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["statusCode"], 200)

    def test_blank_template_renders_empty_not_the_inputs_dict(self) -> None:
        nodes = self._nodes({"label": "page", "html": ""})
        outputs = _run(nodes, self.EDGES, {"text": "x"})
        self.assertEqual(outputs["html1"]["html"], "")

    def test_counts_as_an_output_node_not_merely_a_leaf(self) -> None:
        nodes = self._nodes({"label": "page", "html": "<p>$userInput.text</p>"})
        ex = WorkflowExecutor(nodes=nodes, edges=self.EDGES)
        ex.execute(
            workflow_id=uuid.uuid4(),
            initial_inputs={"headers": {}, "query": {}, "body": {"text": "x"}},
        )
        self.assertIn("html1", ex.get_output_nodes())

    def test_outgoing_edges_are_severed_like_the_json_mapper(self) -> None:
        """A sink's output must not flow downstream.

        The orphaned node still runs - severing the edge leaves it unrooted, so it is
        scheduled as a start node. That is pre-existing jsonOutputMapper behaviour; what
        matters here is that htmlOutputMapper matches it rather than piping its page on.
        """
        nodes = [
            *self._nodes({"label": "page", "html": "<p>x</p>"}),
            {"id": "after", "type": "consoleLog", "data": {"label": "after"}},
        ]
        edges = [*self.EDGES, {"id": "e2", "source": "html1", "target": "after"}]
        ex = WorkflowExecutor(nodes=nodes, edges=edges)
        active_edge_ids = {e["id"] for e in ex.get_active_edges()}
        self.assertNotIn("e2", active_edge_ids)
        self.assertIn("e1", active_edge_ids)


if __name__ == "__main__":
    unittest.main()
