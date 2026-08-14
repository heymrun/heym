import unittest
from unittest.mock import MagicMock, patch

from app.services.code_python_executor import CodeExecutionResult
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import code_node


def _context(node_data: dict) -> NodeExecutionContext:
    executor = MagicMock()
    executor.evaluate_message_template.side_effect = lambda template, *_args, **_kw: template
    return NodeExecutionContext(
        executor=executor,
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={"id": "n1", "type": "code", "data": node_data},
        node_type="code",
        node_data=node_data,
        node_label="transform",
    )


class CodeNodeTest(unittest.TestCase):
    def test_packages_result_logs_and_install_metadata(self) -> None:
        ctx = _context({"codeSource": "def main(params):\n    return 1\n"})
        outcome = CodeExecutionResult(
            result={"ok": True}, logs="hi\n", install_tool="none", install_log=""
        )
        with patch.object(code_node, "execute_code", return_value=outcome) as run_code:
            output = code_node.execute(ctx)

        self.assertEqual(
            output,
            {
                "result": {"ok": True},
                "logs": "hi\n",
                "install": {"ok": True, "tool": "none", "log": ""},
            },
        )
        run_code.assert_called_once()

    def test_parameters_json_is_resolved_and_passed_through(self) -> None:
        ctx = _context(
            {
                "codeSource": "def main(params):\n    return 1\n",
                "codeParameters": '{"name": "Ada", "count": 3}',
            }
        )
        with patch.object(
            code_node, "execute_code", return_value=CodeExecutionResult(result=None)
        ) as run_code:
            code_node.execute(ctx)

        self.assertEqual(run_code.call_args.kwargs["params"], {"name": "Ada", "count": 3})

    def test_blank_parameters_become_an_empty_dict(self) -> None:
        ctx = _context({"codeSource": "def main(params):\n    return 1\n", "codeParameters": "  "})
        with patch.object(
            code_node, "execute_code", return_value=CodeExecutionResult(result=None)
        ) as run_code:
            code_node.execute(ctx)

        self.assertEqual(run_code.call_args.kwargs["params"], {})

    def test_invalid_parameters_json_raises_a_clear_error(self) -> None:
        ctx = _context(
            {"codeSource": "def main(params):\n    return 1\n", "codeParameters": "{oops"}
        )
        with self.assertRaises(ValueError) as err:
            code_node.execute(ctx)
        self.assertIn("Parameters", str(err.exception))

    def test_non_object_parameters_json_is_rejected(self) -> None:
        ctx = _context(
            {"codeSource": "def main(params):\n    return 1\n", "codeParameters": "[1,2]"}
        )
        with self.assertRaises(ValueError) as err:
            code_node.execute(ctx)
        self.assertIn("JSON object", str(err.exception))

    def test_empty_code_is_rejected_before_starting_a_container(self) -> None:
        ctx = _context({"codeSource": "   "})
        with patch.object(code_node, "execute_code") as run_code:
            with self.assertRaises(ValueError) as err:
                code_node.execute(ctx)
        run_code.assert_not_called()
        self.assertIn("Code is empty", str(err.exception))

    def test_allow_network_flag_is_forwarded(self) -> None:
        ctx = _context(
            {"codeSource": "def main(params):\n    return 1\n", "codeAllowNetwork": True}
        )
        with patch.object(
            code_node, "execute_code", return_value=CodeExecutionResult(result=None)
        ) as run_code:
            code_node.execute(ctx)
        self.assertTrue(run_code.call_args.kwargs["allow_network"])

    def test_requirements_are_forwarded_verbatim(self) -> None:
        ctx = _context(
            {
                "codeSource": "def main(params):\n    return 1\n",
                "codeRequirements": "requests==2.32.3\n",
            }
        )
        with patch.object(
            code_node, "execute_code", return_value=CodeExecutionResult(result=None)
        ) as run_code:
            code_node.execute(ctx)
        self.assertEqual(run_code.call_args.kwargs["requirements"], "requests==2.32.3\n")

    def test_install_tool_is_reflected_in_the_output(self) -> None:
        ctx = _context({"codeSource": "def main(params):\n    return 1\n"})
        outcome = CodeExecutionResult(
            result=1, logs="", install_tool="pip", install_log="Successfully installed"
        )
        with patch.object(code_node, "execute_code", return_value=outcome):
            output = code_node.execute(ctx)
        self.assertEqual(
            output["install"], {"ok": True, "tool": "pip", "log": "Successfully installed"}
        )


class ParameterResolutionTest(unittest.TestCase):
    """Expressions inside the Parameters JSON must survive quoting and keep their type."""

    @staticmethod
    def _ctx(parameters: str, resolved: dict) -> NodeExecutionContext:
        ctx = _context(
            {"codeSource": "def main(params):\n    return 1\n", "codeParameters": parameters}
        )
        ctx.executor.resolve_expression.side_effect = lambda expr, *a, **k: resolved[expr]
        ctx.executor.evaluate_message_template.side_effect = lambda tpl, *a, **k: "".join(
            str(resolved.get(part, part)) for part in [tpl]
        )
        return ctx

    def _params_for(self, parameters: str, resolved: dict) -> dict:
        ctx = self._ctx(parameters, resolved)
        with patch.object(
            code_node, "execute_code", return_value=CodeExecutionResult(result=None)
        ) as run_code:
            code_node.execute(ctx)
        return run_code.call_args.kwargs["params"]

    def test_string_with_quotes_does_not_break_the_json(self) -> None:
        params = self._params_for(
            '{"name": "$trigger.name"}', {"$trigger.name": 'Ada "A" Lovelace'}
        )
        self.assertEqual(params, {"name": 'Ada "A" Lovelace'})

    def test_multiline_string_does_not_break_the_json(self) -> None:
        params = self._params_for('{"body": "$fetch.text"}', {"$fetch.text": "line1\nline2"})
        self.assertEqual(params, {"body": "line1\nline2"})

    def test_list_keeps_its_type_instead_of_being_stringified(self) -> None:
        rows = [{"id": 1}, {"id": 2}]
        params = self._params_for('{"rows": "$fetch.result"}', {"$fetch.result": rows})
        self.assertEqual(params, {"rows": rows})

    def test_integer_stays_an_integer(self) -> None:
        params = self._params_for('{"n": "$fetch.count"}', {"$fetch.count": 7})
        self.assertEqual(params, {"n": 7})
        self.assertIsInstance(params["n"], int)

    def test_nested_objects_and_arrays_are_resolved(self) -> None:
        params = self._params_for(
            '{"cfg": {"name": "$t.name"}, "ids": ["$t.id"]}',
            {"$t.name": "Ada", "$t.id": 5},
        )
        self.assertEqual(params, {"cfg": {"name": "Ada"}, "ids": [5]})

    def test_literal_values_are_left_alone(self) -> None:
        params = self._params_for('{"a": 1, "b": "plain", "c": true}', {})
        self.assertEqual(params, {"a": 1, "b": "plain", "c": True})


class RegistryTest(unittest.TestCase):
    def test_code_node_is_registered(self) -> None:
        from app.services.node_execution.registry import get_node_handler

        self.assertIsNotNone(get_node_handler("code"))


if __name__ == "__main__":
    unittest.main()
