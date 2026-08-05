"""Coverage for the per-node ``extraBody`` passthrough on llm and agent nodes.

The feature lets a workflow author attach provider-specific request parameters (for
example ``{"thinking": {"type": "disabled"}}``) to every LLM API call a node makes. It is
off by default, so the most important assertions here are the ones proving that a node
without the fields sends no ``extra_body`` at all.
"""

import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.llm_service import LLMService
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.extra_body import resolve_extra_body
from app.services.node_execution.nodes import llm_node
from app.services.workflow_executor import WorkflowExecutor


class ResolveExtraBodyTests(unittest.TestCase):
    """``resolve_extra_body`` is the single parse/validate seam for both node types."""

    def _executor(self) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[])

    def test_returns_none_when_fields_are_absent(self) -> None:
        self.assertIsNone(resolve_extra_body(self._executor(), {}, {}, "llm-1"))

    def test_returns_none_when_toggle_is_off(self) -> None:
        node_data = {"extraBodyEnabled": False, "extraBody": '{"thinking": {"type": "disabled"}}'}
        self.assertIsNone(resolve_extra_body(self._executor(), node_data, {}, "llm-1"))

    def test_returns_none_when_text_is_blank(self) -> None:
        node_data = {"extraBodyEnabled": True, "extraBody": "   "}
        self.assertIsNone(resolve_extra_body(self._executor(), node_data, {}, "llm-1"))

    def test_parses_a_json_object(self) -> None:
        node_data = {
            "extraBodyEnabled": True,
            "extraBody": '{"thinking": {"type": "disabled"}, "max_tokens": 16}',
        }
        self.assertEqual(
            resolve_extra_body(self._executor(), node_data, {}, "llm-1"),
            {"thinking": {"type": "disabled"}, "max_tokens": 16},
        )

    def test_resolves_expressions_before_parsing(self) -> None:
        node_data = {"extraBodyEnabled": True, "extraBody": '{"max_tokens": $prev.limit}'}
        context = {"prev": {"limit": 16}}
        self.assertEqual(
            resolve_extra_body(self._executor(), node_data, context, "llm-1"),
            {"max_tokens": 16},
        )

    def test_resolves_expressions_inside_string_values(self) -> None:
        node_data = {"extraBodyEnabled": True, "extraBody": '{"user": "$prev.name"}'}
        context = {"prev": {"name": "ada"}}
        self.assertEqual(
            resolve_extra_body(self._executor(), node_data, context, "llm-1"),
            {"user": "ada"},
        )

    def test_raises_on_malformed_json(self) -> None:
        node_data = {"extraBodyEnabled": True, "extraBody": '{"thinking": '}
        with self.assertRaises(ValueError) as ctx:
            resolve_extra_body(self._executor(), node_data, {}, "llm-1")
        self.assertIn("Invalid extra body JSON", str(ctx.exception))

    def test_raises_on_json_array(self) -> None:
        node_data = {"extraBodyEnabled": True, "extraBody": '["disable_reasoning"]'}
        with self.assertRaises(ValueError) as ctx:
            resolve_extra_body(self._executor(), node_data, {}, "llm-1")
        self.assertIn("must be a JSON object", str(ctx.exception))

    def test_raises_on_json_scalar(self) -> None:
        node_data = {"extraBodyEnabled": True, "extraBody": "42"}
        with self.assertRaises(ValueError) as ctx:
            resolve_extra_body(self._executor(), node_data, {}, "llm-1")
        self.assertIn("must be a JSON object", str(ctx.exception))


