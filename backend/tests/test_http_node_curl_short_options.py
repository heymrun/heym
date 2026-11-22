"""cURL short options written the way curl also reads them: `-XDELETE`, `-fsSL`.

curl takes `-XDELETE` as `-X DELETE` and `-fsSL` as `-f -s -S -L`. API docs and install
scripts use both forms, and the HTTP node read neither: `-XDELETE` sent a GET and `-sL`
returned the redirect instead of following it.
"""

import unittest
from unittest.mock import patch

import httpx

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor


def _run_curl(curl: str) -> tuple[dict, list[httpx.Request]]:
    """Run an http node against a mock server; `/old` redirects to `/new`."""
    received: list[httpx.Request] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        received.append(request)
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"}, request=request)
        return httpx.Response(200, text=f"{request.method} {request.url.path}", request=request)

    context = NodeExecutionContext(
        executor=WorkflowExecutor(nodes=[], edges=[]),
        node_id="http1",
        inputs={},
        allow_branch_skip=True,
        start_time=0.0,
        node={},
        node_type="http",
        node_data={"curl": curl},
        node_label="request",
    )
    with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
        with (
            patch("app.services.ssrf_guard.guard_http_url"),
            patch("app.services.ssrf_guard.get_guarded_http_client", return_value=client),
        ):
            output = http_node.execute(context)
    return output, received


class HttpNodeCurlAttachedMethodTests(unittest.TestCase):
    def test_a_method_attached_to_x_is_sent(self) -> None:
        for curl, method in (
            ("curl -XDELETE https://search.example.com/my-index", "DELETE"),
            ("curl -XPUT https://search.example.com/my-index -d '{}'", "PUT"),
            ("curl -Xpatch https://search.example.com/my-index -d '{}'", "PATCH"),
        ):
            with self.subTest(curl=curl):
                _output, received = _run_curl(curl)

                self.assertEqual(received[0].method, method)
                self.assertEqual(str(received[0].url), "https://search.example.com/my-index")

    def test_a_separate_method_still_works(self) -> None:
        _output, received = _run_curl("curl -X DELETE https://search.example.com/my-index")

        self.assertEqual(received[0].method, "DELETE")


class HttpNodeCurlCombinedFlagsTests(unittest.TestCase):
    def test_combined_flags_with_l_follow_the_redirect(self) -> None:
        for flags in ("-sL", "-Ls", "-fsSL"):
            with self.subTest(flags=flags):
                output, _received = _run_curl(f"curl {flags} https://downloads.example.com/old")

                self.assertEqual(output["status"], 200)
                self.assertEqual(output["body"], "GET /new")

    def test_combined_flags_without_l_return_the_redirect(self) -> None:
        output, _received = _run_curl("curl -fsS https://downloads.example.com/old")

        self.assertEqual(output["status"], 301)

    def test_combined_flags_with_g_send_the_data_as_the_query(self) -> None:
        _output, received = _run_curl("curl -sG https://api.example.com/search -d q=heym")

        self.assertEqual(received[0].method, "GET")
        self.assertEqual(str(received[0].url), "https://api.example.com/search?q=heym")


class HttpNodeCurlValueClusterTests(unittest.TestCase):
    """A letter that takes a value uses the rest of the token or the next token, as in curl."""

    def test_a_method_inside_a_cluster_is_sent(self) -> None:
        for curl, method in (
            ("curl -sXPOST https://api.example.com/items", "POST"),
            ("curl -LX POST https://api.example.com/items", "POST"),
            ("curl -sXPUT https://api.example.com/items -d '{}'", "PUT"),
        ):
            with self.subTest(curl=curl):
                _output, received = _run_curl(curl)

                self.assertEqual(received[0].method, method)

    def test_header_data_and_user_inside_a_cluster_are_read(self) -> None:
        _output, received = _run_curl(
            "curl -sH 'X-Api-Key: k1' https://api.example.com/items -sd a=1 -su user:pw"
        )

        self.assertEqual(received[0].method, "POST")
        self.assertEqual(received[0].headers["x-api-key"], "k1")
        self.assertEqual(received[0].content, b"a=1")
        self.assertTrue(received[0].headers["authorization"].startswith("Basic "))

    def test_a_value_that_starts_with_a_dash_is_not_split(self) -> None:
        _output, received = _run_curl("curl https://api.example.com/items -d -5")

        self.assertEqual(received[0].content, b"-5")

    def test_eight_is_not_a_curl_option(self) -> None:
        from app.services.node_execution.curl_parser import _split_short_options

        self.assertIsNone(_split_short_options("-s8"))


if __name__ == "__main__":
    unittest.main()
