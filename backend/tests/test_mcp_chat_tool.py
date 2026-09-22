"""Tests for the `heym_chat` MCP tool: exposure, config, and dispatch."""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.mcp import (
    build_tools_with_chat,
    dispatch_chat_tool_call,
    update_mcp_chat_tool,
    validate_chat_tool_credential,
)
from app.db.models import LLM_CREDENTIAL_TYPES, CredentialType
from app.models.schemas import MCPChatToolUpdate
from app.services import mcp_chat_service
from app.services.mcp_chat_service import (
    MCPChatError,
    MCPChatResult,
    MCPChatSettings,
    build_chat_mcp_tool,
    format_chat_tool_text,
    normalize_chat_arguments,
    resolve_chat_llm,
)

MODULE = "app.services.mcp_chat_service"


def _make_workflow(name: str = "My Workflow") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name=name,
        description=None,
        nodes=[],
        edges=[],
    )


def _make_user(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": uuid.uuid4(),
        "mcp_chat_enabled": False,
        "mcp_chat_credential_id": None,
        "mcp_chat_model": None,
        "preferred_credential_id": None,
        "preferred_model": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_credential(credential_type: CredentialType = CredentialType.openai) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), type=credential_type, name="OpenAI")


class ChatToolExposureTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_tool_is_absent_when_disabled(self) -> None:
        settings = MCPChatSettings(enabled=False, credential_id=None, model=None)

        with patch(
            "app.api.mcp.workflow_to_mcp_tool", side_effect=lambda w: SimpleNamespace(name=w.name)
        ):
            tools = await build_tools_with_chat([_make_workflow()], settings)

        self.assertEqual([t.name for t in tools], ["My Workflow"])

    async def test_chat_tool_is_appended_when_enabled(self) -> None:
        settings = MCPChatSettings(enabled=True, credential_id=uuid.uuid4(), model="gpt-5")

        with patch(
            "app.api.mcp.workflow_to_mcp_tool", side_effect=lambda w: SimpleNamespace(name=w.name)
        ):
            tools = await build_tools_with_chat([_make_workflow()], settings)

        self.assertEqual(
            [t.name for t in tools],
            ["My Workflow", mcp_chat_service.MCP_CHAT_TOOL_NAME],
        )

    def test_tool_schema_requires_message_and_offers_conversation_id(self) -> None:
        tool = build_chat_mcp_tool()

        self.assertEqual(tool.name, "heym_chat")
        self.assertEqual(tool.inputSchema.required, ["message"])
        self.assertIn("conversation_id", tool.inputSchema.properties)


class ChatToolSettingsLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_settings_read_the_persisted_user_row(self) -> None:
        """MCP session auth passes a stub User, so settings must come from the DB."""
        credential_id = uuid.uuid4()
        user = _make_user(
            mcp_chat_enabled=True,
            mcp_chat_credential_id=credential_id,
            mcp_chat_model="gpt-5",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=user))
        )

        settings = await mcp_chat_service.get_global_chat_settings(db, user.id)

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.credential_id, credential_id)
        self.assertEqual(settings.model, "gpt-5")

    async def test_server_settings_disabled_when_server_is_missing(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        settings = await mcp_chat_service.get_server_chat_settings(db, uuid.uuid4(), uuid.uuid4())

        self.assertFalse(settings.enabled)


class ChatLLMResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def _resolve(
        self, user: SimpleNamespace, settings: MCPChatSettings, credential: object
    ) -> object:
        db = AsyncMock()
        with (
            patch(f"{MODULE}.load_user", AsyncMock(return_value=user)),
            patch(f"{MODULE}.get_accessible_credential", AsyncMock(return_value=credential)),
        ):
            return await resolve_chat_llm(db, user.id, settings)

    async def test_surface_selection_wins(self) -> None:
        credential = _make_credential()
        user = _make_user(preferred_credential_id=uuid.uuid4(), preferred_model="gpt-4o")
        settings = MCPChatSettings(enabled=True, credential_id=credential.id, model="gpt-5")

        resolved = await self._resolve(user, settings, credential)

        self.assertEqual(resolved.credential.id, credential.id)
        self.assertEqual(resolved.model, "gpt-5")

    async def test_account_preference_fills_in_when_surface_is_unset(self) -> None:
        credential = _make_credential()
        user = _make_user(preferred_credential_id=credential.id, preferred_model="gpt-4o")
        settings = MCPChatSettings(enabled=True, credential_id=None, model=None)

        resolved = await self._resolve(user, settings, credential)

        self.assertEqual(resolved.credential.id, credential.id)
        self.assertEqual(resolved.model, "gpt-4o")

    async def test_all_llm_credential_types_are_accepted(self) -> None:
        for credential_type in LLM_CREDENTIAL_TYPES:
            with self.subTest(credential_type=credential_type):
                credential = _make_credential(credential_type)
                model = "auto" if credential_type == CredentialType.model_router else "test-model"
                settings = MCPChatSettings(enabled=True, credential_id=credential.id, model=model)

                resolved = await self._resolve(_make_user(), settings, credential)

                self.assertIs(resolved.credential, credential)
                self.assertEqual(resolved.model, model)

    async def test_account_preference_can_select_a_model_router(self) -> None:
        credential = _make_credential(CredentialType.model_router)
        user = _make_user(preferred_credential_id=credential.id, preferred_model="auto")
        settings = MCPChatSettings(enabled=True, credential_id=None, model=None)

        resolved = await self._resolve(user, settings, credential)

        self.assertIs(resolved.credential, credential)
        self.assertEqual(resolved.model, "auto")

    async def test_preferred_model_is_not_reused_for_a_different_credential(self) -> None:
        credential = _make_credential()
        user = _make_user(preferred_credential_id=uuid.uuid4(), preferred_model="gpt-4o")
        settings = MCPChatSettings(enabled=True, credential_id=credential.id, model=None)

        with self.assertRaises(MCPChatError) as ctx:
            await self._resolve(user, settings, credential)

        self.assertIn("No model is configured", str(ctx.exception))

    async def test_missing_credential_raises(self) -> None:
        user = _make_user()
        settings = MCPChatSettings(enabled=True, credential_id=None, model=None)

        with self.assertRaises(MCPChatError) as ctx:
            await self._resolve(user, settings, None)

        self.assertIn("No LLM credential is configured", str(ctx.exception))

    async def test_non_llm_credential_is_rejected(self) -> None:
        credential = _make_credential(CredentialType.slack)
        user = _make_user()
        settings = MCPChatSettings(enabled=True, credential_id=credential.id, model="gpt-5")

        with self.assertRaises(MCPChatError) as ctx:
            await self._resolve(user, settings, credential)

        self.assertIn("not an LLM credential", str(ctx.exception))


class ChatToolArgumentTests(unittest.TestCase):
    def test_message_is_required(self) -> None:
        with self.assertRaises(MCPChatError):
            normalize_chat_arguments({})
        with self.assertRaises(MCPChatError):
            normalize_chat_arguments({"message": "   "})

    def test_conversation_id_is_optional_and_parsed(self) -> None:
        conversation_id = uuid.uuid4()

        message, parsed = normalize_chat_arguments(
            {"message": " hi ", "conversation_id": str(conversation_id)}
        )

        self.assertEqual(message, "hi")
        self.assertEqual(parsed, conversation_id)

    def test_blank_conversation_id_starts_a_new_thread(self) -> None:
        _message, parsed = normalize_chat_arguments({"message": "hi", "conversation_id": ""})
        self.assertIsNone(parsed)

    def test_invalid_conversation_id_is_rejected(self) -> None:
        with self.assertRaises(MCPChatError):
            normalize_chat_arguments({"message": "hi", "conversation_id": "not-a-uuid"})

    def test_overlong_message_is_rejected(self) -> None:
        with self.assertRaises(MCPChatError):
            normalize_chat_arguments({"message": "x" * 20001})


class ChatToolResultFormattingTests(unittest.TestCase):
    def test_result_includes_conversation_id_for_follow_ups(self) -> None:
        conversation_id = uuid.uuid4()
        text = format_chat_tool_text(
            MCPChatResult(
                conversation_id=conversation_id,
                text="Created the workflow.",
                tool_names=["create_workflow"],
                awaiting_clarification=False,
            )
        )

        self.assertIn("Created the workflow.", text)
        self.assertIn(f"conversation_id: {conversation_id}", text)
        self.assertIn("create_workflow", text)
        self.assertNotIn("clarifying questions", text)

    def test_clarification_pause_is_announced(self) -> None:
        text = format_chat_tool_text(
            MCPChatResult(
                conversation_id=uuid.uuid4(),
                text="Which channel?",
                tool_names=[],
                awaiting_clarification=True,
            )
        )

        self.assertIn("clarifying questions", text)


class ChatToolDispatchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.request = MagicMock()
        self.settings = MCPChatSettings(enabled=True, credential_id=uuid.uuid4(), model="gpt-5")

    async def _dispatch(self, run_chat_tool: AsyncMock) -> dict:
        with (
            patch("app.api.mcp.mcp_chat_service.run_chat_tool", run_chat_tool),
            patch("app.api.mcp.build_public_base_url", return_value="https://heym.test"),
        ):
            return await dispatch_chat_tool_call(
                request=self.request,
                db=AsyncMock(),
                msg_id=7,
                user_id=uuid.uuid4(),
                chat_settings=self.settings,
                arguments={"message": "show analytics"},
            )

    async def test_successful_call_returns_text_content(self) -> None:
        conversation_id = uuid.uuid4()
        run_chat_tool = AsyncMock(
            return_value=MCPChatResult(
                conversation_id=conversation_id,
                text="12 runs today.",
                tool_names=["get_analytics_stats"],
                awaiting_clarification=False,
            )
        )

        response = await self._dispatch(run_chat_tool)

        self.assertEqual(response["id"], 7)
        self.assertFalse(response["result"]["isError"])
        self.assertIn("12 runs today.", response["result"]["content"][0]["text"])
        self.assertIn(str(conversation_id), response["result"]["content"][0]["text"])

    async def test_model_router_dispatch_reaches_the_chat_engine(self) -> None:
        credential = _make_credential(CredentialType.model_router)
        user = _make_user()
        settings = MCPChatSettings(enabled=True, credential_id=credential.id, model="auto")
        reply_conversation_id = uuid.uuid4()
        result = MCPChatResult(
            conversation_id=reply_conversation_id,
            text="12 runs today.",
            tool_names=["get_analytics_stats"],
            awaiting_clarification=False,
        )

        for conversation_id in (None, reply_conversation_id):
            with self.subTest(conversation_id=conversation_id):
                arguments = {"message": "show analytics"}
                if conversation_id is not None:
                    arguments["conversation_id"] = str(conversation_id)
                db = AsyncMock()
                with (
                    patch(f"{MODULE}.load_user", AsyncMock(return_value=user)),
                    patch(
                        f"{MODULE}.get_accessible_credential", AsyncMock(return_value=credential)
                    ) as get_credential,
                    patch(
                        "app.api.chats.run_mcp_chat_turn", AsyncMock(return_value=result)
                    ) as run_turn,
                    patch("app.api.mcp.build_public_base_url", return_value="https://heym.test"),
                ):
                    response = await dispatch_chat_tool_call(
                        request=self.request,
                        db=db,
                        msg_id=7,
                        user_id=user.id,
                        chat_settings=settings,
                        arguments=arguments,
                    )

                self.assertFalse(response["result"]["isError"], response)
                self.assertIn("12 runs today.", response["result"]["content"][0]["text"])
                self.assertIn(str(reply_conversation_id), response["result"]["content"][0]["text"])
                get_credential.assert_awaited_once_with(db, credential.id, user.id)
                run_turn.assert_awaited_once_with(
                    user_id=user.id,
                    message="show analytics",
                    conversation_id=conversation_id,
                    credential_id=credential.id,
                    model="auto",
                    public_base_url="https://heym.test",
                )

    async def test_config_error_becomes_an_error_result_not_a_500(self) -> None:
        run_chat_tool = AsyncMock(side_effect=MCPChatError("No model is configured."))

        response = await self._dispatch(run_chat_tool)

        self.assertTrue(response["result"]["isError"])
        self.assertIn("No model is configured.", response["result"]["content"][0]["text"])

    async def test_engine_failure_is_reported_to_the_client(self) -> None:
        run_chat_tool = AsyncMock(side_effect=RuntimeError("upstream 500"))

        response = await self._dispatch(run_chat_tool)

        self.assertTrue(response["result"]["isError"])
        self.assertIn("upstream 500", response["result"]["content"][0]["text"])


class ChatToolConfigEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_router_selection_is_persisted(self) -> None:
        credential = _make_credential(CredentialType.model_router)
        user = _make_user()
        db = AsyncMock()

        with patch("app.api.mcp.get_accessible_credential", AsyncMock(return_value=credential)):
            result = await update_mcp_chat_tool(
                body=MCPChatToolUpdate(enabled=True, credential_id=credential.id, model="auto"),
                current_user=user,
                db=db,
            )

        self.assertTrue(result.enabled)
        self.assertEqual(result.credential_id, credential.id)
        self.assertEqual(result.model, "auto")
        self.assertEqual(user.mcp_chat_credential_id, credential.id)
        self.assertEqual(user.mcp_chat_model, "auto")
        db.flush.assert_awaited_once()

    async def test_enabling_persists_and_returns_the_config(self) -> None:
        credential = _make_credential()
        user = _make_user()
        db = AsyncMock()

        with patch("app.api.mcp.get_accessible_credential", AsyncMock(return_value=credential)):
            result = await update_mcp_chat_tool(
                body=MCPChatToolUpdate(enabled=True, credential_id=credential.id, model="gpt-5"),
                current_user=user,
                db=db,
            )

        self.assertTrue(result.enabled)
        self.assertEqual(result.credential_id, credential.id)
        self.assertEqual(result.model, "gpt-5")
        self.assertTrue(user.mcp_chat_enabled)

    async def test_partial_update_leaves_untouched_fields_alone(self) -> None:
        credential_id = uuid.uuid4()
        user = _make_user(
            mcp_chat_enabled=True, mcp_chat_credential_id=credential_id, mcp_chat_model="gpt-5"
        )
        db = AsyncMock()

        result = await update_mcp_chat_tool(
            body=MCPChatToolUpdate(enabled=False),
            current_user=user,
            db=db,
        )

        self.assertFalse(result.enabled)
        self.assertEqual(result.credential_id, credential_id)
        self.assertEqual(result.model, "gpt-5")

    async def test_clearing_the_credential_is_distinguished_from_omitting_it(self) -> None:
        user = _make_user(mcp_chat_credential_id=uuid.uuid4(), mcp_chat_model="gpt-5")
        db = AsyncMock()

        result = await update_mcp_chat_tool(
            body=MCPChatToolUpdate(credential_id=None),
            current_user=user,
            db=db,
        )

        self.assertIsNone(result.credential_id)
        self.assertEqual(result.model, "gpt-5")

    async def test_non_llm_credential_is_rejected_with_400(self) -> None:
        from fastapi import HTTPException

        credential = _make_credential(CredentialType.slack)
        db = AsyncMock()

        with (
            patch("app.api.mcp.get_accessible_credential", AsyncMock(return_value=credential)),
            self.assertRaises(HTTPException) as ctx,
        ):
            await validate_chat_tool_credential(db, uuid.uuid4(), credential.id)

        self.assertEqual(ctx.exception.status_code, 400)

    async def test_unknown_credential_is_rejected_with_404(self) -> None:
        from fastapi import HTTPException

        db = AsyncMock()

        with (
            patch("app.api.mcp.get_accessible_credential", AsyncMock(return_value=None)),
            self.assertRaises(HTTPException) as ctx,
        ):
            await validate_chat_tool_credential(db, uuid.uuid4(), uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_no_credential_id_skips_validation(self) -> None:
        await validate_chat_tool_credential(AsyncMock(), uuid.uuid4(), None)


class MCPChatTurnPersistenceTests(unittest.IsolatedAsyncioTestCase):
    """The turn runner must record MCP traffic in the Chat tab history."""

    async def test_new_conversation_is_tagged_as_mcp(self) -> None:
        from app.api.chats import MCP_CONVERSATION_SOURCE, _get_or_create_mcp_conversation

        added: list = []
        db = AsyncMock()
        db.add = MagicMock(side_effect=added.append)

        conversation, is_new = await _get_or_create_mcp_conversation(db, uuid.uuid4(), None)

        self.assertTrue(is_new)
        self.assertEqual(conversation.source, MCP_CONVERSATION_SOURCE)
        self.assertEqual(added, [conversation])

    async def test_continuing_a_foreign_conversation_is_refused(self) -> None:
        from app.api.chats import _get_or_create_mcp_conversation

        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        with self.assertRaises(MCPChatError):
            await _get_or_create_mcp_conversation(db, uuid.uuid4(), uuid.uuid4())

    async def test_existing_conversation_is_reused(self) -> None:
        from app.api.chats import _get_or_create_mcp_conversation

        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            source="mcp",
            title="Show analytics...",
            created_at=datetime.now(timezone.utc),
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=conversation))
        )

        resolved, is_new = await _get_or_create_mcp_conversation(db, uuid.uuid4(), conversation.id)

        self.assertFalse(is_new)
        self.assertIs(resolved, conversation)

    def test_hidden_workflow_markers_are_stripped_from_the_reply(self) -> None:
        from app.api.chats import _strip_hidden_markers

        content = "Done.\n<!-- heym-workflow-id:abc heym-workflow-name:Daily report -->"

        self.assertEqual(_strip_hidden_markers(content), "Done.")


if __name__ == "__main__":
    unittest.main()
