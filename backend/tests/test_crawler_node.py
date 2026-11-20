"""Unit tests for the Crawler node execution handler."""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import crawler_node


class _FakeExecutor:
    """Stub executor providing template evaluation and credential retrieval."""

    def evaluate_message_template(self, template: str, inputs: dict, node_id: str) -> str:  # noqa: ARG002
        return template

    def evaluate_nonempty_message_template(self, template: str, inputs: dict, node_id: str) -> str:  # noqa: ARG002
        return template

    def _get_accessible_credential(self, db: object, credential_id: str) -> object | None:  # noqa: ARG002
        if credential_id == "valid-cred":
            return types.SimpleNamespace(encrypted_config=b"ciphertext")
        return None


def _make_ctx(node_data: dict) -> NodeExecutionContext:
    return NodeExecutionContext(
        executor=_FakeExecutor(),
        node_id="crawler_node_1",
        inputs={},
        allow_branch_skip=False,
        start_time=0.0,
        node={},
        node_type="crawler",
        node_data=node_data,
        node_label="crawler",
    )


class TestCrawlerNodeExecute(unittest.TestCase):
    def test_missing_credential_raises_value_error(self) -> None:
        ctx = _make_ctx({"crawlerUrl": "https://example.com"})
        with self.assertRaises(ValueError) as cm:
            crawler_node.execute(ctx)
        self.assertIn("requires a FlareSolverr credential", str(cm.exception))

    def test_missing_flaresolverr_url_raises_value_error(self) -> None:
        ctx = _make_ctx({"credentialId": "missing-cred", "crawlerUrl": "https://example.com"})
        with self.assertRaises(ValueError) as cm:
            crawler_node.execute(ctx)
        self.assertIn("FlareSolverr credential not found or missing URL", str(cm.exception))

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    def test_missing_crawler_url_raises_value_error(self, _mock_decrypt: MagicMock) -> None:
        ctx = _make_ctx({"credentialId": "valid-cred", "crawlerUrl": ""})
        with self.assertRaises(ValueError) as cm:
            crawler_node.execute(ctx)
        self.assertIn("requires a URL to crawl", str(cm.exception))

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    @patch("app.services.ssrf_guard.guard_carrier_url")
    @patch("app.services.ssrf_guard.get_guarded_carrier_http_client")
    def test_flaresolverr_http_error_raises_value_error(
        self, mock_client_factory: MagicMock, _mock_guard: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        mock_response = MagicMock(status_code=500, text="Internal Server Error")
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        ctx = _make_ctx({"credentialId": "valid-cred", "crawlerUrl": "https://example.com"})
        with self.assertRaises(ValueError) as cm:
            crawler_node.execute(ctx)
        self.assertIn("FlareSolverr error: Internal Server Error", str(cm.exception))

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    @patch("app.services.ssrf_guard.guard_carrier_url")
    @patch("app.services.ssrf_guard.get_guarded_carrier_http_client")
    def test_flaresolverr_invalid_json_raises_value_error(
        self, mock_client_factory: MagicMock, _mock_guard: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        mock_response = MagicMock(status_code=200, text="Not JSON")
        mock_response.json.side_effect = ValueError("No JSON object could be decoded")
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        ctx = _make_ctx({"credentialId": "valid-cred", "crawlerUrl": "https://example.com"})
        with self.assertRaises(ValueError) as cm:
            crawler_node.execute(ctx)
        self.assertIn("Invalid JSON response from FlareSolverr", str(cm.exception))

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    @patch("app.services.ssrf_guard.guard_carrier_url")
    @patch("app.services.ssrf_guard.get_guarded_carrier_http_client")
    def test_wait_seconds_included_in_request_when_positive(
        self, mock_client_factory: MagicMock, _mock_guard: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        mock_response = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "solution": {"status": 200, "response": "<html></html>"}},
        )
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        ctx = _make_ctx(
            {
                "credentialId": "valid-cred",
                "crawlerUrl": "https://example.com",
                "crawlerWaitSeconds": 5,
                "crawlerMaxTimeout": 30000,
            }
        )
        crawler_node.execute(ctx)

        post_kwargs = mock_client.post.call_args[1]
        self.assertEqual(post_kwargs["json"]["waitInSeconds"], 5)
        self.assertEqual(post_kwargs["json"]["maxTimeout"], 30000)

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    @patch("app.services.ssrf_guard.guard_carrier_url")
    @patch("app.services.ssrf_guard.get_guarded_carrier_http_client")
    def test_basic_mode_returns_html_and_status(
        self, mock_client_factory: MagicMock, _mock_guard: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        mock_response = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "ok",
                "solution": {"status": 200, "response": "<html><body><h1>Hello</h1></body></html>"},
            },
        )
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        ctx = _make_ctx(
            {
                "credentialId": "valid-cred",
                "crawlerUrl": "https://example.com",
                "crawlerMode": "basic",
            }
        )
        result = crawler_node.execute(ctx)

        self.assertEqual(
            result,
            {
                "html": "<html><body><h1>Hello</h1></body></html>",
                "url": "https://example.com",
                "status": 200,
            },
        )

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    @patch("app.services.ssrf_guard.guard_carrier_url")
    @patch("app.services.ssrf_guard.get_guarded_carrier_http_client")
    def test_extract_mode_with_selectors(
        self, mock_client_factory: MagicMock, _mock_guard: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        sample_html = """
        <html>
          <body>
            <article class="post" data-id="101">
              <a href="/post/101" title="Post 101">First Title</a>
              <p>First paragraph</p>
            </article>
            <article class="post" data-id="102">
              <a href="/post/102">Second Title</a>
              <p>Second paragraph</p>
            </article>
          </body>
        </html>
        """
        mock_response = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "ok",
                "solution": {"status": 200, "response": sample_html},
            },
        )
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        ctx = _make_ctx(
            {
                "credentialId": "valid-cred",
                "crawlerUrl": "https://example.com/posts",
                "crawlerMode": "extract",
                "crawlerSelectors": [
                    {
                        "name": "posts",
                        "selector": ".post",
                        "attributes": ["data-id"],
                    },
                    {
                        "name": "links",
                        "selector": ".post a",
                        "attributes": ["href", "title", "nonexistent"],
                    },
                ],
            }
        )
        result = crawler_node.execute(ctx)

        self.assertIsInstance(result, dict)
        self.assertEqual(result["url"], "https://example.com/posts")
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["html"], sample_html)

        extracted = result["extracted"]
        self.assertEqual(
            extracted["posts"],
            [
                {"text": "First Title\nFirst paragraph", "data-id": "101"},
                {"text": "Second Title\nSecond paragraph", "data-id": "102"},
            ],
        )
        self.assertEqual(
            extracted["links"],
            [
                {"text": "First Title", "href": "/post/101", "title": "Post 101"},
                {"text": "Second Title", "href": "/post/102"},
            ],
        )

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    @patch("app.services.ssrf_guard.guard_carrier_url")
    @patch("app.services.ssrf_guard.get_guarded_carrier_http_client")
    def test_extract_mode_skips_invalid_selector_configs(
        self, mock_client_factory: MagicMock, _mock_guard: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        sample_html = "<div><span class='target'>Value</span></div>"
        mock_response = MagicMock(
            status_code=200,
            json=lambda: {"status": "ok", "solution": {"status": 200, "response": sample_html}},
        )
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        ctx = _make_ctx(
            {
                "credentialId": "valid-cred",
                "crawlerUrl": "https://example.com",
                "crawlerMode": "extract",
                "crawlerSelectors": [
                    {"name": "", "selector": ".target"},
                    {"name": "missing_sel", "selector": ""},
                    {"name": "valid", "selector": ".target"},
                ],
            }
        )
        result = crawler_node.execute(ctx)
        self.assertEqual(result["extracted"], {"valid": [{"text": "Value"}]})

    @patch(
        "app.services.encryption.decrypt_config",
        return_value={"flaresolverr_url": "http://localhost:8191"},
    )
    @patch("app.services.ssrf_guard.guard_carrier_url")
    @patch("app.services.ssrf_guard.get_guarded_carrier_http_client")
    def test_extract_mode_empty_selectors_returns_empty_extracted_dict(
        self, mock_client_factory: MagicMock, _mock_guard: MagicMock, _mock_decrypt: MagicMock
    ) -> None:
        mock_response = MagicMock(
            status_code=200,
            json=lambda: {
                "status": "ok",
                "solution": {"status": 200, "response": "<p>content</p>"},
            },
        )
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        ctx = _make_ctx(
            {
                "credentialId": "valid-cred",
                "crawlerUrl": "https://example.com",
                "crawlerMode": "extract",
                "crawlerSelectors": [],
            }
        )
        result = crawler_node.execute(ctx)
        self.assertEqual(result["extracted"], {})
