"""LLM node image output: failed attempts reach the fallback, image URLs are passed on."""

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from openai.types import Image, ImagesResponse

from app.db.models import CredentialType
from app.services.llm_service import LLMService
from app.services.workflow_executor import WorkflowExecutor

_PIXEL_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
_GOOGLE_NO_IMAGE = {
    "image": "",
    "text": "I can't draw that.",
    "model": "gemini-image",
    "error": "No image in response",
    "elapsed_ms": 12.0,
}
_GOOGLE_IMAGE = {
    "image": "data:image/png;base64,Z29vZ2xl",
    "text": "a cat",
    "model": "gemini-image",
    "elapsed_ms": 12.0,
}


def _credential(cred_type: CredentialType, config: bytes) -> MagicMock:
    cred = MagicMock()
    cred.type = cred_type
    cred.name = config.decode()
    cred.encrypted_config = config
    return cred


class ImageFallbackTests(unittest.TestCase):
    """Run `_execute_llm_node` with image output against two credentials."""

    def setUp(self) -> None:
        self.creds = {
            "google-primary": _credential(CredentialType.google, b"google-primary"),
            "google-fallback": _credential(CredentialType.google, b"google-fallback"),
            "openai-fallback": _credential(CredentialType.openai, b"openai-fallback"),
        }
        self.google_results: dict[str, dict[str, Any]] = {}
        self.openai_client = MagicMock()
        self.openai_client.images.generate.return_value = ImagesResponse(
            created=1, data=[Image(b64_json="b3BlbmFp")]
        )
        self.openai_client.images.edit.return_value = ImagesResponse(
            created=1, data=[Image(b64_json="ZWRpdGVk")]
        )

    def _run(
        self,
        *,
        primary: str,
        fallback: str | None,
        image_input: str | None = None,
    ) -> dict[str, Any]:
        google_results = self.google_results

        async def fake_google(service: LLMService, *_args: object, **_kwargs: object) -> dict:
            return dict(google_results[service.api_key])

        executor = WorkflowExecutor(nodes=[], edges=[])
        with (
            patch.object(
                executor,
                "_get_accessible_credential",
                side_effect=lambda _db, cid: self.creds[cid],
            ),
            patch(
                "app.services.encryption.decrypt_config",
                side_effect=lambda config: {"api_key": config.decode()},
            ),
            patch.object(LLMService, "_execute_google_image_generation", fake_google),
            patch.object(LLMService, "_execute_google_image_edit", fake_google),
            patch(
                "app.services.llm_service.create_openai_client",
                return_value=self.openai_client,
            ),
        ):
            return executor._execute_llm_node(
                credential_id=primary,
                node_id="node-1",
                model="primary-model",
                system_instruction=None,
                user_message="a cat",
                temperature=0.7,
                reasoning_effort=None,
                max_tokens=None,
                json_output_enabled=False,
                json_output_schema=None,
                image_input=image_input,
                output_type="image",
                fallback_credential_id=fallback,
                fallback_model="fallback-model" if fallback else None,
            )

    def test_google_generation_error_moves_on_to_fallback(self) -> None:
        """A Google generation that reports an error lets the fallback produce the image."""
        self.google_results["google-primary"] = _GOOGLE_NO_IMAGE

        out = self._run(primary="google-primary", fallback="openai-fallback")

        self.assertNotIn("error", out)
        self.assertEqual(out["image"], "data:image/png;base64,b3BlbmFp")
        self.assertTrue(out["fallbackUsed"])
        self.assertEqual(out["model"], "fallback-model")
        self.openai_client.images.generate.assert_called_once()

    def test_google_edit_error_moves_on_to_fallback(self) -> None:
        """A Google edit that reports an error lets the fallback edit the image."""
        self.google_results["google-primary"] = _GOOGLE_NO_IMAGE

        out = self._run(
            primary="google-primary",
            fallback="openai-fallback",
            image_input=_PIXEL_DATA_URL,
        )

        self.assertNotIn("error", out)
        self.assertEqual(out["image"], "data:image/png;base64,ZWRpdGVk")
        self.assertTrue(out["fallbackUsed"])
        self.openai_client.images.edit.assert_called_once()

    def test_google_error_without_fallback_is_returned_unchanged(self) -> None:
        """With no fallback configured, the node gets the provider's result as before."""
        self.google_results["google-primary"] = _GOOGLE_NO_IMAGE

        out = self._run(primary="google-primary", fallback=None)

        self.assertEqual(out, _GOOGLE_NO_IMAGE)
        self.openai_client.images.generate.assert_not_called()

    def test_google_success_does_not_call_fallback(self) -> None:
        """A primary that returns an image never touches the fallback."""
        self.google_results["google-primary"] = _GOOGLE_IMAGE

        out = self._run(primary="google-primary", fallback="openai-fallback")

        self.assertEqual(out, _GOOGLE_IMAGE)
        self.assertNotIn("fallbackUsed", out)
        self.openai_client.images.generate.assert_not_called()

    def test_both_google_attempts_fail_reports_the_fallback_error(self) -> None:
        """When the fallback also reports an error, the node fails with the fallback's error."""
        self.google_results["google-primary"] = {**_GOOGLE_NO_IMAGE, "error": "primary failed"}
        self.google_results["google-fallback"] = {**_GOOGLE_NO_IMAGE, "error": "fallback failed"}

        out = self._run(primary="google-primary", fallback="google-fallback")

        self.assertEqual(out["error"], "fallback failed")
        self.assertTrue(out["fallbackUsed"])
        self.assertEqual(out["model"], "fallback-model")

    def test_url_only_primary_succeeds_without_fallback(self) -> None:
        """A primary that sends an image URL is a success; the fallback is not called."""
        self.openai_client.images.generate.return_value = ImagesResponse(
            created=1, data=[Image(url="https://cdn.example.com/cat.png")]
        )
        self.creds["openai-primary"] = _credential(CredentialType.openai, b"openai-primary")
        self.google_results["google-fallback"] = _GOOGLE_IMAGE

        out = self._run(primary="openai-primary", fallback="google-fallback")

        self.assertNotIn("error", out)
        self.assertEqual(out["image"], "https://cdn.example.com/cat.png")
        self.assertNotIn("fallbackUsed", out)

    def test_empty_image_entry_moves_on_to_fallback(self) -> None:
        """An image entry with neither base64 data nor a URL lets the fallback run."""
        self.openai_client.images.generate.return_value = ImagesResponse(
            created=1, data=[Image(b64_json="")]
        )
        self.creds["openai-primary"] = _credential(CredentialType.openai, b"openai-primary")
        self.google_results["google-fallback"] = _GOOGLE_IMAGE

        out = self._run(primary="openai-primary", fallback="google-fallback")

        self.assertNotIn("error", out)
        self.assertEqual(out["image"], _GOOGLE_IMAGE["image"])
        self.assertTrue(out["fallbackUsed"])
        self.assertEqual(out["model"], "fallback-model")


