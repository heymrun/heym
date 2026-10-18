"""A credential form link is no credential: only the user it was opened for can use it.

MCP URL elicitation hands the link to the client, and through it to the model, so the page
behind it must not be pre-authenticated (MCP 2025-11-25, Safe URL Handling) and must check
that the signed-in user is the one who started the request (Phishing).
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.api import credential_setup as api
from app.db.models import CredentialSetupRequest
from app.models.credential_setup_schemas import CredentialSetupComplete


def _row(user_id: uuid.UUID, **overrides: object) -> CredentialSetupRequest:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": user_id,
        "action": "create",
        "credential_type": "github",
        "suggested_name": "GitHub",
        "credential_id": None,
        "reason": None,
        "status": "pending",
        "client_action": None,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "completed_at": None,
    }
    values.update(overrides)
    return CredentialSetupRequest(**values)


def _db(row: CredentialSetupRequest | None, credential_owner: uuid.UUID | None = None) -> AsyncMock:
    db = AsyncMock()
    credential = (
        SimpleNamespace(owner_id=credential_owner, name="GitHub") if credential_owner else None
    )
    results = [MagicMock(scalar_one_or_none=MagicMock(return_value=row))]
    if credential_owner is not None:
        results.append(MagicMock(first=MagicMock(return_value=credential)))
    results.append(MagicMock(scalars=MagicMock(return_value=[])))
    db.execute = AsyncMock(side_effect=results)
    return db


class CredentialSetupOwnerOnlyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = SimpleNamespace(id=uuid.uuid4())

    async def test_every_lookup_is_scoped_to_the_signed_in_user(self) -> None:
        row = _row(self.user.id)
        db = _db(row)

        await api.get_credential_setup(row.id, current_user=self.user, db=db)

        params = db.execute.await_args_list[0].args[0].compile().params
        self.assertEqual(params["id_1"], row.id)
        self.assertEqual(params["user_id_1"], self.user.id)

    async def test_someone_elses_request_is_not_found(self) -> None:
        for call in (
            lambda db: api.get_credential_setup(uuid.uuid4(), current_user=self.user, db=db),
            lambda db: api.complete_credential_setup(
                uuid.uuid4(),
                CredentialSetupComplete(credential_id=uuid.uuid4()),
                current_user=self.user,
                db=db,
            ),
            lambda db: api.decline_credential_setup(uuid.uuid4(), current_user=self.user, db=db),
        ):
            db = _db(None)
            with self.assertRaises(HTTPException) as raised:
                await call(db)
            self.assertEqual(raised.exception.status_code, 404)
            db.commit.assert_not_awaited()

    async def test_completing_needs_a_credential_the_user_owns(self) -> None:
        row = _row(self.user.id)
        db = _db(row, credential_owner=uuid.uuid4())

        with self.assertRaises(HTTPException) as raised:
            await api.complete_credential_setup(
                row.id,
                CredentialSetupComplete(credential_id=uuid.uuid4()),
                current_user=self.user,
                db=db,
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(row.status, "pending")
        db.commit.assert_not_awaited()

    async def test_completing_records_the_owned_credential(self) -> None:
        row = _row(self.user.id)
        credential_id = uuid.uuid4()
        db = _db(row, credential_owner=self.user.id)

        response = await api.complete_credential_setup(
            row.id,
            CredentialSetupComplete(credential_id=credential_id),
            current_user=self.user,
            db=db,
        )

        self.assertEqual(response.status, "completed")
        self.assertEqual(row.credential_id, credential_id)
        self.assertIsNotNone(row.completed_at)
        db.commit.assert_awaited_once()

    async def test_an_update_form_only_accepts_its_own_credential(self) -> None:
        row = _row(self.user.id, action="update", credential_id=uuid.uuid4())
        db = _db(row, credential_owner=self.user.id)

        with self.assertRaises(HTTPException) as raised:
            await api.complete_credential_setup(
                row.id,
                CredentialSetupComplete(credential_id=uuid.uuid4()),
                current_user=self.user,
                db=db,
            )

        self.assertEqual(raised.exception.status_code, 400)
        db.commit.assert_not_awaited()

    async def test_closed_and_expired_forms_cannot_be_finished(self) -> None:
        cases = (
            (_row(self.user.id, status="completed"), 409),
            (_row(self.user.id, status="declined"), 409),
            (_row(self.user.id, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)), 410),
        )
        for row, code in cases:
            with self.subTest(code=code, status=row.status):
                db = _db(row, credential_owner=self.user.id)
                with self.assertRaises(HTTPException) as raised:
                    await api.decline_credential_setup(row.id, current_user=self.user, db=db)
                self.assertEqual(raised.exception.status_code, code)
                db.commit.assert_not_awaited()

    async def test_an_expired_form_reads_as_expired(self) -> None:
        row = _row(self.user.id, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))

        response = await api.get_credential_setup(row.id, current_user=self.user, db=_db(row))

        self.assertEqual(response.status, "expired")

    async def test_declining_closes_the_form(self) -> None:
        row = _row(self.user.id)
        db = _db(row)

        response = await api.decline_credential_setup(row.id, current_user=self.user, db=db)

        self.assertEqual(response.status, "declined")
        db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
