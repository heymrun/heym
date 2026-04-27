import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services.expression_evaluator import (
    ExpressionEvaluateResponse,
    ExpressionEvaluatorService,
    ExpressionTooLongError,
    build_eval_context,
    build_vars_context,
    classify_type,
    coerce_unprefixed_node_path_expression,
    is_single_dollar_expression,
    should_evaluate_as_multi_ref_condition,
    should_evaluate_as_multi_span_comparison_condition,
    should_evaluate_as_single_span_condition_tail,
    should_resolve_embedded_dollar_refs_arithmetically,
)
from app.services.workflow_executor import (
    WorkflowExecutor,
    _normalize_js_logical_ops_for_eval,
)


class TestShouldEvaluateAsMultiRefCondition(unittest.TestCase):
    def _executor(self) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[])

    def test_true_for_two_ref_inequality(self) -> None:
        ex = self._executor()
        expr = "$scrapeWebsite.href!=$getRedisValue.value"
        self.assertTrue(should_evaluate_as_multi_ref_condition(expr, ex))

    def test_true_for_compound_with_trailing_literal(self) -> None:
        ex = self._executor()
        expr = "$a.ok == true and $b.ok == true"
        self.assertTrue(should_evaluate_as_multi_ref_condition(expr, ex))

    def test_false_when_single_dollar_expression(self) -> None:
        ex = self._executor()
        self.assertFalse(should_evaluate_as_multi_ref_condition("$data.count + 1", ex))

    def test_false_without_comparison_operator(self) -> None:
        ex = self._executor()
        self.assertFalse(should_evaluate_as_multi_ref_condition("$a.x $b.y", ex))

    def test_false_for_text_template_prefix(self) -> None:
        ex = self._executor()
        self.assertFalse(
            should_evaluate_as_multi_ref_condition("x $a.href!=$b.value", ex),
        )

    def test_true_for_js_double_ampersand_between_refs(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_evaluate_as_multi_ref_condition("$a.x == 1 && $b.y == 2", ex),
        )

    def test_true_for_js_double_pipe_between_refs(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_evaluate_as_multi_ref_condition("$a.x == 0 || $b.y == 0", ex),
        )


class TestCoerceUnprefixedNodePathExpression(unittest.TestCase):
    def test_prefixes_bare_dot_path(self) -> None:
        self.assertEqual(
            coerce_unprefixed_node_path_expression("execute.outputs.output.result.today"),
            "$execute.outputs.output.result.today",
        )

    def test_unchanged_when_already_dollar(self) -> None:
        self.assertEqual(
            coerce_unprefixed_node_path_expression("$execute.outputs"),
            "$execute.outputs",
        )

    def test_unchanged_single_identifier(self) -> None:
        self.assertEqual(coerce_unprefixed_node_path_expression("execute"), "execute")

    def test_unchanged_with_spaces(self) -> None:
        self.assertEqual(
            coerce_unprefixed_node_path_expression("execute .out"),
            "execute .out",
        )

    def test_empty(self) -> None:
        self.assertEqual(coerce_unprefixed_node_path_expression(""), "")


class TestShouldResolveEmbeddedDollarRefsArithmetically(unittest.TestCase):
    def _executor(self) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[])

    def test_true_for_int_wrapped_ref(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_resolve_embedded_dollar_refs_arithmetically("int($userInput.body.text)", ex),
        )

    def test_true_for_subscripted_ref(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_resolve_embedded_dollar_refs_arithmetically("items[$idx]", ex),
        )

    def test_false_for_leading_dollar_and_natural_language_glue(self) -> None:
        ex = self._executor()
        self.assertFalse(
            should_resolve_embedded_dollar_refs_arithmetically("$a.x and $b.y", ex),
        )

    def test_true_for_numeric_prefix_expression(self) -> None:
        ex = self._executor()
        self.assertTrue(should_resolve_embedded_dollar_refs_arithmetically("1 + $n", ex))

    def test_true_for_multi_ref_subtraction(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_resolve_embedded_dollar_refs_arithmetically(
                "$generateUuid.uuid.length - $generateUuid.uuid.replace('1', '').length",
                ex,
            ),
        )

    def test_false_for_multi_ref_comparison(self) -> None:
        ex = self._executor()
        self.assertFalse(
            should_resolve_embedded_dollar_refs_arithmetically("$a.score > $b.score", ex),
        )


