"""Regression tests for GHSA-39qx-wp7x-69rq.

``POST /credentials/test`` accepted a shared credential together with a
caller-supplied destination, sending the owner's decrypted secret to a host the
collaborator picked.
"""

import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import run_credential_connection_test
from app.db.models import CredentialType
from app.models.schemas import CredentialTestRequest
from app.services.clickhouse_service import ClickHouseService
from app.services.encryption import encrypt_config
from app.services.ssrf_guard import SsrfBlockedError

OWNER_ID = uuid.uuid4()
COLLABORATOR_ID = uuid.uuid4()

# Linear and Notion are absent on purpose: their service origins are constants.
OVERRIDE_CASES = (
    (
        CredentialType.jira,
        {
            "base_url": "https://owner.atlassian.net",
            "email": "owner@company.example",
            "api_token": "OWNER-JIRA-TOKEN",
        },
        {"base_url": "https://collector.attacker.example"},
        "app.services.jira_service.JiraService",
    ),
    (
        CredentialType.supabase,
        {
            "supabase_url": "https://owner.supabase.co",
            "supabase_key": "OWNER-SUPABASE-KEY",
        },
        {"supabase_url": "https://collector.attacker.example"},
        "app.services.supabase_service.SupabaseService",
    ),
    (
        CredentialType.sentry,
        {
            "base_url": "https://sentry.io",
            "api_token": "OWNER-SENTRY-TOKEN",
            "organization": "acme",
        },
        {"base_url": "https://collector.attacker.example"},
        "app.services.sentry_service.SentryService",
    ),
    (
        CredentialType.rag,
        {
            "embedding_base_url": "https://api.openai.com/v1",
            "embedding_model": "text-embedding-3-small",
            "embedding_api_key": "OWNER-EMBEDDING-KEY",
            "embedding_dimensions": 1536,
            "db_type": "qdrant",
        },
        {"embedding_base_url": "https://collector.attacker.example/v1"},
        "app.services.embedding.EmbeddingService",
    ),
    (
        CredentialType.clickhouse,
        {
            "host": "owner.clickhouse.cloud",
            "port": 8443,
            "username": "default",
            "password": "OWNER-CLICKHOUSE-PASSWORD",
            "database": "default",
            "secure": True,
        },
        {"host": "collector.attacker.example", "secure": False},
        "app.services.clickhouse_service.ClickHouseService",
    ),
)


def _user(user_id: uuid.UUID) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.email = f"{user_id}@example.test"
    return user


def _credential(credential_type: CredentialType, stored_config: dict) -> MagicMock:
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.name = f"{credential_type.value} credential"
    credential.type = credential_type
    credential.owner_id = OWNER_ID
    credential.encrypted_config = encrypt_config(stored_config)
    return credential


