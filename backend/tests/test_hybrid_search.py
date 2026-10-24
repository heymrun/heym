"""Hybrid search fuses vector hits with BM25 keyword hits, the same way on every backend."""

import unittest

from app.services.hybrid_search import (
    LEXICAL_CANDIDATE_LIMIT,
    LEXICAL_MATCH_BUDGET,
    MAX_POOL_SIZE,
    MAX_QUERY_TERMS,
    MIN_POOL_SIZE,
    RRF_K,
    bm25_scores,
    hybrid_pool_size,
    query_terms,
    reciprocal_rank_fusion,
    retrieval_terms,
    run_hybrid_search,
    tokenize,
)
from app.services.vector_store import HybridSearchResult, LexicalDoc, SearchResult


class FakeLexicalSource:
    """In-memory keyword leg that counts how it is called."""

    def __init__(self, docs: list[LexicalDoc]) -> None:
        self.docs = docs
        self.calls: list[str] = []
        self.candidate_args: dict = {}

    def corpus_size(self, collection_name: str) -> int:
        self.calls.append("corpus_size")
        return len(self.docs)

    def document_frequencies(self, collection_name: str, terms: list[str]) -> dict[str, int]:
        self.calls.append("document_frequencies")
        return {t: sum(1 for d in self.docs if t in tokenize(d.text)) for t in terms}

    def candidates(
        self,
        collection_name: str,
        terms: list[str],
        limit: int,
        metadata_filter: dict | None,
    ) -> list[LexicalDoc]:
        self.calls.append("candidates")
        self.candidate_args = {"terms": terms, "limit": limit, "filter": metadata_filter}
        return [d for d in self.docs if any(t in tokenize(d.text) for t in terms)][:limit]


def _doc(doc_id: str, text: str) -> LexicalDoc:
    return LexicalDoc(id=doc_id, text=text, metadata={"doc": doc_id})


def _dense(*pairs: tuple[str, str, float]) -> list[SearchResult]:
    return [SearchResult(id=i, text=t, score=s, metadata={"doc": i}) for i, t, s in pairs]


class TestTokenize(unittest.TestCase):
    def test_lowercases_and_splits_on_punctuation(self) -> None:
        self.assertEqual(
            tokenize("Error ERR-4021: Card rejected!"), ["error", "err", "4021", "card", "rejected"]
        )

    def test_underscore_separates_words(self) -> None:
        self.assertEqual(tokenize("snake_case"), ["snake", "case"])

    def test_keeps_non_ascii_letters(self) -> None:
        self.assertEqual(tokenize("Şükrü Çalışkan Straße"), ["şükrü", "çalışkan", "straße"])

    def test_empty_and_symbol_only_text_have_no_tokens(self) -> None:
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("??? --- !!!"), [])

    def test_query_terms_are_distinct_and_keep_order(self) -> None:
        self.assertEqual(
            query_terms("refund the refund of the order"), ["refund", "the", "of", "order"]
        )

    def test_query_terms_are_capped(self) -> None:
        query = " ".join(f"term{i}" for i in range(MAX_QUERY_TERMS + 10))
        self.assertEqual(len(query_terms(query)), MAX_QUERY_TERMS)
        self.assertEqual(query_terms(query)[0], "term0")


class TestPoolSize(unittest.TestCase):
    def test_small_limits_get_the_minimum_pool(self) -> None:
        self.assertEqual(hybrid_pool_size(3), MIN_POOL_SIZE)

    def test_pool_grows_with_the_limit(self) -> None:
        self.assertEqual(hybrid_pool_size(20), 60)

    def test_pool_is_capped(self) -> None:
        self.assertEqual(hybrid_pool_size(100), MAX_POOL_SIZE)

    def test_pool_never_drops_below_the_limit(self) -> None:
        self.assertEqual(hybrid_pool_size(500), 500)


