"""Deciding when a workflow run answers with text/html instead of JSON."""

import unittest

from app.services.html_response import build_html_response, find_sole_html_terminal


def _html_node(node_id: str = "html1") -> dict:
    return {"id": node_id, "type": "htmlOutputMapper", "data": {"label": "page"}}


class FindSoleHtmlTerminalTests(unittest.TestCase):
    def test_finds_the_only_terminal(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}, _html_node()]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")

    def test_none_when_there_is_no_html_node(self) -> None:
        nodes = [{"id": "in1", "type": "textInput", "data": {}}]
        self.assertIsNone(find_sole_html_terminal(nodes, []))

    def test_none_when_a_second_terminal_exists(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "out1", "type": "output", "data": {"label": "out"}},
        ]
        edges = [{"source": "in1", "target": "html1"}, {"source": "in1", "target": "out1"}]
        self.assertIsNone(find_sole_html_terminal(nodes, edges))

    def test_none_when_the_html_node_is_deactivated(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            {"id": "html1", "type": "htmlOutputMapper", "data": {"active": False}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertIsNone(find_sole_html_terminal(nodes, edges))

    def test_sticky_notes_do_not_count_as_a_second_terminal(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "note", "type": "sticky", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")

    def test_error_handlers_do_not_count_as_a_second_terminal(self) -> None:
        nodes = [
            {"id": "in1", "type": "textInput", "data": {}},
            _html_node(),
            {"id": "err", "type": "errorHandler", "data": {}},
        ]
        edges = [{"source": "in1", "target": "html1"}]
        self.assertEqual(find_sole_html_terminal(nodes, edges), "html1")


class BuildHtmlResponseTests(unittest.TestCase):
    def test_builds_a_response_from_the_node_result(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "success",
                "output": {
                    "html": "<h1>hi</h1>",
                    "statusCode": 201,
                    "contentType": "text/html; charset=utf-8",
                },
            }
        ]
        response = build_html_response(node_results, "html1")
        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.body, b"<h1>hi</h1>")
        self.assertEqual(response.headers["content-type"], "text/html; charset=utf-8")

    def test_none_when_the_node_did_not_run(self) -> None:
        self.assertIsNone(build_html_response([], "html1"))

    def test_none_when_the_node_errored(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "error",
                "output": {},
            }
        ]
        self.assertIsNone(build_html_response(node_results, "html1"))

    def test_none_when_the_output_is_not_the_expected_shape(self) -> None:
        node_results = [
            {
                "node_id": "html1",
                "node_type": "htmlOutputMapper",
                "status": "success",
                "output": "x",
            }
        ]
        self.assertIsNone(build_html_response(node_results, "html1"))


if __name__ == "__main__":
    unittest.main()
