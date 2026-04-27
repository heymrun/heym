"""IP-based rate limiters for authentication endpoints."""

from app.services.shared_rate_limiter import SharedRateLimiter

login_limiter = SharedRateLimiter(
    namespace="auth_login",
    max_attempts=10,
    window_seconds=60,
    ban_seconds=900,
)

register_limiter = SharedRateLimiter(
    namespace="auth_register",
    max_attempts=5,
    window_seconds=60,
    ban_seconds=600,
)

oauth_register_limiter = SharedRateLimiter(
    namespace="oauth_register",
    max_attempts=5,
    window_seconds=60,
    ban_seconds=600,
)
