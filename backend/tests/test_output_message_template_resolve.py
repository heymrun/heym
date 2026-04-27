"""Output / template resolution: multi-$ messages and bracket path fallback."""

import unittest
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services.expression_evaluator import (
    ExpressionEvaluatorService,
    is_single_dollar_expression,
)
from app.services.workflow_executor import (
    NodeResult,
    WorkflowExecutor,
    _parse_expression_tree,
    _workflow_gc_callback,
)


class IsSingleDollarExpressionTests(unittest.TestCase):
    def test_bracket_header_is_single_expression(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertTrue(ex._is_single_dollar_expression('$userInput.headers["user-agent"]'))

    def test_string_concat_expression_is_single_expression(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertTrue(
            ex._is_single_dollar_expression("$'## Record ' + str(processRecords.item.id)")
        )

    def test_currency_like_value_is_not_single_expression(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertFalse(ex._is_single_dollar_expression("$100"))

    def test_spaced_two_refs_is_not_single(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertFalse(
            ex._is_single_dollar_expression(
                '$translateAgent.model , $userInput.headers["user-agent"]'
            )
        )

    def test_text_with_embedded_ref_is_not_single(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        self.assertFalse(ex._is_single_dollar_expression("Hello $userInput.body.text"))


class ResolveSimpleExpressionBracketTests(unittest.TestCase):
    def test_headers_quoted_key_via_simple_resolver(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        combined = ex._build_context({})
        combined["u"] = ex._wrap_value({"headers": {"user-agent": "Mozilla/5.0"}})
        out = ex._resolve_simple_expression('u.headers["user-agent"]', combined)
        self.assertEqual(out, "Mozilla/5.0")


class WorkflowExecutorContextCacheTests(unittest.TestCase):
    def test_build_context_reuses_wrapped_vars_and_global_between_calls(self) -> None:
        ex = WorkflowExecutor(
            nodes=[],
            edges=[],
            global_variables_context={"workspace": "alpha"},
        )
        ex.vars["records"] = ex._wrap_value(["a", "b"])
        ex._mark_vars_context_dirty()

        first = ex._build_context({})
        second = ex._build_context({})

        self.assertIs(first["vars"], second["vars"])
        self.assertIs(first["global"], second["global"])
        self.assertEqual(second["global"]["workspace"], "alpha")
        self.assertEqual(second["global"]["records"], ["a", "b"])

    def test_build_context_refreshes_wrapped_vars_and_global_after_var_update(self) -> None:
        ex = WorkflowExecutor(
            nodes=[],
            edges=[],
            global_variables_context={"workspace": "alpha"},
        )
        ex.vars["records"] = ex._wrap_value(["a"])
        ex._mark_vars_context_dirty()

        first = ex._build_context({})

        ex.vars["records"] = ex._wrap_value(["a", "b"])
        ex._mark_vars_context_dirty()
        second = ex._build_context({})

        self.assertIsNot(first["vars"], second["vars"])
        self.assertIsNot(first["global"], second["global"])
        self.assertEqual(second["vars"]["records"], ["a", "b"])
        self.assertEqual(second["global"]["records"], ["a", "b"])

    def test_build_context_input_alias_is_not_self_referential(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])

        combined = ex._build_context({"userInput": {"body": {"id": 25}}})

        self.assertIsNot(combined["input"], combined)
        self.assertEqual(combined["input"]["body"]["id"], 25)
        self.assertEqual(combined["input"]["userInput"]["body"]["id"], 25)


class WorkflowExecutorVariableAppendOptimizationTests(unittest.TestCase):
    def test_self_append_reuses_existing_array_variable(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        existing = ex._wrap_value(["a"])
        ex.vars["records"] = existing
        ex._mark_vars_context_dirty()

        appended = ex._try_resolve_variable_self_append(
            "records",
            "$vars.records.add(node)",
            {"node": {"id": 2}},
        )

        self.assertIs(appended, existing)
        self.assertEqual(appended, ["a", {"id": 2}])

    def test_self_append_ignores_other_variables(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        ex.vars["records"] = ex._wrap_value(["a"])
        ex._mark_vars_context_dirty()

        appended = ex._try_resolve_variable_self_append(
            "records",
            "$vars.otherRecords.add(node)",
            {"node": {"id": 2}},
        )

        self.assertIsNone(appended)
        self.assertEqual(ex.vars["records"], ["a"])


class WorkflowExecutorExpressionParseCacheTests(unittest.TestCase):
    def test_resolve_expression_reuses_parsed_ast(self) -> None:
        _parse_expression_tree.cache_clear()
        ex = WorkflowExecutor(nodes=[], edges=[])
        expression = "$'## Record ' + str(userInput.body.id)"

        ex.resolve_expression(expression, {"userInput": {"body": {"id": 1}}})
        first_info = _parse_expression_tree.cache_info()

        ex.resolve_expression(expression, {"userInput": {"body": {"id": 2}}})
        second_info = _parse_expression_tree.cache_info()

        self.assertEqual(first_info.misses, 1)
        self.assertEqual(second_info.misses, 1)
        self.assertGreater(second_info.hits, first_info.hits)


class WorkflowExecutorGcPauseTrackingTests(unittest.TestCase):
    def test_execute_node_parallel_records_gc_pause_metadata(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])

        def fake_execute_node(
            node_id: str,
            inputs: dict,
            on_retry: object = None,
        ) -> NodeResult:
            self.assertEqual(node_id, "set1")
            self.assertEqual(inputs, {"value": 1})
            self.assertIsNone(on_retry)
            _workflow_gc_callback("start", {"generation": 2})
            _workflow_gc_callback("stop", {"generation": 2})
            return NodeResult(
                node_id="set1",
                node_label="createRecordMarkdown",
                node_type="set",
                status="success",
                output={"markdown": "ok"},
                execution_time_ms=100.0,
            )

        with (
            patch.object(executor, "execute_node", side_effect=fake_execute_node),
            patch(
                "app.services.workflow_executor.time.perf_counter",
                side_effect=[10.0, 10.01, 10.06],
            ),
        ):
            result = executor.execute_node_parallel("set1", {"value": 1})

        self.assertEqual(result.metadata["gc_pause_count"], 1)
        self.assertAlmostEqual(result.metadata["gc_pause_ms"], 50.0, places=3)
        self.assertEqual(
            result.metadata["gc_pause_intervals"],
            [
                {
                    "start_ms": 10.0,
                    "duration_ms": 50.0,
                    "generation": 2,
                }
            ],
        )

    def test_execute_node_parallel_omits_gc_metadata_when_no_pause_recorded(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])

        def fake_execute_node(
            node_id: str,
            inputs: dict,
            on_retry: object = None,
        ) -> NodeResult:
            self.assertEqual(node_id, "set1")
            self.assertEqual(inputs, {"value": 1})
            self.assertIsNone(on_retry)
            return NodeResult(
                node_id="set1",
                node_label="createRecordMarkdown",
                node_type="set",
                status="success",
                output={"markdown": "ok"},
                execution_time_ms=100.0,
            )

        with (
            patch.object(executor, "execute_node", side_effect=fake_execute_node),
            patch("app.services.workflow_executor.time.perf_counter", return_value=10.0),
        ):
            result = executor.execute_node_parallel("set1", {"value": 1})

        self.assertNotIn("gc_pause_ms", result.metadata)
        self.assertNotIn("gc_pause_count", result.metadata)
        self.assertNotIn("gc_pause_intervals", result.metadata)


class OutputMessageMultiRefExecutionTests(unittest.TestCase):
    def test_output_message_with_two_dollar_refs(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "text"}]},
            },
            {
                "id": "set1",
                "type": "set",
                "data": {
                    "label": "translateAgent",
                    "mappings": [
                        {"key": "model", "value": "zai-glm-4.7"},
                        {"key": "text", "value": "ok"},
                    ],
                },
            },
            {
                "id": "out1",
                "type": "output",
                "data": {
                    "label": "finalOut",
                    "message": '$translateAgent.model , $userInput.headers["user-agent"]',
                },
            },
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "set1"},
            {"id": "e2", "source": "set1", "target": "out1"},
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        initial = {
            "headers": {"user-agent": "UA-test"},
            "query": {},
            "body": {"text": "hi"},
        }
        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=initial)
        self.assertEqual(result.status, "success")
        out_nr = next(nr for nr in result.node_results if nr["node_type"] == "output")
        msg = out_nr["output"]["result"]
        self.assertIsInstance(msg, str)
        self.assertIn("zai-glm-4.7", msg)
        self.assertIn("UA-test", msg)

    def test_expression_mode_string_concat_runs_in_set_variable_and_output_nodes(self) -> None:
        nodes = [
            {
                "id": "in1",
                "type": "textInput",
                "data": {"label": "userInput", "inputFields": [{"key": "name"}, {"key": "id"}]},
            },
            {
                "id": "set1",
                "type": "set",
                "data": {
                    "label": "createRecordMarkdown",
                    "mappings": [
                        {
                            "key": "markdown",
                            "value": (
                                "$'## Record ' + str(userInput.body.id)"
                                " + '\\n\\n| Field | Value |\\n|-------|-------|\\n| Name | '"
                                " + str(userInput.body.name) + ' |'"
                            ),
                        }
                    ],
                },
            },
            {
                "id": "var1",
                "type": "variable",
                "data": {
                    "label": "saveMarkdown",
                    "variableName": "savedMarkdown",
                    "variableValue": "$'Saved:\\n' + createRecordMarkdown.markdown",
                    "variableType": "string",
                },
            },
            {
                "id": "out1",
                "type": "output",
                "data": {
                    "label": "finalOut",
                    "message": "$'Preview:\\n' + saveMarkdown.value",
                },
            },
        ]
        edges = [
            {"id": "e1", "source": "in1", "target": "set1"},
            {"id": "e2", "source": "set1", "target": "var1"},
            {"id": "e3", "source": "var1", "target": "out1"},
        ]
        executor = WorkflowExecutor(nodes=nodes, edges=edges)
        initial = {
            "headers": {},
            "query": {},
            "body": {"id": 3, "name": "Abdulhamit"},
        }

        result = executor.execute(workflow_id=uuid.uuid4(), initial_inputs=initial)

        self.assertEqual(result.status, "success")
        set_nr = next(
            nr for nr in result.node_results if nr["node_label"] == "createRecordMarkdown"
        )
        self.assertEqual(
            set_nr["output"]["markdown"],
            "## Record 3\n\n| Field | Value |\n|-------|-------|\n| Name | Abdulhamit |",
        )

        var_nr = next(nr for nr in result.node_results if nr["node_label"] == "saveMarkdown")
        self.assertEqual(
            var_nr["output"]["value"],
            "Saved:\n## Record 3\n\n| Field | Value |\n|-------|-------|\n| Name | Abdulhamit |",
        )

        out_nr = next(nr for nr in result.node_results if nr["node_type"] == "output")
        self.assertEqual(
            out_nr["output"]["result"],
            (
                "Preview:\nSaved:\n## Record 3\n\n| Field | Value |\n"
                "|-------|-------|\n| Name | Abdulhamit |"
            ),
        )

    def test_long_string_concat_expression_with_date_and_many_fields(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])

        result = ex.resolve_expression(
            (
                "$'## Record ' + str(processRecords.item.id)"
                " + '\\n\\n| Field | Value |\\n|-------|-------|'"
                " + '\\n| ID | ' + str(processRecords.item.id) + ' |'"
                " + '\\n| Created At | ' + str(Date(processRecords.item.fields.Created_at)) + ' |'"
                " + '\\n| Name | ' + str(processRecords.item.fields.Name) + ' |'"
                " + '\\n| Last Name | ' + str(processRecords.item.fields.Last_Name) + ' |'"
                " + '\\n| Email | ' + str(processRecords.item.fields.E_Mail_Address) + ' |'"
                " + '\\n| Address | ' + str(processRecords.item.fields.Address) + ' |'"
                " + '\\n| Phone | ' + str(processRecords.item.fields.Phone_Number) + ' |'"
                " + '\\n| Birth Date | ' + str(processRecords.item.fields.Birth_Date) + ' |'"
            ),
            {
                "processRecords": {
                    "item": {
                        "id": 25,
                        "fields": {
                            "Created_at": "2026-04-17T14:58:02.023929+02:00",
                            "Name": "Hassan",
                            "Last_Name": "Ali",
                            "E_Mail_Address": "hassan@example.com",
                            "Address": "Some Street 123",
                            "Phone_Number": "0159",
                            "Birth_Date": "1994-09-07",
                        },
                    }
                }
            },
            preserve_type=True,
        )

        self.assertIn("## Record 25", result)
        self.assertIn("| Created At | 2026-04-17T14:58:02.023929+02:00 |", result)
        self.assertIn("| Email | hassan@example.com |", result)


