"""Exchange Server sign-in on the Outlook credentials keeps its password owner-side.

The stored password never reaches a response, a `$credentials` value or another server or
user name; a refused OAuth connect and a K8s Secret in this mode behave as documented.
"""

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    get_public_credential_fields,
    merge_credential_config_for_update,
    run_credential_connection_test,
    validate_credential_config,
)
from app.db.models import CredentialType
from app.models.schemas import CredentialTestRequest
from app.services.credential_context import credential_context_value
from app.services.k8s_credentials.secret import parse_secret

OWNER_ID = uuid.uuid4()
EWS = {
    "auth_mode": "ews",
    "ews_email": "ada@heym.run",
    "ews_username": "HEYM\\ada",
    "ews_password": "STORED-PASSWORD",
    "ews_server": "mail.heym.run",
}
TYPES = (CredentialType.outlook, CredentialType.outlook_calendar)


class ExchangeCredentialFieldsTests(unittest.TestCase):
    def test_masked_value_and_public_fields_never_show_the_password(self) -> None:
        for credential_type in TYPES:
            with self.subTest(credential_type=credential_type):
                self.assertEqual(
                    get_masked_value(credential_type, EWS), "Exchange Server (ada@heym.run)"
                )
                public = get_public_credential_fields(credential_type, EWS)
                self.assertEqual(public["auth_mode"], "ews")
                self.assertEqual(public["ews_username"], "HEYM\\ada")
                self.assertEqual(public["can_send"], "true")
                self.assertNotIn("STORED-PASSWORD", str(public))

    def test_saving_requires_a_complete_sign_in_but_no_oauth_client(self) -> None:
        for credential_type in TYPES:
            validate_credential_config(credential_type, EWS)
            with self.assertRaises(HTTPException):
                validate_credential_config(credential_type, {**EWS, "ews_password": ""})
            with self.assertRaises(HTTPException):
                validate_credential_config(credential_type, {**EWS, "ews_server": "http://x.com"})

    def test_microsoft_account_credentials_keep_their_oauth_rules(self) -> None:
        with self.assertRaises(HTTPException):
            validate_credential_config(CredentialType.outlook, {"auth_mode": "oauth"})


class ExchangeCredentialUpdateTests(unittest.TestCase):
    def _merge(self, existing: dict, incoming: dict) -> dict:
        return merge_credential_config_for_update(CredentialType.outlook, existing, incoming)

    def test_a_blank_password_keeps_the_stored_one_for_the_same_login(self) -> None:
        merged = self._merge(EWS, {**EWS, "ews_password": "", "ews_email": "new@heym.run"})
        self.assertEqual(merged["ews_password"], "STORED-PASSWORD")
        self.assertEqual(merged["ews_email"], "new@heym.run")

    def test_the_stored_password_never_follows_another_server_or_user(self) -> None:
        for change in ({"ews_server": "attacker.example"}, {"ews_username": "HEYM\\other"}):
            with self.subTest(change=change):
                merged = self._merge(EWS, {**EWS, "ews_password": "", **change})
                self.assertEqual(merged["ews_password"], "")
                with self.assertRaises(HTTPException):
                    validate_credential_config(CredentialType.outlook, merged)

    def test_switching_from_oauth_drops_the_tokens(self) -> None:
        oauth = {"client_id": "c", "client_secret": "s", "refresh_token": "r", "access_token": "a"}
        merged = self._merge(oauth, EWS)
        self.assertEqual(
            set(merged), {"auth_mode", "ews_email", "ews_username", "ews_server", "ews_password"}
        )


class ExchangeConnectionTestRouteTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, config: dict, credential: object | None = None, user_id=OWNER_ID):  # noqa: ANN001, ANN202
        request = CredentialTestRequest(
            type=CredentialType.outlook,
            config=config,
            credential_id=getattr(credential, "id", None),
        )
        with (
            patch(
                "app.api.credentials._get_accessible_credential",
                AsyncMock(return_value=credential),
            ),
            patch("app.api.credentials.decrypt_config", return_value=dict(EWS)),
            patch(
                "app.services.exchange_server.connection.check_connection",
                return_value="Connected to ada@heym.run on mail.heym.run",
            ) as check,
        ):
            response = await run_credential_connection_test(
                request, current_user=MagicMock(id=user_id), db=MagicMock()
            )
        return response, check

    async def test_the_entered_sign_in_is_tested(self) -> None:
        response, check = await self._run(EWS)
        self.assertTrue(response.success)
        self.assertEqual(check.call_args.args[0]["ews_password"], "STORED-PASSWORD")

    async def test_editing_tests_the_stored_password_only_for_the_same_login(self) -> None:
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Exchange",
            type=CredentialType.outlook,
            owner_id=OWNER_ID,
            encrypted_config="x",
        )
        response, check = await self._run({**EWS, "ews_password": ""}, credential)
        self.assertTrue(response.success)
        self.assertEqual(check.call_args.args[0]["ews_password"], "STORED-PASSWORD")

        with self.assertRaises(HTTPException) as caught:
            await self._run(
                {**EWS, "ews_password": "", "ews_server": "attacker.example"}, credential
            )
        self.assertEqual(caught.exception.status_code, 400)

    async def test_a_collaborator_cannot_point_the_owners_password_elsewhere(self) -> None:
        credential = SimpleNamespace(
            id=uuid.uuid4(),
            name="Exchange",
            type=CredentialType.outlook,
            owner_id=OWNER_ID,
            encrypted_config="x",
        )
        with patch("app.api.credentials.audit"), self.assertRaises(HTTPException) as caught:
            await self._run({**EWS, "ews_server": "attacker.example"}, credential, uuid.uuid4())
        self.assertEqual(caught.exception.status_code, 403)

    async def test_a_microsoft_account_has_no_connection_test(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            await self._run({"client_id": "c", "client_secret": "s"})
        self.assertEqual(caught.exception.status_code, 400)


class ExchangeCredentialUseTests(unittest.IsolatedAsyncioTestCase):
    async def test_credentials_context_hands_out_nothing_for_exchange(self) -> None:
        credential = SimpleNamespace(id=uuid.uuid4(), type=CredentialType.outlook)
        self.assertIsNone(await credential_context_value(credential, EWS))

    async def test_oauth_connect_refuses_an_exchange_credential(self) -> None:
        from app.api import outlook_calendar_oauth, outlook_oauth

        for module in (outlook_oauth, outlook_calendar_oauth):
            with self.subTest(module=module.__name__):
                db = AsyncMock()
                db.execute.return_value.scalar_one_or_none = MagicMock(
                    return_value=MagicMock(id=uuid.uuid4())
                )
                with (
                    patch.object(module, "decrypt_config", return_value=dict(EWS)),
                    self.assertRaises(HTTPException) as caught,
                ):
                    await module.authorize(
                        module.AuthorizeRequest(credential_id=uuid.uuid4()),
                        MagicMock(),
                        MagicMock(id=OWNER_ID),
                        db,
                    )
                self.assertEqual(caught.exception.status_code, 400)
                self.assertIn("Exchange Server", caught.exception.detail)

    async def test_pickers_list_exchange_folders_and_the_own_address(self) -> None:
        from app.api import outlook as outlook_api

        credential = SimpleNamespace(type=CredentialType.outlook, encrypted_config="x")
        user = SimpleNamespace(id=OWNER_ID)
        with (
            patch.object(
                outlook_api, "get_accessible_credential", AsyncMock(return_value=credential)
            ),
            patch.object(outlook_api, "decrypt_config", return_value=dict(EWS)),
            patch.object(
                outlook_api.EwsMailbox, "list_folders", return_value=[{"id": "f", "path": "Inbox"}]
            ),
        ):
            folders = await outlook_api.list_folders(uuid.uuid4(), user, AsyncMock())
            addresses = await outlook_api.list_addresses(uuid.uuid4(), user, AsyncMock())
        self.assertEqual([folder.path for folder in folders.folders], ["Inbox"])
        self.assertEqual(
            [(a.email, a.is_primary) for a in addresses.addresses], [("ada@heym.run", True)]
        )


class ExchangeKubernetesSecretTests(unittest.TestCase):
    def _secret(self, config: dict, credential_type: str = "outlook") -> dict:
        import base64
        import json

        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        return {
            "metadata": {
                "name": "outlook",
                "namespace": "heym",
                "labels": {"heym.run/credential": "true"},
                "annotations": {
                    "heym.run/type": credential_type,
                    "heym.run/owner": "owner@example.com",
                    "heym.run/name": "Outlook",
                },
            },
            "data": {"config.json": encoded},
        }

    def test_an_exchange_sign_in_can_be_a_read_only_secret_and_oauth_cannot(self) -> None:
        for credential_type in ("outlook", "outlook_calendar"):
            with self.subTest(credential_type=credential_type):
                self.assertIsNone(parse_secret(self._secret(EWS, credential_type)).problem)
                oauth = parse_secret(
                    self._secret({"client_id": "c", "client_secret": "s"}, credential_type)
                )
                self.assertIn("can't be read-only", oauth.problem or "")


if __name__ == "__main__":
    unittest.main()
