import threading
import time
from dataclasses import dataclass, field

from app.services.shared_rate_limiter import SharedRateLimiter

_shared = SharedRateLimiter(
    namespace="portal_login",
    max_attempts=3,
    window_seconds=86400,
    ban_seconds=86400,
)


@dataclass
class LoginAttempt:
    failed_count: int = 0
    banned_until: float | None = None
    last_attempt: float = field(default_factory=time.time)


class PortalLoginRateLimiter:
    """
    Portal-specific login rate limiter.

    Delegates to SharedRateLimiter (Redis-backed with in-memory fallback) for
    cross-worker consistency.  The in-process dict is kept only as a lightweight
    attempt counter for the remaining-attempts display.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        ban_duration_hours: int = 24,
        cleanup_interval_seconds: int = 3600,
    ):
        self._attempts: dict[str, LoginAttempt] = {}
        self._lock = threading.Lock()
        self._max_attempts = max_attempts
        self._ban_duration_seconds = ban_duration_hours * 3600
        self._cleanup_interval = cleanup_interval_seconds
        self._last_cleanup = time.time()

    def _get_key(self, workflow_id: str, client_ip: str) -> str:
        return f"{workflow_id}:{client_ip}"

    def _cleanup_expired(self) -> None:
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        expired_keys = []
        for key, attempt in self._attempts.items():
            if attempt.banned_until and attempt.banned_until < now:
                expired_keys.append(key)
            elif now - attempt.last_attempt > self._ban_duration_seconds * 2:
                expired_keys.append(key)
        for key in expired_keys:
            del self._attempts[key]
        self._last_cleanup = now

    def is_banned(self, workflow_id: str, client_ip: str) -> tuple[bool, int | None]:
        sub = self._get_key(workflow_id, client_ip)
        allowed, retry_after = _shared.is_allowed(sub)
        if not allowed:
            return True, retry_after
        return False, None

    def record_failed_attempt(self, workflow_id: str, client_ip: str) -> tuple[bool, int | None]:
        sub = self._get_key(workflow_id, client_ip)
        now = time.time()

        with self._lock:
            if sub not in self._attempts:
                self._attempts[sub] = LoginAttempt()
            attempt = self._attempts[sub]
            attempt.failed_count += 1
            attempt.last_attempt = now

            if attempt.failed_count >= self._max_attempts:
                attempt.banned_until = now + self._ban_duration_seconds
                return True, self._ban_duration_seconds

        return False, None

    def record_successful_login(self, workflow_id: str, client_ip: str) -> None:
        sub = self._get_key(workflow_id, client_ip)
        with self._lock:
            self._attempts.pop(sub, None)

    def get_remaining_attempts(self, workflow_id: str, client_ip: str) -> int:
        sub = self._get_key(workflow_id, client_ip)
        with self._lock:
            attempt = self._attempts.get(sub)
            if not attempt:
                return self._max_attempts
            return max(0, self._max_attempts - attempt.failed_count)


portal_login_limiter = PortalLoginRateLimiter()
