"""
In-process sliding-window rate limiter with ban support.

Uses a thread-safe in-memory dict. Suitable for single-process deployments;
for multi-worker setups each worker maintains its own independent state
(which is acceptable since rate limiting is best-effort).
"""

import threading
import time


class SharedRateLimiter:
    """
    Sliding-window + ban rate limiter backed by an in-process dict.

    All keys are namespaced under `namespace:`.
    """

    def __init__(
        self,
        namespace: str,
        max_attempts: int = 10,
        window_seconds: int = 60,
        ban_seconds: int = 900,
    ) -> None:
        self._ns = namespace
        self._max = max_attempts
        self._window = window_seconds
        self._ban = ban_seconds

        self._mem: dict[str, dict] = {}
        self._lock = threading.Lock()

    def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """
        Returns (allowed, retry_after_seconds).
        retry_after_seconds is 0 when allowed.
        """
        now = time.time()
        key = f"{self._ns}:{identifier}"
        with self._lock:
            s = self._mem.setdefault(key, {"count": 0, "window_start": now, "ban_until": None})

            ban_until = s.get("ban_until")
            if ban_until and ban_until > now:
                return False, int(ban_until - now)
            if ban_until and ban_until <= now:
                s["ban_until"] = None
                s["count"] = 0
                s["window_start"] = now

            if now - s["window_start"] >= self._window:
                s["count"] = 0
                s["window_start"] = now

            s["count"] += 1
            if s["count"] > self._max:
                s["ban_until"] = now + self._ban
                return False, self._ban

        return True, 0
