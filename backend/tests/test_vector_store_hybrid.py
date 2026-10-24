"""Hybrid search on the Qdrant and pgvector backends, with the stores mocked."""

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from qdrant_client.http.models import MatchText, MatchValue, TextIndexParams, TokenizerType

from app.services.hybrid_search import LEXICAL_CANDIDATE_LIMIT, MIN_POOL_SIZE
from app.services.vector_store import HybridSearchResult, QdrantLexicalSource, SearchResult
from app.services.vector_store_pg import TEXT_SEARCH_SQL, PgLexicalSource

ALEMBIC_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _point(point_id: str, payload: dict) -> MagicMock:
    point = MagicMock()
    point.id = point_id
    point.payload = payload
    return point


def _qdrant_service() -> tuple[object, MagicMock]:
    with (
        patch("app.services.vector_store.QdrantClient") as client_cls,
        patch("app.services.vector_store.EmbeddingService") as emb_cls,
    ):
        emb_cls.return_value.embed_text.return_value = [0.0] * 1536
        from app.services.vector_store import QdrantVectorStoreService

        return QdrantVectorStoreService("localhost", 6333, None, "sk-test"), client_cls.return_value


def _conditions(query_filter: object) -> dict:
    """Filter conditions keyed by payload field."""
    return {c.key: c.match for c in query_filter.must}


class TestQdrantTextIndex(unittest.TestCase):
    def test_missing_index_is_created_as_a_word_index_on_text(self) -> None:
        client = MagicMock()
        client.get_collection.return_value.payload_schema = {}

        QdrantLexicalSource(client).ensure_text_index("col1")

        kwargs = client.create_payload_index.call_args.kwargs
        self.assertEqual(kwargs["collection_name"], "col1")
        self.assertEqual(kwargs["field_name"], "text")
        self.assertTrue(kwargs["wait"])
        params = kwargs["field_schema"]
        self.assertIsInstance(params, TextIndexParams)
        self.assertEqual(params.tokenizer, TokenizerType.WORD)
        self.assertTrue(params.lowercase)

    def test_existing_index_is_left_alone(self) -> None:
        client = MagicMock()
        client.get_collection.return_value.payload_schema = {"text": MagicMock()}

        QdrantLexicalSource(client).ensure_text_index("col1")

        client.create_payload_index.assert_not_called()

    def test_a_failed_index_build_does_not_fail_the_search(self) -> None:
        client = MagicMock()
        client.get_collection.return_value.payload_schema = None
        client.create_payload_index.side_effect = RuntimeError("timed out")

        with self.assertLogs("app.services.vector_store", level="WARNING"):
            QdrantLexicalSource(client).ensure_text_index("col1")


class TestQdrantLexicalSource(unittest.TestCase):
    def test_corpus_size_is_the_exact_point_count(self) -> None:
        client = MagicMock()
        client.count.return_value.count = 42

        self.assertEqual(QdrantLexicalSource(client).corpus_size("col1"), 42)
        self.assertTrue(client.count.call_args.kwargs["exact"])

    def test_document_frequency_counts_each_term_as_a_text_match(self) -> None:
        client = MagicMock()
        client.count.side_effect = lambda **kw: MagicMock(
            count={"refund": 7, "order": 90}[kw["count_filter"].must[0].match.text]
        )

        frequencies = QdrantLexicalSource(client).document_frequencies("col1", ["refund", "order"])

        self.assertEqual(frequencies, {"refund": 7, "order": 90})
        for call in client.count.call_args_list:
            condition = call.kwargs["count_filter"].must[0]
            self.assertEqual(condition.key, "text")
            self.assertIsInstance(condition.match, MatchText)

    def test_candidates_scroll_the_rarest_term_first_and_split_text_from_metadata(self) -> None:
        client = MagicMock()
        client.scroll.return_value = (
            [_point("p1", {"text": "refund rules", "category": "faq"})],
            None,
        )

        found = QdrantLexicalSource(client).candidates("col1", ["rare", "common"], 10, None)

        first = client.scroll.call_args_list[0].kwargs["scroll_filter"]
        self.assertEqual(first.must[0].match.text, "rare")
        self.assertFalse(client.scroll.call_args_list[0].kwargs["with_vectors"])
        self.assertEqual(found[0].text, "refund rules")
        self.assertEqual(found[0].metadata, {"category": "faq"})

    def test_candidates_apply_the_metadata_filter_to_every_lookup(self) -> None:
        client = MagicMock()
        client.scroll.return_value = ([], None)

        QdrantLexicalSource(client).candidates("col1", ["a", "b"], 10, {"category": "faq"})

        for call in client.scroll.call_args_list:
            conditions = _conditions(call.kwargs["scroll_filter"])
            self.assertEqual(conditions["category"], MatchValue(value="faq"))
            self.assertIsInstance(conditions["text"], MatchText)

    def test_candidates_dedupe_documents_matching_several_terms(self) -> None:
        client = MagicMock()
        client.scroll.return_value = ([_point("p1", {"text": "both terms"})], None)

        found = QdrantLexicalSource(client).candidates("col1", ["a", "b"], 10, None)

        self.assertEqual([doc.id for doc in found], ["p1"])

    def test_candidates_stop_once_the_budget_is_filled(self) -> None:
        client = MagicMock()
        client.scroll.return_value = (
            [_point(f"p{i}", {"text": "x"}) for i in range(3)],
            None,
        )

        found = QdrantLexicalSource(client).candidates("col1", ["a", "b", "c"], 3, None)

        self.assertEqual(client.scroll.call_count, 1)
        self.assertEqual(len(found), 3)


