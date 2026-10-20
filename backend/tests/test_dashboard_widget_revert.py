import datetime
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import dashboards as dash_api
from app.models.dashboard_schemas import AiRefineRequest, WidgetRevertRequest
from app.services.widget_page_record import listing_page_context, open_detail_page_context


class _User:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


def _dashboard(owner_id: uuid.UUID) -> MagicMock:
    return MagicMock(id=uuid.uuid4(), owner_id=owner_id, name="Dashboard")


def _widget(chart_type: str = "line") -> MagicMock:
    widget = MagicMock()
    widget.id = uuid.uuid4()
    widget.workflow_id = uuid.uuid4()
    widget.chart_type = chart_type
    widget.position = 0
    widget.title = "W"
    widget.description = None
    widget.layout = {"x": 0, "y": 0, "w": 4, "h": 4}
    widget.cache_ttl_seconds = 300
    widget.link_dashboard_id = None
    widget.link_record_field = None
    widget.link_label_field = None
    widget.cached_payload = {"old": True}
    widget.cached_at = datetime.datetime.now()
    widget.cached_workflow_version = "v"
    return widget


def _widget_row(widget: MagicMock, owner_id: uuid.UUID) -> MagicMock:
    return MagicMock(one_or_none=MagicMock(return_value=(widget, _dashboard(owner_id))))


def _chart(chart_type: str) -> list[dict]:
    return [{"id": "c", "type": "chartOutput", "data": {"chartType": chart_type}}]


async def _refresh(obj: MagicMock) -> None:
    obj.updated_at = datetime.datetime.now()


class TestRevertWidget(unittest.IsolatedAsyncioTestCase):
    def _db(
        self,
        user: _User,
        widget: MagicMock,
        workflow: MagicMock,
        version: MagicMock | None,
        newest: int | None,
    ) -> MagicMock:
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _widget_row(widget, user.id),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=version)),
                MagicMock(scalar=MagicMock(return_value=newest)),
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=_refresh)
        return db

    async def test_restores_the_snapshot_and_keeps_what_it_replaces(self) -> None:
        user = _User()
        widget = _widget("line")
        workflow = MagicMock(id=widget.workflow_id, nodes=_chart("line"), edges=[])
        version = MagicMock(version_number=4, nodes=_chart("bar"), edges=[{"id": "e"}])
        db = self._db(user, widget, workflow, version, newest=4)
        add_version = AsyncMock(return_value=5)

        with (
            patch.object(dash_api, "add_workflow_version", add_version),
            patch.object(dash_api, "audit"),
        ):
            response = await dash_api.revert_widget(
                widget_id=widget.id,
                body=WidgetRevertRequest(version_number=4),
                current_user=user,
                db=db,
            )

        self.assertEqual(workflow.nodes, _chart("bar"))
        self.assertEqual(workflow.edges, [{"id": "e"}])
        self.assertEqual(widget.chart_type, "bar")
        self.assertEqual(response.chart_type, "bar")
        self.assertIsNone(widget.cached_payload)
        self.assertIsNone(widget.cached_workflow_version)
        # The workflow it replaced is stored first, from the nodes it had before the revert.
        add_version.assert_awaited_once()
        self.assertEqual(add_version.await_args.args[2].nodes, _chart("line"))
        db.commit.assert_awaited_once()

    async def test_refuses_when_the_widget_changed_after_that_edit(self) -> None:
        user = _User()
        widget = _widget()
        workflow = MagicMock(id=widget.workflow_id, nodes=_chart("line"), edges=[])
        version = MagicMock(version_number=4, nodes=_chart("bar"), edges=[])
        db = self._db(user, widget, workflow, version, newest=5)
        add_version = AsyncMock()

        with patch.object(dash_api, "add_workflow_version", add_version):
            with self.assertRaises(HTTPException) as ctx:
                await dash_api.revert_widget(
                    widget_id=widget.id,
                    body=WidgetRevertRequest(version_number=4),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(workflow.nodes, _chart("line"))
        add_version.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_unknown_version_is_not_found(self) -> None:
        user = _User()
        widget = _widget()
        workflow = MagicMock(id=widget.workflow_id, nodes=_chart("line"), edges=[])
        db = self._db(user, widget, workflow, None, newest=None)

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.revert_widget(
                widget_id=widget.id,
                body=WidgetRevertRequest(version_number=9),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_a_snapshot_with_a_trigger_node_is_not_restored(self) -> None:
        user = _User()
        widget = _widget()
        workflow = MagicMock(id=widget.workflow_id, nodes=_chart("line"), edges=[])
        version = MagicMock(
            version_number=2,
            nodes=[{"id": "t", "type": "cron", "data": {"label": "hourly"}}, *_chart("bar")],
            edges=[],
        )
        db = self._db(user, widget, workflow, version, newest=2)

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.revert_widget(
                widget_id=widget.id,
                body=WidgetRevertRequest(version_number=2),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(workflow.nodes, _chart("line"))

    async def test_a_file_run_widget_is_refused(self) -> None:
        user = _User()
        widget = _widget(chart_type=dash_api.FILE_RUN_WIDGET_TYPE)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_widget_row(widget, user.id)])

        with self.assertRaises(HTTPException) as ctx:
            await dash_api.revert_widget(
                widget_id=widget.id,
                body=WidgetRevertRequest(version_number=1),
                current_user=user,
                db=db,
            )

        self.assertEqual(ctx.exception.status_code, 400)


class TestRefineAnswersWithThePreviousVersion(unittest.IsolatedAsyncioTestCase):
    async def test_the_answer_names_the_snapshot_to_revert_to(self) -> None:
        from app.db.models import CredentialType

        user = _User()
        widget = _widget("bar")
        workflow = MagicMock(nodes=_chart("bar"), edges=[])
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _widget_row(widget, user.id),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=_refresh)

        with (
            patch.object(
                dash_api,
                "generate_widget_dsl",
                AsyncMock(return_value={"nodes": _chart("line"), "edges": []}),
            ),
            patch.object(
                dash_api,
                "get_credential_for_user",
                AsyncMock(return_value=MagicMock(type=CredentialType.openai)),
            ),
            patch.object(dash_api, "_record_chat_workflow_edit_version", AsyncMock(return_value=7)),
            patch.object(dash_api, "_refine_page_context", AsyncMock(return_value="")),
        ):
            response = await dash_api.ai_refine_widget(
                widget_id=widget.id,
                body=AiRefineRequest(prompt="line it", credential_id=uuid.uuid4(), model="m"),
                current_user=user,
                db=db,
            )

        self.assertEqual(response.previous_version_number, 7)

    async def test_the_prompt_carries_the_page_context(self) -> None:
        from app.db.models import CredentialType

        user = _User()
        widget = _widget("bar")
        workflow = MagicMock(nodes=_chart("bar"), edges=[])
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _widget_row(widget, user.id),
                MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
            ]
        )
        generate = AsyncMock(side_effect=RuntimeError("stop after the prompt"))

        with (
            patch.object(dash_api, "generate_widget_dsl", generate),
            patch.object(
                dash_api,
                "get_credential_for_user",
                AsyncMock(return_value=MagicMock(type=CredentialType.openai)),
            ),
            patch.object(dash_api, "_refine_page_context", AsyncMock(return_value="PAGE KIND")),
        ):
            with self.assertRaises(RuntimeError):
                await dash_api.ai_refine_widget(
                    widget_id=widget.id,
                    body=AiRefineRequest(
                        prompt="line it", credential_id=uuid.uuid4(), model="m", page_kind="detail"
                    ),
                    current_user=user,
                    db=db,
                )

        self.assertEqual(generate.await_args.args[0], "line it\n\nPAGE KIND")


