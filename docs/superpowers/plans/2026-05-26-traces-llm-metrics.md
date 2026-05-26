# Traces LLM Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM metrics (KPIs, per-model token/cost donuts, calls-over-time chart) on the Traces screen, backed by a Helicone-synced global pricing table with per-user overrides, plus a shared time-range selector that filters both charts and the trace list.

**Architecture:** Two new global+per-user pricing tables seeded asynchronously from Helicone's JSON API. New `/api/traces/stats` endpoint computes KPIs/by-model/by-time aggregates per request, joining against the pricing tables in Python (operator semantics: equals/startsWith/includes). Existing `/api/traces` list endpoint gains a `range` query param to share the same time window as the stats endpoint. Frontend adds a stats header above the existing list and a new "LLM Cost Table" entry in the DataTables panel.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic + httpx (backend), Vue 3 + TypeScript strict + ApexCharts via vue3-apexcharts (frontend), pytest unittest (tests).

**Spec:** `docs/superpowers/specs/2026-05-26-traces-llm-metrics-design.md`

---

## File Structure

### Backend

| File | Action | Responsibility |
|---|---|---|
| `backend/alembic/versions/069_add_llm_pricing.py` | Create | Adds `llm_pricing`, `llm_pricing_override`, composite trace index |
| `backend/app/db/models.py` | Modify (append after `LLMTrace`) | `LLMPricing`, `LLMPricingOverride` ORM classes; add `Index("ix_llm_traces_user_created", ...)` to `LLMTrace.__table_args__` |
| `backend/app/models/schemas.py` | Modify (append) | `LLMPricingRow`, `LLMPricingPatch`, `LLMPricingCustomCreate`, `LLMPricingSyncStatus`, `TraceStatsResponse`, `TraceStatsKpis`, `TraceStatsByModel`, `TraceStatsByTime`, `TraceTimeRange` |
| `backend/app/services/llm_pricing.py` | Create | `resolve_costs_for_user()` resolver (in-memory match by operator) + small `_match_global_rule()` helper |
| `backend/app/services/llm_pricing_sync.py` | Create | `ensure_pricing_synced()` (TTL gate + async task) + `sync_pricing_from_helicone()` (httpx fetch + upsert) |
| `backend/app/api/llm_pricing.py` | Create | `GET /`, `GET /sync-status`, `POST /sync`, `PATCH /{model}`, `DELETE /{model}`, `POST /custom` |
| `backend/app/api/traces.py` | Modify | `GET /stats` endpoint; `range` query param on existing `list_traces` |
| `backend/app/main.py` | Modify (one line near other includes) | `app.include_router(llm_pricing.router, prefix="/api/llm-pricing", ...)` |

### Backend tests

| File | Action | Responsibility |
|---|---|---|
| `backend/tests/test_llm_pricing_resolver.py` | Create | Resolver matching logic (equals/startsWith/includes/override/unpriced) |
| `backend/tests/test_llm_pricing_sync.py` | Create | Helicone parse/upsert/TTL/failure-handling with mocked httpx |
| `backend/tests/test_llm_pricing_api.py` | Create | API endpoints with mocked DB |
| `backend/tests/test_traces_stats.py` | Create | Stats endpoint KPIs, by_model, by_time, filters, cost, user isolation |
| `backend/tests/test_traces_list_range.py` | Create | List endpoint backward compat + `range` param behavior |

### Frontend

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/types/trace.ts` | Modify | Add `TraceTimeRange`, `TraceStatsResponse`, sub-types |
| `frontend/src/types/pricing.ts` | Create | `LLMPricingRow`, `LLMPricingSyncStatus`, payload types |
| `frontend/src/services/api.ts` | Modify | Extend `traceApi` with `stats()` + `range` param; add `llmPricingApi` |
| `frontend/src/components/Traces/TracesTimeRangeSelect.vue` | Create | Select wrapper, 5 presets |
| `frontend/src/components/Traces/TracesStatsHeader.vue` | Create | 5 KPI cards + 3 ApexCharts |
| `frontend/src/components/Traces/TracesPanel.vue` | Modify | Add timeRange ref + stats fetch + render new components; pass range to list |
| `frontend/src/components/DataTable/LLMPricingPanel.vue` | Create | Fixed-schema editable grid for pricing rows |
| `frontend/src/components/DataTable/DataTablePanel.vue` | Modify | Add pinned "System tables → LLM Cost Table" entry |

### Documentation

- `heym-documentation` skill update for Traces page and DataTables (LLM Cost Table)

---

## Task 1: Migration + ORM models

**Files:**
- Create: `backend/alembic/versions/069_add_llm_pricing.py`
- Modify: `backend/app/db/models.py` (append new classes after `LLMTrace`, add composite index to `LLMTrace`)

- [ ] **Step 1: Add SQLAlchemy import for `Index` if missing**

Check `backend/app/db/models.py` imports. Confirm `from sqlalchemy import Index` is present (most projects already have it). If absent, add `Index` to the existing `from sqlalchemy import ...` line.

- [ ] **Step 2: Add composite index to `LLMTrace`**

In `backend/app/db/models.py`, find `class LLMTrace(Base):` (~line 466). Add `__table_args__` immediately after `__tablename__ = "llm_traces"`:

```python
class LLMTrace(Base):
    __tablename__ = "llm_traces"
    __table_args__ = (
        Index("ix_llm_traces_user_created", "user_id", "created_at"),
    )
