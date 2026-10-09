"""The run widget (chart type fileRun): runs an existing workflow from a dashboard.

On a dropped file through file intake, with the values of its start fields, or with none.
"""

import datetime
import unittest
import uuid
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import dashboards as dash_api
from app.config import settings
from app.db.models import Dashboard, DashboardShare, DashboardWidget, User, Workflow
from app.models.dashboard_schemas import (
    AiRefineRequest,
    FileRunSlotRequest,
    WidgetCreateRequest,
    WidgetRunRequest,
)
from app.services import dashboard_data, file_intake_service
from app.services.file_run_widget import FILE_RUN_WIDGET_TYPE, run_widget_payload
from app.services.workflow_access import workflow_access_clause

UPLOAD_NODE = {
    "id": "n1",
    "type": "fileUploadTrigger",
    "data": {"label": "invoice", "maxSizeMb": 5, "allowedTypes": "application/pdf"},
}


class _User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.name = "Editor"
        self.email = "editor@example.com"


def _workflow(nodes: list[dict] | None = None, kind: str = "workflow") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), kind=kind, nodes=[UPLOAD_NODE] if nodes is None else nodes, edges=[]
    )


def _db_with(*results: object) -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    async def refresh(obj: object) -> None:
        obj.id = obj.id or uuid.uuid4()
        obj.position = obj.position or 0
        obj.updated_at = datetime.datetime.now()

    db.refresh = AsyncMock(side_effect=refresh)
    return db