class SharedCredentialTestOverrideTests(unittest.IsolatedAsyncioTestCase):
    """A non-owner may not choose where a shared credential's secret is sent."""

    async def _run(self, credential, user, request):
        with patch(
            "app.api.credentials._get_accessible_credential",
            AsyncMock(return_value=credential),
        ):
            return await run_credential_connection_test(request, current_user=user, db=MagicMock())

    async def test_direct_share_cannot_override_the_destination(self) -> None:
        for credential_type, stored, override, service_path in OVERRIDE_CASES:
            with self.subTest(credential_type=credential_type.value):
                credential = _credential(credential_type, stored)
                with patch(service_path) as service:
                    with self.assertRaises(HTTPException) as ctx:
                        await self._run(
                            credential,
                            _user(COLLABORATOR_ID),
                            CredentialTestRequest(
                                type=credential_type,
                                credential_id=credential.id,
                                config=override,
                            ),
                        )
                self.assertEqual(ctx.exception.status_code, 403)
                self.assertIn("owner", ctx.exception.detail)
                service.assert_not_called()

    async def test_team_share_cannot_override_the_destination(self) -> None:
        credential = _credential(CredentialType.jira, OVERRIDE_CASES[0][1])
        team_member = _user(uuid.uuid4())
        with patch("app.services.jira_service.JiraService") as service:
            with self.assertRaises(HTTPException) as ctx:
                await self._run(
                    credential,
                    team_member,
                    CredentialTestRequest(
                        type=CredentialType.jira,
                        credential_id=credential.id,
                        config={"base_url": "https://collector.attacker.example"},
                    ),
                )
        self.assertEqual(ctx.exception.status_code, 403)
        service.assert_not_called()

    async def test_non_owner_may_still_test_the_stored_configuration(self) -> None:
        credential = _credential(CredentialType.jira, OVERRIDE_CASES[0][1])
        with patch("app.services.jira_service.JiraService") as service:
            service.return_value.test_connection.return_value = {"displayName": "Owner"}
            response = await self._run(
                credential,
                _user(COLLABORATOR_ID),
                CredentialTestRequest(
                    type=CredentialType.jira,
                    credential_id=credential.id,
                    config=None,
                ),
            )
        self.assertTrue(response.success)
        self.assertEqual(service.call_args.args[0]["base_url"], "https://owner.atlassian.net")

    async def test_owner_may_still_override_while_editing(self) -> None:
        credential = _credential(CredentialType.jira, OVERRIDE_CASES[0][1])
        with patch("app.services.jira_service.JiraService") as service:
            service.return_value.test_connection.return_value = {"displayName": "Owner"}
            response = await self._run(
                credential,
                _user(OWNER_ID),
                CredentialTestRequest(
                    type=CredentialType.jira,
                    credential_id=credential.id,
                    config={"base_url": "https://owner-new.atlassian.net"},
                ),
            )
        self.assertTrue(response.success)
        self.assertEqual(service.call_args.args[0]["base_url"], "https://owner-new.atlassian.net")

    async def test_stored_secret_never_reaches_a_non_owner_destination(self) -> None:
        """The owner's token must not appear in any client the request builds."""
        credential = _credential(CredentialType.jira, OVERRIDE_CASES[0][1])
        with patch("app.services.jira_service.JiraService") as service:
            with self.assertRaises(HTTPException):
                await self._run(
                    credential,
                    _user(COLLABORATOR_ID),
                    CredentialTestRequest(
                        type=CredentialType.jira,
                        credential_id=credential.id,
                        config={"base_url": "https://collector.attacker.example"},
                    ),
                )
        self.assertEqual(service.call_args_list, [])


class ClickHouseEgressGuardTests(unittest.TestCase):
    """ClickHouse reached its host without ever consulting the egress guard."""

    def setUp(self) -> None:
        patcher = patch("app.services.ssrf_guard.settings.http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_non_public_hosts_are_refused_before_the_client_is_built(self) -> None:
        for host in ("127.0.0.1", "169.254.169.254", "10.0.0.5"):
            with self.subTest(host=host):
                service = ClickHouseService({"host": host, "password": "OWNER-PASSWORD"})
                with patch("app.services.clickhouse_pool.get_clickhouse_client") as get_client:
                    with self.assertRaises(SsrfBlockedError):
                        service._client()
                get_client.assert_not_called()

    def test_scheme_prefixed_hosts_are_unwrapped_before_the_check(self) -> None:
        service = ClickHouseService({"host": "https://127.0.0.1:8443", "password": "OWNER-PW"})
        self.assertEqual(service._connection_url(), "https://127.0.0.1:8443")
        with self.assertRaises(SsrfBlockedError):
            service._client()

    def test_connection_url_renders_scheme_and_port(self) -> None:
        service = ClickHouseService(
            {"host": "owner.clickhouse.cloud", "secure": True, "port": 8443}
        )
        self.assertEqual(service._connection_url(), "https://owner.clickhouse.cloud:8443")

    def test_public_hosts_reach_the_pool(self) -> None:
        service = ClickHouseService({"host": "owner.clickhouse.cloud", "port": 8123})
        with patch("app.services.clickhouse_service.guard_http_url") as guard:
            with patch("app.services.clickhouse_pool.get_clickhouse_client") as get_client:
                service._client()
        guard.assert_called_once_with(
            "http://owner.clickhouse.cloud:8123", "ClickHouse credential host"
        )
        get_client.assert_called_once()


if __name__ == "__main__":
    unittest.main()
