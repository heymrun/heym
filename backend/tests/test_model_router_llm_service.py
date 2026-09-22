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

        # The breakdown places tools by this offset; without it parallel sub-agents
        # all draw from zero and the run's shape is lost.
        entry = result["tool_calls"][0]
        self.assertIn("start_ms", entry)
        self.assertGreaterEqual(entry["start_ms"], 0.0)
        self.assertIsInstance(entry["elapsed_ms"], float)


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


class TestRoutingReachesTheRoutedTrace(unittest.TestCase):
    """Item the Traces tab needs: routing time on the routed request's own trace."""

    def _routed_service(self, *, trace_context: object | None = None) -> tuple[object, object]:
        from app.db.models import CredentialType
        from app.services.llm_service import LLMService
        from app.services.model_router import BoundOption, RouteDecision, RouterOption

        option = RouterOption(
            id="opt_1",
            label="Fast",
            credential_id=str(uuid.uuid4()),
            model="gpt-4o-mini",
            criteria="easy",
        )
        bound = BoundOption(
            option=option,
            credential_type="openai",
            api_key="sk",
            base_url=None,
            credential_name="OpenAI prod",
            credential_uuid=uuid.uuid4(),
        )
        router = mock.Mock()
        router.label = "Auto Model"
        router.credential_id = str(uuid.uuid4())
        router.trace_context = None
        router.config.decision_model = "jev-latest"
        router.route.return_value = RouteDecision(
            option=option, decision_ms=41.5, trace_id="decision-trace-1"
        )
        service = LLMService(
            credential_type=CredentialType.model_router,
            api_key="",
            trace_context=trace_context,
            router=router,
        )
        return service, bound

    def _resolve(self, service: object, bound: object) -> None:
        from app.services import llm_service as llm_service_module

        with (
            mock.patch.object(llm_service_module, "load_option_credential", return_value=bound),
            mock.patch.object(llm_service_module, "create_openai_client", return_value=mock.Mock()),
        ):
            service._resolve_turn(
                model="auto", system_instruction=None, message="m", tool_names=None
            )

    def test_the_router_inherits_the_request_trace_context(self) -> None:
        context = LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())
        service, bound = self._routed_service(trace_context=context)
        self._resolve(service, bound)

        # Most callers build their context after the router, so without this the
        # decision call writes no trace row and routing looks invisible.
        self.assertIs(service.router.trace_context, context)

    def test_a_router_built_with_its_own_context_keeps_it(self) -> None:
        own = LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())
        request = LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())
        service, bound = self._routed_service(trace_context=request)
        service.router.trace_context = own
        self._resolve(service, bound)

        self.assertIs(service.router.trace_context, own)

    def test_the_summary_carries_per_turn_and_total_decision_time(self) -> None:
        service, bound = self._routed_service()
        self._resolve(service, bound)
        self._resolve(service, bound)

        summary = service.model_routing_summary()
        self.assertEqual(summary["decisionModel"], "jev-latest")
        self.assertEqual(summary["decisionTotalMs"], 83.0)
        self.assertEqual(summary["calls"][0]["turn"], 1)
        self.assertEqual(summary["calls"][0]["decisionMs"], 41.5)
        self.assertEqual(summary["calls"][0]["decisionTraceId"], "decision-trace-1")
        self.assertFalse(summary["calls"][0]["reused"])
        self.assertEqual(summary["calls"][1]["turn"], 2)

    def test_the_routed_trace_response_carries_the_routing(self) -> None:
        from app.services import llm_service as llm_service_module

        context = LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())
        service, bound = self._routed_service(trace_context=context)
        self._resolve(service, bound)

        with mock.patch.object(llm_service_module, "record_llm_trace") as recorded:
            service._record_trace(
                request_type="chat.completions",
                provider="OpenAI",
                model="gpt-4o-mini",
                request={},
                response={"text": "hi"},
                error=None,
                elapsed_ms=120.0,
            )

        # Routing rides on the trace context, so every surface that records a trace
        # gets it without changing its own signature; `record_llm_trace` merges it
        # into the stored response.
        passed = recorded.call_args.kwargs["context"]
        self.assertEqual(passed.model_routing["routerLabel"], "Auto Model")
        self.assertEqual(passed.model_routing["decisionTotalMs"], 41.5)
        self.assertEqual(recorded.call_args.kwargs["response"], {"text": "hi"})

    def test_an_unrouted_request_records_no_routing_block(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService

        service = LLMService(
            credential_type=CredentialType.openai,
            api_key="sk",
            trace_context=LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4()),
        )
        with mock.patch.object(llm_service_module, "record_llm_trace") as recorded:
            service._record_trace(
                request_type="chat.completions",
                provider="OpenAI",
                model="gpt-4o",
                request={},
                response={"text": "hi"},
                error=None,
                elapsed_ms=1.0,
            )

        self.assertIsNone(recorded.call_args.kwargs["context"].model_routing)
        self.assertNotIn("model_routing", recorded.call_args.kwargs["response"])


