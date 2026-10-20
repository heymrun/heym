"""RAG node upsert/delete by a payload id field, across both vector backends."""

import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import rag_node
from app.services.vector_store import upsert_point_id


def _context(node_data: dict, service: MagicMock) -> NodeExecutionContext:
    executor = MagicMock()
    store = MagicMock()
    store.collection_name = "col1"
    store.credential_id = "cred-1"
    executor._get_accessible_vector_store.return_value = store
    cred = MagicMock()
    cred.type = "rag"
    executor._get_vector_store_backing_credential.return_value = cred
    executor.evaluate_message_template.side_effect = lambda template, inputs, node_id=None: str(
        template
    ).replace("$input.id", "doc-42")
    # Metadata resolution is covered on a real executor in
    # test_rag_node_metadata_expressions.py; here it must simply pass values through.
    executor._is_single_dollar_expression.return_value = False
    executor._unwrap_value.side_effect = lambda value: value
    return NodeExecutionContext(
        executor=executor,
        node_id="rag_1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type="rag",
        node_data={"vectorStoreId": "vs-1", **node_data},
        node_label="rag",
    )


def _run(node_data: dict, service: MagicMock) -> dict:
    ctx = _context(node_data, service)
    with (
        patch("app.db.session.SessionLocal", MagicMock()),
        patch("app.services.encryption.decrypt_config", return_value={"db_type": "qdrant"}),
        patch(
            "app.services.vector_store.create_vector_store_service_for_credential",
            return_value=service,
        ),
    ):
        return rag_node.execute(ctx)


class TestRagNodeUpsertOperation(unittest.TestCase):
    def test_upsert_passes_id_field_and_metadata_to_backend(self) -> None:
        service = MagicMock()
        service.upsert_by_field.return_value = ("point-1", 2)

        output = _run(
            {
                "ragOperation": "upsert",
                "documentIdField": "sku",
                "documentId": "$input.id",
                "documentContent": "hello world",
                "documentMetadata": '{"source": "catalog"}',
            },
            service,
        )

        service.upsert_by_field.assert_called_once_with(
            "col1", "sku", "doc-42", "hello world", {"source": "catalog"}
        )
        self.assertEqual(output["operation"], "upsert")
        self.assertEqual(output["point_id"], "point-1")
        self.assertEqual(output["document_id"], "doc-42")
        self.assertEqual(output["id_field"], "sku")
        self.assertTrue(output["replaced"])
        self.assertEqual(output["replaced_count"], 2)

    def test_upsert_of_a_new_document_reports_nothing_replaced(self) -> None:
        service = MagicMock()
        service.upsert_by_field.return_value = ("point-1", 0)

        output = _run(
            {
                "ragOperation": "upsert",
                "documentId": "doc-1",
                "documentContent": "text",
            },
            service,
        )

        self.assertFalse(output["replaced"])
        self.assertEqual(output["replaced_count"], 0)

    def test_upsert_defaults_the_id_field(self) -> None:
        service = MagicMock()
        service.upsert_by_field.return_value = ("point-1", 0)

        output = _run(
            {"ragOperation": "upsert", "documentId": "doc-1", "documentContent": "t"},
            service,
        )

        self.assertEqual(output["id_field"], "doc_id")
        self.assertEqual(service.upsert_by_field.call_args.args[1], "doc_id")

    def test_upsert_without_document_id_is_rejected(self) -> None:
        service = MagicMock()

        with self.assertRaises(ValueError):
            _run({"ragOperation": "upsert", "documentContent": "t"}, service)
        service.upsert_by_field.assert_not_called()


class TestRagNodeDeleteOperation(unittest.TestCase):
    def test_delete_returns_true_when_a_document_matched(self) -> None:
        service = MagicMock()
        service.delete_by_field.return_value = 3

        output = _run(
            {"ragOperation": "delete", "documentIdField": "sku", "documentId": "$input.id"},
            service,
        )

        service.delete_by_field.assert_called_once_with("col1", "sku", "doc-42")
        self.assertEqual(output["operation"], "delete")
        self.assertTrue(output["deleted"])
        self.assertEqual(output["deleted_count"], 3)
        self.assertEqual(output["document_id"], "doc-42")

    def test_delete_returns_false_when_nothing_matched(self) -> None:
        service = MagicMock()
        service.delete_by_field.return_value = 0

        output = _run({"ragOperation": "delete", "documentId": "doc-9"}, service)

        self.assertTrue(output["success"])
        self.assertFalse(output["deleted"])
        self.assertEqual(output["deleted_count"], 0)

    def test_delete_without_document_id_is_rejected(self) -> None:
        service = MagicMock()

        with self.assertRaises(ValueError):
            _run({"ragOperation": "delete"}, service)
        service.delete_by_field.assert_not_called()

    def test_unknown_operation_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            _run({"ragOperation": "purge"}, MagicMock())


