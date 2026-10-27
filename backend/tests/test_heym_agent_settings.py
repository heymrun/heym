"""Heym Agent settings: per-surface switches and the description shared by MCP and A2A."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.heym_agent import profile
from app.services.heym_agent.settings import (
    AgentSettings,
    get_global_agent_settings,
    get_server_agent_settings,
)


def _db_returning(row: object) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=row)))
    return db


class AgentSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_settings_read_the_a2a_switch(self) -> None:
        user = SimpleNamespace(
            id=uuid.uuid4(),
            mcp_chat_enabled=True,
            mcp_chat_credential_id=None,
            mcp_chat_model="gpt-5",
            mcp_a2a_enabled=True,
        )

        settings = await get_global_agent_settings(_db_returning(user), user.id)

        self.assertTrue(settings.enabled)
        self.assertTrue(settings.a2a_enabled)
        self.assertTrue(settings.a2a_reachable)

    async def test_server_settings_read_the_a2a_switch(self) -> None:
        server = SimpleNamespace(
            chat_enabled=False, chat_credential_id=None, chat_model=None, a2a_enabled=True
        )

        settings = await get_server_agent_settings(
            _db_returning(server), uuid.uuid4(), uuid.uuid4()
        )

        self.assertTrue(settings.a2a_enabled)
        self.assertFalse(settings.a2a_reachable)

    async def test_missing_surface_is_off(self) -> None:
        settings = await get_server_agent_settings(_db_returning(None), uuid.uuid4(), uuid.uuid4())

        self.assertEqual(settings, AgentSettings(enabled=False, credential_id=None, model=None))


class AgentProfileTests(unittest.TestCase):
    def test_both_faces_describe_the_same_capabilities(self) -> None:
        self.assertIn(profile.AGENT_CAPABILITIES, profile.MCP_TOOL_DESCRIPTION)
        self.assertIn(profile.AGENT_CAPABILITIES, profile.A2A_DESCRIPTION)
        self.assertIn("eval suites", profile.AGENT_CAPABILITIES)

    def test_skills_have_unique_ids_and_examples(self) -> None:
        ids = [skill.id for skill in profile.AGENT_SKILLS]
        self.assertEqual(len(ids), len(set(ids)))
        for skill in profile.AGENT_SKILLS:
            with self.subTest(skill=skill.id):
                self.assertTrue(skill.tags)
                self.assertTrue(skill.examples)
