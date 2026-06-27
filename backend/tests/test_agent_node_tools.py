"""Unit tests for agent node tool connections (canvas nodes as LLM tools)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.services.workflow_executor import WorkflowExecutor, _coerce_boolean


def _make_executor(nodes: dict, edges: list) -> WorkflowExecutor:
    """Minimal WorkflowExecutor with given nodes and edges, no DB."""
    ex = WorkflowExecutor.__new__(WorkflowExecutor)
    ex.nodes = nodes
    ex.edges = edges
    ex.node_results = {}
    ex.actor_user_id = None
    return ex


class TestBuildNodeToolSchemas(unittest.TestCase):
    def test_builds_schema_from_agent_provided_fields(self) -> None:
        agent_id = "agent-1"
        http_id = "http-1"
        nodes = {
            agent_id: {"type": "agent", "data": {"label": "My Agent"}},
            http_id: {
                "type": "http",
                "data": {
                    "label": "Fetch Data",
                    "curl": "curl https://fixed.com",
                    "agentProvidedFields": ["curl"],
                },
            },
        }
        edges = [{"source": http_id, "target": agent_id, "targetHandle": "tool-input"}]
        ex = _make_executor(nodes, edges)

        schemas = ex._build_node_tool_schemas(agent_id)

        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["name"], "fetch_data")
        self.assertEqual(schemas[0]["_source"], "node_tool")
        self.assertEqual(schemas[0]["_node_id"], http_id)
        self.assertIn("curl", schemas[0]["parameters"]["properties"])
        self.assertEqual(schemas[0]["parameters"]["required"], ["curl"])

    def test_empty_agent_provided_fields_creates_parameterless_tool(self) -> None:
        agent_id = "agent-1"
        code_id = "code-1"
        nodes = {
            agent_id: {"type": "agent", "data": {"label": "Agent"}},
            code_id: {"type": "code", "data": {"label": "Run Script", "agentProvidedFields": []}},
        }
        edges = [{"source": code_id, "target": agent_id, "targetHandle": "tool-input"}]
        ex = _make_executor(nodes, edges)

        schemas = ex._build_node_tool_schemas(agent_id)

        self.assertEqual(len(schemas), 1)
        self.assertEqual(schemas[0]["parameters"]["properties"], {})
        self.assertEqual(schemas[0]["parameters"]["required"], [])

    def test_ignores_non_tool_input_edges(self) -> None:
        agent_id = "agent-1"
        http_id = "http-1"
        nodes = {
            agent_id: {"type": "agent", "data": {"label": "Agent"}},
            http_id: {"type": "http", "data": {"label": "HTTP", "agentProvidedFields": ["curl"]}},
        }
        edges = [{"source": http_id, "target": agent_id, "targetHandle": "input"}]
        ex = _make_executor(nodes, edges)

        schemas = ex._build_node_tool_schemas(agent_id)
        self.assertEqual(schemas, [])

    def test_name_collision_adds_numeric_suffix(self) -> None:
        agent_id = "agent-1"
        nodes = {
            agent_id: {"type": "agent", "data": {}},
            "http-1": {"type": "http", "data": {"label": "Fetch Data", "agentProvidedFields": []}},
            "http-2": {"type": "http", "data": {"label": "Fetch Data", "agentProvidedFields": []}},
        }
        edges = [
            {"source": "http-1", "target": agent_id, "targetHandle": "tool-input"},
            {"source": "http-2", "target": agent_id, "targetHandle": "tool-input"},
        ]
        ex = _make_executor(nodes, edges)

        schemas = ex._build_node_tool_schemas(agent_id)
        names = [s["name"] for s in schemas]
        self.assertEqual(len(set(names)), 2)
        self.assertIn("fetch_data", names)
        self.assertIn("fetch_data_2", names)

    def test_missing_node_is_skipped(self) -> None:
        agent_id = "agent-1"
        nodes = {agent_id: {"type": "agent", "data": {}}}
        edges = [{"source": "ghost-node", "target": agent_id, "targetHandle": "tool-input"}]
        ex = _make_executor(nodes, edges)

        schemas = ex._build_node_tool_schemas(agent_id)
        self.assertEqual(schemas, [])

    def test_new_integration_fields_are_exposed_as_tool_parameters(self) -> None:
        """Integration inputs selected in the UI are retained in each node tool schema."""
        agent_id = "agent-1"
        fields_by_node = {
            "discord-1": ["message", "username", "avatarUrl"],
            "github-1": ["githubOwner", "githubRepo", "githubTitle", "githubDraft"],
            "supabase-1": ["supabaseTable", "supabaseRows", "supabaseLimit", "supabaseAscending"],
            "notion-1": ["notionDataSourceId", "notionProperties", "notionPageSize"],
            "s3-1": ["s3Bucket", "s3Key", "s3MaxKeys", "s3IncludeBinary"],
        }
        nodes = {agent_id: {"type": "agent", "data": {"label": "Agent"}}}
        edges = []
        for node_id, fields in fields_by_node.items():
            nodes[node_id] = {
                "type": node_id.split("-", maxsplit=1)[0],
                "data": {"label": node_id, "agentProvidedFields": fields},
            }
            edges.append({"source": node_id, "target": agent_id, "targetHandle": "tool-input"})

        schemas = _make_executor(nodes, edges)._build_node_tool_schemas(agent_id)
        fields_by_tool = {
            schema["_node_id"]: set(schema["parameters"]["properties"]) for schema in schemas
        }

        self.assertEqual(len(fields_by_tool), len(fields_by_node))
        for node_id, fields in fields_by_node.items():
            self.assertEqual(fields_by_tool[node_id], set(fields))


class TestExecuteNodeTool(unittest.TestCase):
    def _make_executor_with_execute(
        self, nodes: dict, edges: list, node_results: dict | None = None
    ) -> WorkflowExecutor:
        ex = _make_executor(nodes, edges)
        ex.node_results = node_results or {}
        ex.check_cancelled = MagicMock()
        return ex

    def test_merges_agent_args_into_node_data(self) -> None:
        from app.services.workflow_executor import NodeResult

        http_id = "http-1"
        nodes = {
            http_id: {
                "type": "http",
                "data": {
                    "label": "Fetch",
                    "curl": "curl https://fixed.com",
                    "agentProvidedFields": ["curl"],
                    "active": True,
                },
            }
        }
        ex = self._make_executor_with_execute(nodes, [])

        captured_data: list[dict] = []

        def fake_execute_node(node_id: str, inputs: dict, **kwargs) -> NodeResult:
            captured_data.append(dict(ex.nodes[node_id]["data"]))
            return NodeResult(
                node_id=node_id,
                node_label="Fetch",
                node_type="http",
                status="success",
                output={"body": "ok"},
                execution_time_ms=10.0,
            )

        ex.execute_node = fake_execute_node  # type: ignore[assignment]

        tool_def = {"_source": "node_tool", "_node_id": http_id}
        result = ex._execute_node_tool(tool_def, {"curl": "curl https://dynamic.com"})

        self.assertEqual(captured_data[0]["curl"], "curl https://dynamic.com")
        self.assertEqual(result, {"body": "ok"})
        # Original data restored after execution
        self.assertEqual(ex.nodes[http_id]["data"]["curl"], "curl https://fixed.com")

    def test_returns_error_dict_on_node_failure(self) -> None:
        from app.services.workflow_executor import NodeResult

        http_id = "http-1"
        nodes = {http_id: {"type": "http", "data": {"label": "Fetch", "agentProvidedFields": []}}}
        ex = self._make_executor_with_execute(nodes, [])

        def fake_execute_node(node_id: str, inputs: dict, **kwargs) -> NodeResult:
            return NodeResult(
                node_id=node_id,
                node_label="Fetch",
                node_type="http",
                status="error",
                output={},
                execution_time_ms=5.0,
                error="Connection refused",
            )

        ex.execute_node = fake_execute_node  # type: ignore[assignment]

        tool_def = {"_source": "node_tool", "_node_id": http_id}
        result = ex._execute_node_tool(tool_def, {})

        self.assertIn("error", result)
        self.assertEqual(result["error"], "Connection refused")

    def test_returns_error_when_node_not_found(self) -> None:
        ex = _make_executor({}, [])
        tool_def = {"_source": "node_tool", "_node_id": "ghost"}
        result = ex._execute_node_tool(tool_def, {})
        self.assertIn("error", result)

    def test_preserves_agent_argument_types_when_merging_node_data(self) -> None:
        from app.services.workflow_executor import NodeResult

        node_id = "s3-1"
        ex = self._make_executor_with_execute(
            {
                node_id: {
                    "type": "s3",
                    "data": {
                        "label": "Archive",
                        "agentProvidedFields": ["s3MaxKeys", "s3IncludeBinary"],
                    },
                }
            },
            [],
        )
        captured_data: list[dict] = []

        def fake_execute_node(executed_node_id: str, inputs: dict, **kwargs) -> NodeResult:
            captured_data.append(dict(ex.nodes[executed_node_id]["data"]))
            return NodeResult(
                node_id=executed_node_id,
                node_label="Archive",
                node_type="s3",
                status="success",
                output={},
                execution_time_ms=1.0,
            )

        ex.execute_node = fake_execute_node  # type: ignore[assignment]
        ex._execute_node_tool(
            {"_source": "node_tool", "_node_id": node_id},
            {"s3MaxKeys": 25, "s3IncludeBinary": False},
        )

        self.assertEqual(captured_data[0]["s3MaxKeys"], 25)
        self.assertIs(captured_data[0]["s3IncludeBinary"], False)

    def test_restores_original_data_on_exception(self) -> None:
        http_id = "http-1"
        original_curl = "curl https://original.com"
        nodes = {
            http_id: {
                "type": "http",
                "data": {
                    "label": "Fetch",
                    "curl": original_curl,
                    "agentProvidedFields": ["curl"],
                },
            }
        }
        ex = self._make_executor_with_execute(nodes, [])

        def boom(node_id: str, inputs: dict, **kwargs):  # type: ignore[misc]
            raise RuntimeError("simulated crash")

        ex.execute_node = boom  # type: ignore[assignment]

        tool_def = {"_source": "node_tool", "_node_id": http_id}
        with self.assertRaises(RuntimeError):
            ex._execute_node_tool(tool_def, {"curl": "curl https://other.com"})

        self.assertEqual(ex.nodes[http_id]["data"]["curl"], original_curl)


class TestAgentProvidedBooleanValues(unittest.TestCase):
    def test_coerces_agent_provided_boolean_strings(self) -> None:
        self.assertTrue(_coerce_boolean("true"))
        self.assertFalse(_coerce_boolean("false", default=True))
        self.assertTrue(_coerce_boolean("1"))
        self.assertFalse(_coerce_boolean("0", default=True))


class TestAgentNodeToolIntegration(unittest.TestCase):
    def _make_full_executor(self, nodes: dict, edges: list) -> WorkflowExecutor:
        """WorkflowExecutor stub with all attributes needed by _execute_agent_node."""
        import uuid

        ex = WorkflowExecutor.__new__(WorkflowExecutor)
        ex.nodes = nodes
        ex.edges = edges
        ex.node_results = {}
        ex.agent_progress_queue = None
        ex._sub_agent_call_depth = 0
        ex.check_cancelled = MagicMock()
        ex.hitl_resume_context = {}
        ex.conversation_history = None
        ex.workflow_cache = {}
        ex.trace_user_id = None
        ex.actor_user_id = uuid.uuid4()
        ex.workflow_id = uuid.uuid4()
        ex.cancel_event = None
        ex._resolve_template = MagicMock(side_effect=lambda tmpl, *a, **kw: tmpl)
        ex.resolve_expression = MagicMock(return_value="")
        ex._list_mcp_tools = MagicMock(return_value=[])
        ex._build_hitl_mcp_policy = MagicMock(return_value={})
        ex._build_agent_tool_executor = MagicMock(return_value=None)
        return ex

    def test_node_tools_added_to_merged_tools(self) -> None:
        """Node tool schemas appear in the agent's tool list sent to LLM."""
        from unittest.mock import patch

        agent_id = "agent-1"
        http_id = "http-1"
        nodes = {
            agent_id: {
                "type": "agent",
                "data": {
                    "label": "Agent",
                    "model": "claude-3-5-sonnet-20241022",
                    "credentialId": "cred-1",
                    "tools": [],
                    "mcpConnections": [],
                    "skills": [],
                    "toolTimeoutSeconds": 30,
                    "maxToolIterations": 5,
                    "systemInstruction": "You are helpful.",
                    "userMessage": "hello",
                    "active": True,
                },
            },
            http_id: {
                "type": "http",
                "data": {
                    "label": "Fetch Users",
                    "curl": "curl https://api.example.com/users",
                    "agentProvidedFields": ["curl"],
                    "active": True,
                },
            },
        }
        edges = [{"source": http_id, "target": agent_id, "targetHandle": "tool-input"}]

        ex = self._make_full_executor(nodes, edges)

        captured_tools: list[list[dict]] = []

        def fake_execute_llm_with_tools(**kwargs):  # type: ignore[misc]
            captured_tools.append(kwargs.get("tools", []))

            async def _coro() -> dict:
                return {
                    "text": "done",
                    "model": "claude-3-5-sonnet-20241022",
                    "tool_calls": [],
                    "usage": {},
                    "elapsed_ms": 10.0,
                }

            return _coro()

        mock_cred = MagicMock()
        mock_cred.type = MagicMock()
        mock_cred.type.value = "anthropic"
        mock_cred.encrypted_config = b"enc"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cred
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.llm_service.execute_llm_with_tools", fake_execute_llm_with_tools),
            patch("app.db.session.SessionLocal", return_value=mock_db),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"api_key": "test-key"},
            ),
            patch(
                "app.services.agent_memory_service.augment_system_instruction_with_memory",
                side_effect=lambda si, *a, **kw: si,
            ),
        ):
            ex._execute_agent_node(agent_id, {}, nodes[agent_id]["data"])

        tool_names = [t["name"] for t in captured_tools[0]] if captured_tools else []
        self.assertIn("fetch_users", tool_names)
        node_tool = next(t for t in captured_tools[0] if t["name"] == "fetch_users")
        self.assertEqual(node_tool["_source"], "node_tool")
        self.assertIn("curl", node_tool["parameters"]["properties"])
