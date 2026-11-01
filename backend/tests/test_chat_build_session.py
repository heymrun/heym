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
from app.db.models import CredentialType, Workflow, WorkflowVersion
from app.services.chat_build_mode import MAX_BUILD_TEST_RUNS, BuildRequest, BuildToolOutcome
from app.services.chat_eval_mode import EVAL_TOOL_NAMES
from app.services.credential_catalog import CatalogCredential, CredentialPromptMode
from app.services.file_sandbox.manifest import FileAccessError

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

AGENT_DSL = {
    "name": "Reply writer",
    "description": "Drafts a reply",
    "nodes": [
        DSL["nodes"][0],
        {
            "id": "writer",
            "type": "agent",
            "position": {"x": 300, "y": 0},
            "data": {
                "label": "writer",
                "credentialId": "YOUR_CREDENTIAL_ID",
                "model": "gpt-4o",
                "userMessage": "$start.text",
            },
        },
    ],
    "edges": [{"id": "e1", "source": "start", "target": "writer"}],
}


WIDGET_DSL = {
    "name": "Open cases",
    "description": "Cases still open",
    "nodes": [
        {
            "id": "rows",
            "type": "set",
            "position": {"x": 0, "y": 0},
            "data": {"label": "rows", "mappings": [{"key": "rows", "value": "$array(1, 2)"}]},
        },
        {
            "id": "chart",
            "type": "chartOutput",
            "position": {"x": 300, "y": 0},
            "data": {"label": "chart", "chartType": "numeric", "dataPath": "rows"},
        },
    ],
    "edges": [{"id": "e1", "source": "rows", "target": "chart"}],
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
        self.queue_saved = AsyncMock()
        self.stack = ExitStack()
        for name, value in {
            "get_workflow_for_user": AsyncMock(side_effect=self._get_workflow),
            "user_can_write_workflow": AsyncMock(side_effect=lambda *_: self.writable),
            "load_credential_catalog": AsyncMock(return_value=[]),
            "load_accessible_credential_ids": AsyncMock(side_effect=self._accessible_ids),
            "load_data_table_catalog": AsyncMock(return_value=[]),
            "run_execute_workflow_tool": self.runner,
            "audit": self.audit,
            "announce_workflow_saved": self.announce,
            "queue_collab_saved": self.queue_saved,
        }.items():
            self.stack.enter_context(patch.object(chat_build, name, value))

    def tearDown(self) -> None:
        self.stack.close()

    async def _accessible_ids(self, _db: Any, _user_id: uuid.UUID) -> set[str]:
        """The catalog's credentials; the chat credential a test selects is among them."""
        return {str(c.id) for c in chat_build.load_credential_catalog.return_value}

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
        selected_credential: Any = None,
        model: str = "gpt-5.5",
    ) -> chat_build.ChatBuildSession:
        return chat_build.ChatBuildSession(
            db=self.db,
            user=self.user,
            request=BuildRequest(target_workflow_id=target),
            selected_credential=selected_credential
            or SimpleNamespace(id=uuid.uuid4(), owner_id=self.user.id, type="openai"),
            model=model,
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

    async def test_saving_an_existing_workflow_tells_its_canvas_room(self) -> None:
        self.target = Workflow(
            id=uuid.uuid4(), owner_id=self.user.id, name="Old", description="", nodes=[], edges=[]
        )
        session = self._session(target=self.target.id)

        await session.call("save_workflow", {"workflow": DSL})

        self.queue_saved.assert_awaited_once()
        self.assertEqual(self.target.id, self.queue_saved.await_args.args[1])
        self.assertIsNone(self.queue_saved.await_args.kwargs["session"])

    async def test_a_new_workflow_has_no_canvas_room_to_tell(self) -> None:
        session = self._session()

        await session.call("save_workflow", {"workflow": DSL})

        self.queue_saved.assert_not_awaited()

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

    async def test_save_changes_an_earlier_workflow_by_id(self) -> None:
        self.target = Workflow(
            id=uuid.uuid4(), owner_id=self.user.id, name="Old", description="", nodes=[], edges=[]
        )
        session = self._session()

        outcome = await session.call(
            "save_workflow", {"workflow_id": str(self.target.id), "workflow": DSL}
        )

        self.assertEqual(json.loads(outcome.result)["status"], "saved")
        self.assertEqual(self.target.name, "Lead intake")
        self.assertEqual(session.progress.workflow_id, self.target.id)

    def _widget_target(self) -> Workflow:
        return Workflow(
            id=uuid.uuid4(),
            owner_id=self.user.id,
            name="Widget",
            description=None,
            kind="dashboard_widget",
            nodes=[],
            edges=[],
        )

    async def test_saving_a_widget_workflow_carries_onto_its_widget(self) -> None:
        self.target = self._widget_target()
        session = self._session()
        sync = AsyncMock()

        with patch.object(chat_build, "sync_dashboard_widget", sync):
            outcome = await session.call(
                "save_workflow", {"workflow_id": str(self.target.id), "workflow": WIDGET_DSL}
            )

        self.assertEqual(json.loads(outcome.result)["status"], "saved")
        sync.assert_awaited_once_with(
            self.db, self.target, renamed=True, described=True, graph_changed=True
        )

    async def test_a_widget_workflow_without_a_chart_is_refused(self) -> None:
        self.target = self._widget_target()
        session = self._session()
        nodes = [n for n in WIDGET_DSL["nodes"] if n["type"] != "chartOutput"]

        outcome = await session.call(
            "save_workflow",
            {
                "workflow_id": str(self.target.id),
                "workflow": {**WIDGET_DSL, "nodes": nodes, "edges": []},
            },
        )

        self.assertEqual(outcome.status, "error")
        self.assertIn("chartOutput", outcome.result)
        self.db.commit.assert_not_awaited()
        self.assertEqual(self.target.nodes, [])

    async def test_save_refuses_another_workflow_on_a_targeted_turn(self) -> None:
        target = uuid.uuid4()
        session = self._session(target=target)

        other = await session.call(
            "save_workflow", {"workflow_id": str(uuid.uuid4()), "workflow": DSL}
        )
        invalid = await session.call("save_workflow", {"workflow_id": "nope", "workflow": DSL})

        self.assertIn(str(target), other.result)
        self.assertIn("UUID", invalid.result)
        self.db.commit.assert_not_awaited()
        self.assertEqual(session.progress.workflow_id, target)

    def _shared_model_credential(self) -> tuple[SimpleNamespace, CatalogCredential]:
        """A Google credential another account shared with this user, set on heym_chat."""
        shared = SimpleNamespace(id=uuid.uuid4(), owner_id=uuid.uuid4(), type=CredentialType.google)
        listed = CatalogCredential(shared.id, "team-gemini", CredentialType.google, shared=True)
        return shared, listed

    async def test_save_gives_a_new_agent_the_shared_chat_credential_and_model(self) -> None:
        shared, listed = self._shared_model_credential()
        chat_build.load_credential_catalog.return_value = [listed]
        session = self._session(selected_credential=shared, model="gemini-2.5-flash")

        await session.call("save_workflow", {"workflow": AGENT_DSL})

        created = self.db.add.call_args.args[0]
        agent = next(n for n in created.nodes if n["type"] == "agent")
        self.assertEqual(agent["data"]["credentialId"], str(shared.id))
        self.assertEqual(agent["data"]["model"], "gemini-2.5-flash")

    async def test_save_keeps_the_model_credential_an_edited_agent_already_has(self) -> None:
        shared, listed = self._shared_model_credential()
        chat_build.load_credential_catalog.return_value = [listed]
        own_credential = str(uuid.uuid4())
        existing_nodes = json.loads(json.dumps(AGENT_DSL["nodes"]))
        existing_nodes[1]["data"].update({"credentialId": own_credential, "model": "gpt-5"})
        self.target = Workflow(
            id=uuid.uuid4(),
            owner_id=self.user.id,
            name="Old",
            description="",
            nodes=existing_nodes,
            edges=AGENT_DSL["edges"],
        )
        session = self._session(
            target=self.target.id, selected_credential=shared, model="gemini-2.5-flash"
        )
        edited = json.loads(json.dumps(AGENT_DSL))
        edited["nodes"][1]["data"]["systemInstruction"] = "Reply in French."

        await session.call("save_workflow", {"workflow": edited})

        agent = self.target.nodes[1]
        self.assertEqual(agent["data"]["credentialId"], own_credential)
        self.assertEqual(agent["data"]["model"], "gpt-5")
        self.assertEqual(agent["data"]["systemInstruction"], "Reply in French.")

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
        self.assertIsNone(self.runner.await_args.kwargs["sample_file_id"])

    async def test_a_drive_file_goes_to_the_upload_trigger_not_into_inputs(self) -> None:
        file_id = uuid.uuid4()
        session = self._session(
            attachment=FileAttachment(name="q3.xlsx", kind="file", file_id=file_id)
        )
        await session.call("save_workflow", {"workflow": DSL})

        await session.call("run_workflow_test", {"inputs": {}, "expect": "Totals"})

        self.assertEqual(self.runner.await_args.args[3], {})
        self.assertEqual(self.runner.await_args.kwargs["sample_file_id"], file_id)

    async def test_a_named_sample_file_is_resolved_for_the_chat_user(self) -> None:
        session = self._session()
        await session.call("save_workflow", {"workflow": DSL})
        picked = uuid.uuid4()
        with patch.object(chat_build, "_resolve_sample_file", return_value=picked) as resolve:
            await session.call(
                "run_workflow_test", {"inputs": {}, "expect": "x", "sample_file": "q3.xlsx"}
            )
        resolve.assert_called_once_with(self.user.id, "q3.xlsx")
        self.assertEqual(self.runner.await_args.kwargs["sample_file_id"], picked)

    async def test_an_unreachable_sample_file_is_refused_before_running(self) -> None:
        session = self._session()
        await session.call("save_workflow", {"workflow": DSL})
        refusal = FileAccessError("File not found or not accessible: x")
        with patch.object(chat_build, "_resolve_sample_file", side_effect=refusal):
            outcome = await session.call(
                "run_workflow_test", {"inputs": {}, "expect": "x", "sample_file": "x"}
            )
        self.assertEqual(outcome.status, "error")
        self.runner.assert_not_awaited()
        self.assertEqual(session.progress.runs_used, 0)

    async def test_the_conversation_file_feeds_only_an_upload_trigger(self) -> None:
        older, latest = uuid.uuid4(), uuid.uuid4()
        session = self._session()
        session.conversation_id = uuid.uuid4()
        workspace = SimpleNamespace(inputs=lambda: [{"id": str(older)}, {"id": str(latest)}])
        upload = SimpleNamespace(nodes=[{"id": "t", "type": "fileUploadTrigger", "data": {}}])
        text = SimpleNamespace(nodes=[{"id": "s", "type": "textInput", "data": {}}])
        with patch.object(chat_build.FileWorkspace, "for_chat", return_value=workspace) as ws:
            self.assertEqual(await session._sample_file_id({}, upload), latest)
            self.assertIsNone(await session._sample_file_id({}, text))
        ws.assert_called_once_with(self.user.id, session.conversation_id)

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
            session = self._session(target=self.target.id)
            prompt = await session.prompt()

        self.assertIn("## Build mode", prompt)
        self.assertIn("## Skills", prompt)
        self.assertIn(f'"Lead intake" ({self.target.id})', prompt)
        self.assertIn("## Current Workflow Context", prompt)
        self.assertIn("## Eval suites", prompt)
        # The DSL reference is the same on every request, so it goes early in the prompt.
        self.assertNotIn("## Workflow DSL reference", prompt)
        self.assertIn("## Workflow DSL reference", session.reference())

    async def test_prompt_reuses_the_workflow_list_it_is_given(self) -> None:
        listed = AsyncMock(return_value=[])
        given = [{"id": str(uuid.uuid4()), "name": "Invoice parser", "input_fields": []}]
        with (
            patch.object(
                chat_build.template_service, "list_node_templates", AsyncMock(return_value=[])
            ),
            patch.object(chat_build, "get_workflows_for_user_with_inputs", listed),
            patch.object(chat_build, "_load_installed_plugins", AsyncMock(return_value=[])),
        ):
            prompt = await self._session().prompt(given)

        listed.assert_not_awaited()
        self.assertIn("Invoice parser", prompt)

    async def test_build_turns_offer_the_eval_tools_and_hand_them_over(self) -> None:
        session = self._session()
        names = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]
        self.assertTrue(EVAL_TOOL_NAMES <= set(names))
        self.assertEqual(names[-3:], ["save_workflow", "run_workflow_test", "finish"])
        self.assertTrue(session.handles("run_eval_suite"))
        self.assertEqual(session.step_label("save_prompt_suite"), "Saving the prompt suite...")
        self.assertEqual(
            session.display_args("save_prompt_suite", {"name": "x", "test_cases": [{}, {}]}),
            {"name": "x", "test_cases": 2},
        )
        outcome = BuildToolOutcome(result="{}", summary="2 suites", status="success")
        with patch.object(session.evals, "call", AsyncMock(return_value=outcome)) as call:
            self.assertIs(await session.call("list_eval_suites", {}), outcome)
        call.assert_awaited_once_with("list_eval_suites", {})

    async def test_skill_only_turns_get_no_eval_tools(self) -> None:
        session = chat_build.ChatBuildSession(
            db=self.db,
            user=self.user,
            request=BuildRequest(skill_only=True),
            selected_credential=SimpleNamespace(
                id=uuid.uuid4(), owner_id=self.user.id, type="openai"
            ),
            model="gpt-5.5",
            credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=None,
            llm_session_id="conv-1",
        )
        names = {t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)}
        self.assertFalse(EVAL_TOOL_NAMES & names)
        self.assertFalse(session.handles("save_prompt_suite"))
        self.assertIsNone(session.evals)

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

    async def test_build_mode_keeps_skill_writes_through_the_budget(self) -> None:
        session = self._session()
        names = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]
        self.assertIn("apply_skill", names)
        self.assertTrue(session.handles("apply_skill"))

        self.runner.return_value = _run_result("error")
        await session.call("save_workflow", {"workflow": DSL})
        for _ in range(MAX_BUILD_TEST_RUNS):
            await session.call("run_workflow_test", {"inputs": {}, "expect": ""})
        spent = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]
        self.assertIn("apply_skill", spent)


if __name__ == "__main__":
    unittest.main()
