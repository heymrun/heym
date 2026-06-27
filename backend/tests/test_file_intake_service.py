import hashlib
import unittest
import uuid
from unittest.mock import AsyncMock

from app.services import file_intake_service as svc


class TokenHashingTests(unittest.TestCase):
    def test_hash_token_is_sha256_hex(self) -> None:
        token = "abc123"
        self.assertEqual(svc.hash_token(token), hashlib.sha256(token.encode()).hexdigest())

    def test_generate_token_is_high_entropy(self) -> None:
        token = svc.generate_token()
        self.assertGreaterEqual(len(token), 40)
        self.assertNotEqual(token, svc.generate_token())


class ResolveTriggerTests(unittest.TestCase):
    def test_finds_file_upload_trigger_entry_node(self) -> None:
        nodes = [
            {"id": "n1", "type": "fileUploadTrigger", "data": {"label": "audio"}},
            {"id": "n2", "type": "llm", "data": {}},
        ]
        node = svc.find_file_upload_trigger(nodes)
        self.assertIsNotNone(node)
        self.assertEqual(node["id"], "n1")

    def test_returns_none_when_absent(self) -> None:
        nodes = [{"id": "n1", "type": "textInput", "data": {}}]
        self.assertIsNone(svc.find_file_upload_trigger(nodes))


class SlotConfigTests(unittest.TestCase):
    def test_resolve_config_clamps_and_defaults(self) -> None:
        cfg = svc.resolve_slot_config({"data": {}})
        self.assertEqual(cfg.ttl_minutes, 60)
        self.assertEqual(cfg.max_size_bytes, 100 * 1024 * 1024)
        self.assertIsNone(cfg.allowed_mime)

    def test_resolve_config_caps_size_at_100mb(self) -> None:
        cfg = svc.resolve_slot_config({"data": {"maxSizeMb": 9999}})
        self.assertEqual(cfg.max_size_bytes, 100 * 1024 * 1024)

    def test_resolve_config_parses_allowed_types_csv(self) -> None:
        cfg = svc.resolve_slot_config({"data": {"allowedTypes": "audio/mpeg, .wav"}})
        self.assertEqual(cfg.allowed_mime, ["audio/mpeg", ".wav"])

    def test_resolve_config_clamps_ttl_bounds(self) -> None:
        self.assertEqual(svc.resolve_slot_config({"data": {"ttlMinutes": 0}}).ttl_minutes, 1)
        self.assertEqual(
            svc.resolve_slot_config({"data": {"ttlMinutes": 999999}}).ttl_minutes, 10080
        )


class MimeAllowlistTests(unittest.TestCase):
    def test_none_allows_any(self) -> None:
        self.assertTrue(svc.is_mime_allowed(None, "video/mp4", "clip.mp4"))

    def test_exact_mime_match(self) -> None:
        self.assertTrue(svc.is_mime_allowed(["video/mp4"], "video/mp4", "clip.mp4"))

    def test_wildcard_mime_match(self) -> None:
        self.assertTrue(svc.is_mime_allowed(["audio/*"], "audio/mpeg", "a.mp3"))

    def test_extension_match(self) -> None:
        self.assertTrue(svc.is_mime_allowed([".wav"], "application/octet-stream", "rec.wav"))

    def test_rejects_disallowed(self) -> None:
        self.assertFalse(svc.is_mime_allowed(["audio/*"], "video/mp4", "clip.mp4"))


class AuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_audit_adds_row(self) -> None:
        db = AsyncMock()
        db.add = lambda row: None
        await svc.write_audit(
            db,
            event="minted",
            slot_id=uuid.uuid4(),
            workflow_id=uuid.uuid4(),
            client_ip="1.2.3.4",
            user_agent="curl",
            file_name=None,
            file_size=None,
            mime=None,
        )
        db.flush.assert_awaited()
