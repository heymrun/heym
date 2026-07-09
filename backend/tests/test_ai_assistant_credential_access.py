import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.api.ai_assistant import get_credential_for_user
from app.db.models import Credential, CredentialType


class AIAssistantCredentialAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_credential_for_user_uses_accessible_credential_helper(self) -> None:
        user_id = uuid.uuid4()
        credential_id = uuid.uuid4()
        user = AsyncMock(id=user_id)
        db = AsyncMock()
        credential = Credential(
            id=credential_id,
            owner_id=uuid.uuid4(),
            name="Team OpenAI",
            type=CredentialType.openai,
            encrypted_config="encrypted",
        )

        with patch(
            "app.api.ai_assistant.get_accessible_credential",
            AsyncMock(return_value=credential),
        ) as accessible_mock:
            result = await get_credential_for_user(credential_id, user, db)

        self.assertIs(result, credential)
        accessible_mock.assert_awaited_once_with(db, credential_id, user_id)
