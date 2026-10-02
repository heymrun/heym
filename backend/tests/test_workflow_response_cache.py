import hashlib
import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.workflows import clear_workflow_response_cache
from app.services.cache_rate_limit import WorkflowResponseCacheStore


def _legacy_key(workflow_id: str, body: dict, query: dict) -> str:
    data = json.dumps({"workflow_id": workflow_id, "body": body, "query": query}, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()


class WorkflowResponseCacheKeyTests(unittest.TestCase):
    def test_key_matches_legacy_in_memory_scheme(self) -> None:
        store = WorkflowResponseCacheStore()
        wf = str(uuid.uuid4())
        body = {"b": 2, "a": 1}
        query = {"q": "x"}
        self.assertEqual(
            store._generate_key(wf, body, query),
            _legacy_key(wf, body, query),
        )

    def test_key_changes_with_body(self) -> None:
        store = WorkflowResponseCacheStore()
        wf = str(uuid.uuid4())
        self.assertNotEqual(
            store._generate_key(wf, {"a": 1}, {}),
            store._generate_key(wf, {"a": 2}, {}),
        )


class WorkflowResponseCacheGetTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_miss_when_no_row(self) -> None:
        store = WorkflowResponseCacheStore()
        result = SimpleNamespace(scalar_one_or_none=lambda: None)
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        hit, value = await store.get(db, str(uuid.uuid4()), {}, {})

        self.assertFalse(hit)
        self.assertIsNone(value)

    async def test_get_hit_when_not_expired(self) -> None:
        store = WorkflowResponseCacheStore()
        row = SimpleNamespace(
            outputs={"outputs": {"ok": True}},
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        result = SimpleNamespace(scalar_one_or_none=lambda: row)
        db = SimpleNamespace(execute=AsyncMock(return_value=result), delete=AsyncMock())

        hit, value = await store.get(db, str(uuid.uuid4()), {}, {})

        self.assertTrue(hit)
        self.assertEqual(value, {"outputs": {"ok": True}})
        db.delete.assert_not_called()

    async def test_get_expired_returns_miss_and_deletes(self) -> None:
        store = WorkflowResponseCacheStore()
        row = SimpleNamespace(
            outputs={"outputs": {"ok": True}},
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        result = SimpleNamespace(scalar_one_or_none=lambda: row)
        db = SimpleNamespace(execute=AsyncMock(return_value=result), delete=AsyncMock())

        hit, value = await store.get(db, str(uuid.uuid4()), {}, {})

        self.assertFalse(hit)
        self.assertIsNone(value)
        db.delete.assert_awaited_once_with(row)


class WorkflowResponseCacheSetTests(unittest.IsolatedAsyncioTestCase):
    async def test_set_issues_upsert(self) -> None:
        store = WorkflowResponseCacheStore()
        db = SimpleNamespace(execute=AsyncMock())

        await store.set(db, str(uuid.uuid4()), {"a": 1}, {}, {"outputs": {"ok": True}}, 30)

        db.execute.assert_awaited_once()
        stmt = db.execute.await_args.args[0]
        from sqlalchemy.dialects import postgresql

        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        self.assertIn("ON CONFLICT", compiled.upper())


class WorkflowResponseCacheCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_expired_returns_deleted_count(self) -> None:
        store = WorkflowResponseCacheStore()
        result = SimpleNamespace(rowcount=4)
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        deleted = await store.cleanup_expired(db)

        self.assertEqual(deleted, 4)
        db.execute.assert_awaited_once()


class WorkflowResponseCacheClearTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_workflow_deletes_rows_for_workflow(self) -> None:
        store = WorkflowResponseCacheStore()
        workflow_id = uuid.uuid4()
        result = SimpleNamespace(rowcount=3)
        db = SimpleNamespace(execute=AsyncMock(return_value=result))

        deleted = await store.clear_workflow(db, workflow_id)

        self.assertEqual(deleted, 3)
        db.execute.assert_awaited_once()
        stmt = db.execute.await_args.args[0]
        from sqlalchemy.dialects import postgresql

        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        self.assertIn("DELETE FROM workflow_response_cache", compiled)
        self.assertIn("workflow_id", compiled)


class ClearWorkflowResponseCacheEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch("app.api.workflows.user_can_write_workflow", AsyncMock(return_value=True))
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_clear_response_cache_requires_workflow_access(self) -> None:
        workflow_id = uuid.uuid4()
        current_user = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()

        with patch(
            "app.api.workflows.get_workflow_for_user",
            AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await clear_workflow_response_cache(
                    workflow_id=workflow_id,
                    current_user=current_user,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_clear_response_cache_evicts_workflow_rows(self) -> None:
        workflow_id = uuid.uuid4()
        current_user = SimpleNamespace(id=uuid.uuid4())
        workflow = SimpleNamespace(id=workflow_id)
        db = AsyncMock()

        with (
            patch(
                "app.api.workflows.get_workflow_for_user",
                AsyncMock(return_value=workflow),
            ),
            patch(
                "app.api.workflows.response_cache.clear_workflow",
                AsyncMock(return_value=2),
            ) as clear_mock,
        ):
            await clear_workflow_response_cache(
                workflow_id=workflow_id,
                current_user=current_user,
                db=db,
            )

        clear_mock.assert_awaited_once_with(db, workflow_id)


if __name__ == "__main__":
    unittest.main()
