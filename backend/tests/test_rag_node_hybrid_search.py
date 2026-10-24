"""RAG node search switches to hybrid (vector + BM25) retrieval with the hybridSearch flag."""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import rag_node
from app.services.reranker import RerankResult
from app.services.vector_store import HybridSearchResult, SearchResult
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT


def _hybrid_hit(index: int) -> HybridSearchResult:
    return HybridSearchResult(
        id=f"h{index}",
        text=f"hybrid {index}",
        score=1.0 - index * 0.1,
        metadata={"n": index},
        vector_score=0.9 - index * 0.1 if index % 2 == 0 else None,
        keyword_score=3.0 - index if index % 2 == 1 else None,
    )


def _service() -> MagicMock:
    service = MagicMock()
    service.search.side_effect = lambda collection, query, limit, metadata_filter: [
        SearchResult(id=f"v{i}", text=f"vector {i}", score=0.5, metadata={}) for i in range(limit)
    ]
    service.hybrid_search.side_effect = lambda collection, query, limit, metadata_filter: [
        _hybrid_hit(i) for i in range(limit)
    ]
    return service


def _run(node_data: dict, service: MagicMock | None = None) -> tuple[dict, MagicMock]:
    service = service or _service()
    executor = MagicMock()
    store = MagicMock()
    store.collection_name = "col1"
    executor._get_accessible_vector_store.return_value = store
    executor._get_vector_store_backing_credential.return_value = MagicMock(type="rag")
    executor._get_accessible_credential.return_value = MagicMock(encrypted_config="x")
    executor.evaluate_message_template.side_effect = lambda template, inputs, node_id=None: template
    executor._is_single_dollar_expression.return_value = False
    executor._unwrap_value.side_effect = lambda value: value
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="rag_1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type="rag",
        node_data={
            "vectorStoreId": "vs-1",
            "ragOperation": "search",
            "queryText": "ERR-4021",
            **node_data,
        },
        node_label="rag",
    )
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch(
            "app.services.encryption.decrypt_config",
            return_value={"db_type": "qdrant", "api_key": "cohere-key"},
        ),
        patch(
            "app.services.vector_store.create_vector_store_service_for_credential",
            return_value=service,
        ),
    ):
        return rag_node.execute(ctx), service


class TestRagNodeHybridSearch(unittest.TestCase):
    def test_hybrid_flag_routes_the_search_through_hybrid_retrieval(self) -> None:
        output, service = _run({"hybridSearch": True, "searchLimit": 3})

        service.hybrid_search.assert_called_once()
        service.search.assert_not_called()
        self.assertTrue(output["hybrid"])
        self.assertEqual([r["id"] for r in output["results"]], ["h0", "h1", "h2"])

    def test_hybrid_search_gets_the_same_arguments_as_a_plain_search(self) -> None:
        _, service = _run(
            {"hybridSearch": True, "searchLimit": 4, "metadataFilters": '{"team": "a"}'}
        )

        args = service.hybrid_search.call_args
        self.assertEqual(args.args, ("col1", "ERR-4021"))
        self.assertEqual(args.kwargs, {"limit": 4, "metadata_filter": {"team": "a"}})

    def test_plain_search_is_the_default(self) -> None:
        output, service = _run({"searchLimit": 3})

        service.search.assert_called_once()
        service.hybrid_search.assert_not_called()
        self.assertFalse(output["hybrid"])
        self.assertNotIn("vector_score", output["results"][0])
        self.assertNotIn("keyword_score", output["results"][0])

    def test_explicitly_disabled_flag_uses_plain_search(self) -> None:
        for disabled in (False, "false", "", None, "0"):
            with self.subTest(value=disabled):
                _, service = _run({"hybridSearch": disabled})

                service.search.assert_called_once()
                service.hybrid_search.assert_not_called()

    def test_flag_arriving_as_a_string_still_enables_hybrid(self) -> None:
        for enabled in ("true", "True", "1"):
            with self.subTest(value=enabled):
                _, service = _run({"hybridSearch": enabled})

                service.hybrid_search.assert_called_once()
                service.search.assert_not_called()

    def test_results_carry_the_fused_score_and_each_legs_score(self) -> None:
        output, _ = _run({"hybridSearch": True, "searchLimit": 2})

        first, second = output["results"]
        self.assertEqual(first["score"], 1.0)
        self.assertAlmostEqual(first["vector_score"], 0.9)
        self.assertIsNone(first["keyword_score"])
        self.assertIsNone(second["vector_score"])
        self.assertAlmostEqual(second["keyword_score"], 2.0)
        self.assertEqual(second["metadata"], {"n": 1})

    def test_hybrid_results_are_limited_to_search_limit(self) -> None:
        service = _service()
        service.hybrid_search.side_effect = None
        service.hybrid_search.return_value = [_hybrid_hit(i) for i in range(8)]

        output, _ = _run({"hybridSearch": True, "searchLimit": 3}, service)

        self.assertEqual(output["count"], 3)

    def test_reranker_widens_the_hybrid_candidate_pool(self) -> None:
        reranker = MagicMock()
        reranker.rerank.return_value = []

        with patch("app.services.reranker.create_reranker_service", return_value=reranker):
            _, service = _run(
                {
                    "hybridSearch": True,
                    "searchLimit": 5,
                    "enableReranker": True,
                    "rerankerCredentialId": "cohere",
                }
            )

        self.assertEqual(service.hybrid_search.call_args.kwargs["limit"], 20)

    def test_reranked_hybrid_results_keep_each_legs_score(self) -> None:
        reranker = MagicMock()
        reranker.rerank.return_value = [
            RerankResult(
                id="h1", text="hybrid 1", original_score=0.9, relevance_score=0.99, metadata={}
            ),
            RerankResult(
                id="h0", text="hybrid 0", original_score=1.0, relevance_score=0.5, metadata={}
            ),
        ]

        with patch("app.services.reranker.create_reranker_service", return_value=reranker):
            output, _ = _run(
                {
                    "hybridSearch": True,
                    "searchLimit": 2,
                    "enableReranker": True,
                    "rerankerCredentialId": "cohere",
                }
            )

        self.assertTrue(output["reranked"])
        self.assertTrue(output["hybrid"])
        first = output["results"][0]
        self.assertEqual(first["id"], "h1")
        self.assertEqual(first["relevance_score"], 0.99)
        self.assertAlmostEqual(first["keyword_score"], 2.0)
        self.assertIsNone(first["vector_score"])

    def test_other_operations_never_touch_hybrid_retrieval(self) -> None:
        service = _service()
        service.insert.return_value = "point-1"

        output, _ = _run(
            {"ragOperation": "insert", "documentContent": "text", "hybridSearch": True}, service
        )

        self.assertEqual(output["operation"], "insert")
        service.hybrid_search.assert_not_called()


class TestRagHybridSearchDsl(unittest.TestCase):
    def test_prompt_documents_the_flag_its_scores_and_an_example(self) -> None:
        self.assertIn("`hybridSearch`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn('"hybridSearch": true', WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("keyword_score", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("`$ragNodeLabel.hybrid`", WORKFLOW_DSL_SYSTEM_PROMPT)

    def test_prompt_lists_the_flag_on_the_search_operation_only(self) -> None:
        row = next(
            line
            for line in WORKFLOW_DSL_SYSTEM_PROMPT.splitlines()
            if line.startswith("| `search` |") and "queryText" in line
        )
        self.assertIn("hybridSearch (optional)", row)


if __name__ == "__main__":
    unittest.main()
