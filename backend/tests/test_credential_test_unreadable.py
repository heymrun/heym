"""Connection tests on a credential whose stored value no configured key decrypts."""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet
from fastapi import HTTPException

from app.api.credentials import run_credential_connection_test
from app.db.models import CredentialType
from app.models.schemas import CredentialTestRequest

OWNER_ID = uuid.uuid4()
ENTERED = {
    "base_url": "https://owner-new.atlassian.net",
    "email": "owner@company.example",
    "api_token": "ENTERED-JIRA-TOKEN",
}


def _user(user_id: uuid.UUID) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.email = f"{user_id}@example.test"
    return user


def _unreadable_credential() -> MagicMock:
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.name = "jira credential"
    credential.type = CredentialType.jira
    credential.owner_id = OWNER_ID
    credential.encrypted_config = Fernet(Fernet.generate_key()).encrypt(b"{}").decode()
    return credential


class UnreadableCredentialConnectionTestTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, credential: MagicMock, user: MagicMock, config: dict | None):
        request = CredentialTestRequest(
            type=CredentialType.jira, credential_id=credential.id, config=config
        )
        with patch(
            "app.api.credentials._get_accessible_credential",
            AsyncMock(return_value=credential),
        ):
            return await run_credential_connection_test(request, current_user=user, db=MagicMock())

    async def test_the_owner_tests_the_value_entered_again(self) -> None:
        with patch("app.services.jira_service.JiraService") as service:
            service.return_value.test_connection.return_value = {"displayName": "Owner"}
            response = await self._run(_unreadable_credential(), _user(OWNER_ID), ENTERED)
        self.assertTrue(response.success)
        self.assertEqual(service.call_args.args[0]["api_token"], "ENTERED-JIRA-TOKEN")

    async def test_nothing_entered_is_a_409_not_a_500(self) -> None:
        for user_id in (OWNER_ID, uuid.uuid4()):
            with self.subTest(owner=user_id == OWNER_ID):
                with patch("app.services.jira_service.JiraService") as service:
                    with self.assertRaises(HTTPException) as ctx:
                        await self._run(_unreadable_credential(), _user(user_id), None)
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertIn("Enter its whole value again", ctx.exception.detail)
                service.assert_not_called()

    async def test_a_non_owner_still_cannot_send_a_value(self) -> None:
        with patch("app.services.jira_service.JiraService") as service:
            with self.assertRaises(HTTPException) as ctx:
                await self._run(_unreadable_credential(), _user(uuid.uuid4()), ENTERED)
        self.assertEqual(ctx.exception.status_code, 403)
        service.assert_not_called()


if __name__ == "__main__":
    unittest.main()
