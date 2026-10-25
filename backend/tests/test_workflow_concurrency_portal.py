"""Portal runs queue too: the stream watches, the plain endpoint waits, cancel reaches held runs."""

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Request

from app.services.workflow_concurrency import Admission, QueueInfo


def _execute_data(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "inputs": {"q": "hi"},
        "conversation_history": [],
        "conversation_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class AdmitPortalRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_held_run_carries_the_conversation(self) -> None:
        from app.api import portal

        captured: dict[str, object] = {}

        async def admit(run: object) -> Admission:
            captured["run"] = run
            return Admission(
                kind="queued", execution_id=run.execution_id, queue=QueueInfo(1, 1, 1, 1)
            )

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "o", "type": "output", "data": {}}],
            edges=[],
            concurrency_limit=1,
            workflow_timeout_seconds=None,
        )
        conversation_id = uuid.uuid4()
        execute_data = _execute_data(
            conversation_history=[SimpleNamespace(role="user", content="earlier")],
            conversation_id=conversation_id,
        )
        with patch.object(portal.workflow_concurrency, "admit", side_effect=admit):
            admission = await portal._admit_portal_run(
                workflow=workflow,
                execution_id=uuid.uuid4(),
                enriched_inputs={"body": {"q": "hi"}},
                execute_data=execute_data,
                workflow_cache={},
            )
        options = captured["run"].run_options
        self.assertEqual(options["conversation_history"], [{"role": "user", "content": "earlier"}])
        self.assertEqual(options["llm_session_id"], str(conversation_id))
        self.assertEqual(captured["run"].trigger_source, "portal")
        self.assertEqual(admission.kind, "queued")

    async def test_no_limit_skips_admission(self) -> None:
        from app.api import portal

        workflow = SimpleNamespace(id=uuid.uuid4(), concurrency_limit=None)
        with patch.object(portal.workflow_concurrency, "admit", AsyncMock()) as admit:
            self.assertIsNone(
                await portal._admit_portal_run(
                    workflow=workflow,
                    execution_id=uuid.uuid4(),
                    enriched_inputs={},
                    execute_data=_execute_data(),
                    workflow_cache={},
                )
            )
        admit.assert_not_awaited()


class PortalSlotReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_slot_is_released_when_the_executor_ends(self) -> None:
        from app.api import portal

        future = asyncio.get_running_loop().create_future()
        execution_id = uuid.uuid4()
        with patch.object(portal.workflow_concurrency, "release", AsyncMock()) as release:
            task = asyncio.create_task(portal._release_slot_after(future, execution_id))
            await asyncio.sleep(0)
            release.assert_not_awaited()
            future.set_result(None)
            await task
        release.assert_awaited_once_with(execution_id)

    async def test_a_failed_executor_still_releases(self) -> None:
        from app.api import portal

        future = asyncio.get_running_loop().create_future()
        future.set_exception(RuntimeError("boom"))
        with patch.object(portal.workflow_concurrency, "release", AsyncMock()) as release:
            await portal._release_slot_after(future, uuid.uuid4())
        release.assert_awaited_once()


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _request() -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {"type": "http", "method": "POST", "path": "/x", "headers": [], "query_string": b""},
        receive,
    )


class PortalCancelHeldTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_held_portal_run_is_cancelled(self) -> None:
        from app.api.portal import portal_cancel_execution

        workflow = SimpleNamespace(id=uuid.uuid4())
        db = AsyncMock()
        # First the portal workflow, then "no portal users" so no session is required.
        db.execute = AsyncMock(side_effect=[_ScalarResult(workflow), _ScalarResult(None)])
        with (
            patch(
                "app.api.portal.workflow_concurrency.cancel_held", AsyncMock(return_value=True)
            ) as cancel_held,
            patch("app.api.portal.cancel_active_execution") as cancel_local,
        ):
            result = await portal_cancel_execution(
                slug="s", execution_id=uuid.uuid4(), request=_request(), db=db
            )
        self.assertEqual(result, {"status": "cancel_requested"})
        cancel_held.assert_awaited_once()
        cancel_local.assert_not_called()


class PortalPlainExecuteWaitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_queued_plain_portal_run_waits_for_its_result(self) -> None:
        from app.api.portal import portal_execute
        from app.services.cluster.run_history import OffloadedRun

        workflow = SimpleNamespace(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            nodes=[{"id": "o", "type": "output", "data": {}}],
            edges=[],
            concurrency_limit=1,
            workflow_timeout_seconds=None,
        )
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_ScalarResult(workflow), _ScalarResult(None)])
        execution_id_holder: dict[str, uuid.UUID] = {}

        async def admit(run: object) -> Admission:
            execution_id_holder["id"] = run.execution_id
            return Admission(
                kind="queued", execution_id=run.execution_id, queue=QueueInfo(1, 1, 1, 1)
            )

        waited = OffloadedRun(status="success", outputs={"answer": 1}, execution_time_ms=4.0)
        with (
            patch("app.api.portal.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.portal.get_credentials_context", AsyncMock(return_value={})),
            patch("app.api.portal.get_global_variables_context", AsyncMock(return_value={})),
            patch("app.api.portal.workflow_concurrency.admit", side_effect=admit),
            patch("app.api.portal.wait_for_result", AsyncMock(return_value=waited)) as wait,
            patch("app.api.portal.register_execution") as register,
        ):
            response = await portal_execute(
                slug="s",
                execute_data=_execute_data(),
                request=_request(),
                db=db,
            )
        register.assert_not_called()
        wait.assert_awaited_once()
        self.assertEqual(response.status, "success")
        self.assertEqual(response.outputs, {"answer": 1})
        self.assertEqual(response.execution_history_id, execution_id_holder["id"])
