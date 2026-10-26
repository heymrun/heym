"""list_credential_models: the model list the credential route and the chat tools share."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.credentials import build_model_router_models, list_credential_models
from app.db.models import CredentialType
from app.models.schemas import LLMModel


class CredentialModelsListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_type_without_models_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            await list_credential_models(
                SimpleNamespace(type=CredentialType.slack, encrypted_config="x")
            )

    async def test_a_model_router_lists_its_pseudo_model(self) -> None:
        models = await list_credential_models(
            SimpleNamespace(type=CredentialType.model_router, encrypted_config="x")
        )
        self.assertEqual(models, build_model_router_models())

    async def test_known_context_windows_are_filled_in(self) -> None:
        fetched = [LLMModel(id="gpt-4o-2024-08-06", name="gpt-4o")]
        with (
            patch("app.api.credentials.decrypt_config", return_value={"api_key": "k"}),
            patch("app.services.llm_provider.fetch_models", AsyncMock(return_value=fetched)),
        ):
            models = await list_credential_models(
                SimpleNamespace(type=CredentialType.openai, encrypted_config="x")
            )
        self.assertEqual(models[0].context_window, 128_000)


if __name__ == "__main__":
    unittest.main()
