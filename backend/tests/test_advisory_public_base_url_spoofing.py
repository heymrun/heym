"""GHSA-6rv3-wh25-7pg5: capability links must never be built from request headers.

`Origin` and `X-Forwarded-*` are client supplied. When they decided the public base URL, a
single request could mint a HITL review link (or a Codex follow-up link) on a host the
attacker controlled, and the workflow's own notification branch then delivered that link,
token included, to the human reviewer.
"""

import uuid
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

from app.services import codex_followup_service, hitl_service

CONFIGURED = "https://heym.example.com"
SPOOFED = "https://evil.tld"


def _configured_settings(frontend_url: str = CONFIGURED, cors: list[str] | None = None):
    return SimpleNamespace(frontend_url=frontend_url, cors_origins_list=cors or [])


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "server": ("backend", 10105),
            "path": "/api/portal/support/execute",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": ("203.0.113.7", 54321),
        }
    )


class TestPublicBaseUrlIgnoresRequestHeaders(TestCase):
    def test_origin_header_loses_to_configured_frontend_url(self) -> None:
        request = _request({"host": "heym.example.com", "origin": SPOOFED})
        with patch.object(hitl_service, "settings", _configured_settings()):
            self.assertEqual(hitl_service.build_public_base_url(request), CONFIGURED)

    def test_forwarded_host_loses_to_configured_frontend_url(self) -> None:
        request = _request(
            {
                "host": "heym.example.com",
                "x-forwarded-host": "evil.tld",
                "x-forwarded-proto": "https",
            }
        )
        with patch.object(hitl_service, "settings", _configured_settings()):
            self.assertEqual(hitl_service.build_public_base_url(request), CONFIGURED)

    def test_review_url_stays_on_the_configured_host(self) -> None:
        request = _request({"host": "heym.example.com", "origin": SPOOFED})
        with patch.object(hitl_service, "settings", _configured_settings()):
            base = hitl_service.build_public_base_url(request)
        review_url = hitl_service.build_review_url(base, "tok_abc")
        self.assertEqual(review_url, f"{CONFIGURED}/review/tok_abc")
        self.assertNotIn("evil.tld", review_url)

    def test_request_is_never_inspected(self) -> None:
        request = MagicMock()
        with patch.object(hitl_service, "settings", _configured_settings()):
            self.assertEqual(hitl_service.build_public_base_url(request), CONFIGURED)
        request.headers.get.assert_not_called()

    def test_cors_origin_fallback_is_preserved(self) -> None:
        request = _request({"host": "heym.example.com", "origin": SPOOFED})
        fallback = _configured_settings(frontend_url="", cors=["https://ops.example.com"])
        with patch.object(hitl_service, "settings", fallback):
            self.assertEqual(hitl_service.build_public_base_url(request), "https://ops.example.com")

    def test_codex_service_no_longer_defines_its_own_builder(self) -> None:
        self.assertFalse(hasattr(codex_followup_service, "build_public_base_url"))
        self.assertIs(
            codex_followup_service.build_default_public_base_url,
            hitl_service.build_default_public_base_url,
        )


def _poisoned_snapshot() -> dict:
    return {
        "credentials_owner_id": str(uuid.uuid4()),
        "trace_user_id": str(uuid.uuid4()),
        "public_base_url": SPOOFED,
        "trigger_source": "portal",
        "paused_node_id": "node-1",
        "paused_node_label": "Review",
    }


def _resolved_request() -> MagicMock:
    hitl_request = MagicMock()
    hitl_request.id = uuid.uuid4()
    hitl_request.status = "resolved"
    hitl_request.decision = "accept"
    hitl_request.workflow_id = uuid.uuid4()
    hitl_request.execution_history_id = uuid.uuid4()
    hitl_request.execution_snapshot = _poisoned_snapshot()
    hitl_request.original_agent_output = {}
    hitl_request.original_draft_text = "draft"
    hitl_request.summary = "summary"
    hitl_request.edited_text = None
    hitl_request.refusal_reason = None
    return hitl_request


def _session_for(hitl_request: MagicMock) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = hitl_request
    db = AsyncMock()
    db.execute.return_value = result
    db.get.side_effect = [MagicMock(), MagicMock()]  # workflow, history entry
    session = AsyncMock()
    session.__aenter__.return_value = db
    session.__aexit__.return_value = False
    return session


class TestResumeReDerivesBaseUrl(IsolatedAsyncioTestCase):
    """A row persisted before the fix still carries the attacker's host. Never read it back."""

    async def _resume(self, pending_review: dict) -> MagicMock:
        resumed = MagicMock()
        resumed.status = "pending"
        resumed.pending_review = pending_review

        persist_hitl = AsyncMock()
        persist_codex = AsyncMock()

        with (
            patch.object(hitl_service, "settings", _configured_settings()),
            patch.object(
                hitl_service, "async_session_maker", return_value=_session_for(_resolved_request())
            ),
            patch.object(hitl_service, "resume_workflow_execution", return_value=resumed),
            patch.object(hitl_service, "persist_pending_hitl_execution", persist_hitl),
            patch.object(
                codex_followup_service,
                "persist_pending_codex_followup_execution",
                persist_codex,
            ),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            await hitl_service.resume_hitl_request_in_background(uuid.uuid4())

        return persist_codex if pending_review.get("kind") == "codex" else persist_hitl

    async def test_next_hitl_checkpoint_uses_configured_host(self) -> None:
        persist = await self._resume({})
        persist.assert_awaited_once()
        self.assertEqual(persist.await_args.kwargs["public_base_url"], CONFIGURED)

    async def test_next_codex_checkpoint_uses_configured_host(self) -> None:
        persist = await self._resume({"kind": "codex"})
        persist.assert_awaited_once()
        self.assertEqual(persist.await_args.kwargs["public_base_url"], CONFIGURED)


class TestCodexResumeReDerivesBaseUrl(IsolatedAsyncioTestCase):
    async def test_next_codex_checkpoint_uses_configured_host(self) -> None:
        followup = MagicMock()
        followup.id = uuid.uuid4()
        followup.status = "answered"
        followup.answer_text = "answer"
        followup.workflow_id = uuid.uuid4()
        followup.execution_history_id = uuid.uuid4()
        followup.execution_snapshot = _poisoned_snapshot()

        resumed = MagicMock()
        resumed.status = "pending"
        resumed.pending_review = {"kind": "codex"}
        persist = AsyncMock()

        with (
            patch.object(hitl_service, "settings", _configured_settings()),
            patch.object(
                codex_followup_service, "async_session_maker", return_value=_session_for(followup)
            ),
            patch.object(codex_followup_service, "resume_workflow_execution", return_value=resumed),
            patch.object(
                codex_followup_service, "persist_pending_codex_followup_execution", persist
            ),
            patch("app.api.workflows.get_credentials_context", AsyncMock(return_value={})),
            patch(
                "app.services.global_variables_service.get_global_variables_context",
                AsyncMock(return_value={}),
            ),
        ):
            await codex_followup_service.resume_codex_followup_in_background(uuid.uuid4())

        persist.assert_awaited_once()
        self.assertEqual(persist.await_args.kwargs["public_base_url"], CONFIGURED)