class TestQdrantHybridSearch(unittest.TestCase):
    def test_hybrid_search_indexes_text_fetches_a_larger_dense_pool_and_fuses(self) -> None:
        svc, client = _qdrant_service()
        client.get_collection.return_value.payload_schema = {"text": MagicMock()}
        client.count.return_value.count = 10
        client.scroll.return_value = ([], None)
        svc.search = MagicMock(
            return_value=[SearchResult(id="p1", text="refund rules", score=0.8, metadata={})]
        )

        results = svc.hybrid_search("col1", "refund", limit=3, metadata_filter={"team": "a"})

        self.assertEqual(svc.search.call_args.kwargs["limit"], MIN_POOL_SIZE)
        self.assertEqual(svc.search.call_args.kwargs["metadata_filter"], {"team": "a"})
        self.assertEqual(client.scroll.call_args.kwargs["limit"], LEXICAL_CANDIDATE_LIMIT)
        self.assertIsInstance(results[0], HybridSearchResult)
        self.assertEqual(results[0].id, "p1")
        self.assertAlmostEqual(results[0].vector_score, 0.8)
        self.assertGreater(results[0].keyword_score, 0.0)

    def test_hybrid_search_surfaces_a_keyword_only_document(self) -> None:
        svc, client = _qdrant_service()
        client.get_collection.return_value.payload_schema = {"text": MagicMock()}
        client.count.return_value.count = 5
        client.scroll.return_value = (
            [_point("code", {"text": "Error ERR-4021 payment rejected", "kind": "errors"})],
            None,
        )
        svc.search = MagicMock(return_value=[])

        results = svc.hybrid_search("col1", "ERR-4021", limit=3)

        self.assertEqual([r.id for r in results], ["code"])
        self.assertIsNone(results[0].vector_score)
        self.assertEqual(results[0].metadata, {"kind": "errors"})

    def test_search_keeps_building_exact_match_filters(self) -> None:
        svc, client = _qdrant_service()
        client.query_points.return_value.points = []

        svc.search("col1", "q", limit=2, metadata_filter={"category": "faq", "n": 3})
        svc.search("col1", "q", limit=2)

        filtered, unfiltered = client.query_points.call_args_list
        conditions = _conditions(filtered.kwargs["query_filter"])
        self.assertEqual(conditions["category"], MatchValue(value="faq"))
        self.assertEqual(conditions["n"], MatchValue(value=3))
        self.assertIsNone(unfiltered.kwargs["query_filter"])


def _pg_service() -> tuple[object, MagicMock]:
    with patch("app.services.vector_store_pg.EmbeddingService") as emb_cls:
        emb_cls.return_value.embed_text.return_value = [0.0] * 1536
        from app.services.vector_store_pg import PgVectorStoreService

        engine = MagicMock()
        return PgVectorStoreService("sk-test", engine=engine), engine


def _executed_sql(engine: MagicMock) -> tuple[str, dict]:
    conn = engine.connect.return_value.__enter__.return_value
    args = conn.execute.call_args.args
    return str(args[0]), args[1]


