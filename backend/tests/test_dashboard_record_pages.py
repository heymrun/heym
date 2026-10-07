"""Detail pages: `?record=` is checked against the dashboard's format and cached per record."""

import datetime
import unittest
import uuid
from datetime import timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import dashboards as dash_api
from app.models.dashboard_schemas import DashboardUpdateRequest, WidgetDataResponse
from app.services import dashboard_data
from app.services.page_params import is_valid_record, page_inputs


class RecordFormatTests(unittest.TestCase):
    def test_the_default_format_takes_ids(self) -> None:
        for value in ("ACME-1", "inv_2026.10", "42"):
            with self.subTest(value=value):
                self.assertTrue(is_valid_record(value, "id"))
                self.assertTrue(is_valid_record(value, None))
        for value in ("", "a b", "x/../y", "' OR 1=1 --", "a" * 129):
            with self.subTest(value=value):
                self.assertFalse(is_valid_record(value, "id"))

    def test_the_other_formats(self) -> None:
        self.assertTrue(is_valid_record("1042", "number"))
        self.assertFalse(is_valid_record("10.5", "number"))
        self.assertTrue(is_valid_record("6f6aaf51-0000-4000-8000-000000000001", "uuid"))
        self.assertFalse(is_valid_record("6f6aaf51", "uuid"))
        self.assertTrue(is_valid_record("ada+billing@example.co.uk", "email"))
        self.assertFalse(is_valid_record("ada@localhost", "email"))

    def test_an_unknown_format_accepts_nothing(self) -> None:
        self.assertFalse(is_valid_record("ACME-1", "anything"))


class _User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.name = "Owner"
        self.email = "owner@example.com"


def _widget_lookup(widget: object, dashboard: object) -> MagicMock:
    return MagicMock(one_or_none=MagicMock(return_value=(widget, dashboard)))


class WidgetDataRecordApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = _User()
        self.widget = MagicMock(id=uuid.uuid4())
        self.dashboard = MagicMock(id=uuid.uuid4(), owner_id=self.user.id, record_format="id")
        self.db = MagicMock()
        self.db.execute = AsyncMock(return_value=_widget_lookup(self.widget, self.dashboard))
        self.compute = AsyncMock(
            return_value=WidgetDataResponse(
                widget_id=self.widget.id,
                payload={"type": "numeric"},
                cached=False,
                computed_at=None,
            )
        )

    async def _get(self, record: str | None) -> WidgetDataResponse:
        with patch.object(dash_api, "compute_widget_data", self.compute):
            return await dash_api.get_widget_data(
                widget_id=self.widget.id,
                force=False,
                record=record,
                current_user=self.user,
                db=self.db,
            )

    async def test_a_valid_record_reaches_the_widget_run(self) -> None:
        await self._get("ACME-1")

        self.compute.assert_awaited_once_with(
            self.db, self.widget, self.user.id, force=False, record="ACME-1"
        )

    async def test_a_record_outside_the_format_is_rejected_before_any_run(self) -> None:
        self.dashboard.record_format = "number"

        with self.assertRaises(HTTPException) as caught:
            await self._get("ACME-1")

        self.assertEqual(caught.exception.status_code, 422)
        self.compute.assert_not_awaited()


class DashboardRecordFormatApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_owner_sets_the_record_format_and_keeps_the_name(self) -> None:
        user = _User()
        dashboard = MagicMock(
            id=uuid.uuid4(),
            owner_id=user.id,
            record_format="id",
            updated_at=datetime.datetime.now(),
        )
        dashboard.name = "Customer"
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=dashboard))
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch.object(dash_api, "audit"):
            summary = await dash_api.update_dashboard(
                dashboard_id=dashboard.id,
                body=DashboardUpdateRequest(record_format="email"),
                current_user=user,
                db=db,
            )

        self.assertEqual(dashboard.record_format, "email")
        self.assertEqual(summary.record_format, "email")
        self.assertEqual(summary.name, "Customer")


