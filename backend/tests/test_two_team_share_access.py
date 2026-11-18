"""A user in several teams that share the same resource must still resolve it.

Access helpers used to join ``TeamMember`` onto the team-share table and call
``scalar_one_or_none()``. A user who belongs to two teams that both hold a share then matched two
rows and raised ``MultipleResultsFound``, which surfaced as a 500. They now use IN subqueries,
like ``workflow_access_clause``, so the resource is matched once however many teams apply.
"""

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.exc import MultipleResultsFound

from app.api import credentials as credentials_api
from app.api import global_variables as global_variables_api
from app.api import vector_stores as vector_stores_api
from app.db.models import Credential, CredentialType, GlobalVariable, VectorStore
from app.services import alert_access, credential_access
from app.services.encryption import encrypt_config

TEAMS = 2
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _Result:
    """A stand-in for SQLAlchemy's ``Result`` that enforces its row-count contract.

    ``scalar_one_or_none()`` raises ``MultipleResultsFound`` for more than one row, exactly as a
    real session does for a join that matched once per team. Canned ``SimpleNamespace`` doubles
    return one value regardless of the query and so could never show this failure.
    """

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        if len(self._rows) > 1:
            raise MultipleResultsFound(f"Multiple rows were found: {len(self._rows)}")
        return self._rows[0] if self._rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows), first=lambda: self._first())

    def _first(self):
        return self._rows[0] if self._rows else None


def _team_db(resource, *, member: bool = True, teams: int = TEAMS) -> AsyncMock:
    """Model a user who owns nothing, has no direct share, and may sit in ``teams`` teams that
    each share ``resource``.

    Queries are answered by their compiled shape rather than by call order. A query that joins
    ``team_members`` fans out to one row per shared team the user belongs to; one that filters
    through an IN subquery yields the resource at most once. So the same fake exposes the
    join-based implementation and passes the subquery-based one.
    """

    async def execute(stmt):
        sql = str(stmt)
        if "team_members" not in sql:
            return _Result([])
        if not member:
            return _Result([])
        if " JOIN team_members" in sql:
            return _Result([resource] * teams)
        return _Result([resource])

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute)
    return db


def _credential(cred_type: CredentialType = CredentialType.openai) -> Credential:
    credential = Credential(
        name="shared",
        type=cred_type,
        encrypted_config=encrypt_config({"api_key": "sk-test-1234567890"}),
        owner_id=uuid.uuid4(),
    )
    credential.id = uuid.uuid4()
    credential.created_at = NOW
    credential.updated_at = NOW
    return credential


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), email="bob@example.org", name="Bob")


class CredentialAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_resolves_credential_shared_with_two_teams(self) -> None:
        credential = _credential()

        result = await credential_access.get_accessible_credential(
            _team_db(credential), credential.id, uuid.uuid4()
        )

        self.assertIs(result, credential)

    async def test_service_denies_a_user_outside_every_team(self) -> None:
        credential = _credential()

        result = await credential_access.get_accessible_credential(
            _team_db(credential, member=False), credential.id, uuid.uuid4()
        )

        self.assertIsNone(result)

    async def test_api_helper_resolves_credential_shared_with_two_teams(self) -> None:
        credential = _credential()

        result = await credentials_api._get_accessible_credential(
            _team_db(credential), credential.id, _user()
        )

        self.assertIs(result, credential)

    async def test_api_helper_denies_a_user_outside_every_team(self) -> None:
        credential = _credential()

        result = await credentials_api._get_accessible_credential(
            _team_db(credential, member=False), credential.id, _user()
        )

        self.assertIsNone(result)

    async def test_get_credential_returns_credential_shared_with_two_teams(self) -> None:
        credential = _credential()

        response = await credentials_api.get_credential(
            credential.id, current_user=_user(), db=_team_db(credential)
        )

        self.assertEqual(response.id, credential.id)

    async def test_get_credential_is_404_for_a_user_outside_every_team(self) -> None:
        credential = _credential()

        with self.assertRaises(HTTPException) as ctx:
            await credentials_api.get_credential(
                credential.id, current_user=_user(), db=_team_db(credential, member=False)
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_get_credential_models_resolves_credential_shared_with_two_teams(self) -> None:
        credential = _credential()

        with patch("app.services.llm_provider.fetch_models", new=AsyncMock(return_value=[])):
            models = await credentials_api.get_credential_models(
                credential.id, current_user=_user(), db=_team_db(credential)
            )

        self.assertEqual(models, [])

    async def test_get_credential_models_is_404_for_a_user_outside_every_team(self) -> None:
        credential = _credential()

        with self.assertRaises(HTTPException) as ctx:
            await credentials_api.get_credential_models(
                credential.id, current_user=_user(), db=_team_db(credential, member=False)
            )

        self.assertEqual(ctx.exception.status_code, 404)


class AlertAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_alert_shared_with_two_teams(self) -> None:
        alert = SimpleNamespace(id=uuid.uuid4())

        result = await alert_access.get_accessible_alert(_team_db(alert), alert.id, uuid.uuid4())

        self.assertIs(result, alert)

    async def test_denies_a_user_outside_every_team(self) -> None:
        alert = SimpleNamespace(id=uuid.uuid4())

        result = await alert_access.get_accessible_alert(
            _team_db(alert, member=False), alert.id, uuid.uuid4()
        )

        self.assertIsNone(result)


def _variable() -> GlobalVariable:
    variable = GlobalVariable(
        name="shared_var", value={"value": "v"}, value_type="string", owner_id=uuid.uuid4()
    )
    variable.id = uuid.uuid4()
    variable.created_at = NOW
    variable.updated_at = NOW
    return variable


class GlobalVariableAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_returns_variable_shared_with_two_teams(self) -> None:
        variable = _variable()

        response = await global_variables_api.get_global_variable(
            variable.id, current_user=_user(), db=_team_db(variable)
        )

        self.assertEqual(response.id, variable.id)

    async def test_get_is_404_for_a_user_outside_every_team(self) -> None:
        variable = _variable()

        with self.assertRaises(HTTPException) as ctx:
            await global_variables_api.get_global_variable(
                variable.id, current_user=_user(), db=_team_db(variable, member=False)
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_editable_lookup_resolves_variable_shared_with_two_teams(self) -> None:
        variable = _variable()

        result = await global_variables_api._get_editable_variable(
            _team_db(variable), variable.id, uuid.uuid4()
        )

        self.assertIs(result, variable)

    async def test_editable_lookup_denies_a_user_outside_every_team(self) -> None:
        variable = _variable()

        result = await global_variables_api._get_editable_variable(
            _team_db(variable, member=False), variable.id, uuid.uuid4()
        )

        self.assertIsNone(result)


class VectorStoreAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_credential_config_resolves_credential_shared_with_two_teams(self) -> None:
        credential = _credential(CredentialType.qdrant)

        resolved, _config = await vector_stores_api.get_credential_config(
            credential.id, uuid.uuid4(), _team_db(credential)
        )

        self.assertIs(resolved, credential)

    async def test_credential_config_is_404_for_a_user_outside_every_team(self) -> None:
        credential = _credential(CredentialType.qdrant)

        with self.assertRaises(HTTPException) as ctx:
            await vector_stores_api.get_credential_config(
                credential.id, uuid.uuid4(), _team_db(credential, member=False)
            )

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_store_lookup_resolves_store_shared_with_two_teams(self) -> None:
        store = VectorStore(name="s", collection_name="c", owner_id=uuid.uuid4())
        store.id = uuid.uuid4()

        async def execute(stmt):
            sql = str(stmt)
            if "vector_store_team_shares" in sql:
                return _Result(["read"] * TEAMS)
            if "vector_store_shares" in sql or "owner_id =" in sql:
                return _Result([])
            return _Result([store])

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=execute)

        result = await vector_stores_api._get_accessible_store(store.id, uuid.uuid4(), db)

        self.assertIs(result, store)

    async def test_store_lookup_is_404_for_a_user_outside_every_team(self) -> None:
        store = VectorStore(name="s", collection_name="c", owner_id=uuid.uuid4())
        store.id = uuid.uuid4()

        with self.assertRaises(HTTPException) as ctx:
            await vector_stores_api._get_accessible_store(
                store.id, uuid.uuid4(), _team_db(store, member=False)
            )

        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
