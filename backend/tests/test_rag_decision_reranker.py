"""RAG reranking with a Decision Model credential, next to the existing Cohere reranker."""

import unittest
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.credential_catalog import NODE_CREDENTIAL_FIELDS
from app.services.decision_models import DecisionProviderError
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import rag_node
from app.services.reranker import (
    DECISION_RERANK_LEVELS,
    DecisionRerankError,
    DecisionRerankerService,
    DocumentToRerank,
    build_decision_rerank_body,
    read_decision_rerank_scores,
)
from app.services.vector_store import SearchResult
from app.services.workflow_dsl_prompt import WORKFLOW_DSL_SYSTEM_PROMPT
from app.services.workflow_executor import NodeTraceableExecutionError

TOP = len(DECISION_RERANK_LEVELS) - 1


def _docs(count: int) -> list[DocumentToRerank]:
    return [
        DocumentToRerank(id=f"d{i}", text=f"finding {i}", score=1.0 - i * 0.1, metadata={"n": i})
        for i in range(count)
    ]


def _answers(*positions: float) -> dict:
    return {
        "model": "jev-latest",
        "answers": {
            f"finding_{index}": {"type": "score", "score": position, "confidence": 0.9}
            for index, position in enumerate(positions)
        },
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


class TestDecisionRerankBody(unittest.TestCase):
    def test_state_holds_the_query_and_the_findings_array(self) -> None:
        body = build_decision_rerank_body(model="jev-latest", query="reset VPN", documents=_docs(3))

        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(
            body["state"],
            {"query": "reset VPN", "findings": ["finding 0", "finding 1", "finding 2"]},
        )

    def test_every_finding_gets_its_own_score_question(self) -> None:
        body = build_decision_rerank_body(model="jev-latest", query="q", documents=_docs(3))

        self.assertEqual(list(body["questions"]), ["finding_0", "finding_1", "finding_2"])
        for index, question in enumerate(body["questions"].values()):
            self.assertEqual(question["type"], "score")
            self.assertEqual(question["criteria"], list(DECISION_RERANK_LEVELS))
            self.assertIn(f"`findings[{index}]`", question["instructions"])
            self.assertIn("`query`", question["instructions"])

    def test_levels_run_lowest_first(self) -> None:
        self.assertTrue(DECISION_RERANK_LEVELS[0].startswith("Irrelevant"))
        self.assertTrue(DECISION_RERANK_LEVELS[-1].startswith("Answers it"))


class TestReadDecisionRerankScores(unittest.TestCase):
    def test_positions_map_linearly_onto_zero_to_one(self) -> None:
        scores = read_decision_rerank_scores(_answers(0, TOP / 2, TOP), 3)

        self.assertEqual(scores, [0.0, 0.5, 1.0])

    def test_out_of_range_positions_are_clamped(self) -> None:
        scores = read_decision_rerank_scores(_answers(-1.0, TOP + 3), 2)

        self.assertEqual(scores, [0.0, 1.0])

    def test_a_missing_finding_fails_the_rerank(self) -> None:
        with self.assertRaisesRegex(DecisionRerankError, "no score for finding 1"):
            read_decision_rerank_scores(_answers(1.0), 2)

    def test_a_non_numeric_score_fails_the_rerank(self) -> None:
        for bad in (True, "3", None, float("nan")):
            with self.subTest(value=bad):
                payload = {"answers": {"finding_0": {"type": "score", "score": bad}}}
                with self.assertRaises(DecisionRerankError):
                    read_decision_rerank_scores(payload, 1)

    def test_a_response_without_answers_fails_the_rerank(self) -> None:
        for payload in ({}, {"answers": []}, None):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(DecisionRerankError, "no answers"):
                    read_decision_rerank_scores(payload, 1)


class TestDecisionRerankerService(unittest.TestCase):
    def _service(self, trace_context: object = None) -> DecisionRerankerService:
        return DecisionRerankerService(
            base_url="https://api.typesafe.ai",
            api_key="key",
            model="jev-latest",
            trace_context=trace_context,
        )

    def test_results_come_back_most_relevant_first(self) -> None:
        with patch(
            "app.services.reranker.call_decision_model", return_value=_answers(1, 4, 2)
        ) as call:
            results = self._service().rerank("q", _docs(3))

        self.assertEqual([r.id for r in results], ["d1", "d2", "d0"])
        self.assertEqual([r.relevance_score for r in results], [1.0, 0.5, 0.25])
        self.assertEqual(results[0].original_score, 0.9)
        self.assertEqual(results[0].metadata, {"n": 1})
        call.assert_called_once()

    def test_top_n_keeps_the_best_findings(self) -> None:
        with patch("app.services.reranker.call_decision_model", return_value=_answers(1, 4, 2)):
            results = self._service().rerank("q", _docs(3), top_n=2)

        self.assertEqual([r.id for r in results], ["d1", "d2"])

    def test_ties_keep_the_retrieval_order(self) -> None:
        with patch("app.services.reranker.call_decision_model", return_value=_answers(2, 3, 2, 3)):
            results = self._service().rerank("q", _docs(4))

        self.assertEqual([r.id for r in results], ["d1", "d3", "d0", "d2"])

    def test_one_request_carries_the_credential_and_the_trace_context(self) -> None:
        trace_context = MagicMock()
        with patch(
            "app.services.reranker.call_decision_model", return_value=_answers(1, 2)
        ) as call:
            self._service(trace_context).rerank("q", _docs(2))

        kwargs = call.call_args.kwargs
        self.assertEqual(kwargs["base_url"], "https://api.typesafe.ai")
        self.assertEqual(kwargs["api_key"], "key")
        self.assertIs(kwargs["trace_context"], trace_context)
        self.assertEqual(list(kwargs["body"]["questions"]), ["finding_0", "finding_1"])

    def test_no_findings_makes_no_request(self) -> None:
        with patch("app.services.reranker.call_decision_model") as call:
            self.assertEqual(self._service().rerank("q", []), [])

        call.assert_not_called()

    def test_provider_errors_propagate(self) -> None:
        error = DecisionProviderError("Decision model returned 500: boom", status_code=500)
        with patch("app.services.reranker.call_decision_model", side_effect=error):
            with self.assertRaises(DecisionProviderError):
                self._service().rerank("q", _docs(2))


def _decision_credential() -> MagicMock:
    return MagicMock(type=CredentialType.decision, encrypted_config="x")


def _run(
    node_data: dict,
    *,
    credential: MagicMock | None,
    config: dict,
    trace_ids: list | None = None,
) -> tuple[dict, MagicMock]:
    service = MagicMock()
    service.search.side_effect = lambda collection, query, limit, metadata_filter: [
        SearchResult(id=f"v{i}", text=f"vector {i}", score=0.5, metadata={}) for i in range(limit)
    ]
    executor = MagicMock()
    store = MagicMock()
    store.collection_name = "col1"
    executor._get_accessible_vector_store.return_value = store
    executor._get_vector_store_backing_credential.return_value = MagicMock(type="rag")
    executor._get_accessible_credential.side_effect = lambda db, credential_id: (
        credential if credential_id == "cred-1" else None
    )
    trace_context = MagicMock()
    trace_context.trace_ids = trace_ids if trace_ids is not None else []
    executor._build_llm_trace_context.return_value = trace_context
    executor.evaluate_message_template.side_effect = lambda template, inputs, node_id=None: template
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
            "queryText": "how do I reset the VPN",
            "searchLimit": 2,
            "enableReranker": True,
            "rerankerCredentialId": "cred-1",
            "rerankerModel": "jev-latest",
            **node_data,
        },
        node_label="rag",
    )

    def _decrypt(encrypted: object) -> dict:
        return config if encrypted == "x" else {"db_type": "qdrant"}

    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch("app.services.encryption.decrypt_config", side_effect=_decrypt),
        patch(
            "app.services.vector_store.create_vector_store_service_for_credential",
            return_value=service,
        ),
    ):
        return rag_node.execute(ctx), executor