class LlmNodeHandlerExtraBodyTests(unittest.TestCase):
    """The llm handler resolves the payload and hands it to the executor."""

    def _run_handler(self, node_data: dict) -> dict:
        executor = MagicMock()
        executor._visible_inputs.return_value = {}
        executor._resolve_template.side_effect = lambda tmpl, *a, **kw: tmpl
        executor._execute_llm_node.return_value = {"text": "ok", "model": "gpt-4o-mini"}
        executor._pop_internal_trace_id.return_value = None

        ctx = NodeExecutionContext(
            executor=executor,
            node_id="llm-1",
            inputs={},
            allow_branch_skip=False,
            start_time=0.0,
            node={},
            node_type="llm",
            node_data=node_data,
            node_label="llm",
        )
        llm_node.execute(ctx)
        return executor._execute_llm_node.call_args.kwargs

    def test_forwards_resolved_extra_body(self) -> None:
        kwargs = self._run_handler(
            {
                "model": "gpt-4o-mini",
                "credentialId": "cred-1",
                "extraBodyEnabled": True,
                "extraBody": '{"max_tokens": 16}',
            }
        )
        self.assertEqual(kwargs["extra_body"], {"max_tokens": 16})

    def test_sends_nothing_when_disabled(self) -> None:
        kwargs = self._run_handler({"model": "gpt-4o-mini", "credentialId": "cred-1"})
        self.assertIsNone(kwargs["extra_body"])

    def test_malformed_json_fails_the_node(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run_handler(
                {
                    "model": "gpt-4o-mini",
                    "credentialId": "cred-1",
                    "extraBodyEnabled": True,
                    "extraBody": "{oops",
                }
            )
        self.assertIn("Invalid extra body JSON", str(ctx.exception))


class _CredentialPatchMixin:
    """Shared stubs for the credential lookup inside the executor LLM paths."""

    def _credential_patches(self):  # type: ignore[no-untyped-def]
        mock_cred = MagicMock()
        mock_cred.type = MagicMock()
        mock_cred.type.value = "openai"
        mock_cred.encrypted_config = b"enc"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cred
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        return (
            patch("app.db.session.SessionLocal", return_value=mock_db),
            patch(
                "app.services.encryption.decrypt_config",
                return_value={"api_key": "test-key"},
            ),
        )


class ExecuteLlmNodeExtraBodyTests(_CredentialPatchMixin, unittest.TestCase):
    """``_execute_llm_node`` forwards the payload to every attempt it makes."""

    def _call(self, **overrides: object) -> list[dict]:
        captured: list[dict] = []

        def fake_execute_llm(**kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs)

            async def _coro() -> dict:
                if len(captured) == 1 and overrides.pop("_fail_first", False):
                    raise RuntimeError("primary failed")
                return {"text": "ok", "model": kwargs["model"]}

            return _coro()

        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.actor_user_id = uuid.uuid4()
        session_patch, decrypt_patch = self._credential_patches()
        kwargs: dict = {
            "credential_id": "cred-1",
            "node_id": "llm-1",
            "model": "gpt-4o-mini",
            "system_instruction": None,
            "user_message": "hello",
            "temperature": 0.7,
            "reasoning_effort": None,
            "max_tokens": None,
            "json_output_enabled": False,
            "json_output_schema": None,
            "image_input": None,
        }
        kwargs.update({k: v for k, v in overrides.items() if not k.startswith("_")})

        with (
            patch("app.services.llm_service.execute_llm", fake_execute_llm),
            session_patch,
            decrypt_patch,
        ):
            executor._execute_llm_node(**kwargs)
        return captured

    def test_extra_body_reaches_the_primary_call(self) -> None:
        captured = self._call(extra_body={"thinking": {"type": "disabled"}})
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["extra_body"], {"thinking": {"type": "disabled"}})

    def test_no_extra_body_by_default(self) -> None:
        captured = self._call()
        self.assertIsNone(captured[0]["extra_body"])

    def test_fallback_attempt_also_receives_extra_body(self) -> None:
        captured: list[dict] = []
        calls = {"n": 0}

        def fake_execute_llm(**kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs)
            calls["n"] += 1
            attempt = calls["n"]

            async def _coro() -> dict:
                if attempt == 1:
                    raise RuntimeError("primary failed")
                return {"text": "ok", "model": kwargs["model"]}

            return _coro()

        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.actor_user_id = uuid.uuid4()
        session_patch, decrypt_patch = self._credential_patches()

        with (
            patch("app.services.llm_service.execute_llm", fake_execute_llm),
            session_patch,
            decrypt_patch,
        ):
            executor._execute_llm_node(
                credential_id="cred-1",
                node_id="llm-1",
                model="gpt-4o-mini",
                system_instruction=None,
                user_message="hello",
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                json_output_enabled=False,
                json_output_schema=None,
                image_input=None,
                fallback_credential_id="cred-2",
                fallback_model="gpt-4o",
                extra_body={"max_tokens": 16},
            )

        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["extra_body"], {"max_tokens": 16})
        self.assertEqual(captured[1]["extra_body"], {"max_tokens": 16})
        self.assertEqual(captured[1]["model"], "gpt-4o")

    def test_batch_mode_forwards_extra_body(self) -> None:
        captured: list[dict] = []

        def fake_execute_llm_batch(**kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs)

            async def _coro() -> dict:
                return {"results": [], "model": kwargs["model"]}

            return _coro()

        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.actor_user_id = uuid.uuid4()
        session_patch, decrypt_patch = self._credential_patches()

        with (
            patch("app.services.llm_service.execute_llm_batch", fake_execute_llm_batch),
            session_patch,
            decrypt_patch,
        ):
            executor._execute_llm_node(
                credential_id="cred-1",
                node_id="llm-1",
                model="gpt-4o-mini",
                system_instruction=None,
                user_message=["hello", "there"],
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                json_output_enabled=False,
                json_output_schema=None,
                image_input=None,
                batch_mode_enabled=True,
                extra_body={"service_tier": "flex"},
            )

        self.assertEqual(captured[0]["extra_body"], {"service_tier": "flex"})

    def test_image_output_never_receives_extra_body(self) -> None:
        """Image requests take a different endpoint shape, so they stay excluded."""
        captured: list[dict] = []

        def fake_execute_image_generation(**kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs)

            async def _coro() -> dict:
                return {"images": [], "model": kwargs["model"]}

            return _coro()

        executor = WorkflowExecutor(nodes=[], edges=[])
        executor.actor_user_id = uuid.uuid4()
        session_patch, decrypt_patch = self._credential_patches()

        with (
            patch(
                "app.services.llm_service.execute_image_generation",
                fake_execute_image_generation,
            ),
            session_patch,
            decrypt_patch,
        ):
            executor._execute_llm_node(
                credential_id="cred-1",
                node_id="llm-1",
                model="gpt-image-1",
                system_instruction=None,
                user_message="a cat",
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                json_output_enabled=False,
                json_output_schema=None,
                image_input=None,
                output_type="image",
                extra_body={"max_tokens": 16},
            )

        self.assertEqual(len(captured), 1)
        self.assertNotIn("extra_body", captured[0])


