"""A RAG node with a blank Document Content or Query fails instead of embedding the inputs.

Both fields are required on the node page. A blank one went through
evaluate_message_template, which renders a blank template as str(inputs): insert and upsert
stored the Python repr of every input of the run, and search queried it.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import rag_node
from app.services.workflow_executor import WorkflowExecutor

_INPUTS = {"userInput": {"headers": {"user-agent": "curl"}, "body": {"text": "hi"}, "text": "hi"}}


def _run(node_data: dict) -> tuple[object, MagicMock]:
    executor = WorkflowExecutor(nodes=[], edges=[])
    store = MagicMock(collection_name="col1", credential_id="cred-1")
    executor._get_accessible_vector_store = MagicMock(return_value=store)
    executor._get_vector_store_backing_credential = MagicMock(return_value=MagicMock(type="rag"))
    service = MagicMock()
    service.insert.return_value = "p1"
    service.upsert_by_field.return_value = ("p1", 0)
    service.search.return_value = []
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="rag_1",
        inputs=_INPUTS,
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type="rag",
        node_data={"vectorStoreId": "vs-1", **node_data},
        node_label="notes",
    )
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch("app.services.encryption.decrypt_config", return_value={"db_type": "qdrant"}),
        patch(
            "app.services.vector_store.create_vector_store_service_for_credential",
            return_value=service,
        ),
    ):
        try:
            return rag_node.execute(ctx), service
        except ValueError as exc:
            return exc, service


class RagNodeBlankContentQueryTests(unittest.TestCase):
    def test_blank_fields_fail_without_touching_the_store(self) -> None:
        cases = {
            "insert": (
                {"ragOperation": "insert", "documentContent": ""},
                "RAG insert operation requires document content",
            ),
            "upsert": (
                {"ragOperation": "upsert", "documentId": "d1", "documentContent": "  "},
                "RAG upsert operation requires document content",
            ),
            "search": (
                {"ragOperation": "search", "queryText": ""},
                "RAG search operation requires a query",
            ),
            "search without the field": (
                {"ragOperation": "search"},
                "RAG search operation requires a query",
            ),
        }
        for name, (node_data, message) in cases.items():
            with self.subTest(name):
                result, service = _run(node_data)
                self.assertIsInstance(result, ValueError)
                self.assertEqual(str(result), message)
                service.insert.assert_not_called()
                service.upsert_by_field.assert_not_called()
                service.search.assert_not_called()

    def test_expressions_still_resolve(self) -> None:
        _, service = _run({"ragOperation": "insert", "documentContent": "$userInput.text"})
        service.insert.assert_called_once_with("col1", "hi", {})
        _, service = _run({"ragOperation": "search", "queryText": "about $userInput.text"})
        self.assertEqual(service.search.call_args.args[:2], ("col1", "about hi"))


if __name__ == "__main__":
    unittest.main()
