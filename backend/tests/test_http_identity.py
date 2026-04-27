"""Unit tests for app.http_identity (outbound User-Agent and header merge)."""

import unittest

from app.http_identity import (
    HEYM_SERVER_AGENT,
    HEYM_USER_AGENT,
    merge_outbound_headers,
)


class HeymIdentityConstantsTests(unittest.TestCase):
    def test_server_agent_is_stable_product_slug(self) -> None:
        self.assertEqual(HEYM_SERVER_AGENT, "heym.run")

    def test_user_agent_contains_server_slug_and_https_url(self) -> None:
        self.assertIn(HEYM_SERVER_AGENT, HEYM_USER_AGENT)
        self.assertIn(f"https://{HEYM_SERVER_AGENT}", HEYM_USER_AGENT)
        self.assertIn("Heym", HEYM_USER_AGENT)


class MergeOutboundHeadersTests(unittest.TestCase):
    def test_none_returns_default_user_agent_only(self) -> None:
        merged = merge_outbound_headers(None)
        self.assertEqual(list(merged.keys()), ["User-Agent"])
        self.assertEqual(merged["User-Agent"], HEYM_USER_AGENT)

    def test_empty_dict_skipped_like_falsy(self) -> None:
        merged = merge_outbound_headers({})
        self.assertEqual(merged["User-Agent"], HEYM_USER_AGENT)
        self.assertEqual(len(merged), 1)

    def test_extra_headers_are_merged(self) -> None:
        merged = merge_outbound_headers({"X-Custom": "1", "Accept": "application/json"})
        self.assertEqual(merged["User-Agent"], HEYM_USER_AGENT)
        self.assertEqual(merged["X-Custom"], "1")
        self.assertEqual(merged["Accept"], "application/json")

    def test_caller_user_agent_overrides_default(self) -> None:
        merged = merge_outbound_headers({"User-Agent": "CustomAgent/1"})
        self.assertEqual(merged["User-Agent"], "CustomAgent/1")

    def test_does_not_mutate_input_dict(self) -> None:
        original: dict[str, str] = {"X-Trace": "abc"}
        merge_outbound_headers(original)
        self.assertEqual(original, {"X-Trace": "abc"})