class TestShouldEvaluateAsSingleSpanConditionTail(unittest.TestCase):
    def _executor(self) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[])

    def test_true_for_get_with_nested_dollar_and_null_check(self) -> None:
        ex = self._executor()
        expr = "$execute.outputs.output.result.birthdays.get($execute.outputs.output.result.today) != null"
        self.assertTrue(should_evaluate_as_single_span_condition_tail(expr, ex))

    def test_false_when_two_top_level_spans(self) -> None:
        ex = self._executor()
        self.assertFalse(
            should_evaluate_as_single_span_condition_tail("$a.x != $b.y", ex),
        )

    def test_false_when_single_dollar_expression_covers_all(self) -> None:
        ex = self._executor()
        self.assertFalse(should_evaluate_as_single_span_condition_tail("$execute.x != null", ex))

    def test_true_for_arithmetic_subtraction_after_global_ref(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_evaluate_as_single_span_condition_tail("$global.btcBalance - 10", ex),
        )

    def test_true_for_arithmetic_multiplication_after_global_ref(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_evaluate_as_single_span_condition_tail("$global.btcBalance * 3", ex),
        )


class TestShouldEvaluateAsMultiSpanComparisonCondition(unittest.TestCase):
    def _executor(self) -> WorkflowExecutor:
        return WorkflowExecutor(nodes=[], edges=[])

    def test_true_for_repeated_ref_with_string_literal_or(self) -> None:
        ex = self._executor()
        self.assertTrue(
            should_evaluate_as_multi_span_comparison_condition(
                '$tradingAgent.action == "buy" || $tradingAgent.action == "sell"',
                ex,
            )
        )

    def test_false_for_natural_language_two_ref_template(self) -> None:
        ex = self._executor()
        self.assertFalse(
            should_evaluate_as_multi_span_comparison_condition(
                "$a.x and $b.y",
                ex,
            )
        )


class TestIsSingleDollarExpression(unittest.TestCase):
    def test_plain_dollar_ref(self) -> None:
        self.assertTrue(is_single_dollar_expression("$input.text"))

    def test_dollar_ref_with_method(self) -> None:
        self.assertTrue(is_single_dollar_expression("$llm.text.upper()"))

    def test_dollar_ref_with_bracket(self) -> None:
        self.assertTrue(is_single_dollar_expression("$node.headers['x-api-key']"))

    def test_template_with_prefix_text(self) -> None:
        self.assertFalse(is_single_dollar_expression("Hello $input.name"))

    def test_template_with_suffix_text(self) -> None:
        self.assertFalse(is_single_dollar_expression("$input.name suffix"))

    def test_template_with_two_refs(self) -> None:
        self.assertFalse(is_single_dollar_expression("$a.x and $b.y"))

    def test_literal_no_dollar(self) -> None:
        self.assertFalse(is_single_dollar_expression("just text"))

    def test_empty_string(self) -> None:
        self.assertFalse(is_single_dollar_expression(""))

    def test_currency_style_value(self) -> None:
        self.assertFalse(is_single_dollar_expression("$100"))

    def test_arithmetic_is_single(self) -> None:
        self.assertTrue(is_single_dollar_expression("$input.count + 1"))

    def test_ternary_is_single(self) -> None:
        self.assertTrue(is_single_dollar_expression("$x > 0 ? 'pos' : 'neg'"))


class TestClassifyType(unittest.TestCase):
    def test_string(self) -> None:
        self.assertEqual(classify_type("hello"), "string")

    def test_integer(self) -> None:
        self.assertEqual(classify_type(42), "number")

    def test_float(self) -> None:
        self.assertEqual(classify_type(3.14), "number")

    def test_boolean_true(self) -> None:
        self.assertEqual(classify_type(True), "boolean")

    def test_boolean_false(self) -> None:
        self.assertEqual(classify_type(False), "boolean")

    def test_list(self) -> None:
        self.assertEqual(classify_type([1, 2, 3]), "array")

    def test_dict(self) -> None:
        self.assertEqual(classify_type({"a": 1}), "object")

    def test_none(self) -> None:
        self.assertEqual(classify_type(None), "null")


