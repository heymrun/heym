"""Regression tests for credential forwarding on Jira-supplied attachment URLs.

Jira picks the ``content`` URL in an attachment response, so a workflow that
downloads binary content follows a URL the API chose rather than one the
operator configured. Without an origin policy an attacker who can attach a file
to a readable issue points that URL at their own host and receives the
credential's Basic auth header. The SSRF transport blocks private targets but
says nothing about public ones, so credential forwarding is a separate control.
"""

import unittest
from unittest.mock import MagicMock

import httpx

from app.services.jira_service import JiraService

_BASE_URL = "https://example.atlassian.net"


def _service(client: MagicMock, base_url: str = _BASE_URL) -> JiraService:
    return JiraService(
        {"email": "ada@example.com", "api_token": "jira-token", "base_url": base_url},
        client=client,
    )


def _binary_response(url: str) -> httpx.Response:
    return httpx.Response(200, content=b"payload", request=httpx.Request("GET", url))


class JiraAttachmentOriginTests(unittest.TestCase):
    def test_same_origin_content_url_is_downloaded_with_credentials(self) -> None:
        client = MagicMock()
        url = f"{_BASE_URL}/rest/api/3/attachment/content/10001"
        client.request.return_value = _binary_response(url)

        content = _service(client).download_attachment(url)

        self.assertEqual(content, b"payload")
        self.assertEqual(client.request.call_args.args[:2], ("GET", url))
        self.assertEqual(client.request.call_args.kwargs["auth"], ("ada@example.com", "jira-token"))

    def test_cross_origin_content_url_is_refused_before_any_request(self) -> None:
        client = MagicMock()
        service = _service(client)

        with self.assertRaises(ValueError) as ctx:
            service.download_attachment("https://attacker.example.com/steal")

        self.assertIn("outside the credential base URL origin", str(ctx.exception))
        client.request.assert_not_called()

    def test_credentials_are_not_sent_to_a_host_prefixed_with_the_base_host(self) -> None:
        client = MagicMock()
        service = _service(client)

        with self.assertRaises(ValueError):
            service.download_attachment("https://example.atlassian.net.attacker.example/x")

        client.request.assert_not_called()

    def test_scheme_downgrade_and_port_change_are_both_cross_origin(self) -> None:
        client = MagicMock()
        service = _service(client)

        for url in (
            "http://example.atlassian.net/rest/api/3/attachment/content/1",
            "https://example.atlassian.net:8443/rest/api/3/attachment/content/1",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    service.download_attachment(url)
        client.request.assert_not_called()

    def test_non_http_content_url_is_refused(self) -> None:
        client = MagicMock()
        service = _service(client)

        with self.assertRaises(ValueError):
            service.download_attachment("file:///etc/passwd")

        client.request.assert_not_called()

    def test_empty_content_url_is_refused(self) -> None:
        client = MagicMock()
        service = _service(client)

        with self.assertRaises(ValueError) as ctx:
            service.download_attachment("   ")

        self.assertIn("empty", str(ctx.exception))
        client.request.assert_not_called()

    def test_relative_content_url_resolves_against_the_credential_base_url(self) -> None:
        client = MagicMock()
        resolved = f"{_BASE_URL}/secure/attachment/10001/report.pdf"
        client.request.return_value = _binary_response(resolved)

        content = _service(client).download_attachment("/secure/attachment/10001/report.pdf")

        self.assertEqual(content, b"payload")
        self.assertEqual(client.request.call_args.args[:2], ("GET", resolved))

    def test_default_port_matches_an_explicit_default_port(self) -> None:
        client = MagicMock()
        url = "https://example.atlassian.net:443/rest/api/3/attachment/content/1"
        client.request.return_value = _binary_response(url)

        self.assertEqual(_service(client).download_attachment(url), b"payload")

    def test_data_center_base_path_still_accepts_its_own_origin(self) -> None:
        client = MagicMock()
        base = "https://jira.internal.example:8080/jira"
        url = f"{base}/secure/attachment/10001/report.pdf"
        client.request.return_value = _binary_response(url)

        self.assertEqual(_service(client, base).download_attachment(url), b"payload")


if __name__ == "__main__":
    unittest.main()
