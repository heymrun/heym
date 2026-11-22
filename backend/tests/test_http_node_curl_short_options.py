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


if __name__ == "__main__":
    unittest.main()
