import unittest
from unittest import mock

from app.services import model_router
from app.services.decision_models import DecisionProviderError
from app.services.model_router import (
    ROUTER_STATE_MAX_TOOLS,
    ROUTER_STATE_MESSAGE_CHARS,
    ROUTER_STATE_SYSTEM_CHARS,
    BoundOption,
    ModelRouter,
    ModelRouterConfigError,
    ModelRouterError,
    RouterConfig,
    RouterOption,
    build_router_for_credential,
    build_routing_body,
    build_routing_state,
    load_option_credential,
    parse_router_config,
    read_route_answer,
    state_hash,
)


def _valid_config() -> dict:
    return {
        "decision_credential_id": "11111111-1111-1111-1111-111111111111",
        "decision_model": "jev-latest",
        "routing_instructions": "Pick the cheapest model that can answer correctly.",
        "options": [
            {
                "id": "opt_1",
                "label": "Fast",
                "credential_id": "22222222-2222-2222-2222-222222222222",
                "model": "gpt-4o-mini",
                "criteria": "Short factual questions.",
                "is_default": True,
            },
            {
                "id": "opt_2",
                "label": "Deep reasoning",
                "credential_id": "33333333-3333-3333-3333-333333333333",
                "model": "gpt-5",
                "criteria": "Multi-step reasoning and code.",
            },
        ],
        "timeout_seconds": 10,
    }


class TestParseRouterConfig(unittest.TestCase):
    def test_parses_a_valid_config(self) -> None:
        config = parse_router_config(_valid_config())
        self.assertIsInstance(config, RouterConfig)
        self.assertEqual(config.decision_model, "jev-latest")
        self.assertEqual(len(config.options), 2)
        self.assertIsInstance(config.options[0], RouterOption)
        self.assertEqual(config.options[0].label, "Fast")
        self.assertTrue(config.options[0].is_default)
        self.assertFalse(config.options[1].is_default)
        self.assertEqual(config.timeout_seconds, 10.0)

    def test_default_option_is_exposed(self) -> None:
        config = parse_router_config(_valid_config())
        self.assertIsNotNone(config.default_option)
        self.assertEqual(config.default_option.label, "Fast")

    def test_default_option_is_none_when_unmarked(self) -> None:
        raw = _valid_config()
        raw["options"][0].pop("is_default")
        self.assertIsNone(parse_router_config(raw).default_option)

    def test_option_lookup_by_label_is_exact_then_case_insensitive(self) -> None:
        config = parse_router_config(_valid_config())
        self.assertEqual(config.option_by_label("Deep reasoning").model, "gpt-5")
        self.assertEqual(config.option_by_label("deep REASONING").model, "gpt-5")
        self.assertIsNone(config.option_by_label("Nonexistent"))

    def test_timeout_defaults_to_ten_seconds(self) -> None:
        raw = _valid_config()
        raw.pop("timeout_seconds")
        self.assertEqual(parse_router_config(raw).timeout_seconds, 10.0)

    def test_missing_decision_credential_is_rejected(self) -> None:
        raw = _valid_config()
        raw["decision_credential_id"] = "  "
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("decision model credential", str(ctx.exception))

    def test_missing_decision_model_is_rejected(self) -> None:
        raw = _valid_config()
        raw["decision_model"] = ""
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_fewer_than_two_options_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"] = raw["options"][:1]
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("at least two", str(ctx.exception))

    def test_blank_option_label_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1]["label"] = ""
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("name", str(ctx.exception))

    def test_duplicate_option_labels_are_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1]["label"] = "fast"
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("same name", str(ctx.exception))

    def test_blank_option_model_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][0]["model"] = "   "
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_blank_option_credential_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][0]["credential_id"] = ""
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_two_defaults_are_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1]["is_default"] = True
        with self.assertRaises(ModelRouterConfigError) as ctx:
            parse_router_config(raw)
        self.assertIn("one option", str(ctx.exception))

    def test_malformed_option_row_is_rejected(self) -> None:
        raw = _valid_config()
        raw["options"][1] = "not a dict"
        with self.assertRaises(ModelRouterConfigError):
            parse_router_config(raw)

    def test_missing_option_id_is_generated(self) -> None:
        raw = _valid_config()
        raw["options"][0].pop("id")
        config = parse_router_config(raw)
        self.assertTrue(config.options[0].id)
        self.assertNotEqual(config.options[0].id, config.options[1].id)


