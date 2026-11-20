"""A chat turn that carries a skill runs that skill; it never builds another workflow.

apply_skill puts the skill on Request -> Agent -> Result. In that turn save_workflow may
change the existing nodes' settings, but refuses a new workflow, a node added or removed,
and an agent that loses the skill. Converting the skill means changing its own files.
"""

import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from app.api.ai_assistant import FileAttachment, _build_user_message
from app.services.chat_skill_turn import (
    CREATE_REFUSED,
    DROP_REFUSED,
    LOADER_REFUSED,
    SHAPE_REFUSED,
    conversation_skill_names,
    page_loader_problem,
    skill_save_problem,
    skill_use_instructions,
)
from app.services.skill_archive import ArchiveFile, SkillBundle, ZipRead, prompt_for_zip


def _skill_workflow(skills: list[str] | None = None) -> list[dict]:
    return [
        {"id": "request", "type": "textInput", "data": {"label": "Request"}},
        {
            "id": "agent",
            "type": "agent",
            "data": {
                "label": "Agent",
                "skills": [
                    {"name": name, "files": []}
                    for name in (skills if skills is not None else ["docx"])
                ],
                "maxToolIterations": 8,
            },
        },
        {"id": "result", "type": "output", "data": {"label": "Result"}},
    ]


def _loader(**playwright: Any) -> list[dict]:
    return [
        {"id": "in", "type": "textInput", "data": {"label": "urls"}},
        {
            "id": "page",
            "type": "playwright",
            "data": {
                "label": "readPage",
                "playwrightMode": "steps",
                "playwrightSteps": [
                    {"action": "navigate", "url": "$urls.body.urls"},
                    {"action": "getVisibleTextOnPage"},
                ],
                **playwright,
            },
        },
        {"id": "shape", "type": "set", "data": {"label": "pageText"}},
        {"id": "out", "type": "output", "data": {"label": "siteContent"}},
    ]


class PageLoaderTests(unittest.TestCase):
    """The one new workflow a skill chat may build reads pages and runs no model or code."""

    def test_a_page_loader_may_be_created(self) -> None:
        self.assertIsNone(page_loader_problem(_loader()))
        self.assertIsNone(skill_save_problem(None, _loader()))
        http = [
            {"id": "in", "type": "textInput", "data": {"label": "url"}},
            {"id": "get", "type": "http", "data": {"label": "get", "curl": "curl $url.body.url"}},
            {"id": "out", "type": "output", "data": {"label": "page"}},
        ]
        self.assertIsNone(skill_save_problem(None, http))

    def test_a_workflow_that_could_write_the_document_is_refused(self) -> None:
        for extra_type in ("code", "llm", "agent", "execute", "drive"):
            nodes = [*_loader(), {"id": "x", "type": extra_type, "data": {"label": "makeDocx"}}]
            problem = skill_save_problem(None, nodes)
            assert problem is not None
            self.assertTrue(problem.startswith(CREATE_REFUSED), extra_type)
            self.assertIn(f"is a {extra_type} node", problem)

    def test_playwright_code_and_ai_steps_are_refused(self) -> None:
        for playwright in (
            {"playwrightMode": "code", "playwrightCode": "page.goto(url)"},
            {"playwrightCode": "open('/tmp/x.docx', 'wb')"},
            {"playwrightSteps": [{"action": "aiStep", "aiStepPrompt": "write a report"}]},
            {"playwrightAuthFallbackSteps": [{"action": "aiStep"}]},
        ):
            problem = page_loader_problem(_loader(**playwright))
            assert problem is not None
            self.assertIn("Playwright node 'readPage'", problem)

    def test_a_workflow_that_loads_nothing_is_refused(self) -> None:
        nodes = [node for node in _loader() if node["type"] != "playwright"]
        problem = skill_save_problem(None, nodes)
        assert problem is not None
        self.assertIn("loads no page", problem)

    def test_a_loader_may_change_but_must_stay_a_loader(self) -> None:
        fixed = [*_loader(), {"id": "note", "type": "sticky", "data": {"label": "n"}}]
        self.assertIsNone(skill_save_problem(_loader(), fixed))
        turned = _loader(playwrightMode="code", playwrightCode="x")
        problem = skill_save_problem(_loader(), turned)
        assert problem is not None
        self.assertTrue(problem.startswith(LOADER_REFUSED))

    def test_the_skill_workflow_cannot_become_a_loader_with_extra_nodes(self) -> None:
        self.assertEqual(skill_save_problem(_skill_workflow(), _loader()), SHAPE_REFUSED)


