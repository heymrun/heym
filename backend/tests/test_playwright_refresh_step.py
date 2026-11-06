"""The refresh step must reload the current page, in manual and AI step flows."""

import unittest

from app.services.playwright_code_generator import generate_playwright_code


class PlaywrightRefreshStepTests(unittest.TestCase):
    def test_refresh_step_reloads_page(self) -> None:
        code = generate_playwright_code([{"action": "refresh"}])
        compile(code, "<generated>", "exec")
        self.assertIn("page.reload()", code)

    def test_refresh_step_uses_step_timeout(self) -> None:
        code = generate_playwright_code([{"action": "refresh", "timeout": 15000}])
        compile(code, "<generated>", "exec")
        self.assertIn("page.reload(timeout=15000)", code)

    def test_refresh_step_needs_no_selector_or_url(self) -> None:
        code = generate_playwright_code(
            [{"action": "navigate", "url": "https://example.com"}, {"action": "refresh"}]
        )
        compile(code, "<generated>", "exec")
        self.assertIn("page.goto(_heym_navigable_url('https://example.com'))", code)
        self.assertIn("page.reload()", code)

    def test_ai_step_loop_handles_refresh(self) -> None:
        code = generate_playwright_code(
            [
                {
                    "action": "aiStep",
                    "instructions": "reload the page",
                    "credentialId": "cred-1",
                    "model": "gpt-4o-mini",
                }
            ]
        )
        compile(code, "<generated>", "exec")
        self.assertIn("elif _a == 'refresh':", code)
        self.assertIn(
            "page.reload(timeout=int(_rtmo)) if _rtmo is not None else page.reload()", code
        )
        self.assertIn("'navigate', 'refresh',", code)


if __name__ == "__main__":
    unittest.main()