class ImageResponseShapeTests(unittest.IsolatedAsyncioTestCase):
    """OpenAI-compatible image calls: base64 becomes a data URL, a provider URL is kept."""

    async def asyncSetUp(self) -> None:
        self.service = LLMService(CredentialType.openai, "sk-test", None)
        self.client = MagicMock()
        self.service._get_client = MagicMock(return_value=(self.client, "OpenAI"))  # type: ignore[method-assign]

    async def test_generation_with_url_only_passes_the_url_on(self) -> None:
        """A generation answered with a URL returns that URL and records a clean trace."""
        self.client.images.generate.return_value = ImagesResponse(
            created=1,
            data=[Image(url="https://cdn.example.com/cat.png", revised_prompt="a fluffy cat")],
        )

        with patch.object(self.service, "_record_trace") as record:
            result = await self.service.execute_image_generation(model="dall-e-3", prompt="a cat")

        self.assertEqual(result["image"], "https://cdn.example.com/cat.png")
        self.assertEqual(result["revised_prompt"], "a fluffy cat")
        self.assertNotIn("error", result)
        record.assert_called_once()
        self.assertIsNone(record.call_args.kwargs["error"])
        self.assertEqual(
            record.call_args.kwargs["response"]["image"], "https://cdn.example.com/cat.png"
        )

    async def test_edit_with_url_only_passes_the_url_on(self) -> None:
        """An edit answered with a URL returns that URL and records a clean trace."""
        self.client.images.edit.return_value = ImagesResponse(
            created=1, data=[Image(url="https://cdn.example.com/hat.png")]
        )

        with patch.object(self.service, "_record_trace") as record:
            result = await self.service.execute_image_edit(
                model="dall-e-2", prompt="add a hat", image_input=_PIXEL_DATA_URL
            )

        self.assertEqual(result["image"], "https://cdn.example.com/hat.png")
        self.assertNotIn("error", result)
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["request_type"], "images.edit")
        self.assertIsNone(record.call_args.kwargs["error"])

    async def test_base64_wins_over_url_when_both_are_sent(self) -> None:
        """A response with both base64 data and a URL keeps the inline data URL."""
        self.client.images.generate.return_value = ImagesResponse(
            created=1,
            data=[Image(b64_json="aGVsbG8=", url="https://cdn.example.com/cat.png")],
        )

        result = await self.service.execute_image_generation(model="dall-e-3", prompt="a cat")

        self.assertEqual(result["image"], "data:image/png;base64,aGVsbG8=")

    async def test_generation_with_empty_b64_and_no_url_raises(self) -> None:
        """An image entry with neither base64 data nor a URL counts as no image."""
        self.client.images.generate.return_value = ImagesResponse(
            created=1, data=[Image(b64_json="")]
        )

        with patch.object(self.service, "_record_trace") as record:
            with self.assertRaisesRegex(ValueError, "No image returned by provider"):
                await self.service.execute_image_generation(model="dall-e-3", prompt="a cat")

        self.assertEqual(record.call_args.kwargs["error"], "No image returned by provider")

    async def test_edit_with_empty_b64_and_no_url_raises_and_records_trace(self) -> None:
        """An edit entry with neither base64 data nor a URL raises and keeps a trace."""
        self.client.images.edit.return_value = ImagesResponse(created=1, data=[Image(b64_json="")])

        with patch.object(self.service, "_record_trace") as record:
            with self.assertRaisesRegex(ValueError, "No image returned by provider"):
                await self.service.execute_image_edit(
                    model="dall-e-2", prompt="add a hat", image_input=_PIXEL_DATA_URL
                )

        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["error"], "No image returned by provider")

    async def test_generation_with_b64_still_succeeds(self) -> None:
        """A normal base64 response keeps its data URL and revised prompt."""
        self.client.images.generate.return_value = ImagesResponse(
            created=1,
            data=[Image(b64_json="aGVsbG8=", revised_prompt="a fluffy cat")],
        )

        result = await self.service.execute_image_generation(model="dall-e-3", prompt="a cat")

        self.assertEqual(result["image"], "data:image/png;base64,aGVsbG8=")
        self.assertEqual(result["revised_prompt"], "a fluffy cat")
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
