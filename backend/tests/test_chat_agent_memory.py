"""insert_agent_memory in chat build mode: ask for the text, insert, turn memory on."""

import json
import unittest
import uuid
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import chat_agent_memory, chat_build
from app.api.ai_assistant import DASHBOARD_CHAT_TOOLS
from app.db.models import Workflow
from app.models.agent_memory_schemas import MemoryAiInsertResponse, MemoryGraphResponse
from app.services.agent_memory_service import AI_INSERT_MAX_TEXT_CHARS
from app.services.chat_build_mode import (
    INSERT_AGENT_MEMORY_TOOL,
    BuildRequest,
    build_mode_instructions,
)
from app.services.credential_catalog import CredentialPromptMode
from app.services.mcp_elicitation import (
    FormElicitationReply,
    MCPClientChannel,
    form_elicitations,
)

CREDENTIAL_ID = str(uuid.uuid4())
TEXT = "Ada Lovelace is the CTO of Acme. Acme is based in Berlin."


def _agent(node_id: str, label: str, **data: Any) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "agent",
        "position": {"x": 0, "y": 0},
        "data": {"label": label, "credentialId": CREDENTIAL_ID, "model": "gpt-test", **data},
    }


def _inserted(entities: int = 2, relationships: int = 1) -> MemoryAiInsertResponse:
    return MemoryAiInsertResponse(
        graph=MemoryGraphResponse(nodes=[], edges=[]),
        entities_applied=entities,
        relationships_applied=relationships,
    )


class FormClient:
    """An MCP client that declared form elicitation and answers every form with `reply`."""

    def __init__(self, user_id: uuid.UUID, action: str | None, content: dict | None = None):
        self.user_id = user_id
        self.action = action
        self.content = content or {}
        self.sent: list[dict[str, Any]] = []

    async def send(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)
        if self.action is None:
            return
        elicitation_id = uuid.UUID(payload["id"].removeprefix("heym-form-"))
        form_elicitations.resolve(
            self.user_id, FormElicitationReply(elicitation_id, self.action, self.content)
        )

    def channel(self, modes: frozenset[str] = frozenset({"form"})) -> MCPClientChannel:
        return MCPClientChannel(modes, self.send)


class MemoryAgentHelpersTests(unittest.TestCase):
    def test_agents_carry_their_memory_flag_credential_and_model(self) -> None:
        agents = chat_agent_memory.memory_agents(
            [
                {"id": "start", "type": "textInput", "data": {"label": "start"}},
                _agent("a1", "support", persistentMemoryEnabled=True),
                _agent("a2", "writer", model="  "),
            ]
        )
        self.assertEqual([a.id for a in agents], ["a1", "a2"])
        self.assertTrue(agents[0].memory_enabled)
        self.assertFalse(agents[1].memory_enabled)
        self.assertEqual(agents[1].model, "")

    def test_pick_agent_by_id_label_or_the_only_one(self) -> None:
        agents = chat_agent_memory.memory_agents([_agent("a1", "Support"), _agent("a2", "writer")])
        self.assertEqual(chat_agent_memory.pick_agent(agents, "a2").id, "a2")
        self.assertEqual(chat_agent_memory.pick_agent(agents, "support").id, "a1")
        self.assertIsNone(chat_agent_memory.pick_agent(agents, None))
        self.assertIsNone(chat_agent_memory.pick_agent(agents, "nobody"))
        self.assertEqual(chat_agent_memory.pick_agent(agents[:1], None).id, "a1")

    def test_turning_memory_on_copies_the_nodes(self) -> None:
        nodes = [_agent("a1", "support"), _agent("a2", "writer")]
        updated = chat_agent_memory.nodes_with_memory_on(nodes, "a2")
        self.assertTrue(updated[1]["data"]["persistentMemoryEnabled"])
        self.assertNotIn("persistentMemoryEnabled", updated[0]["data"])
        self.assertNotIn("persistentMemoryEnabled", nodes[1]["data"])

    def test_the_question_names_the_agent_and_says_memory_turns_on(self) -> None:
        off, on = chat_agent_memory.memory_agents(
            [_agent("a1", "support"), _agent("a2", "writer", persistentMemoryEnabled=True)]
        )
        question = chat_agent_memory.text_question("Help desk", off)
        self.assertIn('What should agent "support" in "Help desk" remember?', question)
        self.assertIn("24,000 characters", question)
        self.assertIn("turns on with this insert", question)
        self.assertNotIn("turns on", chat_agent_memory.text_question("Help desk", on))

    def test_the_form_is_one_free_text_field(self) -> None:
        schema = chat_agent_memory.text_schema("support")
        self.assertEqual(list(schema["properties"]), ["text"])
        field = schema["properties"]["text"]
        self.assertEqual(field["type"], "string")
        self.assertEqual(field["maxLength"], AI_INSERT_MAX_TEXT_CHARS)
        self.assertEqual(schema["required"], ["text"])

    def test_build_instructions_name_the_tool(self) -> None:
        self.assertIn(INSERT_AGENT_MEMORY_TOOL, build_mode_instructions(None, None))


class InsertAgentMemoryToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com")
        self.db = MagicMock()
        self.db.commit = AsyncMock()
        self.db.refresh = AsyncMock()
        self.db.rollback = AsyncMock()
        self.workflow = Workflow(
            id=uuid.uuid4(),
            owner_id=self.user.id,
            name="Help desk",
            description="",
            nodes=[_agent("a1", "support")],
            edges=[],
        )
        self.writable = True
        self.insert = AsyncMock(return_value=_inserted())
        self.add_version = AsyncMock(return_value=3)
        self.audit = MagicMock()
        self.announce = AsyncMock()
        self.queue_saved = AsyncMock()
        self.stack = ExitStack()
        self.stack.enter_context(
            patch.object(
                chat_build,
                "get_workflow_for_user",
                AsyncMock(side_effect=self._get_workflow),
            )
        )
        self.stack.enter_context(
            patch.object(
                chat_build,
                "user_can_write_workflow",
                AsyncMock(side_effect=lambda *_: self.writable),
            )
        )
        for name, value in {
            "insert_memory_text": self.insert,
            "add_workflow_version": self.add_version,
            "audit": self.audit,
            "announce_workflow_saved": self.announce,
            "queue_collab_saved": self.queue_saved,
        }.items():
            self.stack.enter_context(patch.object(chat_agent_memory, name, value))

    def tearDown(self) -> None:
        self.stack.close()

    async def _get_workflow(self, _db: Any, workflow_id: uuid.UUID, _user_id: uuid.UUID) -> Any:
        return self.workflow if workflow_id == self.workflow.id else None

    def _session(
        self,
        *,
        client: MCPClientChannel | None = None,
        skill_only: bool = False,
        target: uuid.UUID | None = None,
    ) -> chat_build.ChatBuildSession:
        return chat_build.ChatBuildSession(
            db=self.db,
            user=self.user,
            request=BuildRequest(target_workflow_id=target, skill_only=skill_only),
            selected_credential=SimpleNamespace(id=uuid.uuid4(), owner_id=self.user.id),
            model="gpt-5.5",
            credential_mode=CredentialPromptMode.ASK_AND_LINK
            if client is not None
            else CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=None,
            llm_session_id="conv-1",
            credential_form=SimpleNamespace(client=client) if client is not None else None,
        )

    async def _call(
        self, session: chat_build.ChatBuildSession, **args: Any
    ) -> tuple[Any, dict[str, Any]]:
        args.setdefault("workflow_id", str(self.workflow.id))
        args.setdefault("text", TEXT)
        outcome = await session.call(INSERT_AGENT_MEMORY_TOOL, args)
        return outcome, json.loads(outcome.result)

    def _memory_on(self) -> bool:
        return bool(self.workflow.nodes[0]["data"].get("persistentMemoryEnabled"))

    async def test_build_turns_offer_the_tool_and_skill_only_turns_do_not(self) -> None:
        session = self._session()
        names = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]
        self.assertIn(INSERT_AGENT_MEMORY_TOOL, names)
        self.assertEqual(names[-3:], ["save_workflow", "run_workflow_test", "finish"])
        self.assertTrue(session.handles(INSERT_AGENT_MEMORY_TOOL))
        self.assertEqual(
            session.step_label(INSERT_AGENT_MEMORY_TOOL), "Inserting into agent memory..."
        )

        skill_only = self._session(skill_only=True)
        skill_names = {t["function"]["name"] for t in skill_only.tools(DASHBOARD_CHAT_TOOLS)}
        self.assertNotIn(INSERT_AGENT_MEMORY_TOOL, skill_names)
        self.assertFalse(skill_only.handles(INSERT_AGENT_MEMORY_TOOL))

    async def test_step_rows_show_the_length_never_the_text(self) -> None:
        shown = self._session().display_args(INSERT_AGENT_MEMORY_TOOL, {"text": TEXT})
        self.assertEqual(shown["characters"], len(TEXT))
        self.assertNotIn(TEXT, json.dumps(shown))

    async def test_an_insert_turns_memory_on_in_the_same_commit(self) -> None:
        session = self._session()
        session.progress.record_save(self.workflow.id)
        revision = session.progress.revision

        outcome, payload = await self._call(session)

        self.assertEqual(outcome.status, "success")
        self.assertEqual(payload["status"], "inserted")
        self.assertTrue(payload["memory_turned_on"])
        self.assertEqual(payload["version"], 4)
        self.assertEqual(
            outcome.summary, "Inserted 2 entities and 1 relationship · memory turned on"
        )
        kwargs = self.insert.await_args.kwargs
        self.assertEqual(kwargs["node_id"], "a1")
        self.assertEqual(kwargs["credential_id"], uuid.UUID(CREDENTIAL_ID))
        self.assertEqual(kwargs["model"], "gpt-test")
        self.assertEqual(kwargs["text"], TEXT)
        # The conversation's OpenCode session, as every model call of the turn.
        self.assertEqual(kwargs["session_id"], "conv-1")
        self.assertTrue(self._memory_on())
        self.add_version.assert_awaited_once()
        self.db.commit.assert_awaited_once()
        self.queue_saved.assert_awaited_once()
        self.announce.assert_awaited_once_with(self.workflow, self.user.id, created=False)
        actions = [c.kwargs["action"] for c in self.audit.call_args_list]
        self.assertEqual(actions, ["workflow.update", "agent_memory.insert"])
        audited = json.dumps([c.kwargs for c in self.audit.call_args_list], default=str)
        self.assertNotIn(TEXT, audited)
        self.assertEqual(outcome.events[0]["type"], "workflow_created")
        # The save changed the workflow the build tested, so finish needs a new passing run.
        self.assertEqual(session.progress.revision, revision + 1)

    async def test_memory_already_on_inserts_without_a_save(self) -> None:
        self.workflow.nodes = [_agent("a1", "support", persistentMemoryEnabled=True)]

        outcome, payload = await self._call(self._session())

        self.assertFalse(payload["memory_turned_on"])
        self.assertEqual(outcome.summary, "Inserted 2 entities and 1 relationship")
        self.add_version.assert_not_awaited()
        self.announce.assert_not_awaited()
        self.assertEqual(outcome.events, [])
        self.assertEqual(
            [c.kwargs["action"] for c in self.audit.call_args_list], ["agent_memory.insert"]
        )

    async def test_nothing_found_still_reports_and_suggests_rewording(self) -> None:
        self.insert.return_value = _inserted(0, 0)
        outcome, payload = await self._call(self._session())
        self.assertTrue(outcome.summary.startswith("Nothing to insert"))
        self.assertIn("no entities", payload["note"])

    async def test_a_failed_insert_leaves_memory_off(self) -> None:
        self.insert.side_effect = HTTPException(status_code=502, detail="The model request failed.")

        outcome, payload = await self._call(self._session())

        self.assertEqual(outcome.status, "error")
        self.assertEqual(payload["error"], "The model request failed.")
        self.db.rollback.assert_awaited_once()
        self.db.commit.assert_not_awaited()
        self.add_version.assert_not_awaited()
        self.assertFalse(self._memory_on())

    async def test_several_agents_need_a_choice(self) -> None:
        self.workflow.nodes = [_agent("a1", "support"), _agent("a2", "writer")]

        outcome, payload = await self._call(self._session())

        self.assertEqual(outcome.status, "pending")
        self.assertEqual(payload["status"], "needs_choice")
        self.assertEqual([a["id"] for a in payload["agents"]], ["a1", "a2"])
        self.insert.assert_not_awaited()

        await self._call(self._session(), agent_id="writer")
        self.assertEqual(self.insert.await_args.kwargs["node_id"], "a2")

    async def test_refusals_happen_before_the_model_runs(self) -> None:
        cases: list[tuple[dict[str, Any], str]] = [
            ({"text": "x" * (AI_INSERT_MAX_TEXT_CHARS + 1)}, "Split it"),
            ({"workflow_id": "nope"}, "workflow UUID"),
            ({"workflow_id": str(uuid.uuid4())}, "not found"),
        ]
        for args, expected in cases:
            with self.subTest(expected=expected):
                outcome, payload = await self._call(self._session(), **args)
                self.assertEqual(outcome.status, "error")
                self.assertIn(expected, payload["error"])
        self.insert.assert_not_awaited()

    async def test_a_read_only_workflow_is_refused(self) -> None:
        self.writable = False
        outcome, payload = await self._call(self._session())
        self.assertIn("read-only", payload["error"])
        self.insert.assert_not_awaited()

    async def test_an_agent_without_a_model_is_refused(self) -> None:
        self.workflow.nodes = [_agent("a1", "support", model="")]
        outcome, payload = await self._call(self._session())
        self.assertIn("needs a credential and a model", payload["error"])
        self.insert.assert_not_awaited()

    async def test_a_targeted_turn_only_fills_its_own_workflow(self) -> None:
        session = self._session(target=uuid.uuid4())
        outcome, payload = await self._call(session)
        self.assertIn("This turn changes workflow", payload["error"])
        self.insert.assert_not_awaited()

    async def test_text_in_the_request_is_inserted_without_asking(self) -> None:
        client = FormClient(self.user.id, "accept", {"text": "something else"})

        outcome, payload = await self._call(self._session(client=client.channel()))

        self.assertEqual(payload["status"], "inserted")
        self.assertEqual(client.sent, [])
        self.assertEqual(self.insert.await_args.kwargs["text"], TEXT)

    async def test_without_text_mcp_form_elicitation_asks_for_it(self) -> None:
        client = FormClient(self.user.id, "accept", {"text": f"  {TEXT}\n"})

        outcome, payload = await self._call(self._session(client=client.channel()), text="")

        self.assertEqual(payload["status"], "inserted")
        request = client.sent[0]
        self.assertEqual(request["method"], "elicitation/create")
        self.assertNotIn("url", request["params"])
        field = request["params"]["requestedSchema"]["properties"]["text"]
        self.assertEqual(field["type"], "string")
        self.assertIn('What should agent "support"', request["params"]["message"])
        self.assertIn("turns on with this insert", request["params"]["message"])
        self.assertEqual(self.insert.await_args.kwargs["text"], TEXT)
        self.assertTrue(self._memory_on())

    async def test_an_elicited_text_over_the_limit_is_refused(self) -> None:
        client = FormClient(self.user.id, "accept", {"text": "x" * (AI_INSERT_MAX_TEXT_CHARS + 1)})

        outcome, payload = await self._call(self._session(client=client.channel()), text="")

        self.assertEqual(outcome.status, "error")
        self.assertIn("Split it", payload["error"])
        self.insert.assert_not_awaited()

    async def test_declined_cancelled_or_empty_form_changes_nothing(self) -> None:
        for action, content in (("decline", {}), ("cancel", {}), ("accept", {"text": "   "})):
            with self.subTest(action=action, content=content):
                client = FormClient(self.user.id, action, content)
                outcome, payload = await self._call(self._session(client=client.channel()), text="")
                self.assertEqual(payload["status"], "no_text")
                self.assertEqual(outcome.summary, "No text to insert")
        self.insert.assert_not_awaited()
        self.db.commit.assert_not_awaited()
        self.assertFalse(self._memory_on())

    async def test_without_text_and_without_form_mode_the_chat_asks(self) -> None:
        cases = (
            ("no client", None),
            (
                "url only",
                FormClient(self.user.id, "accept", {"text": TEXT}).channel(frozenset({"url"})),
            ),
            ("no answer", FormClient(self.user.id, "error").channel()),
        )
        for name, channel in cases:
            with self.subTest(name):
                outcome, payload = await self._call(self._session(client=channel), text="   ")
                self.assertEqual(outcome.status, "pending")
                self.assertEqual(payload["status"], "needs_text")
                self.assertIn('What should agent "support"', payload["question"])
                self.assertIn("heym-clarify", payload["note"])
                self.assertIn("type text", payload["note"])
        self.insert.assert_not_awaited()
        self.db.commit.assert_not_awaited()
        self.assertFalse(self._memory_on())

    async def test_build_instructions_route_memory_requests_to_the_tool(self) -> None:
        instructions = build_mode_instructions(None, None)
        self.assertIn("never use save_workflow or edit_workflow for that", instructions)
        self.assertIn("call it without text and do not ask for the text yourself", instructions)
