import hashlib
import json
import time
from threading import Lock
from typing import Any


class InMemoryCache:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = Lock()

    def _generate_key(self, workflow_id: str, body: dict, query: dict) -> str:
        data = json.dumps(
            {"workflow_id": workflow_id, "body": body, "query": query}, sort_keys=True
        )
        return hashlib.sha256(data.encode()).hexdigest()

    def get(self, workflow_id: str, body: dict, query: dict) -> tuple[bool, Any]:
        key = self._generate_key(workflow_id, body, query)
        with self._lock:
            if key in self._cache:
                value, expire_time = self._cache[key]
                if time.time() < expire_time:
                    return True, value
                del self._cache[key]
        return False, None

    def set(self, workflow_id: str, body: dict, query: dict, value: Any, ttl_seconds: int) -> None:
        key = self._generate_key(workflow_id, body, query)
        expire_time = time.time() + ttl_seconds
        with self._lock:
            self._cache[key] = (value, expire_time)

    def cleanup_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._cache.items() if now >= exp]
            for key in expired_keys:
                del self._cache[key]
                removed += 1
        return removed


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, list[float]] = {}
        self._lock = Lock()

    def _generate_key(self, workflow_id: str, client_ip: str) -> str:
        return f"{workflow_id}:{client_ip}"

    def is_allowed(
        self, workflow_id: str, client_ip: str, max_requests: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        key = self._generate_key(workflow_id, client_ip)
        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            if key not in self._requests:
                self._requests[key] = []

            self._requests[key] = [ts for ts in self._requests[key] if ts > window_start]

            current_count = len(self._requests[key])
            remaining = max(0, max_requests - current_count)

            if current_count >= max_requests:
                if self._requests[key]:
                    oldest = min(self._requests[key])
                    retry_after = int(oldest + window_seconds - now) + 1
                else:
                    retry_after = window_seconds
                return False, remaining, retry_after

            self._requests[key].append(now)
            return True, remaining - 1, 0

    def cleanup_expired(self, max_window_seconds: int = 3600) -> int:
        now = time.time()
        cutoff = now - max_window_seconds
        removed = 0
        with self._lock:
            empty_keys = []
            for key, timestamps in self._requests.items():
                self._requests[key] = [ts for ts in timestamps if ts > cutoff]
                if not self._requests[key]:
                    empty_keys.append(key)
            for key in empty_keys:
                del self._requests[key]
                removed += 1
        return removed


response_cache = InMemoryCache()
rate_limiter = InMemoryRateLimiter()