class AgentNodeExtraBodyTests(unittest.TestCase):
    """The agent node resolves its own payload and applies it to the tool loop."""

    def _make_executor(self, nodes: dict) -> WorkflowExecutor:
        ex = WorkflowExecutor.__new__(WorkflowExecutor)
        ex.nodes = nodes
        ex.edges = []
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

    def _run_agent(self, extra_node_data: dict) -> list[dict]:
        agent_id = "agent-1"
        node_data = {
            "label": "Agent",
            "model": "gpt-4o-mini",
            "credentialId": "cred-1",
            "tools": [],
            "mcpConnections": [],
            "skills": [],
            "toolTimeoutSeconds": 30,
            "maxToolIterations": 5,
            "systemInstruction": "You are helpful.",
            "userMessage": "hello",
            "active": True,
            **extra_node_data,
        }
        nodes = {agent_id: {"type": "agent", "data": node_data}}
        ex = self._make_executor(nodes)

        captured: list[dict] = []

        def fake_execute_llm(**kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs)

            async def _coro() -> dict:
                return {"text": "done", "model": kwargs["model"], "usage": {}, "elapsed_ms": 1.0}

            return _coro()

        mock_cred = MagicMock()
        mock_cred.type = MagicMock()
        mock_cred.type.value = "openai"
        mock_cred.encrypted_config = b"enc"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cred
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch("app.services.llm_service.execute_llm", fake_execute_llm),
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
            ex._execute_agent_node(agent_id, {}, node_data)

        return captured

    def test_agent_forwards_extra_body(self) -> None:
        captured = self._run_agent(
            {"extraBodyEnabled": True, "extraBody": '{"thinking": {"type": "disabled"}}'}
        )
        self.assertEqual(captured[0]["extra_body"], {"thinking": {"type": "disabled"}})

    def test_agent_sends_nothing_by_default(self) -> None:
        captured = self._run_agent({})
        self.assertIsNone(captured[0]["extra_body"])

    def test_agent_malformed_json_fails_the_node(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run_agent({"extraBodyEnabled": True, "extraBody": "{oops"})
        self.assertIn("Invalid extra body JSON", str(ctx.exception))

    def test_agent_tool_loop_receives_extra_body(self) -> None:
        """With tools attached the agent takes the tool-loop path, which must carry it too."""
        agent_id = "agent-1"
        node_data = {
            "label": "Agent",
            "model": "gpt-4o-mini",
            "credentialId": "cred-1",
            "tools": [
                {
                    "name": "echo",
                    "description": "echo back",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
            "mcpConnections": [],
            "skills": [],
            "toolTimeoutSeconds": 30,
            "maxToolIterations": 5,
            "systemInstruction": "You are helpful.",
            "userMessage": "hello",
            "active": True,
            "extraBodyEnabled": True,
            "extraBody": '{"thinking": {"type": "disabled"}}',
        }
        nodes = {agent_id: {"type": "agent", "data": node_data}}
        ex = self._make_executor(nodes)

        captured: list[dict] = []

        def fake_execute_llm_with_tools(**kwargs):  # type: ignore[no-untyped-def]
            captured.append(kwargs)

            async def _coro() -> dict:
                return {
                    "text": "done",
                    "model": kwargs["model"],
                    "tool_calls": [],
                    "usage": {},
                    "elapsed_ms": 1.0,
                }

            return _coro()

        mock_cred = MagicMock()
        mock_cred.type = MagicMock()
        mock_cred.type.value = "openai"
        mock_cred.encrypted_config = b"enc"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_cred
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "app.services.llm_service.execute_llm_with_tools",
                fake_execute_llm_with_tools,
            ),
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
            ex._execute_agent_node(agent_id, {}, node_data)

        self.assertEqual(captured[0]["extra_body"], {"thinking": {"type": "disabled"}})


class LLMServiceExtraBodyTests(unittest.IsolatedAsyncioTestCase):
    """The service layer places the payload on the outgoing request."""

    @staticmethod
    def _response(content: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def _run_with_tools(self, extra_body: dict | None) -> list[dict]:
        captured: list[dict] = []

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            return self._response("done")

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            await service.execute_with_tools(
                model="test-model",
                system_instruction=None,
                user_message="hi",
                tools=[{"name": "child", "parameters": {"type": "object"}}],
                tool_executor=lambda *_args: {"status": "success"},
                extra_body=extra_body,
            )
        return captured

    async def test_tool_loop_request_carries_extra_body(self) -> None:
        captured = await self._run_with_tools({"thinking": {"type": "disabled"}})
        self.assertEqual(captured[0]["extra_body"], {"thinking": {"type": "disabled"}})

    async def test_tool_loop_omits_extra_body_when_unset(self) -> None:
        captured = await self._run_with_tools(None)
        self.assertNotIn("extra_body", captured[0])

    async def test_execute_request_carries_extra_body(self) -> None:
        captured: list[dict] = []

        def create(**kwargs: object) -> SimpleNamespace:
            captured.append(dict(kwargs))
            return self._response("done")

        client = SimpleNamespace(
            base_url="http://test",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        service = LLMService(CredentialType.openai, "test-key")

        with patch.object(service, "_get_client", return_value=(client, "Test")):
            await service.execute(
                model="test-model",
                system_instruction=None,
                user_message="hi",
                extra_body={"max_tokens": 16},
            )

        self.assertEqual(captured[0]["extra_body"], {"max_tokens": 16})


class LLMServiceBatchExtraBodyTests(unittest.IsolatedAsyncioTestCase):
    """Batch entries are raw request bodies, so the keys merge at the top level."""

    async def _captured_batch_bodies(self, extra_body: dict | None) -> list[dict]:
        uploaded: list[bytes] = []

        def files_create(*, file: tuple, purpose: str) -> SimpleNamespace:
            del purpose
            uploaded.append(file[1].getvalue())
            return SimpleNamespace(id="file-1")

        def batches_create(**_kwargs: object) -> SimpleNamespace:
            raise RuntimeError("stop after upload")

        client = SimpleNamespace(
            base_url="http://test",
            files=SimpleNamespace(create=files_create),
            batches=SimpleNamespace(create=batches_create),
        )
        service = LLMService(CredentialType.openai, "test-key")

        with (
            patch.object(service, "_get_client", return_value=(client, "Test")),
            patch.object(service, "probe_batch_support", return_value=(True, "ok")),
        ):
            with self.assertRaises(RuntimeError):
                await service.execute_batch(
                    model="gpt-4o-mini",
                    system_instruction=None,
                    user_messages=["one", "two"],
                    extra_body=extra_body,
                )

        payload = uploaded[0].decode("utf-8")
        return [json.loads(line)["body"] for line in payload.splitlines()]

    async def test_extra_body_merges_into_each_batch_entry(self) -> None:
        bodies = await self._captured_batch_bodies({"service_tier": "flex"})
        self.assertEqual(len(bodies), 2)
        for body in bodies:
            self.assertEqual(body["service_tier"], "flex")
            self.assertNotIn("extra_body", body)

    async def test_batch_entries_unchanged_when_unset(self) -> None:
        bodies = await self._captured_batch_bodies(None)
        for body in bodies:
            self.assertNotIn("service_tier", body)
            self.assertNotIn("extra_body", body)


if __name__ == "__main__":
    unittest.main()
