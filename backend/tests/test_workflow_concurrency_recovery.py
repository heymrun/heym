"""A recovered or skipped run gives its concurrency slot to the next run in line."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.execution_cancellation import ClaimedOrphan
from app.services.execution_recovery import ExecutionRecoveryService


def _orphan(attempt: int = 1) -> ClaimedOrphan:
    return ClaimedOrphan(
        execution_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        inputs={},
        trigger_source="API",
        actor_user_id=uuid.uuid4(),
        attempt=attempt,
    )


class RecoverySlotReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def _recover(
        self, orphan: ClaimedOrphan, *, auto_recover: bool, finalized: bool = True
    ) -> AsyncMock:
        service = ExecutionRecoveryService()
        workflow = SimpleNamespace(id=orphan.workflow_id, auto_recover_runs=auto_recover)
        release = AsyncMock()
        with (
            patch.object(service, "_load_workflow", AsyncMock(return_value=workflow)),
            patch.object(service, "_rerun", AsyncMock()),
            patch.object(service, "_finalize", AsyncMock(return_value=finalized)),
            patch("app.services.workflow_concurrency.release", release),
        ):
            await service._recover_one(orphan)
        return release

    async def test_a_rerun_releases_when_it_ends(self) -> None:
        orphan = _orphan()
        release = await self._recover(orphan, auto_recover=True)
        release.assert_awaited_once_with(orphan.execution_id)

    async def test_a_skipped_run_releases(self) -> None:
        orphan = _orphan()
        release = await self._recover(orphan, auto_recover=False)
        release.assert_awaited_once_with(orphan.execution_id)

    async def test_a_lost_ownership_keeps_the_slot(self) -> None:
        """Another process owns the run now; its slot is still in use."""
        release = await self._recover(_orphan(), auto_recover=False, finalized=False)
        release.assert_not_awaited()