class TestBuildEvalContext(unittest.TestCase):
    def _node(
        self, node_id: str, label: str, *, node_type: str = "llm", pinned: object = None
    ) -> dict:
        return {
            "id": node_id,
            "type": node_type,
            "data": {"label": label, "pinnedData": pinned},
        }

    def test_pinned_data_injected(self) -> None:
        nodes = [self._node("n1", "myLlm", pinned={"text": "hello"})]
        result = build_eval_context(nodes, [])
        self.assertEqual(result["myLlm"]["text"], "hello")

    def test_canvas_output_fills_when_no_pinned(self) -> None:
        nodes = [self._node("n1", "myLlm")]
        canvas = [{"label": "myLlm", "output": {"text": "world"}}]
        result = build_eval_context(nodes, canvas)
        self.assertEqual(result["myLlm"]["text"], "world")

    def test_pinned_wins_over_canvas(self) -> None:
        nodes = [self._node("n1", "myLlm", pinned={"text": "pinned"})]
        canvas = [{"label": "myLlm", "output": {"text": "canvas"}}]
        result = build_eval_context(nodes, canvas)
        self.assertEqual(result["myLlm"]["text"], "pinned")

    def test_missing_node_not_in_context(self) -> None:
        nodes = [self._node("n1", "myLlm")]
        result = build_eval_context(nodes, [])
        self.assertNotIn("myLlm", result)

    def test_text_input_uses_initial_inputs_without_run(self) -> None:
        nodes = [self._node("input-1", "input", node_type="textInput")]
        result = build_eval_context(
            nodes,
            [],
            initial_inputs={"body": {"items": ["a", "b"]}, "text": "hello"},
        )
        self.assertEqual(result["input"]["items"], ["a", "b"])
        self.assertEqual(result["input"]["text"], "hello")

    def test_upstream_filtering_ignores_unrelated_nodes(self) -> None:
        nodes = [
            self._node("in1", "userInput", pinned={"text": "hello"}),
            self._node("set1", "transform"),
            self._node("other1", "otherNode", pinned={"text": "ignored"}),
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "set1"},
        ]
        result = build_eval_context(
            nodes,
            [],
            workflow_edges=edges,
            current_node_id="set1",
        )
        self.assertIn("userInput", result)
        self.assertNotIn("otherNode", result)

    def test_loop_body_gets_preview_item_not_null_when_canvas_has_done_branch(
        self,
    ) -> None:
        """Canvas stores the loop's last output (often ``done`` without ``item``); preview still resolves ``$loop.item``."""
        nodes = [
            {
                "id": "n_set",
                "type": "set",
                "data": {
                    "label": "set",
                    "pinnedData": {"texts": ["hello", "world"]},
                },
            },
            {
                "id": "n_loop",
                "type": "loop",
                "data": {"label": "loop", "arrayExpression": "$set.texts"},
            },
            {
                "id": "n_body",
                "type": "set",
                "data": {"label": "set1"},
            },
        ]
        edges = [
            {
                "id": "e1",
                "source": "n_set",
                "target": "n_loop",
                "sourceHandle": "output",
                "targetHandle": "input",
            },
            {
                "id": "e2",
                "source": "n_loop",
                "target": "n_body",
                "sourceHandle": "loop",
                "targetHandle": "input",
            },
            {
                "id": "e3",
                "source": "n_body",
                "target": "n_loop",
                "sourceHandle": "output",
                "targetHandle": "loop",
            },
        ]
        canvas = [
            {
                "node_id": "n_loop",
                "label": "loop",
                "output": {"branch": "done", "total": 2, "results": []},
            }
        ]
        result = build_eval_context(
            nodes,
            canvas,
            workflow_edges=edges,
            current_node_id="n_body",
        )
        self.assertEqual(result["loop"]["item"], "hello")
        self.assertEqual(result["loop"]["index"], 0)
        self.assertEqual(result["loop"]["total"], 2)
        self.assertTrue(result["loop"]["isFirst"])
        self.assertFalse(result["loop"]["isLast"])

    def test_nested_loop_preview_outer_before_inner(self) -> None:
        """Inner loop ``arrayExpression`` may reference ``$outer.item``; outer preview must exist first."""
        nodes = [
            {
                "id": "n_root",
                "type": "set",
                "data": {"label": "root", "pinnedData": {"rows": [[1, 2], [3]]}},
            },
            {
                "id": "n_outer",
                "type": "loop",
                "data": {"label": "outer", "arrayExpression": "$root.rows"},
            },
            {
                "id": "n_inner",
                "type": "loop",
                "data": {"label": "inner", "arrayExpression": "$outer.item"},
            },
            {
                "id": "n_leaf",
                "type": "set",
                "data": {"label": "leaf"},
            },
        ]
        edges = [
            {
                "id": "e0",
                "source": "n_root",
                "target": "n_outer",
                "sourceHandle": "output",
                "targetHandle": "input",
            },
            {
                "id": "e1",
                "source": "n_outer",
                "target": "n_inner",
                "sourceHandle": "loop",
                "targetHandle": "input",
            },
            {
                "id": "e2",
                "source": "n_inner",
                "target": "n_leaf",
                "sourceHandle": "loop",
                "targetHandle": "input",
            },
            {
                "id": "e3",
                "source": "n_leaf",
                "target": "n_inner",
                "sourceHandle": "output",
                "targetHandle": "loop",
            },
            {
                "id": "e4",
                "source": "n_inner",
                "target": "n_outer",
                "sourceHandle": "output",
                "targetHandle": "loop",
            },
        ]
        canvas = [
            {
                "node_id": "n_outer",
                "label": "outer",
                "output": {"branch": "done", "total": 2, "results": []},
            },
            {
                "node_id": "n_inner",
                "label": "inner",
                "output": {"branch": "done", "total": 0, "results": []},
            },
        ]
        ctx = build_eval_context(
            nodes,
            canvas,
            workflow_edges=edges,
            current_node_id="n_leaf",
        )
        self.assertEqual(ctx["inner"]["item"], 1)
        self.assertEqual(ctx["inner"]["index"], 0)

    def test_loop_preview_can_select_non_first_iteration_without_run(self) -> None:
        nodes = [
            {
                "id": "n_input",
                "type": "textInput",
                "data": {"label": "input", "pinnedData": None},
            },
            {
                "id": "n_loop",
                "type": "loop",
                "data": {"label": "loop", "arrayExpression": "$input.items"},
            },
            {
                "id": "n_body_source",
                "type": "set",
                "data": {"label": "bodySource"},
            },
            {
                "id": "n_body_target",
                "type": "set",
                "data": {"label": "bodyTarget"},
            },
        ]
        edges = [
            {
                "id": "e1",
                "source": "n_input",
                "target": "n_loop",
                "sourceHandle": "output",
                "targetHandle": "input",
            },
            {
                "id": "e2",
                "source": "n_loop",
                "target": "n_body_source",
                "sourceHandle": "loop",
                "targetHandle": "input",
            },
            {
                "id": "e3",
                "source": "n_body_source",
                "target": "n_body_target",
                "sourceHandle": "output",
                "targetHandle": "input",
            },
            {
                "id": "e4",
                "source": "n_body_target",
                "target": "n_loop",
                "sourceHandle": "output",
                "targetHandle": "loop",
            },
        ]
        canvas = [
            {
                "node_id": "n_loop",
                "label": "loop",
                "output": {"branch": "loop", "index": 0, "total": 2, "item": "first"},
            },
            {
                "node_id": "n_body_source",
                "label": "bodySource",
                "output": {"text": "first-result"},
            },
            {
                "node_id": "n_loop",
                "label": "loop",
                "output": {"branch": "loop", "index": 1, "total": 2, "item": "second"},
            },
            {
                "node_id": "n_body_source",
                "label": "bodySource",
                "output": {"text": "second-result"},
            },
            {
                "node_id": "n_loop",
                "label": "loop",
                "output": {"branch": "done", "total": 2, "results": []},
            },
        ]
        ctx = build_eval_context(
            nodes,
            canvas,
            workflow_edges=edges,
            current_node_id="n_body_target",
            initial_inputs={"body": {"items": ["first", "second"]}},
            selected_loop_iteration_index=1,
        )
        self.assertEqual(ctx["loop"]["item"], "second")
        self.assertEqual(ctx["loop"]["index"], 1)
        self.assertEqual(ctx["loop"]["total"], 2)
        self.assertEqual(ctx["bodySource"]["text"], "second-result")

    def test_loop_body_set_preview_is_synthesized_for_dependent_child_without_run(self) -> None:
        nodes = [
            {
                "id": "n_llm",
                "type": "set",
                "data": {
                    "label": "llm",
                    "pinnedData": {
                        "results": [
                            {"text": "Hello"},
                            {"text": "World"},
                        ]
                    },
                },
            },
            {
                "id": "n_loop",
                "type": "loop",
                "data": {"label": "loop", "arrayExpression": "$llm.results"},
            },
            {
                "id": "n_set",
                "type": "set",
                "data": {
                    "label": "set",
                    "mappings": [{"key": "text", "value": "$loop.item.text"}],
                },
            },
            {
                "id": "n_log",
                "type": "consoleLog",
                "data": {"label": "consoleLog"},
            },
        ]
        edges = [
            {"id": "e1", "source": "n_llm", "target": "n_loop"},
            {"id": "e2", "source": "n_loop", "target": "n_set", "sourceHandle": "loop"},
            {"id": "e3", "source": "n_set", "target": "n_log"},
            {"id": "e4", "source": "n_log", "target": "n_loop", "targetHandle": "loop"},
        ]

        ctx = build_eval_context(
            nodes,
            [],
            workflow_edges=edges,
            current_node_id="n_log",
        )

        self.assertEqual(ctx["loop"]["item"], {"text": "Hello"})
        self.assertEqual(ctx["set"]["text"], "Hello")


