"""DELETE /vector-stores/{id} deletes the row first and reports the real drop."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.db.models import Credential, CredentialType, VectorStore

DROP_FAILED_WARNING = "Store removed, but the vectors could not be deleted"


def _result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class DeleteVectorStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com")
        self.credential = Credential(
            id=uuid.uuid4(),
            owner_id=self.user.id,
            name="RAG",
            type=CredentialType.rag,
            encrypted_config="x",
        )
        self.store = VectorStore(
            id=uuid.uuid4(),
            name="Docs",
            collection_name="docs",
            owner_id=self.user.id,
            credential_id=self.credential.id,
        )
        self.events: list[str] = []

        async def delete_row(_store: object) -> None:
            self.events.append("row")

        async def commit() -> None:
            self.events.append("commit")

        self.db = AsyncMock()
        self.db.execute = AsyncMock(side_effect=[_result(self.store), _result(self.credential)])
        self.db.delete = AsyncMock(side_effect=delete_row)
        self.db.commit = AsyncMock(side_effect=commit)
        self.service = Mock()
        self.service.collection_exists.return_value = True

        def drop(_name: str) -> bool:
            self.events.append("drop")
            return True

        self.service.delete_collection.side_effect = drop
        self.audit = Mock()
        self.logger = Mock()
        for target, value in (
            ("app.api.vector_stores.decrypt_config", Mock(return_value={})),
            (
                "app.api.vector_stores.get_vector_store_service_from_config",
                Mock(return_value=self.service),
            ),
            ("app.api.vector_stores.audit", self.audit),
            ("app.api.vector_stores.logger", self.logger),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _delete(self, delete_collection: bool = True):
        from app.api.vector_stores import delete_vector_store

        return await delete_vector_store(
            self.store.id,
            delete_collection=delete_collection,
            current_user=self.user,
            db=self.db,
        )

    async def test_successful_drop_deletes_the_row_first(self) -> None:
        response = await self._delete()

        self.assertEqual(self.events, ["row", "commit", "drop"])
        self.service.delete_collection.assert_called_once_with("docs")
        self.assertTrue(response.collection_dropped)
        self.assertEqual(response.reason, "dropped")
        self.assertIsNone(response.warning)
        self.assertEqual(self.audit.call_args.kwargs["collection_dropped"], True)
        self.assertEqual(self.audit.call_args.kwargs["collection_result"], "dropped")
        self.assertEqual(self.audit.call_args.kwargs["outcome"], "success")
        self.logger.warning.assert_not_called()

    async def test_drop_failure_reports_a_warning_without_the_raw_error(self) -> None:
        self.service.delete_collection.side_effect = RuntimeError("qdrant is down")

        response = await self._delete()

        self.assertEqual(self.events, ["row", "commit"])
        self.assertFalse(response.collection_dropped)
        self.assertEqual(response.reason, "failed")
        self.assertEqual(response.warning, DROP_FAILED_WARNING)
        self.assertNotIn("qdrant is down", response.warning)
        self.assertEqual(self.audit.call_args.kwargs["collection_dropped"], False)
        self.assertEqual(self.audit.call_args.kwargs["collection_result"], "failed")
        self.assertEqual(self.audit.call_args.kwargs["outcome"], "failure")
        logged = " ".join(str(part) for part in self.logger.warning.call_args.args)
        self.assertNotIn("qdrant is down", logged)
        self.assertTrue(self.logger.warning.call_args.kwargs["exc_info"])
        self.db.delete.assert_awaited()

    async def test_missing_collection_is_not_an_error(self) -> None:
        self.service.collection_exists.return_value = False

        response = await self._delete()

        self.service.delete_collection.assert_not_called()
        self.assertEqual(self.events, ["row", "commit"])
        self.assertFalse(response.collection_dropped)
        self.assertEqual(response.reason, "missing")
        self.assertIsNone(response.warning)
        self.assertEqual(self.audit.call_args.kwargs["collection_dropped"], False)
        self.assertEqual(self.audit.call_args.kwargs["collection_result"], "missing")
        self.assertEqual(self.audit.call_args.kwargs["outcome"], "success")
        self.logger.warning.assert_not_called()

    async def test_delete_collection_false_skips_the_backend(self) -> None:
        response = await self._delete(delete_collection=False)

        self.service.collection_exists.assert_not_called()
        self.service.delete_collection.assert_not_called()
        self.assertEqual(self.events, ["row", "commit"])
        self.assertFalse(response.collection_dropped)
        self.assertEqual(response.reason, "skipped")
        self.assertIsNone(response.warning)
        self.assertEqual(self.audit.call_args.kwargs["collection_dropped"], False)
        self.assertEqual(self.audit.call_args.kwargs["collection_result"], "skipped")
        self.assertEqual(self.audit.call_args.kwargs["outcome"], "success")
