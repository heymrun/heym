import unittest
import uuid
from unittest.mock import AsyncMock, Mock

from app.db.models import Credential, CredentialType
from app.services.credential_access import get_accessible_credential


def make_result(value: object) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = value
    return result


class CredentialAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_directly_shared_credential(self) -> None:
        user_id = uuid.uuid4()
        credential = Credential(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Shared OpenAI",
            type=CredentialType.openai,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                make_result(None),
                make_result(credential),
            ]
        )

        result = await get_accessible_credential(db, credential.id, user_id)

        self.assertIs(result, credential)
        self.assertEqual(db.execute.await_count, 2)

    async def test_returns_team_shared_credential(self) -> None:
        user_id = uuid.uuid4()
        credential = Credential(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            name="Team OpenAI",
            type=CredentialType.openai,
            encrypted_config="encrypted",
        )
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                make_result(None),
                make_result(None),
                make_result(credential),
            ]
        )

        result = await get_accessible_credential(db, credential.id, user_id)

        self.assertIs(result, credential)
        self.assertEqual(db.execute.await_count, 3)
