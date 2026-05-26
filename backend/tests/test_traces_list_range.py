import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.traces import list_traces


class _ExecResult:
    def __init__(self, items):
        self._items = items

    def scalar_one(self):
        return len(self._items)

    def all(self):
        return self._items


class ListRangeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = MagicMock()
        self.user.id = uuid.uuid4()

    async def _run(self, range_arg):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_ExecResult([]), _ExecResult([])])
        await list_traces(
            limit=25,
            offset=0,
            credential_id=None,
            workflow_id=None,
            source=None,
            status_filter=None,
            search=None,
            order="desc",
            range=range_arg,
            current_user=self.user,
            db=db,
        )
        return db

    async def test_range_param_applies_start_filter(self):
        with patch("app.api.traces._resolve_range") as resolve_mock:
            resolve_mock.return_value = (
                datetime(2026, 5, 19, tzinfo=timezone.utc),
                datetime(2026, 5, 26, tzinfo=timezone.utc),
                21600,
            )
            db = await self._run("7d")
        resolve_mock.assert_called_once_with("7d")
        self.assertEqual(db.execute.await_count, 2)

    async def test_range_none_keeps_backward_compat_no_resolve_call(self):
        with patch("app.api.traces._resolve_range") as resolve_mock:
            db = await self._run(None)
        resolve_mock.assert_not_called()
        self.assertEqual(db.execute.await_count, 2)
