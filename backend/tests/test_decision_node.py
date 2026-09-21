"""Decision node handler: expression resolution, credential loading, output."""

import unittest
import unittest.mock as mock
import uuid

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import decision_node


class _FakeExecutor:
    """Minimal stand-in for WorkflowExecutor's expression and trace surface."""

    def __init__(self, trace_context=None) -> None:
        self._trace_context = trace_context

    def _visible_inputs(self, inputs: dict) -> dict:
        return inputs

    def _is_single_dollar_expression(self, template: str) -> bool:
        stripped = str(template).strip()
        return stripped.startswith("$") and " " not in stripped

    def resolve_expression(self, template, inputs, node_id, preserve_type=False):
        return {"ticket": "structured"} if preserve_type else "resolved"

    def _resolve_template(self, template, inputs, node_id):
        return str(template).replace("$input.text", "payouts failing")

    def _build_llm_trace_context(self, credential_id, node_id):
        return self._trace_context


def _base_node(**overrides) -> dict:
    node_data = {
        "label": "decision",
        "credentialId": str(uuid.uuid4()),
        "model": "jev-latest",
        "state": "$input.text",
        "questions": [{"id": "q", "type": "noul", "instructions": "Urgent?"}],
        "customBodyEnabled": False,
        "customBody": "",
        "requestTimeoutSeconds": 60,
    }
    node_data.update(overrides)
    return node_data


def _ctx(node_data: dict, trace_context=None) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=_FakeExecutor(trace_context),
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1", "type": "decision", "data": node_data},
        node_type="decision",
        node_data=node_data,
        node_label="decision",
    )


_CREDENTIAL = {"base_url": "https://api.typesafe.ai", "api_key": "sk-test"}


class DecisionNodeTests(unittest.TestCase):
    def _run(self, node_data: dict, response: dict | None = None):
        response = response or {"answers": {"q": {"type": "noul", "noul": 0.9}}}
        with (
            mock.patch.object(decision_node, "load_decision_credential", return_value=_CREDENTIAL),
            mock.patch.object(decision_node, "call_decision_model", return_value=response) as call,
        ):
            self.call = call
            return decision_node.execute(_ctx(node_data))

    def test_response_is_passed_through_untouched(self) -> None:
        payload = {
            "model": "jev-1.13.0",
            "answers": {"department": {"type": "choice", "choice": "billing"}},
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }
        self.assertEqual(self._run(_base_node(), payload), payload)

    def test_a_template_state_is_resolved_as_text(self) -> None:
        self._run(_base_node(state="Ticket: $input.text"))
        self.assertEqual(self.call.call_args.kwargs["body"]["state"], "Ticket: payouts failing")

    def test_a_single_expression_state_preserves_its_type(self) -> None:
        self._run(_base_node(state="$input"))
        self.assertEqual(self.call.call_args.kwargs["body"]["state"], {"ticket": "structured"})

    def test_a_literal_state_is_left_alone(self) -> None:
        self._run(_base_node(state="A plain sentence."))
        self.assertEqual(self.call.call_args.kwargs["body"]["state"], "A plain sentence.")

    def test_instructions_and_criteria_are_resolved(self) -> None:
        self._run(
            _base_node(
                questions=[
                    {
                        "id": "q",
                        "type": "noul",
                        "instructions": "About $input.text?",
                        "criteriaTrue": "Yes for $input.text",
                        "criteriaFalse": "No",
                    }
                ]
            )
        )
        question = self.call.call_args.kwargs["body"]["questions"]["q"]
        self.assertEqual(question["instructions"], "About payouts failing?")
        self.assertEqual(question["criteria"]["true"], "Yes for payouts failing")

    def test_choice_option_descriptions_are_resolved(self) -> None:
        self._run(
            _base_node(
                questions=[
                    {
                        "id": "d",
                        "type": "choice",
                        "instructions": "Which?",
                        "options": [
                            {"key": "a", "description": "About $input.text"},
                            {"key": "b", "description": "Other"},
                        ],
                    }
                ]
            )
        )
        criteria = self.call.call_args.kwargs["body"]["questions"]["d"]["criteria"]
        self.assertEqual(criteria["a"], "About payouts failing")

    def test_score_levels_are_resolved(self) -> None:
        self._run(
            _base_node(
                questions=[
                    {
                        "id": "s",
                        "type": "score",
                        "instructions": "How bad?",
                        "levels": ["Fine", "About $input.text"],
                    }
                ]
            )
        )
        criteria = self.call.call_args.kwargs["body"]["questions"]["s"]["criteria"]
        self.assertEqual(criteria[1], "About payouts failing")

    def test_custom_body_replaces_the_form(self) -> None:
        self._run(
            _base_node(
                customBodyEnabled=True,
                customBody='{"model": "other-1", "state": "$input.text", "questions": {}}',
            )
        )
        body = self.call.call_args.kwargs["body"]
        self.assertEqual(body["model"], "other-1")
        self.assertEqual(body["state"], "payouts failing")

    def test_malformed_custom_body_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(_base_node(customBodyEnabled=True, customBody="{not json"))
        self.assertIn("JSON", str(ctx.exception))

    def test_empty_custom_body_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(_base_node(customBodyEnabled=True, customBody="   "))
        self.assertIn("empty", str(ctx.exception).lower())

    def test_a_custom_body_that_is_not_an_object_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(_base_node(customBodyEnabled=True, customBody="[1, 2]"))
        self.assertIn("JSON object", str(ctx.exception))

    def test_missing_credential_id_raises(self) -> None:
        node_data = _base_node()
        node_data["credentialId"] = ""
        with self.assertRaises(ValueError) as ctx:
            decision_node.execute(_ctx(node_data))
        self.assertIn("credential", str(ctx.exception).lower())

    def test_a_build_error_surfaces_as_a_node_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._run(_base_node(questions=[]))
        self.assertIn("question", str(ctx.exception).lower())

    def test_a_provider_error_surfaces_as_a_node_error(self) -> None:
        from app.services.decision_models import DecisionProviderError

        with (
            mock.patch.object(decision_node, "load_decision_credential", return_value=_CREDENTIAL),
            mock.patch.object(
                decision_node,
                "call_decision_model",
                side_effect=DecisionProviderError("Decision model is rate limited (429)"),
            ),
        ):
            with self.assertRaises(ValueError) as ctx:
                decision_node.execute(_ctx(_base_node()))
        self.assertIn("rate limited", str(ctx.exception))

    def test_timeout_is_taken_from_node_data(self) -> None:
        self._run(_base_node(requestTimeoutSeconds=12))
        self.assertEqual(self.call.call_args.kwargs["timeout"], 12.0)

    def test_the_credential_supplies_the_base_url_and_key(self) -> None:
        self._run(_base_node())
        kwargs = self.call.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "https://api.typesafe.ai")
        self.assertEqual(kwargs["api_key"], "sk-test")