class TestRoutingState(unittest.TestCase):
    def test_state_carries_system_message_and_tools(self) -> None:
        state = build_routing_state(
            system_instruction="You are a code reviewer.",
            message="Review this diff.",
            tool_names=["read_file", "search"],
        )
        self.assertEqual(state["system"], "You are a code reviewer.")
        self.assertEqual(state["message"], "Review this diff.")
        self.assertEqual(state["tools"], ["read_file", "search"])

    def test_absent_parts_are_omitted_rather_than_sent_empty(self) -> None:
        state = build_routing_state(system_instruction=None, message="Hi", tool_names=[])
        self.assertNotIn("system", state)
        self.assertNotIn("tools", state)
        self.assertEqual(state["message"], "Hi")

    def test_long_values_are_truncated_with_a_marker(self) -> None:
        state = build_routing_state(
            system_instruction="s" * (ROUTER_STATE_SYSTEM_CHARS + 500),
            message="m" * (ROUTER_STATE_MESSAGE_CHARS + 500),
            tool_names=[f"tool_{i}" for i in range(ROUTER_STATE_MAX_TOOLS + 10)],
        )
        self.assertTrue(state["system"].endswith("\u2026[truncated]"))
        self.assertLessEqual(len(state["system"]), ROUTER_STATE_SYSTEM_CHARS + 20)
        self.assertTrue(state["message"].endswith("\u2026[truncated]"))
        self.assertEqual(len(state["tools"]), ROUTER_STATE_MAX_TOOLS)

    def test_state_hash_is_stable_and_input_sensitive(self) -> None:
        first = build_routing_state(system_instruction="a", message="b", tool_names=["t"])
        same = build_routing_state(system_instruction="a", message="b", tool_names=["t"])
        other = build_routing_state(system_instruction="a", message="c", tool_names=["t"])
        self.assertEqual(state_hash(first), state_hash(same))
        self.assertNotEqual(state_hash(first), state_hash(other))