class TestRoutedRequestWritesBothTraces(unittest.IsolatedAsyncioTestCase):
    """A routed request must leave two rows: the decision, and the model that ran.

    The surfaces that build their trace context after the router (Data Tables, the
    expression builder, Evals, Playwright, the board mapper) were writing only the
    model row, so automatic selection was invisible in the Traces tab.
    """

    async def test_execute_llm_traces_the_decision_and_the_model(self) -> None:
        from app.db.models import CredentialType
        from app.services import decision_models
        from app.services import llm_service as llm_service_module
        from app.services import model_router as model_router_module
        from app.services.model_router import build_router_for_credential

        router = build_router_for_credential(
            credential_id=str(uuid.uuid4()),
            credential_name="Auto Model",
            credential_type="model_router",
            config={
                "decision_credential_id": str(uuid.uuid4()),
                "decision_model": "jev-latest",
                "options": [
                    {
                        "label": "Fast",
                        "credential_id": str(uuid.uuid4()),
                        "model": "gpt-4o-mini",
                        "criteria": "easy",
                        "is_default": True,
                    },
                    {
                        "label": "Deep",
                        "credential_id": str(uuid.uuid4()),
                        "model": "gpt-5",
                        "criteria": "hard",
                    },
                ],
            },
            # Built with no trace context, exactly as the API surfaces build it.
        )
        self.assertIsNone(router.trace_context)

        # The caller's context, created after the router, as those surfaces do.
        context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            source="data_table_ai",
            node_label="AI DataTable Extend",
        )

        recorded: list[dict] = []

        def fake_record(*args: object, **kwargs: object) -> uuid.UUID:
            payload = dict(kwargs)
            if args:
                payload["context"] = args[0]
            recorded.append(payload)
            return uuid.uuid4()

        def bind(option: object) -> object:
            from app.services.model_router import BoundOption

            return BoundOption(
                option=option,
                credential_type="openai",
                api_key="sk",
                base_url=None,
                credential_name="OpenAI prod",
                credential_uuid=uuid.uuid4(),
            )

        message = mock.Mock()
        message.content = "answer"
        choice = mock.Mock()
        choice.message = message
        raw_item = mock.Mock()
        raw_item.choices = [choice]
        turn = mock.Mock()
        turn.text = "answer"
        turn.prompt_tokens = 1
        turn.completion_tokens = 1
        turn.total_tokens = 2
        turn.raw_items = [raw_item]

        with (
            mock.patch.object(
                model_router_module,
                "load_decision_credential",
                return_value={"base_url": "https://api.typesafe.ai", "api_key": "k"},
            ),
            mock.patch.object(
                decision_models,
                "record_llm_trace",
                side_effect=lambda ctx, **kw: fake_record(ctx, **kw),
            ),
            mock.patch.object(
                model_router_module,
                "call_decision_model",
                side_effect=lambda **kw: (
                    decision_models.record_llm_trace(
                        kw["trace_context"],
                        request_type="decision.systemone",
                        request={},
                        response={},
                        provider="decision",
                        model="jev-latest",
                    ),
                    {"answers": {"route": {"type": "choice", "choice": "Deep"}}},
                )[1],
            ),
            mock.patch.object(llm_service_module, "load_option_credential", side_effect=bind),
            mock.patch.object(llm_service_module, "create_openai_client", return_value=mock.Mock()),
            mock.patch.object(llm_service_module, "record_llm_trace", side_effect=fake_record),
            mock.patch.object(
                llm_service_module.asyncio, "to_thread", new=mock.AsyncMock(return_value=turn)
            ),
        ):
            result = await llm_service_module.execute_llm(
                credential_type=CredentialType.model_router.value,
                api_key="",
                base_url=None,
                model="auto",
                system_instruction="Return JSON.",
                user_message="Add a priority column.",
                trace_context=context,
                router=router,
            )

        self.assertEqual(result["model"], "gpt-5")
        providers = [entry.get("provider") for entry in recorded]
        self.assertIn("decision", providers, "the decision call left no trace row")
        self.assertIn("OpenAI", providers, "the routed model left no trace row")

        model_row = next(entry for entry in recorded if entry.get("provider") == "OpenAI")
        self.assertEqual(model_row["model"], "gpt-5")
        self.assertEqual(model_row["context"].model_routing["routerLabel"], "Auto Model")
        self.assertEqual(model_row["context"].model_routing["calls"][0]["model"], "gpt-5")


