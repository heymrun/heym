import datetime
import time
import unittest
import unittest.mock
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import jwt
from fastapi import HTTPException, Request

from app.api.workflows import (
    create_execution_token_endpoint,
    list_execution_tokens_endpoint,
    revoke_execution_token_endpoint,
    validate_workflow_auth,
)
from app.config import settings
from app.db.models import WorkflowAuthType
from app.models.schemas import ExecutionTokenCreate
from app.services.auth import create_workflow_execution_token


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _ScalarsResult:
    def __init__(self, values: list) -> None:
        self._values = values

    def scalars(self) -> "_ScalarsResult":
        return self

    def all(self) -> list:
        return self._values


class CreateWorkflowExecutionTokenTests(unittest.TestCase):
    def test_jwt_contains_correct_claims(self) -> None:
        user_id = uuid.uuid4()
        workflow_id = uuid.uuid4()

        token_str, jti, expires_at = create_workflow_execution_token(user_id, workflow_id, 900)

        payload = jwt.decode(token_str, settings.secret_key, algorithms=[settings.jwt_algorithm])
        self.assertEqual(payload["sub"], str(user_id))
        self.assertEqual(payload["wid"], str(workflow_id))
        self.assertEqual(payload["scope"], "workflow:execute")
        self.assertEqual(payload["jti"], str(jti))
        self.assertAlmostEqual(payload["exp"], int(time.time()) + 900, delta=5)

    def test_jti_is_uuid(self) -> None:
        _, jti, _ = create_workflow_execution_token(uuid.uuid4(), uuid.uuid4(), 60)
        self.assertIsInstance(jti, uuid.UUID)

    def test_different_calls_produce_different_jtis(self) -> None:
        uid, wid = uuid.uuid4(), uuid.uuid4()
        _, jti1, _ = create_workflow_execution_token(uid, wid, 60)
        _, jti2, _ = create_workflow_execution_token(uid, wid, 60)
        self.assertNotEqual(jti1, jti2)

    def test_ttl_controls_expiry(self) -> None:
        _, _, expires_at = create_workflow_execution_token(uuid.uuid4(), uuid.uuid4(), 3600)
        delta = (expires_at - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        self.assertAlmostEqual(delta, 3600, delta=5)


class ExecutionTokenEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _user(self) -> SimpleNamespace:
        return SimpleNamespace(id=uuid.uuid4())

    def _workflow(self, owner_id: uuid.UUID | None = None) -> SimpleNamespace:
        return SimpleNamespace(id=uuid.uuid4(), owner_id=owner_id or uuid.uuid4())

    async def test_create_inserts_row_and_returns_token(self) -> None:
        user = self._user()
        workflow = self._workflow(user.id)
        now = datetime.datetime.now(datetime.timezone.utc)
        fake_row = SimpleNamespace(
            id=uuid.uuid4(),
            token="fake.jwt.token",
            expires_at=now,
            created_at=now,
            revoked=False,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda row: None)

        with (
            unittest.mock.patch(
                "app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)
            ),
            unittest.mock.patch(
                "app.api.workflows.create_workflow_execution_token",
                return_value=("fake.jwt.token", uuid.uuid4(), now),
            ),
            unittest.mock.patch(
                "app.api.workflows.ExecutionTokenResponse.model_validate",
                return_value=fake_row,
            ),
        ):
            result = await create_execution_token_endpoint(
                workflow_id=workflow.id,
                body=ExecutionTokenCreate(ttl_seconds=900),
                current_user=user,
                db=db,
            )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        self.assertEqual(result.token, "fake.jwt.token")

    async def test_create_raises_404_for_unknown_workflow(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(None))

        with self.assertRaises(HTTPException) as ctx:
            await create_execution_token_endpoint(
                workflow_id=uuid.uuid4(),
                body=ExecutionTokenCreate(ttl_seconds=900),
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_create_raises_404_when_no_access(self) -> None:
        user = self._user()
        workflow = self._workflow()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(workflow))

        with (
            unittest.mock.patch(
                "app.api.workflows.user_has_workflow_access", AsyncMock(return_value=False)
            ),
            self.assertRaises(HTTPException) as ctx,
        ):
            await create_execution_token_endpoint(
                workflow_id=workflow.id,
                body=ExecutionTokenCreate(ttl_seconds=900),
                current_user=user,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_list_returns_user_tokens(self) -> None:
        user = self._user()
        now = datetime.datetime.now(datetime.timezone.utc)
        token_row = SimpleNamespace(
            id=uuid.uuid4(), token="tok", expires_at=now, created_at=now, revoked=False
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarsResult([token_row]))

        with unittest.mock.patch(
            "app.api.workflows.ExecutionTokenResponse.model_validate",
            side_effect=lambda r: r,
        ):
            result = await list_execution_tokens_endpoint(
                workflow_id=uuid.uuid4(),
                current_user=user,
                db=db,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].token, "tok")

    async def test_revoke_sets_revoked_true(self) -> None:
        user = self._user()
        token_row = SimpleNamespace(id=uuid.uuid4(), revoked=False)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(token_row))
        db.commit = AsyncMock()

        await revoke_execution_token_endpoint(
            workflow_id=uuid.uuid4(),
            token_id=token_row.id,
            current_user=user,
            db=db,
        )

        self.assertTrue(token_row.revoked)
        db.commit.assert_awaited_once()

    async def test_revoke_raises_404_when_not_found(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(None))

        with self.assertRaises(HTTPException) as ctx:
            await revoke_execution_token_endpoint(
                workflow_id=uuid.uuid4(),
                token_id=uuid.uuid4(),
                current_user=SimpleNamespace(id=uuid.uuid4()),
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 404)


