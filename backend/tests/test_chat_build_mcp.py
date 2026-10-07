"""MCP heym_chat runs chat build mode and tells the client when a build is verified."""

import unittest
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chats
from app.services.chat_build_mode import BuildRequest
from app.services.mcp_chat_service import MCPChatResult, format_chat_tool_text


class MCPChatBuildTests(unittest.IsolatedAsyncioTestCase):
    async def test_heym_chat_turns_build_and_report_verification(self) -> None:
        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            is_running=False,
            title="New Chat",
            has_unread=True,
            queue_paused_by_message_id=None,
            last_credential_id=None,
            last_model=None,
        )
        assistant = SimpleNamespace(
            content="It saves leads.\n<!-- heym-workflow-id:abc heym-workflow-name:Leads -->",
            tool_calls=[
                {"name": "save_workflow", "status": "success"},
                {"name": "run_workflow_test", "status": "success"},
                {"name": "finish", "status": "success"},
            ],
        )
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=assistant))
        )

        @asynccontextmanager
        async def session_maker() -> Any:
            yield db

        turns: list[chats.ChatTurn] = []

        async def run_turn(conv_id: str, user_id: uuid.UUID, turn: chats.ChatTurn, url: str) -> Any:
            turns.append(turn)
            return chats.ChatTurnResult(False, uuid.uuid4())

        with (
            patch.object(chats, "async_session_maker", session_maker),
            patch.object(
                chats,
                "_get_or_create_mcp_conversation",
                AsyncMock(return_value=(conversation, True)),
            ),
            patch.object(chats, "_run_chat_turn", run_turn),
            patch.object(chats, "_finish_worker_state", AsyncMock()),
            patch.object(chats.registry, "create_task", AsyncMock()),
            patch.object(chats.registry, "finish", AsyncMock()),
        ):
            result = await chats.run_mcp_chat_turn(
                user_id=uuid.uuid4(),
                message="Build a lead intake workflow",
                conversation_id=None,
                credential_id=uuid.uuid4(),
                model="gpt-5.5",
                public_base_url="http://localhost",
            )

        self.assertEqual(turns[0].build, BuildRequest())
        self.assertTrue(result.verified)
        self.assertEqual(result.text, "It saves leads.")

    def test_the_tool_text_says_when_a_build_is_verified(self) -> None:
        result = MCPChatResult(
            conversation_id=uuid.uuid4(),
            text="It saves leads.",
            tool_names=["save_workflow", "run_workflow_test", "finish"],
            awaiting_clarification=False,
            verified=True,
        )

        self.assertIn("Verified: the latest test run", format_chat_tool_text(result))
        self.assertNotIn(
            "Verified",
            format_chat_tool_text(MCPChatResult(result.conversation_id, "Hi", [], False)),
        )


if __name__ == "__main__":
    unittest.main()