DECISION_CONFIG = {"base_url": "https://api.typesafe.ai", "api_key": "dm-key"}


class TestRagNodeDecisionReranker(unittest.TestCase):
    def test_decision_credential_reranks_with_the_decision_model(self) -> None:
        scores = [0, 1, 4] + [0] * 17
        with (
            patch(
                "app.services.reranker.call_decision_model", return_value=_answers(*scores)
            ) as call,
            patch("app.services.reranker.create_reranker_service") as cohere,
        ):
            output, executor = _run(
                {}, credential=_decision_credential(), config=DECISION_CONFIG, trace_ids=["t-1"]
            )

        cohere.assert_not_called()
        body = call.call_args.kwargs["body"]
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"]["query"], "how do I reset the VPN")
        # The reranker widens the candidate pool, so all 20 hits are scored.
        self.assertEqual(len(body["state"]["findings"]), 20)
        self.assertEqual(call.call_args.kwargs["api_key"], "dm-key")
        executor._build_llm_trace_context.assert_called_once_with("cred-1", "rag_1")

        self.assertTrue(output["reranked"])
        self.assertEqual([r["id"] for r in output["results"]], ["v2", "v1"])
        self.assertEqual(output["results"][0]["relevance_score"], 1.0)
        self.assertEqual(output["results"][0]["score"], 0.5)
        self.assertEqual(output["count"], 2)
        self.assertEqual(output["_trace_id"], "t-1")

    def test_reranker_top_n_limits_the_results(self) -> None:
        with patch("app.services.reranker.call_decision_model", return_value=_answers(*range(20))):
            output, _ = _run(
                {"rerankerTopN": 3}, credential=_decision_credential(), config=DECISION_CONFIG
            )

        self.assertEqual(output["count"], 3)

    def test_a_provider_error_fails_the_node_and_says_so(self) -> None:
        error = DecisionProviderError("Decision model rejected the API key on this credential", 401)
        with patch("app.services.reranker.call_decision_model", side_effect=error):
            with self.assertRaisesRegex(ValueError, "Reranker failed: Decision model rejected"):
                _run({}, credential=_decision_credential(), config=DECISION_CONFIG)

    def test_a_traced_failure_stays_linked_to_its_trace(self) -> None:
        error = DecisionProviderError("Decision model returned 500: boom", 500)
        with patch("app.services.reranker.call_decision_model", side_effect=error):
            with self.assertRaises(NodeTraceableExecutionError) as caught:
                _run(
                    {},
                    credential=_decision_credential(),
                    config=DECISION_CONFIG,
                    trace_ids=["t-9"],
                )

        self.assertEqual(caught.exception.trace_id, "t-9")
        self.assertIn("Reranker failed", str(caught.exception))

    def test_a_malformed_answer_fails_the_node_instead_of_keeping_the_order(self) -> None:
        with patch("app.services.reranker.call_decision_model", return_value=_answers(1, 2)):
            with self.assertRaisesRegex(ValueError, "Reranker failed: .*no score for finding 2"):
                _run({}, credential=_decision_credential(), config=DECISION_CONFIG)

    def test_a_missing_model_fails_before_any_request(self) -> None:
        with patch("app.services.reranker.call_decision_model") as call:
            with self.assertRaisesRegex(ValueError, "enter the decision model"):
                _run(
                    {"rerankerModel": "  "},
                    credential=_decision_credential(),
                    config=DECISION_CONFIG,
                )

        call.assert_not_called()

    def test_a_credential_without_base_url_fails_before_any_request(self) -> None:
        with patch("app.services.reranker.call_decision_model") as call:
            with self.assertRaisesRegex(ValueError, "no base URL"):
                _run({}, credential=_decision_credential(), config={"api_key": "k"})

        call.assert_not_called()

    def test_an_inaccessible_credential_is_never_called(self) -> None:
        with patch("app.services.reranker.call_decision_model") as call:
            output, _ = _run(
                {"rerankerCredentialId": "someone-elses"},
                credential=_decision_credential(),
                config=DECISION_CONFIG,
            )

        call.assert_not_called()
        self.assertFalse(output["reranked"])
        self.assertEqual(output["count"], 2)

    def test_a_cohere_credential_still_reranks_with_cohere(self) -> None:
        cohere = MagicMock()
        cohere.rerank.return_value = []
        with (
            patch("app.services.reranker.create_reranker_service", return_value=cohere) as factory,
            patch("app.services.reranker.call_decision_model") as call,
        ):
            output, _ = _run(
                {},
                credential=MagicMock(type=CredentialType.cohere, encrypted_config="x"),
                config={"api_key": "cohere-key"},
            )

        factory.assert_called_once_with("cohere-key")
        call.assert_not_called()
        self.assertTrue(output["reranked"])
        self.assertNotIn("_trace_id", output)


class TestRerankerCredentialField(unittest.TestCase):
    def test_dsl_prompt_teaches_both_reranker_credentials(self) -> None:
        self.assertIn("`rerankerCredentialId`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("`rerankerModel`", WORKFLOW_DSL_SYSTEM_PROMPT)
        self.assertIn("`decision` credential (Decision Model)", WORKFLOW_DSL_SYSTEM_PROMPT)

    def test_rag_reranker_accepts_cohere_and_decision_credentials(self) -> None:
        (reranker,) = NODE_CREDENTIAL_FIELDS["rag"]

        self.assertEqual(
            reranker.types, frozenset({CredentialType.cohere, CredentialType.decision})
        )
        self.assertFalse(reranker.required)


if __name__ == "__main__":
    unittest.main()
