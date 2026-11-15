"""Regression tests for HTTP-node JSON request-body templates."""

import json
import unittest
from unittest.mock import patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor


class HttpNodeRequestBodyTests(unittest.TestCase):
    """Ensure JSON body expressions are serialized safely."""

    def test_bare_string_expression_is_json_serialized(self) -> None:
        """A bare body expression can safely contain quotes, newlines, and UTF-8."""
        payload = {
            "channel": "C043U7YRLRJ",
            "thread_ts": "1787922196.184389",
            "text": 'Türkçe "MCP timeout" açıklaması\nİkinci satır',
        }
        curl = (
            "curl -X POST https://slack.com/api/chat.postMessage "
            "-H 'Content-Type: application/json; charset=utf-8' "
            '-d \'{"channel":"$source.channel","thread_ts":"$source.thread_ts",'
            '"text":$source.text}\''
        )
        received_requests: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            received_requests.append(request)
            return httpx.Response(200, json={"ok": True}, request=request)

        context = NodeExecutionContext(
            executor=WorkflowExecutor(nodes=[], edges=[]),
            node_id="http1",
            inputs={"source": payload},
            allow_branch_skip=True,
            start_time=0.0,
            node={},
            node_type="http",
            node_data={"curl": curl},
            node_label="Slack message",
        )
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            with (
                patch("app.services.ssrf_guard.guard_http_url"),
                patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
            ):
                http_node.execute(context)

        self.assertEqual(len(received_requests), 1)
        request = received_requests[0]
        self.assertEqual(json.loads(request.content.decode("utf-8")), payload)
        self.assertEqual(request.headers["content-length"], str(len(request.content)))


class HttpNodeJsonMediaTypeTests(unittest.TestCase):
    """Every JSON media type gets the JSON-safe body, not only application/json."""

    TITLE = 'Fix "login" bug\nseen on Safari'

    def _sent_body(self, content_type: str) -> bytes:
        curl = (
            "curl -X POST https://api.example.com/issues "
            f"-H 'Content-Type: {content_type}' "
            '-d \'{"data": {"type": "issues", "attributes": {"title": "$source.title"}}}\''
        )
        received: list[httpx.Request] = []

        def handle_request(request: httpx.Request) -> httpx.Response:
            received.append(request)
            return httpx.Response(201, json={"data": {"id": "1"}}, request=request)

        context = NodeExecutionContext(
            executor=WorkflowExecutor(nodes=[], edges=[]),
            node_id="http1",
            inputs={"source": {"title": self.TITLE}},
            allow_branch_skip=True,
            start_time=0.0,
            node={},
            node_type="http",
            node_data={"curl": curl},
            node_label="Create issue",
        )
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            with (
                patch("app.services.ssrf_guard.guard_http_url"),
                patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
            ):
                http_node.execute(context)
        return received[0].content

    def test_json_suffix_media_types_keep_the_body_valid(self) -> None:
        for content_type in (
            "application/vnd.api+json",
            "application/merge-patch+json; charset=utf-8",
            "application/problem+json",
        ):
            with self.subTest(content_type=content_type):
                self.assertEqual(
                    json.loads(self._sent_body(content_type)),
                    {"data": {"type": "issues", "attributes": {"title": self.TITLE}}},
                )

    def test_a_non_json_body_is_still_plain_text(self) -> None:
        body = self._sent_body("text/plain").decode()
        self.assertIn(self.TITLE, body)
