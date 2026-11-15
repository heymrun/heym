import unittest
from unittest.mock import patch

from app.services.portal_rate_limiter import PortalLoginRateLimiter


class PortalLoginRateLimiterTests(unittest.TestCase):
    def test_successful_logins_never_ban(self) -> None:
        limiter = PortalLoginRateLimiter()
        wf, ip = "wf-1", "1.2.3.4"
        for _ in range(10):
            is_banned, _ = limiter.is_banned(wf, ip)
            self.assertFalse(is_banned)
            limiter.record_successful_login(wf, ip)

    def test_three_failed_attempts_still_bans_the_fourth(self) -> None:
        limiter = PortalLoginRateLimiter()
        wf, ip = "wf-2", "5.6.7.8"
        for _ in range(3):
            is_banned, _ = limiter.is_banned(wf, ip)
            self.assertFalse(is_banned)
            limiter.record_failed_attempt(wf, ip)
        is_banned, retry_after = limiter.is_banned(wf, ip)
        self.assertTrue(is_banned)
        self.assertGreater(retry_after, 0)

    def test_a_success_does_not_erase_prior_failures(self) -> None:
        """Guards against a reset-to-0 bypass: someone with a valid login on the same
        workflow+IP must not be able to launder away failures."""
        limiter = PortalLoginRateLimiter()
        wf, ip = "wf-3", "9.9.9.9"
        limiter.is_banned(wf, ip)
        limiter.record_failed_attempt(wf, ip)
        limiter.is_banned(wf, ip)
        limiter.record_failed_attempt(wf, ip)
        # A correct login for a *different* user, same workflow+IP, interleaved here.
        limiter.is_banned(wf, ip)
        limiter.record_successful_login(wf, ip)
        # One more real failure should now be enough to trip the ban (3rd failure).
        limiter.is_banned(wf, ip)
        limiter.record_failed_attempt(wf, ip)
        is_banned, _ = limiter.is_banned(wf, ip)
        self.assertTrue(is_banned)


class PortalLoginWindowTests(unittest.TestCase):
    """The count shown after a failure follows the gate's 24 h window and ban."""

    def setUp(self) -> None:
        self.now = 1_000_000.0
        clock = patch("app.services.shared_rate_limiter.time")
        self.addCleanup(clock.stop)
        clock.start().time.side_effect = lambda: self.now
        self.limiter = PortalLoginRateLimiter()

    def _fail(self, wf: str, ip: str) -> tuple[bool, int | None]:
        is_banned, retry_after = self.limiter.is_banned(wf, ip)
        if is_banned:
            return True, retry_after
        return self.limiter.record_failed_attempt(wf, ip)

    def test_failures_from_an_expired_window_are_forgotten(self) -> None:
        wf, ip = "wf-window", "10.0.0.1"
        self.assertEqual(self._fail(wf, ip), (False, None))
        self.assertEqual(self._fail(wf, ip), (False, None))
        self.now += 30 * 86400
        self.assertEqual(self._fail(wf, ip), (False, None))
        self.assertEqual(self.limiter.get_remaining_attempts(wf, ip), 2)

    def test_the_third_failure_inside_the_window_still_reports_the_ban(self) -> None:
        wf, ip = "wf-inside", "10.0.0.2"
        self._fail(wf, ip)
        self.now += 3600
        self._fail(wf, ip)
        self.now += 3600
        self.assertEqual(self._fail(wf, ip), (True, 86400))
        self.assertTrue(self.limiter.is_banned(wf, ip)[0])

    def test_a_lapsed_ban_starts_a_fresh_count(self) -> None:
        wf, ip = "wf-ban", "10.0.0.3"
        for _ in range(3):
            self._fail(wf, ip)
        self.assertTrue(self.limiter.is_banned(wf, ip)[0])
        self.now += 86400 + 1
        self.assertEqual(self._fail(wf, ip), (False, None))
        self.assertEqual(self.limiter.get_remaining_attempts(wf, ip), 2)
