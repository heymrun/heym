"""Quick Drawer file inputs: the drawer learns a workflow takes a file, and file runs are its runs."""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import workflows as workflows_api
from app.api.file_intake import upload_to_slot
from app.db.models import ExecutionHistory
from app.services import file_intake_service

UPLOAD_NODE = {
    "id": "n1",
    "type": "fileUploadTrigger",
    "data": {"label": "invoice", "maxSizeMb": 5, "allowedTypes": "application/pdf, .csv"},
}


def _workflow(nodes: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Invoice reader",
        description=None,
        nodes=nodes,
        edges=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        sse_enabled=False,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        cache_ttl_seconds=None,
    )


class FileInputTests(unittest.TestCase):
    def test_a_file_upload_trigger_describes_its_file(self) -> None:
        file_input = workflows_api.extract_file_input_from_workflow(_workflow([UPLOAD_NODE]))

        self.assertEqual(file_input.label, "invoice")
        self.assertEqual(file_input.max_size_mb, 5)
        self.assertEqual(file_input.allowed_types, ["application/pdf", ".csv"])

    def test_a_workflow_without_one_takes_no_file(self) -> None:
        text_input = {"id": "t", "type": "textInput", "data": {"label": "start"}}

        self.assertIsNone(workflows_api.extract_file_input_from_workflow(_workflow([text_input])))


class WithInputsFileInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_list_carries_the_file_input(self) -> None:
        rows = MagicMock()
        rows.scalars.return_value.all.return_value = [_workflow([UPLOAD_NODE])]
        db = MagicMock()
        db.execute = AsyncMock(return_value=rows)

        listed = await workflows_api.list_workflows_with_inputs(
            current_user=SimpleNamespace(id=uuid.uuid4()), db=db
        )

        self.assertEqual(listed[0].file_input.label, "invoice")
        self.assertEqual(listed[0].input_fields, [])


class SlotOriginTests(unittest.TestCase):
    def test_the_quick_drawer_mints_its_own_slots(self) -> None:
        self.assertEqual(
            file_intake_service.mint_source_for("Quick Drawer", "canvas"), "quick_drawer"
        )
        self.assertEqual(file_intake_service.mint_source_for("Canvas", "canvas"), "canvas")
        self.assertEqual(file_intake_service.mint_source_for(None, "http"), "http")

    def test_uploads_are_recorded_under_their_origin(self) -> None:
        self.assertEqual(file_intake_service.upload_trigger_source("quick_drawer"), "Quick Drawer")
        self.assertEqual(file_intake_service.upload_trigger_source("http"), "file_upload")
        self.assertEqual(file_intake_service.upload_trigger_source(None), "file_upload")


class StreamMintTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_quick_drawer_run_mints_a_quick_drawer_slot(self) -> None:
        workflow = _workflow([UPLOAD_NODE])
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=workflow))
        )
        db.commit = AsyncMock()
        slot = SimpleNamespace(
            id=uuid.uuid4(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            max_size_bytes=5 * 1024 * 1024,
            allowed_mime=["application/pdf"],
        )
        mint = AsyncMock(return_value=(slot, "token"))
        user = SimpleNamespace(id=uuid.uuid4())

        with (
            patch.object(
                workflows_api,
                "parse_execute_body",
                AsyncMock(return_value=({}, False, "Quick Drawer", True)),
            ),
            patch.object(workflows_api, "validate_workflow_auth", AsyncMock(return_value=user)),
            patch.object(workflows_api, "enforce_workflow_http_method"),
            patch.object(workflows_api, "get_client_ip", return_value="127.0.0.1"),
            patch.object(workflows_api, "build_public_base_url", return_value="http://heym"),
            patch.object(workflows_api.file_intake_service, "mint_slot", mint),
            patch.object(workflows_api.file_intake_service, "write_audit", AsyncMock()),
        ):
            await workflows_api.execute_workflow_stream(
                workflow_id=workflow.id,
                request=MagicMock(headers={}, query_params={}),
                current_user=user,
                db=db,
                run_until_node_id=None,
            )

        self.assertEqual(mint.await_args.kwargs["mint_source"], "quick_drawer")


class QuickDrawerUploadHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_run_an_upload_starts_is_a_quick_drawer_run(self) -> None:
        slot = MagicMock(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            status="pending",
            max_size_bytes=5 * 1024 * 1024,
            allowed_mime=None,
            trigger_node_id="n1",
            trigger_node_label="invoice",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            mint_source="quick_drawer",
        )
        workflow = SimpleNamespace(
            id=slot.workflow_id, owner_id=uuid.uuid4(), nodes=[UPLOAD_NODE], edges=[]
        )
        consumed = MagicMock(rowcount=1)
        db = AsyncMock()
        db.add = MagicMock()
        db.execute.side_effect = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=slot)),
            consumed,
            MagicMock(scalar_one_or_none=MagicMock(return_value=workflow)),
        ]
        stored = SimpleNamespace(
            id=uuid.uuid4(), filename="inv.pdf", mime_type="application/pdf", size_bytes=3
        )
        result = SimpleNamespace(
            outputs={"total": 42}, node_results=[], status="success", execution_time_ms=8.0
        )
        request = MagicMock(headers={}, base_url="http://heym/")
        request.client = SimpleNamespace(host="1.2.3.4")

        with (
            patch("app.api.file_intake.file_storage.store_file", AsyncMock(return_value=stored)),
            patch("app.api.file_intake.execute_workflow", return_value=result),
            patch("app.api.mcp.get_credentials_context_for_user", AsyncMock(return_value={})),
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            await upload_to_slot(
                token="t",
                request=request,
                file=SimpleNamespace(
                    read=AsyncMock(return_value=b"pdf"),
                    filename="inv.pdf",
                    content_type="application/pdf",
                ),
                db=db,
            )

        history = next(
            c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], ExecutionHistory)
        )
        self.assertEqual(history.trigger_source, "Quick Drawer")


if __name__ == "__main__":
    unittest.main()
