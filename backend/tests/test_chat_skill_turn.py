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

from app.api.ai_assistant import FileAttachment
from app.services.chat_skill_turn import (
    CREATE_REFUSED,
    DROP_REFUSED,
    SHAPE_REFUSED,
    skill_save_problem,
    skill_use_instructions,
)


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


class SkillSaveTests(unittest.TestCase):
    def test_settings_of_the_existing_nodes_may_change(self) -> None:
        after = _skill_workflow()
        after[1]["data"]["maxToolIterations"] = 20
        after[1]["data"]["systemInstruction"] = "Write Turkish documents."
        self.assertIsNone(skill_save_problem(_skill_workflow(), after))

    def test_a_new_workflow_is_refused(self) -> None:
        self.assertEqual(skill_save_problem(None, _skill_workflow()), CREATE_REFUSED)

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
        for words in ("apply_skill", "run_workflow_test", "file_edits", "main.py", "_OUTPUT_DIR"):
            self.assertIn(words, block)
        self.assertIn("Never", block)


class BuildSessionSkillTurnTests(unittest.IsolatedAsyncioTestCase):
    def _session(self, attachments: list[FileAttachment]) -> Any:
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
            self.assertEqual(session.turn_skill_names(), ["docx"])
            outcome = await session._save({"workflow": workflow})
        self.assertEqual(outcome.status, "error")
        self.assertEqual(json.loads(outcome.result)["error"], CREATE_REFUSED)

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
        self.assertEqual(session.turn_skill_names(), [])
        self.assertNotIn("Using the attached skill", await self._prompt(session))

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


if __name__ == "__main__":
    unittest.main()
