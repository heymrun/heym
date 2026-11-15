from app.services.shared_rate_limiter import SharedRateLimiter

_shared = SharedRateLimiter(
    namespace="portal_login",
    max_attempts=3,
    window_seconds=86400,
    ban_seconds=86400,
)


class PortalLoginRateLimiter:
    """
    Portal-specific login rate limiter.

    Delegates to SharedRateLimiter for the gate and reads the remaining-attempts count
    from the same state, so the count shown after a failure always follows the gate's
    window: once the window or a ban lapses, both start counting afresh together.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        ban_duration_hours: int = 24,
        cleanup_interval_seconds: int = 3600,
    ):
        self._max_attempts = max_attempts
        self._ban_duration_seconds = ban_duration_hours * 3600

    def _get_key(self, workflow_id: str, client_ip: str) -> str:
        return f"{workflow_id}:{client_ip}"

    def is_banned(self, workflow_id: str, client_ip: str) -> tuple[bool, int | None]:
        sub = self._get_key(workflow_id, client_ip)
        allowed, retry_after = _shared.is_allowed(sub)
        if not allowed:
            return True, retry_after
        return False, None

    def record_failed_attempt(self, workflow_id: str, client_ip: str) -> tuple[bool, int | None]:
        # is_banned() already counted this attempt when it was admitted.
        sub = self._get_key(workflow_id, client_ip)
        if _shared.attempts(sub) >= self._max_attempts:
            return True, self._ban_duration_seconds
        return False, None

    def record_successful_login(self, workflow_id: str, client_ip: str) -> None:
        sub = self._get_key(workflow_id, client_ip)
        _shared.record_success(sub)

    def get_remaining_attempts(self, workflow_id: str, client_ip: str) -> int:
        sub = self._get_key(workflow_id, client_ip)
        return max(0, self._max_attempts - _shared.attempts(sub))


portal_login_limiter = PortalLoginRateLimiter()
