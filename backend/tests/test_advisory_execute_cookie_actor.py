"""The session cookie alone must not pick whose credentials a run uses (GHSA-m2cg-mg73-qc82).

A signed-in user who followed a link to ``/api/workflows/<id>/execute`` ran the workflow as
themselves: ``validate_workflow_auth`` returned the cookie's user for an anonymous workflow,
and the endpoint built the run's ``$credentials`` and ``$global`` from that user. The
workflow's author then read the values back from run history. An access check alone does
not close it: the author can share the workflow with the victim first, and an instance admin
passes every access check.

``get_execution_caller`` therefore ignores a session that arrives only as the
``access_token`` cookie unless the request is one of Heym's own API calls
(``X-Heym-Client``). Bearer tokens (API clients, execution tokens) keep their actor.
"""

import inspect
import unittest
import uuid
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import HEYM_CLIENT_HEADER, get_execution_caller
from app.api.workflows import (
    execute_workflow_endpoint,
    execute_workflow_stream,
    validate_workflow_auth,
)
from app.models.schemas import WorkflowAuthType
from app.services.auth import create_workflow_execution_token
from app.services.workflow_executor import ExecutionResult

_COOKIE = "access_token=session-token-of-the-visitor"


def _request(
    *,
    method: str = "GET",
    cookie: bool = True,
    heym_client: bool = False,
    authorization: str | None = None,
    extra: dict[str, str] | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie:
        headers.append((b"cookie", _COOKIE.encode()))
    if heym_client:
        headers.append((HEYM_CLIENT_HEADER.lower().encode(), b"heym.run"))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    for key, value in (extra or {}).items():
        headers.append((key.lower().encode(), value.encode()))

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"" if method == "GET" else b"{}"}

    scope = {
        "type": "http",
        "method": method,
        "path": "/api/workflows/test/execute",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope, receive)


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _workflow(auth_type: WorkflowAuthType, owner_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        owner_id=owner_id or uuid.uuid4(),
        auth_type=auth_type,
        auth_header_key="X-Hook-Secret",
        auth_header_value="hook-secret-value",
        nodes=[],
        edges=[],
        rate_limit_requests=None,
        rate_limit_window_seconds=None,
        cache_ttl_seconds=None,
        sse_enabled=False,
        http_method="GET",
        name="Leak",
    )


class _ResolvesTo:
    """Patch the token lookup of ``get_current_user_optional`` to name ``user``."""

    def __init__(self, user: object) -> None:
        self.claims = AsyncMock(return_value=SimpleNamespace(user_id=getattr(user, "id", None)))
        self.load = AsyncMock(return_value=user)

    def __enter__(self) -> "_ResolvesTo":
        self._p1 = patch("app.api.deps.resolve_token_claims", self.claims)
        self._p2 = patch("app.api.deps._load_token_user", self.load)
        self._p1.start()
        self._p2.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._p2.stop()
        self._p1.stop()


class ExecuteEndpointsUseTheCallerDependency(unittest.TestCase):
    def test_execute_and_stream_resolve_the_caller_with_get_execution_caller(self) -> None:
        for endpoint in (execute_workflow_endpoint, execute_workflow_stream):
            with self.subTest(endpoint=endpoint.__name__):
                default = inspect.signature(endpoint).parameters["current_user"].default
                self.assertIs(default.dependency, get_execution_caller)


class GetExecutionCallerTests(unittest.IsolatedAsyncioTestCase):
    async def test_cookie_alone_on_a_navigation_is_no_caller(self) -> None:
        visitor = SimpleNamespace(id=uuid.uuid4())
        with _ResolvesTo(visitor) as lookup:
            caller = await get_execution_caller(_request(), None, AsyncMock())
        self.assertIsNone(caller)
        lookup.claims.assert_not_awaited()

    async def test_cookie_with_cross_site_fetch_metadata_is_no_caller(self) -> None:
        visitor = SimpleNamespace(id=uuid.uuid4())
        request = _request(extra={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})
        with _ResolvesTo(visitor):
            self.assertIsNone(await get_execution_caller(request, None, AsyncMock()))

    async def test_heym_app_request_with_the_cookie_keeps_its_user(self) -> None:
        """Negative case: editor and canvas runs still execute as the signed-in user."""
        editor_user = SimpleNamespace(id=uuid.uuid4())
        with _ResolvesTo(editor_user):
            caller = await get_execution_caller(
                _request(method="POST", heym_client=True), None, AsyncMock()
            )
        self.assertIs(caller, editor_user)

    async def test_bearer_access_token_keeps_its_user(self) -> None:
        """Negative case: API clients that send a bearer token keep their actor."""
        api_user = SimpleNamespace(id=uuid.uuid4())
        with _ResolvesTo(api_user):
            caller = await get_execution_caller(
                _request(method="POST", cookie=False, authorization="Bearer api-token"),
                _bearer("api-token"),
                AsyncMock(),
            )
        self.assertIs(caller, api_user)

    async def test_no_credentials_at_all_is_no_caller(self) -> None:
        self.assertIsNone(await get_execution_caller(_request(cookie=False), None, AsyncMock()))


