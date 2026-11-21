"""Regression tests for empty/null image generation and editing responses."""

import unittest
from unittest.mock import MagicMock, patch

from openai.types import Image, ImagesResponse

from app.db.models import CredentialType
from app.services.llm_service import (
    LLMService,
    execute_image_edit,
    execute_image_generation,
)
from app.services.workflow_executor import WorkflowExecutor

_SAMPLE_PIXEL_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class TestLLMImageEmptyResponse(unittest.IsolatedAsyncioTestCase):
    """Ensure empty or null provider image responses raise controlled ValueError and record traces."""

    async def asyncSetUp(self) -> None:
        self.service = LLMService(CredentialType.openai, "sk-test", None)
        self.mock_client = MagicMock()
        self.service._get_client = MagicMock(return_value=(self.mock_client, "OpenAI"))  # type: ignore[method-assign]

    async def test_image_generation_valid_response(self) -> None:
        """Valid image response preserves expected successful output fields."""
        self.mock_client.images.generate.return_value = ImagesResponse(
            created=1710000000,
            data=[Image(b64_json="aGVsbG8td29ybGQ=", revised_prompt="a cute fluffy cat")],
        )

        result = await self.service._execute_openai_image_generation(
            model="dall-e-3",
            prompt="a cat",
        )

        self.assertEqual(result["image"], "data:image/png;base64,aGVsbG8td29ybGQ=")
        self.assertEqual(result["text"], "a cat")
        self.assertEqual(result["model"], "dall-e-3")
        self.assertEqual(result["revised_prompt"], "a cute fluffy cat")
        self.assertNotIn("error", result)
        self.assertIsInstance(result["elapsed_ms"], (int, float))

    async def test_image_generation_data_none(self) -> None:
        """Image generation with data=None raises ValueError and records error trace."""
        self.mock_client.images.generate.return_value = ImagesResponse(
            created=1710000000,
            data=None,
        )

        with patch.object(self.service, "_record_trace") as mock_trace:
            with self.assertRaisesRegex(ValueError, "No image returned by provider"):
                await self.service.execute_image_generation(
                    model="dall-e-3",
                    prompt="a cat",
                )
            mock_trace.assert_called_once()
            call_kwargs = mock_trace.call_args.kwargs
            self.assertEqual(call_kwargs["request_type"], "images.generate")
            self.assertEqual(call_kwargs["error"], "No image returned by provider")

    async def test_image_generation_data_empty(self) -> None:
        """Image generation with data=[] raises ValueError."""
        self.mock_client.images.generate.return_value = ImagesResponse(
            created=1710000000,
            data=[],
        )

        with self.assertRaisesRegex(ValueError, "No image returned by provider"):
            await self.service._execute_openai_image_generation(
                model="dall-e-3",
                prompt="a cat",
            )

    async def test_image_edit_valid_response(self) -> None:
        """Valid image edit response preserves expected successful output fields."""
        self.mock_client.images.edit.return_value = ImagesResponse(
            created=1710000000,
            data=[Image(b64_json="ZWRpdGVkLWltYWdl", revised_prompt="prompt revised")],
        )

        result = await self.service.execute_image_edit(
            model="dall-e-2",
            prompt="add sunglasses",
            image_input=_SAMPLE_PIXEL_DATA_URL,
        )

        self.assertEqual(result["image"], "data:image/png;base64,ZWRpdGVkLWltYWdl")
        self.assertEqual(result["text"], "add sunglasses")
        self.assertEqual(result["model"], "dall-e-2")
        self.assertEqual(result["revised_prompt"], "prompt revised")
        self.assertNotIn("error", result)
        self.assertIsInstance(result["elapsed_ms"], (int, float))

    async def test_image_edit_data_none(self) -> None:
        """Image edit with data=None raises ValueError and records error trace."""
        self.mock_client.images.edit.return_value = ImagesResponse(
            created=1710000000,
            data=None,
        )

        with patch.object(self.service, "_record_trace") as mock_trace:
            with self.assertRaisesRegex(ValueError, "No image returned by provider"):
                await self.service.execute_image_edit(
                    model="dall-e-2",
                    prompt="add sunglasses",
                    image_input=_SAMPLE_PIXEL_DATA_URL,
                )
            mock_trace.assert_called_once()
            call_kwargs = mock_trace.call_args.kwargs
            self.assertEqual(call_kwargs["request_type"], "images.edit")
            self.assertEqual(call_kwargs["error"], "No image returned by provider")

    async def test_image_edit_data_empty(self) -> None:
        """Image edit with data=[] raises ValueError."""
        self.mock_client.images.edit.return_value = ImagesResponse(
            created=1710000000,
            data=[],
        )

        with self.assertRaisesRegex(ValueError, "No image returned by provider"):
            await self.service.execute_image_edit(
                model="dall-e-2",
                prompt="add sunglasses",
                image_input=_SAMPLE_PIXEL_DATA_URL,
            )

    async def test_public_execute_image_generation_empty_data(self) -> None:
        """Public execute_image_generation wrapper raises ValueError on empty data."""
        mock_client = MagicMock()
        mock_client.images.generate.return_value = ImagesResponse(created=1710000000, data=[])
        with patch("app.services.llm_service.create_openai_client", return_value=mock_client):
            with self.assertRaisesRegex(ValueError, "No image returned by provider"):
                await execute_image_generation(
                    credential_type=CredentialType.openai.value,
                    api_key="sk-test",
                    base_url=None,
                    model="dall-e-3",
                    prompt="a bird",
                )

    async def test_public_execute_image_edit_empty_data(self) -> None:
        """Public execute_image_edit wrapper raises ValueError on empty data."""
        mock_client = MagicMock()
        mock_client.images.edit.return_value = ImagesResponse(created=1710000000, data=None)
        with patch("app.services.llm_service.create_openai_client", return_value=mock_client):
            with self.assertRaisesRegex(ValueError, "No image returned by provider"):
                await execute_image_edit(
                    credential_type=CredentialType.openai.value,
                    api_key="sk-test",
                    base_url=None,
                    model="dall-e-2",
                    prompt="remove background",
                    image_input=_SAMPLE_PIXEL_DATA_URL,
                )


