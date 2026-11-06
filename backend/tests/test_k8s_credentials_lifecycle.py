"""Rows are written by the leader, including a process that only becomes leader later."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.services.k8s_credentials import lifecycle
from app.services.k8s_credentials.store import SecretCredentialStore


def _synced() -> SecretCredentialStore:
    store = SecretCredentialStore()
    store.enabled = True
    store.replace_all([])
    return store


class LeaderReconcilerTests(unittest.IsolatedAsyncioTestCase):
    async def _ticks(self, leadership: list[bool], store: SecretCredentialStore) -> AsyncMock:
        syncer = AsyncMock()
        reconciler = lifecycle.LeaderReconciler(syncer)
        with patch.object(lifecycle, "store", store):
            for leader in leadership:
                with patch.object(lifecycle.lock_service, "_is_leader", leader):
                    await reconciler.tick()
        return syncer

    async def test_winning_the_lock_after_the_first_sync_writes_rows_at_once(self) -> None:
        """Seen live: the first sync finished 21 ms before the lock was won."""
        syncer = await self._ticks([False, True], _synced())

        syncer.assert_awaited_once()

    async def test_a_steady_leader_reconciles_only_when_due(self) -> None:
        syncer = await self._ticks([True, True, True], _synced())

        syncer.assert_awaited_once()

    async def test_nothing_is_written_before_the_first_sync(self) -> None:
        unsynced = SecretCredentialStore()
        unsynced.enabled = True

        syncer = await self._ticks([True, True], unsynced)

        syncer.assert_not_called()

    async def test_a_failed_pass_is_logged_not_raised(self) -> None:
        reconciler = lifecycle.LeaderReconciler(AsyncMock(side_effect=RuntimeError("db down")))
        with (
            patch.object(lifecycle, "store", _synced()),
            patch.object(lifecycle.lock_service, "_is_leader", True),
            self.assertLogs("k8s_credentials", level="ERROR"),
        ):
            await reconciler.tick()


class RowSyncerTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_follower_never_writes(self) -> None:
        with (
            patch.object(lifecycle.lock_service, "_is_leader", False),
            patch.object(lifecycle.rows, "reconcile", new=AsyncMock()) as reconcile,
        ):
            await lifecycle.RowSyncer()()

        reconcile.assert_not_called()


if __name__ == "__main__":
    unittest.main()