class TestBuildVarsContext(unittest.TestCase):
    def test_uses_variable_value_field(self) -> None:
        nodes = [
            {
                "id": "var1",
                "type": "variable",
                "data": {
                    "label": "saveName",
                    "variableName": "savedName",
                    "pinnedData": {"value": "Ada"},
                },
            }
        ]
        self.assertEqual(build_vars_context(nodes, []), {"savedName": "Ada"})


class TestMultiRefArithmeticEvaluation(unittest.TestCase):
    """Regression tests for multi-$ref arithmetic expressions that should return numbers."""

    def _service(self) -> ExpressionEvaluatorService:
        return ExpressionEvaluatorService()

    def test_multi_ref_subtraction_returns_number_not_boolean(self) -> None:
        """$a.uuid.length - $a.uuid.replace('1','').length must be a number, not a boolean."""
        # "abc1def1gh" has 2 occurrences of '1', so 10 - 8 = 2.
        context = {"generateUuid": {"uuid": "abc1def1gh"}}
        result = self._service().evaluate(
            "$generateUuid.uuid.length - $generateUuid.uuid.replace('1', '').length",
            context,
        )
        self.assertIsNone(result.error)
        self.assertEqual(result.result_type, "number")
        self.assertEqual(result.result, 2)
        self.assertTrue(result.preserved_type)

    def test_multi_ref_subtraction_zero_ones_returns_zero_not_false(self) -> None:
        """When the UUID has no '1' chars the result must be 0 (number), not False (boolean)."""
        context = {"generateUuid": {"uuid": "abc-def-gh"}}
        result = self._service().evaluate(
            "$generateUuid.uuid.length - $generateUuid.uuid.replace('1', '').length",
            context,
        )
        self.assertIsNone(result.error)
        self.assertEqual(result.result_type, "number")
        self.assertEqual(result.result, 0)

    def test_condition_expressions_still_return_boolean(self) -> None:
        """Changing multi-ref arithmetic must not break genuine boolean conditions."""
        context = {"a": {"x": 5}, "b": {"y": 3}}
        result_ne = self._service().evaluate("$a.x != $b.y", context)
        self.assertEqual(result_ne.result_type, "boolean")
        self.assertTrue(result_ne.result)

        result_gt = self._service().evaluate("$a.x > $b.y", context)
        self.assertEqual(result_gt.result_type, "boolean")
        self.assertTrue(result_gt.result)


