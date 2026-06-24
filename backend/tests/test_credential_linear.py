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

    def test_masked_value_hides_api_key(self) -> None:
        masked = get_masked_value(CredentialType.linear, {"api_key": "lin_api_secret"})
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, "lin_api_secret")

    def test_update_preserves_existing_api_key_when_form_is_blank(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.linear,
            {"api_key": "lin_api_old"},
            {"api_key": ""},
        )
        self.assertEqual(merged["api_key"], "lin_api_old")

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
