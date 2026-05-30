import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.auth import update_me
from app.db.models import CredentialType
from app.models.schemas import UserUpdate


class UserTtsPreferencesTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_me_sets_tts_fields_for_valid_elevenlabs_credential(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        cred_id = uuid.uuid4()
        credential = MagicMock()
        credential.type = CredentialType.elevenlabs
        db = AsyncMock()

        with (
            patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=credential)),
            patch("app.api.auth.UserResponse") as resp,
        ):
            resp.model_validate.return_value = "ok"
            data = UserUpdate(tts_credential_id=cred_id, tts_voice_id="voice_abc")
            await update_me(data, current_user=user, db=db)

        self.assertEqual(user.tts_credential_id, cred_id)
        self.assertEqual(user.tts_voice_id, "voice_abc")

    async def test_update_me_rejects_non_elevenlabs_credential(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        credential = MagicMock()
        credential.type = CredentialType.openai
        db = AsyncMock()

        with patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=credential)):
            data = UserUpdate(tts_credential_id=uuid.uuid4())
            with self.assertRaises(HTTPException) as ctx:
                await update_me(data, current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 400)
