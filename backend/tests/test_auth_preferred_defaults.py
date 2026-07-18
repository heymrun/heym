import uuid
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.auth import update_me
from app.db.models import CredentialType
from app.models.schemas import UserUpdate


def _user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.preferred_credential_id = None
    user.preferred_model = None
    return user


class UpdatePreferredDefaultsTest(IsolatedAsyncioTestCase):
    async def test_sets_preferred_credential_and_model(self) -> None:
        user = _user()
        cred_id = uuid.uuid4()
        db = AsyncMock()
        cred = MagicMock()
        cred.type = CredentialType.openai
        with (
            patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=cred)),
            patch("app.api.auth.UserResponse") as resp,
        ):
            resp.model_validate.return_value = "ok"
            data = UserUpdate(preferred_credential_id=cred_id, preferred_model="gpt-4o")
            await update_me(data, current_user=user, db=db)
        self.assertEqual(user.preferred_credential_id, cred_id)
        self.assertEqual(user.preferred_model, "gpt-4o")

    async def test_inaccessible_credential_raises_404(self) -> None:
        user = _user()
        db = AsyncMock()
        with patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=None)):
            data = UserUpdate(preferred_credential_id=uuid.uuid4(), preferred_model="gpt-4o")
            with self.assertRaises(HTTPException) as ctx:
                await update_me(data, current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_model_only_update_persists_without_credential_lookup(self) -> None:
        user = _user()
        user.preferred_credential_id = uuid.uuid4()
        db = AsyncMock()
        with (
            patch("app.api.auth.get_accessible_credential", AsyncMock()) as get_cred,
            patch("app.api.auth.UserResponse") as resp,
        ):
            resp.model_validate.return_value = "ok"
            data = UserUpdate(preferred_model="gpt-4o-mini")
            await update_me(data, current_user=user, db=db)
        get_cred.assert_not_awaited()
        self.assertEqual(user.preferred_model, "gpt-4o-mini")
