import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import alerts as alerts_api
from app.models import alert_schemas
from app.models.alert_schemas import AlertCreate, AlertPreviewRequest, AlertUpdate

MODULE = "app.api.alerts"


def _user(user_id=None):
    return SimpleNamespace(id=user_id or uuid.uuid4(), email="a@b.com")


def _alert_row(owner_id, **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "owner_id": owner_id,
        "name": "Invoice failures",
        "description": None,
        "alert_type": "error_threshold",
        "scope": "workflow",
        "workflow_id": uuid.uuid4(),
        "config": {"window_minutes": 10, "threshold_count": 5},
        "enabled": True,
        "notify_workflow_id": None,
        "state": "ok",
        "renotify_mode": "on_recovery",
        "cooldown_minutes": None,
        "check_interval_seconds": 60,
        "last_evaluated_at": None,
        "last_triggered_at": None,
        "last_observed_value": None,
        "next_check_at": None,
        "created_at": None,
        "updated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _empty_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = []
    db.execute = AsyncMock(return_value=rows)
    return db


class TestCreateAlert(unittest.IsolatedAsyncioTestCase):
    async def test_create_rejects_a_workflow_the_user_cannot_access(self):
        payload = AlertCreate(
            name="X",
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=uuid.uuid4(),
            config={"window_minutes": 10, "threshold_count": 5},
        )
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[])):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.create_alert(payload, db=_empty_db(), current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_create_rejects_an_inaccessible_notify_workflow(self):
        workflow_id = uuid.uuid4()
        payload = AlertCreate(
            name="X",
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=workflow_id,
            notify_workflow_id=uuid.uuid4(),
            config={"window_minutes": 10, "threshold_count": 5},
        )
        with patch(
            f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[workflow_id])
        ):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.create_alert(payload, db=_empty_db(), current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_create_persists_and_returns_the_condition_summary(self):
        user = _user()
        workflow_id = uuid.uuid4()
        payload = AlertCreate(
            name="Invoice failures",
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=workflow_id,
            config={"window_minutes": 10, "threshold_count": 5},
        )
        db = _empty_db()
        with patch(
            f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[workflow_id])
        ):
            response = await alerts_api.create_alert(payload, db=db, current_user=user)
        self.assertEqual(response.condition_summary, "5+ errors in 10m")
        self.assertTrue(response.is_owner)
        db.add.assert_called_once()


class TestUnacknowledgedCount(unittest.IsolatedAsyncioTestCase):
    async def test_no_alert_ids_skips_the_query(self):
        db = _empty_db()
        self.assertEqual(await alerts_api._unacknowledged_counts(db, []), {})
        db.execute.assert_not_called()

    async def test_rows_become_a_per_alert_map(self):
        first, second = uuid.uuid4(), uuid.uuid4()
        db = _empty_db()
        rows = MagicMock()
        rows.all.return_value = [(first, 3), (second, 1)]
        db.execute = AsyncMock(return_value=rows)
        counts = await alerts_api._unacknowledged_counts(db, [first, second])
        self.assertEqual(counts, {first: 3, second: 1})

    async def test_the_count_reaches_the_response(self):
        owner = uuid.uuid4()
        alert = _alert_row(owner, state="triggered")
        response = alerts_api._to_response(alert, current_user_id=owner, unacknowledged_count=4)
        self.assertEqual(response.unacknowledged_count, 4)

    async def test_the_count_defaults_to_zero(self):
        owner = uuid.uuid4()
        response = alerts_api._to_response(_alert_row(owner), current_user_id=owner)
        self.assertEqual(response.unacknowledged_count, 0)


class TestCreateNotifyWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_create_notify_workflow_makes_one_and_links_it(self):
        user = _user()
        payload = AlertCreate(
            name="Invoice failures",
            alert_type="error_threshold",
            scope="system",
            config={"window_minutes": 10, "threshold_count": 5},
            create_notify_workflow=True,
        )
        db = _empty_db()
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[])):
            response = await alerts_api.create_alert(payload, db=db, current_user=user)

        added = [call.args[0] for call in db.add.call_args_list]
        workflows = [obj for obj in added if type(obj).__name__ == "Workflow"]
        self.assertEqual(len(workflows), 1)
        self.assertEqual(workflows[0].name, "Invoice failures notification")
        self.assertIn("Error threshold", workflows[0].description)
        self.assertEqual(response.notify_workflow_id, workflows[0].id)

    async def test_the_new_workflow_is_seeded_with_one_generic_input_node(self):
        # An empty canvas gives the user nothing to attach a Slack node to, but the
        # node must NOT declare the payload's keys: a run can carry one firing or a
        # batch of them, and one event's shape is wrong for an array.
        user = _user()
        payload = AlertCreate(
            name="X",
            alert_type="error_threshold",
            scope="system",
            config={"window_minutes": 10, "threshold_count": 5},
            create_notify_workflow=True,
        )
        db = _empty_db()
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[])):
            await alerts_api.create_alert(payload, db=db, current_user=user)

        workflow = next(
            call.args[0]
            for call in db.add.call_args_list
            if type(call.args[0]).__name__ == "Workflow"
        )
        self.assertEqual(len(workflow.nodes), 1)
        node = workflow.nodes[0]
        self.assertEqual(node["type"], "textInput")
        self.assertEqual(node["data"]["label"], "alert")
        self.assertEqual(node["data"]["inputFields"], [{"key": "text"}])
        self.assertEqual(workflow.edges, [])

    async def test_an_explicit_notify_workflow_wins_over_the_flag(self):
        user = _user()
        notify_id = uuid.uuid4()
        payload = AlertCreate(
            name="X",
            alert_type="error_threshold",
            scope="system",
            config={"window_minutes": 10, "threshold_count": 5},
            notify_workflow_id=notify_id,
            create_notify_workflow=True,
        )
        db = _empty_db()
        with patch(
            f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[notify_id])
        ):
            response = await alerts_api.create_alert(payload, db=db, current_user=user)

        added = [call.args[0] for call in db.add.call_args_list]
        self.assertEqual([obj for obj in added if type(obj).__name__ == "Workflow"], [])
        self.assertEqual(response.notify_workflow_id, notify_id)

    async def test_the_flag_is_off_by_default(self):
        user = _user()
        payload = AlertCreate(
            name="X",
            alert_type="error_threshold",
            scope="system",
            config={"window_minutes": 10, "threshold_count": 5},
        )
        db = _empty_db()
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[])):
            response = await alerts_api.create_alert(payload, db=db, current_user=user)

        added = [call.args[0] for call in db.add.call_args_list]
        self.assertEqual([obj for obj in added if type(obj).__name__ == "Workflow"], [])
        self.assertIsNone(response.notify_workflow_id)


class TestMutationRequiresOwnership(unittest.IsolatedAsyncioTestCase):
    async def test_delete_by_non_owner_is_404(self):
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.delete_alert(uuid.uuid4(), db=_empty_db(), current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_update_by_non_owner_is_404(self):
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.update_alert(
                    uuid.uuid4(), AlertUpdate(name="new"), db=_empty_db(), current_user=_user()
                )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_share_endpoints_require_ownership(self):
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.list_alert_shares(
                    uuid.uuid4(), db=_empty_db(), current_user=_user()
                )
        self.assertEqual(ctx.exception.status_code, 404)


class TestUpdateRevalidatesTheMergedResult(unittest.IsolatedAsyncioTestCase):
    async def test_switching_to_cooldown_without_minutes_is_422(self):
        owner = _user()
        row = _alert_row(owner.id)
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=row)):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.update_alert(
                    row.id,
                    AlertUpdate(renotify_mode="cooldown"),
                    db=_empty_db(),
                    current_user=owner,
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_switching_to_system_scope_clears_the_workflow(self):
        owner = _user()
        row = _alert_row(owner.id)
        db = _empty_db()
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=row)):
            with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[])):
                response = await alerts_api.update_alert(
                    row.id,
                    AlertUpdate(scope="system", workflow_id=None),
                    db=db,
                    current_user=owner,
                )
        self.assertEqual(response.scope, "system")
        self.assertIsNone(response.workflow_id)

    async def test_reenabling_resets_next_check_and_state(self):
        owner = _user()
        row = _alert_row(owner.id, enabled=False, state="triggered")
        with patch(f"{MODULE}.get_owned_alert", new=AsyncMock(return_value=row)):
            await alerts_api.update_alert(
                row.id, AlertUpdate(enabled=True), db=_empty_db(), current_user=owner
            )
        self.assertEqual(row.state, "ok")
        self.assertIsNotNone(row.next_check_at)


