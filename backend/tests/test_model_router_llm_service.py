import unittest
import uuid
from dataclasses import replace
from unittest import mock

from app.services.llm_trace import LLMTraceContext


class TestTraceContextRouterFields(unittest.TestCase):
    def _context(self) -> LLMTraceContext:
        return LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            node_id="node-1",
            node_label="Agent",
            source="workflow",
            session_id="session-1",
        )

    def test_router_fields_default_to_none(self) -> None:
        context = self._context()
        self.assertIsNone(context.router_credential_id)
        self.assertIsNone(context.router_label)

    def test_replace_rebinds_the_credential_and_keeps_the_same_trace_id_list(self) -> None:
        context = self._context()
        router_id = uuid.uuid4()
        actual_credential = uuid.uuid4()

        rebound = replace(
            context,
            credential_id=actual_credential,
            router_credential_id=router_id,
            router_label="Auto Model",
        )

        self.assertEqual(rebound.credential_id, actual_credential)
        self.assertEqual(rebound.router_credential_id, router_id)
        self.assertEqual(rebound.router_label, "Auto Model")
        # The executor reads trace ids off the context it built, so the list must be
        # the very same object, not a copy. A fresh LLMTraceContext(...) here would
        # silently break every "Open trace" link in the execution log.
        self.assertIs(rebound.trace_ids, context.trace_ids)
        rebound.trace_ids.append(uuid.uuid4())
        self.assertEqual(len(context.trace_ids), 1)

    def test_record_llm_trace_persists_the_router_columns(self) -> None:
        from app.services import llm_trace

        context = replace(
            self._context(),
            router_credential_id=uuid.uuid4(),
            router_label="Auto Model",
        )
        captured: list[object] = []
        session = mock.MagicMock()
        session.__enter__.return_value.add.side_effect = captured.append

        with mock.patch.object(llm_trace, "SessionLocal", return_value=session):
            llm_trace.record_llm_trace(
                context,
                request_type="chat.completions",
                request={"model": "gpt-5"},
                response={"text": "hi"},
                model="gpt-5",
                provider="OpenAI",
            )

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].router_credential_id, context.router_credential_id)
        self.assertEqual(captured[0].router_label, "Auto Model")
        self.assertEqual(captured[0].model, "gpt-5")
        self.assertEqual(captured[0].credential_id, context.credential_id)


