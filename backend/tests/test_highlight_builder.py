import unittest

from app.services.highlight.highlight_builder import build_highlight_payload


def _row(node_id, node_type, output, label=None, metadata=None):
    row = {
        "node_id": node_id,
        "node_label": label or node_id,
        "node_type": node_type,
        "status": "success",
        "output": output,
        "execution_time_ms": 1.0,
        "error": None,
    }
    if metadata:
        row["metadata"] = metadata
    return row


def _node(node_id, node_type, highlight=None, label=None):
    data = {"label": label or node_id}
    if highlight is not None:
        data["highlight"] = highlight
    return {"id": node_id, "type": node_type, "data": data}


class TestBuildHighlightPayload(unittest.TestCase):
    def test_input_node_uses_run_inputs(self):
        nodes = [_node("t1", "textInput"), _node("o1", "output")]
        rows = [_row("t1", "textInput", {"text": "hi"}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={"topic": "AI"})
        records = payload["records"]
        self.assertEqual(records[0]["node_id"], "t1")
        self.assertEqual(records[0]["kind"], "input")
        self.assertIn("topic", records[0]["runs"][0])

    def test_output_node_record(self):
        nodes = [_node("o1", "output")]
        rows = [_row("o1", "output", {"message": "final result"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(payload["records"][-1]["kind"], "output")
        self.assertEqual(payload["records"][-1]["runs"], ["final result"])

    def test_final_fallback_when_no_output_node(self):
        nodes = [_node("h1", "http")]
        rows = [_row("h1", "http", {"text": "last message"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(payload["records"][0]["kind"], "final")
        self.assertEqual(payload["records"][0]["runs"], ["last message"])

    def test_agent_and_llm_auto_highlighted(self):
        nodes = [_node("a1", "agent"), _node("l1", "llm"), _node("o1", "output")]
        rows = [
            _row("a1", "agent", {"text": "agent says"}),
            _row("l1", "llm", {"content": "llm says"}),
            _row("o1", "output", {"message": "done"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        kinds = {r["node_id"]: r["kind"] for r in payload["records"]}
        self.assertEqual(kinds["a1"], "agent")
        self.assertEqual(kinds["l1"], "llm")

    def test_flagged_node_output_only(self):
        nodes = [_node("h1", "http", highlight=True), _node("o1", "output")]
        rows = [_row("h1", "http", {"status": 200}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        ids = [r["node_id"] for r in payload["records"]]
        self.assertIn("h1", ids)

    def test_unflagged_middle_node_excluded(self):
        nodes = [_node("h1", "http"), _node("o1", "output")]
        rows = [_row("h1", "http", {"status": 200}), _row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        ids = [r["node_id"] for r in payload["records"]]
        self.assertNotIn("h1", ids)

    def test_dedup_no_duplicate_for_auto_and_flagged(self):
        nodes = [_node("o1", "output", highlight=True)]
        rows = [_row("o1", "output", {"message": "done"})]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(len([r for r in payload["records"] if r["node_id"] == "o1"]), 1)

    def test_multi_run_collects_runs_in_order(self):
        nodes = [_node("a1", "agent")]
        rows = [
            _row("a1", "agent", {"text": "run 1"}),
            _row("a1", "agent", {"text": "run 2"}),
            _row("a1", "agent", {"text": "run 3"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        record = payload["records"][0]
        self.assertEqual(record["runs"], ["run 1", "run 2", "run 3"])

    def test_retry_attempts_excluded_from_runs(self):
        nodes = [_node("a1", "agent")]
        rows = [
            _row("a1", "agent", {"text": "failed"}, metadata={"retry_stage": "attempt_failed"}),
            _row("a1", "agent", {"text": "ok"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(payload["records"][0]["runs"], ["ok"])

    def test_message_extraction_json_fallback(self):
        nodes = [_node("h1", "http", highlight=True), _node("o1", "output")]
        rows = [
            _row("h1", "http", {"status": 200, "body": {"a": 1}}),
            _row("o1", "output", {"message": "done"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        http_record = next(r for r in payload["records"] if r["node_id"] == "h1")
        self.assertIn("status", http_record["runs"][0])

    def test_records_in_execution_order(self):
        nodes = [_node("t1", "textInput"), _node("a1", "agent"), _node("o1", "output")]
        rows = [
            _row("t1", "textInput", {"text": "in"}),
            _row("a1", "agent", {"text": "mid"}),
            _row("o1", "output", {"message": "out"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={"x": 1})
        self.assertEqual([r["node_id"] for r in payload["records"]], ["t1", "a1", "o1"])

    def test_widget_no_input_node_no_input_record(self):
        nodes = [_node("c1", "chartOutput")]
        rows = [_row("c1", "chartOutput", {"type": "bar", "data": []})]
        payload = build_highlight_payload(rows, nodes, inputs=None)
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["kind"], "output")

    def test_trigger_type_is_input(self):
        nodes = [_node("s1", "slackTrigger"), _node("o1", "output")]
        rows = [
            _row("s1", "slackTrigger", {"text": "event"}),
            _row("o1", "output", {"message": "done"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={"channel": "C1"})
        self.assertEqual(payload["records"][0]["kind"], "input")

    def test_empty_loop_iteration_runs_excluded(self):
        # A 2-item loop that emits a 3rd empty iteration must show 2 runs, not 3.
        nodes = [_node("a1", "agent")]
        rows = [
            _row("a1", "agent", {"text": "item 1"}),
            _row("a1", "agent", {"text": "item 2"}),
            _row("a1", "agent", {}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={})
        self.assertEqual(payload["records"][0]["runs"], ["item 1", "item 2"])

    def test_input_prefers_body_not_request_envelope(self):
        nodes = [_node("t1", "textInput"), _node("o1", "output")]
        rows = [_row("t1", "textInput", {"text": "hi"}), _row("o1", "output", {"message": "done"})]
        inputs = {
            "body": {"text": "girdiler burada"},
            "query": {"test_run": "true"},
            "headers": {"host": "localhost:10105"},
        }
        payload = build_highlight_payload(rows, nodes, inputs=inputs)
        input_run = payload["records"][0]["runs"][0]
        self.assertEqual(input_run, "girdiler burada")
        self.assertNotIn("headers", input_run)
        self.assertNotIn("host", input_run)

    def test_execution_order_terminal_output_last(self):
        # Executor batches loop-body results AFTER the output node, so the output
        # node's first appearance is early; the builder must still order it last.
        nodes = [
            _node("t1", "textInput"),
            _node("o1", "output"),
            _node("h1", "http", highlight=True),
            _node("a1", "agent"),
        ]
        rows = [
            _row("t1", "textInput", {"text": "in"}),
            _row("o1", "output", {"message": "final"}),  # appears before body rows
            _row("h1", "http", {"status": 200}),
            _row("h1", "http", {"status": 200}),
            _row("a1", "agent", {"text": "comment"}),
            _row("a1", "agent", {"text": "comment"}),
        ]
        payload = build_highlight_payload(rows, nodes, inputs={"body": {"text": "in"}})
        kinds_order = [r["node_id"] for r in payload["records"]]
        self.assertEqual(kinds_order, ["t1", "h1", "a1", "o1"])
        self.assertEqual(payload["records"][0]["kind"], "input")
        self.assertEqual(payload["records"][-1]["kind"], "output")


if __name__ == "__main__":
    unittest.main()
