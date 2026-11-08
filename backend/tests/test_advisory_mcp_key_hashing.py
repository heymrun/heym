"""GHSA-6x65-w7q7-wg93 finding 2: MCP API keys at rest and in URLs."""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException

from app.api.mcp import get_mcp_user
from app.services.secret_tokens import hash_secret


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Request:
    def __init__(self, query: dict[str, str] | None = None, headers: dict[str, str] | None = None):
        self.query_params = query or {}
        self.headers = headers or {}


class HashSecretTests(unittest.TestCase):
    def test_digest_is_stable_sha256_hex(self) -> None:
        digest = hash_secret("swordfish")

        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, hash_secret("swordfish"))
        self.assertNotEqual(digest, hash_secret("swordfisi"))

    def test_digest_fits_the_existing_column_width(self) -> None:
        """Both key columns are String(64); a hex digest is exactly 64 chars."""
        self.assertEqual(len(hash_secret("a" * 512)), 64)


class MCPKeyAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_key_authenticates_against_the_stored_digest(self) -> None:
        raw_key = "the-real-key"
        user = SimpleNamespace(id=uuid.uuid4(), mcp_api_key=hash_secret(raw_key), is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(user))

        result = await get_mcp_user(request=_Request(), x_mcp_key=raw_key, db=db)

        self.assertIs(result, user)

    async def test_stored_digest_is_not_itself_a_credential(self) -> None:
        """The whole point of hashing: reading the row must not yield a key.

        A lookup that also tried the presented value verbatim would match the
        stored digest and hand a database reader a working credential.
        """
        raw_key = "the-real-key"
        stored = hash_secret(raw_key)
        seen_bindings: list[object] = []

        async def capture(statement):
            seen_bindings.append(statement)
            return _ScalarResult(None)

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=capture)

        with self.assertRaises(HTTPException) as ctx:
            await get_mcp_user(request=_Request(), x_mcp_key=stored, db=db)

        self.assertEqual(ctx.exception.status_code, 401)
        # The query looked for SHA256(stored), never for `stored` itself.
        compiled = str(seen_bindings[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn(hash_secret(stored), compiled)
        self.assertNotIn(f"'{stored}'", compiled)

    async def test_query_string_key_no_longer_authenticates(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(None))

        with self.assertRaises(HTTPException) as ctx:
            await get_mcp_user(
                request=_Request(query={"key": "the-real-key"}), x_mcp_key=None, db=db
            )

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("X-MCP-Key header", ctx.exception.detail)

    async def test_query_string_oauth_token_no_longer_authenticates(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(None))

        with self.assertRaises(HTTPException) as ctx:
            await get_mcp_user(
                request=_Request(query={"token": "oauth-token"}), x_mcp_key=None, db=db
            )

        self.assertEqual(ctx.exception.status_code, 401)

    async def test_unknown_key_is_rejected(self) -> None:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(None))

        with self.assertRaises(HTTPException) as ctx:
            await get_mcp_user(request=_Request(), x_mcp_key="nope", db=db)

        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
