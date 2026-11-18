"""Tests ensuring all OpenAPI operationId values are unique and emit no duplicate warnings."""

import unittest
import warnings

from app.main import app


class OpenAPIOperationIdTests(unittest.TestCase):
    def test_all_operation_ids_are_unique_and_no_duplicate_warning(self) -> None:
        """Verify that app.openapi() emits no duplicate Operation ID warnings and all IDs are unique."""
        app.openapi_schema = None

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            schema = app.openapi()

        duplicate_warnings = [
            str(w.message) for w in captured if "Duplicate Operation ID" in str(w.message)
        ]
        self.assertEqual(
            duplicate_warnings,
            [],
            f"Expected no Duplicate Operation ID warnings, got: {duplicate_warnings}",
        )

        operation_ids: list[str] = []
        for path_item in schema.get("paths", {}).values():
            for method, operation in path_item.items():
                if method.lower() in {
                    "get",
                    "post",
                    "put",
                    "delete",
                    "patch",
                    "options",
                    "head",
                    "trace",
                } and isinstance(operation, dict):
                    op_id = operation.get("operationId")
                    if op_id:
                        operation_ids.append(op_id)

        seen: set[str] = set()
        duplicates: set[str] = set()
        for op_id in operation_ids:
            if op_id in seen:
                duplicates.add(op_id)
            seen.add(op_id)

        self.assertEqual(
            duplicates,
            set(),
            f"Found duplicate operationId values in OpenAPI schema: {duplicates}",
        )

    def test_workflow_execution_endpoints_have_method_specific_operation_ids(self) -> None:
        """Verify that /execute and /execute/stream have stable, method-specific operation IDs."""
        app.openapi_schema = None
        schema = app.openapi()
        paths = schema.get("paths", {})

        execute_path = paths.get("/api/workflows/{workflow_id}/execute", {})
        for method in ("get", "post", "put", "delete"):
            self.assertIn(method, execute_path)
            expected_id = f"execute_workflow_endpoint_api_workflows__workflow_id__execute_{method}"
            self.assertEqual(execute_path[method].get("operationId"), expected_id)

        stream_path = paths.get("/api/workflows/{workflow_id}/execute/stream", {})
        for method in ("get", "post", "put", "delete"):
            self.assertIn(method, stream_path)
            expected_id = (
                f"execute_workflow_stream_api_workflows__workflow_id__execute_stream_{method}"
            )
            self.assertEqual(stream_path[method].get("operationId"), expected_id)


if __name__ == "__main__":
    unittest.main()
