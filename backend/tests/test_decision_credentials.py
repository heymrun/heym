"""Validation, masking, exposure and listing for the decision credential."""

import unittest
import unittest.mock as mock
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.credentials import (
    _list_credentials_of_types,
    _test_decision_endpoint,
    get_masked_value,
    get_public_credential_fields,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.models.schemas import CredentialType
from app.services.decision_models import DecisionProviderError


class DecisionCredentialValidationTests(unittest.TestCase):
    def test_base_url_is_required(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.decision, {"api_key": "k"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("base_url", str(ctx.exception.detail))

    def test_api_key_is_optional(self) -> None:
        validate_credential_config(CredentialType.decision, {"base_url": "https://api.typesafe.ai"})

    def test_base_url_must_be_http(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.decision, {"base_url": "ftp://x.test"})
        self.assertEqual(ctx.exception.status_code, 400)


class DecisionCredentialExposureTests(unittest.TestCase):
    def test_masked_value_hides_the_api_key(self) -> None:
        masked = get_masked_value(
            CredentialType.decision,
            {"base_url": "https://api.typesafe.ai", "api_key": "sk-abcdef123456"},
        )
        self.assertIsNotNone(masked)
        self.assertNotIn("abcdef123456", str(masked))

    def test_masked_value_falls_back_to_the_host_without_a_key(self) -> None:
        masked = get_masked_value(CredentialType.decision, {"base_url": "https://api.typesafe.ai"})
        self.assertEqual(masked, "api.typesafe.ai")

    def test_public_fields_expose_base_url_but_never_the_key(self) -> None:
        fields = get_public_credential_fields(
            CredentialType.decision,
            {"base_url": "https://api.typesafe.ai", "api_key": "sk-abcdef123456"},
        )
        self.assertEqual(fields.get("base_url"), "https://api.typesafe.ai")
        self.assertNotIn("api_key", fields)


class DecisionCredentialUpdateMergeTests(unittest.TestCase):
    """A blank API key input must never overwrite the stored one."""

    STORED = {"base_url": "https://api.typesafe.ai", "api_key": "sk-stored"}

    def test_a_blank_api_key_keeps_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.decision,
            self.STORED,
            {"base_url": "https://api.typesafe.ai", "api_key": ""},
        )
        self.assertEqual(merged["api_key"], "sk-stored")

    def test_a_whitespace_api_key_keeps_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.decision,
            self.STORED,
            {"base_url": "https://api.typesafe.ai", "api_key": "   "},
        )
        self.assertEqual(merged["api_key"], "sk-stored")

    def test_a_retyped_api_key_replaces_the_stored_one(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.decision,
            self.STORED,
            {"base_url": "https://api.typesafe.ai", "api_key": "sk-new"},
        )
        self.assertEqual(merged["api_key"], "sk-new")

    def test_the_base_url_is_always_taken_from_the_payload(self) -> None:
        merged = merge_credential_config_for_update(
            CredentialType.decision,
            self.STORED,
            {"base_url": "http://gw.internal:8765", "api_key": ""},
        )
        self.assertEqual(merged["base_url"], "http://gw.internal:8765")


class DecisionCredentialConnectionTests(unittest.IsolatedAsyncioTestCase):
    CONFIG = {"base_url": "https://api.typesafe.ai", "api_key": "sk-test"}

    async def test_a_successful_probe_reports_success(self) -> None:
        with mock.patch(
            "app.api.credentials.call_decision_model",
            return_value={"answers": {"probe": {"type": "noul", "noul": 0.5}}},
        ):
            result = await _test_decision_endpoint(self.CONFIG, model="jev-latest")
        self.assertTrue(result.success)

    async def test_a_rejected_key_reports_the_reason(self) -> None:
        with mock.patch(
            "app.api.credentials.call_decision_model",
            side_effect=DecisionProviderError("Decision model rejected the API key"),
        ):
            result = await _test_decision_endpoint(self.CONFIG, model="jev-latest")
        self.assertFalse(result.success)
        self.assertIn("API key", result.message)

    async def test_an_unreachable_host_is_reported_not_raised(self) -> None:
        with mock.patch(
            "app.api.credentials.call_decision_model",
            side_effect=RuntimeError("boom"),
        ):
            result = await _test_decision_endpoint(self.CONFIG, model="jev-latest")
        self.assertFalse(result.success)
        self.assertIn("Connection failed", result.message)

    async def test_the_probe_sends_exactly_one_question(self) -> None:
        with mock.patch(
            "app.api.credentials.call_decision_model", return_value={"answers": {}}
        ) as call:
            await _test_decision_endpoint(self.CONFIG, model="jev-latest")
        body = call.call_args.kwargs["body"]
        self.assertEqual(len(body["questions"]), 1)
        self.assertEqual(body["model"], "jev-latest")

    async def test_a_blank_model_falls_back_to_a_default(self) -> None:
        with mock.patch(
            "app.api.credentials.call_decision_model", return_value={"answers": {}}
        ) as call:
            await _test_decision_endpoint(self.CONFIG, model="")
        self.assertEqual(call.call_args.kwargs["body"]["model"], "jev-latest")


class _Cred:
    """A credential row that decrypt_config can be pointed away from."""

    def __init__(self, name: str, cred_id: uuid.UUID) -> None:
        self.id = cred_id
        self.name = name
        self.type = CredentialType.decision
        self.encrypted_config = "encrypted"
        self.created_at = datetime(2026, 9, 21, tzinfo=timezone.utc)


def _scalars(rows: list[object]) -> mock.MagicMock:
    result = mock.MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result


def _rows(rows: list[tuple]) -> mock.MagicMock:
    result = mock.MagicMock()
    result.all.return_value = rows
    return result


class ListCredentialsOfTypesTests(unittest.IsolatedAsyncioTestCase):
    """Guards the sharing semantics shared by the llm and decision listings."""

    async def _list(self, owned, shared, team) -> list:
        db = mock.AsyncMock()
        db.execute.side_effect = [_scalars(owned), _rows(shared), _rows(team)]
        user = mock.MagicMock()
        user.id = uuid.uuid4()
        with mock.patch(
            "app.api.credentials.decrypt_config",
            return_value={"base_url": "https://api.typesafe.ai", "api_key": "sk-secret"},
        ):
            return await _list_credentials_of_types(db, user, [CredentialType.decision])

    async def test_owned_credentials_are_not_marked_shared(self) -> None:
        cred = _Cred("Mine", uuid.uuid4())
        entries = await self._list([cred], [], [])
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].is_shared)
        self.assertIsNone(entries[0].shared_by)

    async def test_a_directly_shared_credential_names_its_owner(self) -> None:
        cred = _Cred("Theirs", uuid.uuid4())
        entries = await self._list([], [(cred, "owner@example.com")], [])
        self.assertTrue(entries[0].is_shared)
        self.assertEqual(entries[0].shared_by, "owner@example.com")

    async def test_a_team_shared_credential_names_its_team(self) -> None:
        cred = _Cred("Team", uuid.uuid4())
        entries = await self._list([], [], [(cred, "Platform")])
        self.assertTrue(entries[0].is_shared)
        self.assertEqual(entries[0].shared_by_team, "Platform")

    async def test_ownership_outranks_a_share_and_never_repeats(self) -> None:
        cred = _Cred("Both", uuid.uuid4())
        entries = await self._list([cred], [(cred, "owner@example.com")], [(cred, "Platform")])
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].is_shared)

    async def test_the_api_key_never_reaches_the_listing(self) -> None:
        cred = _Cred("Mine", uuid.uuid4())
        entries = await self._list([cred], [], [])
        self.assertNotIn("sk-secret", str(entries[0].model_dump()))


if __name__ == "__main__":
    unittest.main()
