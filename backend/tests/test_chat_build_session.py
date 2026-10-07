"""ChatBuildSession: save_workflow, run_workflow_test and finish for one chat turn."""

import json
import unittest
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chat_build
from app.api.ai_assistant import DASHBOARD_CHAT_TOOLS, FileAttachment
from app.db.models import Workflow, WorkflowVersion
from app.services.chat_build_mode import MAX_BUILD_TEST_RUNS, BuildRequest
from app.services.credential_catalog import CredentialPromptMode

DSL = {
    "name": "Lead intake",
    "description": "Saves website leads",
    "nodes": [
        {
            "id": "start",
            "type": "textInput",
            "position": {"x": 0, "y": 0},
            "data": {"label": "start", "inputFields": [{"key": "text"}]},
        },
        {
            "id": "done",
            "type": "output",
            "position": {"x": 300, "y": 0},
            "data": {"label": "result", "message": "$start.text"},
        },
    ],
    "edges": [{"id": "e1", "source": "start", "target": "done"}],
}


def _run_result(status: str = "success") -> str:
    return json.dumps(
        {
            "status": status,
            "outputs": {"result": {"text": "hello"}},
            "node_results": [
                {"node_label": "start", "node_type": "textInput", "status": "success", "output": {}}
            ],
            "execution_time_ms": 420,
            "execution_history_id": str(uuid.uuid4()),
        }
    )


class ChatBuildSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com", user_rules=None)
        self.db = MagicMock()
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()
        self.db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=2)))
        self.runner = AsyncMock(return_value=_run_result())
        self.audit = MagicMock()
        self.announce = AsyncMock()
        self.target: Workflow | None = None
        self.writable = True
        self.stack = ExitStack()
        for name, value in {
            "get_workflow_for_user": AsyncMock(side_effect=self._get_workflow),
            "user_can_write_workflow": AsyncMock(side_effect=lambda *_: self.writable),
            "load_credential_catalog": AsyncMock(return_value=[]),
            "load_data_table_catalog": AsyncMock(return_value=[]),
            "run_execute_workflow_tool": self.runner,
            "audit": self.audit,
            "announce_workflow_saved": self.announce,
        }.items():
            self.stack.enter_context(patch.object(chat_build, name, value))

    def tearDown(self) -> None:
        self.stack.close()

    async def _get_workflow(self, _db: Any, workflow_id: uuid.UUID, _user_id: uuid.UUID) -> Any:
        if self.target is not None and self.target.id == workflow_id:
            return self.target
        added = [c.args[0] for c in self.db.add.call_args_list if isinstance(c.args[0], Workflow)]
        return next((w for w in added if w.id == workflow_id), None)

    def _session(
        self,
        target: uuid.UUID | None = None,
        session_id: str | None = "conv-1",
        attachment: FileAttachment | None = None,
    ) -> chat_build.ChatBuildSession:
        return chat_build.ChatBuildSession(
            db=self.db,
            user=self.user,
            request=BuildRequest(target_workflow_id=target),
            selected_credential=SimpleNamespace(
                id=uuid.uuid4(), owner_id=self.user.id, type="openai"
            ),
            model="gpt-5.5",
            credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=None,
            llm_session_id=session_id,
            attachment=attachment,
        )

    async def test_save_creates_a_workflow_when_the_turn_has_no_target(self) -> None:
        session = self._session()

        outcome = await session.call("save_workflow", {"workflow": DSL})

        created = self.db.add.call_args.args[0]
        self.assertIsInstance(created, Workflow)
        self.assertEqual(created.owner_id, self.user.id)
        payload = json.loads(outcome.result)
        self.assertEqual(payload["status"], "created")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(outcome.events[0]["type"], "workflow_created")
        self.assertTrue(self.announce.call_args.kwargs["created"])
        self.assertEqual(self.audit.call_args.kwargs["action"], "workflow.create")
        self.assertEqual(self.audit.call_args.kwargs["source"], "chat_build")
        self.assertEqual(session.progress.workflow_id, created.id)

    async def test_save_updates_the_target_and_stores_a_version(self) -> None:
        self.target = Workflow(
            id=uuid.uuid4(), owner_id=self.user.id, name="Old", description="", nodes=[], edges=[]
        )
        session = self._session(target=self.target.id)

        outcome = await session.call("save_workflow", {"workflow": DSL})

        version = self.db.add.call_args.args[0]
        self.assertIsInstance(version, WorkflowVersion)
        self.assertEqual(version.version_number, 3)
        self.assertEqual(version.nodes, [])
        self.assertEqual(self.target.name, "Lead intake")
        self.assertEqual(json.loads(outcome.result)["version"], 4)
        self.assertIn("version 4", outcome.summary)
        self.assertEqual(self.audit.call_args.kwargs["action"], "workflow.update")
        self.assertFalse(self.announce.call_args.kwargs["created"])

    async def test_save_refuses_a_read_only_target(self) -> None:
        self.target = Workflow(
            id=uuid.uuid4(), owner_id=uuid.uuid4(), name="Shared", nodes=[], edges=[]
        )
        self.writable = False
        session = self._session(target=self.target.id)

        outcome = await session.call("save_workflow", {"workflow": DSL})

        self.assertEqual(outcome.status, "error")
        self.assertIn("read-only", outcome.result)
        self.db.commit.assert_not_awaited()
        self.assertEqual(self.target.name, "Shared")

    async def test_a_test_run_needs_a_saved_workflow(self) -> None:
        outcome = await self._session().call("run_workflow_test", {"inputs": {}, "expect": "x"})

        self.assertIn("save_workflow before testing", outcome.result)
        self.runner.assert_not_awaited()

    async def test_test_runs_carry_one_session_id_and_stop_at_the_budget(self) -> None:
        self.runner.return_value = _run_result("error")
        session = self._session(session_id="conv-42")
        await session.call("save_workflow", {"workflow": DSL})

        outcomes = [
            await session.call(
                "run_workflow_test", {"inputs": {"text": "hi"}, "expect": "Echoes hi"}
            )
            for _ in range(MAX_BUILD_TEST_RUNS + 1)
        ]

        self.assertEqual(self.runner.await_count, MAX_BUILD_TEST_RUNS)
        session_ids = {c.kwargs["llm_session_id"] for c in self.runner.await_args_list}
        self.assertEqual(session_ids, {"conv-42"})
        first = json.loads(outcomes[0].result)
        self.assertEqual((first["attempt"], first["max_attempts"]), (1, MAX_BUILD_TEST_RUNS))
        self.assertIn("budget_spent", json.loads(outcomes[MAX_BUILD_TEST_RUNS - 1].result))
        self.assertEqual(json.loads(outcomes[-1].result)["status"], "refused")

    async def test_a_missing_session_id_falls_back_to_one_stable_id(self) -> None:
        session = self._session(session_id=None)
        await session.call("save_workflow", {"workflow": DSL})

        await session.call("run_workflow_test", {"inputs": {}, "expect": ""})
        await session.call("run_workflow_test", {"inputs": {}, "expect": ""})

        session_ids = {c.kwargs["llm_session_id"] for c in self.runner.await_args_list}
        self.assertEqual(len(session_ids), 1)
        self.assertTrue(next(iter(session_ids)))
        self.assertNotEqual(self._session(session_id=None).llm_session_id, session.llm_session_id)

    async def test_a_cancelled_run_is_not_counted(self) -> None:
        self.runner.return_value = json.dumps(
            {"status": "cancelled", "error": "Execution cancelled"}
        )
        session = self._session()
        await session.call("save_workflow", {"workflow": DSL})

        outcome = await session.call("run_workflow_test", {"inputs": {}, "expect": ""})

        self.assertEqual(outcome.status, "cancelled")
        self.assertEqual(session.progress.runs_used, 0)

    async def test_an_attached_file_is_the_sample_input_of_a_test_run(self) -> None:
        attachment = FileAttachment(name="leads.csv", kind="text", content="email\na@example.com")
        session = self._session(attachment=attachment)
        await session.call("save_workflow", {"workflow": DSL})

        outcome = await session.call(
            "run_workflow_test", {"inputs": {}, "expect": "Reads one lead"}
        )

        run_inputs = self.runner.await_args.args[3]
        self.assertEqual(run_inputs, {"text": "email\na@example.com"})
        self.assertEqual(json.loads(outcome.result)["inputs"], {})

    async def test_finish_needs_a_passing_run_then_emits_verified(self) -> None:
        session = self._session()
        await session.call("save_workflow", {"workflow": DSL})

        refused = await session.call("finish", {"summary": "Saves leads"})
        await session.call("run_workflow_test", {"inputs": {"text": "hi"}, "expect": "Echoes hi"})
        finished = await session.call("finish", {"summary": "Saves leads"})

        self.assertEqual(refused.status, "error")
        self.assertIsNone(refused.finished_summary)
        self.assertEqual(finished.finished_summary, "Saves leads")
        event = finished.events[0]
        self.assertEqual(event["type"], "verified")
        self.assertEqual(event["workflow_name"], "Lead intake")
        self.assertEqual(event["test_runs"], 1)

    async def test_prompt_adds_instructions_target_and_dsl_reference(self) -> None:
        self.target = Workflow(
            id=uuid.uuid4(), owner_id=self.user.id, name="Lead intake", nodes=DSL["nodes"], edges=[]
        )
        with (
            patch.object(
                chat_build.template_service, "list_node_templates", AsyncMock(return_value=[])
            ),
            patch.object(
                chat_build, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])
            ),
            patch.object(chat_build, "_load_installed_plugins", AsyncMock(return_value=[])),
        ):
            prompt = await self._session(target=self.target.id).prompt()

        self.assertIn("## Build mode", prompt)
        self.assertIn(f'"Lead intake" ({self.target.id})', prompt)
        self.assertIn("## Workflow DSL reference", prompt)
        self.assertIn("## Current Workflow Context", prompt)

    async def test_tools_replace_the_ai_builder_and_follow_the_budget(self) -> None:
        session = self._session()
        names = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]
        self.assertNotIn("create_workflow", names)
        self.assertNotIn("edit_workflow", names)
        self.assertIn("execute_workflow", names)
        self.assertEqual(names[-3:], ["save_workflow", "run_workflow_test", "finish"])

        self.runner.return_value = _run_result("error")
        await session.call("save_workflow", {"workflow": DSL})
        for _ in range(MAX_BUILD_TEST_RUNS):
            await session.call("run_workflow_test", {"inputs": {}, "expect": ""})
        spent = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]
        self.assertFalse({"save_workflow", "run_workflow_test", "finish"} & set(spent))


if __name__ == "__main__":
    unittest.main()
