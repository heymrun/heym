"""Execution tokens for Playwright AI step callbacks from subprocess.

Uses JWT signed with SECRET_KEY so tokens are stateless and valid across
all uvicorn workers without any shared state.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings

_TTL_SECONDS = 600  # 10 minutes
_TOKEN_TYPE = "playwright_execution"


def create_token(user_id: str) -> str:
    """Create a signed JWT execution token for Playwright subprocess callbacks."""
    expire = datetime.now(timezone.utc) + timedelta(seconds=_TTL_SECONDS)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": _TOKEN_TYPE,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def validate_token(token: str | None) -> str | None:
    """Validate token and return user_id if valid, else None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != _TOKEN_TYPE:
            return None
        return payload.get("sub")
    except JWTError:
        return None