class TestPgLexicalSource(unittest.TestCase):
    def test_corpus_size_counts_the_collection(self) -> None:
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value.execute.return_value.scalar.return_value = 9

        self.assertEqual(PgLexicalSource(engine).corpus_size("col1"), 9)
        sql, params = _executed_sql(engine)
        self.assertIn("collection_name = :c", sql)
        self.assertEqual(params, {"c": "col1"})

    def test_document_frequencies_run_one_query_on_the_indexed_expression(self) -> None:
        engine = MagicMock()
        rows = [MagicMock(term="refund", df=3), MagicMock(term="order", df=40)]
        engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = rows

        frequencies = PgLexicalSource(engine).document_frequencies("col1", ["refund", "order"])

        self.assertEqual(frequencies, {"refund": 3, "order": 40})
        sql, params = _executed_sql(engine)
        self.assertIn(TEXT_SEARCH_SQL, sql)
        self.assertIn("plainto_tsquery('simple', t.term)", sql)
        self.assertEqual(params, {"c": "col1", "terms": ["refund", "order"]})
        self.assertEqual(engine.connect.return_value.__enter__.return_value.execute.call_count, 1)

    def test_candidates_or_the_terms_and_rank_them_in_sql(self) -> None:
        engine = MagicMock()
        row = MagicMock(id="11111111-1111-1111-1111-111111111111", text="refund", metadata={"a": 1})
        engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [
            row
        ]

        found = PgLexicalSource(engine).candidates("col1", ["rare", "common"], 50, None)

        sql, params = _executed_sql(engine)
        self.assertIn("plainto_tsquery('simple', :t0) || plainto_tsquery('simple', :t1)", sql)
        self.assertIn("ts_rank_cd", sql)
        self.assertIn("LIMIT :k", sql)
        self.assertNotIn("metadata @>", sql)
        self.assertEqual(params, {"c": "col1", "k": 50, "t0": "rare", "t1": "common"})
        self.assertEqual(found[0].id, "11111111-1111-1111-1111-111111111111")
        self.assertEqual(found[0].metadata, {"a": 1})

    def test_candidates_apply_the_metadata_filter(self) -> None:
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []

        PgLexicalSource(engine).candidates("col1", ["rare"], 50, {"category": "faq"})

        sql, params = _executed_sql(engine)
        self.assertIn("metadata @> (:mf)::jsonb", sql)
        self.assertEqual(params["mf"], '{"category": "faq"}')

    def test_candidate_terms_are_bound_not_interpolated(self) -> None:
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []

        PgLexicalSource(engine).candidates("col1", ["x'); DROP TABLE t;--"], 5, None)

        sql, params = _executed_sql(engine)
        self.assertNotIn("DROP", sql)
        self.assertEqual(params["t0"], "x'); DROP TABLE t;--")


class TestPgHybridSearch(unittest.TestCase):
    def test_hybrid_search_fuses_dense_and_keyword_hits(self) -> None:
        svc, engine = _pg_service()
        conn = engine.connect.return_value.__enter__.return_value
        dense_row = MagicMock(
            id="11111111-1111-1111-1111-111111111111",
            text="refund rules",
            distance=0.2,
            metadata={"source": "a.txt"},
        )
        keyword_row = MagicMock(
            id="22222222-2222-2222-2222-222222222222",
            text="Error ERR-4021 refund rejected",
            metadata={},
        )
        df_rows = [MagicMock(term="refund", df=2)]

        def execute(statement, params=None):
            sql = str(statement)
            result = MagicMock()
            if "to_regclass" in sql:
                result.scalar.return_value = True
            elif "COUNT(*) FROM" in sql and "unnest" not in sql:
                result.scalar.return_value = 20
            elif "unnest" in sql:
                result.fetchall.return_value = df_rows
            elif "ts_rank_cd" in sql:
                result.fetchall.return_value = [keyword_row]
            else:
                result.fetchall.return_value = [dense_row]
            return result

        conn.execute.side_effect = execute
        conn.exec_driver_sql.return_value.scalar.return_value = True

        results = svc.hybrid_search("col1", "refund", limit=2)

        self.assertEqual({r.id for r in results}, {dense_row.id, keyword_row.id})
        by_id = {r.id: r for r in results}
        self.assertAlmostEqual(by_id[dense_row.id].vector_score, 0.8)
        self.assertIsNone(by_id[keyword_row.id].vector_score)
        self.assertTrue(all(r.keyword_score and r.keyword_score > 0 for r in results))


class TestPgTextSearchIndexMigration(unittest.TestCase):
    def test_migration_indexes_the_expression_hybrid_search_queries(self) -> None:
        migration = (ALEMBIC_VERSIONS / "142_add_vector_store_text_search_index.py").read_text()

        indexed = re.search(r"USING gin \((.+?)\);", migration, re.DOTALL)

        self.assertIsNotNone(indexed)
        self.assertEqual(indexed.group(1).strip(), TEXT_SEARCH_SQL)

    def test_migration_is_skipped_where_the_pgvector_table_is_missing(self) -> None:
        migration = (ALEMBIC_VERSIONS / "142_add_vector_store_text_search_index.py").read_text()

        self.assertIn("to_regclass('public.vector_store_items') IS NOT NULL", migration)


if __name__ == "__main__":
    unittest.main()
