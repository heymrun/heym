import unittest
import uuid
from unittest import mock

from fastapi import HTTPException

from app.api.credentials import (
    get_masked_value,
    get_public_credential_fields,
    merge_credential_config_for_update,
    validate_credential_config,
)
from app.db.models import CredentialType


def _config() -> dict:
    return {
        "decision_credential_id": str(uuid.uuid4()),
        "decision_model": "jev-latest",
        "routing_instructions": "Pick the cheapest model that works.",
        "options": [
            {
                "id": "opt_1",
                "label": "Fast",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-4o-mini",
                "criteria": "Short questions.",
                "is_default": True,
            },
            {
                "id": "opt_2",
                "label": "Deep",
                "credential_id": str(uuid.uuid4()),
                "model": "gpt-5",
                "criteria": "Hard questions.",
            },
        ],
    }


class TestRouterConfigValidation(unittest.TestCase):
    def test_a_valid_config_passes_shape_validation(self) -> None:
        validate_credential_config(CredentialType.model_router, _config())

    def test_a_shape_error_becomes_a_400(self) -> None:
        raw = _config()
        raw["options"] = raw["options"][:1]
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.model_router, raw)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("at least two", ctx.exception.detail)


class TestRouterMaskingAndPublicFields(unittest.TestCase):
    def test_masked_value_is_none_because_there_is_no_secret(self) -> None:
        self.assertIsNone(get_masked_value(CredentialType.model_router, _config()))

    def test_public_fields_summarise_the_router(self) -> None:
        fields = get_public_credential_fields(CredentialType.model_router, _config())
        self.assertEqual(fields["decision_model"], "jev-latest")
        self.assertEqual(fields["option_count"], "2")

    def test_public_fields_never_leak_a_referenced_key(self) -> None:
        raw = _config()
        raw["options"][0]["api_key"] = "sk-should-not-be-here"
        fields = get_public_credential_fields(CredentialType.model_router, raw)
        self.assertNotIn("sk-should-not-be-here", str(fields))


class TestRouterUpdateMerge(unittest.TestCase):
    def test_update_replaces_the_config_wholesale(self) -> None:
        existing = _config()
        incoming = _config()
        incoming["options"].pop()
        merged = merge_credential_config_for_update(CredentialType.model_router, existing, incoming)
        self.assertEqual(merged, incoming)
        self.assertEqual(len(merged["options"]), 1)


class TestRouterReferenceValidation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner = mock.Mock()
        self.owner.id = uuid.uuid4()
        self.config = _config()

    def _credential(self, cred_type: CredentialType) -> mock.Mock:
        credential = mock.Mock()
        credential.type = cred_type
        credential.name = "ref"
        return credential

    async def _run(self, lookups: dict) -> None:
        from app.api import credentials as credentials_api

        async def fake_lookup(db: object, credential_id: uuid.UUID, user: object) -> object:
            return lookups.get(str(credential_id))

        with mock.patch.object(
            credentials_api, "_get_accessible_credential", side_effect=fake_lookup
        ):
            await credentials_api.validate_model_router_references(
                mock.AsyncMock(), self.config, self.owner
            )

    async def test_passes_when_every_reference_resolves(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.google),
        }
        await self._run(lookups)

    async def test_unreachable_decision_credential_is_a_400(self) -> None:
        lookups = {
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.openai),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("decision model credential", ctx.exception.detail)

    async def test_wrong_decision_credential_type_is_a_400(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.openai),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("decision model credential", ctx.exception.detail)

    async def test_unreachable_option_credential_is_a_400_naming_the_option(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("Deep", ctx.exception.detail)

    async def test_an_option_pointing_at_another_router_is_a_400(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(
                CredentialType.model_router
            ),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("another Model Router", ctx.exception.detail)

    async def test_an_option_pointing_at_a_slack_credential_is_a_400(self) -> None:
        lookups = {
            self.config["decision_credential_id"]: self._credential(CredentialType.decision),
            self.config["options"][0]["credential_id"]: self._credential(CredentialType.openai),
            self.config["options"][1]["credential_id"]: self._credential(CredentialType.slack),
        }
        with self.assertRaises(HTTPException) as ctx:
            await self._run(lookups)
        self.assertIn("Deep", ctx.exception.detail)


class TestRouterSyntheticModel(unittest.TestCase):
    def test_auto_model_row_rejects_batch_and_responses(self) -> None:
        from app.api.credentials import build_model_router_models

        models = build_model_router_models()
        self.assertEqual(len(models), 1)
        auto = models[0]
        self.assertEqual(auto.id, "auto")
        self.assertEqual(auto.name, "Auto")
        self.assertFalse(auto.is_reasoning)
        self.assertFalse(auto.supports_batch)
        self.assertFalse(auto.supports_responses)
        self.assertIn("Responses API", auto.responses_support_reason)
        self.assertIn("Batch", auto.batch_support_reason)
        self.assertIsNone(auto.context_window)


class TestRouterInLlmList(unittest.TestCase):
    def test_llm_listing_includes_the_router_type(self) -> None:
        import inspect

        from app.api import credentials as credentials_api

        source = inspect.getsource(credentials_api.list_llm_credentials)
        self.assertIn("CredentialType.model_router", source)


class TestRouterConfigReadSchema(unittest.TestCase):
    def test_response_model_mirrors_the_stored_config(self) -> None:
        from app.models.schemas import ModelRouterConfigResponse

        response = ModelRouterConfigResponse(**_config())
        self.assertEqual(response.decision_model, "jev-latest")
        self.assertEqual(len(response.options), 2)
        self.assertEqual(response.options[0].label, "Fast")
        self.assertTrue(response.options[0].is_default)
        self.assertFalse(response.options[1].is_default)

    def test_the_response_model_has_no_key_field_to_fill(self) -> None:
        from app.models.schemas import ModelRouterConfigResponse, ModelRouterOptionResponse

        self.assertNotIn("api_key", ModelRouterConfigResponse.model_fields)
        self.assertNotIn("api_key", ModelRouterOptionResponse.model_fields)

    def test_endpoint_exists_and_is_owner_scoped(self) -> None:
        import inspect

        from app.api import credentials as credentials_api

        source = inspect.getsource(credentials_api.get_model_router_config)
        self.assertIn("_get_accessible_credential", source)
        self.assertIn("CredentialType.model_router", source)


if __name__ == "__main__":
    unittest.main()