class TestResolveTurn(unittest.TestCase):
    def _service(self, **kwargs: object) -> object:
        from app.db.models import CredentialType
        from app.services.llm_service import LLMService

        defaults = {
            "credential_type": CredentialType.openai,
            "api_key": "sk-static",
            "base_url": None,
        }
        defaults.update(kwargs)
        return LLMService(**defaults)

    def _routed_service(self, decision: object) -> tuple[object, object]:
        from app.db.models import CredentialType
        from app.services.model_router import BoundOption, RouterOption

        option = getattr(decision, "option")
        bound = BoundOption(
            option=option,
            credential_type="openai",
            api_key="sk-routed",
            base_url=None,
            credential_name="OpenAI prod",
            credential_uuid=uuid.uuid4(),
        )
        assert isinstance(option, RouterOption)
        router = mock.Mock()
        router.label = "Auto Model"
        router.credential_id = str(uuid.uuid4())
        router.route.return_value = decision
        service = self._service(
            credential_type=CredentialType.model_router, api_key="", router=router
        )
        return service, bound

    def test_without_a_router_the_binding_is_the_static_credential(self) -> None:
        service = self._service()
        with mock.patch.object(
            service, "_get_client", return_value=(mock.sentinel.client, "OpenAI")
        ):
            binding = service._resolve_turn(
                model="gpt-4o", system_instruction="s", message="m", tool_names=None
            )
        self.assertIs(binding.client, mock.sentinel.client)
        self.assertEqual(binding.provider, "OpenAI")
        self.assertEqual(binding.model, "gpt-4o")
        self.assertIsNone(binding.router_label)
        self.assertFalse(binding.fallback)

    def test_with_a_router_the_binding_comes_from_the_chosen_option(self) -> None:
        from app.services import llm_service as llm_service_module
        from app.services.model_router import RouteDecision, RouterOption

        option = RouterOption(
            id="opt_2",
            label="Deep",
            credential_id=str(uuid.uuid4()),
            model="gpt-5",
            criteria="hard",
        )
        service, bound = self._routed_service(RouteDecision(option=option))

        with (
            mock.patch.object(llm_service_module, "load_option_credential", return_value=bound),
            mock.patch.object(
                llm_service_module, "create_openai_client", return_value=mock.sentinel.routed
            ),
        ):
            binding = service._resolve_turn(
                model="auto", system_instruction="s", message="m", tool_names=["search"]
            )

        service.router.route.assert_called_once_with(
            system_instruction="s", message="m", tool_names=["search"]
        )
        self.assertEqual(binding.model, "gpt-5")
        self.assertEqual(binding.provider, "OpenAI")
        self.assertEqual(binding.router_label, "Auto Model")
        self.assertEqual(binding.option_label, "Deep")
        self.assertEqual(binding.credential_name, "OpenAI prod")
        self.assertEqual(binding.credential_id, bound.credential_uuid)

    def test_each_resolved_turn_is_recorded_for_the_executor(self) -> None:
        from app.services import llm_service as llm_service_module
        from app.services.model_router import RouteDecision, RouterOption

        option = RouterOption(
            id="opt_1",
            label="Fast",
            credential_id=str(uuid.uuid4()),
            model="gpt-4o-mini",
            criteria="easy",
        )
        service, bound = self._routed_service(
            RouteDecision(option=option, fallback=True, error="Decision model timed out")
        )

        with (
            mock.patch.object(llm_service_module, "load_option_credential", return_value=bound),
            mock.patch.object(
                llm_service_module, "create_openai_client", return_value=mock.sentinel.routed
            ),
        ):
            service._resolve_turn(
                model="auto", system_instruction=None, message="a", tool_names=None
            )
            service._resolve_turn(
                model="auto", system_instruction=None, message="b", tool_names=None
            )

        summary = service.model_routing_summary()
        self.assertEqual(summary["routerLabel"], "Auto Model")
        self.assertEqual(len(summary["calls"]), 2)
        self.assertEqual(summary["calls"][0]["model"], "gpt-4o-mini")
        self.assertEqual(summary["calls"][0]["option"], "Fast")
        self.assertTrue(summary["calls"][0]["fallback"])
        self.assertEqual(summary["calls"][0]["error"], "Decision model timed out")

    def test_no_router_means_no_routing_summary(self) -> None:
        self.assertIsNone(self._service().model_routing_summary())

    def test_a_router_with_the_responses_api_is_refused(self) -> None:
        from app.db.models import CredentialType

        with self.assertRaises(ValueError) as ctx:
            self._service(
                credential_type=CredentialType.model_router,
                api_key="",
                router=mock.Mock(),
                use_responses_api=True,
            )
        self.assertIn("Responses API", str(ctx.exception))

    def test_a_routed_trace_row_names_the_real_credential_and_the_router(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService, TurnBinding

        context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            node_id="n1",
        )
        service = LLMService(
            credential_type=CredentialType.model_router,
            api_key="",
            trace_context=context,
            router=mock.Mock(),
        )
        actual_credential = uuid.uuid4()
        router_credential = uuid.uuid4()
        binding = TurnBinding(
            client=mock.Mock(),
            provider="OpenAI",
            model="gpt-5",
            credential_id=actual_credential,
            router_credential_id=router_credential,
            router_label="Auto Model",
        )

        with mock.patch.object(llm_service_module, "record_llm_trace") as recorded:
            service._record_trace(
                request_type="chat.completions",
                provider="OpenAI",
                model="gpt-5",
                request={},
                response={},
                error=None,
                elapsed_ms=1.0,
                binding=binding,
            )

        passed = recorded.call_args.kwargs["context"]
        self.assertEqual(passed.credential_id, actual_credential)
        self.assertEqual(passed.router_credential_id, router_credential)
        self.assertEqual(passed.router_label, "Auto Model")
        self.assertIs(passed.trace_ids, context.trace_ids)


class TestExecuteRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_execute_uses_the_routed_model_in_result_and_trace(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService, TurnBinding

        service = LLMService(
            credential_type=CredentialType.model_router,
            api_key="",
            router=mock.Mock(),
        )
        service.router.label = "Auto Model"
        service.router.credential_id = str(uuid.uuid4())
        service._routed_calls.append(
            {
                "model": "gpt-5",
                "option": "Deep",
                "credentialName": "OpenAI prod",
                "fallback": False,
                "error": None,
            }
        )
        binding = TurnBinding(
            client=mock.Mock(),
            provider="OpenAI",
            model="gpt-5",
            credential_id=uuid.uuid4(),
            credential_name="OpenAI prod",
            router_credential_id=uuid.uuid4(),
            router_label="Auto Model",
            option_label="Deep",
        )
        message = mock.Mock()
        message.content = "routed answer"
        choice = mock.Mock()
        choice.message = message
        raw_item = mock.Mock()
        raw_item.choices = [choice]

        turn = mock.Mock()
        turn.text = "routed answer"
        turn.prompt_tokens = 3
        turn.completion_tokens = 4
        turn.total_tokens = 7
        turn.raw_items = [raw_item]

        recorded: list[dict] = []

        with (
            mock.patch.object(service, "_resolve_turn", return_value=binding) as resolve,
            mock.patch.object(
                service, "_record_trace", side_effect=lambda **kw: recorded.append(kw)
            ),
            mock.patch.object(
                llm_service_module.asyncio, "to_thread", new=mock.AsyncMock(return_value=turn)
            ),
        ):
            result = await service.execute(
                model="auto",
                system_instruction="You are helpful.",
                user_message="Explain this diff.",
            )

        resolve.assert_called_once()
        self.assertEqual(resolve.call_args.kwargs["system_instruction"], "You are helpful.")
        self.assertEqual(resolve.call_args.kwargs["message"], "Explain this diff.")
        self.assertEqual(result["model"], "gpt-5")
        self.assertEqual(recorded[-1]["model"], "gpt-5")
        self.assertIs(recorded[-1]["binding"], binding)
        self.assertEqual(result["_model_routing"]["routerLabel"], "Auto Model")


def _chat_turn(text: str | None, tool_calls: list) -> mock.Mock:
    message = mock.Mock()
    message.content = text
    choice = mock.Mock()
    choice.message = message
    raw_item = mock.Mock()
    raw_item.choices = [choice]

    turn = mock.Mock()
    turn.text = text
    turn.prompt_tokens = 1
    turn.completion_tokens = 1
    turn.total_tokens = 2
    turn.raw_items = [raw_item]
    turn.tool_calls = tool_calls
    return turn


class TestExecuteWithToolsRoutesEachTurn(unittest.IsolatedAsyncioTestCase):
    async def test_two_turns_can_land_on_two_models(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService, TurnBinding

        service = LLMService(
            credential_type=CredentialType.model_router,
            api_key="",
            router=mock.Mock(),
        )
        service.router.label = "Auto Model"
        service.router.credential_id = str(uuid.uuid4())

        def _binding(model: str) -> TurnBinding:
            return TurnBinding(
                client=mock.Mock(),
                provider="OpenAI",
                model=model,
                credential_id=uuid.uuid4(),
                credential_name="OpenAI prod",
                router_credential_id=uuid.uuid4(),
                router_label="Auto Model",
                option_label=model,
            )

        call = mock.Mock()
        call.id = "call_1"
        call.name = "search"
        call.arguments = '{"q": "x"}'

        turns = [_chat_turn(None, [call]), _chat_turn("final", [])]

        with (
            mock.patch.object(
                service,
                "_resolve_turn",
                side_effect=[_binding("gpt-4o-mini"), _binding("gpt-5")],
            ) as resolve,
            mock.patch.object(service, "_record_trace"),
            mock.patch.object(
                llm_service_module.ChatCompletionsTransport,
                "create",
                side_effect=turns,
            ),
        ):
            result = await service.execute_with_tools(
                model="auto",
                system_instruction="sys",
                user_message="go",
                tools=[{"name": "search", "description": "", "parameters": {}}],
                tool_executor=lambda *args, **kwargs: "tool output",
                max_tool_iterations=4,
            )

        self.assertEqual(resolve.call_count, 2)
        # Turn one routes on the user message; turn two routes on the tool result.
        self.assertEqual(resolve.call_args_list[0].kwargs["message"], "go")
        self.assertIn("tool output", str(resolve.call_args_list[1].kwargs["message"]))
        self.assertEqual(resolve.call_args_list[0].kwargs["tool_names"], ["search"])
        self.assertEqual(result["model"], "gpt-5")


class TestRouterRejections(unittest.IsolatedAsyncioTestCase):
    def _router_service(self) -> object:
        from app.db.models import CredentialType
        from app.services.llm_service import LLMService

        return LLMService(
            credential_type=CredentialType.model_router, api_key="", router=mock.Mock()
        )

    async def test_batch_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self._router_service().execute_batch(
                model="auto",
                system_instruction=None,
                user_messages=["a", "b"],
            )
        self.assertIn("Batch", str(ctx.exception))

    async def test_image_generation_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self._router_service().execute_image_generation(model="auto", prompt="a cat")
        self.assertIn("image", str(ctx.exception).lower())

    async def test_image_edit_is_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self._router_service().execute_image_edit(
                model="auto", prompt="a cat", image_input="data:image/png;base64,AAA"
            )
        self.assertIn("image", str(ctx.exception).lower())


class TestRouterPassesThroughModuleFunctions(unittest.IsolatedAsyncioTestCase):
    async def test_execute_llm_forwards_the_router(self) -> None:
        from app.services import llm_service as llm_service_module

        router = mock.Mock()
        captured: dict = {}

        class FakeService:
            def __init__(self, *args: object, **kwargs: object) -> None:
                captured.update(kwargs)

            async def execute(self, **kwargs: object) -> dict:
                return {"text": "ok", "model": "gpt-5"}

        with mock.patch.object(llm_service_module, "LLMService", FakeService):
            await llm_service_module.execute_llm(
                credential_type="model_router",
                api_key="",
                base_url=None,
                model="auto",
                system_instruction=None,
                user_message="hi",
                router=router,
            )

        self.assertIs(captured["router"], router)


class TestExecutorLlmNodeRouting(unittest.TestCase):
    def test_routing_summary_reaches_node_metadata(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        output = {
            "text": "answer",
            "model": "gpt-5",
            "_model_routing": {
                "routerLabel": "Auto Model",
                "routerCredentialId": str(uuid.uuid4()),
                "calls": [
                    {
                        "model": "gpt-5",
                        "option": "Deep",
                        "credentialName": "OpenAI prod",
                        "fallback": False,
                        "error": None,
                    }
                ],
            },
        }
        metadata: dict = {}
        routing = WorkflowExecutor._pop_model_routing(output)
        if routing:
            metadata["model_routing"] = routing

        self.assertNotIn("_model_routing", output)
        self.assertEqual(metadata["model_routing"]["routerLabel"], "Auto Model")
        self.assertEqual(metadata["model_routing"]["calls"][0]["model"], "gpt-5")

    def test_pop_ignores_a_non_dict(self) -> None:
        from app.services.workflow_executor import WorkflowExecutor

        self.assertIsNone(WorkflowExecutor._pop_model_routing({"_model_routing": "nope"}))
        self.assertIsNone(WorkflowExecutor._pop_model_routing({}))

    def test_traceable_error_carries_routing(self) -> None:
        from app.services.workflow_executor import NodeTraceableExecutionError

        error = NodeTraceableExecutionError(
            "boom", "trace-1", model_routing={"routerLabel": "Auto Model", "calls": []}
        )
        self.assertEqual(error.trace_id, "trace-1")
        self.assertEqual(error.model_routing["routerLabel"], "Auto Model")

    def test_traceable_error_routing_defaults_to_none(self) -> None:
        from app.services.workflow_executor import NodeTraceableExecutionError

        self.assertIsNone(NodeTraceableExecutionError("boom", "trace-1").model_routing)


class TestAgentPathBuildsRouter(unittest.TestCase):
    def test_agent_loop_builds_a_router_and_forwards_it(self) -> None:
        import inspect

        from app.services import workflow_executor

        source = inspect.getsource(workflow_executor.WorkflowExecutor)
        # Both the llm and the agent attempt loops must build a router, or an agent on
        # Auto Model would bail out on "Credential has no API key".
        self.assertGreaterEqual(source.count("build_router_for_credential"), 2)
        self.assertGreaterEqual(source.count("router=router"), 4)

    def test_the_hitl_policy_classifier_does_not_route(self) -> None:
        import inspect

        from app.services import workflow_executor

        source = inspect.getsource(workflow_executor.WorkflowExecutor)
        self.assertIn("if hitl_enabled and mcp_tool_names and router is None:", source)


class TestEverySurfaceForwardsTheRouter(unittest.TestCase):
    """Auto Model has to work everywhere a model is picked, not just in the nodes."""

    EXECUTE_LLM_SURFACES = (
        "app.api.playwright",
        "app.api.data_tables",
        "app.api.decisions",
        "app.api.dashboards",
        "app.api.expressions",
        "app.services.eval_service",
        "app.services.board_mapper_service",
        "app.services.agent_memory_service",
    )

    # These build their own client instead of going through LLMService, so they route
    # through `resolve_model_binding` rather than an `execute_llm(router=...)` argument.
    OWN_CLIENT_SURFACES = (
        "app.api.ai_assistant",
        "app.api.chats",
        "app.api.skill_builder",
        "app.api.alerts",
    )

    def test_execute_llm_surfaces_build_and_forward_a_router(self) -> None:
        import importlib
        import inspect

        missing: list[str] = []
        for name in self.EXECUTE_LLM_SURFACES:
            source = inspect.getsource(importlib.import_module(name))
            if "build_router_for_credential" not in source or "router" not in source:
                missing.append(name)
        self.assertEqual(missing, [], f"surfaces not wired for Auto Model: {missing}")

    def test_own_client_surfaces_bind_through_resolve_model_binding(self) -> None:
        import importlib
        import inspect

        missing: list[str] = []
        for name in self.OWN_CLIENT_SURFACES:
            source = inspect.getsource(importlib.import_module(name))
            if "resolve_model_binding" not in source:
                missing.append(name)
        self.assertEqual(missing, [], f"surfaces not wired for Auto Model: {missing}")

    def test_no_surface_keeps_a_hand_rolled_llm_credential_guard(self) -> None:
        import importlib
        import inspect

        stale: list[str] = []
        for name in self.EXECUTE_LLM_SURFACES + self.OWN_CLIENT_SURFACES:
            source = inspect.getsource(importlib.import_module(name))
            if "CredentialType.openai, CredentialType.google, CredentialType.custom" in source:
                stale.append(name)
        # A local tuple silently excludes model_router, which is exactly how a surface
        # ends up rejecting Auto Model. LLM_CREDENTIAL_TYPES is the one list.
        self.assertEqual(stale, [], f"surfaces still guarding on a local tuple: {stale}")

    def test_the_shared_type_list_includes_the_router(self) -> None:
        from app.db.models import LLM_CREDENTIAL_TYPES, CredentialType

        self.assertIn(CredentialType.model_router, LLM_CREDENTIAL_TYPES)
        self.assertIn(CredentialType.openai, LLM_CREDENTIAL_TYPES)

    def test_a_context_estimate_does_not_spend_a_decision_call(self) -> None:
        import inspect

        from app.api import chats

        source = inspect.getsource(chats)
        self.assertIn("consult_router=False", source)


class TestTraceApiSurface(unittest.TestCase):
    def _item(self, **kwargs: object) -> object:
        import datetime

        from app.models.schemas import LLMTraceListItem

        base = {
            "id": uuid.uuid4(),
            "created_at": datetime.datetime.now(),
            "source": "workflow",
            "request_type": "chat.completions",
            "status": "success",
        }
        base.update(kwargs)
        return LLMTraceListItem(**base)

    def test_list_item_carries_the_router_columns(self) -> None:
        router_id = uuid.uuid4()
        item = self._item(
            provider="OpenAI",
            model="gpt-5",
            router_credential_id=router_id,
            router_label="Auto Model",
        )
        self.assertEqual(item.router_label, "Auto Model")
        self.assertEqual(item.router_credential_id, router_id)
        # The real model stays in `model`, which is what pricing and the per-model
        # stats read; putting the router there would make cost attribution wrong.
        self.assertEqual(item.model, "gpt-5")

    def test_router_fields_default_to_none(self) -> None:
        item = self._item()
        self.assertIsNone(item.router_label)
        self.assertIsNone(item.router_credential_id)

    def test_trace_search_and_responses_cover_the_router_label(self) -> None:
        import inspect

        from app.api import traces

        source = inspect.getsource(traces)
        self.assertIn("LLMTrace.router_label.ilike(pattern)", source)
        self.assertIn("router_label=trace.router_label", source)
        # by_model must keep grouping on the real model.
        self.assertIn('LLMTrace.model.label("model")', source)


if __name__ == "__main__":
    unittest.main()
