"""The status URL authenticates like the webhook; anonymous runs need their run token.

A stored digest must never authenticate, and the token is read from a header only.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request

from app.db.models import WorkflowAuthType
from app.services.secret_tokens import hash_secret


def _request(headers: dict[str, str] | None = None, query: bytes = b"") -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "query_string": query,
        },
        receive,
    )


class StatusEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _call(
        self,
        *,
        auth_type: WorkflowAuthType,
        headers: dict[str, str] | None = None,
        query: bytes = b"",
        stored_hash: str | None = None,
        validate: AsyncMock | None = None,
    ) -> object:
        from app.api.workflows import get_workflow_execution_status

        workflow = SimpleNamespace(id=uuid.uuid4(), auth_type=auth_type)
        db = AsyncMock()
        db.get = AsyncMock(return_value=workflow)
        body = {
            "execution_id": "e",
            "workflow_id": str(workflow.id),
            "status": "queued",
            "queue": None,
            "outputs": None,
            "error": None,
            "execution_time_ms": None,
        }
        with (
            patch("app.api.workflows.validate_workflow_auth", validate or AsyncMock()),
            patch(
                "app.api.workflows.workflow_concurrency.status_token_hash_for",
                AsyncMock(return_value=stored_hash),
            ),
            patch(
                "app.api.workflows.workflow_concurrency.build_status_body",
                AsyncMock(return_value=body),
            ),
        ):
            return await get_workflow_execution_status(
                workflow_id=workflow.id,
                execution_id=uuid.uuid4(),
                request=_request(headers, query),
                current_user=None,
                db=db,
            )

    async def test_an_anonymous_run_is_read_with_its_token(self) -> None:
        response = await self._call(
            auth_type=WorkflowAuthType.anonymous,
            headers={"X-Heym-Run-Token": "tok"},
            stored_hash=hash_secret("tok"),
        )
        self.assertEqual(response.status, "queued")

    async def test_an_anonymous_run_without_a_token_is_not_found(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(auth_type=WorkflowAuthType.anonymous, stored_hash=hash_secret("tok"))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_the_stored_digest_does_not_authenticate(self) -> None:
        digest = hash_secret("tok")
        with self.assertRaises(HTTPException) as ctx:
            await self._call(
                auth_type=WorkflowAuthType.anonymous,
                headers={"X-Heym-Run-Token": digest},
                stored_hash=digest,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_a_token_in_the_query_string_is_ignored(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(
                auth_type=WorkflowAuthType.anonymous,
                query=b"token=tok&run_token=tok",
                stored_hash=hash_secret("tok"),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_a_wrong_token_looks_like_an_unknown_run(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._call(
                auth_type=WorkflowAuthType.anonymous,
                headers={"X-Heym-Run-Token": "nope"},
                stored_hash=hash_secret("tok"),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_jwt_workflows_use_the_webhook_auth(self) -> None:
        validate = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="JWT authentication required")
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(auth_type=WorkflowAuthType.jwt, validate=validate)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_header_auth_workflows_pass_through_validation(self) -> None:
        validate = AsyncMock()
        response = await self._call(auth_type=WorkflowAuthType.header_auth, validate=validate)
        validate.assert_awaited_once()
        self.assertEqual(response.status, "queued")