class TestRefinePageContext(unittest.IsolatedAsyncioTestCase):
    async def _context(self, detail: str, page_kind: str | None, prompt: str) -> str:
        user = _User()
        with patch.object(dash_api, "_detail_page_context", AsyncMock(return_value=detail)):
            return await dash_api._refine_page_context(
                MagicMock(), _dashboard(user.id), user, page_kind, prompt
            )

    async def test_a_page_no_table_opens_is_a_listing_page(self) -> None:
        self.assertEqual(await self._context("", None, "sort by name"), listing_page_context())

    async def test_a_page_a_table_opens_keeps_the_detail_context(self) -> None:
        self.assertEqual(await self._context("DETAIL", None, "sort by name"), "DETAIL")

    async def test_the_caller_can_say_the_page_is_a_detail_page(self) -> None:
        self.assertEqual(
            await self._context("", "detail", "sort by name"), open_detail_page_context()
        )
        self.assertEqual(await self._context("DETAIL", "detail", "x"), "DETAIL")

    async def test_the_caller_can_say_the_page_is_a_listing_page(self) -> None:
        self.assertEqual(await self._context("DETAIL", "listing", "x"), listing_page_context())

    async def test_a_request_that_names_the_record_is_not_told_there_is_none(self) -> None:
        self.assertEqual(await self._context("", None, "keep rows where id is $page.record"), "")

    def test_the_listing_note_forbids_the_record_and_the_detail_note_allows_it(self) -> None:
        self.assertIn("$page.record is null", listing_page_context())
        self.assertIn("Do not read $page.record", listing_page_context())
        self.assertIn("one record as $page.record", open_detail_page_context())
        self.assertIn("Never write $page.record.id", open_detail_page_context())


if __name__ == "__main__":
    unittest.main()
