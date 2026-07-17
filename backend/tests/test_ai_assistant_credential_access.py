import unittest
import uuid
from unittest.mock import AsyncMock, patch

from app.api.ai_assistant import get_credential_for_user, get_openai_client
from app.db.models import Credential, CredentialType
from app.http_identity import HEYM_USER_AGENT


class AIAssistantOpenAIClientTests(unittest.TestCase):
    def test_all_provider_clients_include_heym_user_agent(self) -> None:
        cases = (
            (CredentialType.openai, {"api_key": "sk-test"}, "OpenAI"),
            (CredentialType.google, {"api_key": "sk-test"}, "Google"),
            (
                CredentialType.custom,
                {"api_key": "sk-test", "base_url": "https://llm.example.test"},
                "Custom",
            ),
        )

        for credential_type, config, expected_label in cases:
            with self.subTest(credential_type=credential_type):
                client, label = get_openai_client(credential_type, config)
                try:
                    self.assertEqual(label, expected_label)
                    self.assertEqual(client.default_headers["User-Agent"], HEYM_USER_AGENT)
                finally:
                    client.close()


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
