"""RAG node search keeps to searchLimit when the reranker cannot run."""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import rag_node


def _run(node_data: dict, reranker_credential: MagicMock | None) -> tuple[dict, MagicMock]:
    executor = MagicMock()
    store = MagicMock()
    store.collection_name = "col1"
    executor._get_accessible_vector_store.return_value = store
    executor._get_vector_store_backing_credential.return_value = MagicMock(type="rag")
    executor._get_accessible_credential.return_value = reranker_credential
    executor.evaluate_message_template.side_effect = lambda template, inputs, node_id=None: template
    service = MagicMock()
    service.search.side_effect = lambda collection, query, limit, metadata_filter: [
        MagicMock(id=str(i), text=f"t{i}", score=1.0, metadata={}) for i in range(limit)
    ]
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="rag_1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type="rag",
        node_data={"vectorStoreId": "vs-1", "ragOperation": "search", **node_data},
        node_label="rag",
    )
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch("app.services.encryption.decrypt_config", return_value={"db_type": "qdrant"}),
        patch(
            "app.services.vector_store.create_vector_store_service_for_credential",
            return_value=service,
        ),
    ):
        return rag_node.execute(ctx), service


class TestRagNodeSearchLimit(unittest.TestCase):
    def test_unusable_reranker_credential_returns_search_limit_results(self) -> None:
        output, service = _run(
            {"searchLimit": 5, "enableReranker": True, "rerankerCredentialId": "gone"},
            None,
        )

        self.assertEqual(service.search.call_args.kwargs["limit"], 20)
        self.assertFalse(output["reranked"])
        self.assertEqual(output["count"], 5)
        self.assertEqual(len(output["results"]), 5)

    def test_search_without_reranker_returns_search_limit_results(self) -> None:
        output, _ = _run({"searchLimit": 5}, None)

        self.assertEqual(output["count"], 5)

    def test_negative_search_limit_returns_no_results(self) -> None:
        output, _ = _run(
            {"searchLimit": -5, "enableReranker": True, "rerankerCredentialId": "gone"},
            None,
        )

        self.assertEqual(output["count"], 0)
