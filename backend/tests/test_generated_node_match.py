"""Telling an edited node from a new one when the chat builder returns a whole workflow."""

import unittest

from app.services.generated_node_match import node_label, previous_node_version


def _node(node_id: str, node_type: str = "dataTable", label: str = "saveLead") -> dict:
    return {"id": node_id, "type": node_type, "data": {"label": label}}


class PreviousNodeVersionTests(unittest.TestCase):
    def test_same_id_and_type_match_first(self) -> None:
        by_label = _node("other")
        by_id = _node("save", label="renamed")

        self.assertIs(previous_node_version(_node("save"), [by_label, by_id]), by_id)

    def test_same_label_and_type_match_when_the_id_changed(self) -> None:
        old = _node("old-id")

        self.assertIs(previous_node_version(_node("new-id"), [old]), old)

    def test_a_new_node_has_no_previous_version(self) -> None:
        self.assertIsNone(previous_node_version(_node("x", label="fresh"), [_node("y")]))
        self.assertIsNone(previous_node_version(_node("y", "http"), [_node("y")]))

    def test_label_is_empty_without_data(self) -> None:
        self.assertEqual(node_label({"id": "n"}), "")
        self.assertEqual(node_label(_node("n")), "saveLead")


if __name__ == "__main__":
    unittest.main()