```

- [ ] **Step 3: Append ORM classes for pricing tables**

Add to `backend/app/db/models.py` after the `LLMTrace` class:

```python
class LLMPricing(Base):
    __tablename__ = "llm_pricing"
    __table_args__ = (
        UniqueConstraint("provider", "model", "operator", name="uq_llm_pricing_pmo"),
        Index("ix_llm_pricing_model", "model"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    operator: Mapped[str] = mapped_column(String(20), nullable=False, default="equals")
    input_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    output_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="helicone")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMPricingOverride(Base):
    __tablename__ = "llm_pricing_override"
    __table_args__ = (
        UniqueConstraint("user_id", "model", name="uq_llm_pricing_override_user_model"),
        Index("ix_llm_pricing_override_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    input_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    output_per_1m_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_pricing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_pricing.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User")
    base_pricing: Mapped["LLMPricing | None"] = relationship("LLMPricing")
```

Confirm `Decimal`, `Numeric`, `Text`, `UniqueConstraint`, `Index`, `relationship` are imported at the top of the file. Add to the existing import lines if any are missing:

```python
from decimal import Decimal
from sqlalchemy import ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
```

- [ ] **Step 4: Write the Alembic migration**

Create `backend/alembic/versions/069_add_llm_pricing.py`:

```python
"""add llm pricing tables and composite trace index

Revision ID: 069
Revises: 068
Create Date: 2026-05-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "069"
down_revision: str | None = "068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_pricing",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("operator", sa.String(20), nullable=False, server_default="equals"),
        sa.Column("input_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="helicone"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model", "operator", name="uq_llm_pricing_pmo"),
    )
    op.create_index("ix_llm_pricing_model", "llm_pricing", ["model"])

    op.create_table(
        "llm_pricing_override",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("input_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("output_per_1m_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("base_pricing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["base_pricing_id"], ["llm_pricing.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "model", name="uq_llm_pricing_override_user_model"),
    )
    op.create_index("ix_llm_pricing_override_user", "llm_pricing_override", ["user_id"])

    op.create_index("ix_llm_traces_user_created", "llm_traces", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_traces_user_created", table_name="llm_traces")
    op.drop_index("ix_llm_pricing_override_user", table_name="llm_pricing_override")
    op.drop_table("llm_pricing_override")
    op.drop_index("ix_llm_pricing_model", table_name="llm_pricing")
    op.drop_table("llm_pricing")
```

- [ ] **Step 5: Apply migration and verify**

```bash
cd backend && uv run alembic upgrade head
```

Expected: ends with `INFO  [alembic.runtime.migration] Running upgrade 068 -> 069`. No errors.

Verify the tables exist:

```bash
docker exec -i heym-postgres-1 psql -U heym -d heym -c "\d llm_pricing"
docker exec -i heym-postgres-1 psql -U heym -d heym -c "\d llm_pricing_override"
docker exec -i heym-postgres-1 psql -U heym -d heym -c "\d llm_traces"
```

Expected: both new tables shown; `llm_traces` shows the new `ix_llm_traces_user_created` index.

(If the container name differs, run `docker ps` and substitute. Skip this verify if postgres isn't running locally — migration success in step 5 is sufficient.)

- [ ] **Step 6: Backend lint + formatter**

```bash
cd backend && uv run ruff format . && uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/069_add_llm_pricing.py backend/app/db/models.py
git commit -m "feat(traces): add llm_pricing tables and composite trace index"
```

---

## Task 2: Pricing resolver service (TDD)

**Files:**
- Create: `backend/app/services/llm_pricing.py`
- Test: `backend/tests/test_llm_pricing_resolver.py`

- [ ] **Step 1: Write the failing test file**

Create `backend/tests/test_llm_pricing_resolver.py`:

```python
import unittest
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

from app.services.llm_pricing import resolve_costs_for_user


class _Row:
    """Lightweight stand-in for ORM rows returned by db.execute(...).all()."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _global(model: str, op: str = "equals", inp: float = 1.0, out: float = 2.0) -> _Row:
    return _Row(
        provider="ANTHROPIC",
        model=model,
        operator=op,
        input_per_1m_usd=Decimal(str(inp)),
        output_per_1m_usd=Decimal(str(out)),
    )


def _override(model: str, inp: float = 0.5, out: float = 1.0) -> _Row:
    return _Row(
        model=model,
        input_per_1m_usd=Decimal(str(inp)),
        output_per_1m_usd=Decimal(str(out)),
    )


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user_id = uuid.uuid4()

    def _db_with(self, globals_=(), overrides=()) -> AsyncMock:
        db = AsyncMock()
        scalars_global = AsyncMock()
        scalars_global.all = lambda: list(globals_)
        scalars_override = AsyncMock()
        scalars_override.all = lambda: list(overrides)
        exec_global = AsyncMock(); exec_global.scalars = lambda: scalars_global
        exec_override = AsyncMock(); exec_override.scalars = lambda: scalars_override
        db.execute = AsyncMock(side_effect=[exec_global, exec_override])
        return db

    async def test_equals_match_computes_cost(self):
        db = self._db_with(globals_=[_global("gpt-4o", "equals", 5, 15)])
        out = await resolve_costs_for_user(
            db, self.user_id, [("gpt-4o", 1_000_000, 1_000_000)]
        )
        self.assertEqual(out, [(Decimal("20"), True)])

    async def test_startswith_picks_longest_match(self):
        db = self._db_with(globals_=[
            _global("gpt-4", "startsWith", 1, 2),
            _global("gpt-4o-mini", "startsWith", 10, 20),
        ])
        out = await resolve_costs_for_user(
            db, self.user_id, [("gpt-4o-mini-2024-07-18", 1_000_000, 0)]
        )
        self.assertEqual(out, [(Decimal("10"), True)])

    async def test_includes_match(self):
        db = self._db_with(globals_=[_global("haiku", "includes", 0.25, 1.25)])
        out = await resolve_costs_for_user(
            db, self.user_id, [("claude-3-haiku-20240307", 0, 1_000_000)]
        )
        self.assertEqual(out, [(Decimal("1.25"), True)])

    async def test_override_beats_global(self):
        db = self._db_with(
            globals_=[_global("gpt-4o", "equals", 5, 15)],
            overrides=[_override("gpt-4o", 1, 3)],
        )
        out = await resolve_costs_for_user(
            db, self.user_id, [("gpt-4o", 1_000_000, 1_000_000)]
        )
        self.assertEqual(out, [(Decimal("4"), True)])

    async def test_unpriced_returns_none(self):
        db = self._db_with()
        out = await resolve_costs_for_user(
            db, self.user_id, [("never-heard-of-it", 100, 100)]
        )
        self.assertEqual(out, [(None, False)])

    async def test_empty_token_pairs_short_circuits(self):
        db = AsyncMock()
        out = await resolve_costs_for_user(db, self.user_id, [])
        self.assertEqual(out, [])
        db.execute.assert_not_called()

    async def test_equals_priority_over_startswith(self):
        db = self._db_with(globals_=[
            _global("gpt-4o", "startsWith", 10, 20),
            _global("gpt-4o", "equals", 1, 2),
        ])
        out = await resolve_costs_for_user(
            db, self.user_id, [("gpt-4o", 1_000_000, 0)]
        )
        self.assertEqual(out, [(Decimal("1"), True)])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_llm_pricing_resolver.py -v
```

Expected: `ImportError: cannot import name 'resolve_costs_for_user' from 'app.services.llm_pricing'` (or `ModuleNotFoundError`).

- [ ] **Step 3: Implement the resolver**

Create `backend/app/services/llm_pricing.py`:

```python
"""LLM pricing resolver: matches trace models against global pricing rows + user overrides."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMPricing, LLMPricingOverride


def _match_global_rule(model: str, rules: list[LLMPricing]) -> LLMPricing | None:
    """Apply Helicone operator semantics. Priority: equals > startsWith > includes.
    Within startsWith/includes, the longest matching rule.model wins (most specific).
    """
    equals_match = next(
        (r for r in rules if r.operator == "equals" and r.model == model), None
    )
    if equals_match is not None:
        return equals_match

    starts = [r for r in rules if r.operator == "startsWith" and model.startswith(r.model)]
    if starts:
        return max(starts, key=lambda r: len(r.model))

    includes = [r for r in rules if r.operator == "includes" and r.model in model]
    if includes:
        return max(includes, key=lambda r: len(r.model))

    return None


async def resolve_costs_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    model_token_pairs: list[tuple[str, int, int]],
) -> list[tuple[Decimal | None, bool]]:
    """For each (model, prompt_tokens, completion_tokens), return (cost_usd, is_priced).

    Fetches all global + user-override rows once and resolves in-memory.
    """
    if not model_token_pairs:
        return []

    global_result = await db.execute(select(LLMPricing))
    global_rules: list[LLMPricing] = list(global_result.scalars().all())

    override_result = await db.execute(
        select(LLMPricingOverride).where(LLMPricingOverride.user_id == user_id)
    )
    overrides: list[LLMPricingOverride] = list(override_result.scalars().all())
    override_by_model = {o.model: o for o in overrides}

    out: list[tuple[Decimal | None, bool]] = []
    for model, prompt_tok, completion_tok in model_token_pairs:
        prompt_tok = max(0, int(prompt_tok or 0))
        completion_tok = max(0, int(completion_tok or 0))

        override = override_by_model.get(model)
        if override is not None:
            cost = (
                Decimal(prompt_tok) * override.input_per_1m_usd
                + Decimal(completion_tok) * override.output_per_1m_usd
            ) / Decimal(1_000_000)
            out.append((cost, True))
            continue

        rule = _match_global_rule(model, global_rules)
        if rule is None:
            out.append((None, False))
            continue

        cost = (
            Decimal(prompt_tok) * rule.input_per_1m_usd
            + Decimal(completion_tok) * rule.output_per_1m_usd
        ) / Decimal(1_000_000)
        out.append((cost, True))

    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_llm_pricing_resolver.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Format + lint**

```bash
cd backend && uv run ruff format . && uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/llm_pricing.py backend/tests/test_llm_pricing_resolver.py
git commit -m "feat(traces): add llm pricing resolver with helicone operator semantics"
```

---

## Task 3: Helicone sync service (TDD)

**Files:**
- Create: `backend/app/services/llm_pricing_sync.py`
- Test: `backend/tests/test_llm_pricing_sync.py`

- [ ] **Step 1: Write the failing test file**

Create `backend/tests/test_llm_pricing_sync.py`:

```python
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.llm_pricing_sync import (
    HELICONE_URL,
    ensure_pricing_synced,
    sync_pricing_from_helicone,
)

SAMPLE_PAYLOAD = {
    "metadata": {"total_models": 2},
    "data": [
        {
            "provider": "ANTHROPIC",
            "model": "claude-3-5-sonnet-20241022",
            "operator": "equals",
            "input_cost_per_1m": 3.0,
            "output_cost_per_1m": 15.0,
        },
        {
            "provider": "OPENAI",
            "model": "gpt-4o",
            "operator": "equals",
            "input_cost_per_1m": 5.0,
            "output_cost_per_1m": 15.0,
        },
    ],
}


def _mock_httpx_get(payload=SAMPLE_PAYLOAD, status_code=200, raise_exc=None):
    async def _get(url, *a, **kw):
        if raise_exc is not None:
            raise raise_exc
        resp = MagicMock()
        resp.status_code = status_code
        resp.json = MagicMock(return_value=payload)
        resp.raise_for_status = MagicMock()
        return resp

    return _get


class SyncFromHeliconeTests(unittest.IsolatedAsyncioTestCase):
    async def test_upserts_helicone_rows(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch("httpx.AsyncClient") as client_cls:
            instance = client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_mock_httpx_get())
            inserted = await sync_pricing_from_helicone(db)
        self.assertEqual(inserted, 2)
        self.assertEqual(db.execute.await_count, 2)  # one upsert per row
        db.commit.assert_awaited_once()

    async def test_fetch_failure_logs_and_returns_zero(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch("httpx.AsyncClient") as client_cls:
            instance = client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(
                side_effect=_mock_httpx_get(raise_exc=httpx.ConnectError("boom"))
            )
            inserted = await sync_pricing_from_helicone(db)
        self.assertEqual(inserted, 0)
        db.execute.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_bad_payload_handled(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()
        with patch("httpx.AsyncClient") as client_cls:
            instance = client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=_mock_httpx_get(payload={"nope": True}))
            inserted = await sync_pricing_from_helicone(db)
        self.assertEqual(inserted, 0)


class EnsurePricingSyncedTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_fresh_within_ttl(self):
        db = AsyncMock()
        fresh = datetime.now(timezone.utc) - timedelta(hours=1)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=fresh)
        db.execute = AsyncMock(return_value=scalar_result)

        with patch("app.services.llm_pricing_sync.sync_pricing_from_helicone") as sync_mock:
            sync_mock.return_value = 0
            triggered = await ensure_pricing_synced(db, force=False)
        self.assertFalse(triggered)
        sync_mock.assert_not_called()

    async def test_schedules_async_sync_when_stale(self):
        db = AsyncMock()
        stale = datetime.now(timezone.utc) - timedelta(hours=48)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=stale)
        db.execute = AsyncMock(return_value=scalar_result)

        with (
            patch("app.services.llm_pricing_sync.SessionLocal") as session_cls,
            patch("app.services.llm_pricing_sync.sync_pricing_from_helicone", AsyncMock(return_value=2)) as sync_mock,
        ):
            session_ctx = session_cls.return_value
            session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
            session_ctx.__aexit__ = AsyncMock(return_value=False)
            triggered = await ensure_pricing_synced(db, force=False)
            # Allow the spawned task to run
            import asyncio
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertTrue(triggered)
        sync_mock.assert_awaited()

    async def test_force_bypasses_ttl(self):
        db = AsyncMock()
        fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=fresh)
        db.execute = AsyncMock(return_value=scalar_result)

        with (
            patch("app.services.llm_pricing_sync.SessionLocal") as session_cls,
            patch("app.services.llm_pricing_sync.sync_pricing_from_helicone", AsyncMock(return_value=0)),
        ):
            session_ctx = session_cls.return_value
            session_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
            session_ctx.__aexit__ = AsyncMock(return_value=False)
            triggered = await ensure_pricing_synced(db, force=True)
        self.assertTrue(triggered)


class HeliconeUrlTests(unittest.TestCase):
    def test_helicone_url_constant(self):
        self.assertEqual(HELICONE_URL, "https://www.helicone.ai/api/llm-costs")
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && uv run pytest tests/test_llm_pricing_sync.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the sync service**

Create `backend/app/services/llm_pricing_sync.py`:

```python
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
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

HELICONE_URL = "https://www.helicone.ai/api/llm-costs"
SYNC_TTL = timedelta(hours=24)
HTTP_TIMEOUT = 10.0


async def sync_pricing_from_helicone(db: AsyncSession) -> int:
    """Fetch Helicone payload and upsert rows. Returns count of upserted rows
    (0 on fetch/parse failure)."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(
                HELICONE_URL, headers={"User-Agent": "heym/1.0"}
            )
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
    async with SessionLocal() as db:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_llm_pricing_sync.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Format + lint**

```bash
cd backend && uv run ruff format . && uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/llm_pricing_sync.py backend/tests/test_llm_pricing_sync.py
git commit -m "feat(traces): add helicone llm pricing sync service"
```

---

## Task 4: Pricing Pydantic schemas

**Files:**
- Modify: `backend/app/models/schemas.py` (append)

- [ ] **Step 1: Append pricing schemas to `schemas.py`**

Add to the end of `backend/app/models/schemas.py`:

```python
class LLMPricingRow(BaseModel):
    """Merged view: global pricing rows + this user's overrides applied."""

    id: uuid.UUID
    provider: str | None  # null for user-added custom rows
    model: str
    operator: str  # equals | startsWith | includes
    input_per_1m_usd: Decimal
    output_per_1m_usd: Decimal
    source: str  # 'helicone' | 'seed' | 'user'
    is_override: bool
    is_custom: bool
    override_id: uuid.UUID | None = None
    updated_at: datetime


class LLMPricingPatch(BaseModel):
    input_per_1m_usd: Decimal = Field(gt=Decimal("0"))
    output_per_1m_usd: Decimal = Field(gt=Decimal("0"))
    note: str | None = None


class LLMPricingCustomCreate(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    input_per_1m_usd: Decimal = Field(gt=Decimal("0"))
    output_per_1m_usd: Decimal = Field(gt=Decimal("0"))
    note: str | None = None


class LLMPricingSyncStatus(BaseModel):
    last_synced_at: datetime | None
    total_rows: int
    override_rows: int


TraceTimeRange = Literal["1h", "24h", "7d", "30d", "all"]


class TraceStatsRangeMeta(BaseModel):
    start: datetime | None
    end: datetime
    bucket_seconds: int


class TraceStatsKpis(BaseModel):
    total_calls: int
    success_calls: int
    error_calls: int
    error_pct: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    total_cost_usd: Decimal
    avg_latency_ms: float
    unpriced_models: list[str]


class TraceStatsByModel(BaseModel):
    model: str
    provider: str | None
    calls: int
    total_tokens: int
    cost_usd: Decimal
    is_priced: bool
    is_other: bool = False


class TraceStatsByTime(BaseModel):
    bucket_start: datetime
    calls: int
    success: int
    error: int
    total_tokens: int
    cost_usd: Decimal


class TraceStatsResponse(BaseModel):
    range: TraceStatsRangeMeta
    kpis: TraceStatsKpis
    by_model: list[TraceStatsByModel]
    by_time: list[TraceStatsByTime]
```

Confirm imports at the top of `schemas.py` include `from decimal import Decimal`, `from datetime import datetime`, `from typing import Literal`, `from pydantic import Field`. Add any that are missing to the existing import block (do not duplicate).

- [ ] **Step 2: Run the schema module import smoke test**

```bash
cd backend && uv run python -c "from app.models.schemas import LLMPricingRow, TraceStatsResponse, TraceTimeRange; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Format + lint**

```bash
cd backend && uv run ruff format . && uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat(traces): add pydantic schemas for pricing and trace stats"
```

---

## Task 5: Pricing API endpoints (TDD)

**Files:**
- Create: `backend/app/api/llm_pricing.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_llm_pricing_api.py`

- [ ] **Step 1: Write the failing API test file**

Create `backend/tests/test_llm_pricing_api.py`:

```python
import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.llm_pricing import (
    create_custom_pricing,
    delete_pricing_override,
    list_pricing,
    sync_now,
    sync_status,
    update_pricing,
)
from app.models.schemas import LLMPricingCustomCreate, LLMPricingPatch


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _global(model="gpt-4o", op="equals"):
    return _Row(
        id=uuid.uuid4(),
        provider="OPENAI",
        model=model,
        operator=op,
        input_per_1m_usd=Decimal("5"),
        output_per_1m_usd=Decimal("15"),
        source="helicone",
        last_synced_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _override(model="gpt-4o", base_id=None):
    return _Row(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        model=model,
        input_per_1m_usd=Decimal("1"),
        output_per_1m_usd=Decimal("3"),
        note=None,
        base_pricing_id=base_id,
        updated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )


def _exec_with(items):
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=items)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    return result


class ListPricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_merges_global_with_overrides(self):
        user = MagicMock(); user.id = uuid.uuid4()
        global_row = _global("gpt-4o")
        override_row = _override("gpt-4o", base_id=global_row.id)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _exec_with([global_row]),
            _exec_with([override_row]),
        ])
        with patch("app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=False)):
            rows = await list_pricing(current_user=user, db=db)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row.is_override)
        self.assertFalse(row.is_custom)
        self.assertEqual(row.input_per_1m_usd, Decimal("1"))  # override prices
        self.assertEqual(row.output_per_1m_usd, Decimal("3"))
        self.assertEqual(row.provider, "OPENAI")  # global identity

    async def test_list_includes_custom_only_rows(self):
        user = MagicMock(); user.id = uuid.uuid4()
        custom = _override("my-private-model", base_id=None)
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _exec_with([]),
            _exec_with([custom]),
        ])
        with patch("app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=False)):
            rows = await list_pricing(current_user=user, db=db)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].is_custom)
        self.assertIsNone(rows[0].provider)


class UpdatePricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_creates_override(self):
        user = MagicMock(); user.id = uuid.uuid4()
        global_row = _global("gpt-4o")
        db = AsyncMock()
        # Look up global by model -> returns one row
        scalar1 = MagicMock(); scalar1.scalar_one_or_none = MagicMock(return_value=global_row)
        # Look up existing override -> none
        scalar2 = MagicMock(); scalar2.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[scalar1, scalar2])
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        payload = LLMPricingPatch(input_per_1m_usd=Decimal("2"), output_per_1m_usd=Decimal("6"))
        result = await update_pricing(
            model_name="gpt-4o", payload=payload, current_user=user, db=db
        )
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        self.assertEqual(added.user_id, user.id)
        self.assertEqual(added.model, "gpt-4o")
        self.assertEqual(added.base_pricing_id, global_row.id)
        self.assertEqual(result.input_per_1m_usd, Decimal("2"))

    async def test_patch_updates_existing_override(self):
        user = MagicMock(); user.id = uuid.uuid4()
        existing = _override("gpt-4o", base_id=uuid.uuid4())
        db = AsyncMock()
        scalar1 = MagicMock(); scalar1.scalar_one_or_none = MagicMock(return_value=None)  # global missing
        scalar2 = MagicMock(); scalar2.scalar_one_or_none = MagicMock(return_value=existing)
        db.execute = AsyncMock(side_effect=[scalar1, scalar2])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        payload = LLMPricingPatch(input_per_1m_usd=Decimal("9"), output_per_1m_usd=Decimal("10"))
        result = await update_pricing(
            model_name="gpt-4o", payload=payload, current_user=user, db=db
        )
        self.assertEqual(existing.input_per_1m_usd, Decimal("9"))
        self.assertEqual(result.output_per_1m_usd, Decimal("10"))

    async def test_patch_404_when_neither_exists(self):
        user = MagicMock(); user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock(); scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[scalar, scalar])
        with self.assertRaises(HTTPException) as ctx:
            await update_pricing(
                model_name="ghost",
                payload=LLMPricingPatch(input_per_1m_usd=Decimal("1"), output_per_1m_usd=Decimal("2")),
                current_user=user,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 404)


class DeletePricingTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_removes_existing_override(self):
        user = MagicMock(); user.id = uuid.uuid4()
        override = _override("gpt-4o", base_id=uuid.uuid4())
        db = AsyncMock()
        scalar = MagicMock(); scalar.scalar_one_or_none = MagicMock(return_value=override)
        db.execute = AsyncMock(return_value=scalar)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        await delete_pricing_override(model_name="gpt-4o", current_user=user, db=db)
        db.delete.assert_awaited_once_with(override)
        db.commit.assert_awaited_once()

    async def test_delete_404_when_missing(self):
        user = MagicMock(); user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock(); scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=scalar)
        with self.assertRaises(HTTPException) as ctx:
            await delete_pricing_override(model_name="ghost", current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 404)


class CustomCreateTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_custom_row(self):
        user = MagicMock(); user.id = uuid.uuid4()
        db = AsyncMock()
        scalar = MagicMock(); scalar.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=scalar)
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        payload = LLMPricingCustomCreate(
            model="org/private-model",
            input_per_1m_usd=Decimal("2"),
            output_per_1m_usd=Decimal("4"),
        )
        result = await create_custom_pricing(payload=payload, current_user=user, db=db)
        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        self.assertIsNone(added.base_pricing_id)
        self.assertEqual(added.model, "org/private-model")
        self.assertEqual(result.model, "org/private-model")
        self.assertTrue(result.is_custom)
        self.assertIsNone(result.provider)

    async def test_creates_custom_409_when_duplicate(self):
        user = MagicMock(); user.id = uuid.uuid4()
        existing = _override("org/private-model")
        db = AsyncMock()
        scalar = MagicMock(); scalar.scalar_one_or_none = MagicMock(return_value=existing)
        db.execute = AsyncMock(return_value=scalar)
        with self.assertRaises(HTTPException) as ctx:
            await create_custom_pricing(
                payload=LLMPricingCustomCreate(
                    model="org/private-model",
                    input_per_1m_usd=Decimal("1"),
                    output_per_1m_usd=Decimal("2"),
                ),
                current_user=user,
                db=db,
            )
        self.assertEqual(ctx.exception.status_code, 409)


class SyncEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_status_returns_counts(self):
        user = MagicMock(); user.id = uuid.uuid4()
        db = AsyncMock()
        s1 = MagicMock(); s1.scalar_one_or_none = MagicMock(return_value=datetime.now(timezone.utc))
        s2 = MagicMock(); s2.scalar_one = MagicMock(return_value=42)
        s3 = MagicMock(); s3.scalar_one = MagicMock(return_value=3)
        db.execute = AsyncMock(side_effect=[s1, s2, s3])
        result = await sync_status(current_user=user, db=db)
        self.assertEqual(result.total_rows, 42)
        self.assertEqual(result.override_rows, 3)

    async def test_sync_now_triggers_force(self):
        user = MagicMock(); user.id = uuid.uuid4()
        db = AsyncMock()
        with patch("app.api.llm_pricing.ensure_pricing_synced", AsyncMock(return_value=True)) as ensure_mock:
            await sync_now(current_user=user, db=db)
        ensure_mock.assert_awaited_once_with(db, force=True)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && uv run pytest tests/test_llm_pricing_api.py -v
```

Expected: `ModuleNotFoundError: app.api.llm_pricing`.

- [ ] **Step 3: Implement the API**

Create `backend/app/api/llm_pricing.py`:

```python
"""LLM pricing API: merged global + per-user override view, sync, custom rows."""

import uuid
from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import LLMPricing, LLMPricingOverride, User
from app.db.session import get_db
from app.models.schemas import (
    LLMPricingCustomCreate,
    LLMPricingPatch,
    LLMPricingRow,
    LLMPricingSyncStatus,
)
from app.services.llm_pricing_sync import ensure_pricing_synced

router = APIRouter()


def _global_to_row(g: LLMPricing) -> LLMPricingRow:
    return LLMPricingRow(
        id=g.id,
        provider=g.provider,
        model=g.model,
        operator=g.operator,
        input_per_1m_usd=g.input_per_1m_usd,
        output_per_1m_usd=g.output_per_1m_usd,
        source=g.source,
        is_override=False,
        is_custom=False,
        override_id=None,
        updated_at=g.updated_at,
    )


def _apply_override(base: LLMPricingRow, override: LLMPricingOverride) -> LLMPricingRow:
    return base.model_copy(update={
        "input_per_1m_usd": override.input_per_1m_usd,
        "output_per_1m_usd": override.output_per_1m_usd,
        "is_override": True,
        "override_id": override.id,
        "updated_at": override.updated_at,
    })


def _custom_to_row(o: LLMPricingOverride) -> LLMPricingRow:
    return LLMPricingRow(
        id=o.id,
        provider=None,
        model=o.model,
        operator="equals",
        input_per_1m_usd=o.input_per_1m_usd,
        output_per_1m_usd=o.output_per_1m_usd,
        source="user",
        is_override=False,
        is_custom=True,
        override_id=o.id,
        updated_at=o.updated_at,
    )


@router.get("", response_model=list[LLMPricingRow])
async def list_pricing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LLMPricingRow]:
    """Merged view: every global row, with this user's overrides applied,
    plus the user's custom-only rows appended."""
    await ensure_pricing_synced(db, force=False)

    globals_result = await db.execute(select(LLMPricing))
    globals_list: list[LLMPricing] = list(globals_result.scalars().all())

    overrides_result = await db.execute(
        select(LLMPricingOverride).where(LLMPricingOverride.user_id == current_user.id)
    )
    overrides_list: list[LLMPricingOverride] = list(overrides_result.scalars().all())
    overrides_by_model = {o.model: o for o in overrides_list}
    custom_overrides = [o for o in overrides_list if o.base_pricing_id is None]

    rows: list[LLMPricingRow] = []
    seen_models: set[str] = set()
    for g in globals_list:
        base = _global_to_row(g)
        if g.model in overrides_by_model:
            rows.append(_apply_override(base, overrides_by_model[g.model]))
        else:
            rows.append(base)
        seen_models.add(g.model)

    for o in custom_overrides:
        if o.model in seen_models:
            continue
        rows.append(_custom_to_row(o))

    rows.sort(key=lambda r: ((r.provider or "ZZZ"), r.model))
    return rows


