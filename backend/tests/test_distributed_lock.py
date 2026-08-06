import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncConnection

from app.services.distributed_lock import DistributedLockService


class TestDistributedLockService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lock_service = DistributedLockService()

    async def test_successful_release(self):
        """
        Test that a successfully acquired lock is unlocked and the connection is closed normally.
        """
        mock_conn = AsyncMock(spec=AsyncConnection)
        mock_conn.execution_options.return_value = mock_conn

        mock_acquire_result = MagicMock()
        mock_acquire_result.fetchone.return_value = (True,)

        mock_unlock_result = MagicMock()
        mock_unlock_result.fetchone.return_value = (True,)

        async def mock_execute(query, *args, **kwargs):
            query_str = str(query)
            if "pg_try_advisory_lock" in query_str:
                return mock_acquire_result
            elif "pg_advisory_unlock" in query_str:
                return mock_unlock_result
            return MagicMock()

        mock_conn.execute.side_effect = mock_execute

        with patch("app.services.distributed_lock.engine") as mock_engine:
            mock_engine.connect = AsyncMock(return_value=mock_conn)

            acquired = await self.lock_service._try_acquire_leader_lock()
            self.assertTrue(acquired)
            self.lock_service._is_leader = True

            await self.lock_service._release_leader_session()

            self.assertEqual(mock_conn.execute.call_count, 2)

            mock_conn.close.assert_awaited_once()
            mock_conn.invalidate.assert_not_awaited()

    async def test_follower_cleanup(self):
        """
        Test that if a worker fails to acquire the lock (follower), it cleanly closes the connection.
        """
        mock_conn = AsyncMock(spec=AsyncConnection)
        mock_conn.execution_options.return_value = mock_conn

        mock_acquire_result = MagicMock()
        mock_acquire_result.fetchone.return_value = (False,)
        mock_conn.execute.return_value = mock_acquire_result

        with patch("app.services.distributed_lock.engine") as mock_engine:
            mock_engine.connect = AsyncMock(return_value=mock_conn)

            acquired = await self.lock_service._try_acquire_leader_lock()
            self.assertFalse(acquired)
            self.assertFalse(self.lock_service._is_leader)

            self.assertEqual(mock_conn.execute.call_count, 1)

            mock_conn.close.assert_awaited_once()
            mock_conn.invalidate.assert_not_awaited()

    async def test_failed_unlock(self):
        """
        Test that if the unlock query fails or throws an exception, the connection is invalidated.
        """
        mock_conn = AsyncMock(spec=AsyncConnection)
        mock_conn.execution_options.return_value = mock_conn

        mock_acquire_result = MagicMock()
        mock_acquire_result.fetchone.return_value = (True,)

        async def mock_execute(query, *args, **kwargs):
            query_str = str(query)
            if "pg_try_advisory_lock" in query_str:
                return mock_acquire_result
            elif "pg_advisory_unlock" in query_str:
                raise RuntimeError("Database connection lost")
            return MagicMock()

        mock_conn.execute.side_effect = mock_execute

        with patch("app.services.distributed_lock.engine") as mock_engine:
            mock_engine.connect = AsyncMock(return_value=mock_conn)

            acquired = await self.lock_service._try_acquire_leader_lock()
            self.assertTrue(acquired)
            self.lock_service._is_leader = True

            await self.lock_service._release_leader_session()

            mock_conn.invalidate.assert_awaited_once()
            mock_conn.close.assert_not_awaited()

    async def test_uncertain_acquire_cancellation(self):
        """
        Test that if the acquire query throws an exception or is cancelled, the connection is forcibly invalidated
        because the database might have granted the lock before the error reached Python.
        """
        mock_conn = AsyncMock(spec=AsyncConnection)
        mock_conn.execution_options.return_value = mock_conn

        mock_conn.execute.side_effect = asyncio.CancelledError("Task cancelled")

        with patch("app.services.distributed_lock.engine") as mock_engine:
            mock_engine.connect = AsyncMock(return_value=mock_conn)

            with self.assertRaises(asyncio.CancelledError):
                await self.lock_service._try_acquire_leader_lock()

            self.assertFalse(self.lock_service._is_leader)

            mock_conn.invalidate.assert_awaited_once()
            mock_conn.close.assert_not_awaited()

    async def test_uncertain_acquire_exception(self):
        """
        Test that a regular Exception during acquire also force-invalidates and returns False
        (as opposed to CancelledError which re-raises).
        """
        mock_conn = AsyncMock(spec=AsyncConnection)
        mock_conn.execution_options.return_value = mock_conn

        mock_conn.execute.side_effect = RuntimeError("Connection reset by peer")

        with patch("app.services.distributed_lock.engine") as mock_engine:
            mock_engine.connect = AsyncMock(return_value=mock_conn)

            acquired = await self.lock_service._try_acquire_leader_lock()
            self.assertFalse(acquired)
            self.assertFalse(self.lock_service._is_leader)

            mock_conn.invalidate.assert_awaited_once()
            mock_conn.close.assert_not_awaited()

    async def test_execution_options_failure(self):
        """
        Test that if execution_options fails, the original raw connection is closed.
        """
        mock_conn = AsyncMock(spec=AsyncConnection)
        mock_conn.execution_options.side_effect = RuntimeError("Failed to set options")

        with patch("app.services.distributed_lock.engine") as mock_engine:
            mock_engine.connect = AsyncMock(return_value=mock_conn)

            acquired = await self.lock_service._try_acquire_leader_lock()
            self.assertFalse(acquired)

            mock_conn.close.assert_awaited_once()
            mock_conn.invalidate.assert_not_awaited()

    async def test_execution_options_cancellation(self):
        """
        Test that if execution_options is cancelled, the connection is closed and CancelledError is re-raised.
        """
        mock_conn = AsyncMock(spec=AsyncConnection)
        mock_conn.execution_options.side_effect = asyncio.CancelledError("Task cancelled")

        with patch("app.services.distributed_lock.engine") as mock_engine:
            mock_engine.connect = AsyncMock(return_value=mock_conn)

            with self.assertRaises(asyncio.CancelledError):
                await self.lock_service._try_acquire_leader_lock()

            mock_conn.close.assert_awaited_once()
            mock_conn.invalidate.assert_not_awaited()
