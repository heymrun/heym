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


class RegistryTest(unittest.TestCase):
    def test_code_node_is_registered(self) -> None:
        from app.services.node_execution.registry import get_node_handler

        self.assertIsNotNone(get_node_handler("code"))


if __name__ == "__main__":
    unittest.main()
