"""Points written without a `source` stay one addressable group, on both backends."""

import unittest
from unittest.mock import MagicMock, patch


def _qdrant_service():
    with (
        patch("app.services.vector_store.QdrantClient") as client_cls,
        patch("app.services.vector_store.EmbeddingService") as emb_cls,
    ):
        emb_cls.return_value.embed_text.return_value = [0.0] * 1536
        from app.services.vector_store import QdrantVectorStoreService

        svc = QdrantVectorStoreService("localhost", 6333, None, "sk-test")
        client = client_cls.return_value
        collections = MagicMock()
        collection = MagicMock()
        collection.name = "col1"
        collections.collections = [collection]
        client.get_collections.return_value = collections
        return svc, client


def _point(point_id: str, payload: dict) -> MagicMock:
    point = MagicMock()
    point.id = point_id
    point.payload = payload
    return point


class TestQdrantSourceGrouping(unittest.TestCase):
    def test_a_point_without_a_source_is_not_labelled_unknown(self) -> None:
        svc, client = _qdrant_service()
        client.scroll.return_value = ([_point("p1", {"text": "Thanks"})], None)

        groups, total = svc.list_items("col1")

        self.assertEqual(total, 1)
        self.assertEqual([group.source for group in groups], [""])
        self.assertEqual(groups[0].chunk_count, 1)

    def test_uploaded_points_keep_their_filename_group(self) -> None:
        svc, client = _qdrant_service()
        client.scroll.return_value = (
            [
                _point("p1", {"text": "a", "source": "guide.pdf"}),
                _point("p2", {"text": "b"}),
            ],
            None,
        )

        groups, _ = svc.list_items("col1")

        self.assertEqual(sorted(group.source for group in groups), ["", "guide.pdf"])

    def test_deleting_the_sourceless_group_matches_an_absent_field(self) -> None:
        # Matching source == "" would delete nothing: the field is absent, not blank.
        from qdrant_client.http.models import IsEmptyCondition

        svc, client = _qdrant_service()

        svc.delete_by_source("col1", "")

        selector = client.delete.call_args.kwargs["points_selector"]
        self.assertIsInstance(selector.filter.must[0], IsEmptyCondition)
        self.assertEqual(selector.filter.must[0].is_empty.key, "source")

    def test_deleting_a_named_source_still_matches_on_value(self) -> None:
        from qdrant_client.http.models import FieldCondition

        svc, client = _qdrant_service()

        svc.delete_by_source("col1", "guide.pdf")

        selector = client.delete.call_args.kwargs["points_selector"]
        self.assertIsInstance(selector.filter.must[0], FieldCondition)
        self.assertEqual(selector.filter.must[0].match.value, "guide.pdf")
        self.assertIsNone(selector.filter.must_not)

    def test_a_replacement_just_written_is_kept(self) -> None:
        from qdrant_client.http.models import HasIdCondition

        svc, client = _qdrant_service()

        svc.delete_by_source("col1", "guide.pdf", ["new-1", "new-2"])

        selector = client.delete.call_args.kwargs["points_selector"]
        self.assertEqual(selector.filter.must[0].match.value, "guide.pdf")
        self.assertIsInstance(selector.filter.must_not[0], HasIdCondition)
        self.assertEqual(selector.filter.must_not[0].has_id, ["new-1", "new-2"])


class TestPgVectorSourceGrouping(unittest.TestCase):
    def _service(self):
        with patch("app.services.vector_store_pg.EmbeddingService") as emb_cls:
            emb_cls.return_value.embed_text.return_value = [0.0] * 1536
            from app.services.vector_store_pg import PgVectorStoreService

            engine = MagicMock()
            return PgVectorStoreService("sk-test", engine=engine), engine

    def test_a_null_source_is_not_labelled_unknown(self) -> None:
        svc, engine = self._service()
        row = MagicMock()
        row.id = "11111111-1111-1111-1111-111111111111"
        row.text = "Thanks"
        row.metadata = {}
        row.source = None
        row.file_size = None
        engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = [
            row
        ]

        groups, total = svc.list_items("col1")

        self.assertEqual(total, 1)
        self.assertEqual([group.source for group in groups], [""])

    def test_deleting_the_sourceless_group_targets_null_rows(self) -> None:
        svc, engine = self._service()

        svc.delete_by_source("col1", "")

        conn = engine.begin.return_value.__enter__.return_value
        sql = str(conn.execute.call_args.args[0])
        self.assertIn("source IS NULL", sql)
        self.assertNotIn(":s", sql)
        self.assertEqual(conn.execute.call_args.args[1], {"c": "col1"})

    def test_deleting_a_named_source_still_binds_the_value(self) -> None:
        svc, engine = self._service()

        svc.delete_by_source("col1", "guide.pdf")

        conn = engine.begin.return_value.__enter__.return_value
        sql = str(conn.execute.call_args.args[0])
        self.assertIn("source = :s", sql)
        self.assertEqual(conn.execute.call_args.args[1], {"c": "col1", "s": "guide.pdf"})
        self.assertNotIn(":keep", sql)

    def test_a_replacement_just_written_is_kept(self) -> None:
        svc, engine = self._service()

        svc.delete_by_source("col1", "guide.pdf", ["11111111-1111-1111-1111-111111111111"])

        conn = engine.begin.return_value.__enter__.return_value
        sql = str(conn.execute.call_args.args[0])
        self.assertIn("AND NOT (id::text = ANY(:keep))", sql)
        self.assertEqual(
            conn.execute.call_args.args[1]["keep"], ["11111111-1111-1111-1111-111111111111"]
        )


if __name__ == "__main__":
    unittest.main()
