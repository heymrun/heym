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
    """Ensure empty or null provider image responses return controlled errors."""

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
        """Image generation with data=None returns a controlled error dictionary."""
        self.mock_client.images.generate.return_value = ImagesResponse(
            created=1710000000,
            data=None,
        )

        result = await self.service._execute_openai_image_generation(
            model="dall-e-3",
            prompt="a cat",
        )

        self.assertEqual(result["image"], "")
        self.assertEqual(result["text"], "a cat")
        self.assertEqual(result["model"], "dall-e-3")
        self.assertIsNone(result.get("revised_prompt"))
        self.assertEqual(result["error"], "No image returned by provider")
        self.assertIsInstance(result["elapsed_ms"], (int, float))

    async def test_image_generation_data_empty(self) -> None:
        """Image generation with data=[] returns a controlled error dictionary."""
        self.mock_client.images.generate.return_value = ImagesResponse(
            created=1710000000,
            data=[],
        )

        result = await self.service._execute_openai_image_generation(
            model="dall-e-3",
            prompt="a cat",
        )

        self.assertEqual(result["image"], "")
        self.assertEqual(result["text"], "a cat")
        self.assertEqual(result["model"], "dall-e-3")
        self.assertIsNone(result.get("revised_prompt"))
        self.assertEqual(result["error"], "No image returned by provider")
        self.assertIsInstance(result["elapsed_ms"], (int, float))

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
        """Image edit with data=None returns a controlled error dictionary."""
        self.mock_client.images.edit.return_value = ImagesResponse(
            created=1710000000,
            data=None,
        )

        result = await self.service.execute_image_edit(
            model="dall-e-2",
            prompt="add sunglasses",
            image_input=_SAMPLE_PIXEL_DATA_URL,
        )

        self.assertEqual(result["image"], "")
        self.assertEqual(result["text"], "add sunglasses")
        self.assertEqual(result["model"], "dall-e-2")
        self.assertIsNone(result.get("revised_prompt"))
        self.assertEqual(result["error"], "No image returned by provider")
        self.assertIsInstance(result["elapsed_ms"], (int, float))

    async def test_image_edit_data_empty(self) -> None:
        """Image edit with data=[] returns a controlled error dictionary."""
        self.mock_client.images.edit.return_value = ImagesResponse(
            created=1710000000,
            data=[],
        )

        result = await self.service.execute_image_edit(
            model="dall-e-2",
            prompt="add sunglasses",
            image_input=_SAMPLE_PIXEL_DATA_URL,
        )

        self.assertEqual(result["image"], "")
        self.assertEqual(result["text"], "add sunglasses")
        self.assertEqual(result["model"], "dall-e-2")
        self.assertIsNone(result.get("revised_prompt"))
        self.assertEqual(result["error"], "No image returned by provider")
        self.assertIsInstance(result["elapsed_ms"], (int, float))

    async def test_public_execute_image_generation_empty_data(self) -> None:
        """Public execute_image_generation wrapper returns controlled error."""
        mock_client = MagicMock()
        mock_client.images.generate.return_value = ImagesResponse(created=1710000000, data=[])
        with patch("app.services.llm_service.create_openai_client", return_value=mock_client):
            result = await execute_image_generation(
                credential_type=CredentialType.openai.value,
                api_key="sk-test",
                base_url=None,
                model="dall-e-3",
                prompt="a bird",
            )
        self.assertEqual(result["error"], "No image returned by provider")
        self.assertEqual(result["image"], "")

    async def test_public_execute_image_edit_empty_data(self) -> None:
        """Public execute_image_edit wrapper returns controlled error."""
        mock_client = MagicMock()
        mock_client.images.edit.return_value = ImagesResponse(created=1710000000, data=None)
        with patch("app.services.llm_service.create_openai_client", return_value=mock_client):
            result = await execute_image_edit(
                credential_type=CredentialType.openai.value,
                api_key="sk-test",
                base_url=None,
                model="dall-e-2",
                prompt="remove background",
                image_input=_SAMPLE_PIXEL_DATA_URL,
            )
        self.assertEqual(result["error"], "No image returned by provider")
        self.assertEqual(result["image"], "")


class TestWorkflowExecutorImageErrorPropagation(unittest.TestCase):
    """Ensure image error dictionaries propagate cleanly through workflow node execution."""

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
        self.assertEqual(out["image"], "")
        self.assertEqual(out["model"], "dall-e-3")


if __name__ == "__main__":
    unittest.main()