class ConversationSkillNamesTests(unittest.TestCase):
    """Later messages know the skills earlier messages attached, from the stored blocks."""

    def _stored(self, text: str, *bundles: SkillBundle) -> str:
        reading = ZipRead(skills=bundles, text_files=(), notes=())
        attachment = FileAttachment(name="skills.zip", kind="zip", content="z")
        with (
            patch("app.services.skill_archive.decode_zip_payload", return_value=b"zip"),
            patch("app.services.skill_archive.read_zip", return_value=reading),
        ):
            return _build_user_message(text, [attachment])["content"]

    def _bundle(self, name: str, body: str = "# Skill") -> SkillBundle:
        return SkillBundle(
            name=name,
            content=body,
            files=(ArchiveFile(path="scripts/main.py", content="print(1)"),),
            directory=name,
        )

    def test_names_come_back_from_the_stored_message(self) -> None:
        first = self._stored("use this skill", self._bundle("docx"), self._bundle("pdf"))
        again = self._stored("", self._bundle("docx"))
        self.assertTrue(again.startswith("\n\n[ATTACHED ZIP: "))
        self.assertEqual(
            conversation_skill_names([first, "now make the document", again]), ["docx", "pdf"]
        )

    def test_messages_without_a_skill_zip_name_none(self) -> None:
        context_zip = prompt_for_zip("notes.zip", ZipRead(skills=(), text_files=(), notes=()))
        self.assertEqual(
            conversation_skill_names(
                [
                    "Skill docx. Other files: none.",
                    f"see this\n\n{context_zip}",
                    "plain text",
                ]
            ),
            [],
        )


class SkillSaveTests(unittest.TestCase):
    def test_settings_of_the_existing_nodes_may_change(self) -> None:
        after = _skill_workflow()
        after[1]["data"]["maxToolIterations"] = 20
        after[1]["data"]["systemInstruction"] = "Write Turkish documents."
        self.assertIsNone(skill_save_problem(_skill_workflow(), after))

    def test_a_new_workflow_is_refused(self) -> None:
        problem = skill_save_problem(None, _skill_workflow())
        assert problem is not None
        self.assertTrue(problem.startswith(CREATE_REFUSED))

    def test_adding_or_removing_a_node_is_refused(self) -> None:
        added = [
            *_skill_workflow(),
            {"id": "fetch", "type": "http", "data": {"label": "fetchHome"}},
        ]
        self.assertEqual(skill_save_problem(_skill_workflow(), added), SHAPE_REFUSED)
        removed = _skill_workflow()[:2]
        self.assertEqual(skill_save_problem(_skill_workflow(), removed), SHAPE_REFUSED)
        swapped = _skill_workflow()
        swapped[1] = {"id": "agent", "type": "code", "data": {"label": "buildDocx"}}
        self.assertEqual(skill_save_problem(_skill_workflow(), swapped), SHAPE_REFUSED)

    def test_dropping_the_skill_is_refused(self) -> None:
        self.assertEqual(
            skill_save_problem(_skill_workflow(), _skill_workflow(skills=[])), DROP_REFUSED
        )
        self.assertEqual(
            skill_save_problem(_skill_workflow(), _skill_workflow(skills=["other"])),
            DROP_REFUSED,
        )

    def test_the_messages_point_to_running_or_converting_the_skill(self) -> None:
        for message in (CREATE_REFUSED, SHAPE_REFUSED, DROP_REFUSED):
            self.assertIn("apply_skill", message)


class SkillUseInstructionsTests(unittest.TestCase):
    def test_the_block_names_the_skills_and_the_rules(self) -> None:
        block = skill_use_instructions(["docx"])
        self.assertIn("docx", block)
        for words in (
            "apply_skill",
            "run_workflow_test",
            "file_edits",
            "main.py",
            "_OUTPUT_DIR",
            "--help",
            "unchanged_files",
            "let you build a page loader",
            "page loader",
            "never run Skill Discover",
            "stop before running the skill",
            "paste its text",
            "run_python is off",
            "Page loader rule",
            "every later message",
        ):
            self.assertIn(words, block)
        self.assertIn("Never stand in for the page with search_documentation", block)
        self.assertIn("never writes a placeholder or empty document", block)