class TestRecordMergesRoutingIntoTheResponse(unittest.TestCase):
    def test_a_context_with_routing_stores_it_on_the_response(self) -> None:
        from app.services import llm_trace

        context = LLMTraceContext(
            user_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
            model_routing={"routerLabel": "Auto Model", "calls": []},
        )
        captured: list[object] = []
        session = mock.MagicMock()
        session.__enter__.return_value.add.side_effect = captured.append

        with mock.patch.object(llm_trace, "SessionLocal", return_value=session):
            llm_trace.record_llm_trace(
                context,
                request_type="chat.completions",
                request={},
                response={"text": "hi"},
                model="gpt-5",
                provider="OpenAI",
            )

        self.assertEqual(captured[0].response["model_routing"]["routerLabel"], "Auto Model")
        self.assertEqual(captured[0].response["text"], "hi")

    def test_a_context_without_routing_leaves_the_response_alone(self) -> None:
        from app.services import llm_trace

        context = LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())
        captured: list[object] = []
        session = mock.MagicMock()
        session.__enter__.return_value.add.side_effect = captured.append

        with mock.patch.object(llm_trace, "SessionLocal", return_value=session):
            llm_trace.record_llm_trace(
                context,
                request_type="chat.completions",
                request={},
                response={"text": "hi"},
                model="gpt-4o",
                provider="OpenAI",
            )

        self.assertNotIn("model_routing", captured[0].response)