class TestWorkflowExecutorImageErrorPropagation(unittest.TestCase):
    """Ensure image errors propagate cleanly through workflow node execution and support fallbacks."""

    def test_workflow_executor_handles_empty_image_response(self) -> None:
        executor = WorkflowExecutor(nodes=[], edges=[])
        mock_credential = MagicMock()
        mock_credential.type = CredentialType.openai
        mock_credential.name = "Test OpenAI"
        mock_credential.encrypted_config = b"dummy"

        mock_client = MagicMock()
        mock_client.images.generate.return_value = ImagesResponse(created=1710000000, data=[])

        with (
            patch.object(executor, "_get_accessible_credential", return_value=mock_credential),
            patch("app.services.encryption.decrypt_config", return_value={"api_key": "sk-test"}),
            patch("app.services.llm_service.create_openai_client", return_value=mock_client),
        ):
            out = executor._execute_llm_node(
                credential_id="cred-1",
                node_id="node-1",
                model="dall-e-3",
                system_instruction=None,
                user_message="a landscape",
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                json_output_enabled=False,
                json_output_schema=None,
                image_input=None,
                output_type="image",
            )

        self.assertEqual(out["error"], "No image returned by provider")
        self.assertEqual(out["model"], "dall-e-3")
        self.assertNotIn("image", out)

    def test_workflow_executor_image_fallback_when_primary_returns_empty_data(self) -> None:
        """When primary provider returns empty data, fallback credential/model runs and succeeds."""
        executor = WorkflowExecutor(nodes=[], edges=[])
        primary_cred = MagicMock()
        primary_cred.type = CredentialType.openai
        primary_cred.name = "Primary OpenAI"
        primary_cred.encrypted_config = b"primary_dummy"

        fallback_cred = MagicMock()
        fallback_cred.type = CredentialType.openai
        fallback_cred.name = "Fallback OpenAI"
        fallback_cred.encrypted_config = b"fallback_dummy"

        def mock_get_cred(_db: object, cid: str) -> MagicMock:
            if cid == "cred-primary":
                return primary_cred
            return fallback_cred

        primary_client = MagicMock()
        primary_client.images.generate.return_value = ImagesResponse(created=1710000000, data=[])

        fallback_client = MagicMock()
        fallback_client.images.generate.return_value = ImagesResponse(
            created=1710000000,
            data=[Image(b64_json="ZmFsbGJhY2staW1hZ2U=", revised_prompt="fallback prompt")],
        )

        def mock_create_client(*args: object, **kwargs: object) -> MagicMock:
            api_key = kwargs.get("api_key")
            if not api_key and len(args) > 1:
                api_key = args[1]
            if api_key == "sk-primary":
                return primary_client
            return fallback_client

        def mock_decrypt(config: bytes) -> dict[str, str]:
            if config == b"primary_dummy":
                return {"api_key": "sk-primary"}
            return {"api_key": "sk-fallback"}

        with (
            patch.object(executor, "_get_accessible_credential", side_effect=mock_get_cred),
            patch("app.services.encryption.decrypt_config", side_effect=mock_decrypt),
            patch("app.services.llm_service.create_openai_client", side_effect=mock_create_client),
        ):
            out = executor._execute_llm_node(
                credential_id="cred-primary",
                node_id="node-1",
                model="dall-e-3",
                system_instruction=None,
                user_message="a landscape",
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                json_output_enabled=False,
                json_output_schema=None,
                image_input=None,
                output_type="image",
                fallback_credential_id="cred-fallback",
                fallback_model="dall-e-2",
            )

        self.assertNotIn("error", out)
        self.assertTrue(out.get("fallbackUsed"))
        self.assertEqual(out["model"], "dall-e-2")
        self.assertEqual(out["image"], "data:image/png;base64,ZmFsbGJhY2staW1hZ2U=")
        self.assertEqual(out["revised_prompt"], "fallback prompt")


if __name__ == "__main__":
    unittest.main()