class TestExpressionEvaluatorServiceConsistency(unittest.TestCase):
    def test_single_expr_consistent_with_executor_branch(self) -> None:
        expr = "$node.items"
        self.assertTrue(is_single_dollar_expression(expr))
        response = ExpressionEvaluatorService().evaluate(expr, {"node": {"items": [1, 2]}})
        self.assertEqual(response.result, [1, 2])

    def test_template_consistent_with_executor_branch(self) -> None:
        expr = "prefix $node.text suffix"
        self.assertFalse(is_single_dollar_expression(expr))
        response = ExpressionEvaluatorService().evaluate(expr, {"node": {"text": "hello"}})
        self.assertEqual(response.result, "prefix hello suffix")


class WorkflowExecutorHeymExpressionEvalTests(unittest.TestCase):
    """Regression for executor eval: DotDateTime.format and DotDict keys vs dict methods."""

    def test_resolve_expression_date_format_uses_dotdatetime_not_blocked(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            '$Date("2024-06-01T15:30:00+00:00").format("YYYY-MM-DD")',
            {},
        )
        self.assertEqual(out, "2024-06-01")

    def test_resolve_expression_date_format_default_pattern(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression('$Date("2024-01-15T08:09:10+00:00").format()', {})
        self.assertEqual(out, "2024-01-15 08:09:10")

    def test_resolve_expression_date_hour_uses_configured_timezone(self) -> None:
        berlin_tz = ZoneInfo("Europe/Berlin")
        fixed_now = datetime(2024, 1, 15, 14, 30, 0, tzinfo=berlin_tz)

        with (
            patch("app.services.workflow_executor.get_configured_timezone", return_value=berlin_tz),
            patch.object(WorkflowExecutor, "_current_datetime", return_value=fixed_now),
        ):
            ex = WorkflowExecutor(nodes=[], edges=[])
            out = ex.resolve_expression("$Date().hour", {}, preserve_type=True)

        self.assertEqual(out, 14)

    def test_resolve_expression_node_items_json_key_not_dict_method(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression("$node.items", {"node": {"items": "from-json-key"}})
        self.assertEqual(out, "from-json-key")

    def test_resolve_expression_node_keys_json_key(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$node.keys",
            {"node": {"keys": [10, 20]}},
            preserve_type=True,
        )
        self.assertEqual(out, [10, 20])

    def test_resolve_expression_node_values_json_key(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$node.values",
            {"node": {"values": {"a": 1}}},
            preserve_type=True,
        )
        self.assertEqual(out, {"a": 1})

    def test_resolve_expression_array_add_preserves_nested_items_key(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$array().add(node)",
            {
                "node": {
                    "url": "https://heym.run/",
                    "items": [
                        {"question": "Q1", "score": -3},
                        {"question": "Q2", "score": 0},
                    ],
                }
            },
            preserve_type=True,
        )
        self.assertEqual(
            out,
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


class DotDictIterationMethodsTests(unittest.TestCase):
    """``.map`` / ``.filter`` / ``.keys`` / ``.values`` / ``.entries`` on objects (DotDict).

    Executor and :class:`ExpressionEvaluatorService` must agree on these semantics so
    the canvas Evaluate dialog matches live workflow execution.
    """

    def _ctx(self) -> dict:
        # Mimics the shape from the screenshot: ``$readSheet.rows.first()`` is a dict.
        return {
            "readSheet": {
                "rows": [
                    {"colA": "foo", "colB": "bar", "colC": None},
                ]
            }
        }

    def test_map_returns_values_list_via_item_value(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            '$readSheet.rows.first().map("item.value")',
            self._ctx(),
            preserve_type=True,
        )
        self.assertEqual(list(out), ["foo", "bar", None])

    def test_map_returns_keys_list_via_item_key(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            '$readSheet.rows.first().map("item.key")',
            self._ctx(),
            preserve_type=True,
        )
        self.assertEqual(list(out), ["colA", "colB", "colC"])

    def test_map_concat_key_value(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$readSheet.rows.first().map(\"concat('item.key', '=', 'item.value')\")",
            self._ctx(),
            preserve_type=True,
        )
        self.assertEqual(list(out), ["colA=foo", "colB=bar", "colC="])

    def test_filter_then_map_drops_null_values(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            '$readSheet.rows.first().filter("item.value != null").map("item.key")',
            self._ctx(),
            preserve_type=True,
        )
        self.assertEqual(list(out), ["colA", "colB"])

    def test_keys_returns_list(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$readSheet.rows.first().keys()",
            self._ctx(),
            preserve_type=True,
        )
        self.assertEqual(list(out), ["colA", "colB", "colC"])

    def test_values_returns_list(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$readSheet.rows.first().values()",
            self._ctx(),
            preserve_type=True,
        )
        self.assertEqual(list(out), ["foo", "bar", None])

    def test_entries_returns_key_value_pairs(self) -> None:
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$readSheet.rows.first().entries()",
            self._ctx(),
            preserve_type=True,
        )
        self.assertEqual(
            [dict(e) for e in out],
            [
                {"key": "colA", "value": "foo"},
                {"key": "colB", "value": "bar"},
                {"key": "colC", "value": None},
            ],
        )

    def test_keys_shadowed_by_json_key_preserves_existing_behavior(self) -> None:
        """Accessing ``$node.keys`` (no parens) must still return a JSON field named ``keys``."""
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$node.keys",
            {"node": {"keys": [10, 20]}},
            preserve_type=True,
        )
        self.assertEqual(out, [10, 20])

    def test_dict_map_returns_values_when_no_shadowing_key(self) -> None:
        """Calling ``.map()`` as a method returns our iteration helper when there is no JSON key."""
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            '$config.map("item.value")',
            {"config": {"a": 1, "b": 2}},
            preserve_type=True,
        )
        self.assertEqual(list(out), [1, 2])

    def test_evaluator_service_matches_executor_for_dict_map(self) -> None:
        """Evaluate dialog (ExpressionEvaluatorService) must produce the same result as executor."""
        ctx = self._ctx()
        expr = '$readSheet.rows.first().map("item.value")'
        executor_out = WorkflowExecutor(nodes=[], edges=[]).resolve_expression(
            expr, ctx, preserve_type=True
        )
        service_out = ExpressionEvaluatorService().evaluate(expr, ctx)
        self.assertEqual(list(executor_out), list(service_out.result))
        self.assertEqual(service_out.result_type, "array")
        self.assertTrue(service_out.preserved_type)
        self.assertIsNone(service_out.error)

    def test_entries_items_support_object_methods(self) -> None:
        """Each ``.entries()`` item is a DotDict and must support object methods (``.get``, chaining)."""
        ex = WorkflowExecutor(nodes=[], edges=[])
        ctx = {"obj": {"name": "Alice", "age": 30}}

        # .get on entry
        self.assertEqual(
            ex.resolve_expression('$obj.entries().first().get("key")', ctx, preserve_type=True),
            "name",
        )
        # attribute access on entry
        self.assertEqual(
            ex.resolve_expression("$obj.entries().first().value", ctx, preserve_type=True),
            "Alice",
        )
        # entry is itself iterable with .keys() / .values() / .map()
        self.assertEqual(
            list(ex.resolve_expression("$obj.entries().first().keys()", ctx, preserve_type=True)),
            ["key", "value"],
        )

    def test_values_list_preserves_nested_object_methods(self) -> None:
        """Values that are dicts/lists stay wrapped so object/array methods still work on them."""
        ex = WorkflowExecutor(nodes=[], edges=[])
        ctx = {
            "obj": {
                "meta": {"owner": "bob", "active": True},
                "tags": ["a", "b", "c"],
            }
        }
        # .values() first element is a dict → .get() must work on it.
        self.assertEqual(
            ex.resolve_expression(
                '$obj.values().first().get("owner")',
                ctx,
                preserve_type=True,
            ),
            "bob",
        )
        # .values()[1] is a list → .length must still work (array method preserved).
        self.assertEqual(
            ex.resolve_expression("$obj.values()[1].length", ctx, preserve_type=True),
            3,
        )

    def test_keys_list_supports_string_methods(self) -> None:
        """Each key produced by ``.keys()`` is a DotStr and supports string methods."""
        ex = WorkflowExecutor(nodes=[], edges=[])
        out = ex.resolve_expression(
            "$obj.keys().first().upper()",
            {"obj": {"name": "Alice"}},
            preserve_type=True,
        )
        self.assertEqual(out, "NAME")
