"""Poller: baseline, one run per change, carryover, CAS loss, revert, skip on errors."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.db.models import CredentialType
from app.services.google_triggers.config import TRIGGER_EVENTS
from app.services.google_triggers.events import (
    MOVED,
    ItemWrite,
    PollSkippedError,
    TriggerEvent,
)
from app.services.google_triggers.poller import MAX_RUNS_PER_POLL, GoogleTriggerPoller
from app.services.google_triggers.state_store import Claim, ClaimedPoll
from app.services.trigger_run_dispatch import TriggerDispatchNotStartedError

SECRET = "test-secret-key-for-tests-only-32-bytes"


class FakeStore:
    """In-memory TriggerStateStore with the same compare-and-swap rule."""

    def __init__(self) -> None:
        self.state_id: uuid.UUID | None = None
        self.version = 0
        self.scope = ""
        self.key_id = ""
        self.items: dict = {}
        self.lose_next_consume = False
        self.kept: set | None = None

    async def claim(self, workflow_id, node_id, poll_minutes) -> Claim:
        if self.state_id is None:
            return Claim(due=True)
        return Claim(
            due=True,
            poll=ClaimedPoll(
                self.state_id, self.version, self.scope, self.key_id, dict(self.items)
            ),
        )

    async def insert_baseline(self, *, scope_fingerprint, key_id, items, **_kwargs) -> bool:
        self.state_id = uuid.uuid4()
        self.scope, self.key_id, self.items = scope_fingerprint, key_id, dict(items)
        self.version = 0
        return True

    async def consume(self, state_id, expected_version, writes) -> bool:
        if self.lose_next_consume:
            self.lose_next_consume = False
            self.version += 1
            return False
        if expected_version != self.version:
            return False
        self.version += 1
        for write in writes:
            if write.payload is None:
                self.items.pop(write.item_key, None)
            else:
                self.items[write.item_key] = write.payload
        return True

    async def reset_baseline(self, state_id, expected_version, *, scope_fingerprint, key_id, items):
        if expected_version != self.version:
            return False
        self.version += 1
        self.scope, self.key_id, self.items = scope_fingerprint, key_id, dict(items)
        return True

    async def delete_except(self, node_types, keep) -> int:
        self.kept = keep
        return 0


class FakeSource:
    node_type = "googleSheetsTrigger"
    trigger_source = "google_sheets"
    label = "Google Sheets Trigger"
    credential_type = CredentialType.google_sheets
    poll_minutes = 1

    def __init__(
        self,
        changes=None,
        events=frozenset(TRIGGER_EVENTS),
        scope="scope-a",
        fetch_error=None,
        live_items=None,
    ) -> None:
        self.credential_id = str(uuid.uuid4())
        self.changes = changes or []
        self.events = events
        self.scope = scope
        self.fetch_error = fetch_error
        self.live_items = live_items or {"a": {"r": 2, "c": ["x"]}}

    def problem(self):
        return None

    def fetch(self, credential_config):
        if self.fetch_error:
            raise self.fetch_error
        return "live"

    def scope_fingerprint(self, live):
        return self.scope

    def items(self, live):
        return self.live_items

    def diff(self, stored, live):
        return self.changes


def _change(key: str, event: str = "created") -> TriggerEvent:
    return TriggerEvent(
        event=event,
        payload={"event": event, "row": {"rowIndex": 2}},
        write=ItemWrite(key, {"r": 2, "c": [key]}),
        revert=ItemWrite(key, None),
    )


WORKFLOW = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4())
NODE = {"id": "n1", "type": "googleSheetsTrigger", "data": {}}


class PollerTests(unittest.IsolatedAsyncioTestCase):
    async def _poll(self, store: FakeStore, source: FakeSource, dispatch: AsyncMock) -> None:
        poller = GoogleTriggerPoller(store=store, dispatch=dispatch, secret=SECRET)
        with (
            patch("app.services.google_triggers.poller.build_source", return_value=source),
            patch.object(poller, "_load_credential", AsyncMock(return_value={"t": 1})),
        ):
            await poller.poll_node(WORKFLOW, NODE)

    async def _baselined(self, source: FakeSource) -> FakeStore:
        store = FakeStore()
        await self._poll(store, source, AsyncMock())
        return store

    async def test_first_poll_records_a_baseline_and_runs_nothing(self) -> None:
        store = FakeStore()
        dispatch = AsyncMock()
        await self._poll(store, FakeSource(changes=[_change("b")]), dispatch)
        self.assertIsNotNone(store.state_id)
        self.assertEqual(store.items, {"a": {"r": 2, "c": ["x"]}})
        dispatch.assert_not_awaited()

    async def test_a_change_is_consumed_then_run_once(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        dispatch.assert_awaited_once()
        kwargs = dispatch.await_args.kwargs
        self.assertEqual(kwargs["trigger_source"], "google_sheets")
        self.assertEqual(kwargs["inputs"]["triggered_by"], "google_sheets")
        self.assertEqual(kwargs["inputs"]["trigger_node_id"], "n1")
        self.assertEqual(kwargs["inputs"]["change"]["event"], "created")
        self.assertIn("b", store.items)
        self.assertEqual(store.version, 1)

    async def test_filtered_and_moved_changes_are_consumed_silently(self) -> None:
        source = FakeSource(
            changes=[_change("b", "deleted"), _change("c", MOVED), _change("d", "created")],
            events=frozenset({"created"}),
        )
        store = await self._baselined(source)
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, 1)
        self.assertEqual(dispatch.await_args.kwargs["inputs"]["change"]["event"], "created")
        self.assertEqual(store.version, 2)
        self.assertIn("c", store.items)

    async def test_at_most_fifty_runs_per_poll_and_the_rest_wait(self) -> None:
        source = FakeSource(changes=[_change(f"k{index}") for index in range(60)])
        store = await self._baselined(source)
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, MAX_RUNS_PER_POLL)
        self.assertNotIn("k59", store.items)

    async def test_losing_the_compare_and_swap_starts_no_run(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        store.lose_next_consume = True
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        dispatch.assert_not_awaited()

    async def test_failure_before_dispatch_is_reverted_for_the_next_poll(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        dispatch = AsyncMock(side_effect=TriggerDispatchNotStartedError("db down"))
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, 3)
        self.assertNotIn("b", store.items)
        self.assertEqual(store.version, 2)

        retry = AsyncMock()
        await self._poll(store, source, retry)
        retry.assert_awaited_once()

    async def test_failure_after_dispatch_started_is_not_retried(self) -> None:
        source = FakeSource(changes=[_change("b"), _change("c")])
        store = await self._baselined(source)
        dispatch = AsyncMock(side_effect=RuntimeError("node failed"))
        await self._poll(store, source, dispatch)
        self.assertEqual(dispatch.await_count, 2)
        self.assertIn("b", store.items)
        self.assertIn("c", store.items)

    async def test_a_google_error_leaves_the_snapshot_alone(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        version = store.version
        failing = FakeSource(changes=[_change("b")], fetch_error=PollSkippedError("403"))
        dispatch = AsyncMock()
        await self._poll(store, failing, dispatch)
        dispatch.assert_not_awaited()
        self.assertEqual(store.version, version)

    async def test_an_unavailable_credential_skips_the_poll(self) -> None:
        store = FakeStore()
        poller = GoogleTriggerPoller(store=store, dispatch=AsyncMock(), secret=SECRET)
        with (
            patch("app.services.google_triggers.poller.build_source", return_value=FakeSource()),
            patch.object(poller, "_load_credential", AsyncMock(return_value=None)),
        ):
            await poller.poll_node(WORKFLOW, NODE)
        self.assertIsNone(store.state_id)

    async def test_a_scope_change_resets_the_baseline_without_runs(self) -> None:
        store = await self._baselined(FakeSource())
        moved = FakeSource(scope="scope-b", changes=[_change("b")], live_items={"z": {"r": 9}})
        dispatch = AsyncMock()
        await self._poll(store, moved, dispatch)
        dispatch.assert_not_awaited()
        self.assertEqual(store.scope, "scope-b")
        self.assertEqual(store.items, {"z": {"r": 9}})

    async def test_a_new_secret_resets_the_baseline_without_runs(self) -> None:
        source = FakeSource(changes=[_change("b")])
        store = await self._baselined(source)
        store.key_id = "older-key"
        dispatch = AsyncMock()
        await self._poll(store, source, dispatch)
        dispatch.assert_not_awaited()
        self.assertNotEqual(store.key_id, "older-key")


class PollOnceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_keeps_only_active_trigger_nodes(self) -> None:
        store = FakeStore()
        poller = GoogleTriggerPoller(store=store, dispatch=AsyncMock(), secret=SECRET)
        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[
                {"id": "on", "type": "googleDriveTrigger", "data": {}},
                {"id": "off", "type": "googleSheetsTrigger", "data": {"active": False}},
                {"id": "other", "type": "http", "data": {}},
            ],
        )
        with (
            patch.object(poller, "_load_workflows", AsyncMock(return_value=[workflow])),
            patch.object(poller, "poll_node", AsyncMock()) as poll_node,
        ):
            await poller.poll_once()
        poll_node.assert_awaited_once()
        self.assertEqual(store.kept, {(workflow.id, "on")})


if __name__ == "__main__":
    unittest.main()
