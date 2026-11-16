"""What a workflow's execute endpoint reads from a request body, per content type."""

from __future__ import annotations

import json
import unittest
from urllib.parse import urlencode

from starlette.requests import Request

from app.api.workflows import parse_execute_body


def _request(body: bytes, content_type: str) -> Request:
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/workflows/x/execute",
        "query_string": b"",
        "headers": [(b"content-type", content_type.encode())],
    }
    return Request(scope, receive)


class ExecuteBodyFormatTests(unittest.IsolatedAsyncioTestCase):
    FORM = "application/x-www-form-urlencoded"

    async def _body(self, body: bytes, content_type: str) -> object:
        raw_body, _test_run, _source, _simple = await parse_execute_body(
            _request(body, content_type)
        )
        return raw_body

    async def test_a_form_webhook_reaches_the_workflow_as_fields(self) -> None:
        # What Twilio posts for an incoming SMS.
        sms = {
            "From": "+15551234567",
            "Body": "Is order #42 shipped? Müller & Söhne",
            "NumMedia": "0",
        }

        self.assertEqual(
            await self._body(urlencode(sms).encode(), f"{self.FORM}; charset=utf-8"), sms
        )

    async def test_a_repeated_form_field_is_a_list(self) -> None:
        body = b"tag=urgent&tag=billing&empty="
        self.assertEqual(
            await self._body(body, self.FORM), {"tag": ["urgent", "billing"], "empty": ""}
        )

    async def test_json_sent_with_curls_default_form_content_type_stays_json(self) -> None:
        body = json.dumps({"inputs": {"text": "hi"}}).encode()
        self.assertEqual(await self._body(body, self.FORM), {"text": "hi"})

    async def test_other_bodies_that_are_not_json_stay_empty(self) -> None:
        self.assertEqual(await self._body(b"<xml/>", "application/xml"), {})
        self.assertEqual(await self._body(b"a=1", "text/plain"), {})
