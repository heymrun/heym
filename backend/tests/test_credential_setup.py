"""`request_credential_form`: MCP chat turns open credential forms on a Heym page."""

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.api import chat_build
from app.api.ai_assistant import DASHBOARD_CHAT_TOOLS
from app.db.models import CredentialSetupRequest, CredentialType
from app.services import credential_setup
from app.services.chat_build_mode import BuildRequest
from app.services.credential_catalog import CredentialPromptMode, format_credentials_prompt
from app.services.credential_setup import (
    REQUEST_CREDENTIAL_FORM_TOOL,
    CredentialFormTool,
    record_elicitation_reply,
    settle_form_step,
    wait_for_conversation_forms,
)
from app.services.mcp_chat_service import (
    MCPChatResult,
    MCPChatSettings,
    build_chat_mcp_tool,
    format_chat_tool_text,
    run_chat_tool,
)
from app.services.mcp_elicitation import ElicitationReply, MCPClientChannel

BASE_URL = "https://heym.run"


class _FakeSessions:
    """Stands in for `async_session_maker`; every session shares one mock."""

    def __init__(self, execute: Any = None) -> None:
        self.session = MagicMock()
        self.session.add = MagicMock()
        self.session.commit = AsyncMock()
        self.session.execute = (
            AsyncMock(side_effect=execute) if execute is not None else AsyncMock()
        )

    def __call__(self) -> "_FakeSessions":
        return self

    async def __aenter__(self) -> MagicMock:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None

    @property
    def added(self) -> list[CredentialSetupRequest]:
        return [c.args[0] for c in self.session.add.call_args_list]


def _state(status: str, client_action: str | None = None, name: str | None = None) -> MagicMock:
    credential_id = uuid.uuid4() if name else None
    row = (status, client_action, credential_id, name, CredentialType.github if name else None)
    return MagicMock(first=MagicMock(return_value=row))


def _client(*modes: str) -> MCPClientChannel:
    return MCPClientChannel(frozenset(modes), AsyncMock())


class CredentialFormToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()
        self.conversation_id = uuid.uuid4()
        poll = patch.object(credential_setup, "FORM_POLL_SECONDS", 0)
        poll.start()
        self.addCleanup(poll.stop)

    def _tool(self, sessions: _FakeSessions, client: MCPClientChannel | None) -> CredentialFormTool:
        return CredentialFormTool(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            public_base_url=BASE_URL,
            client=client,
            session_factory=sessions,
        )

    async def test_a_client_without_url_mode_gets_a_link_to_heym(self) -> None:
        for client in (None, _client("form")):
            with self.subTest(client=client):
                sessions = _FakeSessions()
                tool = self._tool(sessions, client)

                outcome = await tool.call(
                    {"action": "create", "credential_type": "github", "name": "GitHub"}
                )

                request = sessions.added[0]
                url = f"{BASE_URL}/credentials/setup/{request.id}"
                payload = json.loads(outcome.result)
                self.assertEqual(payload["status"], "waiting_for_user")
                self.assertEqual(payload["url"], url)
                self.assertEqual(tool.waiting_urls, [url])
                self.assertEqual(
                    (request.user_id, request.conversation_id, request.action),
                    (self.user_id, self.conversation_id, "create"),
                )
                self.assertEqual(
                    (request.credential_type, request.suggested_name), ("github", "GitHub")
                )
                self.assertEqual(request.status, "pending")
                self.assertGreater(
                    request.expires_at, datetime.now(timezone.utc) + timedelta(hours=23)
                )
                if client is not None:
                    client.send.assert_not_awaited()

    async def test_the_turn_waits_and_continues_with_the_created_credential(self) -> None:
        sessions = _FakeSessions(
            [
                _state("pending"),
                _state("pending", "accept"),
                _state("completed", "accept", "GitHub"),
            ]
        )
        client = _client("url")
        tool = self._tool(sessions, client)

        outcome = await tool.call(
            {"action": "create", "credential_type": "github", "reason": "For the repo digest."}
        )

        request = sessions.added[0]
        elicitation, completed = [c.args[0] for c in client.send.await_args_list]
        self.assertEqual(elicitation["method"], "elicitation/create")
        self.assertEqual(
            elicitation["params"],
            {
                "mode": "url",
                "elicitationId": str(request.id),
                "url": f"{BASE_URL}/credentials/setup/{request.id}",
                "message": "For the repo digest.",
            },
        )
        self.assertEqual(completed["method"], "notifications/elicitation/complete")
        self.assertEqual(completed["params"]["elicitationId"], str(request.id))
        payload = json.loads(outcome.result)
        self.assertEqual(payload["status"], "created")
        self.assertEqual(payload["credential"]["name"], "GitHub")
        self.assertEqual(payload["credential"]["type"], "github")
        self.assertEqual(outcome.summary, 'Created credential "GitHub"')
        self.assertEqual(tool.waiting_urls, [])

    async def test_a_decline_ends_the_wait_without_a_credential(self) -> None:
        sessions = _FakeSessions([_state("declined", "decline")])
        tool = self._tool(sessions, _client("url"))

        outcome = await tool.call({"action": "create", "credential_type": "slack_bot"})

        self.assertEqual(json.loads(outcome.result)["status"], "declined")
        self.assertEqual(tool.waiting_urls, [])

    async def test_a_dismissed_or_failed_elicitation_hands_back_the_link(self) -> None:
        for action in ("cancel", "error"):
            with self.subTest(action=action):
                sessions = _FakeSessions([_state("pending", action)])
                tool = self._tool(sessions, _client("url"))

                outcome = await tool.call({"action": "create", "credential_type": "notion"})

                self.assertEqual(json.loads(outcome.result)["status"], "waiting_for_user")
                self.assertEqual(len(tool.waiting_urls), 1)

    async def test_a_client_that_went_away_gets_the_link(self) -> None:
        sessions = _FakeSessions()
        client = MCPClientChannel(frozenset({"url"}), AsyncMock(side_effect=RuntimeError("gone")))
        tool = self._tool(sessions, client)

        outcome = await tool.call({"action": "create", "credential_type": "github"})

        self.assertEqual(json.loads(outcome.result)["status"], "waiting_for_user")
        sessions.session.execute.assert_not_awaited()

    async def test_the_wait_ends_on_timeout_or_stop(self) -> None:
        with patch.object(credential_setup, "FORM_WAIT_SECONDS", 0.05):
            sessions = _FakeSessions()
            sessions.session.execute = AsyncMock(return_value=_state("pending"))
            outcome = await self._tool(sessions, _client("url")).call(
                {"action": "create", "credential_type": "github"}
            )
        self.assertEqual(json.loads(outcome.result)["status"], "waiting_for_user")

        stopped = Event()
        stopped.set()
        sessions = _FakeSessions()
        outcome = await self._tool(sessions, _client("url")).call(
            {"action": "create", "credential_type": "github"}, cancel_event=stopped
        )
        self.assertEqual(json.loads(outcome.result)["status"], "waiting_for_user")
        sessions.session.execute.assert_not_awaited()

    async def test_bad_arguments_open_no_form(self) -> None:
        for args in (
            {"action": "create", "credential_type": "not-a-type"},
            {"action": "delete"},
            {"action": "update", "credential_id": "nope"},
        ):
            with self.subTest(args=args):
                sessions = _FakeSessions()
                outcome = await self._tool(sessions, _client("url")).call(args)

                self.assertEqual(outcome.status, "error")
                self.assertEqual(sessions.added, [])

    async def test_only_an_owned_credential_can_be_updated(self) -> None:
        credential_id = uuid.uuid4()
        for owner_id, expected in ((uuid.uuid4(), "error"), (None, "pending")):
            with self.subTest(owned=owner_id is None):
                row = SimpleNamespace(
                    name="Work GitHub",
                    type=CredentialType.github,
                    owner_id=owner_id or self.user_id,
                )
                sessions = _FakeSessions([MagicMock(first=MagicMock(return_value=row))])
                outcome = await self._tool(sessions, None).call(
                    {"action": "update", "credential_id": str(credential_id)}
                )

                self.assertEqual(outcome.status, expected)
                if expected == "pending":
                    request = sessions.added[0]
                    self.assertEqual(
                        (request.action, request.credential_id, request.credential_type),
                        ("update", credential_id, "github"),
                    )
                    self.assertEqual(request.suggested_name, "Work GitHub")
                else:
                    self.assertEqual(sessions.added, [])