class TestNormalizeJsLogicalOpsForEval(unittest.TestCase):
    def test_replaces_double_ampersand(self) -> None:
        self.assertEqual(_normalize_js_logical_ops_for_eval("1&&2"), "1 and 2")

    def test_replaces_double_pipe(self) -> None:
        self.assertEqual(_normalize_js_logical_ops_for_eval("0||1"), "0 or 1")

    def test_preserves_ampersand_inside_single_quoted_literal(self) -> None:
        self.assertEqual(
            _normalize_js_logical_ops_for_eval("'a&&b'&&True"),
            "'a&&b' and True",
        )

    def test_preserves_pipe_inside_double_quoted_literal(self) -> None:
        self.assertEqual(
            _normalize_js_logical_ops_for_eval('"x||y"||False'),
            '"x||y" or False',
        )

    def test_chained_operators(self) -> None:
        self.assertEqual(
            _normalize_js_logical_ops_for_eval("1&&2||0"),
            "1 and 2 or 0",
        )


class TestWorkflowExecutorConditionStrict(unittest.TestCase):
    def test_double_ampersand_after_substitution(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertTrue(
            ex.evaluate_condition_strict(
                "$a.x == 1 && $b.y < 14",
                {"a": {"x": 1}, "b": {"y": 3}},
            ),
        )

    def test_double_pipe_after_substitution(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertTrue(
            ex.evaluate_condition_strict(
                "$a.x == 0 || $b.y > 0",
                {"a": {"x": 0}, "b": {"y": 2}},
            ),
        )

    def test_double_ampersand_evaluates_false(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertFalse(
            ex.evaluate_condition_strict(
                "$a.x == 1 && $b.y == 0",
                {"a": {"x": 1}, "b": {"y": 5}},
            ),
        )

    def test_expression_tail_strict_arithmetic_subtraction(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertEqual(
            ex.evaluate_expression_tail_strict(
                "$a.n - 7",
                {"a": {"n": 17}},
            ),
            10,
        )

    def test_expression_tail_strict_modulo(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertEqual(
            ex.evaluate_expression_tail_strict(
                "$a.n % 5",
                {"a": {"n": 12}},
            ),
            2,
        )


class TestExpressionEvaluatorServiceEvaluate(unittest.TestCase):
    def _service(self, **kwargs) -> ExpressionEvaluatorService:
        return ExpressionEvaluatorService(**kwargs)

    def test_single_expr_string_result(self) -> None:
        response = self._service().evaluate("$user.name", {"user": {"name": "Ali"}})
        self.assertEqual(response.result, "Ali")
        self.assertEqual(response.result_type, "string")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_unprefixed_dot_path_resolves_like_dollar_prefixed(self) -> None:
        response = self._service().evaluate(
            "user.profile.name", {"user": {"profile": {"name": "Ada"}}}
        )
        self.assertEqual(response.result, "Ada")
        self.assertEqual(response.result_type, "string")
        self.assertTrue(response.preserved_type)

    def test_multiline_value_skips_bare_path_coercion(self) -> None:
        response = self._service().evaluate(
            "execute.outputs\nmore",
            {"execute": {"outputs": {"x": 1}}},
        )
        self.assertEqual(response.result, "execute.outputs\nmore")
        self.assertEqual(response.result_type, "string")
        self.assertFalse(response.preserved_type)

    def test_single_expr_array_preserved(self) -> None:
        response = self._service().evaluate("$data.items", {"data": {"items": [1, 2, 3]}})
        self.assertEqual(response.result, [1, 2, 3])
        self.assertEqual(response.result_type, "array")
        self.assertTrue(response.preserved_type)

    def test_single_expr_object_preserved(self) -> None:
        response = self._service().evaluate("$data.meta", {"data": {"meta": {"key": "val"}}})
        self.assertEqual(response.result, {"key": "val"})
        self.assertEqual(response.result_type, "object")

    def test_single_expr_boolean_preserved(self) -> None:
        response = self._service().evaluate("$data.active", {"data": {"active": True}})
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")

    def test_single_expr_number_preserved(self) -> None:
        response = self._service().evaluate("$data.count", {"data": {"count": 42}})
        self.assertEqual(response.result, 42)
        self.assertEqual(response.result_type, "number")

    def test_int_cast_of_string_node_field_returns_number(self) -> None:
        response = self._service().evaluate(
            "int($userInput.body.text)",
            {"userInput": {"body": {"text": "5"}}},
        )
        self.assertEqual(response.result, 5)
        self.assertEqual(response.result_type, "number")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_range_with_nested_int_cast_in_arguments(self) -> None:
        response = self._service().evaluate(
            "$range(1, int($userInput.body.text) + 1)",
            {"userInput": {"body": {"text": "5"}}},
        )
        self.assertEqual(response.result, [1, 2, 3, 4, 5])
        self.assertEqual(response.result_type, "array")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_range_map_filter_chain_arithmetic_path_matches_evaluator(self) -> None:
        """Set/output nodes use ``resolve_arithmetic_expression`` when ``_has_arithmetic`` is true."""
        expr = "$range(1, int($userInput.body.text) + 1).map('item * 3').filter('item % 2 == 0')"
        ctx = {"userInput": {"body": {"text": "5"}}}
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertTrue(
            ex._has_arithmetic(expr),
            "precondition: set node must choose resolve_arithmetic_expression for this template",
        )
        arith_result = ex.resolve_arithmetic_expression(expr, ctx, None, preserve_type=True)
        self.assertEqual(list(arith_result), [6, 12])

        response = self._service().evaluate(expr, ctx)
        self.assertEqual(list(response.result), [6, 12])
        self.assertEqual(response.result_type, "array")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_template_string_concatenation(self) -> None:
        response = self._service().evaluate("Hello $user.name", {"user": {"name": "John"}})
        self.assertEqual(response.result, "Hello John")
        self.assertEqual(response.result_type, "string")
        self.assertFalse(response.preserved_type)

    def test_template_two_refs(self) -> None:
        response = self._service().evaluate(
            "$a.x and $b.y",
            {"a": {"x": "foo"}, "b": {"y": "bar"}},
        )
        self.assertEqual(response.result, "foo and bar")

    def test_two_dollar_ref_inequality_evaluates_boolean(self) -> None:
        response = self._service().evaluate(
            "$scrapeWebsite.href!=$getRedisValue.value",
            {
                "scrapeWebsite": {"href": "/engineering/noise"},
                "getRedisValue": {"value": "/aengineering/noise"},
            },
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_two_dollar_ref_equality_evaluates_boolean_false(self) -> None:
        response = self._service().evaluate(
            "$scrapeWebsite.href==$getRedisValue.value",
            {
                "scrapeWebsite": {"href": "/same"},
                "getRedisValue": {"value": "/same"},
            },
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")

    def test_two_dollar_ref_method_chain_inequality(self) -> None:
        response = self._service().evaluate(
            "$scrapeWebsite.extracted.item.first().href!=$getRedisValue.value",
            {
                "scrapeWebsite": {"extracted": {"item": [{"href": "/p/one"}]}},
                "getRedisValue": {"value": "/p/two"},
            },
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")

    def test_two_dollar_ref_logical_and(self) -> None:
        response = self._service().evaluate(
            "$a.ok == true and $b.ok == true",
            {"a": {"ok": True}, "b": {"ok": True}},
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")

    def test_two_dollar_ref_logical_and_js_double_ampersand(self) -> None:
        response = self._service().evaluate(
            "$a.ok == true && $b.ok == true",
            {"a": {"ok": True}, "b": {"ok": True}},
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")
        self.assertIsNone(response.error)

    def test_two_dollar_ref_logical_or_js_double_pipe(self) -> None:
        response = self._service().evaluate(
            "$a.ok == false || $b.ok == true",
            {"a": {"ok": False}, "b": {"ok": False}},
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")
        self.assertIsNone(response.error)

    def test_repeated_ref_string_literal_or_evaluates_false_boolean(self) -> None:
        response = self._service().evaluate(
            '$tradingAgent.action == "buy" || $tradingAgent.action == "sell"',
            {"tradingAgent": {"action": "hold"}},
        )
        self.assertIs(response.result, False)
        self.assertEqual(response.result_type, "boolean")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_repeated_ref_string_literal_or_evaluates_true_boolean(self) -> None:
        response = self._service().evaluate(
            '$tradingAgent.action == "buy" || $tradingAgent.action == "sell"',
            {"tradingAgent": {"action": "buy"}},
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_single_span_numeric_subtraction_after_global_ref(self) -> None:
        service = self._service(global_variables_context={"btcBalance": 50})
        response = service.evaluate("$global.btcBalance - 50", {})
        self.assertEqual(response.result, 0)
        self.assertEqual(response.result_type, "number")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_single_span_multiplication_after_node_ref(self) -> None:
        response = self._service().evaluate(
            "$row.qty * 4",
            {"row": {"qty": 3}},
        )
        self.assertEqual(response.result, 12)
        self.assertEqual(response.result_type, "number")
        self.assertTrue(response.preserved_type)

    def test_single_span_division_after_node_ref(self) -> None:
        response = self._service().evaluate(
            "$row.total / 2",
            {"row": {"total": 9}},
        )
        self.assertEqual(response.result, 4.5)
        self.assertEqual(response.result_type, "number")

    def test_single_span_subtraction_comparison_yields_boolean(self) -> None:
        service = self._service(global_variables_context={"btcBalance": 50})
        response = service.evaluate("$global.btcBalance - 50 == 0", {})
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")

    def test_single_span_subtraction_comparison_yields_false(self) -> None:
        service = self._service(global_variables_context={"btcBalance": 49})
        response = service.evaluate("$global.btcBalance - 50 == 0", {})
        self.assertIs(response.result, False)
        self.assertEqual(response.result_type, "boolean")

    def test_two_dollar_double_ampersand_evaluates_false(self) -> None:
        response = self._service().evaluate(
            "$a.ok == true && $b.ok == true",
            {"a": {"ok": True}, "b": {"ok": False}},
        )
        self.assertIs(response.result, False)
        self.assertEqual(response.result_type, "boolean")

    def test_two_dollar_double_ampersand_three_clauses(self) -> None:
        response = self._service().evaluate(
            "$a.x > 0 && $b.y > 0 && $c.z == 3",
            {"a": {"x": 1}, "b": {"y": 2}, "c": {"z": 3}},
        )
        self.assertIs(response.result, True)

    def test_two_dollar_mixed_and_or_precedence(self) -> None:
        response = self._service().evaluate(
            "$a.x == 0 || $b.y == 2 && $c.z == 1",
            {"a": {"x": 0}, "b": {"y": 2}, "c": {"z": 9}},
        )
        self.assertIs(response.result, True)

    def test_nested_dollar_in_get_with_null_check_is_boolean(self) -> None:
        context = {
            "execute": {
                "outputs": {
                    "output": {
                        "result": {
                            "today": "Jan1",
                            "birthdays": {"Jan1": {"name": "Ada"}},
                        }
                    }
                }
            }
        }
        response = self._service().evaluate(
            "$execute.outputs.output.result.birthdays.get($execute.outputs.output.result.today) != null",
            context,
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_nested_dollar_in_get_missing_key_null_check_is_boolean(self) -> None:
        context = {
            "execute": {
                "outputs": {
                    "output": {
                        "result": {
                            "today": "Feb1",
                            "birthdays": {"Jan1": {"name": "Ada"}},
                        }
                    }
                }
            }
        }
        response = self._service().evaluate(
            "$execute.outputs.output.result.birthdays.get($execute.outputs.output.result.today) != null",
            context,
        )
        self.assertIs(response.result, False)
        self.assertEqual(response.result_type, "boolean")

    def test_arithmetic_expression(self) -> None:
        response = self._service().evaluate("$data.count + 1", {"data": {"count": 5}})
        self.assertEqual(response.result, 6)

    def test_ternary_expression(self) -> None:
        response = self._service().evaluate("$data.x > 0 ? 'pos' : 'neg'", {"data": {"x": 10}})
        self.assertEqual(response.result, "pos")

    def test_multiline_template_evaluates_standalone_expression_lines(self) -> None:
        response = self._service().evaluate(
            'gün\n\n$Date().day < 32 ? "yes" : "no"\n\n$fetchBtcPrice.status',
            {"fetchBtcPrice": {"status": 200}},
        )
        self.assertEqual(response.result, "gün\n\nyes\n\n200")
        self.assertEqual(response.result_type, "string")
        self.assertFalse(response.preserved_type)

    def test_string_method_upper(self) -> None:
        response = self._service().evaluate("$data.text.upper()", {"data": {"text": "hello"}})
        self.assertEqual(response.result, "HELLO")

    def test_date_number_chain_to_string(self) -> None:
        response = self._service().evaluate("$Date().year.toString()", {})
        self.assertEqual(response.result, str(datetime.now(timezone.utc).year))
        self.assertEqual(response.result_type, "string")
        self.assertTrue(response.preserved_type)

    def test_date_hour_uses_configured_timezone(self) -> None:
        berlin_tz = ZoneInfo("Europe/Berlin")
        fixed_now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=berlin_tz)

        with (
            patch(
                "app.services.workflow_executor.get_configured_timezone",
                return_value=berlin_tz,
            ),
            patch.object(WorkflowExecutor, "_current_datetime", return_value=fixed_now),
        ):
            response = self._service().evaluate("$Date().hour", {})

        self.assertEqual(response.result, 14)
        self.assertEqual(response.result_type, "number")
        self.assertTrue(response.preserved_type)

    def test_date_format_callable_uses_default_pattern(self) -> None:
        response = self._service().evaluate('$Date("2024-01-15T08:09:10+00:00").format', {})
        self.assertEqual(response.result, "2024-01-15 08:09:10")
        self.assertEqual(response.result_type, "string")
        self.assertTrue(response.preserved_type)

    def test_date_format_with_pattern_returns_string(self) -> None:
        response = self._service().evaluate(
            '$Date("2024-01-15T08:09:10+00:00").format("YYYY-MM-DD")',
            {},
        )
        self.assertEqual(response.result, "2024-01-15")
        self.assertEqual(response.result_type, "string")
        self.assertTrue(response.preserved_type)

    def test_nested_dollar_inside_method_parameter(self) -> None:
        response = self._service().evaluate(
            "$text.contains($other.value)",
            {"text": "hello", "other": {"value": "ell"}},
        )
        self.assertIs(response.result, True)
        self.assertEqual(response.result_type, "boolean")
        self.assertTrue(response.preserved_type)

    def test_array_function(self) -> None:
        response = self._service().evaluate("$array(1, 2, 3)", {})
        self.assertEqual(response.result, [1, 2, 3])

    def test_range_function(self) -> None:
        response = self._service().evaluate("$range(1, 5)", {})
        self.assertEqual(response.result, [1, 2, 3, 4])

    def test_vars_and_global_context(self) -> None:
        service = self._service(
            vars_context={"savedName": "Ada"},
            global_variables_context={"apiBase": "https://api.example.com"},
        )
        vars_response = service.evaluate("$vars.savedName", {})
        global_response = service.evaluate("$global.apiBase", {})
        self.assertEqual(vars_response.result, "Ada")
        self.assertEqual(global_response.result, "https://api.example.com")

    def test_add_object_with_items_key_to_array_variable(self) -> None:
        service = self._service(vars_context={"evaluationResults": []})
        response = service.evaluate(
            "$vars.evaluationResults.add(evaluateSite)",
            {
                "evaluateSite": {
                    "url": "https://heym.run/",
                    "items": [
                        {"question": "Q1", "score": -3},
                        {"question": "Q2", "score": 0},
                    ],
                }
            },
        )
        self.assertEqual(
            response.result,
            [
                {
                    "url": "https://heym.run/",
                    "items": [
                        {"question": "Q1", "score": -3},
                        {"question": "Q2", "score": 0},
                    ],
                }
            ],
        )
        self.assertEqual(response.result_type, "array")
        self.assertTrue(response.preserved_type)
        self.assertIsNone(response.error)

    def test_credentials_context(self) -> None:
        response = self._service(credentials_context={"MyToken": "Bearer abc"}).evaluate(
            "$credentials.MyToken",
            {},
        )
        self.assertEqual(response.result, "Bearer abc")

    def test_invalid_expression_returns_error_field(self) -> None:
        response = self._service().evaluate("$@@invalid@@", {})
        self.assertIsNone(response.result)
        self.assertEqual(response.result_type, "null")
        self.assertIsNotNone(response.error)

    def test_undefined_label_resolves_to_none(self) -> None:
        response = self._service().evaluate("$unknown.field", {})
        self.assertIsNone(response.result)
        self.assertEqual(response.result_type, "null")
        self.assertIsNone(response.error)

    def test_literal_no_dollar_returned_as_is(self) -> None:
        response = self._service().evaluate("just text", {})
        self.assertEqual(response.result, "just text")
        self.assertEqual(response.result_type, "string")

    def test_empty_expression_returns_empty_string(self) -> None:
        response = self._service().evaluate("", {})
        self.assertEqual(response.result, "")
        self.assertEqual(response.result_type, "string")

    def test_expression_over_length_limit_raises(self) -> None:
        with self.assertRaises(ExpressionTooLongError):
            self._service().evaluate("$" + ("x" * 10001), {})

    def test_response_model_type(self) -> None:
        response = self._service().evaluate("$array(1, 2)", {})
        self.assertIsInstance(response, ExpressionEvaluateResponse)


if __name__ == "__main__":
    unittest.main()