class TestBm25(unittest.TestCase):
    def test_only_documents_with_a_query_term_are_scored(self) -> None:
        docs = [_doc("a", "refund policy"), _doc("b", "shipping times")]

        scores = bm25_scores(["refund"], docs, {"refund": 1}, corpus_size=10)

        self.assertEqual(list(scores), ["a"])
        self.assertGreater(scores["a"], 0.0)

    def test_rare_term_outweighs_common_term(self) -> None:
        docs = [_doc("rare", "alpha zeta"), _doc("common", "alpha beta")]
        doc_freq = {"zeta": 1, "beta": 900}

        scores = bm25_scores(["zeta", "beta"], docs, doc_freq, corpus_size=1000)

        self.assertGreater(scores["rare"], scores["common"])

    def test_term_frequency_saturates(self) -> None:
        docs = [_doc("one", "refund x y z"), _doc("many", "refund refund refund refund")]

        scores = bm25_scores(["refund"], docs, {"refund": 2}, corpus_size=100)

        self.assertGreater(scores["many"], scores["one"])
        self.assertLess(scores["many"], scores["one"] * 4)

    def test_shorter_document_wins_on_equal_term_frequency(self) -> None:
        docs = [_doc("short", "refund policy"), _doc("long", "refund " + "filler " * 40)]

        scores = bm25_scores(["refund"], docs, {"refund": 2}, corpus_size=100)

        self.assertGreater(scores["short"], scores["long"])

    def test_term_in_every_document_still_scores_positive(self) -> None:
        docs = [_doc("a", "refund"), _doc("b", "refund")]

        scores = bm25_scores(["refund"], docs, {"refund": 2}, corpus_size=2)

        self.assertGreater(scores["a"], 0.0)

    def test_observed_documents_raise_an_underreported_frequency(self) -> None:
        docs = [_doc("a", "refund"), _doc("b", "refund"), _doc("c", "refund")]

        undercounted = bm25_scores(["refund"], docs, {"refund": 0}, corpus_size=1000)
        counted = bm25_scores(["refund"], docs, {"refund": 3}, corpus_size=1000)

        self.assertAlmostEqual(undercounted["a"], counted["a"])

    def test_no_terms_or_no_documents_score_nothing(self) -> None:
        self.assertEqual(bm25_scores([], [_doc("a", "x")], {}, 1), {})
        self.assertEqual(bm25_scores(["x"], [], {}, 1), {})


class TestReciprocalRankFusion(unittest.TestCase):
    def test_first_in_every_list_scores_one(self) -> None:
        fused = reciprocal_rank_fusion([["a", "b"], ["a", "c"]])

        self.assertAlmostEqual(fused["a"], 1.0)

    def test_agreement_beats_a_single_list(self) -> None:
        fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d", "e"]])

        self.assertGreater(fused["b"], fused["a"])
        self.assertGreater(fused["b"], fused["d"])

    def test_single_list_hit_scores_below_one(self) -> None:
        fused = reciprocal_rank_fusion([["a"], []])

        self.assertAlmostEqual(fused["a"], 0.5)

    def test_rank_decays_with_position(self) -> None:
        fused = reciprocal_rank_fusion([["a", "b"], []])

        self.assertAlmostEqual(fused["b"] / fused["a"], (RRF_K + 1) / (RRF_K + 2))


class TestRetrievalTerms(unittest.TestCase):
    def test_terms_come_rarest_first(self) -> None:
        self.assertEqual(
            retrieval_terms(["common", "rare", "mid"], {"common": 300, "rare": 2, "mid": 40}),
            ["rare", "mid", "common"],
        )

    def test_terms_without_matches_are_dropped(self) -> None:
        self.assertEqual(retrieval_terms(["gone", "here"], {"gone": 0, "here": 3}), ["here"])

    def test_common_terms_beyond_the_budget_are_left_out(self) -> None:
        doc_freq = {"rare": 10, "common": LEXICAL_MATCH_BUDGET}

        self.assertEqual(retrieval_terms(["common", "rare"], doc_freq), ["rare"])

    def test_the_rarest_term_is_kept_even_over_budget(self) -> None:
        self.assertEqual(retrieval_terms(["huge"], {"huge": LEXICAL_MATCH_BUDGET * 10}), ["huge"])


