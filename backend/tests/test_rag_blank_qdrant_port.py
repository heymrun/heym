"""A RAG or QDrant credential with a blank QDrant Port uses 6333.

The RAG credential form does not require the port and saves "" when it is cleared; the
credential list already shows such a credential with port 6333. The vector store was
built with int(""), so creating a vector store on it answered 500 and every RAG node
using it failed with "invalid literal for int() with base 10: ''".
"""

import unittest
from unittest.mock import patch

from app.services.vector_store import create_vector_store_service_for_credential

RAG = {
    "db_type": "qdrant",
    "qdrant_host": "qdrant.internal",
    "qdrant_api_key": "",
    "embedding_base_url": "https://embeddings.example.com/v1",
    "embedding_api_key": "k",
    "embedding_model": "text-embedding-3-small",
    "embedding_dimensions": "1536",
}
QDRANT = {"qdrant_host": "qdrant.internal", "openai_api_key": "sk-test"}


def _port(credential_type: str, config: dict) -> int:
    with (
        patch("app.services.vector_store.QdrantClient") as client,
        patch("app.services.vector_store.EmbeddingService"),
    ):
        create_vector_store_service_for_credential(credential_type, config)
    return client.call_args.kwargs["port"]


class BlankQdrantPortTests(unittest.TestCase):
    def test_blank_or_missing_port_is_6333(self) -> None:
        for credential_type, base in (("rag", RAG), ("qdrant", QDRANT)):
            for port in ("", "  ", None, ...):
                with self.subTest(credential_type=credential_type, port=port):
                    config = dict(base) if port is ... else {**base, "qdrant_port": port}
                    self.assertEqual(_port(credential_type, config), 6333)

    def test_a_set_port_is_used(self) -> None:
        for port, expected in (("6334", 6334), (" 6334 ", 6334), (6334, 6334)):
            with self.subTest(port=port):
                self.assertEqual(_port("rag", {**RAG, "qdrant_port": port}), expected)


if __name__ == "__main__":
    unittest.main()
