"""The chat prompt says what Heym is, and no longer carries the coding agents' AGENTS.md."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api import ai_assistant, chats
from app.services.credential_catalog import CredentialPromptMode


class IdentityTests(unittest.TestCase):
    def test_prompt_opens_with_what_heym_is(self) -> None:
        prompt = ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT
        self.assertTrue(prompt.startswith("You are the Heym Agent"))
        opening = prompt[:1200]
        self.assertIn("self-hosted AI agent platform", opening)
        self.assertIn("Heym Work", opening)
        self.assertIn("search_documentation", opening)

    def test_agents_md_loader_is_gone(self) -> None:
        self.assertFalse(hasattr(ai_assistant, "_load_agents_md_content"))
        self.assertNotIn("Heym Platform Context", ai_assistant.DASHBOARD_CHAT_SYSTEM_PROMPT)


class PersistedChatPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_assembled_prompt_has_no_agents_md(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4(), user_rules="")
        with (
            patch.object(chats, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])),
            patch.object(chats, "knowledge_bases_prompt_block", AsyncMock(return_value="")),
            patch.object(chats, "build_credentials_prompt", AsyncMock(return_value="")),
        ):
            parts = await chats._assemble_system_prompt_parts(
                user,
                AsyncMock(),
                include_attachment_instructions=False,
                credential_mode=CredentialPromptMode.ASK_AND_CREATE,
            )

        self.assertTrue(parts.full_system_prompt.startswith("You are the Heym Agent"))
        self.assertNotIn("Heym Platform Context", parts.full_system_prompt)
        self.assertNotIn("AI Coding Agents", parts.full_system_prompt)
        self.assertFalse(hasattr(parts, "agents_md"))


if __name__ == "__main__":
    unittest.main()
