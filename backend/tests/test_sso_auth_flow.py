"""SSO login initiation, callback state handling, and account resolution."""

import unittest

from app.api.sso_auth import safe_next_path


class NextPathTests(unittest.TestCase):
    def test_a_relative_path_is_kept(self) -> None:
        self.assertEqual(safe_next_path("/workflows/42"), "/workflows/42")

    def test_an_absolute_url_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path("https://evil.example/phish"), "/")

    def test_a_protocol_relative_url_falls_back_to_root(self) -> None:
        """//evil.example is a URL, not a path; browsers follow it off-site."""
        self.assertEqual(safe_next_path("//evil.example"), "/")

    def test_a_backslash_variant_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path("/\\evil.example"), "/")

    def test_a_path_without_a_leading_slash_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path("workflows"), "/")

    def test_none_falls_back_to_root(self) -> None:
        self.assertEqual(safe_next_path(None), "/")
