"""Sign-in surfaces find an account whatever the casing of the address."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy.dialects import postgresql

from app.api.auth import password_sign_in
from app.api.oauth import _generate_csrf_token, authorize_post
from app.api.sso_auth import resolve_sso_user
from app.models.schemas import UserLogin
from app.services.auth import hash_password
from app.services.user_lookup import find_user_by_email


def _result(value: object) -> MagicMock:
    return MagicMock(scalar_one_or_none=MagicMock(return_value=value))


def _sql(statement: object) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _open_sso_row() -> SimpleNamespace:
    return SimpleNamespace(enabled=False, issuer="", client_id="", password_login_disabled=False)


def _form_request(data: dict[str, str]) -> Request:
    body = urlencode(data).encode()

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/authorize",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
            "query_string": b"",
        },
        receive,
    )


class FindUserByEmailTests(unittest.IsolatedAsyncioTestCase):
    async def _statement_for(self, email: str) -> str:
        db = AsyncMock()
        db.execute.return_value = _result(None)
        await find_user_by_email(db, email)
        return _sql(db.execute.await_args.args[0])

    async def test_the_lookup_ignores_case_and_surrounding_whitespace(self) -> None:
        sql = await self._statement_for("  Jane.Doe@Corp.example ")

        self.assertIn("lower(trim(users.email)) = 'jane.doe@corp.example'", sql)

    async def test_case_variant_rows_resolve_to_one_account_preferring_the_exact_spelling(
        self,
    ) -> None:
        """Older instances can hold Jane@ and jane@; picking one must not raise."""
        sql = await self._statement_for("Jane.Doe@corp.example")

        self.assertIn(
            "ORDER BY users.email = 'Jane.Doe@corp.example' DESC, users.created_at, users.id",
            sql,
        )
        self.assertIn("LIMIT 1", sql)

    async def test_a_blank_address_matches_nobody_without_querying(self) -> None:
        db = AsyncMock()

        self.assertIsNone(await find_user_by_email(db, "   "))
        db.execute.assert_not_awaited()


class PasswordSignInEmailCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_case_variant_of_the_stored_address_signs_in(self) -> None:
        stored = SimpleNamespace(
            id=uuid.uuid4(),
            email="Jane.Doe@corp.example",
            hashed_password=hash_password("Passw0rd!x"),
        )
        db = AsyncMock()
        db.execute.return_value = _result(stored)

        with (
            patch("app.api.auth.get_sso_settings", AsyncMock(return_value=_open_sso_row())),
            patch("app.api.auth.login_limiter") as limiter,
        ):
            limiter.is_allowed.return_value = (True, 0)
            user = await password_sign_in(
                db,
                UserLogin(email="jane.doe@corp.example", password="Passw0rd!x"),
                "203.0.113.7",
            )

        self.assertIs(user, stored)
        self.assertIn(
            "lower(trim(users.email)) = 'jane.doe@corp.example'",
            _sql(db.execute.await_args.args[0]),
        )


class SsoEmailCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_password_account_with_other_casing_is_claimed_not_duplicated(self) -> None:
        """The provider's address is lowercased; the stored one was kept as typed."""
        existing = SimpleNamespace(
            id=uuid.uuid4(), email="Ada@heym.example", sso_issuer=None, sso_subject=None
        )
        db = AsyncMock()
        db.execute.side_effect = [_result(None), _result(existing)]
        row = SimpleNamespace(auto_provision_users=True, allowed_email_domains="")
        claims = {"sub": "ada-subject", "email": "ADA@heym.example", "email_verified": True}

        user = await resolve_sso_user(db, row, "https://idp.example/realms/heym", claims)

        self.assertIs(user, existing)
        self.assertEqual(existing.sso_subject, "ada-subject")
        db.add.assert_not_called()
        self.assertIn(
            "lower(trim(users.email)) = 'ada@heym.example'",
            _sql(db.execute.await_args_list[1].args[0]),
        )


class OAuthConsentEmailCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_consent_form_accepts_a_case_variant_of_the_stored_address(self) -> None:
        client = SimpleNamespace(
            client_id="confidential-client",
            client_name="Client",
            redirect_uris=["https://client.example/callback"],
            is_confidential=True,
        )
        stored = SimpleNamespace(id=uuid.uuid4(), email="Jane@corp.example", hashed_password="h")
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(
            side_effect=[_result(client), _result(stored), _result(_open_sso_row())]
        )

        with patch("app.api.oauth.verify_password", return_value=True):
            response = await authorize_post(
                request=_form_request(
                    {
                        "client_id": client.client_id,
                        "redirect_uri": client.redirect_uris[0],
                        "scope": "mcp",
                        "state": "s",
                        "csrf_token": _generate_csrf_token(client.client_id),
                        "email": "jane@corp.example",
                        "password": "secret",
                    }
                ),
                db=db,
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "lower(trim(users.email)) = 'jane@corp.example'",
            _sql(db.execute.await_args_list[1].args[0]),
        )


if __name__ == "__main__":
    unittest.main()
