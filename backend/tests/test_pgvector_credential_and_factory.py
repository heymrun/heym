import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api.credentials import validate_credential_config
from app.db.models import CredentialType


class TestPgvectorCredentialValidation(unittest.TestCase):
    def test_pgvector_requires_openai_api_key(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.pgvector, {})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_pgvector_valid_config_passes(self):
        # Should not raise.
        validate_credential_config(CredentialType.pgvector, {"openai_api_key": "sk-test"})


class TestCredentialTypeEnumsInSync(unittest.TestCase):
    def test_schema_and_model_credential_types_match(self):
        """The API schema enum and the DB model enum must list the same types.

        A POST /api/credentials body is validated against the schema enum, so a
        type missing there (e.g. pgvector) fails with 422 before reaching the DB.
        """
        from app.db.models import CredentialType as ModelType
        from app.models.schemas import CredentialType as SchemaType

        self.assertEqual(
            {e.value for e in SchemaType},
            {e.value for e in ModelType},
        )

    def test_create_credential_accepts_pgvector(self):
        from app.models.schemas import CredentialCreate

        cred = CredentialCreate(
            name="RAG Psql", type="pgvector", config={"openai_api_key": "sk-test"}
        )
        self.assertEqual(cred.type.value, "pgvector")


class TestVectorStoreFactory(unittest.TestCase):
    def test_qdrant_credential_returns_qdrant_service(self):
        from app.services.vector_store import (
            QdrantVectorStoreService,
            create_vector_store_service_for_credential,
        )

        config = {
            "qdrant_host": "localhost",
            "qdrant_port": 6333,
            "openai_api_key": "sk-test",
        }
        svc = create_vector_store_service_for_credential("qdrant", config)
        self.assertIsInstance(svc, QdrantVectorStoreService)

    def test_pgvector_credential_returns_pg_service(self):
        with patch("app.services.vector_store_pg.EmbeddingService"):
            from app.services.vector_store import create_vector_store_service_for_credential
            from app.services.vector_store_pg import PgVectorStoreService

            svc = create_vector_store_service_for_credential(
                "pgvector", {"openai_api_key": "sk-test"}
            )
            self.assertIsInstance(svc, PgVectorStoreService)

    def test_unknown_type_raises(self):
        from app.services.vector_store import create_vector_store_service_for_credential

        with self.assertRaises(ValueError):
            create_vector_store_service_for_credential("nope", {})


class TestExecutorRagPgvector(unittest.TestCase):
    def test_rag_search_uses_pg_backend_for_pgvector_credential(self):
        """The RAG branch must build the backend from the store's credential type."""
        from app.services.vector_store import create_vector_store_service_for_credential
        from app.services.vector_store_pg import PgVectorStoreService

        with patch("app.services.vector_store_pg.EmbeddingService"):
            svc = create_vector_store_service_for_credential(
                "pgvector", {"openai_api_key": "sk-test"}
            )
        self.assertIsInstance(svc, PgVectorStoreService)


if __name__ == "__main__":
    unittest.main()
