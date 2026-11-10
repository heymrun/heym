"""RAG reranking with a Decision Model credential, next to the existing Cohere reranker."""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.db.models import CredentialType
from app.services.credential_catalog import NODE_CREDENTIAL_FIELDS
from app.services.decision_models import DecisionProviderError
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import rag_node
from app.services.reranker import (
    DECISION_RERANK_LEVELS,
    DECISION_RERANK_MAX_CONCURRENCY,
    DecisionRerankError,
    DecisionRerankerService,
    DocumentToRerank,
    build_decision_rerank_body,
    read_decision_rerank_score,
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


def _answer(position: object) -> dict:
    return {
        "model": "jev-latest",
        "answers": {"relevance": {"type": "score", "score": position, "confidence": 0.9}},
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


def _scored_by_text(scores: dict[str, float], default: float = 0.0):
    """A stand-in for the decision endpoint that scores each finding by its text."""

    def _call(**kwargs: object) -> dict:
        body = kwargs["body"]
        assert isinstance(body, dict)
        return _answer(scores.get(body["state"]["finding"], default))

    return _call


class TestDecisionRerankBody(unittest.TestCase):
    def test_state_holds_the_query_and_one_finding(self) -> None:
        body = build_decision_rerank_body(model="jev-latest", query="reset VPN", text="finding 3")

        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"], {"query": "reset VPN", "finding": "finding 3"})

    def test_one_score_question_refers_to_both_fields_by_name(self) -> None:
        body = build_decision_rerank_body(model="jev-latest", query="q", text="t")

        self.assertEqual(list(body["questions"]), ["relevance"])
        question = body["questions"]["relevance"]
        self.assertEqual(question["type"], "score")
        self.assertEqual(question["criteria"], list(DECISION_RERANK_LEVELS))
        self.assertIn("`finding`", question["instructions"])
        self.assertIn("`query`", question["instructions"])

    def test_levels_run_lowest_first(self) -> None:
        self.assertTrue(DECISION_RERANK_LEVELS[0].startswith("Irrelevant"))
        self.assertTrue(DECISION_RERANK_LEVELS[-1].startswith("Answers it"))


class TestReadDecisionRerankScore(unittest.TestCase):
    def test_positions_map_linearly_onto_zero_to_one(self) -> None:
        for position, expected in ((0, 0.0), (TOP / 2, 0.5), (TOP, 1.0), (2.4, 0.6)):
            with self.subTest(position=position):
                self.assertEqual(read_decision_rerank_score(_answer(position)), expected)

    def test_out_of_range_positions_are_clamped(self) -> None:
        self.assertEqual(read_decision_rerank_score(_answer(-1.0)), 0.0)
        self.assertEqual(read_decision_rerank_score(_answer(TOP + 3)), 1.0)

    def test_a_non_numeric_score_fails_the_rerank(self) -> None:
        for bad in (True, "3", None, float("nan")):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(DecisionRerankError, "no relevance score"):
                    read_decision_rerank_score(_answer(bad))

    def test_a_response_without_the_answer_fails_the_rerank(self) -> None:
        for payload in ({}, {"answers": []}, {"answers": {"other": {}}}, None):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(DecisionRerankError, "no relevance score"):
                    read_decision_rerank_score(payload)


class TestDecisionRerankerService(unittest.TestCase):
    def _service(self, trace_context: object = None) -> DecisionRerankerService:
        return DecisionRerankerService(
            base_url="https://api.typesafe.ai",
            api_key="key",
            model="jev-latest",
            trace_context=trace_context,
        )

    def test_results_come_back_most_relevant_first(self) -> None:
        scorer = _scored_by_text({"finding 0": 1, "finding 1": 4, "finding 2": 2})
        with patch("app.services.reranker.call_decision_model", side_effect=scorer):
            results = self._service().rerank("q", _docs(3))

        self.assertEqual([r.id for r in results], ["d1", "d2", "d0"])
        self.assertEqual([r.relevance_score for r in results], [1.0, 0.5, 0.25])
        self.assertEqual(results[0].original_score, 0.9)
        self.assertEqual(results[0].metadata, {"n": 1})

    def test_every_finding_is_scored_in_its_own_request(self) -> None:
        with patch(
            "app.services.reranker.call_decision_model", side_effect=_scored_by_text({})
        ) as call:
            self._service().rerank("q", _docs(5))

        self.assertEqual(call.call_count, 5)
        findings = sorted(c.kwargs["body"]["state"]["finding"] for c in call.call_args_list)
        self.assertEqual(findings, [f"finding {i}" for i in range(5)])
        for request in call.call_args_list:
            self.assertEqual(request.kwargs["body"]["state"]["query"], "q")

    def test_requests_run_in_parallel_up_to_the_cap(self) -> None:
        lock = threading.Lock()
        running = 0
        peak = 0

        def _slow(**kwargs: object) -> dict:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.02)
            with lock:
                running -= 1
            return _answer(1)

        with patch("app.services.reranker.call_decision_model", side_effect=_slow):
            self._service().rerank("q", _docs(20))

        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, DECISION_RERANK_MAX_CONCURRENCY)

    def test_top_n_keeps_the_best_findings(self) -> None:
        scorer = _scored_by_text({"finding 0": 1, "finding 1": 4, "finding 2": 2})
        with patch("app.services.reranker.call_decision_model", side_effect=scorer):
            results = self._service().rerank("q", _docs(3), top_n=2)

        self.assertEqual([r.id for r in results], ["d1", "d2"])

    def test_ties_keep_the_retrieval_order(self) -> None:
        scorer = _scored_by_text({"finding 0": 2, "finding 1": 3, "finding 2": 2, "finding 3": 3})
        with patch("app.services.reranker.call_decision_model", side_effect=scorer):
            results = self._service().rerank("q", _docs(4))

        self.assertEqual([r.id for r in results], ["d1", "d3", "d0", "d2"])

    def test_each_request_carries_the_credential_and_is_not_traced_on_its_own(self) -> None:
        with (
            patch(
                "app.services.reranker.call_decision_model", side_effect=_scored_by_text({})
            ) as call,
            patch("app.services.reranker.record_llm_trace"),
        ):
            self._service(MagicMock()).rerank("q", _docs(2))

        for request in call.call_args_list:
            self.assertEqual(request.kwargs["base_url"], "https://api.typesafe.ai")
            self.assertEqual(request.kwargs["api_key"], "key")
            self.assertIsNone(request.kwargs.get("trace_context"))

    def test_the_whole_rerank_is_one_trace_with_summed_usage(self) -> None:
        trace_context = MagicMock()
        scorer = _scored_by_text({"finding 0": 1, "finding 1": 4, "finding 2": 2})
        with (
            patch("app.services.reranker.call_decision_model", side_effect=scorer),
            patch("app.services.reranker.record_llm_trace") as record,
        ):
            self._service(trace_context).rerank("q", _docs(3))

        record.assert_called_once()
        args, kwargs = record.call_args
        self.assertIs(args[0], trace_context)
        self.assertEqual(kwargs["request_type"], "decision.systemone")
        self.assertEqual(kwargs["provider"], "decision")
        self.assertIsNone(kwargs["error"])
        self.assertEqual(kwargs["prompt_tokens"], 30)
        self.assertEqual(kwargs["completion_tokens"], 6)
        self.assertEqual(kwargs["total_tokens"], 36)
        rerank = kwargs["request"]["rerank"]
        self.assertEqual(rerank["query"], "q")
        self.assertEqual(rerank["findings"], ["finding 0", "finding 1", "finding 2"])
        self.assertEqual(rerank["requests"], 3)
        answers = kwargs["response"]["answers"]
        self.assertEqual([a["finding"] for a in answers], [0, 1, 2])
        self.assertEqual([a["answer"]["score"] for a in answers], [1, 4, 2])

    def test_a_failed_rerank_is_still_one_trace_that_names_the_error(self) -> None:
        error = DecisionProviderError("Decision model returned 500: boom", status_code=500)
        with (
            patch("app.services.reranker.call_decision_model", side_effect=error),
            patch("app.services.reranker.record_llm_trace") as record,
        ):
            with self.assertRaises(DecisionProviderError):
                self._service(MagicMock()).rerank("q", _docs(3))

        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["error"], "Decision model returned 500: boom")
        self.assertIsNone(record.call_args.kwargs["prompt_tokens"])

    def test_no_trace_context_records_nothing(self) -> None:
        with (
            patch("app.services.reranker.call_decision_model", side_effect=_scored_by_text({})),
            patch("app.services.reranker.record_llm_trace") as record,
        ):
            self._service().rerank("q", _docs(2))

        record.assert_not_called()

    def test_no_findings_makes_no_request(self) -> None:
        with patch("app.services.reranker.call_decision_model") as call:
            self.assertEqual(self._service().rerank("q", []), [])

        call.assert_not_called()

    def test_provider_errors_propagate(self) -> None:
        error = DecisionProviderError("Decision model returned 500: boom", status_code=500)
        with patch("app.services.reranker.call_decision_model", side_effect=error):
            with self.assertRaises(DecisionProviderError):
                self._service().rerank("q", _docs(2))

    def test_one_failure_fails_the_rerank_and_drops_requests_not_yet_started(self) -> None:
        error = DecisionProviderError("Decision model returned 500: boom", status_code=500)

        def _first_fails(**kwargs: object) -> dict:
            body = kwargs["body"]
            assert isinstance(body, dict)
            if body["state"]["finding"] == "finding 0":
                raise error
            time.sleep(0.05)
            return _answer(1)

        with patch("app.services.reranker.call_decision_model", side_effect=_first_fails) as call:
            with self.assertRaises(DecisionProviderError):
                self._service().rerank("q", _docs(40))

        self.assertLess(call.call_count, 40)

    def test_an_answer_without_a_score_fails_the_rerank_and_names_the_finding(self) -> None:
        def _second_unscored(**kwargs: object) -> dict:
            body = kwargs["body"]
            assert isinstance(body, dict)
            if body["state"]["finding"] == "finding 1":
                return {"answers": {}}
            return _answer(1)

        with patch("app.services.reranker.call_decision_model", side_effect=_second_unscored):
            with self.assertRaisesRegex(DecisionRerankError, "no relevance score for finding 1"):
                self._service().rerank("q", _docs(3))


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
        patch("app.services.reranker.record_llm_trace"),
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
        scorer = _scored_by_text({"vector 1": 1, "vector 2": 4})
        with (
            patch("app.services.reranker.call_decision_model", side_effect=scorer) as call,
            patch("app.services.reranker.create_reranker_service") as cohere,
        ):
            output, executor = _run(
                {}, credential=_decision_credential(), config=DECISION_CONFIG, trace_ids=["t-1"]
            )

        cohere.assert_not_called()
        # The reranker widens the candidate pool, so all 20 hits are scored, one each.
        self.assertEqual(call.call_count, 20)
        body = call.call_args.kwargs["body"]
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"]["query"], "how do I reset the VPN")
        self.assertEqual(call.call_args.kwargs["api_key"], "dm-key")
        executor._build_llm_trace_context.assert_called_once_with("cred-1", "rag_1")

        self.assertTrue(output["reranked"])
        self.assertEqual([r["id"] for r in output["results"]], ["v2", "v1"])
        self.assertEqual(output["results"][0]["relevance_score"], 1.0)
        self.assertEqual(output["results"][0]["score"], 0.5)
        self.assertEqual(output["count"], 2)
        self.assertEqual(output["_trace_id"], "t-1")

    def test_reranker_top_n_limits_the_results(self) -> None:
        with patch("app.services.reranker.call_decision_model", side_effect=_scored_by_text({}, 2)):
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
        with patch("app.services.reranker.call_decision_model", return_value={"answers": {}}):
            with self.assertRaisesRegex(ValueError, "Reranker failed: .*no relevance score"):
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