def _scalar(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _widget_row(widget: object, dashboard: object) -> MagicMock:
    return MagicMock(one_or_none=MagicMock(return_value=(widget, dashboard)))


def _file_run_widget() -> MagicMock:
    return MagicMock(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        dashboard_id=uuid.uuid4(),
        title="Invoices",
        description=None,
        chart_type=FILE_RUN_WIDGET_TYPE,
        layout={"x": 0, "y": 0, "w": 4, "h": 3},
        cache_ttl_seconds=300,
        position=0,
        link_dashboard_id=None,
        link_record_field=None,
        link_label_field=None,
    )


FORM_NODE = {
    "id": "t",
    "type": "textInput",
    "data": {"inputFields": [{"key": "vendor"}, {"key": "amount", "defaultValue": "10"}]},
}


class RunWidgetPayloadTests(unittest.TestCase):
    def test_a_file_workflow_describes_the_file_it_takes(self) -> None:
        self.assertEqual(
            run_widget_payload([UPLOAD_NODE], []),
            {
                "type": "fileRun",
                "mode": "file",
                "file_label": "invoice",
                "max_size_mb": 5,
                "allowed_types": ["application/pdf"],
                "input_fields": [],
            },
        )

    def test_a_file_workflow_with_a_text_input_asks_for_its_fields_too(self) -> None:
        payload = run_widget_payload([UPLOAD_NODE, FORM_NODE], [])

        self.assertEqual(payload["mode"], "file")
        self.assertEqual(
            payload["input_fields"],
            [{"key": "vendor", "defaultValue": None}, {"key": "amount", "defaultValue": "10"}],
        )

    def test_a_workflow_with_start_fields_asks_for_them(self) -> None:
        self.assertEqual(
            run_widget_payload([FORM_NODE], []),
            {
                "type": "fileRun",
                "mode": "form",
                "input_fields": [
                    {"key": "vendor", "defaultValue": None},
                    {"key": "amount", "defaultValue": "10"},
                ],
            },
        )

    def test_a_workflow_without_inputs_just_runs(self) -> None:
        cron = {"id": "c", "type": "cron", "data": {}}

        self.assertEqual(
            run_widget_payload([cron], []), {"type": "fileRun", "mode": "run", "input_fields": []}
        )

    def test_uploads_from_a_dashboard_are_dashboard_runs(self) -> None:
        self.assertEqual(file_intake_service.upload_trigger_source("dashboard"), "dashboard")


class CreateFileRunWidgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = _User()
        self.dashboard = MagicMock(id=uuid.uuid4(), owner_id=self.user.id)

    async def _create(self, body: WidgetCreateRequest, access: dict) -> object:
        db = _db_with(_scalar(self.dashboard))

        async def lookup(_db: object, workflow_id: uuid.UUID, user_id: uuid.UUID) -> object:
            return access.get(user_id)

        with (
            patch.object(dash_api, "get_workflow_for_user", lookup),
            patch.object(dash_api, "audit"),
        ):
            response = await dash_api.create_widget(
                dashboard_id=self.dashboard.id, body=body, current_user=self.user, db=db
            )
        return response, db

    def _body(self, workflow_id: uuid.UUID | None) -> WidgetCreateRequest:
        return WidgetCreateRequest(
            title="Invoices", chart_type=FILE_RUN_WIDGET_TYPE, workflow_id=workflow_id
        )

    async def test_the_widget_points_at_the_workflow_without_a_hidden_copy(self) -> None:
        workflow = _workflow()

        response, db = await self._create(self._body(workflow.id), {self.user.id: workflow})

        self.assertEqual(response.workflow_id, workflow.id)
        self.assertEqual(response.chart_type, "fileRun")
        added = [c.args[0] for c in db.add.call_args_list]
        self.assertFalse(any(isinstance(obj, Workflow) for obj in added))

    async def test_a_workflow_is_required(self) -> None:
        cases = [
            (None, {}, 422),
            (uuid.uuid4(), {}, 404),
            (uuid.uuid4(), {self.user.id: _workflow(kind="dashboard_widget")}, 404),
        ]
        for workflow_id, access, status_code in cases:
            with self.subTest(status_code=status_code, access=access):
                with self.assertRaises(HTTPException) as caught:
                    await self._create(self._body(workflow_id), access)
                self.assertEqual(caught.exception.status_code, status_code)

    async def test_a_workflow_without_a_file_upload_trigger_is_taken_too(self) -> None:
        workflow = _workflow(nodes=[FORM_NODE])

        response, _db = await self._create(self._body(workflow.id), {self.user.id: workflow})

        self.assertEqual(response.workflow_id, workflow.id)

    async def test_an_editor_cannot_add_a_workflow_the_owner_cannot_run(self) -> None:
        self.dashboard.owner_id = uuid.uuid4()
        workflow = _workflow()

        with self.assertRaises(HTTPException) as caught:
            with patch.object(dash_api, "dashboard_permission", AsyncMock(return_value="write")):
                await self._create(self._body(workflow.id), {self.user.id: workflow})

        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("owner", caught.exception.detail)


class FileRunWidgetActionsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = _User()
        self.widget = _file_run_widget()
        self.dashboard = MagicMock(id=self.widget.dashboard_id, owner_id=uuid.uuid4())
        self.workflow = _workflow()

    async def test_clone_runs_the_same_workflow(self) -> None:
        db = _db_with(_widget_row(self.widget, self.dashboard), _scalar(self.workflow))

        with (
            patch.object(dash_api, "dashboard_permission", AsyncMock(return_value="write")),
            patch.object(dash_api, "audit"),
        ):
            response = await dash_api.clone_widget(
                widget_id=self.widget.id, current_user=self.user, db=db
            )

        self.assertEqual(response.workflow_id, self.workflow.id)
        added = [c.args[0] for c in db.add.call_args_list]
        self.assertFalse(any(isinstance(obj, Workflow) for obj in added))

    async def test_loading_the_widget_describes_the_file_and_runs_nothing(self) -> None:
        db = _db_with(_widget_row(self.widget, self.dashboard))
        compute = AsyncMock()

        with (
            patch.object(dash_api, "dashboard_permission", AsyncMock(return_value="read")),
            patch.object(
                dash_api, "get_workflow_for_user", AsyncMock(return_value=self.workflow)
            ) as lookup,
            patch.object(dash_api, "compute_widget_data", compute),
        ):
            response = await dash_api.get_widget_data(
                widget_id=self.widget.id,
                force=False,
                record=None,
                current_user=self.user,
                db=db,
            )

        compute.assert_not_awaited()
        lookup.assert_awaited_once_with(db, self.widget.workflow_id, self.dashboard.owner_id)
        self.assertEqual(response.payload["file_label"], "invoice")

    async def test_fine_tune_with_ai_is_refused(self) -> None:
        db = _db_with(_widget_row(self.widget, self.dashboard))

        with patch.object(dash_api, "dashboard_permission", AsyncMock(return_value="write")):
            with self.assertRaises(HTTPException) as caught:
                await dash_api.ai_refine_widget(
                    widget_id=self.widget.id,
                    body=AiRefineRequest(
                        prompt="Make it a bar chart", credential_id=uuid.uuid4(), model="m"
                    ),
                    current_user=self.user,
                    db=db,
                )

        self.assertEqual(caught.exception.status_code, 400)


class FileRunSlotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.viewer = _User()
        self.widget = _file_run_widget()
        self.dashboard = MagicMock(id=self.widget.dashboard_id, owner_id=uuid.uuid4())
        self.slot = SimpleNamespace(
            id=uuid.uuid4(),
            expires_at=datetime.datetime.now(timezone.utc) + timedelta(hours=1),
            max_size_bytes=5 * 1024 * 1024,
            allowed_mime=["application/pdf"],
        )

    async def _mint(
        self, workflow: object, body: FileRunSlotRequest | None = None
    ) -> tuple[object, AsyncMock]:
        db = _db_with(_widget_row(self.widget, self.dashboard))
        mint = AsyncMock(return_value=(self.slot, "secret-token"))
        request = MagicMock(headers={"user-agent": "test"})
        with (
            patch.object(dash_api, "dashboard_permission", AsyncMock(return_value="read")),
            patch.object(dash_api, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(dash_api.file_intake_service, "mint_slot", mint),
            patch.object(dash_api.file_intake_service, "write_audit", AsyncMock()),
            patch.object(dash_api, "get_client_ip", return_value="1.2.3.4"),
            patch.object(dash_api, "build_public_base_url", return_value="http://heym"),
        ):
            response = await dash_api.create_file_run_slot(
                widget_id=self.widget.id,
                request=request,
                body=body,
                current_user=self.viewer,
                db=db,
            )
        return response, mint

    async def test_a_viewer_gets_a_single_use_upload_link(self) -> None:
        workflow = _workflow()

        response, mint = await self._mint(workflow)

        self.assertEqual(response.upload_url, "http://heym/api/file-intake/u/secret-token")
        self.assertEqual(response.max_size_mb, 5)
        self.assertEqual(mint.await_args.kwargs["mint_source"], "dashboard")
        self.assertEqual(mint.await_args.kwargs["created_by_user_id"], self.viewer.id)
        self.assertEqual(mint.await_args.kwargs["workflow_id"], workflow.id)
        self.assertEqual(mint.await_args.kwargs["initial_inputs"], {})

    async def test_the_text_input_fields_travel_on_the_slot(self) -> None:
        workflow = _workflow([UPLOAD_NODE, FORM_NODE])
        body = FileRunSlotRequest(inputs={"vendor": "Acme", "secret": "not a field"})

        _response, mint = await self._mint(workflow, body)

        self.assertEqual(mint.await_args.kwargs["initial_inputs"], {"vendor": "Acme"})

    async def test_no_link_when_the_owner_lost_the_workflow(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._mint(None)

        self.assertEqual(caught.exception.status_code, 404)

    async def test_a_chart_widget_takes_no_files(self) -> None:
        self.widget.chart_type = "bar"

        with self.assertRaises(HTTPException) as caught:
            await self._mint(_workflow())

        self.assertEqual(caught.exception.status_code, 400)


class RunWidgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.viewer = _User()
        self.widget = _file_run_widget()
        self.dashboard = MagicMock(id=self.widget.dashboard_id, owner_id=uuid.uuid4())
        self.run_id = uuid.uuid4()

    async def _run(self, workflow: object, inputs: dict[str, str]) -> tuple[object, AsyncMock]:
        db = _db_with(_widget_row(self.widget, self.dashboard))
        run = AsyncMock(
            return_value=(
                SimpleNamespace(status="success", outputs={"result": "ok"}),
                SimpleNamespace(id=self.run_id),
            )
        )
        with (
            patch.object(dash_api, "dashboard_permission", AsyncMock(return_value="read")),
            patch.object(dash_api, "get_workflow_for_user", AsyncMock(return_value=workflow)),
            patch.object(dash_api, "run_widget_workflow", run),
        ):
            response = await dash_api.run_widget(
                widget_id=self.widget.id,
                body=WidgetRunRequest(inputs=inputs),
                current_user=self.viewer,
                db=db,
            )
        return response, run

    async def test_a_viewer_runs_the_workflow_as_the_owner_with_its_own_fields(self) -> None:
        workflow = _workflow(nodes=[FORM_NODE])

        response, run = await self._run(workflow, {"vendor": "Acme", "injected": "x"})

        run.assert_awaited_once()
        _db, ran, run_as, inputs = run.await_args.args
        self.assertIs(ran, workflow)
        self.assertEqual(run_as, self.dashboard.owner_id)
        self.assertEqual(inputs, {"headers": {}, "query": {}, "body": {"vendor": "Acme"}})
        self.assertEqual(
            (response.run_id, response.status, response.output),
            (self.run_id, "success", {"result": "ok"}),
        )

    async def test_a_file_workflow_takes_a_file_not_fields(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._run(_workflow(), {})

        self.assertEqual(caught.exception.status_code, 400)

    async def test_a_chart_widget_runs_nothing(self) -> None:
        self.widget.chart_type = "bar"

        with self.assertRaises(HTTPException) as caught:
            await self._run(_workflow(nodes=[FORM_NODE]), {})

        self.assertEqual(caught.exception.status_code, 400)

    async def test_no_run_when_the_owner_lost_the_workflow(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._run(None, {})

        self.assertEqual(caught.exception.status_code, 404)


class RunWidgetWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_it_runs_as_the_owner_from_the_dashboard_and_is_recorded(self) -> None:
        owner = uuid.uuid4()
        workflow = SimpleNamespace(id=uuid.uuid4(), nodes=[FORM_NODE], edges=[], name="Invoices")
        result = SimpleNamespace(status="success", outputs={"ok": True})
        history = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock(commit=AsyncMock())
        inputs = {"headers": {}, "query": {}, "body": {"vendor": "Acme"}}
        dispatch = AsyncMock(return_value=result)

        with (
            patch.object(
                dashboard_data,
                "_load_widget_execution_context",
                AsyncMock(return_value=({}, {}, {})),
            ),
            patch.object(dashboard_data, "dispatch_workflow", dispatch),
            patch.object(
                dashboard_data, "_record_widget_execution", AsyncMock(return_value=history)
            ) as record,
            patch.object(dashboard_data, "_persist_widget_global_variables", AsyncMock()),
        ):
            ran, recorded = await dashboard_data.run_widget_workflow(db, workflow, owner, inputs)

        kwargs = dispatch.await_args.kwargs
        self.assertEqual(kwargs["inputs"], inputs)
        self.assertEqual(kwargs["trigger_source"], "dashboard")
        self.assertEqual(kwargs["credentials_owner_id"], owner)
        self.assertEqual(kwargs["actor_user_id"], owner)
        record.assert_awaited_once_with(db, workflow, result, inputs)
        self.assertEqual((ran, recorded), (result, history))
        db.commit.assert_awaited()


class FileRunAccessPostgresTests(unittest.IsolatedAsyncioTestCase):
    """A dashboard write share reaches widget workflows, never a file-run widget's workflow."""

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            await self.engine.dispose()
            self.skipTest("PostgreSQL database is not reachable")
        self.owner = User(email=f"o-{uuid.uuid4()}@example.com", hashed_password="x", name="O")
        self.editor = User(email=f"e-{uuid.uuid4()}@example.com", hashed_password="x", name="E")
        async with AsyncSession(self.engine, expire_on_commit=False) as db:
            db.add_all([self.owner, self.editor])
            await db.flush()
            self.dashboard = Dashboard(owner_id=self.owner.id, name="Ops")
            self.widget_workflow = Workflow(
                name="chart", owner_id=self.owner.id, kind="dashboard_widget", nodes=[], edges=[]
            )
            self.file_workflow = Workflow(
                name="Invoice reader", owner_id=self.owner.id, nodes=[UPLOAD_NODE], edges=[]
            )
            db.add_all([self.dashboard, self.widget_workflow, self.file_workflow])
            await db.flush()
            db.add_all(
                [
                    DashboardWidget(
                        dashboard_id=self.dashboard.id,
                        workflow_id=self.widget_workflow.id,
                        title="Chart",
                    ),
                    DashboardWidget(
                        dashboard_id=self.dashboard.id,
                        workflow_id=self.file_workflow.id,
                        title="Invoices",
                        chart_type=FILE_RUN_WIDGET_TYPE,
                    ),
                    DashboardShare(
                        dashboard_id=self.dashboard.id, user_id=self.editor.id, permission="write"
                    ),
                ]
            )
            await db.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSession(self.engine) as db:
            await db.execute(delete(Dashboard).where(Dashboard.id == self.dashboard.id))
            await db.execute(
                delete(Workflow).where(
                    Workflow.id.in_([self.widget_workflow.id, self.file_workflow.id])
                )
            )
            await db.execute(delete(User).where(User.id.in_([self.owner.id, self.editor.id])))
            await db.commit()
        await self.engine.dispose()

    async def test_the_editor_reaches_the_chart_workflow_only(self) -> None:
        async with AsyncSession(self.engine) as db:
            rows = await db.execute(
                select(Workflow.id).where(
                    Workflow.id.in_([self.widget_workflow.id, self.file_workflow.id]),
                    workflow_access_clause(self.editor.id),
                )
            )

        self.assertEqual(set(rows.scalars().all()), {self.widget_workflow.id})


if __name__ == "__main__":
    unittest.main()
