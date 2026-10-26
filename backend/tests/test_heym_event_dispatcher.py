"""Tests for Heym platform event dispatch."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.services import heym_event_dispatcher as dispatcher


def _event(name: str, owner_id: uuid.UUID | None = None, minute: int = 0) -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.name = name
    event.payload = {"workflow_id": "w1"}
    event.owner_id = owner_id
    event.workflow_id = uuid.uuid4()
    event.created_at = datetime(2026, 8, 11, 12, minute, tzinfo=timezone.utc)
    return event


def _session_factory(rows: list[Any]) -> tuple[MagicMock, AsyncMock]:
    db = AsyncMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute.return_value = result
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=db)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session), db


class FindTriggerNodesTest(unittest.TestCase):
    def test_finds_active_heym_trigger_nodes(self) -> None:
        nodes = [
            {"id": "n1", "type": "heymTrigger", "data": {}},
            {"id": "n2", "type": "llm", "data": {}},
            {"id": "n3", "type": "heymTrigger", "data": {"active": False}},
        ]

        found = dispatcher.find_heym_trigger_nodes(nodes)

        self.assertEqual([node["id"] for node in found], ["n1"])

    def test_missing_active_flag_counts_as_active(self) -> None:
        nodes = [{"id": "n1", "type": "heymTrigger", "data": {"active": True}}]

        self.assertEqual(len(dispatcher.find_heym_trigger_nodes(nodes)), 1)


class NodeAcceptsEventTest(unittest.TestCase):
    def test_empty_filter_accepts_every_event(self) -> None:
        node = {"id": "n1", "type": "heymTrigger", "data": {"eventNames": []}}

        self.assertTrue(dispatcher.node_accepts_event(node, "workflow.created"))
        self.assertTrue(dispatcher.node_accepts_event(node, "heym.started"))

    def test_missing_filter_accepts_every_event(self) -> None:
        node = {"id": "n1", "type": "heymTrigger", "data": {}}

        self.assertTrue(dispatcher.node_accepts_event(node, "workflow.deleted"))

    def test_filter_rejects_unlisted_names(self) -> None:
        node = {"id": "n1", "type": "heymTrigger", "data": {"eventNames": ["workflow.updated"]}}

        self.assertTrue(dispatcher.node_accepts_event(node, "workflow.updated"))
        self.assertFalse(dispatcher.node_accepts_event(node, "workflow.created"))


class EventVisibilityTest(unittest.TestCase):
    def test_instance_wide_events_reach_every_owner(self) -> None:
        self.assertTrue(dispatcher.event_visible_to_owner(None, uuid.uuid4()))

    def test_owned_events_reach_only_their_owner(self) -> None:
        owner_id = uuid.uuid4()

        self.assertTrue(dispatcher.event_visible_to_owner(owner_id, owner_id))
        self.assertFalse(dispatcher.event_visible_to_owner(owner_id, uuid.uuid4()))


class BuildTriggerInputsTest(unittest.TestCase):
    def test_events_are_batched_in_created_at_order(self) -> None:
        second = _event("workflow.created", minute=2)
        first = _event("workflow.created", minute=1)

        inputs = dispatcher.build_trigger_inputs("n1", [second, first])

        self.assertEqual(inputs["triggered_by"], "heym_event")
        self.assertEqual(inputs["trigger_node_id"], "n1")
        self.assertEqual(len(inputs["events"]), 2)
        self.assertEqual(inputs["events"][0]["created_at"], "2026-08-11T12:01:00+00:00")
        self.assertEqual(inputs["events"][1]["created_at"], "2026-08-11T12:02:00+00:00")

    def test_single_event_still_arrives_as_an_array(self) -> None:
        inputs = dispatcher.build_trigger_inputs("n1", [_event("heym.started")])

        self.assertIsInstance(inputs["events"], list)
        self.assertEqual(len(inputs["events"]), 1)

    def test_event_entry_shape(self) -> None:
        event = _event("workflow.updated")

        entry = dispatcher.build_trigger_inputs("n1", [event])["events"][0]

        self.assertEqual(set(entry.keys()), {"id", "name", "payload", "workflow_id", "created_at"})
        self.assertEqual(entry["name"], "workflow.updated")
        self.assertEqual(entry["payload"], {"workflow_id": "w1"})


class DispatchWorkflowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.workflow = MagicMock()
        self.workflow.id = uuid.uuid4()
        self.workflow.owner_id = self.owner_id
        self.workflow.nodes = [{"id": "n1", "type": "heymTrigger", "data": {"eventNames": []}}]

    async def test_two_events_in_one_pass_produce_one_run(self) -> None:
        events = [
            _event("workflow.created", owner_id=self.owner_id, minute=1),
            _event("workflow.created", owner_id=self.owner_id, minute=2),
        ]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        run.assert_awaited_once()
        _workflow_arg, node_id, inputs = run.await_args.args
        self.assertEqual(node_id, "n1")
        self.assertEqual(len(inputs["events"]), 2)

    async def test_a_lost_claim_drops_only_that_event(self) -> None:
        events = [
            _event("workflow.created", owner_id=self.owner_id, minute=1),
            _event("workflow.created", owner_id=self.owner_id, minute=2),
        ]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service,
                "claim_heym_event",
                AsyncMock(side_effect=[True, False]),
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        _workflow_arg, _node_id, inputs = run.await_args.args
        self.assertEqual(len(inputs["events"]), 1)

    async def test_no_claims_means_no_run(self) -> None:
        events = [_event("workflow.created", owner_id=self.owner_id)]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=False)
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        run.assert_not_awaited()

    async def test_another_owners_event_is_not_delivered(self) -> None:
        events = [_event("workflow.created", owner_id=uuid.uuid4())]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ) as claim,
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        claim.assert_not_awaited()
        run.assert_not_awaited()

    async def test_filtered_out_events_are_never_claimed(self) -> None:
        self.workflow.nodes = [
            {"id": "n1", "type": "heymTrigger", "data": {"eventNames": ["workflow.deleted"]}}
        ]
        events = [_event("workflow.created", owner_id=self.owner_id)]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ) as claim,
            patch.object(manager, "_run_workflow", AsyncMock()),
        ):
            await manager._dispatch_workflow(self.workflow, events)

        claim.assert_not_awaited()

    async def test_each_subscribing_node_gets_its_own_run(self) -> None:
        self.workflow.nodes = [
            {"id": "n1", "type": "heymTrigger", "data": {}},
            {"id": "n2", "type": "heymTrigger", "data": {}},
        ]
        events = [_event("heym.started")]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ),
            patch.object(manager, "_run_workflow", AsyncMock()) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        self.assertEqual(run.await_count, 2)


class FailedDeliveryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner_id = uuid.uuid4()
        self.workflow = MagicMock()
        self.workflow.id = uuid.uuid4()
        self.workflow.owner_id = self.owner_id
        self.workflow.nodes = [{"id": "n1", "type": "heymTrigger", "data": {}}]

    async def test_a_failed_run_releases_its_claims_for_retry(self) -> None:
        events = [_event("heym.started", minute=1)]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ),
            patch.object(
                dispatcher.heym_event_service, "release_heym_event_claims", AsyncMock()
            ) as release,
            patch.object(manager, "_run_workflow", AsyncMock(side_effect=RuntimeError("reload"))),
        ):
            await manager._dispatch_workflow(self.workflow, events)

        release.assert_awaited_once()
        self.assertEqual(release.await_args.kwargs["event_ids"], [events[0].id])
        self.assertEqual(release.await_args.kwargs["node_id"], "n1")

    async def test_one_failing_node_does_not_stop_the_others(self) -> None:
        self.workflow.nodes = [
            {"id": "n1", "type": "heymTrigger", "data": {}},
            {"id": "n2", "type": "heymTrigger", "data": {}},
        ]
        events = [_event("heym.started")]
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(
                dispatcher.heym_event_service, "claim_heym_event", AsyncMock(return_value=True)
            ),
            patch.object(dispatcher.heym_event_service, "release_heym_event_claims", AsyncMock()),
            patch.object(
                manager, "_run_workflow", AsyncMock(side_effect=[RuntimeError("boom"), None])
            ) as run,
        ):
            await manager._dispatch_workflow(self.workflow, events)

        self.assertEqual(run.await_count, 2)


class TickTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_recent_events_skips_the_workflow_scan(self) -> None:
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(manager, "_get_recent_events", AsyncMock(return_value=[])),
            patch.object(manager, "_get_subscribing_workflows", AsyncMock()) as subscribers,
            patch.object(manager, "_dispatch_workflow", AsyncMock()) as dispatch,
            patch.object(manager, "_maybe_cleanup", AsyncMock()) as cleanup,
        ):
            await manager._tick()

        subscribers.assert_not_awaited()
        dispatch.assert_not_awaited()
        cleanup.assert_awaited_once()

    async def test_recent_events_reach_every_subscribing_workflow(self) -> None:
        events = [_event("heym.started")]
        first, second = MagicMock(), MagicMock()
        manager = dispatcher.HeymEventDispatcher()

        with (
            patch.object(manager, "_get_recent_events", AsyncMock(return_value=events)),
            patch.object(
                manager, "_get_subscribing_workflows", AsyncMock(return_value=[first, second])
            ),
            patch.object(manager, "_dispatch_workflow", AsyncMock()) as dispatch,
            patch.object(manager, "_maybe_cleanup", AsyncMock()) as cleanup,
        ):
            await manager._tick()

        self.assertEqual(
            [call.args for call in dispatch.await_args_list], [(first, events), (second, events)]
        )
        cleanup.assert_awaited_once()


class SubscribingWorkflowsTest(unittest.IsolatedAsyncioTestCase):
    async def test_scan_is_narrowed_in_sql(self) -> None:
        session_factory, db = _session_factory([])

        with patch.object(dispatcher, "async_session_maker", session_factory):
            await dispatcher.HeymEventDispatcher()._get_subscribing_workflows()

        stmt = db.execute.await_args.args[0]
        sql = str(
            stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        self.assertEqual(
            [column.name for column in stmt.selected_columns], ["id", "owner_id", "nodes"]
        )
        self.assertIn("CAST(workflows.nodes AS TEXT) LIKE", sql)
        self.assertIn("'\"heymTrigger\"'", sql)

    async def test_text_match_alone_does_not_subscribe(self) -> None:
        subscribed = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1", "type": "heymTrigger", "data": {}}],
        )
        mentioned_in_a_note = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1", "type": "sticky", "data": {"note": '"heymTrigger"'}}],
        )
        inactive = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "n1", "type": "heymTrigger", "data": {"active": False}}],
        )
        session_factory, _db = _session_factory([subscribed, mentioned_in_a_note, inactive])

        with patch.object(dispatcher, "async_session_maker", session_factory):
            workflows = await dispatcher.HeymEventDispatcher()._get_subscribing_workflows()

        self.assertEqual(workflows, [subscribed])
