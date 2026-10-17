"""Slack node operations on a bot token, and answers that come back from Slack."""

import hashlib
import hmac
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

from fastapi import BackgroundTasks, HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from app.services import slack_service as slack
from app.services.node_execution.base import NodeExecutionContext
from app.services.slack_operations import run_bot_operation


class _Executor:
    """Resolves `$name` to fixed values, the way a template would after an earlier step."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = values or {}

    def evaluate_message_template(self, template: str, _inputs: dict, _node_id: str) -> str:
        for key, value in self.values.items():
            template = template.replace(key, value)
        return template


def _ctx(data: dict, values: dict[str, str] | None = None) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=_Executor(values),
        node_id="n1",
        inputs={},
        allow_branch_skip=False,
        start_time=time.time(),
        node={"id": "n1", "type": "slack", "data": data},
        node_type="slack",
        node_data=data,
        node_label=data.get("label", "slack"),
    )


def _posted(channel: str = "C0123456", ts: str = "1700000000.000100") -> dict:
    return {"ok": True, "channel": channel, "ts": ts, "message": {"ts": ts}}


CONFIG = {"bot_token": "xoxb-test", "signing_secret": "secret"}


class TestPostingOperations(unittest.TestCase):
    def test_send_message_resolves_a_channel_name_and_returns_where_it_landed(self) -> None:
        calls: list[tuple[str, dict]] = []

        def fake(_token: str, method: str, payload: dict | None = None, *, read: bool = False):
            calls.append((method, payload or {}))
            if method == "conversations.list":
                return {"ok": True, "channels": [{"id": "C0OPS1234", "name": "ops"}]}
            return _posted("C0OPS1234")

        with patch.object(slack, "call_slack", side_effect=fake):
            output = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "sendMessage",
                        "slackChannel": "#ops",
                        "message": "Deployed $v",
                    },
                    {"$v": "1.2"},
                ),
                "cred",
                CONFIG,
            )

        self.assertEqual(
            calls[-1], ("chat.postMessage", {"channel": "C0OPS1234", "text": "Deployed 1.2"})
        )
        self.assertEqual(output["channel"], "C0OPS1234")
        self.assertEqual(output["threadTs"], output["ts"])

    def test_direct_message_to_an_email_opens_the_dm_first(self) -> None:
        methods: list[str] = []

        def fake(_token: str, method: str, payload: dict | None = None, *, read: bool = False):
            methods.append(method)
            if method == "users.lookupByEmail":
                return {"ok": True, "user": {"id": "U0ALICE12"}}
            if method == "conversations.open":
                return {"ok": True, "channel": {"id": "D0ALICE12"}}
            return _posted("D0ALICE12")

        with patch.object(slack, "call_slack", side_effect=fake):
            output = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "sendDirectMessage",
                        "slackUser": "alice@example.com",
                        "message": "Hi",
                    }
                ),
                "cred",
                CONFIG,
            )

        self.assertEqual(methods, ["users.lookupByEmail", "conversations.open", "chat.postMessage"])
        self.assertEqual(output["user"], "U0ALICE12")

    def test_reply_in_thread_requires_the_thread(self) -> None:
        with patch.object(slack, "call_slack", return_value=_posted()):
            with self.assertRaisesRegex(ValueError, "thread timestamp"):
                run_bot_operation(
                    _ctx(
                        {
                            "slackOperation": "replyInThread",
                            "slackChannel": "C0123456",
                            "message": "x",
                        }
                    ),
                    "cred",
                    CONFIG,
                )

    def test_outcome_card_is_colored_by_status(self) -> None:
        with patch.object(slack, "call_slack", return_value=_posted()) as call:
            output = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "postOutcome",
                        "slackChannel": "C0123456",
                        "slackThreadTs": "1.1",
                        "slackOutcomeStatus": "failure",
                        "slackOutcomeTitle": "Import failed",
                        "message": "3 rows rejected",
                    }
                ),
                "cred",
                CONFIG,
            )
        payload = call.call_args.args[2]
        self.assertEqual(payload["thread_ts"], "1.1")
        self.assertEqual(payload["attachments"][0]["color"], "#dc2626")
        self.assertEqual(output["status"], "failure")

    def test_outcome_can_follow_an_approval(self) -> None:
        with patch.object(slack, "call_slack", return_value=_posted()):
            output = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "postOutcome",
                        "slackChannel": "C0123456",
                        "slackOutcomeStatus": "$approval",
                        "slackOutcomeTitle": "Refund",
                    },
                    {"$approval": "rejected"},
                ),
                "cred",
                CONFIG,
            )
        self.assertEqual(output["status"], "failure")

    def test_find_user_needs_no_channel(self) -> None:
        user = {
            "id": "U0BOB1234",
            "name": "bob",
            "profile": {"real_name": "Bob", "email": "b@x.io"},
        }
        with patch.object(slack, "call_slack", return_value={"ok": True, "user": user}):
            output = run_bot_operation(
                _ctx({"slackOperation": "findUser", "slackUser": "U0BOB1234"}), "c", CONFIG
            )
        self.assertEqual(output["realName"], "Bob")

    def test_read_messages_gives_a_transcript_oldest_first_with_names(self) -> None:
        history = {
            "ok": True,
            "messages": [
                {"ts": "1700000600.0", "user": "U0BOB1234", "text": "Done, <@U0ANA1234>"},
                {"ts": "1700000000.0", "user": "U0ANA1234", "text": "Who deploys?"},
            ],
        }

        def fake(_token: str, method: str, payload: dict | None = None, *, read: bool = False):
            if method == "users.info":
                name = {"U0ANA1234": "Ana", "U0BOB1234": "Bob"}[(payload or {})["user"]]
                return {"ok": True, "user": {"profile": {"display_name": name}}}
            return history

        with patch.object(slack, "call_slack", side_effect=fake):
            output = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "getMessages",
                        "slackChannel": "C0123456",
                        "slackLimit": "10",
                    }
                ),
                "c",
                CONFIG,
            )
        self.assertEqual(
            output["transcript"],
            "[2023-11-14 22:13] Ana: Who deploys?\n[2023-11-14 22:23] Bob: Done, @Ana",
        )

    def test_model_markdown_is_posted_as_slack_formatting(self) -> None:
        with patch.object(slack, "call_slack", return_value=_posted()) as call:
            run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "sendMessage",
                        "slackChannel": "C0123456",
                        "message": "$draft",
                    },
                    {"$draft": "## Digest\n**Ship** it, see [notes](https://x.io)"},
                ),
                "cred",
                CONFIG,
            )
        self.assertEqual(
            call.call_args.args[2]["text"], "*Digest*\n*Ship* it, see <https://x.io|notes>"
        )

    def test_unknown_operation_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Slack operation"):
            run_bot_operation(_ctx({"slackOperation": "nope"}), "cred", CONFIG)

    def test_slack_errors_name_the_missing_scope(self) -> None:
        response = MagicMock(status_code=200)
        response.json.return_value = {"ok": False, "error": "missing_scope", "needed": "im:write"}
        client = MagicMock()
        client.post.return_value = response
        with patch.object(slack.ssrf_guard, "get_guarded_http_client", return_value=client):
            with self.assertRaisesRegex(slack.SlackApiError, "im:write"):
                slack.call_slack("xoxb", "conversations.open", {"users": "U1"})


class TestWaitingOperations(unittest.TestCase):
    def test_request_approval_pauses_with_a_key_on_every_button(self) -> None:
        with patch.object(slack, "call_slack", return_value=_posted()) as call:
            result = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "requestApproval",
                        "slackChannel": "C0123456",
                        "message": "Refund $40?",
                    }
                ),
                "cred-1",
                CONFIG,
            )

        self.assertEqual(result.status, "pending")
        hitl = result.metadata["hitl"]
        self.assertEqual(hitl["resume_mode"], "inject_output")
        internals = hitl["original_agent_output"]["_slack"]
        self.assertEqual(internals["kind"], "approval")
        self.assertEqual(internals["credentialId"], "cred-1")
        buttons = call.call_args.args[2]["blocks"][1]["elements"]
        self.assertEqual(
            [b["action_id"] for b in buttons], ["heym_approve", "heym_changes", "heym_reject"]
        )
        self.assertTrue(all(b["value"] == internals["key"] for b in buttons))
        self.assertIsNone(result.output["decision"])

    def test_buttons_and_form_keep_what_the_answer_needs(self) -> None:
        with patch.object(slack, "call_slack", return_value=_posted()):
            buttons = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "sendButtons",
                        "slackChannel": "C0123456",
                        "message": "Retry?",
                        "slackButtons": [{"label": "Retry", "value": "retry"}, {"label": ""}],
                    }
                ),
                "c",
                CONFIG,
            )
            form = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "sendForm",
                        "slackChannel": "C0123456",
                        "message": "Details please",
                        "slackFormTitle": "Incident",
                        "slackFormFields": [
                            {"label": "Severity", "type": "select", "options": "low, high"}
                        ],
                    }
                ),
                "c",
                CONFIG,
            )
        self.assertEqual(
            buttons.metadata["hitl"]["original_agent_output"]["_slack"]["buttons"],
            [{"label": "Retry", "value": "retry", "style": ""}],
        )
        fields = form.metadata["hitl"]["original_agent_output"]["_slack"]["fields"]
        self.assertEqual(fields[0]["name"], "severity")
        self.assertEqual(fields[0]["options"], ["low", "high"])

    def test_allowed_users_are_resolved_to_ids_before_posting(self) -> None:
        def fake(_token: str, method: str, payload: dict | None = None, *, read: bool = False):
            if method == "users.lookupByEmail":
                return {"ok": True, "user": {"id": "U0LEAD123"}}
            return _posted()

        with patch.object(slack, "call_slack", side_effect=fake):
            result = run_bot_operation(
                _ctx(
                    {
                        "slackOperation": "requestApproval",
                        "slackChannel": "C0123456",
                        "message": "Ship?",
                        "slackAllowedUsers": "lead@example.com, <@U0OWNER12>",
                    }
                ),
                "c",
                CONFIG,
            )
        allowed = result.metadata["hitl"]["original_agent_output"]["_slack"]["allowedUsers"]
        self.assertEqual(allowed, ["U0LEAD123", "U0OWNER12"])


class TestMrkdwn(unittest.TestCase):
    def test_markdown_becomes_slack_formatting(self) -> None:
        self.assertEqual(slack.to_slack_mrkdwn("# Title"), "*Title*")
        self.assertEqual(slack.to_slack_mrkdwn("**a** and __b__ and ~~c~~"), "*a* and *b* and ~c~")
        self.assertEqual(slack.to_slack_mrkdwn("- one\n* two"), "• one\n• two")
        self.assertEqual(slack.to_slack_mrkdwn("[docs](https://x.io)"), "<https://x.io|docs>")

    def test_slack_syntax_and_code_stay_as_they_are(self) -> None:
        text = "*bold* _it_ <https://x.io|x> <@U1>\n`**raw**`\n```\n## not a heading\n```"
        self.assertEqual(slack.to_slack_mrkdwn(text), text)


class TestFormsAndOutputs(unittest.TestCase):
    def test_form_modal_and_submitted_values(self) -> None:
        fields = slack.normalize_form_fields(
            [
                {"label": "Amount", "type": "number"},
                {"label": "Due", "type": "date", "required": False},
                {"label": "Team", "type": "select", "options": ["a", "b"]},
            ]
        )
        modal = slack.form_modal("k", "A very long form title here", fields, "Send")
        self.assertEqual(modal["private_metadata"], "k")
        self.assertLessEqual(len(modal["title"]["text"]), 24)
        self.assertEqual([b["block_id"] for b in modal["blocks"]], ["amount", "due", "team"])
        state = {
            "values": {
                "amount": {"value": {"value": "12.5"}},
                "due": {"value": {"selected_date": "2026-10-20"}},
                "team": {"value": {"selected_option": {"value": "b"}}},
            }
        }
        self.assertEqual(
            slack.read_form_values(state, fields),
            {"amount": "12.5", "due": "2026-10-20", "team": "b"},
        )

    def test_resolved_output_drops_internals_and_names_the_answer(self) -> None:
        output = {
            "channel": "C1",
            "_slack": {
                "kind": "approval",
                "key": "k",
                "answer": {"approval": "approved", "user": {"id": "U1"}},
            },
        }
        resolved = slack.resolved_slack_output(
            output, decision="accept", edited_text=None, refusal_reason=None
        )
        self.assertNotIn("_slack", resolved)
        self.assertEqual(resolved["approval"], "approved")
        self.assertEqual(resolved["answeredIn"], "slack")

    def test_a_heym_decision_maps_to_the_same_approval_words(self) -> None:
        resolved = slack.resolved_slack_output(
            {"_slack": {"kind": "approval", "key": "k"}},
            decision="edit",
            edited_text="Lower the amount",
            refusal_reason=None,
        )
        self.assertEqual(resolved["approval"], "changes_requested")
        self.assertEqual(resolved["comment"], "Lower the amount")
        self.assertEqual(resolved["answeredIn"], "heym")
        self.assertIsNone(resolved["answeredBy"])

    def test_build_hitl_resolved_output_applies_the_slack_mapping(self) -> None:
        from app.services.hitl_service import build_hitl_resolved_output

        request = SimpleNamespace(
            id=uuid.uuid4(),
            original_agent_output={
                "channel": "C1",
                "ts": "1.1",
                "_slack": {
                    "kind": "buttons",
                    "key": "k",
                    "answer": {"choice": {"label": "Retry", "value": "retry"}},
                },
            },
            decision="accept",
            original_draft_text="Retry?",
            edited_text=None,
            refusal_reason=None,
            summary="Waiting",
        )
        resolved = build_hitl_resolved_output(request)
        self.assertEqual(resolved["choice"]["value"], "retry")
        self.assertEqual(resolved["ts"], "1.1")
        self.assertNotIn("_slack", resolved)


class TestAnswers(unittest.TestCase):
    def _request(self, **internals: object) -> SimpleNamespace:
        return SimpleNamespace(
            original_agent_output={"_slack": {"kind": "approval", "key": "k", **internals}}
        )

    def test_actions_map_to_review_decisions(self) -> None:
        from app.services.slack_interactions import answer_for_action

        user = {"id": "U1", "name": "ana"}
        request = self._request(buttons=[{"label": "Retry", "value": "retry"}])
        self.assertEqual(answer_for_action(request, "heym_approve", user).decision, "accept")
        rejected = answer_for_action(request, "heym_reject", user)
        self.assertEqual(rejected.decision, "refuse")
        self.assertIn("ana", rejected.refusal_reason)
        choice = answer_for_action(request, "heym_choice:0", user)
        self.assertEqual(choice.answer["choice"], {"label": "Retry", "value": "retry"})
        self.assertIsNone(answer_for_action(request, "heym_choice:9", user))
        self.assertIsNone(answer_for_action(request, "heym_changes", user))

    def test_request_changes_modal_becomes_an_edit_with_the_comment(self) -> None:
        from app.services.slack_interactions import answer_for_view

        view = {
            "callback_id": "heym_changes",
            "state": {"values": {"comment": {"value": {"value": "Split the invoice"}}}},
        }
        answer = answer_for_view(self._request(), view, {"id": "U1", "name": "ana"})
        self.assertEqual(answer.decision, "edit")
        self.assertEqual(answer.edited_text, "Split the invoice")
        self.assertEqual(answer.answer["approval"], "changes_requested")

    def test_allowed_users_limit_who_answers(self) -> None:
        from app.services.slack_interactions import may_answer

        self.assertTrue(may_answer(self._request(), "U9"))
        self.assertFalse(may_answer(self._request(allowedUsers=["U1"]), "U9"))
        self.assertTrue(may_answer(self._request(allowedUsers=["U1"]), "U1"))


def _signed_request(body: bytes, secret: str, *, timestamp: str | None = None) -> Request:
    stamp = timestamp or str(int(time.time()))
    signature = (
        "v0="
        + hmac.new(
            secret.encode(), f"v0:{stamp}:{body.decode()}".encode(), hashlib.sha256
        ).hexdigest()
    )
    headers = Headers(
        {
            "content-type": "application/x-www-form-urlencoded",
            "x-slack-request-timestamp": stamp,
            "x-slack-signature": signature,
        }
    )
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": headers.raw,
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


class TestInteractionsEndpoint(unittest.IsolatedAsyncioTestCase):
    def _body(self, payload: dict) -> bytes:
        return urlencode({"payload": json.dumps(payload)}).encode()

    async def test_a_credential_without_signing_secret_accepts_nothing(self) -> None:
        from app.api.slack_bot import slack_interactions

        config = slack.SlackBotConfig(bot_token="xoxb", signing_secret="")
        with patch("app.api.slack_bot.bot_credential", new=AsyncMock(return_value=config)):
            with self.assertRaises(HTTPException) as caught:
                await slack_interactions(
                    "c", _signed_request(b"payload=%7B%7D", "x"), BackgroundTasks(), AsyncMock()
                )
        self.assertEqual(caught.exception.status_code, 400)

    async def test_a_wrong_signature_is_refused(self) -> None:
        from app.api.slack_bot import slack_interactions

        config = slack.SlackBotConfig(bot_token="xoxb", signing_secret="right")
        with patch("app.api.slack_bot.bot_credential", new=AsyncMock(return_value=config)):
            with self.assertRaises(HTTPException) as caught:
                await slack_interactions(
                    "c",
                    _signed_request(self._body({"type": "block_actions"}), "wrong"),
                    BackgroundTasks(),
                    AsyncMock(),
                )
        self.assertEqual(caught.exception.status_code, 403)

    async def test_approve_click_resolves_the_review_and_schedules_the_resume(self) -> None:
        from app.api.slack_bot import slack_interactions

        config = slack.SlackBotConfig(bot_token="xoxb", signing_secret="s")
        request_row = SimpleNamespace(
            id=uuid.uuid4(), original_agent_output={"_slack": {"kind": "approval", "key": "k"}}
        )
        payload = {
            "type": "block_actions",
            "user": {"id": "U1", "username": "ana"},
            "actions": [{"action_id": "heym_approve", "value": "k"}],
            "response_url": "https://hooks.slack.com/actions/x",
        }
        tasks = BackgroundTasks()
        with (
            patch("app.api.slack_bot.bot_credential", new=AsyncMock(return_value=config)),
            patch(
                "app.api.slack_bot.find_waiting_request", new=AsyncMock(return_value=request_row)
            ),
            patch("app.api.slack_bot.record_answer", new=AsyncMock(return_value=True)) as record,
        ):
            response = await slack_interactions(
                "c", _signed_request(self._body(payload), "s"), tasks, AsyncMock()
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(record.await_args.args[2].decision, "accept")
        names = [task.func.__name__ for task in tasks.tasks]
        self.assertEqual(names, ["replace_buttons", "resume_hitl_request_in_background"])

    async def test_a_click_on_an_answered_request_only_tells_the_person(self) -> None:
        from app.api.slack_bot import slack_interactions

        config = slack.SlackBotConfig(bot_token="xoxb", signing_secret="s")
        payload = {
            "type": "block_actions",
            "user": {"id": "U1"},
            "actions": [{"action_id": "heym_approve", "value": "k"}],
            "response_url": "https://hooks.slack.com/actions/x",
        }
        tasks = BackgroundTasks()
        with (
            patch("app.api.slack_bot.bot_credential", new=AsyncMock(return_value=config)),
            patch("app.api.slack_bot.find_waiting_request", new=AsyncMock(return_value=None)),
            patch("app.api.slack_bot.record_answer", new=AsyncMock()) as record,
        ):
            await slack_interactions(
                "c", _signed_request(self._body(payload), "s"), tasks, AsyncMock()
            )

        record.assert_not_awaited()
        self.assertEqual([task.func.__name__ for task in tasks.tasks], ["_ephemeral"])

    async def test_form_button_opens_the_modal_with_the_stored_fields(self) -> None:
        from app.api.slack_bot import slack_interactions

        config = slack.SlackBotConfig(bot_token="xoxb", signing_secret="s")
        fields = slack.normalize_form_fields([{"label": "Reason"}])
        request_row = SimpleNamespace(
            id=uuid.uuid4(),
            original_agent_output={
                "_slack": {"kind": "form", "key": "k", "fields": fields, "formTitle": "Why"}
            },
        )
        payload = {
            "type": "block_actions",
            "trigger_id": "t1",
            "user": {"id": "U1"},
            "actions": [{"action_id": "heym_form_open", "value": "k"}],
        }
        with (
            patch("app.api.slack_bot.bot_credential", new=AsyncMock(return_value=config)),
            patch(
                "app.api.slack_bot.find_waiting_request", new=AsyncMock(return_value=request_row)
            ),
            patch.object(slack, "call_slack", return_value={"ok": True}) as call,
        ):
            await slack_interactions(
                "c", _signed_request(self._body(payload), "s"), BackgroundTasks(), AsyncMock()
            )

        method, body = call.call_args.args[1], call.call_args.args[2]
        self.assertEqual(method, "views.open")
        self.assertEqual(body["trigger_id"], "t1")
        self.assertEqual(body["view"]["blocks"][0]["block_id"], "reason")


class TestSlackTriggerEchoes(unittest.TestCase):
    def test_bot_posts_and_edits_are_echoes(self) -> None:
        from app.api.slack import _is_bot_echo

        self.assertTrue(_is_bot_echo({"event": {"type": "message", "bot_id": "B1"}}))
        self.assertTrue(_is_bot_echo({"event": {"type": "message", "subtype": "message_changed"}}))
        self.assertFalse(_is_bot_echo({"event": {"type": "message", "user": "U1", "text": "hi"}}))
        self.assertFalse(_is_bot_echo({"type": "event_callback"}))


class TestCredentialRules(unittest.TestCase):
    def test_bot_credential_merge_keeps_secrets_left_blank(self) -> None:
        from app.api.credentials import merge_credential_config_for_update
        from app.db.models import CredentialType

        merged = merge_credential_config_for_update(
            CredentialType.slack_bot,
            {"bot_token": "xoxb-old", "signing_secret": "old"},
            {"bot_token": "", "signing_secret": "new"},
        )
        self.assertEqual(merged, {"bot_token": "xoxb-old", "signing_secret": "new"})

    def test_slack_nodes_accept_the_bot_credential(self) -> None:
        from app.db.models import CredentialType
        from app.services.credential_catalog import NODE_CREDENTIAL_FIELDS

        self.assertIn(CredentialType.slack_bot, NODE_CREDENTIAL_FIELDS["slack"][0].types)
        self.assertIn(CredentialType.slack_bot, NODE_CREDENTIAL_FIELDS["slackTrigger"][0].types)


if __name__ == "__main__":
    unittest.main()
