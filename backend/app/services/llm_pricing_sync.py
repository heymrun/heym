"""Helicone pricing sync: fetches https://www.helicone.ai/api/llm-costs,
upserts into llm_pricing, never touches llm_pricing_override.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMPricing
from app.db.session import async_session_maker

logger = logging.getLogger(__name__)

HELICONE_URL = "https://www.helicone.ai/api/llm-costs"
SYNC_TTL = timedelta(hours=24)
HTTP_TIMEOUT = 10.0


async def sync_pricing_from_helicone(db: AsyncSession) -> int:
    """Fetch Helicone payload and upsert rows. Returns count of upserted rows
    (0 on fetch/parse failure)."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(HELICONE_URL, headers={"User-Agent": "heym/1.0"})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("Helicone pricing fetch failed: %s", exc)
        return 0

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        logger.warning("Helicone payload missing 'data' list")
        return 0

    now = datetime.now(timezone.utc)
    upserted = 0
    for entry in rows:
        try:
            provider = str(entry["provider"])
            model = str(entry["model"])
            operator = str(entry.get("operator") or "equals")
            input_cost = Decimal(str(entry["input_cost_per_1m"]))
            output_cost = Decimal(str(entry["output_cost_per_1m"]))
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("Skipping invalid Helicone entry %r: %s", entry, exc)
            continue

        # Helicone uses negative values (e.g. -1000000) as sentinels for
        # dynamic/unknown pricing. Skip those — they're not real prices and
        # would overflow our Numeric(12, 6) column.
        if input_cost < 0 or output_cost < 0:
            logger.debug(
                "Skipping Helicone entry with sentinel pricing: %s/%s in=%s out=%s",
                provider,
                model,
                input_cost,
                output_cost,
            )
            continue

        stmt = pg_insert(LLMPricing).values(
            provider=provider,
            model=model,
            operator=operator,
            input_per_1m_usd=input_cost,
            output_per_1m_usd=output_cost,
            source="helicone",
            last_synced_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_llm_pricing_pmo",
            set_={
                "input_per_1m_usd": input_cost,
                "output_per_1m_usd": output_cost,
                "source": "helicone",
                "last_synced_at": now,
                "updated_at": now,
            },
        )
        await db.execute(stmt)
        upserted += 1

    if upserted > 0:
        await db.commit()
    return upserted


async def _run_sync_with_own_session() -> None:
    async with async_session_maker() as db:
        await sync_pricing_from_helicone(db)


async def ensure_pricing_synced(db: AsyncSession, *, force: bool = False) -> bool:
    """If pricing is stale (or `force`), schedule a background sync.
    Returns True if a sync task was scheduled.
    """
    if not force:
        result = await db.execute(select(func.max(LLMPricing.last_synced_at)))
        last_synced = result.scalar_one_or_none()
        if last_synced is not None:
            if last_synced.tzinfo is None:
                last_synced = last_synced.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - last_synced < SYNC_TTL:
                return False

    asyncio.create_task(_run_sync_with_own_session())
    return True
