from unittest import TestCase

from app.services.codex_usage_service import parse_codex_usage_headers, window_label


class WindowLabelTest(TestCase):
    def test_known_labels(self) -> None:
        self.assertEqual(window_label(300), "5 hours")
        self.assertEqual(window_label(10080), "Weekly")

    def test_generic_hours_and_days(self) -> None:
        self.assertEqual(window_label(60), "1h")
        self.assertEqual(window_label(2880), "2d")


class ParseHeadersTest(TestCase):
    def _headers(self) -> dict[str, str]:
        return {
            "x-codex-active-limit": "premium",
            "x-codex-plan-type": "plus",
            "x-codex-primary-used-percent": "34",
            "x-codex-secondary-used-percent": "0",
            "x-codex-primary-window-minutes": "10080",
            "x-codex-secondary-window-minutes": "0",
            "x-codex-primary-reset-after-seconds": "569620",
            "x-codex-primary-reset-at": "1784966861",
            "x-codex-secondary-reset-after-seconds": "0",
            "x-codex-secondary-reset-at": "",
            "x-codex-credits-has-credits": "False",
            "x-codex-credits-balance": "0E-10",
            "x-codex-credits-unlimited": "False",
        }

    def test_skips_zero_minute_window(self) -> None:
        usage = parse_codex_usage_headers(self._headers())
        self.assertTrue(usage.available)
        self.assertEqual(usage.plan_type, "plus")
        self.assertEqual([w.key for w in usage.windows], ["primary"])
        w = usage.windows[0]
        self.assertEqual(w.label, "Weekly")
        self.assertEqual(w.used_percent, 34.0)
        self.assertEqual(w.reset_at, 1784966861)

    def test_credits_parsed(self) -> None:
        usage = parse_codex_usage_headers(self._headers())
        assert usage.credits is not None
        self.assertFalse(usage.credits.has_credits)
        self.assertFalse(usage.credits.unlimited)

    def test_missing_headers_yield_unavailable(self) -> None:
        usage = parse_codex_usage_headers({})
        self.assertFalse(usage.available)