class TestRoutingBody(unittest.TestCase):
    def test_body_is_one_choice_question_keyed_by_option_label(self) -> None:
        config = parse_router_config(_valid_config())
        body = build_routing_body(config, {"message": "hello"})
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"], {"message": "hello"})
        question = body["questions"]["route"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(
            question["instructions"], "Pick the cheapest model that can answer correctly."
        )
        self.assertEqual(
            question["criteria"],
            {
                "Fast": "Short factual questions.",
                "Deep reasoning": "Multi-step reasoning and code.",
            },
        )

    def test_an_option_without_criteria_still_reaches_the_question(self) -> None:
        raw = _valid_config()
        raw["options"][1]["criteria"] = ""
        body = build_routing_body(parse_router_config(raw), {"message": "x"})
        self.assertIsNone(body["questions"]["route"]["criteria"]["Deep reasoning"])


class TestReadRouteAnswer(unittest.TestCase):
    def test_reads_the_choice(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Deep reasoning"}}}
        self.assertEqual(read_route_answer(payload), "Deep reasoning")

    def test_missing_answer_returns_none(self) -> None:
        self.assertIsNone(read_route_answer({"answers": {}}))
        self.assertIsNone(read_route_answer({}))
        self.assertIsNone(read_route_answer({"answers": {"route": {"type": "choice"}}}))
        self.assertIsNone(read_route_answer({"answers": {"route": "not a dict"}}))


class TestModelRouterRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.config = parse_router_config(_valid_config())

    def _router(self, config: RouterConfig | None = None) -> ModelRouter:
        return ModelRouter(
            credential_id="99999999-9999-9999-9999-999999999999",
            label="Auto Model",
            config=config or self.config,
        )

    def _credential(self) -> dict:
        return {"base_url": "https://api.typesafe.ai", "api_key": "k"}

    def test_routes_to_the_chosen_option(self) -> None:
        calls: list[dict] = []

        def fake_call(**kwargs: object) -> dict:
            calls.append(dict(kwargs))
            return {"answers": {"route": {"type": "choice", "choice": "Deep reasoning"}}}

        with (
            mock.patch.object(model_router, "call_decision_model", side_effect=fake_call),
            mock.patch.object(
                model_router, "load_decision_credential", return_value=self._credential()
            ),
        ):
            decision = self._router().route(
                system_instruction="sys", message="deep question", tool_names=None
            )

        self.assertEqual(decision.option.label, "Deep reasoning")
        self.assertEqual(decision.option.model, "gpt-5")
        self.assertFalse(decision.fallback)
        self.assertIsNone(decision.error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["timeout"], 10.0)

    def test_identical_state_reuses_the_decision_without_a_second_call(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Fast"}}}
        router = self._router()
        with (
            mock.patch.object(model_router, "call_decision_model", return_value=payload) as called,
            mock.patch.object(
                model_router, "load_decision_credential", return_value=self._credential()
            ),
        ):
            first = router.route(system_instruction="s", message="m", tool_names=None)
            second = router.route(system_instruction="s", message="m", tool_names=None)
            third = router.route(system_instruction="s", message="changed", tool_names=None)

        self.assertEqual(first.option.label, "Fast")
        self.assertEqual(second.option.label, "Fast")
        self.assertEqual(third.option.label, "Fast")
        self.assertEqual(called.call_count, 2)

    def test_provider_failure_falls_back_to_the_default_option(self) -> None:
        with (
            mock.patch.object(
                model_router,
                "call_decision_model",
                side_effect=DecisionProviderError("Decision model returned 500"),
            ),
            mock.patch.object(
                model_router, "load_decision_credential", return_value=self._credential()
            ),
        ):
            decision = self._router().route(system_instruction=None, message="m", tool_names=None)

        self.assertEqual(decision.option.label, "Fast")
        self.assertTrue(decision.fallback)
        self.assertIn("500", decision.error)

    def test_unknown_label_falls_back_to_the_default_option(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Nonexistent"}}}
        with (
            mock.patch.object(model_router, "call_decision_model", return_value=payload),
            mock.patch.object(
                model_router, "load_decision_credential", return_value=self._credential()
            ),
        ):
            decision = self._router().route(system_instruction=None, message="m", tool_names=None)

        self.assertEqual(decision.option.label, "Fast")
        self.assertTrue(decision.fallback)
        self.assertIn("Nonexistent", decision.error)

    def test_failure_without_a_default_option_raises(self) -> None:
        raw = _valid_config()
        raw["options"][0].pop("is_default")
        router = self._router(parse_router_config(raw))
        with (
            mock.patch.object(
                model_router, "call_decision_model", side_effect=DecisionProviderError("boom")
            ),
            mock.patch.object(
                model_router, "load_decision_credential", return_value=self._credential()
            ),
        ):
            with self.assertRaises(ModelRouterError) as ctx:
                router.route(system_instruction=None, message="m", tool_names=None)
        self.assertIn("boom", str(ctx.exception))

    def test_a_fallback_decision_is_not_cached(self) -> None:
        payload = {"answers": {"route": {"type": "choice", "choice": "Fast"}}}
        router = self._router()
        with (
            mock.patch.object(
                model_router,
                "call_decision_model",
                side_effect=[DecisionProviderError("boom"), payload],
            ) as called,
            mock.patch.object(
                model_router, "load_decision_credential", return_value=self._credential()
            ),
        ):
            first = router.route(system_instruction=None, message="m", tool_names=None)
            second = router.route(system_instruction=None, message="m", tool_names=None)

        self.assertTrue(first.fallback)
        self.assertFalse(second.fallback)
        self.assertEqual(called.call_count, 2)


def _option(credential_id: str = "22222222-2222-2222-2222-222222222222") -> RouterOption:
    return RouterOption(
        id="opt_1",
        label="Fast",
        credential_id=credential_id,
        model="gpt-4o-mini",
        criteria="",
    )


class TestLoadOptionCredential(unittest.TestCase):
    def _session(self, credential: object) -> mock.MagicMock:
        session = mock.MagicMock()
        session.__enter__.return_value.get.return_value = credential
        return session

    def _credential(self, cred_type: object, name: str = "OpenAI prod") -> mock.Mock:
        credential = mock.Mock()
        credential.type = cred_type
        credential.name = name
        credential.encrypted_config = "encrypted"
        return credential

    def test_returns_type_key_and_base_url(self) -> None:
        from app.db.models import CredentialType

        with (
            mock.patch.object(
                model_router,
                "SessionLocal",
                return_value=self._session(self._credential(CredentialType.openai)),
            ),
            mock.patch.object(
                model_router, "decrypt_config", return_value={"api_key": "sk-x", "base_url": None}
            ),
        ):
            bound = load_option_credential(_option())

        self.assertIsInstance(bound, BoundOption)
        self.assertEqual(bound.credential_type, "openai")
        self.assertEqual(bound.api_key, "sk-x")
        self.assertIsNone(bound.base_url)
        self.assertEqual(bound.credential_name, "OpenAI prod")

    def test_missing_credential_is_reported_with_the_option_name(self) -> None:
        with mock.patch.object(model_router, "SessionLocal", return_value=self._session(None)):
            with self.assertRaises(ModelRouterError) as ctx:
                load_option_credential(_option())
        self.assertIn("Fast", str(ctx.exception))

    def test_a_router_option_pointing_at_another_router_is_refused(self) -> None:
        from app.db.models import CredentialType

        credential = self._credential(CredentialType.model_router, name="Other router")
        with (
            mock.patch.object(model_router, "SessionLocal", return_value=self._session(credential)),
            mock.patch.object(model_router, "decrypt_config", return_value={}),
        ):
            with self.assertRaises(ModelRouterError) as ctx:
                load_option_credential(_option())
        self.assertIn("another Model Router", str(ctx.exception))

    def test_a_non_llm_credential_is_refused(self) -> None:
        from app.db.models import CredentialType

        credential = self._credential(CredentialType.slack, name="Slack")
        with (
            mock.patch.object(model_router, "SessionLocal", return_value=self._session(credential)),
            mock.patch.object(model_router, "decrypt_config", return_value={"api_key": "x"}),
        ):
            with self.assertRaises(ModelRouterError) as ctx:
                load_option_credential(_option())
        self.assertIn("cannot serve model requests", str(ctx.exception))

    def test_a_credential_with_no_key_is_refused(self) -> None:
        from app.db.models import CredentialType

        credential = self._credential(CredentialType.openai)
        with (
            mock.patch.object(model_router, "SessionLocal", return_value=self._session(credential)),
            mock.patch.object(model_router, "decrypt_config", return_value={"api_key": ""}),
        ):
            with self.assertRaises(ModelRouterError) as ctx:
                load_option_credential(_option())
        self.assertIn("no API key", str(ctx.exception))

    def test_a_bad_uuid_is_reported(self) -> None:
        with self.assertRaises(ModelRouterError):
            load_option_credential(_option(credential_id="not-a-uuid"))


class TestBuildRouterForCredential(unittest.TestCase):
    def test_returns_none_for_a_plain_llm_credential(self) -> None:
        self.assertIsNone(
            build_router_for_credential(
                credential_id="x",
                credential_name="OpenAI prod",
                credential_type="openai",
                config={"api_key": "sk"},
            )
        )

    def test_builds_a_router_labelled_with_the_credential_name(self) -> None:
        router = build_router_for_credential(
            credential_id="99999999-9999-9999-9999-999999999999",
            credential_name="Auto Model",
            credential_type="model_router",
            config=_valid_config(),
        )
        self.assertIsInstance(router, ModelRouter)
        self.assertEqual(router.label, "Auto Model")
        self.assertEqual(len(router.config.options), 2)

    def test_a_broken_config_raises_a_router_error(self) -> None:
        raw = _valid_config()
        raw["options"] = []
        with self.assertRaises(ModelRouterConfigError):
            build_router_for_credential(
                credential_id="99999999-9999-9999-9999-999999999999",
                credential_name="Auto Model",
                credential_type="model_router",
                config=raw,
            )


if __name__ == "__main__":
    unittest.main()
