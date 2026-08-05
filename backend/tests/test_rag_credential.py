import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    get_public_credential_fields,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType
from app.services.embedding import (
    EMBEDDING_DIMENSIONS,
    EmbeddingConfig,
    EmbeddingService,
    embedding_config_from_credential,
)
from app.services.vector_store import (
    QdrantVectorStoreService,
    create_vector_store_service_for_credential,
    rag_credential_backend,
)


def _qdrant_config(**overrides: object) -> dict:
    config: dict = {
        "embedding_base_url": "http://localhost:11434/v1",
        "embedding_api_key": "",
        "embedding_model": "nomic-embed-text",
        "embedding_dimensions": 768,
        "db_type": "qdrant",
        "qdrant_host": "localhost",
        "qdrant_port": 6333,
        "qdrant_api_key": "",
    }
    config.update(overrides)
    return config


def _pgvector_config(**overrides: object) -> dict:
    config: dict = {
        "embedding_base_url": "https://api.openai.com/v1",
        "embedding_api_key": "sk-test",
        "embedding_model": "text-embedding-3-large",
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "db_type": "pgvector",
    }
    config.update(overrides)
    return config


class TestRagCredentialValidation(unittest.TestCase):
    def test_valid_qdrant_config_passes(self):
        validate_credential_config(CredentialType.rag, _qdrant_config())

    def test_valid_pgvector_config_passes(self):
        validate_credential_config(CredentialType.rag, _pgvector_config())

    def test_missing_base_url_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.rag, _qdrant_config(embedding_base_url=""))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("embedding_base_url", ctx.exception.detail)

    def test_missing_model_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.rag, _qdrant_config(embedding_model=""))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("embedding_model", ctx.exception.detail)

    def test_non_positive_dimensions_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.rag, _qdrant_config(embedding_dimensions=-1))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_unknown_db_type_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.rag, _qdrant_config(db_type="milvus"))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("db_type", ctx.exception.detail)

    def test_qdrant_requires_host(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.rag, _qdrant_config(qdrant_host=""))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("qdrant_host", ctx.exception.detail)

    def test_pgvector_rejects_non_default_dimensions(self):
        """pgvector's column is a fixed vector(1536), so other widths cannot be stored."""
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(
                CredentialType.rag, _pgvector_config(embedding_dimensions=768)
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("768", ctx.exception.detail)
        self.assertIn(str(EMBEDDING_DIMENSIONS), ctx.exception.detail)

    def test_qdrant_allows_non_default_dimensions(self):
        validate_credential_config(CredentialType.rag, _qdrant_config(embedding_dimensions=1024))


class TestRagCredentialFields(unittest.TestCase):
    def test_masked_value_masks_api_key(self):
        masked = get_masked_value(CredentialType.rag, _pgvector_config())
        self.assertIsNotNone(masked)
        self.assertNotIn("sk-test", str(masked))

    def test_masked_value_falls_back_to_model_without_key(self):
        masked = get_masked_value(CredentialType.rag, _qdrant_config())
        self.assertEqual(masked, "nomic-embed-text")

    def test_public_fields_expose_non_secret_config(self):
        fields = get_public_credential_fields(CredentialType.rag, _qdrant_config())
        self.assertEqual(fields["embedding_base_url"], "http://localhost:11434/v1")
        self.assertEqual(fields["embedding_model"], "nomic-embed-text")
        self.assertEqual(fields["embedding_dimensions"], "768")
        self.assertEqual(fields["db_type"], "qdrant")
        self.assertEqual(fields["qdrant_host"], "localhost")
        self.assertEqual(fields["embedding_request_dimensions"], "false")
        self.assertNotIn("embedding_api_key", fields)

    def test_public_fields_round_trip_the_request_dimensions_flag(self):
        fields = get_public_credential_fields(
            CredentialType.rag, _pgvector_config(embedding_request_dimensions=True)
        )
        self.assertEqual(fields["embedding_request_dimensions"], "true")

    def test_update_keeps_stored_secrets_when_inputs_are_blank(self):
        existing = _qdrant_config(embedding_api_key="stored-key", qdrant_api_key="stored-qdrant")
        incoming = _qdrant_config(embedding_api_key="", qdrant_api_key="")
        merged = merge_credential_config_for_update(CredentialType.rag, existing, incoming)
        self.assertEqual(merged["embedding_api_key"], "stored-key")
        self.assertEqual(merged["qdrant_api_key"], "stored-qdrant")

    def test_update_carries_the_request_dimensions_flag(self):
        """A cleared checkbox must survive the merge, not fall back to the stored value."""
        existing = _pgvector_config(embedding_request_dimensions=True)
        incoming = _pgvector_config(embedding_request_dimensions=False)
        merged = merge_credential_config_for_update(CredentialType.rag, existing, incoming)
        self.assertIs(merged["embedding_request_dimensions"], False)

    def test_update_applies_new_secrets_and_fields(self):
        existing = _qdrant_config(embedding_api_key="stored-key")
        incoming = _qdrant_config(embedding_api_key="fresh-key", embedding_model="bge-m3")
        merged = merge_credential_config_for_update(CredentialType.rag, existing, incoming)
        self.assertEqual(merged["embedding_api_key"], "fresh-key")
        self.assertEqual(merged["embedding_model"], "bge-m3")


class TestCredentialTypeEnumsInSync(unittest.TestCase):
    def test_schema_and_model_enums_both_carry_rag(self):
        from app.db.models import CredentialType as ModelType
        from app.models.schemas import CredentialType as SchemaType

        self.assertIn("rag", {e.value for e in SchemaType})
        self.assertIn("rag", {e.value for e in ModelType})

    def test_create_credential_accepts_rag(self):
        from app.models.schemas import CredentialCreate

        cred = CredentialCreate(name="RAG Custom", type="rag", config=_qdrant_config())
        self.assertEqual(cred.type.value, "rag")


class TestEmbeddingConfigFromCredential(unittest.TestCase):
    def test_reads_custom_endpoint_fields(self):
        config = embedding_config_from_credential(_qdrant_config())
        self.assertEqual(config.base_url, "http://localhost:11434/v1")
        self.assertEqual(config.model, "nomic-embed-text")
        self.assertEqual(config.dimensions, 768)
        self.assertIsNone(config.api_key)
        self.assertTrue(config.is_custom_endpoint)

    def test_falls_back_to_defaults_for_empty_fields(self):
        config = embedding_config_from_credential({})
        self.assertIsNone(config.base_url)
        self.assertEqual(config.dimensions, EMBEDDING_DIMENSIONS)
        self.assertFalse(config.is_custom_endpoint)
        self.assertFalse(config.request_dimensions)

    def test_request_dimensions_flag_accepts_bool_and_string(self):
        """The flag arrives as a bool from JSON but as a string from public_fields."""
        for raw in (True, "true", "True", "1"):
            config = embedding_config_from_credential(
                _pgvector_config(embedding_request_dimensions=raw)
            )
            self.assertTrue(config.request_dimensions, raw)
        for raw in (False, "false", "", None):
            config = embedding_config_from_credential(
                _pgvector_config(embedding_request_dimensions=raw)
            )
            self.assertFalse(config.request_dimensions, raw)


class TestEmbeddingServiceCustomEndpoint(unittest.TestCase):
    def _service(self, config: EmbeddingConfig) -> tuple[EmbeddingService, MagicMock]:
        with patch("app.services.embedding.create_openai_client") as make_client:
            client = MagicMock()
            make_client.return_value = client
            service = EmbeddingService(config)
        return service, client

    def _response(self, embedding: list[float]) -> MagicMock:
        response = MagicMock()
        item = MagicMock()
        item.embedding = embedding
        item.index = 0
        response.data = [item]
        return response

    def test_custom_endpoint_omits_dimensions_parameter(self):
        """Most OpenAI-compatible servers reject unknown request parameters."""
        config = EmbeddingConfig(base_url="http://localhost:11434/v1", model="m", dimensions=3)
        service, client = self._service(config)
        client.embeddings.create.return_value = self._response([0.1, 0.2, 0.3])

        service.embed_text("hello")

        kwargs = client.embeddings.create.call_args.kwargs
        self.assertNotIn("dimensions", kwargs)
        self.assertEqual(kwargs["model"], "m")

    def test_custom_endpoint_sends_dimensions_when_requested(self):
        """Opting in asks a Matryoshka-capable model to shorten its output."""
        config = EmbeddingConfig(
            base_url="http://localhost:11434/v1",
            model="m",
            dimensions=1536,
            request_dimensions=True,
        )
        service, client = self._service(config)
        client.embeddings.create.return_value = self._response([0.0] * 1536)

        service.embed_text("hello")

        self.assertEqual(client.embeddings.create.call_args.kwargs["dimensions"], 1536)

    def test_ignored_dimensions_request_explains_the_failure(self):
        """An endpoint may accept the parameter yet return its native width."""
        config = EmbeddingConfig(
            base_url="http://localhost:11434/v1",
            model="m",
            dimensions=1536,
            request_dimensions=True,
        )
        service, client = self._service(config)
        client.embeddings.create.return_value = self._response([0.0] * 2560)

        with self.assertRaises(ValueError) as ctx:
            service.embed_text("hello")
        message = str(ctx.exception)
        self.assertIn("2560", message)
        self.assertIn("did not shorten", message)
        self.assertIn("Qdrant", message)

    def test_openai_path_still_sends_dimensions(self):
        config = EmbeddingConfig(api_key="sk-test", dimensions=EMBEDDING_DIMENSIONS)
        service, client = self._service(config)
        client.embeddings.create.return_value = self._response([0.0] * EMBEDDING_DIMENSIONS)

        service.embed_text("hello")

        kwargs = client.embeddings.create.call_args.kwargs
        self.assertEqual(kwargs["dimensions"], EMBEDDING_DIMENSIONS)

    def test_dimension_mismatch_raises_with_both_values(self):
        config = EmbeddingConfig(base_url="http://localhost:11434/v1", model="m", dimensions=1024)
        service, client = self._service(config)
        client.embeddings.create.return_value = self._response([0.1, 0.2, 0.3])

        with self.assertRaises(ValueError) as ctx:
            service.embed_text("hello")
        self.assertIn("3 dimensions", str(ctx.exception))
        self.assertIn("1024", str(ctx.exception))

    def test_batch_embedding_checks_dimensions(self):
        config = EmbeddingConfig(base_url="http://localhost:11434/v1", model="m", dimensions=2)
        service, client = self._service(config)
        client.embeddings.create.return_value = self._response([0.1, 0.2, 0.3])

        with self.assertRaises(ValueError):
            service.embed_texts(["hello"])

    def test_blank_api_key_uses_placeholder(self):
        config = EmbeddingConfig(base_url="http://localhost:11434/v1", model="m")
        with patch("app.services.embedding.create_openai_client") as make_client:
            EmbeddingService(config)
        kwargs = make_client.call_args.kwargs
        self.assertTrue(kwargs["api_key"])
        self.assertEqual(kwargs["base_url"], "http://localhost:11434/v1")


class TestRagVectorStoreFactory(unittest.TestCase):
    def test_backend_selection_reads_db_type(self):
        self.assertEqual(rag_credential_backend({"db_type": "pgvector"}), "pgvector")
        self.assertEqual(rag_credential_backend({"db_type": "qdrant"}), "qdrant")
        self.assertEqual(rag_credential_backend({}), "qdrant")

    def test_unknown_db_type_raises(self):
        with self.assertRaises(ValueError):
            rag_credential_backend({"db_type": "milvus"})

    def test_rag_qdrant_credential_returns_qdrant_service(self):
        with patch("app.services.vector_store.QdrantClient"):
            service = create_vector_store_service_for_credential("rag", _qdrant_config())
        self.assertIsInstance(service, QdrantVectorStoreService)
        self.assertEqual(service.embedding_dimensions, 768)

    def test_rag_pgvector_credential_returns_pg_service(self):
        from app.services.vector_store_pg import PgVectorStoreService

        service = create_vector_store_service_for_credential("rag", _pgvector_config())
        self.assertIsInstance(service, PgVectorStoreService)

    def test_pg_service_rejects_non_default_dimensions(self):
        """Defence in depth: the factory must not build an unusable pgvector service."""
        with self.assertRaises(ValueError) as ctx:
            create_vector_store_service_for_credential(
                "rag", dict(_pgvector_config(), embedding_dimensions=768)
            )
        self.assertIn("768", str(ctx.exception))

    def test_qdrant_collection_uses_credential_dimensions(self):
        with patch("app.services.vector_store.QdrantClient") as client_cls:
            client = MagicMock()
            client_cls.return_value = client
            service = create_vector_store_service_for_credential(
                "rag", _qdrant_config(embedding_dimensions=1024)
            )
            service.create_collection("heym_vs_test")

        vectors_config = client.create_collection.call_args.kwargs["vectors_config"]
        self.assertEqual(vectors_config.size, 1024)

    def test_legacy_qdrant_credential_keeps_default_dimensions(self):
        with patch("app.services.vector_store.QdrantClient"):
            service = create_vector_store_service_for_credential(
                "qdrant",
                {"qdrant_host": "localhost", "qdrant_port": 6333, "openai_api_key": "sk-test"},
            )
        self.assertEqual(service.embedding_dimensions, EMBEDDING_DIMENSIONS)


class TestVectorStoreBackendDerivation(unittest.TestCase):
    def test_rag_credential_backend_comes_from_config(self):
        from app.api.vector_stores import _backend_for_credential_type

        self.assertEqual(
            _backend_for_credential_type(CredentialType.rag, _pgvector_config()),
            "pgvector",
        )
        self.assertEqual(
            _backend_for_credential_type(CredentialType.rag, _qdrant_config()),
            "qdrant",
        )

    def test_legacy_credential_backend_comes_from_type(self):
        from app.api.vector_stores import _backend_for_credential_type

        self.assertEqual(_backend_for_credential_type(CredentialType.pgvector), "pgvector")
        self.assertEqual(_backend_for_credential_type(CredentialType.qdrant), "qdrant")


class TestRagConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_reports_dimension_count_on_success(self):
        from app.api.credentials import _test_rag_embedding_endpoint

        with patch("app.api.credentials.EmbeddingService") as service_cls:
            service_cls.return_value.embed_text.return_value = [0.0] * 768
            result = await _test_rag_embedding_endpoint(_qdrant_config())

        self.assertTrue(result.success)
        self.assertIn("768", result.message)

    async def test_reports_that_the_endpoint_honored_the_request(self):
        from app.api.credentials import _test_rag_embedding_endpoint

        with patch("app.api.credentials.EmbeddingService") as service_cls:
            service_cls.return_value.embed_text.return_value = [0.0] * 1536
            result = await _test_rag_embedding_endpoint(
                _pgvector_config(embedding_request_dimensions=True)
            )

        self.assertTrue(result.success)
        self.assertIn("honored", result.message)
        self.assertIn("1536", result.message)

    async def test_reports_dimension_mismatch_as_failure(self):
        from app.api.credentials import _test_rag_embedding_endpoint

        with patch("app.api.credentials.EmbeddingService") as service_cls:
            service_cls.return_value.embed_text.side_effect = ValueError(
                "returned 768 dimensions, but the credential expects 1024"
            )
            result = await _test_rag_embedding_endpoint(_qdrant_config(embedding_dimensions=1024))

        self.assertFalse(result.success)
        self.assertIn("768", result.message)

    async def test_unreachable_endpoint_is_a_failure_not_an_error(self):
        from app.api.credentials import _test_rag_embedding_endpoint

        with patch("app.api.credentials.EmbeddingService") as service_cls:
            service_cls.return_value.embed_text.side_effect = ConnectionError("refused")
            result = await _test_rag_embedding_endpoint(_qdrant_config())

        self.assertFalse(result.success)
        self.assertIn("refused", result.message)


if __name__ == "__main__":
    unittest.main()
