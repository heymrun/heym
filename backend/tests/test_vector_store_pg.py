import unittest
from unittest.mock import MagicMock, patch

from app.services.vector_store import SearchResult


class TestPgVectorStoreService(unittest.TestCase):
    def _service(self, embed_return=None):
        with patch("app.services.vector_store_pg.EmbeddingService") as emb_cls:
            emb = emb_cls.return_value
            emb.embed_text.return_value = embed_return or [0.0] * 1536
            from app.services.vector_store_pg import PgVectorStoreService

            engine = MagicMock()
            svc = PgVectorStoreService("sk-test", engine=engine)
            return svc, engine, emb

    def test_search_builds_results_and_score(self):
        svc, engine, emb = self._service()
        conn = engine.connect.return_value.__enter__.return_value
        row = MagicMock()
        row.id = "11111111-1111-1111-1111-111111111111"
        row.text = "hello"
        row.distance = 0.25  # cosine distance -> score 0.75
        row.metadata = {"source": "a.txt", "file_size": 10}
        conn.execute.return_value.fetchall.return_value = [row]

        results = svc.search("col1", "query", limit=3)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], SearchResult)
        self.assertEqual(results[0].text, "hello")
        self.assertAlmostEqual(results[0].score, 0.75, places=5)
        self.assertEqual(results[0].metadata.get("source"), "a.txt")

    def test_insert_returns_point_id(self):
        svc, engine, emb = self._service()
        pid = svc.insert("col1", "doc text", {"source": "a.txt"})
        self.assertTrue(pid)
        engine.begin.assert_called()  # write used a transaction

    def test_collection_exists_is_true(self):
        svc, engine, emb = self._service()
        self.assertTrue(svc.collection_exists("anything"))

    def test_delete_point_casts_uuid_column_to_text(self):
        # Guards against "operator does not exist: uuid = text": the id column is
        # UUID but point ids arrive as strings, so the comparison must cast.
        svc, engine, emb = self._service()
        svc.delete_point("col", "d54a25df-f73d-4397-9925-55d39334116d")
        conn = engine.begin.return_value.__enter__.return_value
        sql = str(conn.execute.call_args.args[0])
        self.assertIn("id::text = ANY", sql)


class TestPgVectorBackendUnavailable(unittest.TestCase):
    def _service_without_table(self):
        with patch("app.services.vector_store_pg.EmbeddingService") as emb_cls:
            emb_cls.return_value.embed_text.return_value = [0.0] * 1536
            from app.services.vector_store_pg import PgVectorStoreService

            engine = MagicMock()
            # _table_exists() -> to_regclass IS NOT NULL -> False (table missing)
            conn = engine.connect.return_value.__enter__.return_value
            conn.exec_driver_sql.return_value.scalar.return_value = False
            return PgVectorStoreService("sk-test", engine=engine)

    def test_create_collection_raises_clear_error(self):
        from app.services.vector_store_pg import VectorStoreBackendUnavailableError

        svc = self._service_without_table()
        with self.assertRaises(VectorStoreBackendUnavailableError):
            svc.create_collection("col")

    def test_insert_and_search_raise_clear_error(self):
        from app.services.vector_store_pg import VectorStoreBackendUnavailableError

        svc = self._service_without_table()
        with self.assertRaises(VectorStoreBackendUnavailableError):
            svc.insert("col", "text")
        with self.assertRaises(VectorStoreBackendUnavailableError):
            svc.search("col", "query")

    def test_reads_degrade_gracefully(self):
        svc = self._service_without_table()
        self.assertIsNone(svc.get_collection_stats("col"))
        self.assertEqual(svc.list_items("col"), ([], 0))
        self.assertEqual(svc.find_existing_files("col", [("a.txt", 1)]), [])
        self.assertFalse(svc.collection_exists("col"))


if __name__ == "__main__":
    unittest.main()