class ConversationFormsPromptTests(unittest.IsolatedAsyncioTestCase):
    def _tool(
        self, sessions: _FakeSessions, conversation_id: uuid.UUID | None
    ) -> CredentialFormTool:
        return CredentialFormTool(
            user_id=uuid.uuid4(),
            conversation_id=conversation_id,
            public_base_url=BASE_URL,
            client=None,
            session_factory=sessions,
        )

    async def test_the_next_turn_learns_what_became_of_each_form(self) -> None:
        later = datetime.now(timezone.utc) + timedelta(hours=1)
        earlier = datetime.now(timezone.utc) - timedelta(hours=1)
        saved_id, open_id = uuid.uuid4(), uuid.uuid4()
        rows = [
            (
                uuid.uuid4(),
                "create",
                "header",
                "tanay",
                "completed",
                later,
                saved_id,
                "tanay",
                CredentialType.header,
            ),
            (open_id, "create", "github", "GitHub", "pending", later, None, None, None),
            (uuid.uuid4(), "create", "notion", None, "declined", later, None, None, None),
            (uuid.uuid4(), "update", "slack_bot", "Ops bot", "pending", earlier, None, None, None),
        ]
        sessions = _FakeSessions([MagicMock(all=MagicMock(return_value=rows))])

        prompt = await self._tool(sessions, uuid.uuid4()).conversation_forms_prompt()

        self.assertIn("## Credential forms in this conversation", prompt)
        self.assertIn("never a credential id", prompt)
        self.assertIn(f'- Created: "tanay" (header), credential id `{saved_id}`', prompt)
        self.assertIn(
            f'- Still open: the github form for "GitHub", {BASE_URL}/credentials/setup/{open_id}',
            prompt,
        )
        self.assertIn("- Declined: the notion form.", prompt)
        self.assertIn('- Expired: the slack_bot form for "Ops bot".', prompt)

    async def test_nothing_is_added_without_forms(self) -> None:
        sessions = _FakeSessions([MagicMock(all=MagicMock(return_value=[]))])
        self.assertEqual(await self._tool(sessions, uuid.uuid4()).conversation_forms_prompt(), "")

        sessions = _FakeSessions()
        self.assertEqual(await self._tool(sessions, None).conversation_forms_prompt(), "")
        sessions.session.execute.assert_not_awaited()


def _form_step(args: dict[str, Any], status: str = "pending") -> dict[str, Any]:
    return {
        "id": "call_1",
        "name": REQUEST_CREDENTIAL_FORM_TOOL,
        "label": "Opening the credential form...",
        "args": args,
        "status": status,
        "response_summary": "Waiting for the credential form",
    }


class SettleFormStepTests(unittest.IsolatedAsyncioTestCase):
    def _row(self, **overrides: Any) -> CredentialSetupRequest:
        values: dict[str, Any] = {
            "id": uuid.uuid4(),
            "user_id": uuid.uuid4(),
            "conversation_id": uuid.uuid4(),
            "action": "create",
            "credential_type": "header",
            "suggested_name": "tanay",
            "credential_id": None,
            "status": "completed",
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        values.update(overrides)
        return CredentialSetupRequest(**values)

    async def _settle(self, row: CredentialSetupRequest, messages: list[Any]) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=messages)))
        await settle_form_step(db, row, 'Created credential "tanay"')

    async def test_the_step_that_opened_the_form_is_finished(self) -> None:
        other = _form_step({"action": "create", "credential_type": "github", "name": "GitHub"})
        opened = _form_step({"action": "create", "credential_type": "header", "name": " tanay "})
        message = SimpleNamespace(tool_calls=[other, opened])

        await self._settle(self._row(), [message])

        self.assertEqual(message.tool_calls[0], other)
        self.assertEqual(message.tool_calls[1]["status"], "success")
        self.assertEqual(message.tool_calls[1]["response_summary"], 'Created credential "tanay"')
        self.assertEqual(message.tool_calls[1]["label"], "Opening the credential form...")

    async def test_an_update_matches_by_credential_id(self) -> None:
        credential_id = uuid.uuid4()
        step = _form_step({"action": "update", "credential_id": str(credential_id).upper()})
        message = SimpleNamespace(tool_calls=[step])

        await self._settle(self._row(action="update", credential_id=credential_id), [message])

        self.assertEqual(message.tool_calls[0]["status"], "success")

    async def test_finished_or_unrelated_steps_stay_as_they_are(self) -> None:
        done = _form_step(
            {"action": "create", "credential_type": "header", "name": "tanay"}, "success"
        )
        unrelated = {"id": "call_2", "name": "save_workflow", "status": "pending", "args": {}}
        message = SimpleNamespace(tool_calls=[done, unrelated])

        await self._settle(self._row(), [message])

        self.assertEqual(message.tool_calls, [done, unrelated])

    async def test_a_form_without_a_conversation_touches_nothing(self) -> None:
        db = AsyncMock()
        await settle_form_step(db, self._row(conversation_id=None), "x")
        db.execute.assert_not_awaited()


class FollowUpWaitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for name, value in (("FORM_POLL_SECONDS", 0), ("FORM_FOLLOW_UP_WAIT_SECONDS", 0.05)):
            patcher = patch.object(credential_setup, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def _wait(self, sessions: _FakeSessions) -> list[str]:
        return await wait_for_conversation_forms(
            user_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            public_base_url=BASE_URL,
            session_factory=sessions,
        )

    async def test_the_wait_ends_when_the_user_saves_the_form(self) -> None:
        open_id = uuid.uuid4()
        sessions = _FakeSessions(
            [
                MagicMock(scalars=MagicMock(return_value=[open_id])),
                MagicMock(scalars=MagicMock(return_value=[])),
            ]
        )

        self.assertEqual(await self._wait(sessions), [])
        self.assertEqual(sessions.session.execute.await_count, 2)

    async def test_a_form_still_open_comes_back_as_its_link(self) -> None:
        open_id = uuid.uuid4()
        sessions = _FakeSessions()
        sessions.session.execute = AsyncMock(
            return_value=MagicMock(scalars=MagicMock(return_value=[open_id]))
        )

        self.assertEqual(await self._wait(sessions), [f"{BASE_URL}/credentials/setup/{open_id}"])


class ChatToolFormWaitTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self, arguments: dict[str, Any], still_open: list[str]
    ) -> tuple[Any, AsyncMock, AsyncMock]:
        resolved = SimpleNamespace(credential=SimpleNamespace(id=uuid.uuid4()), model="gpt-5.5")
        turn = AsyncMock(
            return_value=MCPChatResult(
                uuid.uuid4(), "Created it.", [], awaiting_clarification=False
            )
        )
        with (
            patch(
                "app.services.mcp_chat_service.resolve_chat_llm", AsyncMock(return_value=resolved)
            ),
            patch(
                "app.services.mcp_chat_service.wait_for_conversation_forms",
                AsyncMock(return_value=still_open),
            ) as wait,
            patch("app.api.chats.run_mcp_chat_turn", turn),
        ):
            result = await run_chat_tool(
                AsyncMock(),
                user_id=uuid.uuid4(),
                settings=MCPChatSettings(enabled=True, credential_id=None, model=None),
                arguments=arguments,
                public_base_url=BASE_URL,
            )
        return result, turn, wait

    async def test_a_saved_form_continues_the_conversation(self) -> None:
        conversation_id = str(uuid.uuid4())
        args = {
            "message": "I saved the credential form.",
            "conversation_id": conversation_id,
            "wait_for_credential_form": True,
        }

        result, turn, wait = await self._run(args, [])

        wait.assert_awaited_once()
        turn.assert_awaited_once()
        self.assertEqual(turn.await_args.kwargs["message"], "I saved the credential form.")
        self.assertEqual(result.text, "Created it.")

    async def test_a_form_still_open_returns_its_link_without_a_turn(self) -> None:
        url = f"{BASE_URL}/credentials/setup/{uuid.uuid4()}"
        args = {
            "message": "I saved the credential form.",
            "conversation_id": str(uuid.uuid4()),
            "wait_for_credential_form": True,
        }

        result, turn, _wait = await self._run(args, [url])

        turn.assert_not_awaited()
        self.assertEqual(result.credential_form_urls, (url,))
        self.assertIn(url, format_chat_tool_text(result))

    async def test_calls_without_the_flag_never_wait(self) -> None:
        for args in (
            {"message": "hi", "conversation_id": str(uuid.uuid4())},
            {"message": "hi", "wait_for_credential_form": True},
        ):
            with self.subTest(args=args):
                _result, turn, wait = await self._run(args, ["unused"])
                wait.assert_not_awaited()
                turn.assert_awaited_once()

    def test_the_tool_offers_the_wait_flag(self) -> None:
        schema = build_chat_mcp_tool().inputSchema
        self.assertEqual(schema.properties["wait_for_credential_form"].type, "boolean")
        self.assertEqual(schema.required, ["message"])


class ElicitationReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_reply_only_touches_the_users_pending_request(self) -> None:
        user_id, elicitation_id = uuid.uuid4(), uuid.uuid4()
        for action, closes in (("decline", True), ("accept", False), ("cancel", False)):
            with self.subTest(action=action):
                db = AsyncMock()
                await record_elicitation_reply(
                    db, user_id, ElicitationReply(elicitation_id, action)
                )

                params = db.execute.await_args.args[0].compile().params
                self.assertEqual(params["client_action"], action)
                self.assertEqual(params["id_1"], elicitation_id)
                self.assertEqual(params["user_id_1"], user_id)
                self.assertEqual(params["status_1"], "pending")
                self.assertEqual(params.get("status") == "declined", closes)


class CredentialFormPromptTests(unittest.TestCase):
    def test_mcp_turns_use_the_form_tool_and_never_ask_for_secrets(self) -> None:
        prompt = format_credentials_prompt([], CredentialPromptMode.ASK_AND_LINK)

        self.assertIn("`request_credential_form`", prompt)
        self.assertIn("Never ask the user to paste a key", prompt)
        self.assertNotIn('"create": {"type"', prompt)
        self.assertNotIn('"edit": {"id"', prompt)

    def test_ui_turns_keep_the_dialog_card(self) -> None:
        prompt = format_credentials_prompt([], CredentialPromptMode.ASK_AND_CREATE)

        self.assertIn('"create": {"type"', prompt)
        self.assertNotIn("request_credential_form", prompt)


class MCPResultTextTests(unittest.TestCase):
    def _result(self, text: str, urls: tuple[str, ...]) -> MCPChatResult:
        return MCPChatResult(
            conversation_id=uuid.uuid4(),
            text=text,
            tool_names=[REQUEST_CREDENTIAL_FORM_TOOL],
            awaiting_clarification=False,
            credential_form_urls=urls,
        )

    def test_a_link_the_model_left_out_is_added_once(self) -> None:
        url = f"{BASE_URL}/credentials/setup/{uuid.uuid4()}"

        added = format_chat_tool_text(self._result("Open the form, then reply.", (url,)))
        kept = format_chat_tool_text(self._result(f"Open [the form]({url}).", (url,)))

        self.assertEqual(added.count(url), 1)
        self.assertIn("never pass through this client", added)
        self.assertEqual(kept.count(url), 1)
        for text in (added, kept):
            self.assertIn("wait_for_credential_form set to true", text)

    def test_no_wait_instruction_without_an_open_form(self) -> None:
        self.assertNotIn(
            "wait_for_credential_form", format_chat_tool_text(self._result("Done.", ()))
        )


class BuildSessionCredentialFormTests(unittest.IsolatedAsyncioTestCase):
    def _session(self, form: CredentialFormTool | None) -> chat_build.ChatBuildSession:
        user = SimpleNamespace(id=uuid.uuid4(), email="owner@example.com", user_rules=None)
        return chat_build.ChatBuildSession(
            db=MagicMock(),
            user=user,
            request=BuildRequest(),
            selected_credential=SimpleNamespace(id=uuid.uuid4(), owner_id=user.id, type="openai"),
            model="gpt-5.5",
            credential_mode=CredentialPromptMode.ASK_AND_LINK,
            public_base_url=BASE_URL,
            cancel_event=None,
            llm_session_id="conv-1",
            credential_form=form,
        )

    async def test_only_mcp_turns_offer_the_form_tool(self) -> None:
        ui_names = [t["function"]["name"] for t in self._session(None).tools(DASHBOARD_CHAT_TOOLS)]
        self.assertNotIn(REQUEST_CREDENTIAL_FORM_TOOL, ui_names)
        self.assertFalse(self._session(None).handles(REQUEST_CREDENTIAL_FORM_TOOL))

        form = MagicMock(spec=CredentialFormTool)
        form.call = AsyncMock(
            return_value=credential_setup.CredentialFormOutcome(
                result='{"status": "created"}',
                summary='Created credential "GitHub"',
                status="success",
            )
        )
        session = self._session(form)
        names = [t["function"]["name"] for t in session.tools(DASHBOARD_CHAT_TOOLS)]

        self.assertIn(REQUEST_CREDENTIAL_FORM_TOOL, names)
        self.assertTrue(session.handles(REQUEST_CREDENTIAL_FORM_TOOL))
        outcome = await session.call(REQUEST_CREDENTIAL_FORM_TOOL, {"action": "create"})
        self.assertEqual(outcome.summary, 'Created credential "GitHub"')
        form.call.assert_awaited_once_with({"action": "create"}, cancel_event=None)


if __name__ == "__main__":
    unittest.main()
