"""The A2A columns and table: switches default off, tasks scoped by user and server."""

import unittest

from app.db.models import A2ATask, DashboardMessage, MCPServer, User
from app.models.schemas import MCPChatToolConfig, MCPChatToolUpdate


class A2AModelTests(unittest.TestCase):
    def test_switches_exist_and_default_off(self) -> None:
        for column in (User.__table__.c.mcp_a2a_enabled, MCPServer.__table__.c.a2a_enabled):
            with self.subTest(column=column.name):
                self.assertFalse(column.nullable)
                self.assertIs(column.default.arg, False)

    def test_task_columns(self) -> None:
        columns = A2ATask.__table__.c
        self.assertEqual(
            set(columns.keys()),
            {
                "id",
                "user_id",
                "mcp_server_id",
                "context_id",
                "state",
                "status_message",
                "artifacts",
                "created_at",
                "updated_at",
            },
        )
        self.assertTrue(columns.mcp_server_id.nullable)
        self.assertFalse(columns.context_id.nullable)
        self.assertFalse(columns.user_id.nullable)

    def test_list_index_covers_scope_and_recency(self) -> None:
        indexes = {
            index.name: [column.name for column in index.columns]
            for index in A2ATask.__table__.indexes
        }
        self.assertEqual(
            indexes["ix_a2a_tasks_user_server_updated"], ["user_id", "mcp_server_id", "updated_at"]
        )

    def test_messages_point_at_their_task(self) -> None:
        column = DashboardMessage.__table__.c.a2a_task_id
        self.assertTrue(column.nullable)
        (foreign_key,) = column.foreign_keys
        self.assertEqual(foreign_key.target_fullname, "a2a_tasks.id")
        self.assertEqual(foreign_key.ondelete, "SET NULL")

    def test_chat_tool_schemas_carry_the_a2a_switch(self) -> None:
        self.assertFalse(MCPChatToolConfig().a2a_enabled)
        self.assertIsNone(MCPChatToolUpdate().a2a_enabled)
        self.assertTrue(MCPChatToolUpdate(a2a_enabled=True).a2a_enabled)
