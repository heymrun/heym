"""SSRF guard tests for the LLM image-edit input loader (GHSA-6rph-qqcv-jqh4)."""

import base64
import unittest
from unittest.mock import MagicMock, patch

from app.services import ssrf_guard
from app.services.llm_service import _load_image_bytes
from app.services.ssrf_guard import SsrfBlockedError


class LoadImageBytesSsrfTests(unittest.TestCase):
    """Caller-controlled image URLs must pass through the shared SSRF guard."""

    def setUp(self) -> None:
        # Pin the opt-out so the blocking assertions do not depend on the ambient
        # HEYM_HTTP_ALLOW_PRIVATE_URLS. Without it these tests both fail and make
        # real outbound requests on a machine that sets the flag.
        patcher = patch.object(ssrf_guard.settings, "http_allow_private_urls", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_loopback_url_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            _load_image_bytes("http://127.0.0.1:8080/x.png")

    def test_cloud_metadata_ip_blocked(self) -> None:
        with self.assertRaises(SsrfBlockedError):
            _load_image_bytes("http://169.254.169.254/latest/meta-data/")

    def test_private_ipv4_blocked(self) -> None:
        for url in (
            "http://10.0.0.5/x.png",
            "http://192.168.1.10/x.png",
            "http://172.16.5.5/x.png",
        ):
            with self.subTest(url=url), self.assertRaises(SsrfBlockedError):
                _load_image_bytes(url)

    def test_non_http_scheme_not_fetched(self) -> None:
        # file:// falls through to the base64 branch rather than being fetched.
        with self.assertRaises(Exception) as ctx:
            _load_image_bytes("file:///etc/passwd")
        self.assertNotIsInstance(ctx.exception, SsrfBlockedError)

    def test_rejection_names_the_llm_field_not_the_http_node(self) -> None:
        with self.assertRaises(SsrfBlockedError) as ctx:
            _load_image_bytes("http://127.0.0.1:8080/x.png")
        self.assertIn("LLM image input URL", str(ctx.exception))
        self.assertNotIn("HTTP node", str(ctx.exception))

    def test_data_url_bypasses_guard(self) -> None:
        payload = base64.b64encode(b"hello").decode()
        data, mime = _load_image_bytes(f"data:image/png;base64,{payload}")
        self.assertEqual(data, b"hello")
        self.assertEqual(mime, "image/png")

    def test_public_url_fetched_via_guarded_client(self) -> None:
        client = MagicMock()
        response = MagicMock()
        response.headers = {"Content-Type": "image/png"}
        response.content = b"png-bytes"
        client.get.return_value = response
        with patch(
            "app.services.image_input.get_guarded_http_client", return_value=client
        ) as get_client:
            data, mime = _load_image_bytes("http://1.1.1.1/x.png")
        get_client.assert_called_once_with()
        client.get.assert_called_once()
        self.assertEqual(data, b"png-bytes")
        self.assertEqual(mime, "image/png")


if __name__ == "__main__":
    unittest.main()