class TestWaterfallTiming(unittest.IsolatedAsyncioTestCase):
    """The Duration Breakdown draws a waterfall, so spans need true start offsets."""

    def test_routing_and_turns_report_offsets_in_order(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService
        from app.services.model_router import BoundOption, RouteDecision, RouterOption

        option = RouterOption(
            id="opt_1",
            label="Fast",
            credential_id=str(uuid.uuid4()),
            model="gpt-4o-mini",
            criteria="easy",
        )
        bound = BoundOption(
            option=option,
            credential_type="openai",
            api_key="sk",
            base_url=None,
            credential_name="OpenAI prod",
            credential_uuid=uuid.uuid4(),
        )
        router = mock.Mock()
        router.label = "Auto Model"
        router.credential_id = str(uuid.uuid4())
        router.trace_context = None
        router.config.decision_model = "jev-latest"
        router.route.return_value = RouteDecision(option=option, decision_ms=5.0)

        service = LLMService(credential_type=CredentialType.model_router, api_key="", router=router)
        with (
            mock.patch.object(llm_service_module, "load_option_credential", return_value=bound),
            mock.patch.object(llm_service_module, "create_openai_client", return_value=mock.Mock()),
        ):
            service._resolve_turn(
                model="auto", system_instruction=None, message="a", tool_names=None
            )
            service._record_turn_timing(service._offset_ms(), 40.0)
            service._resolve_turn(
                model="auto", system_instruction=None, message="b", tool_names=None
            )
            service._record_turn_timing(service._offset_ms(), 30.0)

        summary = service.model_routing_summary()
        starts = [call["startMs"] for call in summary["calls"]]
        # The first thing in a routed request is its first decision, so it starts at 0.
        self.assertEqual(starts[0], 0.0)
        self.assertGreaterEqual(starts[1], starts[0])

        timings = summary["turnTimings"]
        self.assertEqual([entry["turn"] for entry in timings], [1, 2])
        self.assertEqual([entry["durationMs"] for entry in timings], [40.0, 30.0])
        self.assertGreaterEqual(timings[1]["startMs"], timings[0]["startMs"])

    async def test_a_plain_request_records_one_turn(self) -> None:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService

        message = mock.Mock()
        message.content = "answer"
        choice = mock.Mock()
        choice.message = message
        raw_item = mock.Mock()
        raw_item.choices = [choice]
        turn = mock.Mock()
        turn.text = "answer"
        turn.prompt_tokens = 1
        turn.completion_tokens = 1
        turn.total_tokens = 2
        turn.raw_items = [raw_item]

        service = LLMService(credential_type=CredentialType.openai, api_key="sk")
        with (
            mock.patch.object(service, "_get_client", return_value=(mock.Mock(), "OpenAI")),
            mock.patch.object(
                llm_service_module.asyncio, "to_thread", new=mock.AsyncMock(return_value=turn)
            ),
        ):
            await service.execute(model="gpt-4o", system_instruction=None, user_message="hi")

        timings = service.turn_timings()
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["turn"], 1)
        self.assertGreaterEqual(timings[0]["durationMs"], 0.0)

    def test_no_turns_means_no_timings(self) -> None:
        from app.db.models import CredentialType
        from app.services.llm_service import LLMService

        self.assertIsNone(
            LLMService(credential_type=CredentialType.openai, api_key="sk").turn_timings()
        )


class TestToolTraceCorrelation(unittest.IsolatedAsyncioTestCase):
    """A tool that ran work of its own links to the trace that work wrote."""

    async def _run_tool(self, tool_result: object) -> dict:
        from app.db.models import CredentialType
        from app.services import llm_service as llm_service_module
        from app.services.llm_service import LLMService

        call = mock.Mock()
        call.id = "call_1"
        call.name = "call_sub_agent"
        call.arguments = '{"sub_agent_label": "restaurantFinder"}'

        first = _chat_turn(None, [call])
        second = _chat_turn("done", [])

        service = LLMService(credential_type=CredentialType.openai, api_key="sk")
        with (
            mock.patch.object(service, "_get_client", return_value=(mock.Mock(), "OpenAI")),
            mock.patch.object(service, "_record_trace"),
            mock.patch.object(
                llm_service_module.ChatCompletionsTransport,
                "create",
                side_effect=[first, second],
            ),
        ):
            return await service.execute_with_tools(
                model="gpt-4o",
                system_instruction="sys",
                user_message="go",
                tools=[{"name": "call_sub_agent", "description": "", "parameters": {}}],
                tool_executor=lambda *args, **kwargs: tool_result,
                max_tool_iterations=4,
            )

    async def test_the_tool_record_keeps_the_trace_the_tool_wrote(self) -> None:
        result = await self._run_tool(
            {"text": "sub agent answer", "_trace_id": "sub-agent-trace-1"}
        )
        entry = result["tool_calls"][0]

        self.assertEqual(entry["trace_id"], "sub-agent-trace-1")
        # The private key is taken off the payload, so it never reaches the model.
        self.assertNotIn("_trace_id", entry["result"])

    async def test_a_tool_without_a_trace_of_its_own_records_none(self) -> None:
        result = await self._run_tool({"text": "plain answer"})
        self.assertNotIn("trace_id", result["tool_calls"][0])

    async def test_a_non_dict_tool_result_is_left_alone(self) -> None:
        result = await self._run_tool("just text")
        self.assertNotIn("trace_id", result["tool_calls"][0])


if __name__ == "__main__":
    unittest.main()
