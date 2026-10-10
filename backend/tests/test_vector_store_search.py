"""Searching a vector store from the API, as a RAG node's search would."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.db.models import Credential, CredentialType, VectorStore
from app.models.schemas import VectorStoreSearchRequest
from app.services.vector_store import SearchResult


def make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class VectorStoreSearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Policies",
            description=None,
            collection_name="policies",
            owner_id=uuid.uuid4(),
            credential_id=uuid.uuid4(),
        )
        self.credential = Credential(
            id=self.store.credential_id,
            owner_id=self.store.owner_id,
            name="Qdrant",
            type=CredentialType.qdrant,
            encrypted_config="encrypted",
        )
        self.db = AsyncMock()
        self.db.execute = AsyncMock(return_value=make_result(self.credential))

    async def _search(self, service: MagicMock, **body: object) -> object:
        from app.api.vector_stores import search_vector_store

        with (
            patch(
                "app.api.vector_stores.get_vector_store_with_grant",
                new=AsyncMock(return_value=(self.store, "read")),
            ),
            patch("app.api.vector_stores.decrypt_config", return_value={"url": "q"}),
            patch(
                "app.api.vector_stores.get_vector_store_service_from_config",
                return_value=service,
            ),
        ):
            return await search_vector_store(
                self.store.id,
                VectorStoreSearchRequest(**body),
                current_user=self.user,
                db=self.db,
            )

    async def test_returns_the_chunks_the_store_ranks_highest(self) -> None:
        service = MagicMock()
        service.search.return_value = [
            SearchResult(
                id="p1",
                text="Refunds within 30 days.",
                score=0.91,
                metadata={"source": "refunds.pdf", "page": 2},
            )
        ]

        response = await self._search(service, query="refund window", limit=3)

        service.search.assert_called_once_with("policies", "refund window", limit=3)
        self.assertEqual(len(response.results), 1)
        hit = response.results[0]
        self.assertEqual((hit.id, hit.text, hit.score), ("p1", "Refunds within 30 days.", 0.91))
        self.assertEqual(hit.source, "refunds.pdf")
        self.assertEqual(hit.metadata, {"source": "refunds.pdf", "page": 2})

    async def test_a_store_the_user_cannot_reach_is_not_found(self) -> None:
        from app.api.vector_stores import search_vector_store

        with patch(
            "app.api.vector_stores.get_vector_store_with_grant", new=AsyncMock(return_value=None)
        ):
            with self.assertRaises(HTTPException) as raised:
                await search_vector_store(
                    self.store.id,
                    VectorStoreSearchRequest(query="refund"),
                    current_user=self.user,
                    db=self.db,
                )

        self.assertEqual(raised.exception.status_code, status.HTTP_404_NOT_FOUND)
        self.db.execute.assert_not_awaited()

    async def test_a_failing_backend_answers_bad_gateway(self) -> None:
        service = MagicMock()
        service.search.side_effect = RuntimeError("connection refused")

        with self.assertRaises(HTTPException) as raised:
            await self._search(service, query="refund")

        self.assertEqual(raised.exception.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertNotIn("connection refused", raised.exception.detail)

    def test_queries_and_limits_are_bounded(self) -> None:
        self.assertEqual(VectorStoreSearchRequest(query="refund").limit, 5)
        with self.assertRaises(ValidationError):
            VectorStoreSearchRequest(query="")
        with self.assertRaises(ValidationError):
            VectorStoreSearchRequest(query="refund", limit=21)


if __name__ == "__main__":
    unittest.main()
