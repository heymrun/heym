"""Terminal mappers must never be offered to an agent as callable tools."""

import unittest

from app.services.agent_tool_policy import node_tools_for_agent
from app.services.workflow_executor import WorkflowExecutor


class AgentToolPolicyTests(unittest.TestCase):
    def _executor(self, tool_node: dict) -> WorkflowExecutor:
        nodes = [
            {"id": "agent1", "type": "agent", "data": {"label": "assistant"}},
            tool_node,
        ]
        edges = [
            {
                "id": "t1",
                "source": tool_node["id"],
                "target": "agent1",
                "targetHandle": "tool-input",
            }
        ]
        return WorkflowExecutor(nodes=nodes, edges=edges)

    def test_json_output_mapper_is_not_offered_as_a_tool(self) -> None:
        ex = self._executor(
            {"id": "map1", "type": "jsonOutputMapper", "data": {"label": "payload"}}
        )
        self.assertEqual(ex._build_node_tool_schemas("agent1"), [])

    def test_html_output_mapper_is_not_offered_as_a_tool(self) -> None:
        ex = self._executor({"id": "html1", "type": "htmlOutputMapper", "data": {"label": "page"}})
        self.assertEqual(ex._build_node_tool_schemas("agent1"), [])

    def test_an_ordinary_node_is_still_offered(self) -> None:
        ex = self._executor({"id": "http1", "type": "http", "data": {"label": "fetch"}})
        schemas = ex._build_node_tool_schemas("agent1")
        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["_node_id"], "http1")

    def test_two_nodes_with_one_name_get_numbered_tool_names(self) -> None:
        nodes = [
            {"id": "agent1", "type": "agent", "data": {"label": "assistant"}},
            {"id": "h1", "type": "http", "data": {"label": "Fetch page"}},
            {"id": "h2", "type": "http", "data": {"label": "fetch-page"}},
            {"id": "h3", "type": "http", "data": {}},
        ]
        edges = [
            {"source": node_id, "target": "agent1", "targetHandle": "tool-input"}
            for node_id in ("h1", "h2", "h3")
        ]
        ex = WorkflowExecutor(nodes=nodes, edges=edges)
        names = [schema["name"] for schema in ex._build_node_tool_schemas("agent1")]
        self.assertEqual(names, ["fetch_page", "fetch_page_2", "h3"])
        self.assertEqual(
            [(tool.node_id, tool.name) for tool in node_tools_for_agent(nodes, edges, "agent1")],
            [("h1", "fetch_page"), ("h2", "fetch_page_2"), ("h3", "h3")],
        )

    def test_the_output_node_is_deliberately_still_allowed(self) -> None:
        """Only the two mappers are blocked - narrowing further would break saved workflows."""
        ex = self._executor({"id": "out1", "type": "output", "data": {"label": "reply"}})
        self.assertEqual(len(ex._build_node_tool_schemas("agent1")), 1)


if __name__ == "__main__":
    unittest.main()