class TestQdrantUpsertAndDeleteByField(unittest.TestCase):
    def _service(self):
        with (
            patch("app.services.vector_store.QdrantClient") as client_cls,
            patch("app.services.vector_store.EmbeddingService") as emb_cls,
        ):
            emb_cls.return_value.embed_text.return_value = [0.0] * 1536
            from app.services.vector_store import QdrantVectorStoreService

            svc = QdrantVectorStoreService("localhost", 6333, None, "sk-test")
            client = client_cls.return_value
            collections = MagicMock()
            collections.collections = [MagicMock(name="col")]
            collections.collections[0].name = "col1"
            client.get_collections.return_value = collections
            return svc, client

    def test_upsert_replaces_existing_points_and_stamps_the_id_field(self) -> None:
        svc, client = self._service()
        client.count.return_value.count = 2

        point_id, replaced = svc.upsert_by_field("col1", "sku", "a-1", "text", {"lang": "en"})

        self.assertEqual(replaced, 2)
        self.assertEqual(point_id, upsert_point_id("col1", "sku", "a-1"))
        client.delete.assert_called_once()
        payload = client.upsert.call_args.kwargs["points"][0].payload
        self.assertEqual(payload["sku"], "a-1")
        self.assertEqual(payload["lang"], "en")
        self.assertEqual(payload["text"], "text")

    def test_upsert_keeps_existing_points_when_embedding_fails(self) -> None:
        svc, client = self._service()
        client.count.return_value.count = 1
        svc.embedding_service.embed_text.side_effect = RuntimeError("429 rate limited")

        with self.assertRaises(RuntimeError):
            svc.upsert_by_field("col1", "sku", "a-1", "text")

        client.delete.assert_not_called()
        client.upsert.assert_not_called()

    def test_upsert_deletes_only_stale_points_after_the_new_one_is_written(self) -> None:
        svc, client = self._service()
        client.count.return_value.count = 2
        calls = MagicMock()
        calls.attach_mock(client.upsert, "upsert")
        calls.attach_mock(client.delete, "delete")

        point_id, _ = svc.upsert_by_field("col1", "sku", "a-1", "text")

        self.assertEqual([c[0] for c in calls.mock_calls], ["upsert", "delete"])
        stale = client.delete.call_args.kwargs["points_selector"].filter
        self.assertEqual(stale.must[0].key, "sku")
        self.assertEqual(stale.must[0].match.value, "a-1")
        self.assertEqual(stale.must_not[0].has_id, [point_id])

    def test_upsert_is_stable_so_repeated_calls_reuse_one_point(self) -> None:
        svc, client = self._service()
        client.count.return_value.count = 0

        first, _ = svc.upsert_by_field("col1", "sku", "a-1", "v1")
        second, _ = svc.upsert_by_field("col1", "sku", "a-1", "v2")

        self.assertEqual(first, second)

    def test_upsert_into_a_missing_collection_skips_the_replace_probe(self) -> None:
        svc, client = self._service()
        client.get_collections.return_value.collections = []

        _, replaced = svc.upsert_by_field("col1", "sku", "a-1", "text")

        self.assertEqual(replaced, 0)
        client.count.assert_not_called()
        client.delete.assert_not_called()

    def test_delete_by_field_returns_matched_count(self) -> None:
        svc, client = self._service()
        client.count.return_value.count = 4

        self.assertEqual(svc.delete_by_field("col1", "sku", "a-1"), 4)
        client.delete.assert_called_once()

    def test_delete_by_field_without_a_match_does_not_delete(self) -> None:
        svc, client = self._service()
        client.count.return_value.count = 0

        self.assertEqual(svc.delete_by_field("col1", "sku", "a-1"), 0)
        client.delete.assert_not_called()

    def test_delete_by_field_on_a_missing_collection_returns_zero(self) -> None:
        svc, client = self._service()
        client.get_collections.return_value.collections = []

        self.assertEqual(svc.delete_by_field("col1", "sku", "a-1"), 0)
        client.delete.assert_not_called()


class TestPgVectorUpsertAndDeleteByField(unittest.TestCase):
    def _service(self):
        with patch("app.services.vector_store_pg.EmbeddingService") as emb_cls:
            emb_cls.return_value.embed_text.return_value = [0.0] * 1536
            from app.services.vector_store_pg import PgVectorStoreService

            engine = MagicMock()
            return PgVectorStoreService("sk-test", engine=engine), engine

    def test_upsert_deletes_and_inserts_in_one_transaction(self) -> None:
        svc, engine = self._service()
        conn = engine.begin.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 2

        point_id, replaced = svc.upsert_by_field("col1", "sku", "a-1", "text", {"lang": "en"})

        self.assertEqual(replaced, 2)
        self.assertEqual(point_id, upsert_point_id("col1", "sku", "a-1"))
        self.assertEqual(engine.begin.call_count, 1)
        delete_sql = str(conn.execute.call_args_list[0].args[0])
        self.assertIn("DELETE FROM vector_store_items", delete_sql)
        self.assertIn("metadata @> (:mf)::jsonb", delete_sql)
        insert_params = conn.execute.call_args_list[1].args[1]
        self.assertIn('"sku": "a-1"', insert_params["m"])
        self.assertEqual(insert_params["id"], point_id)

    def test_delete_by_field_returns_deleted_row_count(self) -> None:
        svc, engine = self._service()
        conn = engine.begin.return_value.__enter__.return_value
        conn.execute.return_value.rowcount = 3

        self.assertEqual(svc.delete_by_field("col1", "sku", "a-1"), 3)
        params = conn.execute.call_args.args[1]
        self.assertEqual(params["mf"], '{"sku": "a-1"}')

    def test_delete_by_field_without_the_backend_table_returns_zero(self) -> None:
        svc, engine = self._service()
        engine.connect.return_value.__enter__.return_value.exec_driver_sql.return_value.scalar.return_value = False

        self.assertEqual(svc.delete_by_field("col1", "sku", "a-1"), 0)
        engine.begin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
