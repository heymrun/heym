"""Registration treats addresses that differ only by case as the same account."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.auth import register_account
from app.models.schemas import UserCreate


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


def _open_sso_row() -> SimpleNamespace:
    return SimpleNamespace(enabled=False, issuer="", client_id="", password_login_disabled=False)


class RegisterEmailCaseTests(unittest.IsolatedAsyncioTestCase):
    async def _register(self, email: str, existing_id: uuid.UUID | None) -> AsyncMock:
        db = AsyncMock()
        db.add = lambda _user: None
        db.execute.return_value = _ScalarResult(existing_id)
        with (
            patch("app.api.auth.get_sso_settings", AsyncMock(return_value=_open_sso_row())),
            patch("app.api.auth.register_limiter") as limiter,
            patch("app.api.auth.settings.allow_register", True),
        ):
            limiter.is_allowed.return_value = (True, 0)
            await register_account(
                db, UserCreate(email=email, password="Passw0rd!x", name="Test"), "203.0.113.7"
            )
        return db

    async def test_a_case_variant_of_an_existing_address_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            await self._register("ADMIN@corp.example", uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Email already registered")

    async def test_the_duplicate_lookup_compares_lowercased_addresses(self) -> None:
        db = await self._register("Grace.Hopper@corp.example", None)

        statement = db.execute.await_args.args[0]
        sql = str(
            statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        self.assertIn("lower(trim(users.email))", sql)
        self.assertIn("'grace.hopper@corp.example'", sql)

    async def test_a_new_address_is_still_stored_as_typed(self) -> None:
        db = await self._register("Grace.Hopper@corp.example", None)

        created = db.refresh.await_args.args[0]
        self.assertEqual(created.email, "Grace.Hopper@corp.example")


if __name__ == "__main__":
    unittest.main()
