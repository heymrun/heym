"""The shared HTTP client keeps no cookie between runs.

httpx stores every Set-Cookie on the client that received it, and the guarded client is
shared by every run in the process. A session cookie from one user's run was sent with
the next request any run made to the same site, and showed in that run's output. Cookies
now stay with the run that received them, its sub-workflows included.
"""

import unittest
import uuid
from unittest.mock import patch

import httpx

from app.services import ssrf_guard
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import http_node
from app.services.workflow_executor import WorkflowExecutor

_SITE = "https://api.example.com"


class _Site:
    """`/login` sets a session cookie, `/hop` sets one and redirects to `/me`."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/login":
            return httpx.Response(200, headers={"set-cookie": "session=alice; Path=/"}, json={})
        if request.url.path == "/hop":
            headers = {"location": f"{_SITE}/me", "set-cookie": "hop=1; Path=/"}
            return httpx.Response(302, headers=headers)
        return httpx.Response(200, json={"cookie": request.headers.get("cookie")})

    def last_cookie(self) -> str | None:
        return self.requests[-1].headers.get("cookie")


def _run(executor: WorkflowExecutor, curl: str) -> dict:
    context = NodeExecutionContext(
        executor=executor,
        node_id="http1",
        inputs={},
        allow_branch_skip=True,
        start_time=0.0,
        node={},
        node_type="http",
        node_data={"curl": curl},
        node_label="request",
    )
    return http_node.execute(context)


def _executor(
    nodes: list[dict] | None = None, edges: list[dict] | None = None, **kwargs: object
) -> WorkflowExecutor:
    return WorkflowExecutor(nodes=nodes or [], edges=edges or [], **kwargs)


class HttpCookiesPerRunTests(unittest.TestCase):
    def setUp(self) -> None:
        ssrf_guard.close_guarded_http_client()
        self.addCleanup(ssrf_guard.close_guarded_http_client)
        self.site = _Site()
        self.client = ssrf_guard.get_guarded_http_client()
        self.client._transport = httpx.MockTransport(self.site)
        guard = patch("app.services.ssrf_guard.guard_http_url")
        guard.start()
        self.addCleanup(guard.stop)

    def test_a_cookie_one_run_receives_is_not_sent_by_another_run(self) -> None:
        _run(_executor(), f"curl {_SITE}/login")

        output = _run(_executor(), f"curl {_SITE}/me")

        self.assertIsNone(self.site.last_cookie())
        self.assertNotIn("cookie", {name.lower() for name in output["request"]["headers"]})
        self.assertIsNone(output["body"]["cookie"])

    def test_a_request_outside_a_run_gets_no_stored_cookie(self) -> None:
        self.client.get(f"{_SITE}/login")
        self.client.get(f"{_SITE}/me")

        self.assertIsNone(self.site.last_cookie())
        self.assertEqual(len(self.client.cookies), 0)

    def test_a_run_sends_the_cookie_it_received_earlier(self) -> None:
        executor = _executor()
        _run(executor, f"curl {_SITE}/login")

        _run(executor, f"curl {_SITE}/me")

        self.assertEqual(self.site.last_cookie(), "session=alice")

    def test_a_redirect_hop_gets_the_cookie_the_previous_hop_set(self) -> None:
        output = _run(_executor(), f"curl -L {_SITE}/hop")

        self.assertEqual(self.site.last_cookie(), "hop=1")
        self.assertEqual(output["body"]["cookie"], "hop=1")

    def test_a_cookie_header_the_command_sets_wins(self) -> None:
        executor = _executor()
        _run(executor, f"curl {_SITE}/login")

        _run(executor, f"curl {_SITE}/me -H 'Cookie: mine=b'")

        self.assertEqual(self.site.last_cookie(), "mine=b")

    def _run_with_sub_workflow(self, parent_path: str, child_path: str, child_first: bool) -> None:
        """Run parent -> Execute node -> child, each with one HTTP call, in the given order."""
        child_id = str(uuid.uuid4())
        parent_id = uuid.uuid4()
        child_nodes = [
            {"id": "c1", "type": "textInput", "data": {"label": "subInput"}},
            {
                "id": "c2",
                "type": "http",
                "data": {"label": "childCall", "curl": f"curl {child_path}"},
            },
        ]
        child_edges = [{"id": "ce1", "source": "c1", "target": "c2"}]
        execute = {"id": "pe", "type": "execute"}
        execute["data"] = {"label": "callSub", "executeWorkflowId": child_id}
        http = {"id": "ph", "type": "http"}
        http["data"] = {"label": "parentCall", "curl": f"curl {parent_path}"}
        first, second = (execute, http) if child_first else (http, execute)
        parent_nodes = [
            {"id": "p1", "type": "textInput", "data": {"label": "parentInput"}},
            first,
            second,
        ]
        parent_edges = [
            {"id": "e1", "source": "p1", "target": first["id"]},
            {"id": "e2", "source": first["id"], "target": second["id"]},
        ]
        executor = _executor(
            parent_nodes,
            parent_edges,
            workflow_cache={child_id: {"nodes": child_nodes, "edges": child_edges, "name": "Sub"}},
            workflow_id=parent_id,
        )

        result = executor.execute(parent_id, {"body": {}})

        self.assertEqual(result.status, "success")
        self.assertEqual([request.url.path for request in self.site.requests], ["/login", "/me"])

    def test_a_sub_workflow_sends_the_cookie_its_parent_received(self) -> None:
        self._run_with_sub_workflow(f"{_SITE}/login", f"{_SITE}/me", child_first=False)

        self.assertEqual(self.site.last_cookie(), "session=alice")

    def test_the_parent_sends_the_cookie_its_sub_workflow_received(self) -> None:
        self._run_with_sub_workflow(f"{_SITE}/me", f"{_SITE}/login", child_first=True)

        self.assertEqual(self.site.last_cookie(), "session=alice")


if __name__ == "__main__":
    unittest.main()
