"""GHSA-6x65-w7q7-wg93 finding 1: webhook header_auth secret exposure."""

import datetime
import hmac
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api import workflows as workflows_module
from app.api.workflows import (
    _build_workflow_response,
    _build_workflow_version_response,
    _sanitize_headers,
    _webhook_secret_names,
    get_workflow,
    update_workflow,
    validate_workflow_auth,
)
from app.config import settings
from app.models.schemas import WorkflowUpdate


def _workflow(*, owner_id: uuid.UUID, header_key: str | None, header_value: str | None):
    now = datetime.datetime.now(datetime.timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="wf",
        description=None,
        kind="workflow",
        nodes=[],
        edges=[],
        auth_type="header_auth",
        auth_header_key=header_key,
        auth_header_value=header_value,
        webhook_body_mode="legacy",
        allow_anonymous=False,
        owner_id=owner_id,
        folder_id=None,
        cache_ttl_seconds=None,
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        sse_enabled=False,
        sse_node_config=None,
        auto_recover_runs=True,
        error_workflow_id=None,
        minutes_saved_per_run=None,
        workflow_timeout_seconds=None,
        created_at=now,
        updated_at=now,
    )


class PersistedHeaderDenylistTests(unittest.TestCase):
    """The fixed denylist cannot know a workflow's own auth header name."""

    def test_configured_auth_header_is_stripped(self) -> None:
        workflow = _workflow(
            owner_id=uuid.uuid4(), header_key="X-Webhook-Secret", header_value="s3cr3t"
        )

        result = _sanitize_headers(
            {"X-Webhook-Secret": "s3cr3t", "Content-Type": "application/json"},
            _webhook_secret_names(workflow),
        )

        self.assertNotIn("x-webhook-secret", result)
        self.assertIn("content-type", result)

    def test_match_is_case_insensitive(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Webhook-Secret", header_value="s")

        result = _sanitize_headers({"x-WEBHOOK-secret": "s"}, _webhook_secret_names(workflow))

        self.assertEqual(result, {})

    def test_fixed_denylist_still_applies(self) -> None:
        result = _sanitize_headers({"Authorization": "Bearer x", "Accept": "*/*"})

        self.assertNotIn("authorization", result)
        self.assertIn("accept", result)

    def test_workflow_without_header_auth_adds_no_names(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key=None, header_value=None)

        self.assertEqual(_webhook_secret_names(workflow), ())

    def test_unrelated_query_style_headers_are_preserved(self) -> None:
        """Only the configured name is stripped; generic names stay usable."""
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Webhook-Secret", header_value="s")

        result = _sanitize_headers(
            {"X-Request-Id": "abc", "X-Token-Hint": "keep"}, _webhook_secret_names(workflow)
        )

        self.assertEqual(result, {"x-request-id": "abc", "x-token-hint": "keep"})


class WorkflowResponseMaskingTests(unittest.TestCase):
    def test_owner_still_reads_the_secret(self) -> None:
        owner_id = uuid.uuid4()
        workflow = _workflow(owner_id=owner_id, header_key="X-Key", header_value="s3cr3t")

        response = _build_workflow_response(workflow, owner_id)

        self.assertEqual(response.auth_header_value, "s3cr3t")
        self.assertTrue(response.auth_header_value_set)

    def test_collaborator_gets_null(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")

        response = _build_workflow_response(workflow, uuid.uuid4())

        self.assertIsNone(response.auth_header_value)
        # Still told a secret exists so the editor can render it read-only.
        self.assertTrue(response.auth_header_value_set)

    def test_unset_secret_reports_not_set(self) -> None:
        owner_id = uuid.uuid4()
        workflow = _workflow(owner_id=owner_id, header_key=None, header_value=None)

        self.assertFalse(_build_workflow_response(workflow, owner_id).auth_header_value_set)


class AdminWorkflowSecretTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_write_access_still_masks_owner_secret(self) -> None:
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")
        db = AsyncMock()
        db.execute.side_effect = [
            MagicMock(scalar_one_or_none=lambda: workflow),
            MagicMock(scalar=lambda: True),
            MagicMock(scalar_one_or_none=lambda: None),
            MagicMock(scalar_one_or_none=lambda: "Owner"),
        ]
        with patch.object(settings, "admin_emails", admin.email):
            response = await get_workflow(workflow.id, admin, db)
        self.assertEqual(response.permission, "write")
        self.assertIsNone(response.auth_header_value)
        self.assertTrue(response.auth_header_value_set)

    async def test_admin_cannot_overwrite_owner_authentication(self) -> None:
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")
        db = AsyncMock()
        db.execute.side_effect = [
            MagicMock(scalar_one_or_none=lambda: workflow),
            MagicMock(scalar=lambda: True),
        ]
        with patch.object(settings, "admin_emails", admin.email):
            with self.assertRaises(HTTPException) as raised:
                await update_workflow(workflow.id, WorkflowUpdate(auth_type="anonymous"), admin, db)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(workflow.auth_type, "header_auth")
        self.assertEqual(workflow.auth_header_value, "s3cr3t")
        db.commit.assert_not_awaited()


class WorkflowVersionMaskingTests(unittest.TestCase):
    def _version(self):
        return SimpleNamespace(
            id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            version_number=3,
            name="wf",
            description=None,
            nodes=[],
            edges=[],
            auth_type="header_auth",
            auth_header_key="X-Key",
            auth_header_value="s3cr3t",
            webhook_body_mode="legacy",
            cache_ttl_seconds=None,
            rate_limit_requests=None,
            rate_limit_window_seconds=None,
            created_by_id=uuid.uuid4(),
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )

    def test_version_masks_for_collaborator(self) -> None:
        masked = _build_workflow_version_response(self._version(), is_owner=False)

        self.assertIsNone(masked.auth_header_value)
        self.assertTrue(masked.auth_header_value_set)

    def test_version_visible_to_owner(self) -> None:
        visible = _build_workflow_version_response(self._version(), is_owner=True)

        self.assertEqual(visible.auth_header_value, "s3cr3t")


class HeaderAuthComparisonTests(unittest.IsolatedAsyncioTestCase):
    """The inbound header secret is compared in constant time (CWE-208)."""

    async def test_a_matching_header_authenticates(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")
        request = SimpleNamespace(headers={"X-Key": "s3cr3t"})

        result = await validate_workflow_auth(workflow, request, None, AsyncMock())

        self.assertIsNone(result)

    async def test_a_wrong_header_is_rejected(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")
        request = SimpleNamespace(headers={"X-Key": "s3cr3"})

        with self.assertRaises(HTTPException) as raised:
            await validate_workflow_auth(workflow, request, None, AsyncMock())

        self.assertEqual(raised.exception.status_code, 401)

    async def test_a_missing_header_is_rejected(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")
        request = SimpleNamespace(headers={})

        with self.assertRaises(HTTPException) as raised:
            await validate_workflow_auth(workflow, request, None, AsyncMock())

        self.assertEqual(raised.exception.status_code, 401)

    async def test_the_comparison_is_constant_time(self) -> None:
        workflow = _workflow(owner_id=uuid.uuid4(), header_key="X-Key", header_value="s3cr3t")
        request = SimpleNamespace(headers={"X-Key": "s3cr3t"})

        with patch.object(workflows_module, "hmac", MagicMock(wraps=hmac)) as spy:
            await validate_workflow_auth(workflow, request, None, AsyncMock())

        spy.compare_digest.assert_called_once()
        (first, second), _ = spy.compare_digest.call_args
        self.assertEqual((first, second), (b"s3cr3t", b"s3cr3t"))


if __name__ == "__main__":
    unittest.main()