@router.get("/sync-status", response_model=LLMPricingSyncStatus)
async def sync_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMPricingSyncStatus:
    last_synced_result = await db.execute(select(func.max(LLMPricing.last_synced_at)))
    last_synced = last_synced_result.scalar_one_or_none()

    total_result = await db.execute(select(func.count()).select_from(LLMPricing))
    override_result = await db.execute(
        select(func.count())
        .select_from(LLMPricingOverride)
        .where(LLMPricingOverride.user_id == current_user.id)
    )
    return LLMPricingSyncStatus(
        last_synced_at=last_synced,
        total_rows=total_result.scalar_one(),
        override_rows=override_result.scalar_one(),
    )


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_now(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await ensure_pricing_synced(db, force=True)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.patch("/{model_name:path}", response_model=LLMPricingRow)
async def update_pricing(
    model_name: str,
    payload: LLMPricingPatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMPricingRow:
    model_name = unquote(model_name)

    global_result = await db.execute(
        select(LLMPricing).where(LLMPricing.model == model_name).limit(1)
    )
    global_row = global_result.scalar_one_or_none()

    override_result = await db.execute(
        select(LLMPricingOverride).where(
            LLMPricingOverride.user_id == current_user.id,
            LLMPricingOverride.model == model_name,
        )
    )
    override = override_result.scalar_one_or_none()

    if global_row is None and override is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found. Use POST /custom to add a new model.",
        )

    if override is None:
        override = LLMPricingOverride(
            user_id=current_user.id,
            model=model_name,
            input_per_1m_usd=payload.input_per_1m_usd,
            output_per_1m_usd=payload.output_per_1m_usd,
            note=payload.note,
            base_pricing_id=global_row.id if global_row is not None else None,
        )
        db.add(override)
    else:
        override.input_per_1m_usd = payload.input_per_1m_usd
        override.output_per_1m_usd = payload.output_per_1m_usd
        override.note = payload.note
        override.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(override)

    if global_row is not None:
        return _apply_override(_global_to_row(global_row), override)
    return _custom_to_row(override)


@router.delete("/{model_name:path}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pricing_override(
    model_name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    model_name = unquote(model_name)
    result = await db.execute(
        select(LLMPricingOverride).where(
            LLMPricingOverride.user_id == current_user.id,
            LLMPricingOverride.model == model_name,
        )
    )
    override = result.scalar_one_or_none()
    if override is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No override found")
    await db.delete(override)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/custom", response_model=LLMPricingRow, status_code=status.HTTP_201_CREATED)
async def create_custom_pricing(
    payload: LLMPricingCustomCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMPricingRow:
    result = await db.execute(
        select(LLMPricingOverride).where(
            LLMPricingOverride.user_id == current_user.id,
            LLMPricingOverride.model == payload.model,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A row for this model already exists for your user.",
        )

    row = LLMPricingOverride(
        user_id=current_user.id,
        model=payload.model,
        input_per_1m_usd=payload.input_per_1m_usd,
        output_per_1m_usd=payload.output_per_1m_usd,
        note=payload.note,
        base_pricing_id=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _custom_to_row(row)
```

- [ ] **Step 4: Mount the router in `main.py`**

In `backend/app/main.py`, find the block of `app.include_router(...)` calls near line 197-235. Add the import alongside the existing `from app.api import (...)` block (find the multi-line import that contains `traces`, add `llm_pricing` to it). Then add this line near the `traces` router include (around line 223):

```python
app.include_router(llm_pricing.router, prefix="/api/llm-pricing", tags=["LLM Pricing"])
```

- [ ] **Step 5: Run API tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_llm_pricing_api.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Format + lint + full test sweep**

```bash
cd backend && uv run ruff format . && uv run ruff check . && uv run pytest tests/test_llm_pricing_resolver.py tests/test_llm_pricing_sync.py tests/test_llm_pricing_api.py -v
```

Expected: ruff clean, all 3 suites PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/llm_pricing.py backend/app/main.py backend/tests/test_llm_pricing_api.py
git commit -m "feat(traces): add /api/llm-pricing endpoints (list, sync, patch, delete, custom)"
```

---

## Task 6: Range helpers + Stats endpoint (TDD)

**Files:**
- Modify: `backend/app/api/traces.py`
- Test: `backend/tests/test_traces_stats.py`

This task covers both the range/bucket helpers and the `/stats` endpoint. Because the endpoint uses three SQL queries that are awkward to mock individually, the unit tests focus on the helper functions and a small end-to-end integration test that constructs traces via a fake `db.execute` returning real-looking aggregate rows.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_traces_stats.py`:

```python
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.traces import (
    _resolve_range,
    get_trace_stats,
)


class RangeResolverTests(unittest.TestCase):
    def _fixed_now(self) -> datetime:
        return datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)

    def test_1h_window_5min_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("1h", now=now)
        self.assertEqual(end, now)
        self.assertEqual(start, now - timedelta(hours=1))
        self.assertEqual(bucket, 300)

    def test_24h_window_1h_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("24h", now=now)
        self.assertEqual(start, now - timedelta(hours=24))
        self.assertEqual(bucket, 3600)

    def test_7d_window_6h_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("7d", now=now)
        self.assertEqual(start, now - timedelta(days=7))
        self.assertEqual(bucket, 6 * 3600)

    def test_30d_window_1d_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("30d", now=now)
        self.assertEqual(start, now - timedelta(days=30))
        self.assertEqual(bucket, 86400)

    def test_all_returns_none_start_with_day_bucket(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("all", now=now)
        self.assertIsNone(start)
        self.assertEqual(bucket, 86400)

    def test_invalid_range_defaults_to_7d(self):
        now = self._fixed_now()
        start, end, bucket = _resolve_range("invalid", now=now)
        self.assertEqual(start, now - timedelta(days=7))


class StatsEndpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.user = MagicMock()
        self.user.id = uuid.uuid4()

    async def test_empty_returns_zero_kpis(self):
        db = AsyncMock()
        # KPI query: row with all-None aggregates
        kpi_row = MagicMock()
        kpi_row.total_calls = 0
        kpi_row.error_calls = 0
        kpi_row.prompt_tokens = 0
        kpi_row.completion_tokens = 0
        kpi_row.total_tokens = 0
        kpi_row.avg_elapsed_ms = None
        kpi_result = MagicMock(); kpi_result.one = MagicMock(return_value=kpi_row)

        # by_model + by_time both empty
        empty_result = MagicMock(); empty_result.all = MagicMock(return_value=[])

        db.execute = AsyncMock(side_effect=[kpi_result, empty_result, empty_result])

        with patch("app.api.traces.resolve_costs_for_user", AsyncMock(return_value=[])):
            response = await get_trace_stats(
                range="7d", source=None, credential_id=None,
                workflow_id=None, status_filter=None, search=None,
                current_user=self.user, db=db,
            )
        self.assertEqual(response.kpis.total_calls, 0)
        self.assertEqual(response.kpis.total_cost_usd, Decimal("0"))
        self.assertEqual(response.by_model, [])
        self.assertEqual(response.kpis.unpriced_models, [])

    async def test_kpis_and_by_model_aggregated(self):
        db = AsyncMock()
        kpi_row = MagicMock()
        kpi_row.total_calls = 10
        kpi_row.error_calls = 2
        kpi_row.prompt_tokens = 1000
        kpi_row.completion_tokens = 500
        kpi_row.total_tokens = 1500
        kpi_row.avg_elapsed_ms = 250.0
        kpi_result = MagicMock(); kpi_result.one = MagicMock(return_value=kpi_row)

        # by_model: two rows
        m_rows = [
            MagicMock(model="gpt-4o", provider="openai", calls=6, total_tokens=1000,
                      prompt_tokens=700, completion_tokens=300),
            MagicMock(model="unknown-x", provider=None, calls=4, total_tokens=500,
                      prompt_tokens=300, completion_tokens=200),
        ]
        m_result = MagicMock(); m_result.all = MagicMock(return_value=m_rows)

        # by_time: one bucket
        t_rows = [
            MagicMock(
                bucket_ts=datetime(2026, 5, 26, 0, 0, tzinfo=timezone.utc),
                model="gpt-4o",
                calls=10, success=8, error=2,
                prompt_tokens=1000, completion_tokens=500,
                total_tokens=1500,
            ),
        ]
        t_result = MagicMock(); t_result.all = MagicMock(return_value=t_rows)

        db.execute = AsyncMock(side_effect=[kpi_result, m_result, t_result])

        async def fake_resolve(_db, _uid, pairs):
            # gpt-4o priced; unknown-x not
            out = []
            for model, p, c in pairs:
                if model == "gpt-4o":
                    out.append((Decimal("0.10"), True))
                else:
                    out.append((None, False))
            return out

        with patch("app.api.traces.resolve_costs_for_user", side_effect=fake_resolve):
            response = await get_trace_stats(
                range="7d", source=None, credential_id=None,
                workflow_id=None, status_filter=None, search=None,
                current_user=self.user, db=db,
            )

        self.assertEqual(response.kpis.total_calls, 10)
        self.assertEqual(response.kpis.error_calls, 2)
        self.assertEqual(response.kpis.success_calls, 8)
        self.assertAlmostEqual(response.kpis.error_pct, 20.0, places=1)
        self.assertEqual(response.kpis.avg_latency_ms, 250.0)
        self.assertEqual(response.kpis.unpriced_models, ["unknown-x"])
        # by_model sorted by tokens desc
        self.assertEqual(response.by_model[0].model, "gpt-4o")
        self.assertEqual(response.by_model[0].cost_usd, Decimal("0.10"))
        self.assertFalse(response.by_model[1].is_priced)
        self.assertEqual(response.by_model[1].cost_usd, Decimal("0"))

    async def test_by_model_collapses_other_after_top8(self):
        db = AsyncMock()
        kpi_row = MagicMock(
            total_calls=10, error_calls=0,
            prompt_tokens=1000, completion_tokens=0,
            total_tokens=1000, avg_elapsed_ms=10.0,
        )
        kpi_result = MagicMock(); kpi_result.one = MagicMock(return_value=kpi_row)

        # 10 models: top 8 returned verbatim, last 2 collapsed
        m_rows = []
        for i in range(10):
            m_rows.append(MagicMock(
                model=f"m{i}", provider="openai",
                calls=10 - i, total_tokens=1000 - i * 50,
                prompt_tokens=500 - i * 25, completion_tokens=500 - i * 25,
            ))
        m_result = MagicMock(); m_result.all = MagicMock(return_value=m_rows)
        empty = MagicMock(); empty.all = MagicMock(return_value=[])

        db.execute = AsyncMock(side_effect=[kpi_result, m_result, empty])

        async def fake_resolve(_db, _uid, pairs):
            return [(Decimal("0.01"), True) for _ in pairs]

        with patch("app.api.traces.resolve_costs_for_user", side_effect=fake_resolve):
            response = await get_trace_stats(
                range="7d", source=None, credential_id=None,
                workflow_id=None, status_filter=None, search=None,
                current_user=self.user, db=db,
            )
        self.assertEqual(len(response.by_model), 9)  # 8 + 1 "Other"
        self.assertEqual(response.by_model[-1].model, "Other")
        self.assertTrue(response.by_model[-1].is_other)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && uv run pytest tests/test_traces_stats.py -v
```

Expected: `ImportError` for `_resolve_range` / `get_trace_stats`.

- [ ] **Step 3: Implement helpers + endpoint in `traces.py`**

Modify `backend/app/api/traces.py`. Add imports at the top (merge with existing):

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.schemas import (
    LLMTraceDetailResponse,
    LLMTraceListItem,
    LLMTraceListResponse,
    TraceStatsByModel,
    TraceStatsByTime,
    TraceStatsKpis,
    TraceStatsRangeMeta,
    TraceStatsResponse,
)
from app.services.llm_pricing import resolve_costs_for_user
from app.services.llm_pricing_sync import ensure_pricing_synced
```

(Adjust the existing `from app.models.schemas import ...` line — don't duplicate it.)

Add the range resolver helper above the existing routes:

```python
_RANGE_TABLE: dict[str, tuple[timedelta, int]] = {
    "1h": (timedelta(hours=1), 300),
    "24h": (timedelta(hours=24), 3600),
    "7d": (timedelta(days=7), 6 * 3600),
    "30d": (timedelta(days=30), 86400),
}


def _resolve_range(
    range_key: str, *, now: datetime | None = None
) -> tuple[datetime | None, datetime, int]:
    """Returns (start_dt or None, end_dt, bucket_seconds). 'all' returns start=None.
    Unknown range_key falls back to '7d'."""
    now = now or datetime.now(timezone.utc)
    if range_key == "all":
        return (None, now, 86400)
    delta, bucket = _RANGE_TABLE.get(range_key, _RANGE_TABLE["7d"])
    return (now - delta, now, bucket)


def _build_filters(
    user_id,
    *,
    source: str | None,
    credential_id,
    workflow_id,
    status_filter: str | None,
    search: str | None,
    start_dt: datetime | None,
):
    """Returns (where_clauses, joined_with_workflow_credential).
    Mirrors the list endpoint's filtering logic 1:1."""
    filters = [LLMTrace.user_id == user_id]
    if credential_id:
        filters.append(LLMTrace.credential_id == credential_id)
    if workflow_id:
        filters.append(LLMTrace.workflow_id == workflow_id)
    if source:
        filters.append(LLMTrace.source == source)
    if status_filter == "error":
        filters.append(LLMTrace.error.is_not(None))
    elif status_filter == "success":
        filters.append(LLMTrace.error.is_(None))
    if start_dt is not None:
        filters.append(LLMTrace.created_at >= start_dt)
    return filters
```

(Note `_build_filters` returns just `filters` for the stats endpoint; the list endpoint can keep its inline construction. The "joined_with_workflow_credential" name in the docstring was a working note — drop it from the docstring before committing.)

Then append the new endpoint at the end of `traces.py`:

```python
@router.get("/stats", response_model=TraceStatsResponse)
async def get_trace_stats(
    range: str = Query("7d", description="1h | 24h | 7d | 30d | all"),
    source: str | None = None,
    credential_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TraceStatsResponse:
    """Aggregate KPIs, per-model breakdown, and per-time-bucket series for the
    current user's LLM traces in the requested window."""
    await ensure_pricing_synced(db, force=False)

    start_dt, end_dt, bucket_seconds = _resolve_range(range)
    filters = _build_filters(
        current_user.id,
        source=source,
        credential_id=credential_id,
        workflow_id=workflow_id,
        status_filter=status_filter,
        search=search,
        start_dt=start_dt,
    )

    # Search filter needs joins; apply on each query that consults user-visible text
    def _apply_search(stmt):
        if not search:
            return stmt
        pattern = f"%{search}%"
        return stmt.outerjoin(
            Workflow, LLMTrace.workflow_id == Workflow.id
        ).outerjoin(
            Credential, LLMTrace.credential_id == Credential.id
        ).where(
            or_(
                LLMTrace.model.ilike(pattern),
                LLMTrace.node_label.ilike(pattern),
                Workflow.name.ilike(pattern),
                Credential.name.ilike(pattern),
                cast(LLMTrace.request, String).ilike(pattern),
                cast(LLMTrace.response, String).ilike(pattern),
            )
        )

    # 1. KPI aggregate
    kpi_stmt = _apply_search(
        select(
            func.count().label("total_calls"),
            func.sum(case((LLMTrace.error.is_not(None), 1), else_=0)).label("error_calls"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
            func.avg(LLMTrace.elapsed_ms).label("avg_elapsed_ms"),
        ).where(*filters)
    )
    kpi_row = (await db.execute(kpi_stmt)).one()

    # 2. By model
    by_model_stmt = _apply_search(
        select(
            LLMTrace.model.label("model"),
            LLMTrace.provider.label("provider"),
            func.count().label("calls"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("completion_tokens"),
        )
        .where(*filters)
        .group_by(LLMTrace.model, LLMTrace.provider)
        .order_by(func.coalesce(func.sum(LLMTrace.total_tokens), 0).desc())
    )
    by_model_rows = list((await db.execute(by_model_stmt)).all())

    # 3. By time + model (single query, folded in Python)
    bucket_expr = func.to_timestamp(
        func.floor(func.extract("epoch", LLMTrace.created_at) / bucket_seconds)
        * bucket_seconds
    ).label("bucket_ts")
    by_time_stmt = _apply_search(
        select(
            bucket_expr,
            LLMTrace.model.label("model"),
            func.count().label("calls"),
            func.sum(case((LLMTrace.error.is_(None), 1), else_=0)).label("success"),
            func.sum(case((LLMTrace.error.is_not(None), 1), else_=0)).label("error"),
            func.coalesce(func.sum(LLMTrace.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMTrace.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(LLMTrace.total_tokens), 0).label("total_tokens"),
        )
        .where(*filters)
        .group_by(bucket_expr, LLMTrace.model)
        .order_by(bucket_expr)
    )
    by_time_rows = list((await db.execute(by_time_stmt)).all())

    # Resolve costs once for all (model, prompt, completion) pairs from by_model
    model_pairs: list[tuple[str, int, int]] = [
        (r.model or "", int(r.prompt_tokens or 0), int(r.completion_tokens or 0))
        for r in by_model_rows
    ]
    model_costs = await resolve_costs_for_user(db, current_user.id, model_pairs)

    # Resolve costs for each (bucket, model) aggregate
    time_pairs: list[tuple[str, int, int]] = [
        (r.model or "", int(r.prompt_tokens or 0), int(r.completion_tokens or 0))
        for r in by_time_rows
    ]
    time_costs = await resolve_costs_for_user(db, current_user.id, time_pairs)

    # Build by_model with Top 8 + Other
    by_model: list[TraceStatsByModel] = []
    other_calls = 0
    other_tokens = 0
    other_cost = Decimal("0")
    for idx, (row, (cost, is_priced)) in enumerate(zip(by_model_rows, model_costs)):
        cost_value = cost if cost is not None else Decimal("0")
        if idx < 8:
            by_model.append(TraceStatsByModel(
                model=row.model or "(unknown)",
                provider=row.provider,
                calls=int(row.calls),
                total_tokens=int(row.total_tokens or 0),
                cost_usd=cost_value,
                is_priced=is_priced,
            ))
        else:
            other_calls += int(row.calls)
            other_tokens += int(row.total_tokens or 0)
            other_cost += cost_value
    if other_calls > 0:
        by_model.append(TraceStatsByModel(
            model="Other",
            provider=None,
            calls=other_calls,
            total_tokens=other_tokens,
            cost_usd=other_cost,
            is_priced=True,
            is_other=True,
        ))

    # Fold by_time across models
    by_time_map: dict[datetime, dict] = {}
    for row, (cost, _is_priced) in zip(by_time_rows, time_costs):
        bucket_ts = row.bucket_ts
        if bucket_ts.tzinfo is None:
            bucket_ts = bucket_ts.replace(tzinfo=timezone.utc)
        slot = by_time_map.setdefault(bucket_ts, {
            "calls": 0, "success": 0, "error": 0, "total_tokens": 0, "cost_usd": Decimal("0"),
        })
        slot["calls"] += int(row.calls)
        slot["success"] += int(row.success or 0)
        slot["error"] += int(row.error or 0)
        slot["total_tokens"] += int(row.total_tokens or 0)
        if cost is not None:
            slot["cost_usd"] += cost

    by_time = [
        TraceStatsByTime(
            bucket_start=ts,
            calls=v["calls"],
            success=v["success"],
            error=v["error"],
            total_tokens=v["total_tokens"],
            cost_usd=v["cost_usd"],
        )
        for ts, v in sorted(by_time_map.items(), key=lambda kv: kv[0])
    ]

    total_calls = int(kpi_row.total_calls or 0)
    error_calls = int(kpi_row.error_calls or 0)
    success_calls = total_calls - error_calls
    error_pct = (error_calls / total_calls * 100.0) if total_calls else 0.0
    total_cost_usd = sum((m.cost_usd for m in by_model), Decimal("0"))
    unpriced_models = [m.model for m in by_model if not m.is_priced and not m.is_other]

    return TraceStatsResponse(
        range=TraceStatsRangeMeta(start=start_dt, end=end_dt, bucket_seconds=bucket_seconds),
        kpis=TraceStatsKpis(
            total_calls=total_calls,
            success_calls=success_calls,
            error_calls=error_calls,
            error_pct=round(error_pct, 2),
            prompt_tokens=int(kpi_row.prompt_tokens or 0),
            completion_tokens=int(kpi_row.completion_tokens or 0),
            total_tokens=int(kpi_row.total_tokens or 0),
            total_cost_usd=total_cost_usd,
            avg_latency_ms=float(kpi_row.avg_elapsed_ms or 0.0),
            unpriced_models=unpriced_models,
        ),
        by_model=by_model,
        by_time=by_time,
    )
```

Add `case` to the existing SQLAlchemy import (top of file):

```python
from sqlalchemy import String, case, cast, delete, func, or_, select
```

- [ ] **Step 4: Run stats tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_traces_stats.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Format + lint**

```bash
cd backend && uv run ruff format . && uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/traces.py backend/tests/test_traces_stats.py
git commit -m "feat(traces): add /api/traces/stats aggregate endpoint"
```

---

## Task 7: List endpoint `range` parameter (TDD)

**Files:**
- Modify: `backend/app/api/traces.py` (signature of `list_traces`)
- Test: `backend/tests/test_traces_list_range.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_traces_list_range.py`:

```python
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.traces import list_traces


class _ExecResult:
    def __init__(self, items):
        self._items = items

    def scalar_one(self):
        return len(self._items)

    def all(self):
        return self._items


class ListRangeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = MagicMock()
        self.user.id = uuid.uuid4()

    async def _run(self, range_arg):
        db = AsyncMock()
        # First execute is count, second is page
        db.execute = AsyncMock(side_effect=[_ExecResult([]), _ExecResult([])])
        await list_traces(
            limit=25, offset=0, credential_id=None, workflow_id=None,
            source=None, status_filter=None, search=None, order="desc",
            range=range_arg,
            current_user=self.user, db=db,
        )
        return db

    async def test_range_param_applies_start_filter(self):
        with patch("app.api.traces._resolve_range") as resolve_mock:
            resolve_mock.return_value = (
                datetime(2026, 5, 19, tzinfo=timezone.utc),
                datetime(2026, 5, 26, tzinfo=timezone.utc),
                21600,
            )
            db = await self._run("7d")
        resolve_mock.assert_called_once_with("7d")
        # Both queries (count + page) were executed
        self.assertEqual(db.execute.await_count, 2)

    async def test_range_none_keeps_backward_compat_no_resolve_call(self):
        with patch("app.api.traces._resolve_range") as resolve_mock:
            db = await self._run(None)
        resolve_mock.assert_not_called()
        self.assertEqual(db.execute.await_count, 2)
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd backend && uv run pytest tests/test_traces_list_range.py -v
```

Expected: `TypeError: list_traces() got an unexpected keyword argument 'range'`.

- [ ] **Step 3: Add `range` parameter to `list_traces`**

In `backend/app/api/traces.py`, update the `list_traces` signature and filter construction:

```python
@router.get("", response_model=LLMTraceListResponse)
async def list_traces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    credential_id: uuid.UUID | None = None,
    workflow_id: uuid.UUID | None = None,
    source: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    search: str | None = Query(None),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    range: str | None = Query(None, description="Optional time window: 1h|24h|7d|30d|all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMTraceListResponse:
    """List LLM traces for the current user with pagination."""
    filters = [LLMTrace.user_id == current_user.id]
    if credential_id:
        filters.append(LLMTrace.credential_id == credential_id)
    if workflow_id:
        filters.append(LLMTrace.workflow_id == workflow_id)
    if source:
        filters.append(LLMTrace.source == source)
    if status_filter == "error":
        filters.append(LLMTrace.error.is_not(None))
    elif status_filter == "success":
        filters.append(LLMTrace.error.is_(None))
    if range is not None:
        start_dt, _, _ = _resolve_range(range)
        if start_dt is not None:
            filters.append(LLMTrace.created_at >= start_dt)
    # ... rest unchanged
```

(Keep the existing body below this point. The only changes are the new `range` query parameter and the four-line `if range is not None` block added just before the existing `base_query = ...` construction.)

- [ ] **Step 4: Run list range tests and existing trace tests to verify**

```bash
cd backend && uv run pytest tests/test_traces_list_range.py tests/test_mcp_workflow_traces.py tests/test_workflow_trace_metadata.py -v
```

Expected: all PASS (backward compatibility preserved).

- [ ] **Step 5: Format + lint**

```bash
cd backend && uv run ruff format . && uv run ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/traces.py backend/tests/test_traces_list_range.py
git commit -m "feat(traces): list endpoint accepts optional range query param"
```

---

## Task 8: Backend full test sweep + check.sh

- [ ] **Step 1: Run the full backend check**

```bash
./check.sh
```

Expected: frontend lint/typecheck pass (untouched), backend ruff format check passes, ruff check passes, `./run_tests.sh` reports all green.

If any backend test fails — pause and fix before the commit step. Common gotchas:
- `LLMPricing` ORM class missing column → check `models.py` matches Task 1 step 3
- Migration ordering issues → confirm `068` is the parent and revision string is `"069"`
- `_resolve_range` import path → must be `from app.api.traces import _resolve_range`

- [ ] **Step 2: If anything got reformatted, commit it**

```bash
git status
# If files show modified due to ruff format:
git add -A
git commit -m "style: ruff format after pricing/stats additions"
# Otherwise skip (no empty commits).
```

---

## Task 9: Frontend types

**Files:**
- Modify: `frontend/src/types/trace.ts`
- Create: `frontend/src/types/pricing.ts`

- [ ] **Step 1: Append trace stats types to `trace.ts`**

Add to `frontend/src/types/trace.ts`:

```typescript
export type TraceTimeRange = "1h" | "24h" | "7d" | "30d" | "all";

export interface TraceStatsRangeMeta {
  start: string | null;
  end: string;
  bucket_seconds: number;
}

export interface TraceStatsKpis {
  total_calls: number;
  success_calls: number;
  error_calls: number;
  error_pct: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_cost_usd: string; // server sends Decimal as string
  avg_latency_ms: number;
  unpriced_models: string[];
}

export interface TraceStatsByModel {
  model: string;
  provider: string | null;
  calls: number;
  total_tokens: number;
  cost_usd: string;
  is_priced: boolean;
  is_other?: boolean;
}

export interface TraceStatsByTime {
  bucket_start: string;
  calls: number;
  success: number;
  error: number;
  total_tokens: number;
  cost_usd: string;
}

export interface TraceStatsResponse {
  range: TraceStatsRangeMeta;
  kpis: TraceStatsKpis;
  by_model: TraceStatsByModel[];
  by_time: TraceStatsByTime[];
}
```

- [ ] **Step 2: Create `pricing.ts`**

Create `frontend/src/types/pricing.ts`:

```typescript
export interface LLMPricingRow {
  id: string;
  provider: string | null;
  model: string;
  operator: "equals" | "startsWith" | "includes";
  input_per_1m_usd: string;
  output_per_1m_usd: string;
  source: string; // 'helicone' | 'seed' | 'user'
  is_override: boolean;
  is_custom: boolean;
  override_id: string | null;
  updated_at: string;
}

export interface LLMPricingSyncStatus {
  last_synced_at: string | null;
  total_rows: number;
  override_rows: number;
}

export interface LLMPricingPatchPayload {
  input_per_1m_usd: string;
  output_per_1m_usd: string;
  note?: string | null;
}

export interface LLMPricingCustomPayload {
  model: string;
  input_per_1m_usd: string;
  output_per_1m_usd: string;
  note?: string | null;
}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && bun run typecheck
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/trace.ts frontend/src/types/pricing.ts
git commit -m "feat(traces): add frontend types for stats and llm pricing"
```

---

## Task 10: Frontend API services

**Files:**
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Locate the existing `traceApi` block**

In `frontend/src/services/api.ts`, find the existing `traceApi` exports (search for `traceApi`).

- [ ] **Step 2: Extend `traceApi.list` and add `stats`**

Update `traceApi.list` parameter type to accept an optional `range`:

```typescript
list: async (params: {
  limit?: number;
  offset?: number;
  source?: string;
  credentialId?: string;
  workflowId?: string;
  search?: string;
  order?: "asc" | "desc";
  range?: TraceTimeRange;
}): Promise<LLMTraceListResponse> => {
  const query = new URLSearchParams();
  // ... existing param building ...
  if (params.range) query.set("range", params.range);
  // ... rest unchanged ...
},

stats: async (params: {
  range?: TraceTimeRange;
  source?: string;
  credentialId?: string;
  workflowId?: string;
  status?: string;
  search?: string;
}): Promise<TraceStatsResponse> => {
  const query = new URLSearchParams();
  if (params.range) query.set("range", params.range);
  if (params.source) query.set("source", params.source);
  if (params.credentialId) query.set("credential_id", params.credentialId);
  if (params.workflowId) query.set("workflow_id", params.workflowId);
  if (params.status) query.set("status", params.status);
  if (params.search) query.set("search", params.search);
  const url = `/traces/stats${query.toString() ? `?${query}` : ""}`;
  const response = await apiClient.get<TraceStatsResponse>(url);
  return response.data;
},
```

Add the import at the top of the file:

```typescript
import type {
  LLMTraceDetail,
  LLMTraceListItem,
  LLMTraceListResponse,
  TraceStatsResponse,
  TraceTimeRange,
} from "@/types/trace";
import type {
  LLMPricingCustomPayload,
  LLMPricingPatchPayload,
  LLMPricingRow,
  LLMPricingSyncStatus,
} from "@/types/pricing";
```

(Merge with existing trace imports; do not duplicate.)

- [ ] **Step 3: Add `llmPricingApi`**

Append after `traceApi`:

```typescript
export const llmPricingApi = {
  list: async (): Promise<LLMPricingRow[]> => {
    const response = await apiClient.get<LLMPricingRow[]>("/llm-pricing");
    return response.data;
  },
  syncStatus: async (): Promise<LLMPricingSyncStatus> => {
    const response = await apiClient.get<LLMPricingSyncStatus>("/llm-pricing/sync-status");
    return response.data;
  },
  sync: async (): Promise<void> => {
    await apiClient.post("/llm-pricing/sync");
  },
  updateOverride: async (model: string, payload: LLMPricingPatchPayload): Promise<LLMPricingRow> => {
    const response = await apiClient.patch<LLMPricingRow>(
      `/llm-pricing/${encodeURIComponent(model)}`,
      payload,
    );
    return response.data;
  },
  deleteOverride: async (model: string): Promise<void> => {
    await apiClient.delete(`/llm-pricing/${encodeURIComponent(model)}`);
  },
  createCustom: async (payload: LLMPricingCustomPayload): Promise<LLMPricingRow> => {
    const response = await apiClient.post<LLMPricingRow>("/llm-pricing/custom", payload);
    return response.data;
  },
};
```

- [ ] **Step 4: Typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.ts
git commit -m "feat(traces): add llmPricingApi and traceApi.stats client"
```

---

## Task 11: TracesTimeRangeSelect component

**Files:**
- Create: `frontend/src/components/Traces/TracesTimeRangeSelect.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
import { computed } from "vue";

import type { TraceTimeRange } from "@/types/trace";

import Select from "@/components/ui/Select.vue";

interface Props {
  modelValue: TraceTimeRange;
}
interface Emits {
  (e: "update:modelValue", value: TraceTimeRange): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const options = computed<Array<{ value: TraceTimeRange; label: string }>>(() => [
  { value: "1h", label: "Last 1 hour" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "all", label: "All time" },
]);

const internal = computed({
  get: () => props.modelValue,
  set: (value: TraceTimeRange) => emit("update:modelValue", value),
});
</script>

<template>
  <Select
    v-model="internal"
    :options="options"
  />
</template>
```

- [ ] **Step 2: Typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Traces/TracesTimeRangeSelect.vue
git commit -m "feat(traces): add time range select component"
```

---

## Task 12: TracesStatsHeader component (KPIs + ApexCharts)

**Files:**
- Create: `frontend/src/components/Traces/TracesStatsHeader.vue`

- [ ] **Step 1: Verify the existing ApexCharts import path used in the project**

```bash
grep -rn "vue3-apexcharts\|apexcharts" /Users/mbakgun/Projects/heym/heymrun/frontend/src/components/Analytics/ | head -5
```

Use the same import pattern as `AnalyticsDashboard.vue`.

- [ ] **Step 2: Create the component**

Create `frontend/src/components/Traces/TracesStatsHeader.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";
import VueApexCharts from "vue3-apexcharts";

import type { TraceStatsResponse } from "@/types/trace";

import Card from "@/components/ui/Card.vue";

interface Props {
  stats: TraceStatsResponse | null;
  loading: boolean;
}

const props = defineProps<Props>();

function fmtNum(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return value.toLocaleString();
}

function fmtCost(value: string | number): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  if (!Number.isFinite(n) || n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtMs(value: number): string {
  if (!Number.isFinite(value) || value === 0) return "—";
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${Math.round(value)} ms`;
}

const kpis = computed(() => props.stats?.kpis ?? null);

const tokensByModelOptions = computed(() => ({
  chart: { type: "donut" as const, fontFamily: "inherit" },
  labels: (props.stats?.by_model ?? []).map((m) => m.model),
  legend: { position: "bottom" as const, labels: { colors: "var(--foreground)" } },
  dataLabels: { enabled: false },
  tooltip: {
    y: { formatter: (val: number) => fmtNum(val) + " tokens" },
  },
  noData: { text: "No data" },
}));
const tokensByModelSeries = computed(() =>
  (props.stats?.by_model ?? []).map((m) => m.total_tokens),
);

const costByModelOptions = computed(() => ({
  chart: { type: "donut" as const, fontFamily: "inherit" },
  labels: (props.stats?.by_model ?? []).map((m) => m.model),
  legend: { position: "bottom" as const, labels: { colors: "var(--foreground)" } },
  dataLabels: { enabled: false },
  tooltip: {
    y: { formatter: (val: number) => fmtCost(val) },
  },
  noData: { text: "No data" },
}));
const costByModelSeries = computed(() =>
  (props.stats?.by_model ?? []).map((m) => parseFloat(m.cost_usd) || 0),
);

const callsOverTimeOptions = computed(() => ({
  chart: { type: "area" as const, stacked: true, fontFamily: "inherit", toolbar: { show: false } },
  xaxis: {
    type: "datetime" as const,
    labels: { style: { colors: "var(--muted-foreground)" } },
  },
  yaxis: {
    labels: { style: { colors: "var(--muted-foreground)" }, formatter: (val: number) => fmtNum(val) },
  },
  colors: ["#10b981", "#ef4444"],
  stroke: { curve: "smooth" as const, width: 2 },
  fill: { opacity: 0.3 },
  legend: { position: "bottom" as const, labels: { colors: "var(--foreground)" } },
  noData: { text: "No data" },
}));
const callsOverTimeSeries = computed(() => {
  const buckets = props.stats?.by_time ?? [];
  return [
    {
      name: "Success",
      data: buckets.map((b) => [new Date(b.bucket_start).getTime(), b.success]),
    },
    {
      name: "Error",
      data: buckets.map((b) => [new Date(b.bucket_start).getTime(), b.error]),
    },
  ];
});

const hasCostData = computed(() => costByModelSeries.value.some((v) => v > 0));
const showUnpriced = computed(() => (kpis.value?.unpriced_models?.length ?? 0) > 0);
</script>

<template>
  <div class="space-y-4">
    <div class="grid gap-3 grid-cols-2 md:grid-cols-5">
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-xs text-muted-foreground">Calls</div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtNum(kpis?.total_calls ?? 0) }}
        </div>
      </Card>
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-xs text-muted-foreground">Tokens</div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtNum(kpis?.total_tokens ?? 0) }}
        </div>
      </Card>
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-xs text-muted-foreground">Cost</div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtCost(kpis?.total_cost_usd ?? "0") }}
        </div>
      </Card>
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-xs text-muted-foreground">Avg Latency</div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : fmtMs(kpis?.avg_latency_ms ?? 0) }}
        </div>
      </Card>
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-xs text-muted-foreground">Error %</div>
        <div class="mt-1 text-xl font-semibold">
          {{ loading ? "…" : (kpis?.error_pct ?? 0).toFixed(1) + "%" }}
        </div>
      </Card>
    </div>

    <div class="grid gap-4 md:grid-cols-3">
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-sm font-medium mb-2">Tokens by Model</div>
        <VueApexCharts
          type="donut"
          height="240"
          :options="tokensByModelOptions"
          :series="tokensByModelSeries"
        />
      </Card>
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-sm font-medium mb-2 flex items-center justify-between">
          <span>Cost by Model</span>
          <router-link
            v-if="!hasCostData && !loading"
            to="/dashboard?tab=datatable/llm-pricing"
            class="text-xs text-primary hover:underline"
          >
            Configure pricing
          </router-link>
        </div>
        <VueApexCharts
          type="donut"
          height="240"
          :options="costByModelOptions"
          :series="costByModelSeries"
        />
      </Card>
      <Card variant="flat" :hover="false" class="p-3">
        <div class="text-sm font-medium mb-2">Calls Over Time</div>
        <VueApexCharts
          type="area"
          height="240"
          :options="callsOverTimeOptions"
          :series="callsOverTimeSeries"
        />
      </Card>
    </div>

    <div
      v-if="showUnpriced"
      class="text-xs text-muted-foreground rounded-md border border-yellow-500/30 bg-yellow-500/5 px-3 py-2"
    >
      {{ kpis?.unpriced_models.length }} model(s) without pricing:
      <span class="font-mono">{{ kpis?.unpriced_models.join(", ") }}</span>
      ·
      <router-link
        to="/dashboard?tab=datatable/llm-pricing"
        class="text-primary hover:underline"
      >
        Configure
      </router-link>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors. If the `Select` or `Card` import path differs (check `frontend/src/components/ui/`), adjust accordingly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Traces/TracesStatsHeader.vue
git commit -m "feat(traces): add stats header with KPI cards and ApexCharts"
```

---

## Task 13: Wire stats + time range into TracesPanel

**Files:**
- Modify: `frontend/src/components/Traces/TracesPanel.vue`

- [ ] **Step 1: Add imports + refs**

In the `<script setup>` block of `frontend/src/components/Traces/TracesPanel.vue`, add to the existing imports:

```typescript
import type { TraceStatsResponse, TraceTimeRange } from "@/types/trace";

import TracesStatsHeader from "@/components/Traces/TracesStatsHeader.vue";
import TracesTimeRangeSelect from "@/components/Traces/TracesTimeRangeSelect.vue";
```

(Merge `TraceStatsResponse, TraceTimeRange` into the existing `import type { ... } from "@/types/trace"` line — do not create a duplicate.)

After the existing `const error = ref("");` line add:

```typescript
const timeRange = ref<TraceTimeRange>("7d");
const stats = ref<TraceStatsResponse | null>(null);
const statsLoading = ref(false);
```

- [ ] **Step 2: Add `loadStats` and `loadAll`**

Just below the existing `loadTraces` function, add:

```typescript
async function loadStats(): Promise<void> {
  statsLoading.value = true;
  try {
    stats.value = await traceApi.stats({
      range: timeRange.value,
      source: sourceFilter.value === "all" ? undefined : sourceFilter.value,
      credentialId: credentialFilter.value === "all" ? undefined : credentialFilter.value,
      workflowId:
        isWorkflowSource.value && workflowFilter.value !== "all"
          ? workflowFilter.value
          : undefined,
      search: searchQuery.value || undefined,
    });
  } catch {
    stats.value = null;
  } finally {
    statsLoading.value = false;
  }
}

async function loadAll(): Promise<void> {
  await Promise.all([loadTraces(), loadStats()]);
}
```

- [ ] **Step 3: Update `loadTraces` to include `range`**

In the existing `loadTraces` function, find the `await traceApi.list({...})` call and add `range: timeRange.value` to the params object:

```typescript
const response = await traceApi.list({
  limit: limit.value,
  offset: offset.value,
  source: sourceFilter.value === "all" ? undefined : sourceFilter.value,
  credentialId: credentialFilter.value === "all" ? undefined : credentialFilter.value,
  workflowId:
    isWorkflowSource.value && workflowFilter.value !== "all"
      ? workflowFilter.value
      : undefined,
  search: searchQuery.value || undefined,
  order: "desc",
  range: timeRange.value,
});
```

- [ ] **Step 4: Wire watchers**

Find the existing `watch([sourceFilter, credentialFilter, workflowFilter], ...)` block and replace it with:

```typescript
watch([timeRange, sourceFilter, credentialFilter, workflowFilter], () => {
  resetPagination();
  loadAll();
});
```

In `onSearchInput`'s debounce callback, replace `loadTraces()` with `loadAll()`. Same for `clearSearch` (`loadTraces()` → `loadAll()`) and the `onMounted` block: `await loadTraces();` → `await loadAll();`.

Also update `clearTraces`: after `offset.value = 0;` add `await loadStats();` so the charts also reset to zero after a "Clear All".

- [ ] **Step 5: Add components to template**

In the `<template>` block, insert `<TracesStatsHeader>` immediately after the header `<div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">...</div>` (i.e., above the search input row):

```vue
<TracesStatsHeader
  :stats="stats"
  :loading="statsLoading"
/>
```

Then add the time range select as the first item inside the existing filter grid. Locate the grid `<div class="grid gap-4 grid-cols-1 sm:grid-cols-2" :class="isWorkflowSource ? 'md:grid-cols-3' : ''">`. Update its class to:

```vue
<div
  class="grid gap-4 grid-cols-1 sm:grid-cols-2"
  :class="isWorkflowSource ? 'md:grid-cols-4' : 'md:grid-cols-3'"
>
  <div class="space-y-2">
    <Label>Time range</Label>
    <TracesTimeRangeSelect v-model="timeRange" />
  </div>
  <!-- existing Source/Credential/Workflow selects -->
```

- [ ] **Step 6: Typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 7: Manual smoke test**

```bash
./run.sh --no-debug
```

Wait for "Frontend ready". Open http://localhost:4017, log in, navigate to Traces.

Expected:
- KPI cards render (probably "$0.00", "0 calls" if no traces yet)
- Three chart cards visible with "No data" placeholder if no data
- Time range select shows "Last 7 days"
- Switching to "Last 1 hour" reloads list + charts together

Stop dev server (Ctrl+C in the run.sh terminal).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Traces/TracesPanel.vue
git commit -m "feat(traces): integrate stats header and time range selector"
```

---

## Task 14: LLMPricingPanel component

**Files:**
- Create: `frontend/src/components/DataTable/LLMPricingPanel.vue`

- [ ] **Step 1: Create the panel**

Create `frontend/src/components/DataTable/LLMPricingPanel.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Coins, Plus, RefreshCcw, RotateCcw, Trash2, X } from "lucide-vue-next";

import type { LLMPricingRow, LLMPricingSyncStatus } from "@/types/pricing";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { formatDate } from "@/lib/utils";
import { llmPricingApi } from "@/services/api";

const rows = ref<LLMPricingRow[]>([]);
const syncStatus = ref<LLMPricingSyncStatus | null>(null);
const loading = ref(false);
const syncing = ref(false);
const error = ref("");
const search = ref("");

const editingId = ref<string | null>(null);
const editInput = ref({ input: "", output: "" });

const showAddDialog = ref(false);
const addForm = ref({ model: "", input: "", output: "" });
const adding = ref(false);
const addError = ref("");

const filteredRows = computed(() => {
  if (!search.value) return rows.value;
  const q = search.value.toLowerCase();
  return rows.value.filter(
    (r) =>
      r.model.toLowerCase().includes(q) ||
      (r.provider ?? "").toLowerCase().includes(q),
  );
});

async function loadAll(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [list, status] = await Promise.all([
      llmPricingApi.list(),
      llmPricingApi.syncStatus(),
    ]);
    rows.value = list;
    syncStatus.value = status;
  } catch {
    error.value = "Failed to load pricing";
  } finally {
    loading.value = false;
  }
}

async function refreshSync(): Promise<void> {
  syncing.value = true;
  try {
    await llmPricingApi.sync();
    // Poll for a short window so the user sees updated last_synced_at
    for (let i = 0; i < 5; i++) {
      await new Promise((r) => setTimeout(r, 800));
      const status = await llmPricingApi.syncStatus();
      if (
        status.last_synced_at !== syncStatus.value?.last_synced_at
      ) {
        syncStatus.value = status;
        rows.value = await llmPricingApi.list();
        break;
      }
    }
  } finally {
    syncing.value = false;
  }
}

function startEdit(row: LLMPricingRow): void {
  editingId.value = row.id;
  editInput.value = {
    input: row.input_per_1m_usd,
    output: row.output_per_1m_usd,
  };
}

function cancelEdit(): void {
  editingId.value = null;
}

async function saveEdit(row: LLMPricingRow): Promise<void> {
  try {
    const updated = await llmPricingApi.updateOverride(row.model, {
      input_per_1m_usd: editInput.value.input,
      output_per_1m_usd: editInput.value.output,
    });
    const idx = rows.value.findIndex((r) => r.model === row.model);
    if (idx >= 0) rows.value[idx] = updated;
    editingId.value = null;
  } catch {
    error.value = `Failed to update ${row.model}`;
  }
}

async function resetOverride(row: LLMPricingRow): Promise<void> {
  if (!row.is_override) return;
  if (!confirm(`Reset pricing for ${row.model} to default?`)) return;
  try {
    await llmPricingApi.deleteOverride(row.model);
    await loadAll();
  } catch {
    error.value = `Failed to reset ${row.model}`;
  }
}

async function deleteCustom(row: LLMPricingRow): Promise<void> {
  if (!row.is_custom) return;
  if (!confirm(`Delete custom row ${row.model}?`)) return;
  try {
    await llmPricingApi.deleteOverride(row.model);
    await loadAll();
  } catch {
    error.value = `Failed to delete ${row.model}`;
  }
}

async function submitAdd(): Promise<void> {
  addError.value = "";
  if (!addForm.value.model || !addForm.value.input || !addForm.value.output) {
    addError.value = "All fields required";
    return;
  }
  adding.value = true;
  try {
    await llmPricingApi.createCustom({
      model: addForm.value.model,
      input_per_1m_usd: addForm.value.input,
      output_per_1m_usd: addForm.value.output,
    });
    showAddDialog.value = false;
    addForm.value = { model: "", input: "", output: "" };
    await loadAll();
  } catch (err) {
    addError.value = (err as { response?: { data?: { detail?: string } } })
      ?.response?.data?.detail ?? "Failed to add model";
  } finally {
    adding.value = false;
  }
}

function badgeFor(row: LLMPricingRow): { label: string; classes: string } | null {
  if (row.is_custom) return { label: "User added", classes: "bg-blue-500/15 text-blue-600" };
  if (row.is_override) return { label: "Customized", classes: "bg-amber-500/15 text-amber-600" };
  return null;
}

onMounted(() => {
  loadAll();
});
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2 justify-between">
      <div>
        <h2 class="text-xl font-semibold flex items-center gap-2">
          <Coins class="w-5 h-5" />
          LLM Cost Table
        </h2>
        <p class="text-xs text-muted-foreground">
          Per-model pricing used to compute cost in the Traces dashboard. Global
          rows are synced from Helicone; your edits create per-user overrides.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <div class="text-xs text-muted-foreground">
          <span v-if="syncStatus?.last_synced_at">
            Last synced: {{ formatDate(syncStatus.last_synced_at) }}
          </span>
          <span v-else>Never synced</span>
        </div>
        <Button variant="outline" size="sm" :loading="syncing" @click="refreshSync">
          <RefreshCcw class="w-4 h-4 mr-1" /> Refresh
        </Button>
        <Button variant="outline" size="sm" @click="showAddDialog = true">
          <Plus class="w-4 h-4 mr-1" /> Add Custom Model
        </Button>
      </div>
    </div>

    <Input v-model="search" placeholder="Search model or provider…" />

    <div v-if="error" class="text-sm text-destructive">{{ error }}</div>

    <Card variant="flat" :hover="false" class="p-0 overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-muted/30">
          <tr class="text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th class="px-3 py-2">Provider</th>
            <th class="px-3 py-2">Model</th>
            <th class="px-3 py-2">Op</th>
            <th class="px-3 py-2">Input $/1M</th>
            <th class="px-3 py-2">Output $/1M</th>
            <th class="px-3 py-2">Source</th>
            <th class="px-3 py-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in filteredRows"
            :key="row.id"
            class="border-t border-border/40"
          >
            <td class="px-3 py-2 text-xs text-muted-foreground">{{ row.provider ?? "—" }}</td>
            <td class="px-3 py-2 font-mono text-xs">
              {{ row.model }}
              <span
                v-if="badgeFor(row)"
                class="ml-2 text-[10px] px-1.5 py-0.5 rounded"
                :class="badgeFor(row)?.classes"
              >
                {{ badgeFor(row)?.label }}
              </span>
            </td>
            <td class="px-3 py-2 text-xs">{{ row.operator }}</td>
            <td class="px-3 py-2">
              <Input
                v-if="editingId === row.id"
                v-model="editInput.input"
                class="h-7 w-24"
              />
              <span v-else>${{ row.input_per_1m_usd }}</span>
            </td>
            <td class="px-3 py-2">
              <Input
                v-if="editingId === row.id"
                v-model="editInput.output"
                class="h-7 w-24"
              />
              <span v-else>${{ row.output_per_1m_usd }}</span>
            </td>
            <td class="px-3 py-2 text-xs text-muted-foreground">{{ row.source }}</td>
            <td class="px-3 py-2 text-right">
              <div class="flex items-center justify-end gap-1">
                <template v-if="editingId === row.id">
                  <Button size="sm" variant="outline" @click="saveEdit(row)">Save</Button>
                  <Button size="sm" variant="ghost" @click="cancelEdit">
                    <X class="w-3 h-3" />
                  </Button>
                </template>
                <template v-else>
                  <Button size="sm" variant="ghost" @click="startEdit(row)">Edit</Button>
                  <Button
                    v-if="row.is_override"
                    size="sm"
                    variant="ghost"
                    title="Reset to default"
                    @click="resetOverride(row)"
                  >
                    <RotateCcw class="w-3 h-3" />
                  </Button>
                  <Button
                    v-if="row.is_custom"
                    size="sm"
                    variant="ghost"
                    title="Delete"
                    @click="deleteCustom(row)"
                  >
                    <Trash2 class="w-3 h-3 text-destructive" />
                  </Button>
                </template>
              </div>
            </td>
          </tr>
          <tr v-if="filteredRows.length === 0">
            <td colspan="7" class="px-3 py-6 text-center text-sm text-muted-foreground">
              {{ loading ? "Loading…" : "No pricing rows" }}
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <Dialog
      :open="showAddDialog"
      title="Add Custom Model Pricing"
      size="md"
      @close="showAddDialog = false"
    >
      <div class="space-y-3">
        <div>
          <Label>Model name</Label>
          <Input v-model="addForm.model" placeholder="e.g. my-org/private-llm" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <Label>Input $/1M</Label>
            <Input v-model="addForm.input" placeholder="0.50" />
          </div>
          <div>
            <Label>Output $/1M</Label>
            <Input v-model="addForm.output" placeholder="1.50" />
          </div>
        </div>
        <div v-if="addError" class="text-sm text-destructive">{{ addError }}</div>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" @click="showAddDialog = false">Cancel</Button>
          <Button :loading="adding" @click="submitAdd">Add</Button>
        </div>
      </div>
    </Dialog>
  </div>
</template>
```

- [ ] **Step 2: Typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors. If the `Input` component path differs (check `frontend/src/components/ui/Input.vue` exists), adjust import or use a plain `<input class="...">`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/DataTable/LLMPricingPanel.vue
git commit -m "feat(traces): add LLM Cost Table editable pricing panel"
```

---

## Task 15: DataTablePanel "System tables" integration

**Files:**
- Modify: `frontend/src/components/DataTable/DataTablePanel.vue`

- [ ] **Step 1: Read the current detail-pane pattern**

```bash
grep -n "parseDataTableRoute\|kind === \"detail\"\|selectedTable\|openTable" /Users/mbakgun/Projects/heym/heymrun/frontend/src/components/DataTable/DataTablePanel.vue | head -20
```

The panel uses query-string routing (`?tab=datatable/<id>`). Reserve the id `llm-pricing` for the system table. Note: any watcher that calls `openTable(parsed.id)` based on the parsed route must skip when `parsed.id === "llm-pricing"`, otherwise the panel will try to fetch a non-existent DataTable and surface an error.

- [ ] **Step 2: Wire the special route**

In `frontend/src/components/DataTable/DataTablePanel.vue`, add this import at the top:

```typescript
import LLMPricingPanel from "@/components/DataTable/LLMPricingPanel.vue";
```

Add a computed flag:

```typescript
const isLLMPricingSelected = computed(() => {
  const parsed = parseDataTableRoute(route.query.tab);
  return parsed.kind === "detail" && parsed.id === "llm-pricing";
});
```

In the template, find the list-mode render block (where the user's `tables` array is iterated). Just above the user tables list (after the "Create DataTable" toolbar), insert a System tables section:

```vue
<div v-if="!selectedTable && !isLLMPricingSelected" class="space-y-2">
  <div class="text-xs uppercase tracking-wide text-muted-foreground">
    System tables
  </div>
  <Card
    class="p-4 cursor-pointer hover:bg-muted/40"
    @click="$router.push({ query: { ...$route.query, tab: 'datatable/llm-pricing' } })"
  >
    <div class="flex items-center gap-2">
      <Coins class="w-4 h-4 text-primary" />
      <div>
        <div class="font-medium">LLM Cost Table</div>
        <div class="text-xs text-muted-foreground">
          Per-model pricing used by the Traces cost charts
        </div>
      </div>
    </div>
  </Card>
</div>
```

Add the `Coins` import to the existing `lucide-vue-next` imports.

In the detail rendering block, add a branch that renders the pricing panel when `isLLMPricingSelected` is true. Find the existing detail mode `v-if` (something like `v-if="selectedTable"`). Add **above** it:

```vue
<LLMPricingPanel v-if="isLLMPricingSelected" />
```

Adjust the existing detail mode `v-if` so it also requires `!isLLMPricingSelected` (e.g. `v-else-if="selectedTable"`).

In the route watcher (search for the existing watcher that reads `route.query.tab` and calls `openTable(parsed.id)`), add a guard before calling `openTable`:

```typescript
if (parsed.kind === "detail" && parsed.id === "llm-pricing") {
  selectedTable.value = null;  // drop any previously-loaded user table
  return;  // skip openTable for the system pricing route
}
```

This prevents the panel from trying to fetch a DataTable with id `"llm-pricing"` (which doesn't exist) and lets `isLLMPricingSelected` render the system panel instead.

- [ ] **Step 3: Typecheck + lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 4: Manual smoke test**

```bash
./run.sh --no-debug
```

Open Dashboard → DataTables tab. Expected:
- "System tables" section appears above user tables
- Clicking "LLM Cost Table" opens the pricing panel
- After ~1s the table should populate (auto-sync triggers in background; refresh manually if needed)
- Edit a row → cell prices change immediately, "Customized" badge appears
- Reset → badge clears, default returns

Stop dev server.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DataTable/DataTablePanel.vue
git commit -m "feat(traces): add system-tables section with LLM Cost Table entry"
```

---

## Task 16: heym-documentation update

**Files:**
- (Skill-driven) updates under `docs/` for Traces page and DataTables

- [ ] **Step 1: Invoke `heym-documentation` skill**

Run the `heym-documentation` skill (via Skill tool) with this brief:

```
Document two changes:
1. Traces page now shows a stats header above the list with KPI cards
   (Calls, Tokens, Cost, Avg Latency, Error %) and three charts (Tokens by
   Model donut, Cost by Model donut, Calls Over Time area). A "Time range"
   select (1h/24h/7d/30d/All, default 7d) filters both the charts and the
   list. The "Refresh" and "Clear All" buttons retain their existing behavior.
   An "Unpriced models" notice appears when some traced models lack pricing
   rows, with a link to the LLM Cost Table.

2. DataTables now has a "System tables" section above user-created tables
   containing a pinned "LLM Cost Table" entry. Opening it shows a fixed-
   schema editable grid of per-model pricing rows. The table is synced from
   Helicone's public pricing endpoint (https://www.helicone.ai/api/llm-costs)
   in the background, capped to one fetch per 24 hours unless the user
   presses Refresh. Editing a row creates a per-user override that the next
   Helicone sync will not overwrite; "Reset to default" removes the override.
   Use "Add Custom Model" to add a model Helicone does not list.
```

The skill should produce or update doc pages under `docs/` and (for heymweb) sync any indices.

- [ ] **Step 2: Commit doc changes**

```bash
git add docs/
git commit -m "docs(traces): document llm metrics header, time range, and cost table"
```

---

## Task 17: Final verification

- [ ] **Step 1: Run `./check.sh`**

```bash
./check.sh
```

Expected: green across frontend lint+typecheck and backend ruff+tests.

- [ ] **Step 2: End-to-end manual smoke**

```bash
./run.sh --no-debug
```

In the browser:
1. Create or run a workflow that makes at least 2-3 LLM calls (or use the AI Assistant / Dashboard Chat to generate some traces).
2. Navigate to Traces.
3. Confirm KPI numbers, donuts, and area chart all render with real values.
4. Switch "Time range" between presets — both charts and list update; pagination resets.
5. Change Source filter — both update together.
6. Open DataTables → LLM Cost Table → edit one row's pricing → return to Traces → confirm the per-model cost updates immediately on next reload.
7. Add a custom row for a fictional model, run a workflow using it (or simulate by adjusting a trace) — confirm it counts toward cost.

Stop dev server.

- [ ] **Step 3: Final status check, no automatic push**

```bash
git status
git log --oneline -20
```

Expected: clean working tree, all task commits present. Per project policy (`feedback_no_auto_push`), do **not** push — wait for the user's explicit instruction.

- [ ] **Step 4: Report to the user**

Summarize what landed locally and ask whether to push.

---

## Self-Review Notes

**Spec coverage check:**
- Section 1 (models/migration) → Task 1 ✓
- Section 2 (Helicone sync + Pricing API) → Tasks 3, 4, 5 ✓
- Section 3 (Stats endpoint + list range param) → Tasks 6, 7 ✓
- Section 4 (frontend files + tests) → Tasks 9–15 ✓
- Documentation → Task 16 ✓

**Cross-task consistency:**
- ORM column types (`Numeric(12, 6)`, `String(200)`) match across migration (Task 1) and tests (Tasks 2, 5) ✓
- Resolver signature `resolve_costs_for_user(db, user_id, list[tuple[str, int, int]])` matches in service (Task 2), stats endpoint usage (Task 6), and tests ✓
- API URL prefix `/api/llm-pricing` matches between backend mount (Task 5) and frontend client (Task 10) ✓
- Range key set `1h|24h|7d|30d|all` consistent in `_resolve_range` (Task 6), list param (Task 7), frontend type (Task 9), select (Task 11) ✓
- Frontend route id `llm-pricing` used identically in stats header link (Task 12), DataTablePanel system section (Task 15) ✓
