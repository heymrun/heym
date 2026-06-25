import unittest

from app.services.file_intake_service import build_mint_payload


class MintPayloadTests(unittest.TestCase):
    def test_build_mint_payload_shape(self) -> None:
        payload = build_mint_payload(
            base_url="https://heym.run",
            token="TOK",
            expires_at_iso="2026-06-25T12:00:00+00:00",
            max_size_bytes=100 * 1024 * 1024,
            allowed_mime=["audio/*"],
            slot_id="11111111-1111-1111-1111-111111111111",
        )
        self.assertEqual(payload["upload_url"], "https://heym.run/api/file-intake/u/TOK")
        self.assertIn("curl", payload["curl"])
        self.assertIn("-F", payload["curl"])
        self.assertIn("https://heym.run/api/file-intake/u/TOK", payload["curl"])
        self.assertEqual(payload["max_size_mb"], 100)
        self.assertEqual(payload["allowed_types"], ["audio/*"])
        self.assertEqual(payload["expires_at"], "2026-06-25T12:00:00+00:00")

    def test_allowed_types_empty_when_none(self) -> None:
        payload = build_mint_payload(
            base_url="https://heym.run",
            token="T",
            expires_at_iso="x",
            max_size_bytes=1024 * 1024,
            allowed_mime=None,
            slot_id="s",
        )
        self.assertEqual(payload["allowed_types"], [])