class BuildSessionSkillTurnTests(unittest.IsolatedAsyncioTestCase):
    def _session(self, attachments: list[FileAttachment], earlier: list[str] | None = None) -> Any:
        from app.api.chat_build import ChatBuildSession
        from app.services.chat_build_mode import BuildRequest
        from app.services.credential_catalog import CredentialPromptMode

        return ChatBuildSession(
            db=AsyncMock(),
            user=SimpleNamespace(id=uuid.uuid4()),
            request=BuildRequest(),
            selected_credential=SimpleNamespace(id=uuid.uuid4(), type="openai"),
            model="m",
            credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            public_base_url="http://localhost",
            cancel_event=None,
            llm_session_id="conv-1",
            attachments=attachments,
            earlier_skill_names=earlier or [],
        )

    def _zips(self, names: list[str]) -> Any:
        reading = SimpleNamespace(skills=[SimpleNamespace(name=name) for name in names])
        return (
            patch("app.api.chat_build.decode_zip_payload", side_effect=lambda value: value),
            patch("app.api.chat_build.read_zip", side_effect=lambda _raw: reading),
        )

    async def test_a_skill_turn_refuses_to_build_a_new_workflow(self) -> None:
        session = self._session([FileAttachment(name="docx.zip", kind="zip", content="z")])
        decode, read = self._zips(["docx"])
        workflow = {"name": "Site to docx", "nodes": _skill_workflow(), "edges": []}
        with decode, read:
            self.assertEqual(session.skill_names(), ["docx"])
            outcome = await session._save({"workflow": workflow})
        self.assertEqual(outcome.status, "error")
        self.assertTrue(json.loads(outcome.result)["error"].startswith(CREATE_REFUSED))

    async def test_a_skill_turn_refuses_nodes_around_the_skill(self) -> None:
        session = self._session([FileAttachment(name="docx.zip", kind="zip", content="z")])
        existing = SimpleNamespace(id=uuid.uuid4(), nodes=_skill_workflow(), edges=[])
        bigger = [*_skill_workflow(), {"id": "fetch", "type": "http", "data": {"label": "f"}}]
        decode, read = self._zips(["docx"])
        with (
            decode,
            read,
            patch("app.api.chat_build.get_workflow_for_user", AsyncMock(return_value=existing)),
            patch("app.api.chat_build.user_can_write_workflow", AsyncMock(return_value=True)),
        ):
            outcome = await session._save(
                {"workflow_id": str(existing.id), "workflow": {"name": "d", "nodes": bigger}}
            )
        self.assertEqual(json.loads(outcome.result)["error"], SHAPE_REFUSED)

    async def test_a_turn_without_a_skill_is_not_held(self) -> None:
        session = self._session([])
        self.assertEqual(session.skill_names(), [])
        self.assertTrue(session.python_allowed)
        self.assertNotIn("Using the attached skill", await self._prompt(session))

    async def test_a_later_message_keeps_the_skill_rules(self) -> None:
        """No zip in this message, but an earlier one carried the skill."""
        session = self._session([], earlier=["docx"])
        self.assertEqual(session.skill_names(), ["docx"])
        self.assertFalse(session.python_allowed)
        self.assertIn("## Using the attached skill", await self._prompt(session))
        outcome = await session._save(
            {"workflow": {"name": "heym.run to DOCX", "nodes": _skill_workflow(), "edges": []}}
        )
        self.assertTrue(json.loads(outcome.result)["error"].startswith(CREATE_REFUSED))

    async def test_a_loader_after_apply_skill_is_a_new_workflow(self) -> None:
        """Saved without a workflow_id, the loader goes beside the skill workflow."""
        session = self._session([], earlier=["docx"])
        skill_workflow = SimpleNamespace(id=uuid.uuid4(), nodes=_skill_workflow(), edges=[])
        session.progress.record_save(skill_workflow.id)
        seen: dict[str, Any] = {}

        def stop_at_sanitize(_nodes: Any, **kwargs: Any) -> Any:
            seen["previous"] = kwargs["previous_nodes"]
            raise RuntimeError("reached the save")

        async def save(workflow_id: str | None) -> Any:
            args: dict[str, Any] = {"workflow": {"name": "Page loader", "nodes": _loader()}}
            if workflow_id is not None:
                args["workflow_id"] = workflow_id
            with (
                patch(
                    "app.api.chat_build.get_workflow_for_user",
                    AsyncMock(return_value=skill_workflow),
                ),
                patch("app.api.chat_build.user_can_write_workflow", AsyncMock(return_value=True)),
                patch("app.api.chat_build.load_credential_catalog", AsyncMock(return_value=[])),
                patch("app.api.chat_build.load_data_table_catalog", AsyncMock(return_value=[])),
                patch(
                    "app.api.chat_build.load_accessible_credential_ids",
                    AsyncMock(return_value=set()),
                ),
                patch(
                    "app.api.chat_build._sanitize_generated_workflow_nodes",
                    side_effect=stop_at_sanitize,
                ),
            ):
                return await session._save(args)

        with self.assertRaises(RuntimeError):
            await save(None)
        self.assertIsNone(seen["previous"])
        # Named explicitly, the skill workflow cannot be turned into a loader.
        outcome = await save(str(skill_workflow.id))
        self.assertEqual(json.loads(outcome.result)["error"], SHAPE_REFUSED)

    async def test_a_page_loader_passes_the_lock(self) -> None:
        session = self._session([], earlier=["docx"])
        sentinel = RuntimeError("reached the save")
        with (
            patch("app.api.chat_build.load_credential_catalog", AsyncMock(side_effect=sentinel)),
            self.assertRaises(RuntimeError) as raised,
        ):
            await session._save({"workflow": {"name": "Page loader", "nodes": _loader()}})
        self.assertIs(raised.exception, sentinel)

    async def test_the_skill_turn_rules_reach_the_prompt(self) -> None:
        session = self._session([FileAttachment(name="docx.zip", kind="zip", content="z")])
        decode, read = self._zips(["docx"])
        with decode, read:
            prompt = await self._prompt(session)
        self.assertIn("## Using the attached skill", prompt)
        self.assertIn("(docx)", prompt)

    async def _prompt(self, session: Any) -> str:
        with (
            patch.object(session, "_target_workflow", AsyncMock(return_value=None)),
            patch(
                "app.api.chat_build.get_workflows_for_user_with_inputs", AsyncMock(return_value=[])
            ),
            patch(
                "app.api.chat_build.template_service.list_node_templates",
                AsyncMock(return_value=[]),
            ),
            patch("app.api.chat_build.load_credential_catalog", AsyncMock(return_value=[])),
            patch("app.api.chat_build.load_data_table_catalog", AsyncMock(return_value=[])),
            patch("app.api.chat_build._load_installed_plugins", AsyncMock(return_value=[])),
        ):
            return await session.prompt([])


class ChatFilePythonTests(unittest.IsolatedAsyncioTestCase):
    """run_python is off in a chat that uses a skill: the skill makes the files."""

    def _tools(self, allow_python: bool) -> Any:
        from app.api.chat_files import ChatFileTools

        return ChatFileTools(
            user=SimpleNamespace(id=uuid.uuid4()),
            conversation_id=uuid.uuid4(),
            allow_python=allow_python,
        )

    def test_the_tool_is_left_out(self) -> None:
        names = [s["function"]["name"] for s in self._tools(False).schemas()]
        self.assertNotIn("run_python", names)
        self.assertIn("inspect_file", names)
        self.assertIn("run_python", [s["function"]["name"] for s in self._tools(True).schemas()])

    async def test_a_call_is_refused_without_running(self) -> None:
        tools = self._tools(False)
        with patch.object(tools.toolbox, "call") as run:
            outcome = await tools.call("run_python", {"code": "open('x.docx', 'w')"})
        run.assert_not_called()
        self.assertEqual(outcome.status, "error")
        self.assertIn("run_python is off", json.loads(outcome.result)["error"])


if __name__ == "__main__":
    unittest.main()