class TestGetAlert(unittest.IsolatedAsyncioTestCase):
    async def test_shared_viewer_gets_is_owner_false(self):
        owner_id = uuid.uuid4()
        viewer = _user()
        row = _alert_row(owner_id)
        with patch(f"{MODULE}.get_accessible_alert", new=AsyncMock(return_value=row)):
            response = await alerts_api.get_alert(row.id, db=_empty_db(), current_user=viewer)
        self.assertFalse(response.is_owner)

    async def test_inaccessible_alert_is_404(self):
        with patch(f"{MODULE}.get_accessible_alert", new=AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.get_alert(uuid.uuid4(), db=_empty_db(), current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)


class TestPreview(unittest.IsolatedAsyncioTestCase):
    async def test_preview_backtests_and_reports_fire_count(self):
        workflow_id = uuid.uuid4()
        payload = AlertPreviewRequest(
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=workflow_id,
            config={"window_minutes": 60, "threshold_count": 5},
            lookback_hours=3,
        )
        observations = [
            SimpleNamespace(observed_value=9.0, threshold_value=5.0, breached=True, context={}),
            SimpleNamespace(observed_value=9.0, threshold_value=5.0, breached=True, context={}),
            SimpleNamespace(observed_value=1.0, threshold_value=5.0, breached=False, context={}),
            SimpleNamespace(observed_value=7.0, threshold_value=5.0, breached=True, context={}),
        ]
        with patch(
            f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[workflow_id])
        ):
            with patch(f"{MODULE}.observe_config", new=AsyncMock(side_effect=observations)):
                response = await alerts_api.preview_alert(
                    payload, db=_empty_db(), current_user=_user()
                )
        self.assertEqual(response.backtest_fire_count, 2)
        self.assertEqual(response.backtest_max_observed, 9.0)
        self.assertTrue(response.would_fire_now)
        self.assertEqual(response.lookback_hours, 3)

    async def test_preview_rejects_an_inaccessible_workflow(self):
        payload = AlertPreviewRequest(
            alert_type="error_threshold",
            scope="workflow",
            workflow_id=uuid.uuid4(),
            config={"window_minutes": 60, "threshold_count": 5},
        )
        with patch(f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[])):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.preview_alert(payload, db=_empty_db(), current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_backtest_step_count_is_capped(self):
        """A 1-minute window over 168 hours must not issue 10,080 queries."""
        payload = AlertPreviewRequest(
            alert_type="execution_count",
            scope="system",
            config={"window_minutes": 1, "threshold_count": 1},
            lookback_hours=168,
        )
        calls = {"n": 0}

        async def _observe(*_args, **_kwargs):
            calls["n"] += 1
            return SimpleNamespace(
                observed_value=0.0, threshold_value=1.0, breached=False, context={}
            )

        with patch(f"{MODULE}.observe_config", new=_observe):
            await alerts_api.preview_alert(payload, db=_empty_db(), current_user=_user())

        self.assertLessEqual(calls["n"], alerts_api.MAX_BACKTEST_STEPS + 1)


class TestTestEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_test_endpoint_does_not_write_an_event(self):
        import datetime as dt

        owner = _user()
        row = _alert_row(owner.id)
        db = _empty_db()
        observation = SimpleNamespace(
            observed_value=12.0, threshold_value=5.0, breached=True, context={"error_count": 12}
        )
        now = dt.datetime(2026, 8, 9, 12, 0, tzinfo=dt.timezone.utc)
        with patch(f"{MODULE}.get_accessible_alert", new=AsyncMock(return_value=row)):
            with patch(
                f"{MODULE}.observe",
                new=AsyncMock(return_value=(observation, now - dt.timedelta(minutes=10), now)),
            ):
                response = await alerts_api.test_alert(row.id, db=db, current_user=owner)

        self.assertTrue(response.would_fire_now)
        self.assertEqual(response.observed_value, 12.0)
        self.assertEqual(response.backtest_fire_count, 0)
        db.add.assert_not_called()


class TestAiDraftRoute(unittest.IsolatedAsyncioTestCase):
    """The route drives the *synchronous* OpenAI client off the event loop.

    Awaiting client.chat.completions.create directly compiles fine but raises
    TypeError at runtime, which the route converts into a 502. A MagicMock client
    here reproduces that: it is only awaitable via asyncio.to_thread.
    """

    def _request(self):
        return alert_schemas.AlertDraftRequest(
            prompt="warn me if invoice sync fails 5 times in 10 minutes",
            credential_id=uuid.uuid4(),
            model="gpt-4o-mini",
        )

    def _client_returning(self, content):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )
        return client

    async def _call(self, client, *, workflow_id, db=None):
        with (
            patch(
                "app.services.credential_access.get_accessible_credential",
                new=AsyncMock(return_value=SimpleNamespace(type="openai", encrypted_config="x")),
            ),
            patch("app.services.encryption.decrypt_config", return_value={"api_key": "k"}),
            patch("app.api.ai_assistant.get_openai_client", return_value=(client, "OpenAI")),
            patch(
                f"{MODULE}.get_accessible_workflow_ids", new=AsyncMock(return_value=[workflow_id])
            ),
            patch(f"{MODULE}._workflow_names", new=AsyncMock(return_value={workflow_id: "Sync"})),
        ):
            return await alerts_api.draft_alert_from_prompt(
                self._request(), db=db or _empty_db(), current_user=_user()
            )

    async def test_the_call_is_recorded_as_an_llm_trace(self):
        # Without this the Alerts wizard spends tokens that never show up in Traces.
        workflow_id = uuid.uuid4()
        client = self._client_returning('{"alert_type": "execution_count"}')
        client.chat.completions.create.return_value.usage = SimpleNamespace(
            prompt_tokens=120, completion_tokens=30, total_tokens=150
        )
        with patch(f"{MODULE}.record_llm_trace") as recorder:
            await self._call(client, workflow_id=workflow_id)

        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        self.assertEqual(kwargs["context"].source, "alert_builder")
        self.assertEqual(kwargs["total_tokens"], 150)
        self.assertIsNone(kwargs["error"] if "error" in kwargs else None)

    async def test_a_provider_failure_is_still_traced(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("upstream down")
        with patch(f"{MODULE}.record_llm_trace") as recorder:
            with self.assertRaises(HTTPException):
                await self._call(client, workflow_id=uuid.uuid4())

        recorder.assert_called_once()
        self.assertIn("upstream down", recorder.call_args.kwargs["error"])

    async def test_sync_client_is_driven_without_awaiting_it(self):
        workflow_id = uuid.uuid4()
        client = self._client_returning(
            '{"name": "Invoice failures", "alert_type": "error_threshold", "scope": "workflow",'
            f' "workflow_id": "{workflow_id}",'
            ' "config": {"window_minutes": 10, "threshold_count": 5}}'
        )
        response = await self._call(client, workflow_id=workflow_id)
        self.assertIsNotNone(response.draft)
        self.assertEqual(response.draft.workflow_id, workflow_id)
        client.chat.completions.create.assert_called_once()

    async def test_a_workflow_the_user_cannot_access_is_dropped_not_fatal(self):
        # The id is stripped but the condition the model got right survives, so the
        # wizard opens on Scope instead of making the user start over.
        client = self._client_returning(
            '{"name": "X", "alert_type": "error_threshold", "scope": "workflow",'
            f' "workflow_id": "{uuid.uuid4()}",'
            ' "config": {"window_minutes": 10, "threshold_count": 5}}'
        )
        response = await self._call(client, workflow_id=uuid.uuid4())
        self.assertIsNotNone(response.draft)
        self.assertIsNone(response.draft.workflow_id)
        self.assertEqual(response.draft.config["threshold_count"], 5)
        self.assertIn("workflow", response.clarification)

    async def test_provider_failure_is_a_502(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("upstream down")
        with self.assertRaises(HTTPException) as ctx:
            await self._call(client, workflow_id=uuid.uuid4())
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_missing_credential_is_a_404(self):
        with patch(
            "app.services.credential_access.get_accessible_credential",
            new=AsyncMock(return_value=None),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await alerts_api.draft_alert_from_prompt(
                    self._request(), db=_empty_db(), current_user=_user()
                )
        self.assertEqual(ctx.exception.status_code, 404)


class TestAcknowledge(unittest.IsolatedAsyncioTestCase):
    async def test_acknowledge_requires_access_to_the_parent_alert(self):
        db = _empty_db()
        result = MagicMock()
        result.first.return_value = None
        db.execute = AsyncMock(return_value=result)
        with self.assertRaises(HTTPException) as ctx:
            await alerts_api.acknowledge_alert_event(uuid.uuid4(), db=db, current_user=_user())
        self.assertEqual(ctx.exception.status_code, 404)
