import unittest

from app.config import settings
from app.services.mcp_session import MCPSessionStore, MCPSSEChannelStore


class MCPSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MCPSessionStore()

    def test_create_without_server_id_resolves_to_none_server_id(self) -> None:
        token = self.store.create("user-123")
        result = self.store.resolve(token)
        self.assertIsNotNone(result)
        user_id, server_id = result
        self.assertEqual(user_id, "user-123")
        self.assertIsNone(server_id)

    def test_create_with_server_id_resolves_correctly(self) -> None:
        token = self.store.create("user-456", server_id="server-abc")
        result = self.store.resolve(token)
        self.assertIsNotNone(result)
        user_id, server_id = result
        self.assertEqual(user_id, "user-456")
        self.assertEqual(server_id, "server-abc")

    def test_signed_token_resolves_in_different_store_instance(self) -> None:
        token = self.store.create("user-456", server_id="server-abc")
        other_store = MCPSessionStore()

        result = other_store.resolve(token)

        self.assertIsNotNone(result)
        user_id, server_id = result
        self.assertEqual(user_id, "user-456")
        self.assertEqual(server_id, "server-abc")

    def test_resolve_unknown_token_returns_none(self) -> None:
        self.assertIsNone(self.store.resolve("nonexistent-token"))

    def test_revoke_makes_token_invalid(self) -> None:
        token = self.store.create("user-789")
        self.store.revoke(token)
        self.assertIsNone(self.store.resolve(token))


class MCPSSEChannelStoreTests(unittest.TestCase):
    def test_can_register_respects_session_limit(self) -> None:
        original_limit = settings.mcp_sse_max_sessions
        settings.mcp_sse_max_sessions = 1
        try:
            store = MCPSSEChannelStore()
            self.assertTrue(store.can_register())
            store.register("tok-1")

            self.assertFalse(store.can_register())

            store.unregister("tok-1")
            self.assertTrue(store.can_register())
        finally:
            settings.mcp_sse_max_sessions = original_limit
