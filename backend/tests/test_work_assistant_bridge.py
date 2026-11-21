"""The bridge to Heym Work's assistant tools: manifest limits, caching, relaying, no redirects."""

import json
import unittest
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services import work_assistant
from app.services.auth import decode_token
from app.services.work_assistant import (
    ASSISTANT_TOKEN_HEADER,
    DID_NOT_ANSWER,
    MAX_RESULT_CHARS,
    ManifestState,
    WorkLink,
    WorkTool,
    call_tool,
    cap_result,
    load_work_link,
    manifest_for,
    parse_manifest,
)

_LINK = WorkLink(work_url="https://work.example.com", key_hash="b" * 64)


def _user(active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), is_active=active)


def _tool(name: str = "get_world", **overrides: Any) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "name": name,
        "description": "Read the world.",
        "parameters": {"type": "object", "properties": {}},
    }
    tool.update(overrides)
    return tool


def _manifest(*tools: dict[str, Any], instructions: str = "Use the tools.") -> dict[str, Any]:
    return {"version": 1, "instructions": instructions, "tools": list(tools)}


class _Recorder:
    """An httpx transport that answers with `handler` and keeps every request."""

    def __init__(self, handler: Any) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._handler(request)

        return httpx.MockTransport(handle)


class ParseManifestTests(unittest.TestCase):
    def test_valid_manifest(self) -> None:
        manifest = parse_manifest(_manifest(_tool(), _tool("list_flows", long_running=True)))
        assert manifest is not None
        self.assertEqual([tool.name for tool in manifest.tools], ["get_world", "list_flows"])
        self.assertTrue(manifest.tools[1].long_running)
        self.assertEqual(manifest.instructions, "Use the tools.")

    def test_requires_version_one_and_a_tool_list(self) -> None:
        self.assertIsNone(parse_manifest({"version": 2, "tools": []}))
        self.assertIsNone(parse_manifest({"version": 1, "tools": "x"}))
        self.assertIsNone(parse_manifest([]))

    def test_drops_tools_that_break_a_limit(self) -> None:
        manifest = parse_manifest(
            _manifest(
                _tool("Bad-Name"),
                _tool("a/b"),
                _tool("../x"),
                _tool("ab"),
                _tool("x" * 42),
                _tool("empty_description", description="  "),
                _tool("long_description", description="d" * 1001),
                _tool("array_schema", parameters={"type": "array"}),
                _tool(
                    "huge_schema",
                    parameters={"type": "object", "description": "s" * 9000},
                ),
                _tool("odd_flag", long_running="yes"),
                _tool("get_world"),
                _tool("get_world", description="A duplicate."),
            )
        )
        assert manifest is not None
        self.assertEqual([tool.name for tool in manifest.tools], ["get_world"])
        self.assertEqual(manifest.tools[0].description, "Read the world.")

    def test_keeps_at_most_sixteen_tools(self) -> None:
        manifest = parse_manifest(_manifest(*[_tool(f"tool_{index}") for index in range(20)]))
        assert manifest is not None
        self.assertEqual(len(manifest.tools), 16)

    def test_oversized_instructions_are_dropped(self) -> None:
        manifest = parse_manifest(_manifest(_tool(), instructions="i" * 4001))
        assert manifest is not None
        self.assertEqual(manifest.instructions, "")


class LoadLinkTests(unittest.IsolatedAsyncioTestCase):
    def _db(self, row: object) -> AsyncMock:
        result = MagicMock()
        result.one_or_none.return_value = row
        db = AsyncMock()
        db.execute.return_value = result
        return db

    async def test_enabled_complete_integration(self) -> None:
        row = SimpleNamespace(enabled=True, work_url="https://w.example", key_hash="c" * 64)
        link = await load_work_link(self._db(row))
        self.assertEqual(link, WorkLink("https://w.example", "c" * 64))

    async def test_disabled_or_incomplete_integration(self) -> None:
        for row in (
            None,
            SimpleNamespace(enabled=False, work_url="https://w.example", key_hash="c" * 64),
            SimpleNamespace(enabled=True, work_url="", key_hash="c" * 64),
            SimpleNamespace(enabled=True, work_url="https://w.example", key_hash=None),
        ):
            self.assertIsNone(await load_work_link(self._db(row)))


class ManifestForTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        work_assistant.clear_manifest_cache()

    async def _fetch(self, recorder: _Recorder, user: Any | None = None) -> ManifestState:
        with patch.object(work_assistant, "_TRANSPORT", recorder.transport()):
            return await manifest_for(_LINK, user or _user())

    async def test_fetches_with_the_token_header(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, json=_manifest(_tool())))
        user = _user()
        state = await self._fetch(recorder, user)

        assert state.manifest is not None
        self.assertFalse(state.unreachable)
        request = recorder.requests[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(str(request.url), "https://work.example.com/api/assistant/tools")
        self.assertTrue(request.headers["user-agent"].startswith("Heym"))
        claims = decode_token(request.headers[ASSISTANT_TOKEN_HEADER])
        self.assertEqual(claims["sub"], str(user.id))
        self.assertEqual(claims["cli"], "work")

    async def test_refusals_mean_no_tools_and_no_note(self) -> None:
        for status in (401, 403, 404):
            work_assistant.clear_manifest_cache()
            state = await self._fetch(_Recorder(lambda _r, s=status: httpx.Response(s)))
            self.assertEqual(state, ManifestState(None, unreachable=False))

    async def test_failures_mean_unreachable(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("slow", request=request)

        handlers = [
            timeout,
            lambda _r: httpx.Response(502),
            lambda _r: httpx.Response(302, headers={"location": "https://evil.example/"}),
            lambda _r: httpx.Response(200, content=b"not json"),
            lambda _r: httpx.Response(200, json={"version": 9}),
        ]
        for handler in handlers:
            work_assistant.clear_manifest_cache()
            recorder = _Recorder(handler)
            state = await self._fetch(recorder)
            self.assertEqual(state, ManifestState(None, unreachable=True))
            self.assertEqual(len(recorder.requests), 1, "a redirect must not be followed")

    async def test_cached_for_the_same_user(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, json=_manifest(_tool())))
        user = _user()
        await self._fetch(recorder, user)
        await self._fetch(recorder, user)
        self.assertEqual(len(recorder.requests), 1)
        await self._fetch(recorder, _user())
        self.assertEqual(len(recorder.requests), 2)

    async def test_cache_expires(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, json=_manifest(_tool())))
        user = _user()
        with patch.object(work_assistant.time, "monotonic", return_value=1000.0):
            await self._fetch(recorder, user)
        with patch.object(work_assistant.time, "monotonic", return_value=1061.0):
            await self._fetch(recorder, user)
        self.assertEqual(len(recorder.requests), 2)

    async def test_inactive_user_sends_nothing(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, json=_manifest(_tool())))
        state = await self._fetch(recorder, _user(active=False))
        self.assertEqual(state, ManifestState(None, unreachable=False))
        self.assertEqual(recorder.requests, [])


class CallToolTests(unittest.IsolatedAsyncioTestCase):
    async def _call(
        self, recorder: _Recorder, tool: WorkTool, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with patch.object(work_assistant, "_TRANSPORT", recorder.transport()):
            return await call_tool(_LINK, _user(), tool, args or {})

    async def test_posts_arguments_to_the_tool_path(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, json={"total": 3}))
        result = await self._call(recorder, WorkTool("list_flows", "d", {}), {"limit": 5})

        self.assertEqual(result, {"total": 3})
        request = recorder.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            str(request.url), "https://work.example.com/api/assistant/tools/list_flows"
        )
        self.assertEqual(json.loads(request.content), {"limit": 5})

    async def test_long_running_tool_gets_the_long_token(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, json={}))
        await self._call(recorder, WorkTool("start_discover_search", "d", {}, long_running=True))
        await self._call(recorder, WorkTool("get_world", "d", {}))
        long_claims = decode_token(recorder.requests[0].headers[ASSISTANT_TOKEN_HEADER])
        short_claims = decode_token(recorder.requests[1].headers[ASSISTANT_TOKEN_HEADER])
        self.assertGreater(long_claims["exp"] - short_claims["exp"], 25 * 60)

    async def test_refusal_keeps_work_message_and_status(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(403, json={"detail": "Needs an Editor."}))
        result = await self._call(recorder, WorkTool("list_flows", "d", {}))
        self.assertEqual(result, {"error": "Needs an Editor.", "status": 403})

    async def test_redirect_is_not_followed(self) -> None:
        recorder = _Recorder(
            lambda _r: httpx.Response(307, headers={"location": "https://evil.example/x"})
        )
        result = await self._call(recorder, WorkTool("list_flows", "d", {}))
        self.assertEqual(len(recorder.requests), 1)
        self.assertEqual(result["status"], 307)
        self.assertIn("redirect", result["error"])

    async def test_timeout(self) -> None:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        result = await self._call(_Recorder(timeout), WorkTool("list_flows", "d", {}))
        self.assertEqual(result, {"error": DID_NOT_ANSWER})

    async def test_unreadable_answer(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, content=b"<html>"))
        result = await self._call(recorder, WorkTool("list_flows", "d", {}))
        self.assertIn("error", result)

    async def test_inactive_user_sends_nothing(self) -> None:
        recorder = _Recorder(lambda _r: httpx.Response(200, json={}))
        with patch.object(work_assistant, "_TRANSPORT", recorder.transport()):
            result = await call_tool(_LINK, _user(active=False), WorkTool("x_tool", "d", {}), {})
        self.assertIn("error", result)
        self.assertEqual(recorder.requests, [])


class CapResultTests(unittest.TestCase):
    def test_small_result_is_plain_json(self) -> None:
        self.assertEqual(json.loads(cap_result({"a": 1})), {"a": 1})

    def test_large_result_is_cut(self) -> None:
        capped = json.loads(cap_result({"text": "x" * (MAX_RESULT_CHARS + 10)}))
        self.assertTrue(capped["truncated"])
        self.assertEqual(len(capped["partial"]), MAX_RESULT_CHARS)


if __name__ == "__main__":
    unittest.main()
