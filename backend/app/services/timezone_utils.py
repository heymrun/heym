"""Shared timezone helpers for workflow execution and schedulers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

from app.config import settings

logger = logging.getLogger(__name__)


def get_configured_timezone() -> tzinfo:
    """Return the configured application timezone, falling back to UTC."""
    tz_name = settings.effective_timezone
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid timezone '%s', falling back to UTC", tz_name)
        return timezone.utc


def normalize_datetime_to_timezone(value: datetime, configured_timezone: tzinfo) -> datetime:
    """Attach or convert a datetime into the configured timezone."""
    if value.tzinfo is None:
        return value.replace(tzinfo=configured_timezone)
    return value.astimezone(configured_timezone)
