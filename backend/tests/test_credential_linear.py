import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import (
    _merge_linear_test_config,
    get_masked_value,
    merge_credential_config_for_update,
    run_credential_connection_test,
    validate_credential_config,
)
from app.db.models import CredentialType
from app.models.schemas import CredentialTestRequest


class LinearCredentialTests(unittest.TestCase):
    def test_validate_requires_api_key(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(CredentialType.linear, {})
        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("api_key", context.exception.detail)

    def test_validation_accepts_pending_oauth_client(self) -> None:
        validate_credential_config(
            CredentialType.linear,
            {
                "auth_mode": "oauth",
                "client_id": "client",
                "client_secret": "secret",
            },
            allow_pending_oauth=True,
        )

    def test_validation_rejects_pending_oauth_without_allow_flag(self) -> None:
        with self.assertRaises(HTTPException) as context:
            validate_credential_config(
                CredentialType.linear,
                {
                    "auth_mode": "oauth",
                    "client_id": "client",
                    "client_secret": "secret",
                },
            )
        self.assertIn("completed authorization", str(context.exception.detail))

    def test_masked_value_hides_api_key(self) -> None:
        masked = get_masked_value(CredentialType.linear, {"api_key": "lin_api_secret"})
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, "lin_api_secret")

    def test_masked_value_marks_oauth_connected(self) -> None:
        self.assertEqual(
            get_masked_value(CredentialType.linear, {"auth_mode": "oauth", "access_token": "x"}),
            "connected",
        )

    def test_masked_value_marks_pending_oauth(self) -> None:
        self.assertEqual(
            get_masked_value(CredentialType.linear, {"auth_mode": "oauth"}),
            "Not connected",
        )

    def test_update_preserves_existing_api_key_when_form_is_blank(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.linear,
            {"api_key": "lin_api_old"},
            {"api_key": ""},
        )
        self.assertEqual(merged["api_key"], "lin_api_old")

    def test_update_switches_between_api_key_and_oauth(self) -> None:
        oauth_config = merge_credential_config_for_update(
            CredentialType.linear,
            {"api_key": "lin_api_old"},
            {"auth_mode": "oauth", "client_id": "client", "client_secret": "secret"},
        )
        self.assertNotIn("api_key", oauth_config)
        self.assertEqual(oauth_config["auth_mode"], "oauth")

        api_config = merge_credential_config_for_update(
            CredentialType.linear,
            {"auth_mode": "oauth", "access_token": "oauth-token"},
            {"auth_mode": "api_key", "api_key": "lin_api_new"},
        )
        self.assertNotIn("access_token", api_config)
        self.assertEqual(api_config["api_key"], "lin_api_new")

    def test_merge_linear_test_config_prefers_inline_key(self) -> None:
        merged = _merge_linear_test_config(
            {"api_key": "lin_api_new"},
            {"api_key": "lin_api_old"},
        )
        self.assertEqual(merged["api_key"], "lin_api_new")

    def test_merge_linear_test_config_preserves_stored_key_when_blank(self) -> None:
        merged = _merge_linear_test_config(
            {"api_key": ""},
            {"api_key": "lin_api_old"},
        )
        self.assertEqual(merged["api_key"], "lin_api_old")

    def test_merge_linear_test_config_preserves_oauth_token(self) -> None:
        merged = _merge_linear_test_config(
            {"auth_mode": "oauth"},
            {"auth_mode": "oauth", "access_token": "oauth-token"},
        )
        self.assertEqual(merged["access_token"], "oauth-token")
        self.assertEqual(merged["auth_mode"], "oauth")


class LinearCredentialConnectionApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_test_connection_returns_success_with_viewer_name(self) -> None:
        current_user = MagicMock(id=uuid.uuid4())
        with patch(
            "app.services.linear_service.LinearService.test_connection",
            return_value={"displayName": "Ada Lovelace"},
        ):
            result = await run_credential_connection_test(
                CredentialTestRequest(
                    type=CredentialType.linear,
                    config={"api_key": "lin_api_test"},
                ),
                current_user=current_user,
                db=AsyncMock(),
            )
        self.assertTrue(result.success)
        self.assertIn("Ada Lovelace", result.message)

    async def test_test_connection_closes_linear_service(self) -> None:
        current_user = MagicMock(id=uuid.uuid4())
        instances = []

        class FakeLinearService:
            def __init__(self, config: dict) -> None:
                self.config = config
                self.close = MagicMock()
                instances.append(self)

            def test_connection(self) -> dict:
                return {"displayName": "Ada Lovelace"}

        with patch("app.services.linear_service.LinearService", FakeLinearService):
            result = await run_credential_connection_test(
                CredentialTestRequest(
                    type=CredentialType.linear,
                    config={"api_key": "lin_api_test"},
                ),
                current_user=current_user,
                db=AsyncMock(),
            )

        self.assertTrue(result.success)
        self.assertEqual(len(instances), 1)
        instances[0].close.assert_called_once()

    async def test_test_connection_returns_failure_message(self) -> None:
        current_user = MagicMock(id=uuid.uuid4())
        with patch(
            "app.services.linear_service.LinearService.test_connection",
            side_effect=ValueError("Linear API error: Not authorized"),
        ):
            result = await run_credential_connection_test(
                CredentialTestRequest(
                    type=CredentialType.linear,
                    config={"api_key": "bad-key"},
                ),
                current_user=current_user,
                db=AsyncMock(),
            )
        self.assertFalse(result.success)
        self.assertIn("Not authorized", result.message)
