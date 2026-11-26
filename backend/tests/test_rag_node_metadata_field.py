"""A RAG node's documentMetadata and metadataFilters, run through the node.

Metadata that was not a JSON object was stored as {}, so a search filtered on it never found
the document, and neither field could take its object from the run as one expression.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import rag_node
from app.services.workflow_executor import WorkflowExecutor

_INPUTS = {
    "start": {
        "meta": {"source": "crm", "account": 42, "note": "$start.text"},
        "meta_text": '{"source": "crm", "account": 42}',
        "filter": {"account": 42},
        "plain": {"account": 42},
        "count": 7,
        "text": "hi",
    }
}


_WORKFLOW = "Notes sync"
_STAMP = {"source": f"workflow:{_WORKFLOW}"}


def _run(node_data: dict) -> tuple[object, MagicMock]:
    executor = WorkflowExecutor(nodes=[], edges=[], workflow_name=_WORKFLOW)
    store = MagicMock(collection_name="col1", credential_id="cred-1")
    executor._get_accessible_vector_store = MagicMock(return_value=store)
    executor._get_vector_store_backing_credential = MagicMock(return_value=MagicMock(type="rag"))
    service = MagicMock()
    service.insert.return_value = "p1"
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


def _insert(metadata: object) -> tuple[object, MagicMock]:
    return _run(
        {"ragOperation": "insert", "documentContent": "hello", "documentMetadata": metadata}
    )


class RagDocumentMetadataTests(unittest.TestCase):
    def test_metadata_that_is_not_a_json_object_fails_and_stores_nothing(self) -> None:
        for metadata, message in (
            ('{"source": "crm",}', "documentMetadata is not valid JSON"),
            ('["crm"]', "documentMetadata must be a JSON object"),
            ("$start.count", "documentMetadata must be a JSON object"),
        ):
            with self.subTest(metadata=metadata):
                result, service = _insert(metadata)

                self.assertIsInstance(result, ValueError)
                self.assertIn(message, str(result))
                service.insert.assert_not_called()

    def test_one_expression_stores_the_run_s_object_as_it_is(self) -> None:
        _, service = _insert("$start.meta")
        stored = service.insert.call_args.args[2]
        # Numbers stay numbers, and "$" inside a value from the run is not resolved again.
        self.assertEqual(stored, {"source": "crm", "account": 42, "note": "$start.text"})
        self.assertIs(type(stored["account"]), int)

        _, service = _insert("$start.meta_text")
        self.assertEqual(service.insert.call_args.args[2], {"source": "crm", "account": 42})

    def test_one_expression_without_a_source_gets_the_workflow_stamp(self) -> None:
        _, service = _insert("$start.plain")

        self.assertEqual(service.insert.call_args.args[2], {"account": 42, **_STAMP})

    def test_one_expression_with_its_own_source_keeps_it(self) -> None:
        _, service = _insert("$start.meta")

        self.assertEqual(service.insert.call_args.args[2]["source"], "crm")

    def test_blank_empty_and_null_store_only_the_workflow_stamp(self) -> None:
        # main stored {} with no stamp for "null", so the document could not be traced back.
        for metadata in ("", "{}", "null", None):
            with self.subTest(metadata=metadata):
                _, service = _insert(metadata)
                self.assertEqual(service.insert.call_args.args[2], _STAMP)


class RagMetadataFilterExpressionTests(unittest.TestCase):
    def test_a_filter_can_come_from_the_run_as_one_expression(self) -> None:
        _, service = _run(
            {"ragOperation": "search", "queryText": "q", "metadataFilters": "$start.filter"}
        )

        self.assertEqual(service.search.call_args.kwargs["metadata_filter"], {"account": 42})

    def test_an_expression_that_is_not_an_object_fails(self) -> None:
        result, service = _run(
            {"ragOperation": "search", "queryText": "q", "metadataFilters": "$start.count"}
        )

        self.assertIn("metadataFilters must be a JSON object", str(result))
        service.search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
