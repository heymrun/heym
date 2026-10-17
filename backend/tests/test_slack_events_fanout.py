"""One events URL per Slack credential: scopes, DMs, redeliveries and who may listen."""

import hashlib
import hmac
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.requests import Request

from app.api import slack as slack_api

SECRET = "signing-secret"
CREDENTIAL = str(uuid.uuid4())


def _request(body: dict, *, secret: str = SECRET, extra: dict | None = None) -> Request:
    raw = json.dumps(body).encode()
    stamp = str(int(time.time()))
    signature = (
        "v0="
        + hmac.new(
            secret.encode(), f"v0:{stamp}:{raw.decode()}".encode(), hashlib.sha256
        ).hexdigest()
    )
    headers = Headers(
        {
            "content-type": "application/json",
            "x-slack-request-timestamp": stamp,
            "x-slack-signature": signature,
            **(extra or {}),
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
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request(scope, receive)


def _event(event: dict, event_id: str | None = None) -> dict:
    return {"type": "event_callback", "event_id": event_id or uuid.uuid4().hex, "event": event}


DM = {"type": "message", "channel_type": "im", "channel": "D01", "user": "U1", "text": "hi"}
CHANNEL_MESSAGE = {
    "type": "message",
    "channel_type": "channel",
    "channel": "C01",
    "user": "U1",
    "text": "x",
}
MENTION = {"type": "app_mention", "channel": "C01", "user": "U1", "text": "<@B1> help"}


class EventScopeTests(unittest.TestCase):
    def _matches(self, scope: str, event: dict, **data: str) -> bool:
        return slack_api._event_matches({"slackEventScope": scope, **data}, {"event": event})

    def test_older_nodes_still_start_on_every_event(self) -> None:
        self.assertTrue(slack_api._event_matches({}, {"event": {"type": "reaction_added"}}))

    def test_direct_messages_only_start_on_dms(self) -> None:
        self.assertTrue(self._matches("directMessages", DM))
        self.assertFalse(self._matches("directMessages", CHANNEL_MESSAGE))

    def test_messages_skip_mentions_and_housekeeping(self) -> None:
        self.assertTrue(self._matches("messages", DM))
        self.assertTrue(self._matches("messages", CHANNEL_MESSAGE))
        self.assertFalse(self._matches("messages", MENTION))
        self.assertFalse(self._matches("messages", {**CHANNEL_MESSAGE, "subtype": "channel_join"}))
        self.assertTrue(self._matches("messages", {**CHANNEL_MESSAGE, "subtype": "file_share"}))

    def test_mentions_and_one_channel(self) -> None:
        self.assertTrue(self._matches("mentions", MENTION))
        self.assertFalse(self._matches("mentions", CHANNEL_MESSAGE))
        self.assertTrue(self._matches("channel", CHANNEL_MESSAGE, slackEventChannel="C01"))
        self.assertFalse(self._matches("channel", CHANNEL_MESSAGE, slackEventChannel="C02"))
        self.assertFalse(self._matches("channel", CHANNEL_MESSAGE))


class FirstDeliveryTests(unittest.TestCase):
    def test_a_redelivered_event_is_handled_once(self) -> None:
        event_id = uuid.uuid4().hex
        self.assertTrue(slack_api._first_delivery(event_id))
        self.assertFalse(slack_api._first_delivery(event_id))
        self.assertTrue(slack_api._first_delivery(None))


def _workflow(*nodes: dict, owner: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), owner_id=owner or uuid.uuid4(), nodes=list(nodes))


def _trigger(node_id: str, **data: object) -> dict:
    return {"id": node_id, "type": "slackTrigger", "data": {"credentialId": CREDENTIAL, **data}}


class ListeningTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_active_triggers_in_workflows_whose_owner_may_use_the_credential(
        self,
    ) -> None:
        allowed = _workflow(
            _trigger("a"), _trigger("off", active=False), {"id": "x", "type": "llm", "data": {}}
        )
        stranger = _workflow(_trigger("b"))
        result = MagicMock()
        result.scalars.return_value = [allowed, stranger]
        db = AsyncMock()
        db.execute.return_value = result

        async def access(_db: object, _cred: uuid.UUID, owner_id: uuid.UUID) -> object:
            return object() if owner_id == allowed.owner_id else None

        with patch.object(slack_api, "get_accessible_credential", side_effect=access):
            targets = await slack_api._listening_triggers(db, CREDENTIAL)

        self.assertEqual(
            [(workflow.id, node_id) for workflow, node_id, _ in targets], [(allowed.id, "a")]
        )


class EventsEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _patches(self, targets: list, *, bot: bool = True) -> tuple:
        return (
            patch.object(slack_api, "_get_signing_secret", AsyncMock(return_value=SECRET)),
            patch.object(slack_api, "_listening_triggers", AsyncMock(return_value=targets)),
            patch.object(slack_api, "_is_bot_credential", AsyncMock(return_value=bot)),
            patch.object(slack_api, "_execute_workflow_background", new=AsyncMock()),
        )

    async def test_url_verification_answers_the_challenge(self) -> None:
        response = await slack_api.slack_events(
            CREDENTIAL, _request({"type": "url_verification", "challenge": "c1"})
        )
        self.assertEqual(response, {"challenge": "c1"})

    async def test_a_wrong_signature_is_refused(self) -> None:
        secret, *_ = self._patches([])
        with secret:
            with self.assertRaises(HTTPException) as caught:
                await slack_api.slack_events(CREDENTIAL, _request(_event(DM), secret="wrong"))
        self.assertEqual(caught.exception.status_code, 403)

    async def test_a_dm_starts_only_the_workflows_listening_for_it(self) -> None:
        dms = _workflow(_trigger("dm", slackEventScope="directMessages"))
        support = _workflow(_trigger("support", slackEventScope="channel", slackEventChannel="C09"))
        everything = _workflow(_trigger("all"))
        targets = [
            (dms, "dm", dms.nodes[0]["data"]),
            (support, "support", support.nodes[0]["data"]),
            (everything, "all", everything.nodes[0]["data"]),
        ]
        secret, listening, bot, background = self._patches(targets)
        with secret, listening, bot, background as run:
            response = await slack_api.slack_events(CREDENTIAL, _request(_event(DM)))

        self.assertEqual(response, {"ok": True})
        self.assertEqual([call.args[1] for call in run.call_args_list], ["dm", "all"])

    async def test_the_bots_own_post_and_a_redelivery_start_nothing(self) -> None:
        workflow = _workflow(_trigger("all"))
        targets = [(workflow, "all", workflow.nodes[0]["data"])]
        event_id = uuid.uuid4().hex
        secret, listening, bot, background = self._patches(targets)
        with secret, listening, bot, background as run:
            await slack_api.slack_events(CREDENTIAL, _request(_event({**DM, "bot_id": "B1"})))
            await slack_api.slack_events(CREDENTIAL, _request(_event(DM, event_id)))
            await slack_api.slack_events(
                CREDENTIAL, _request(_event(DM, event_id), extra={"x-slack-retry-num": "1"})
            )

        self.assertEqual(run.call_count, 1)

    async def test_a_credential_without_a_signing_secret_accepts_nothing(self) -> None:
        with patch.object(slack_api, "_get_signing_secret", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as caught:
                await slack_api.slack_events(CREDENTIAL, _request(_event(DM)))
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
