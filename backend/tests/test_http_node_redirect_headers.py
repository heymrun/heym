"""curl -L in the HTTP node: command headers stay with their origin, cookies with theirs.

httpx forwards every custom header to another origin except Authorization, so once `-sL`
followed redirects an API key in `-H` or a header credential reached the redirect target. It
also drops the Cookie header on every hop. The node follows each hop itself: another origin
gets only Accept, Content-Type and User-Agent from the command; the command's origin (also
after an http to https upgrade, and on the way back from another origin) gets every command
header, the cookies the server set in the run and the `-b` cookie; `--location-trusted`
sends the command headers everywhere, as curl does.
"""

import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import httpx

from app.services.http_run_cookies import add_run_cookies, keep_run_cookies, refusing_cookie_jar
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor

OPTIONS = (
    "-H 'X-Api-Key: k1' -H 'Accept: application/json' "
    '-b session=abc -u user:pw -H "$credentials.MyKey"'
)
SECRET_HEADERS = ("x-api-key", "cookie", "authorization", "x-token")

Route = Callable[[httpx.Request], httpx.Response]


def _redirect(location: str, status: int = 302, **headers: str) -> Route:
    return lambda request: httpx.Response(
        status, headers={"Location": location, **headers}, request=request
    )


def _run(command: str, routes: list[Route]) -> list[httpx.Request]:
    """Run an http node; the n-th request is answered by routes[n], then 200."""
    received: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        index = len(received)
        received.append(request)
        if index < len(routes):
            return routes[index](request)
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
        node_data={"curl": command},
        node_label="request",
    )
    # As the guarded client: no shared cookie store, the run's jar through the hooks.
    client = httpx.Client(
        transport=httpx.MockTransport(handle),
        cookies=refusing_cookie_jar(),
        event_hooks={"request": [add_run_cookies], "response": [keep_run_cookies]},
    )
    with client:
        with (
            patch("app.services.ssrf_guard.guard_http_url"),
            patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
        ):
            output = http_node.execute(context)
    assert output["status"] == 200
    return received


class RedirectHeaderTests(unittest.TestCase):
    def test_the_first_request_carries_every_command_header(self) -> None:
        first = _run(f"curl -sL https://api.example.com/start {OPTIONS}", [_redirect("/next")])[0]

        for name in SECRET_HEADERS:
            self.assertIn(name, first.headers)

    def test_another_origin_receives_none_of_the_command_headers(self) -> None:
        for location in (
            "https://other.example.net/land",  # another host
            "http://api.example.com/land",  # https to http on the same host
            "https://api.example.com:8443/land",  # another port
        ):
            with self.subTest(location=location):
                second = _run(
                    f"curl -sL https://api.example.com/start {OPTIONS}", [_redirect(location)]
                )[1]

                self.assertEqual(str(second.url), location)
                for name in SECRET_HEADERS:
                    self.assertNotIn(name, second.headers)
                self.assertEqual(second.headers["accept"], "application/json")

    def test_the_same_origin_keeps_the_cookie_and_the_headers(self) -> None:
        second = _run(f"curl -sL https://api.example.com/start {OPTIONS}", [_redirect("/home")])[1]

        self.assertEqual(str(second.url), "https://api.example.com/home")
        self.assertEqual(second.headers["cookie"], "session=abc")
        self.assertEqual(second.headers["x-api-key"], "k1")
        self.assertEqual(second.headers["x-token"], "secret-token")

    def test_an_http_to_https_upgrade_on_the_same_host_keeps_the_headers(self) -> None:
        second = _run(
            f"curl -sL http://api.example.com/start {OPTIONS}",
            [_redirect("https://api.example.com/start")],
        )[1]

        for name in SECRET_HEADERS:
            self.assertIn(name, second.headers)

    def test_a_login_redirect_sends_the_server_cookie_and_the_command_cookie(self) -> None:
        second = _run(
            "curl -sL https://app.example.com/login -b theme=dark",
            [_redirect("/home", **{"Set-Cookie": "sid=s3cr3t; Path=/"})],
        )[1]

        cookies = {part.strip() for part in second.headers["cookie"].split(";")}
        self.assertEqual(cookies, {"sid=s3cr3t", "theme=dark"})

    def test_coming_back_to_the_first_origin_restores_the_headers(self) -> None:
        received = _run(
            f"curl -sL https://api.example.com/start {OPTIONS}",
            [
                _redirect("https://sso.example.net/check"),
                _redirect("https://api.example.com/done"),
            ],
        )

        for name in SECRET_HEADERS:
            self.assertNotIn(name, received[1].headers)
            self.assertIn(name, received[2].headers)

    def test_location_trusted_sends_the_headers_to_another_origin(self) -> None:
        second = _run(
            f"curl --location-trusted https://api.example.com/start {OPTIONS}",
            [_redirect("https://other.example.net/land")],
        )[1]

        for name in SECRET_HEADERS:
            self.assertIn(name, second.headers)
        self.assertEqual(second.headers["x-api-key"], "k1")

    def test_a_307_keeps_the_method_and_body_on_another_origin(self) -> None:
        second = _run(
            "curl -sL https://api.example.com/upload -d 'a=1'",
            [_redirect("https://other.example.net/upload", status=307)],
        )[1]

        self.assertEqual(second.method, "POST")
        self.assertEqual(second.content, b"a=1")


class HttpNodePageTests(unittest.TestCase):
    def test_the_page_explains_trusted_redirects_and_307_308(self) -> None:
        page = (
            Path(__file__).resolve().parents[2] / "frontend/src/docs/content/nodes/http-node.md"
        ).read_text(encoding="utf-8")

        self.assertIn("`--location-trusted`", page)
        self.assertIn("A 307 or 308 redirect sends the same method and body", page)


if __name__ == "__main__":
    unittest.main()