class LinkScenarioTests(unittest.IsolatedAsyncioTestCase):
    """The cases from the advisory: shared workflows and instance admins."""

    async def _actor_for_link(self, workflow: SimpleNamespace, visitor: object) -> object:
        # The visitor has access: the author shared the workflow, or the visitor is an admin.
        request = _request()
        with (
            _ResolvesTo(visitor),
            patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)),
        ):
            caller = await get_execution_caller(request, None, AsyncMock())
            return await validate_workflow_auth(workflow, request, caller, AsyncMock())

    async def test_shared_anonymous_workflow_runs_as_owner_not_visitor(self) -> None:
        visitor = SimpleNamespace(id=uuid.uuid4(), email="visitor@example.org")
        actor = await self._actor_for_link(_workflow(WorkflowAuthType.anonymous), visitor)
        # None means the endpoint resolves credentials as workflow.owner_id.
        self.assertIsNone(actor)

    async def test_shared_jwt_workflow_opened_from_a_link_is_401(self) -> None:
        visitor = SimpleNamespace(id=uuid.uuid4(), email="visitor@example.org")
        with self.assertRaises(HTTPException) as ctx:
            await self._actor_for_link(_workflow(WorkflowAuthType.jwt), visitor)
        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    async def test_admin_link_on_anonymous_workflow_runs_as_owner(self) -> None:
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@example.org")
        self.assertIsNone(await self._actor_for_link(_workflow(WorkflowAuthType.anonymous), admin))

    async def test_admin_link_on_jwt_workflow_is_401(self) -> None:
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@example.org")
        with self.assertRaises(HTTPException) as ctx:
            await self._actor_for_link(_workflow(WorkflowAuthType.jwt), admin)
        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    async def test_admin_link_on_header_auth_workflow_without_the_header_is_401(self) -> None:
        admin = SimpleNamespace(id=uuid.uuid4(), email="admin@example.org")
        with self.assertRaises(HTTPException) as ctx:
            await self._actor_for_link(_workflow(WorkflowAuthType.header_auth), admin)
        self.assertEqual(ctx.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    async def test_editor_run_of_a_shared_jwt_workflow_keeps_the_user(self) -> None:
        """Negative case: the same user running it from Heym is still the actor."""
        user = SimpleNamespace(id=uuid.uuid4(), email="visitor@example.org")
        workflow = _workflow(WorkflowAuthType.jwt)
        request = _request(method="POST", heym_client=True)
        with (
            _ResolvesTo(user),
            patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)),
        ):
            caller = await get_execution_caller(request, None, AsyncMock())
            actor = await validate_workflow_auth(workflow, request, caller, AsyncMock())
        self.assertIs(actor, user)

    async def test_execution_token_keeps_its_minter(self) -> None:
        """Negative case: an execution token still runs as the user who minted it."""
        minter = SimpleNamespace(id=uuid.uuid4(), is_active=True)
        workflow = _workflow(WorkflowAuthType.jwt)
        token, _jti, _exp = create_workflow_execution_token(minter.id, workflow.id, 3600)
        request = _request(method="POST", cookie=False, authorization=f"Bearer {token}")
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                SimpleNamespace(scalar_one_or_none=lambda: SimpleNamespace(jti=uuid.uuid4())),
                SimpleNamespace(scalar_one_or_none=lambda: minter),
            ]
        )
        caller = await get_execution_caller(request, _bearer(token), AsyncMock())
        self.assertIsNone(caller)  # not an access token, so the token path decides
        with patch("app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)):
            actor = await validate_workflow_auth(workflow, request, caller, db)
        self.assertEqual(actor.id, minter.id)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class ExecuteEndpointCredentialOwnerTests(unittest.IsolatedAsyncioTestCase):
    """Through the endpoint: whose credentials and global variables the run receives."""

    async def _credential_owner(self, request: Request, visitor: object) -> uuid.UUID:
        owner_id = uuid.uuid4()
        workflow = _workflow(WorkflowAuthType.anonymous, owner_id=owner_id)
        workflow.http_method = request.method
        workflow.nodes = [
            {"id": "in1", "type": "textInput", "data": {"label": "userInput"}},
            {"id": "out1", "type": "output", "data": {"label": "out", "message": "done"}},
        ]
        workflow.edges = [{"id": "e1", "source": "in1", "target": "out1"}]
        execution_result = ExecutionResult(
            workflow_id=workflow.id,
            status="success",
            outputs={},
            node_results=[],
            execution_time_ms=1.0,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        credentials_context = AsyncMock(return_value={})
        globals_context = AsyncMock(return_value={})
        with _ResolvesTo(visitor):
            caller = await get_execution_caller(request, None, AsyncMock())
        with (
            patch("app.api.workflows.collect_referenced_workflows", AsyncMock(return_value={})),
            patch("app.api.workflows.get_credentials_context", credentials_context),
            patch("app.api.workflows.get_global_variables_context", globals_context),
            patch("app.api.workflows.register_execution", return_value=Event()),
            patch("app.api.workflows.clear_active_execution"),
            patch("app.api.workflows.upsert_workflow_analytics_snapshot", AsyncMock()),
            patch("app.api.workflows.asyncio.to_thread", AsyncMock(return_value=execution_result)),
            patch(
                "app.api.workflows.ExecutionHistory",
                side_effect=lambda **kw: SimpleNamespace(id=uuid.uuid4()),
            ),
        ):
            await execute_workflow_endpoint(
                workflow_id=workflow.id, request=request, current_user=caller, db=db
            )
        credentials_owner = credentials_context.await_args.args[1]
        self.assertEqual(globals_context.await_args.args[1], credentials_owner)
        self.owner_id = owner_id
        return credentials_owner

    async def test_link_visit_uses_the_owners_credentials(self) -> None:
        visitor = SimpleNamespace(id=uuid.uuid4())
        used = await self._credential_owner(_request(), visitor)
        self.assertEqual(used, self.owner_id)
        self.assertNotEqual(used, visitor.id)

    async def test_heym_app_run_uses_the_users_credentials(self) -> None:
        """Negative case: a run started inside Heym keeps the signed-in user's context."""
        user = SimpleNamespace(id=uuid.uuid4())
        used = await self._credential_owner(_request(method="POST", heym_client=True), user)
        self.assertEqual(used, user.id)


if __name__ == "__main__":
    unittest.main()