def _jwt_workflow(workflow_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=workflow_id,
        auth_type=WorkflowAuthType.jwt,
        auth_header_key=None,
        auth_header_value=None,
    )


def _request_with_bearer(token: str) -> Request:
    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "query_string": b"",
    }
    return Request(scope, receive)


class ValidateWorkflowAuthScopedTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_scoped_token_is_accepted(self) -> None:
        workflow_id = uuid.uuid4()
        token_str, _, _ = create_workflow_execution_token(uuid.uuid4(), workflow_id, 900)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(SimpleNamespace(revoked=False)))

        await validate_workflow_auth(
            _jwt_workflow(workflow_id), _request_with_bearer(token_str), None, db
        )

    async def test_revoked_scoped_token_raises_401(self) -> None:
        workflow_id = uuid.uuid4()
        token_str, _, _ = create_workflow_execution_token(uuid.uuid4(), workflow_id, 900)

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(None))

        with self.assertRaises(HTTPException) as ctx:
            await validate_workflow_auth(
                _jwt_workflow(workflow_id), _request_with_bearer(token_str), None, db
            )
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_scoped_token_for_wrong_workflow_raises_401(self) -> None:
        token_str, _, _ = create_workflow_execution_token(uuid.uuid4(), uuid.uuid4(), 900)
        db = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await validate_workflow_auth(
                _jwt_workflow(uuid.uuid4()), _request_with_bearer(token_str), None, db
            )
        self.assertEqual(ctx.exception.status_code, 401)
        db.execute.assert_not_called()

    async def test_expired_scoped_token_raises_401(self) -> None:
        workflow_id = uuid.uuid4()
        payload = {
            "sub": str(uuid.uuid4()),
            "wid": str(workflow_id),
            "scope": "workflow:execute",
            "jti": str(uuid.uuid4()),
            "exp": int(time.time()) - 10,
        }
        expired_token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
        db = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await validate_workflow_auth(
                _jwt_workflow(workflow_id), _request_with_bearer(expired_token), None, db
            )
        self.assertEqual(ctx.exception.status_code, 401)
        db.execute.assert_not_called()

    async def test_regular_user_jwt_still_works(self) -> None:
        user = SimpleNamespace(id=uuid.uuid4())
        workflow = _jwt_workflow(uuid.uuid4())
        db = AsyncMock()

        with unittest.mock.patch(
            "app.api.workflows.user_has_workflow_access", AsyncMock(return_value=True)
        ):
            await validate_workflow_auth(workflow, _request_with_bearer("ignored"), user, db)
