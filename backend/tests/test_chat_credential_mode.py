"""Chat tab turns get the credential flow; MCP turns never do."""

import contextlib
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chats
from app.services.credential_catalog import CredentialPromptMode

SECTION = "\n\n## Credentials\n\nCATALOG\n"


class ChatSystemPromptCredentialTests(unittest.IsolatedAsyncioTestCase):
    async def _parts(self, mode: CredentialPromptMode) -> tuple[chats.SystemPromptParts, AsyncMock]:
        user = SimpleNamespace(id=uuid.uuid4(), user_rules="")
        with (
            patch.object(chats, "get_workflows_for_user_with_inputs", AsyncMock(return_value=[])),
            patch.object(chats, "_load_agents_md_content", return_value=""),
            patch.object(
                chats, "build_credentials_prompt", AsyncMock(return_value=SECTION)
            ) as build,
        ):
            parts = await chats._assemble_system_prompt_parts(
                user,
                AsyncMock(),
                include_attachment_instructions=False,
                credential_mode=mode,
            )
        return parts, build

    async def test_ui_turns_get_the_credentials_section(self) -> None:
        parts, build = await self._parts(CredentialPromptMode.ASK_AND_CREATE)

        self.assertIn("CATALOG", parts.full_system_prompt)
        self.assertEqual(parts.credentials_block, SECTION)
        build.assert_awaited_once()

    async def test_mcp_turns_get_no_credentials_section(self) -> None:
        parts, build = await self._parts(CredentialPromptMode.OFF)

        self.assertNotIn("CATALOG", parts.full_system_prompt)
        self.assertEqual(parts.credentials_block, "")
        build.assert_not_awaited()

    def test_turns_default_to_the_full_flow(self) -> None:
        turn = chats.ChatTurn(
            content="hi",
            credential_id=uuid.uuid4(),
            model="gpt-4o",
            attachment_data=None,
            should_generate_title=False,
        )

        self.assertEqual(turn.credential_mode, CredentialPromptMode.ASK_AND_CREATE)


class MCPChatTurnCredentialModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_turns_run_with_credentials_off(self) -> None:
        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            is_running=False,
            title=chats.DEFAULT_CONVERSATION_TITLE,
            has_unread=False,
            queue_paused_by_message_id=None,
            last_credential_id=None,
            last_model=None,
        )
        assistant_message = SimpleNamespace(content="Done.", tool_calls=[])
        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=assistant_message))
        )

        @contextlib.asynccontextmanager
        async def fake_session_maker():
            yield session

        captured: dict[str, chats.ChatTurn] = {}

        async def fake_run_chat_turn(
            _conv_id: str, _user_id: uuid.UUID, turn: chats.ChatTurn, _base_url: str
        ) -> chats.ChatTurnResult:
            captured["turn"] = turn
            return chats.ChatTurnResult(False, uuid.uuid4())

        with (
            patch.object(chats, "async_session_maker", fake_session_maker),
            patch.object(
                chats,
                "_get_or_create_mcp_conversation",
                AsyncMock(return_value=(conversation, True)),
            ),
            patch.object(chats, "_run_chat_turn", side_effect=fake_run_chat_turn),
            patch.object(chats, "_finish_worker_state", AsyncMock()),
            patch.object(chats.registry, "create_task", AsyncMock()),
            patch.object(chats.registry, "finish", AsyncMock()),
        ):
            await chats.run_mcp_chat_turn(
                user_id=uuid.uuid4(),
                message="list my GitHub repositories",
                conversation_id=None,
                credential_id=uuid.uuid4(),
                model="gpt-4o",
                public_base_url="https://heym.test",
            )

        self.assertEqual(captured["turn"].credential_mode, CredentialPromptMode.OFF)


if __name__ == "__main__":
    unittest.main()