class DecisionNodeTraceLinkTests(unittest.TestCase):
    """The execution log links to Traces through `_trace_id` on the node output."""

    def _context(self):
        from app.services.llm_trace import LLMTraceContext

        return LLMTraceContext(user_id=uuid.uuid4(), credential_id=uuid.uuid4())

    def test_a_recorded_trace_id_reaches_the_node_output(self) -> None:
        context = self._context()
        trace_id = uuid.uuid4()

        def _record(**kwargs):
            context.trace_ids.append(trace_id)
            return {"answers": {}}

        with (
            mock.patch.object(decision_node, "load_decision_credential", return_value=_CREDENTIAL),
            mock.patch.object(decision_node, "call_decision_model", side_effect=_record),
        ):
            output = decision_node.execute(_ctx(_base_node(), context))
        self.assertEqual(output["_trace_id"], str(trace_id))

    def test_no_trace_context_means_no_trace_key(self) -> None:
        with (
            mock.patch.object(decision_node, "load_decision_credential", return_value=_CREDENTIAL),
            mock.patch.object(decision_node, "call_decision_model", return_value={"answers": {}}),
        ):
            output = decision_node.execute(_ctx(_base_node(), None))
        self.assertNotIn("_trace_id", output)

    def test_a_failed_call_still_carries_its_trace_id(self) -> None:
        from app.services.decision_models import DecisionProviderError
        from app.services.workflow_executor import NodeTraceableExecutionError

        context = self._context()
        trace_id = uuid.uuid4()

        def _record(**kwargs):
            context.trace_ids.append(trace_id)
            raise DecisionProviderError("Decision model rejected the API key")

        with (
            mock.patch.object(decision_node, "load_decision_credential", return_value=_CREDENTIAL),
            mock.patch.object(decision_node, "call_decision_model", side_effect=_record),
        ):
            with self.assertRaises(NodeTraceableExecutionError) as ctx:
                decision_node.execute(_ctx(_base_node(), context))
        self.assertEqual(ctx.exception.trace_id, str(trace_id))

    def test_the_provider_payload_is_not_mutated(self) -> None:
        context = self._context()
        payload = {"answers": {"q": {"type": "noul", "noul": 0.9}}}

        def _record(**kwargs):
            context.trace_ids.append(uuid.uuid4())
            return payload

        with (
            mock.patch.object(decision_node, "load_decision_credential", return_value=_CREDENTIAL),
            mock.patch.object(decision_node, "call_decision_model", side_effect=_record),
        ):
            decision_node.execute(_ctx(_base_node(), context))
        self.assertNotIn("_trace_id", payload)


class DecisionNodeRegistrationTests(unittest.TestCase):
    def test_the_handler_is_registered(self) -> None:
        from app.services.node_execution.registry import get_node_handler

        self.assertIsNotNone(get_node_handler("decision"))


if __name__ == "__main__":
    unittest.main()
