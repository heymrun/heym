"""The IMAP Trigger's cursor survives a restart and is forgotten when the trigger goes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select
from workflow_concurrency_fixtures import ConcurrencyPostgresCase

from app.db.models import TriggerPollState
from app.db.session import async_session_maker
from app.services.imap_trigger_service import ImapCursor, ImapTriggerManager

NODE = {"id": "imap-1", "type": "imapTrigger", "data": {"credentialId": "c1"}}


class ImapCursorStorageTests(ConcurrencyPostgresCase):
    limit = None

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.addAsyncCleanup(self._drop_cursors)
        self.workflow = SimpleNamespace(id=self.workflow_id, nodes=[NODE])

    async def _drop_cursors(self) -> None:
        async with async_session_maker() as db:
            await db.execute(
                delete(TriggerPollState).where(TriggerPollState.workflow_id == self.workflow_id)
            )
            await db.commit()

    async def _poll(self, manager: ImapTriggerManager, returned: ImapCursor, emails: list):
        fetch = AsyncMock(return_value=(returned, emails))
        with (
            patch.object(manager, "_load_credential_config", AsyncMock(return_value={})),
            patch.object(manager, "_fetch_node_messages", fetch),
            patch.object(manager, "_execute_workflow_for_email", AsyncMock()),
        ):
            await manager._poll_workflow_node(self.workflow, NODE)
        return fetch.await_args.args[1]

    async def test_a_new_process_continues_from_the_stored_cursor(self) -> None:
        await self._poll(ImapTriggerManager(), ImapCursor(uidvalidity="77", last_uid=100), [])

        seen = await self._poll(
            ImapTriggerManager(), ImapCursor(uidvalidity="77", last_uid=101), [{"uid": "101"}]
        )

        self.assertEqual(seen, ImapCursor(uidvalidity="77", last_uid=100))

    async def test_a_node_never_polled_starts_without_a_cursor(self) -> None:
        seen = await self._poll(ImapTriggerManager(), ImapCursor(uidvalidity="1", last_uid=5), [])
        self.assertEqual(seen, ImapCursor())

    async def test_a_removed_or_deactivated_trigger_forgets_its_cursor(self) -> None:
        await self._poll(ImapTriggerManager(), ImapCursor(uidvalidity="77", last_uid=100), [])

        await ImapTriggerManager()._forget_inactive_cursors(active_keys=set())

        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(TriggerPollState.id).where(
                        TriggerPollState.workflow_id == self.workflow_id
                    )
                )
            ).all()
        self.assertEqual(rows, [])

    async def test_an_active_trigger_keeps_its_cursor(self) -> None:
        manager = ImapTriggerManager()
        await self._poll(manager, ImapCursor(uidvalidity="77", last_uid=100), [])

        await manager._forget_inactive_cursors(
            active_keys={manager._get_node_key(self.workflow_id, "imap-1")}
        )

        self.assertEqual(
            await manager._load_cursor(self.workflow_id, "imap-1"),
            ImapCursor(uidvalidity="77", last_uid=100),
        )