class TestRunHybridSearch(unittest.TestCase):
    CORPUS = [
        _doc("refund", "How to request a refund for an order"),
        _doc("money", "Reimbursement policy money returns in five days"),
        _doc("code", "Error ERR-4021 means the payment gateway rejected the card"),
        _doc("other", "Our office dog is called Biscuit"),
    ]

    def test_exact_term_missed_by_vectors_is_surfaced_by_keywords(self) -> None:
        source = FakeLexicalSource(self.CORPUS)
        dense = _dense(("refund", self.CORPUS[0].text, 0.5), ("money", self.CORPUS[1].text, 0.4))

        results = run_hybrid_search(source, "col", "ERR-4021", dense, limit=3)

        by_id = {r.id: r for r in results}
        self.assertIn("code", by_id)
        self.assertIsNone(by_id["code"].vector_score)
        self.assertGreater(by_id["code"].keyword_score, 0.0)

    def test_document_both_legs_rank_high_comes_first(self) -> None:
        corpus = [
            _doc("x", "unrelated words only"),
            _doc("y", "refund refund policy"),
            _doc("z", "refund policy for a long order with many extra words"),
        ]
        source = FakeLexicalSource(corpus)
        dense = _dense(
            ("x", corpus[0].text, 0.9), ("y", corpus[1].text, 0.8), ("z", corpus[2].text, 0.7)
        )

        results = run_hybrid_search(source, "col", "refund", dense, limit=3)

        self.assertEqual([r.id for r in results], ["y", "z", "x"])
        self.assertAlmostEqual(results[0].vector_score, 0.8)
        self.assertGreater(results[0].keyword_score, results[1].keyword_score)
        self.assertIsNone(results[2].keyword_score)

    def test_vector_only_hit_is_kept_with_no_keyword_score(self) -> None:
        source = FakeLexicalSource(self.CORPUS)
        dense = _dense(("money", self.CORPUS[1].text, 0.9))

        results = run_hybrid_search(source, "col", "ERR-4021", dense, limit=5)

        by_id = {r.id: r for r in results}
        self.assertIsNone(by_id["money"].keyword_score)
        self.assertAlmostEqual(by_id["money"].vector_score, 0.9)

    def test_dense_hit_earns_a_keyword_rank_the_lookup_missed(self) -> None:
        source = FakeLexicalSource([])
        source.corpus_size = lambda _c: 50
        source.document_frequencies = lambda _c, terms: {t: 5 for t in terms}
        source.candidates = lambda *_a: []
        dense = _dense(("refund", self.CORPUS[0].text, 0.7))

        results = run_hybrid_search(source, "col", "refund", dense, limit=5)

        self.assertGreater(results[0].keyword_score, 0.0)

    def test_results_are_limited_and_scores_are_between_zero_and_one(self) -> None:
        source = FakeLexicalSource(self.CORPUS)
        dense = _dense(*((d.id, d.text, 0.5) for d in self.CORPUS))

        results = run_hybrid_search(source, "col", "refund error biscuit", dense, limit=2)

        self.assertEqual(len(results), 2)
        for result in results:
            self.assertIsInstance(result, HybridSearchResult)
            self.assertTrue(0.0 < result.score <= 1.0)
        self.assertGreaterEqual(results[0].score, results[1].score)

    def test_metadata_filter_and_budget_reach_the_keyword_lookup(self) -> None:
        source = FakeLexicalSource(self.CORPUS)

        run_hybrid_search(source, "col", "refund", [], limit=3, metadata_filter={"team": "a"})

        self.assertEqual(source.candidate_args["filter"], {"team": "a"})
        self.assertEqual(source.candidate_args["limit"], LEXICAL_CANDIDATE_LIMIT)
        self.assertEqual(source.candidate_args["terms"], ["refund"])

    def test_candidate_metadata_is_preserved(self) -> None:
        source = FakeLexicalSource(self.CORPUS)

        results = run_hybrid_search(source, "col", "Biscuit", [], limit=3)

        self.assertEqual(results[0].metadata, {"doc": "other"})

    def test_query_without_terms_skips_the_keyword_leg(self) -> None:
        source = FakeLexicalSource(self.CORPUS)
        dense = _dense(("refund", self.CORPUS[0].text, 0.5), ("money", self.CORPUS[1].text, 0.4))

        results = run_hybrid_search(source, "col", "???", dense, limit=5)

        self.assertEqual(source.calls, [])
        self.assertEqual([r.id for r in results], ["refund", "money"])
        self.assertTrue(all(r.keyword_score is None for r in results))

    def test_empty_collection_skips_frequency_and_candidate_lookups(self) -> None:
        source = FakeLexicalSource([])

        results = run_hybrid_search(source, "col", "refund", [], limit=5)

        self.assertEqual(source.calls, ["corpus_size"])
        self.assertEqual(results, [])

    def test_terms_nobody_contains_skip_the_candidate_lookup(self) -> None:
        source = FakeLexicalSource(self.CORPUS)

        run_hybrid_search(source, "col", "zzzz", [], limit=5)

        self.assertEqual(source.calls, ["corpus_size", "document_frequencies"])

    def test_non_positive_limit_returns_nothing_without_touching_the_store(self) -> None:
        source = FakeLexicalSource(self.CORPUS)

        self.assertEqual(run_hybrid_search(source, "col", "refund", [], limit=0), [])
        self.assertEqual(run_hybrid_search(source, "col", "refund", [], limit=-3), [])
        self.assertEqual(source.calls, [])


if __name__ == "__main__":
    unittest.main()
