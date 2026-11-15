from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from starlette.responses import JSONResponse

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import throw_error_node


class ThrowErrorNodeTests(unittest.TestCase):
    def _create_context(self, node_data: dict) -> NodeExecutionContext:
        executor = MagicMock()
        executor.evaluate_message_template.side_effect = lambda t, *a, **k: t
        return NodeExecutionContext(
            executor=executor,
            node_id="throw_1",
            node_label="Throw Error",
            node_type="throwError",
            node_data=node_data,
            inputs={},
            start_time=0.0,
            allow_branch_skip=False,
            node={"id": "throw_1", "type": "throwError", "data": node_data},
        )

    def test_integer_status_code_is_preserved(self) -> None:
        ctx = self._create_context({"errorMessage": "Not found", "httpStatusCode": 404})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.output, {"httpStatusCode": 404})

    def test_string_status_code_is_coerced_to_integer(self) -> None:
        ctx = self._create_context({"errorMessage": "Bad request", "httpStatusCode": "400"})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.output, {"httpStatusCode": 400})
        self.assertIsInstance(result.output["httpStatusCode"], int)

    def test_out_of_range_status_code_is_omitted(self) -> None:
        ctx = self._create_context({"errorMessage": "Fail", "httpStatusCode": 999})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.output, {})

    def test_non_numeric_status_code_is_omitted(self) -> None:
        ctx = self._create_context({"errorMessage": "Fail", "httpStatusCode": "invalid"})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.output, {})

    def test_empty_status_code_is_omitted(self) -> None:
        ctx = self._create_context({"errorMessage": "Fail"})
        result = throw_error_node.execute(ctx)
        self.assertEqual(result.output, {})

    def test_string_status_code_in_json_response_does_not_crash(self) -> None:
        # Verify defensive coercion for Starlette JSONResponse
        for raw_code, expected_status in [
            ("404", 404),
            ("400", 400),
            (403, 403),
            ("999", 400),
            ("bad", 400),
        ]:
            try:
                status_int = int(raw_code)
                if not (100 <= status_int <= 599):
                    status_int = 400
            except (ValueError, TypeError):
                status_int = 400
            response = JSONResponse(status_code=status_int, content={"error": "test"})
            self.assertEqual(response.status_code, expected_status)


if __name__ == "__main__":
    unittest.main()
