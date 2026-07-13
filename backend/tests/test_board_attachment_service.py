import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import board_attachment_service


def _card(attachments):
    return SimpleNamespace(id=uuid.uuid4(), card_metadata={"attachments": attachments})


class TestLoadCardAttachments(unittest.IsolatedAsyncioTestCase):
    async def test_card_without_attachments_returns_empty(self):
        db = AsyncMock()
        self.assertEqual(await board_attachment_service.load_card_attachments(db, _card([])), [])
        self.assertEqual(
            await board_attachment_service.load_card_attachments(
                db, SimpleNamespace(id=uuid.uuid4(), card_metadata={})
            ),
            [],
        )

    async def test_document_attachment_carries_its_extracted_text(self):
        file_id = str(uuid.uuid4())
        card = _card(
            [
                {
                    "file_id": file_id,
                    "name": "brief.txt",
                    "mime_type": "text/plain",
                    "size": 12,
                    "url": "http://x/api/files/dl/tok",
                }
            ]
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=MagicMock())

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "brief.txt"
            path.write_text("launch the beta on friday")
            with patch.object(board_attachment_service, "get_file_path", return_value=path):
                resolved = await board_attachment_service.load_card_attachments(db, card)

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["kind"], "text")
        self.assertIn("launch the beta on friday", resolved[0]["text"])

    async def test_image_attachment_is_passed_through_as_a_url(self):
        card = _card(
            [
                {
                    "file_id": str(uuid.uuid4()),
                    "name": "shot.png",
                    "mime_type": "image/png",
                    "size": 99,
                    "url": "http://x/api/files/dl/tok",
                }
            ]
        )
        db = AsyncMock()

        resolved = await board_attachment_service.load_card_attachments(db, card)

        # Images are not extracted; the vision path loads them from the URL.
        self.assertEqual(resolved[0]["kind"], "image")
        self.assertEqual(resolved[0]["url"], "http://x/api/files/dl/tok")
        self.assertNotIn("text", resolved[0])
        db.get.assert_not_awaited()

    async def test_extraction_failure_keeps_the_reference(self):
        card = _card(
            [
                {
                    "file_id": str(uuid.uuid4()),
                    "name": "broken.pdf",
                    "mime_type": "application/pdf",
                    "size": 5,
                    "url": "http://x/api/files/dl/tok",
                }
            ]
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=MagicMock())

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.pdf"
            path.write_bytes(b"not a pdf")
            with patch.object(board_attachment_service, "get_file_path", return_value=path):
                resolved = await board_attachment_service.load_card_attachments(db, card)

        # A file that cannot be read must not fail the run; the card still points at it.
        self.assertEqual(resolved[0]["name"], "broken.pdf")
        self.assertNotIn("text", resolved[0])

    async def test_extracted_text_is_capped(self):
        card = _card(
            [
                {
                    "file_id": str(uuid.uuid4()),
                    "name": "long.txt",
                    "mime_type": "text/plain",
                    "size": 1,
                    "url": "http://x/api/files/dl/tok",
                }
            ]
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=MagicMock())

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "long.txt"
            path.write_text("a" * (board_attachment_service.MAX_EXTRACTED_CHARS + 5000))
            with patch.object(board_attachment_service, "get_file_path", return_value=path):
                resolved = await board_attachment_service.load_card_attachments(db, card)

        self.assertLessEqual(len(resolved[0]["text"]), board_attachment_service.MAX_EXTRACTED_CHARS)
