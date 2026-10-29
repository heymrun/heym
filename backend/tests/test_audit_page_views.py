"""Page views reported by the web app end up in the audit trail with their URL path."""

import unittest
import uuid
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.api.page_views import PageViewRequest, normalize_page_path, record_page_view


def _fake_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    user.email = "burak@example.com"
    return user


class NormalizePagePathTests(unittest.TestCase):
    def test_plain_path_is_kept(self) -> None:
        self.assertEqual(
            normalize_page_path("/workflows/3a91d7e2-55c8-4b19-b0a1-9e8d7c6b5a43"),
            "/workflows/3a91d7e2-55c8-4b19-b0a1-9e8d7c6b5a43",
        )

    def test_dashboard_tab_survives_because_the_tab_is_the_page(self) -> None:
        self.assertEqual(normalize_page_path("/?tab=traces"), "/?tab=traces")

    def test_data_table_sub_tab_stays_readable(self) -> None:
        self.assertEqual(
            normalize_page_path("/?tab=datatable/3a91d7e2"), "/?tab=datatable/3a91d7e2"
        )

    def test_unlisted_query_parameters_are_dropped(self) -> None:
        result = normalize_page_path("/?tab=credentials&code=oauth-code&redirect=/x&sso_error=boom")

        self.assertEqual(result, "/?tab=credentials")

    def test_fragment_is_dropped(self) -> None:
        self.assertEqual(normalize_page_path("/evals#access_token=abc"), "/evals")

    def test_capability_token_in_the_path_is_replaced(self) -> None:
        self.assertEqual(normalize_page_path("/review/s3cr3t-token"), "/review/:token")
        self.assertEqual(
            normalize_page_path("/codex/followup/s3cr3t-token"), "/codex/followup/:token"
        )

    def test_overlong_query_value_is_cut(self) -> None:
        result = normalize_page_path("/?tab=" + "a" * 500)

        self.assertEqual(result, "/?tab=" + "a" * 128)

    def test_non_app_urls_are_rejected(self) -> None:
        for raw in ("https://evil.example/x", "//evil.example/x", "evil", "javascript:alert(1)"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    normalize_page_path(raw)

    def test_control_characters_are_rejected(self) -> None:
        for raw in ("/a\nb", "/a\rb", "/a\x00b", "/a\x7fb"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    normalize_page_path(raw)


class RecordPageViewTests(unittest.IsolatedAsyncioTestCase):
    async def test_emits_page_view_line_with_actor_and_path(self) -> None:
        with self.assertLogs("winston.audit", level="INFO") as captured:
            response = await record_page_view(PageViewRequest(path="/?tab=traces"), _fake_user())

        self.assertEqual(response.status_code, 204)
        line = captured.records[0].getMessage()
        self.assertIn("action=page.view", line)
        self.assertIn("outcome=success", line)
        self.assertIn("actor_email=burak@example.com", line)
        self.assertIn('path="/?tab=traces"', line)

    async def test_token_never_reaches_the_line(self) -> None:
        with self.assertLogs("winston.audit", level="INFO") as captured:
            await record_page_view(PageViewRequest(path="/review/s3cr3t-token"), _fake_user())

        line = captured.records[0].getMessage()
        self.assertIn("path=/review/:token", line)
        self.assertNotIn("s3cr3t-token", line)

    async def test_invalid_path_is_refused_and_not_logged(self) -> None:
        with self.assertNoLogs("winston.audit", level="INFO"):
            with self.assertRaises(HTTPException) as raised:
                await record_page_view(PageViewRequest(path="//evil.example"), _fake_user())

        self.assertEqual(raised.exception.status_code, 422)

    async def test_forged_newline_cannot_split_the_audit_line(self) -> None:
        with self.assertNoLogs("winston.audit", level="INFO"):
            with self.assertRaises(HTTPException):
                await record_page_view(
                    PageViewRequest(path="/x\naudit action=auth.login outcome=success"),
                    _fake_user(),
                )


if __name__ == "__main__":
    unittest.main()
