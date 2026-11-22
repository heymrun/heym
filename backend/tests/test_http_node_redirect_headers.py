"""curl -L in the HTTP node: command headers stay with their origin, cookies with theirs.

httpx forwards every custom header to another origin except Authorization, so once `-sL`
followed redirects an API key in `-H` or a header credential reached the redirect target. It
also drops the Cookie header on every hop, so `-b session=...` lost its session even on the
same origin and could land on a 200 login page.
"""

import unittest
from unittest.mock import patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor

COMMAND = (
    "curl -sL {url} -H 'X-Api-Key: k1' -H 'Accept: application/json' "
    '-b session=abc -u user:pw -H "$credentials.MyKey"'
)


def _run(start: str, location: str) -> list[httpx.Request]:
    received: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        received.append(request)
        if len(received) == 1:
            return httpx.Response(302, headers={"Location": location}, request=request)
        return httpx.Response(200, text="landed", request=request)

    context = NodeExecutionContext(
        executor=WorkflowExecutor(
            nodes=[], edges=[], credentials_context={"MyKey": "X-Token: secret-token"}
        ),
        node_id="http1",
        inputs={},
        allow_branch_skip=True,
        start_time=0.0,
        node={},
        node_type="http",
        node_data={"curl": COMMAND.format(url=start)},
        node_label="request",
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with (
            patch("app.services.ssrf_guard.guard_http_url"),
            patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
        ):
            output = http_node.execute(context)
    assert output["status"] == 200
    return received


SECRET_HEADERS = ("x-api-key", "cookie", "authorization", "x-token")


class RedirectHeaderTests(unittest.TestCase):
    def test_the_first_request_carries_every_command_header(self) -> None:
        first = _run("https://api.example.com/start", "/next")[0]

        for name in SECRET_HEADERS:
            self.assertIn(name, first.headers)

    def test_another_origin_receives_none_of_the_command_headers(self) -> None:
        for location in (
            "https://other.example.net/land",  # another host
            "http://api.example.com/land",  # https to http on the same host
            "https://api.example.com:8443/land",  # another port
        ):
            with self.subTest(location=location):
                second = _run("https://api.example.com/start", location)[1]

                self.assertEqual(str(second.url), location)
                for name in SECRET_HEADERS:
                    self.assertNotIn(name, second.headers)
                self.assertEqual(second.headers["accept"], "application/json")

    def test_the_same_origin_keeps_the_cookie_and_the_headers(self) -> None:
        second = _run("https://api.example.com/start", "/dashboard")[1]

        self.assertEqual(str(second.url), "https://api.example.com/dashboard")
        self.assertEqual(second.headers["cookie"], "session=abc")
        self.assertEqual(second.headers["x-api-key"], "k1")
        self.assertEqual(second.headers["x-token"], "secret-token")


if __name__ == "__main__":
    unittest.main()
