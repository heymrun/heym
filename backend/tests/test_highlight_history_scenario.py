import unittest

from app.services.highlight.highlight_builder import build_highlight_payload


class TestHistoryHighlightScenario(unittest.TestCase):
    """History passes stored dict rows + the workflow's current nodes/flags."""

    def test_recompute_from_stored_rows_uses_current_flags(self):
        stored_rows = [
            {
                "node_id": "t1",
                "node_label": "Input",
                "node_type": "textInput",
                "status": "success",
                "output": {"text": "hi"},
                "execution_time_ms": 1.0,
                "error": None,
            },
            {
                "node_id": "h1",
                "node_label": "HTTP",
                "node_type": "http",
                "status": "success",
                "output": {"status": 200},
                "execution_time_ms": 1.0,
                "error": None,
            },
            {
                "node_id": "o1",
                "node_label": "Out",
                "node_type": "output",
                "status": "success",
                "output": {"message": "done"},
                "execution_time_ms": 1.0,
                "error": None,
            },
        ]
        # h1 is flagged on the CURRENT workflow graph
        nodes = [
            {"id": "t1", "type": "textInput", "data": {"label": "Input"}},
            {"id": "h1", "type": "http", "data": {"label": "HTTP", "highlight": True}},
            {"id": "o1", "type": "output", "data": {"label": "Out"}},
        ]
        payload = build_highlight_payload(stored_rows, nodes, {"topic": "AI"})
        ids = [r["node_id"] for r in payload["records"]]
        self.assertEqual(ids, ["t1", "h1", "o1"])

    def test_run_history_without_nodes_still_yields_structural_records(self):
        """RunHistory (chat/assistant) passes empty nodes; row node_type drives kinds."""
        rows = [
            {
                "node_id": "a1",
                "node_label": "Agent",
                "node_type": "agent",
                "status": "success",
                "output": {"text": "answer"},
                "execution_time_ms": 1.0,
                "error": None,
            },
        ]
        payload = build_highlight_payload(rows, [], {})
        self.assertEqual(payload["records"][0]["kind"], "agent")


if __name__ == "__main__":
    unittest.main()
