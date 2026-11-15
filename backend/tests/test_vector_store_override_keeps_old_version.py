"""Replacing a file's chunks writes the new version before it drops the old one.

Runs the real QdrantVectorStoreService on qdrant-client's local in-memory mode, with the
embeddings client replaced at its seam.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

DIMS = 8
SOURCE = "handbook.txt"


class _Embeddings:
    def __init__(self) -> None:
        self.fail = False

    def create(self, model: str, input: list[str] | str, **_: object) -> SimpleNamespace:
        if self.fail:
            raise RuntimeError("Rate limit reached")
        items = input if isinstance(input, list) else [input]
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=i, embedding=[float(len(t) % 7 + 1)] * DIMS)
                for i, t in enumerate(items)
            ]
        )


class QdrantOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = QdrantClient(":memory:")
        self.embeddings = _Embeddings()
        patches = (
            patch("app.services.vector_store.QdrantClient", Mock(return_value=self.client)),
            patch(
                "app.services.embedding.create_openai_client",
                Mock(return_value=SimpleNamespace(embeddings=self.embeddings)),
            ),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        from app.services.embedding import EmbeddingConfig
        from app.services.vector_store import QdrantVectorStoreService

        self.service = QdrantVectorStoreService(
            "localhost",
            6333,
            None,
            embedding_config=EmbeddingConfig(api_key="sk-test", dimensions=DIMS),
        )
        self.collection = f"c{uuid.uuid4().hex[:8]}"
        self.client.create_collection(
            self.collection, vectors_config=VectorParams(size=DIMS, distance=Distance.COSINE)
        )
        self.service.insert_batch(
            self.collection, ["Refund window is 30 days."], [{"source": SOURCE}]
        )

    def _texts(self) -> list[str]:
        points, _ = self.client.scroll(self.collection, limit=100, with_payload=True)
        return sorted(p.payload["text"] for p in points if p.payload.get("source") == SOURCE)

    def _replace(self, text: str) -> None:
        new_ids = self.service.insert_batch(self.collection, [text], [{"source": SOURCE}])
        self.service.delete_by_source(self.collection, SOURCE, keep_ids=new_ids)

    def test_a_failed_embed_keeps_the_old_version(self) -> None:
        self.embeddings.fail = True

        with self.assertRaises(RuntimeError):
            self._replace("Refund window is 45 days.")

        self.assertEqual(self._texts(), ["Refund window is 30 days."])

    def test_a_replace_leaves_only_the_new_version(self) -> None:
        self._replace("Refund window is 45 days.")

        self.assertEqual(self._texts(), ["Refund window is 45 days."])

    def test_without_keep_ids_every_chunk_of_the_source_goes(self) -> None:
        self.service.delete_by_source(self.collection, SOURCE)

        self.assertEqual(self._texts(), [])


if __name__ == "__main__":
    unittest.main()
