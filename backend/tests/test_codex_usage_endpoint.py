import uuid
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import get_codex_usage
from app.db.models import CredentialType
from app.models.schemas import CodexUsageResponse


class CodexUsageEndpointTest(IsolatedAsyncioTestCase):
    async def test_non_codex_returns_400(self) -> None:
        cred = MagicMock()
        cred.type = CredentialType.openai
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid.uuid4()
        with patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=cred)):
            with self.assertRaises(HTTPException) as ctx:
                await get_codex_usage(uuid.uuid4(), current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_not_found_returns_404(self) -> None:
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid.uuid4()
        with patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await get_codex_usage(uuid.uuid4(), current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_codex_returns_usage(self) -> None:
        cred = MagicMock()
        cred.id = uuid.uuid4()
        cred.type = CredentialType.codex
        cred.encrypted_config = "enc"
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid.uuid4()
        with (
            patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=cred)),
            patch(
                "app.api.credentials.decrypt_config",
                return_value={"access_token": "t", "account_id": "a"},
            ),
            patch(
                "app.api.credentials.fetch_codex_usage",
                AsyncMock(return_value=CodexUsageResponse(available=True, plan_type="plus")),
            ),
        ):
            result = await get_codex_usage(cred.id, current_user=user, db=db)
        self.assertTrue(result.available)
        self.assertEqual(result.plan_type, "plus")
