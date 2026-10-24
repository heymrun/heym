"""Hybrid search against a real Postgres with pgvector; skipped where the table is absent."""

import hashlib
import unittest
import uuid

from sqlalchemy import text

from app.db.session import sync_engine
from app.services.embedding import EMBEDDING_DIMENSIONS, EmbeddingConfig
from app.services.vector_store_pg import PgLexicalSource, PgVectorStoreService


def _embed(value: str) -> list[float]:
    """Deterministic pseudo-embedding: similar to nothing, so only keywords can find a code."""
    seed = hashlib.sha256(value.encode()).digest()
    return [seed[i % len(seed)] / 255.0 + 0.01 for i in range(EMBEDDING_DIMENSIONS)]


class PgHybridSearchPostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            with sync_engine.connect() as conn:
                has_table = conn.exec_driver_sql(
                    "SELECT to_regclass('public.vector_store_items') IS NOT NULL"
                ).scalar()
        except Exception:
            self.skipTest("PostgreSQL database is not reachable")
        if not has_table:
            self.skipTest("pgvector table vector_store_items is not provisioned")

        self.collection = f"hybrid-{uuid.uuid4()}"
        self.service = PgVectorStoreService(
            engine=sync_engine, embedding_config=EmbeddingConfig(api_key="unused")
        )
        self.service.embedding_service.embed_text = _embed
        self.addCleanup(self._drop_collection)

        for doc_id, body, category in [
            ("refund", "How to request a refund for an order you no longer want", "faq"),
            ("money", "Reimbursement policy: money returns within five working days", "faq"),
            ("code", "Error ERR-4021 means the payment gateway rejected the card", "errors"),
            ("other", "Error ERR-5090 means the warehouse API timed out", "errors"),
            ("dog", "Our office dog is called Biscuit and loves Fridays", "misc"),
        ]:
            self.service.insert(self.collection, body, {"doc_id": doc_id, "category": category})

    def _drop_collection(self) -> None:
        with sync_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM vector_store_items WHERE collection_name = :c"),
                {"c": self.collection},
            )

    def test_keyword_leg_finds_the_document_holding_an_exact_code(self) -> None:
        results = self.service.hybrid_search(self.collection, "ERR-4021", limit=5)

        by_doc = {r.metadata["doc_id"]: r for r in results}
        self.assertGreater(by_doc["code"].keyword_score, by_doc["other"].keyword_score)
        self.assertIsNone(by_doc["dog"].keyword_score)
        self.assertTrue(all(r.vector_score is not None for r in results))

    def test_rarer_term_ranks_its_document_higher(self) -> None:
        results = self.service.hybrid_search(self.collection, "error 4021", limit=5)

        by_doc = {r.metadata["doc_id"]: r for r in results}
        self.assertGreater(by_doc["code"].keyword_score, by_doc["other"].keyword_score)

    def test_metadata_filter_limits_both_legs(self) -> None:
        results = self.service.hybrid_search(
            self.collection, "ERR-4021", limit=5, metadata_filter={"category": "faq"}
        )

        self.assertEqual({r.metadata["category"] for r in results}, {"faq"})
        self.assertTrue(all(r.keyword_score is None for r in results))

    def test_lexical_source_counts_and_matches_whole_words(self) -> None:
        source = PgLexicalSource(sync_engine)

        self.assertEqual(source.corpus_size(self.collection), 5)
        frequencies = source.document_frequencies(
            self.collection, ["error", "4021", "biscuit", "nothing"]
        )
        self.assertEqual(frequencies, {"error": 2, "4021": 1, "biscuit": 1, "nothing": 0})

    def test_lexical_candidates_are_ranked_and_filtered_in_sql(self) -> None:
        source = PgLexicalSource(sync_engine)

        found = source.candidates(self.collection, ["4021", "error"], 10, None)
        self.assertEqual({d.metadata["doc_id"] for d in found}, {"code", "other"})
        self.assertEqual(found[0].metadata["doc_id"], "code")

        filtered = source.candidates(self.collection, ["error"], 10, {"doc_id": "other"})
        self.assertEqual([d.metadata["doc_id"] for d in filtered], ["other"])

    def test_other_collections_are_never_searched(self) -> None:
        results = self.service.hybrid_search(f"{self.collection}-missing", "ERR-4021", limit=5)

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