def _cache_widget(**attrs: object) -> MagicMock:
    widget = MagicMock(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        cache_ttl_seconds=300,
        cached_payload={"type": "bar", "labels": ["page"]},
        cached_at=datetime.datetime.now(timezone.utc),
        cached_workflow_version="2026-01-01T00:00:00+00:00",
    )
    for key, value in attrs.items():
        setattr(widget, key, value)
    return widget


class RecordCacheComputeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.workflow = MagicMock(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            updated_at=datetime.datetime(2026, 1, 1, tzinfo=timezone.utc),
            nodes=[{"id": "c", "type": "chartOutput", "data": {}}],
            edges=[],
        )
        self.workflow.name = "widget"
        self.db = MagicMock()
        self.db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=self.workflow))
        )
        self.db.commit = AsyncMock()
        self.result = MagicMock(
            node_results=[
                {"node_type": "chartOutput", "output": {"type": "bar", "labels": ["ACME-1"]}}
            ],
            outputs={},
            status="success",
            execution_time_ms=5.0,
            allow_downstream_pending=False,
            history_written=True,
        )
        for patcher in (
            patch.object(
                dashboard_data,
                "_load_widget_execution_context",
                AsyncMock(return_value=({}, {}, {})),
            ),
            patch.object(dashboard_data, "_persist_widget_global_variables", AsyncMock()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_a_record_run_gets_the_record_and_leaves_the_page_cache_alone(self) -> None:
        widget = _cache_widget()
        dispatch = AsyncMock(return_value=self.result)
        store = AsyncMock()

        with (
            patch.object(dashboard_data, "dispatch_workflow", dispatch),
            patch.object(dashboard_data, "_load_record_cache", AsyncMock(return_value=None)),
            patch.object(dashboard_data, "store_record_cache", store),
        ):
            response = await dashboard_data.compute_widget_data(
                self.db, widget, uuid.uuid4(), record="ACME-1"
            )

        self.assertEqual(dispatch.call_args.kwargs["inputs"], page_inputs("ACME-1"))
        self.assertEqual(response.payload, {"type": "bar", "labels": ["ACME-1"]})
        self.assertEqual(widget.cached_payload, {"type": "bar", "labels": ["page"]})
        self.assertEqual(store.await_args.args[1:4], (widget.id, "ACME-1", response.payload))

    async def test_a_fresh_record_cache_is_served_without_a_run(self) -> None:
        widget = _cache_widget()
        entry = MagicMock(
            payload={"type": "bar", "labels": ["cached ACME-1"]},
            cached_at=datetime.datetime.now(timezone.utc) - timedelta(seconds=5),
            cached_workflow_version="2026-01-01T00:00:00+00:00",
        )
        dispatch = AsyncMock()

        with (
            patch.object(dashboard_data, "dispatch_workflow", dispatch),
            patch.object(dashboard_data, "_load_record_cache", AsyncMock(return_value=entry)),
        ):
            response = await dashboard_data.compute_widget_data(
                self.db, widget, uuid.uuid4(), record="ACME-1"
            )

        dispatch.assert_not_awaited()
        self.assertTrue(response.cached)
        self.assertEqual(response.payload, {"type": "bar", "labels": ["cached ACME-1"]})

    async def test_the_page_without_a_record_still_uses_the_widget_cache(self) -> None:
        widget = _cache_widget(cached_payload=None)
        dispatch = AsyncMock(return_value=self.result)
        store = AsyncMock()

        with (
            patch.object(dashboard_data, "dispatch_workflow", dispatch),
            patch.object(dashboard_data, "store_record_cache", store),
        ):
            await dashboard_data.compute_widget_data(self.db, widget, uuid.uuid4())

        self.assertEqual(dispatch.call_args.kwargs["inputs"], page_inputs(None))
        self.assertEqual(widget.cached_payload, {"type": "bar", "labels": ["ACME-1"]})
        store.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
