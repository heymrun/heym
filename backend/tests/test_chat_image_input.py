"""An image attached in chat reaches a workflow's image input as a data URL, from Drive."""

import base64
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import chat_image_input
from app.services.file_sandbox.instructions import chat_file_instructions

PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"


class TestImageField(unittest.TestCase):
    def test_only_a_field_named_like_an_image_takes_it(self):
        self.assertEqual(chat_image_input.image_field(["query", "photo_url"]), "photo_url")
        self.assertEqual(chat_image_input.image_field(["imageBase64", "text"]), "imageBase64")
        self.assertIsNone(chat_image_input.image_field(["query", "text"]))
        self.assertIsNone(chat_image_input.image_field([]))

    def test_the_chat_is_told_how_to_read_images(self):
        rules = chat_file_instructions()
        self.assertIn("Images (png, jpg, gif, webp)", rules)
        self.assertIn("heym_ocr.image_to_text", rules)


class TestImageInput(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user_id = uuid.uuid4()
        self.file_id = uuid.uuid4()
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "screen.png"
        self.path.write_bytes(PNG)

    def tearDown(self):
        self._tmp.cleanup()

    def _row(self, mime="image/png", size=len(PNG)):
        return SimpleNamespace(
            file=SimpleNamespace(id=self.file_id, mime_type=mime, size_bytes=size)
        )

    async def _input(self, *, found, mime="image/png", fields=("image", "query")):
        with (
            patch.object(
                chat_image_input, "get_accessible_file", AsyncMock(return_value=found)
            ) as get,
            patch.object(chat_image_input, "get_file_path", return_value=self.path),
        ):
            result = await chat_image_input.image_input(
                AsyncMock(), self.user_id, file_id=self.file_id, mime=mime, field_keys=list(fields)
            )
        return result, get

    async def test_an_image_drive_file_fills_the_image_field(self):
        result, get = await self._input(found=self._row())
        expected = f"data:image/png;base64,{base64.b64encode(PNG).decode('ascii')}"
        self.assertEqual(result, ("image", expected))
        get.assert_awaited_once()
        self.assertEqual(get.await_args.args[1:], (self.file_id, self.user_id))

    async def test_nothing_is_read_without_an_image_or_an_image_field(self):
        for kwargs in ({"mime": "application/pdf"}, {"fields": ("query", "text")}):
            result, get = await self._input(found=self._row(), **kwargs)
            self.assertIsNone(result)
            get.assert_not_awaited()

    async def test_a_file_the_user_cannot_open_or_too_large_stays_out(self):
        for found in (None, self._row(size=chat_image_input.MAX_INLINE_IMAGE_BYTES + 1)):
            result, _ = await self._input(found=found)
            self.assertIsNone(result)

    async def test_the_stored_type_decides_not_the_claimed_one(self):
        result, _ = await self._input(found=self._row(mime="application/pdf"))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
