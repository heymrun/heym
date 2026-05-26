# Traces Screen — LLM Metrics, Cost Table & Time Range

**Date:** 2026-05-26
**Status:** Design approved (pending spec review)

## Goal

Add visual LLM metrics to the Traces screen (KPI summary, per-model token/cost donuts, calls-over-time chart) backed by a configurable LLM pricing table synced from Helicone, plus a time-range selector that filters both charts and the underlying trace list.

## Motivation

The current Traces panel is a flat paginated list — useful for inspecting individual calls but offers no way to see aggregate spend, model mix, or temporal patterns. Users have no idea how much their workflows cost or which models dominate their usage. A small set of charts on top of the existing list, driven by a shared time-range filter, closes that gap with minimal UI churn.

## Out of scope

- Custom date range picker (only presets in v1)
- Pre-aggregated snapshot tables (on-demand SQL is fast enough at expected scale)
- Admin role-gated global pricing edits (no admin role yet; users override globally via per-user table)
- Cost backfill into existing trace rows (cost is computed at read time)
- Pricing in currencies other than USD

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Frontend: TracesPanel.vue                                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ TracesStatsHeader.vue  (KPI cards + 3 ApexCharts)        │    │
│  └──────────────────────────────────────────────────────────┘    │
│  ┌─────────────────┐ ┌──────────────┐ ┌────────────────────┐    │
│  │ TimeRangeSelect │ │ Source/Cred  │ │ Search / Pagination│    │
│  └─────────────────┘ └──────────────┘ └────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Existing trace list (now filtered by time range)         │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
                │ parallel fetch
                ▼
┌──────────────────────────────────────────────────────────────────┐
│  Backend                                                          │
│  ┌────────────────────────┐  ┌──────────────────────────────┐    │
│  │ GET /api/traces        │  │ GET /api/traces/stats        │    │
│  │ (now accepts ?range=)  │  │ (new endpoint)               │    │
│  └─────────────┬──────────┘  └──────────┬───────────────────┘    │
│                │ shared WHERE clause     │ + pricing resolver    │
│                ▼                          ▼                       │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  llm_traces  (+ new composite index user_id, created_at) │    │
│  └──────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  llm_pricing  (global)  ←─ async sync from Helicone API  │    │
│  │  llm_pricing_override   (per-user customizations)        │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

## Section 1 — Data model & migration

### New table: `llm_pricing` (global, system-managed, all users read)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `provider` | varchar(50) | Helicone's value (`"ANTHROPIC"`, `"OPENAI"`, ...); informational |
| `model` | varchar(200) | e.g. `"claude-3-5-sonnet-20241022"` |
| `operator` | varchar(20) | `equals` \| `startsWith` \| `includes` |
| `input_per_1m_usd` | numeric(12,6) | |
| `output_per_1m_usd` | numeric(12,6) | |
| `source` | varchar(20) | `helicone` \| `seed` |
| `last_synced_at` | timestamptz | |
| `created_at`, `updated_at` | timestamptz | |

Constraints:
- `UNIQUE (provider, model, operator)`
- `INDEX (model)` — speeds up resolver match

### New table: `llm_pricing_override` (per-user)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `user_id` | uuid fk users(id) on delete cascade | |
| `model` | varchar(200) | Always exact-match (`operator='equals'` semantics) |
| `input_per_1m_usd` | numeric(12,6) | |
| `output_per_1m_usd` | numeric(12,6) | |
| `note` | text nullable | User's free-form note |
| `base_pricing_id` | uuid fk llm_pricing(id) on delete set null | Null = pure user-added custom model |
| `created_at`, `updated_at` | timestamptz | |

Constraints:
- `UNIQUE (user_id, model)`
- `INDEX (user_id)`

### `llm_traces` index addition

- New composite: `INDEX (user_id, created_at DESC)`
- Existing `ix_llm_traces_user_id` and `ix_llm_traces_created_at` are kept (low risk; Postgres picks the right one).

### Alembic migration: `024_add_llm_pricing.py`

Creates both tables and the composite trace index in a single revision. Downgrade drops them.

## Section 2 — Helicone sync service & Pricing API

### Sync service: `backend/app/services/llm_pricing_sync.py`

- **Source:** `GET https://www.helicone.ai/api/llm-costs` (JSON; `data[]` of `{provider, model, operator, input_cost_per_1m, output_cost_per_1m}`)
- **HTTP client:** `httpx.AsyncClient`, 10s timeout, `User-Agent: heym/1.0`
- **TTL gate:** Skip auto-sync if `MAX(llm_pricing.last_synced_at)` is within 24h. Manual sync ignores TTL.
- **Upsert logic:**
  - For each payload row → UPSERT `llm_pricing` keyed by `(provider, model, operator)`, set `input/output_per_1m_usd`, `source='helicone'`, `last_synced_at=now()`.
  - Rows in DB that are absent from the payload are **not deleted** (avoid breaking historic cost lookups when Helicone removes a model).
  - `llm_pricing_override` is **never** touched.
- **Failure handling:** Network/parse errors → log warning, leave DB as-is, do not raise to the caller.
- **No bundled static seed for v1.** If the first sync fails, the table stays empty and the UI shows a "no pricing yet" hint with a manual Refresh button.

### Lazy trigger

When `GET /api/traces/stats` or `GET /api/llm-pricing` is called, the handler invokes `ensure_pricing_synced(db)` which:
- If TTL is fresh → no-op.
- If stale → schedules `asyncio.create_task(sync_pricing(...))` and returns immediately. Stats/pricing for this request use whatever is currently in the DB; the next request sees fresh data.

### API: `backend/app/api/llm_pricing.py` (mounted at `/api/llm-pricing`)

```
GET    /api/llm-pricing
       → [{id, provider, model, operator,
            input_per_1m_usd, output_per_1m_usd,
            is_override: bool,    # true if this row is overridden by user
            is_custom:   bool,    # true if user-added only (no global)
            override_id: uuid?,   # if overridden, points to override row
            source, updated_at}]
       Merges global rows with the calling user's overrides:
         - For a global row with an override → returns the override's prices
           but keeps global identity, marks is_override=true.
         - For an override with base_pricing_id=null → returned as a custom
           row, is_custom=true, provider=null.

GET    /api/llm-pricing/sync-status
       → {last_synced_at, is_syncing, total_rows, override_rows}

POST   /api/llm-pricing/sync
       → Forces refresh (bypasses TTL). 202 Accepted, runs async.

PATCH  /api/llm-pricing/{model}
       Body: {input_per_1m_usd, output_per_1m_usd, note?}
       → Upserts an override row (sets base_pricing_id if the global row exists).
       URL key is the model string (URL-encoded). 404 if no matching global row
       AND no existing override AND not a custom-add (use POST /custom for those).

DELETE /api/llm-pricing/{model}
       → If override exists: delete it (global default returns).
         If custom (no global): delete it entirely (model disappears from list).
         204 No Content.

POST   /api/llm-pricing/custom
       Body: {model, input_per_1m_usd, output_per_1m_usd, note?}
       → Creates user-only override row (base_pricing_id=null).
       409 if (user_id, model) already exists in either global or override.
```

### Pricing resolver: `backend/app/services/llm_pricing.py`

```python
async def resolve_costs_for_user(
    db: AsyncSession,
    user_id: UUID,
    model_token_pairs: list[tuple[str, int, int]],  # (model, prompt_tok, completion_tok)
) -> list[tuple[float | None, bool]]:
    """
    Returns (cost_usd, is_priced) per input pair.
    Fetches all global + override rows once, builds in-memory lookup,
    matches each model against the rules.
    """
```

**Resolution per model string:**
1. User override exact match on `model` → use override prices.
2. Otherwise scan global rows in this order:
   - `operator='equals'` exact match
   - `operator='startsWith'` rows where `model.startswith(rule.model)` — pick longest matching `rule.model`
   - `operator='includes'` rows where `rule.model in model` — pick longest matching `rule.model`
3. If still no match → `(None, False)`. Caller treats cost as 0 and adds model to `unpriced_models`.

`cost = (prompt_tok * input_per_1m + completion_tok * output_per_1m) / 1_000_000`

## Section 3 — Stats endpoint & time range

### Endpoint: `GET /api/traces/stats`

**Query params** (mirror the list endpoint):
```
range:          str = "7d"     # 1h | 24h | 7d | 30d | all
source:         str | None
credential_id:  uuid | None
workflow_id:    uuid | None
status:         str | None     # "error" | "success"
search:         str | None
```

**Range → window & bucket mapping (single source of truth in backend):**

| range | window start | bucket size | nominal points |
|---|---|---|---|
| `1h` | now − 1h | 5 min | 12 |
| `24h` | now − 24h | 1 hour | 24 |
| `7d` | now − 7d | 6 hours | 28 |
| `30d` | now − 30d | 1 day | 30 |
| `all` | `MIN(created_at)` for user (clamped to 365 days back) | 1 day | dynamic, cap 365 |

**Response:**
```jsonc
{
  "range": {"start": "...", "end": "...", "bucket_seconds": 21600},
  "kpis": {
    "total_calls": 142,
    "success_calls": 138,
    "error_calls": 4,
    "error_pct": 2.82,
    "prompt_tokens": 45120,
    "completion_tokens": 8930,
    "total_tokens": 54050,
    "total_cost_usd": 0.4321,
    "avg_latency_ms": 1245.3,
    "unpriced_models": ["unknown-x"]
  },
  "by_model": [
    {"model": "gpt-4o", "provider": "openai", "calls": 80,
     "total_tokens": 32000, "cost_usd": 0.21, "is_priced": true},
    // ... top 8 verbatim,
    // remainder collapsed into one entry:
    //   {"model": "Other", "provider": null, "calls": N, "total_tokens": N,
    //    "cost_usd": N, "is_priced": true, "is_other": true}
  ],
  "by_time": [
    {"bucket_start": "2026-05-19T00:00:00Z", "calls": 12, "success": 12,
     "error": 0, "total_tokens": 4500, "cost_usd": 0.034}
    // zero-fill in Python for empty buckets
  ]
}
```

### SQL strategy

Three queries sharing the same WHERE clause (`user_id` + filters + `created_at >= start`):

1. **KPIs:** single aggregate query (`COUNT`, `SUM`, `AVG`, conditional `SUM` for errors).
2. **By model:** `GROUP BY provider, model` ordered by `SUM(total_tokens) DESC`. Top 8 returned verbatim; remainder collapsed in Python into one `"Other"` entry.
3. **By time + model:** `GROUP BY bucket_ts, provider, model` where `bucket_ts = to_timestamp(floor(extract(epoch FROM created_at)/:bucket_seconds) * :bucket_seconds)`. Python folds per-bucket model rows into `by_time[]` entries and accumulates per-bucket `cost_usd` via the resolver.

Cost is computed in Python from the per-(model, bucket) aggregates using a single resolver call per request (pricing lookup is in-memory dict).

### List endpoint change: `GET /api/traces`

- Adds optional `range` query param (same enum as stats).
- Backend converts `range` → `start_date`, adds `WHERE created_at >= :start` to both items and `total` queries.
- Backward compatible: omitting `range` preserves "all time" behavior. Note this default differs from the stats endpoint default (`7d`); the frontend always sends `range` explicitly so they stay in sync.

### Frontend coupling

- One `timeRange` ref (default `"7d"`).
- Changing `timeRange` or any other filter → `resetPagination()` + `Promise.all([loadTraces(), loadStats()])`.
- Pagination only affects the list; charts always summarize the full window.
- Stats and list share the same `range`+filters, so they stay visually consistent.

## Section 4 — Frontend files & tests

### New frontend files

1. **`frontend/src/types/trace.ts`** — extend with `TraceTimeRange`, `TraceStatsResponse`, `TraceStatsKpis`, `TraceStatsByModel`, `TraceStatsByTime`.
2. **`frontend/src/types/pricing.ts`** — `LLMPricingRow`, `LLMPricingSyncStatus`, `LLMPricingPatchPayload`, `LLMPricingCustomPayload`.
3. **`frontend/src/services/api.ts`** — extend:
   - `traceApi.stats(params)`
   - `traceApi.list(...)` accepts `range`
   - new `llmPricingApi = { list, syncStatus, sync, updateOverride, deleteOverride, createCustom }`
4. **`frontend/src/components/Traces/TracesStatsHeader.vue`** (~250 lines)
   - Props: `stats: TraceStatsResponse | null`, `loading: boolean`
   - 5 KPI cards (Total Calls, Total Tokens, Total Cost, Avg Latency, Error %)
   - Donut: Tokens by Model
   - Donut: Cost by Model (or "No pricing configured → Configure" link if `total_cost_usd === 0 && unpriced_models.length > 0`)
   - Line/area: Calls over Time (success vs error stacked)
   - Unpriced-models warning chip below charts when applicable
   - Uses `vue3-apexcharts`; chart colors via CSS vars (theme-aware)
   - Skeleton state while loading, empty state when no data
5. **`frontend/src/components/Traces/TracesTimeRangeSelect.vue`** (~40 lines)
   - Simple `<Select>` wrapper; v-model emits `TraceTimeRange`
6. **`frontend/src/components/DataTable/LLMPricingPanel.vue`** (~350 lines)
   - Fixed-schema editable grid (separate component, does not fork `DataTablePanel.vue`)
   - Columns: Provider · Model · Operator · Input $/1M · Output $/1M · Source · Actions
   - Toolbar: "Last synced: 2h ago" · `Refresh` · `Add Custom Model` · search input
   - Row badges: `Customized` (override), `User added` (custom), `Default` (global)
   - Inline edit (click cell → input → blur saves)
   - `Reset to default` action on override rows; `Delete` only on custom rows
   - Loads via `llmPricingApi.list()`; refresh polls `syncStatus` once after manual sync

### Edited frontend files

7. **`frontend/src/components/Traces/TracesPanel.vue`**
   - Imports `TracesStatsHeader`, `TracesTimeRangeSelect`
   - Adds `timeRange = ref<TraceTimeRange>("7d")`, `stats`, `statsLoading`
   - `loadStats()` and `loadAll()` helpers
   - `loadTraces()` passes `range: timeRange.value`
   - Single `watch([timeRange, sourceFilter, credentialFilter, workflowFilter, searchQuery], ...)` resets pagination and reloads both
   - Mounts `loadAll()` instead of `loadTraces()`
   - Template: `<TracesStatsHeader>` above filters; `<TracesTimeRangeSelect>` as the first filter in the bar
8. **`frontend/src/components/DataTable/DataTablePanel.vue`**
   - Adds a "System tables" section above user tables with a pinned card "LLM Cost Table"
   - Click opens `LLMPricingPanel` (same detail-pane pattern the panel already uses for user tables)
   - User's own DataTables continue to render below

### Dependencies

- Backend: `httpx` (already present), no `beautifulsoup4` needed (JSON API).
- Frontend: `apexcharts` + `vue3-apexcharts` already in `package.json` — no new packages.

### Backend tests

9. **`backend/tests/test_traces_stats.py`** (new)
   - `test_stats_empty_returns_zeros`
   - `test_stats_kpis_correct`
   - `test_stats_by_model_groups_and_collapses_other`
   - `test_stats_by_time_buckets_for_each_range`
   - `test_stats_user_isolation`
   - `test_stats_applies_source_credential_workflow_search_filters`
   - `test_stats_cost_uses_user_override_then_global`
   - `test_stats_unpriced_model_reports_zero_cost_and_lists_in_unpriced`
   - `test_stats_respects_helicone_operators` (`equals`/`startsWith`/`includes`)
10. **`backend/tests/test_traces_list_range.py`** (new)
    - `test_list_with_range_filter_limits_results`
    - `test_list_without_range_returns_all_backwards_compat`
    - `test_list_total_count_respects_range`
11. **`backend/tests/test_llm_pricing.py`** (new)
    - `test_list_merges_overrides_with_global`
    - `test_patch_creates_override_doesnt_modify_global`
    - `test_delete_removes_override_keeps_global_visible`
    - `test_post_custom_creates_user_only_row`
    - `test_user_isolation_for_overrides_and_custom`
    - `test_sync_status_returns_last_synced`
12. **`backend/tests/test_llm_pricing_sync.py`** (new)
    - `test_sync_upserts_helicone_data` (mocks httpx with sample payload)
    - `test_sync_doesnt_touch_overrides`
    - `test_sync_doesnt_delete_missing_helicone_rows`
    - `test_sync_skips_when_fresh_within_24h`
    - `test_sync_handles_helicone_fetch_failure_gracefully`
    - `test_sync_marks_source_and_last_synced_at`
13. **`backend/tests/test_llm_pricing_resolver.py`** (new)
    - `test_resolve_cost_equals_match`
    - `test_resolve_cost_startswith_picks_longest_match`
    - `test_resolve_cost_includes_match`
    - `test_resolve_cost_override_beats_global`
    - `test_resolve_cost_unpriced_returns_none`

### Documentation (`heym-documentation` skill)

- Update Traces page user guide: stats header, time range selector, cost interpretation, unpriced-model warning
- New DataTables section for "LLM Cost Table": sync mechanism, override behavior, adding custom models, source field meaning

## Implementation order

1. Alembic migration + SQLAlchemy models (`LLMPricing`, `LLMPricingOverride`) + composite trace index
2. Pricing resolver (`services/llm_pricing.py`) + sync service (`services/llm_pricing_sync.py`) with tests
3. Pricing API endpoints (`api/llm_pricing.py`) with tests
4. Stats endpoint (`api/traces.py`) + list endpoint `range` param with tests
5. Run `./check.sh` — backend green
6. Frontend types + `api.ts` extensions
7. `TracesStatsHeader.vue` + `TracesTimeRangeSelect.vue` + `TracesPanel.vue` integration
8. `LLMPricingPanel.vue` + `DataTablePanel.vue` "System tables" section
9. `heym-documentation` updates
10. End-to-end manual verification

## Risks & decisions captured

- **Provider mismatch (Helicone uppercase vs our lowercase/credential-type-derived):** Resolver matches by `model` only; `provider` is informational. Trace records keep their existing `provider` value untouched.
- **Helicone schema drift:** Sync service is tolerant — unknown keys ignored, missing rows preserved, fetch failures logged not raised.
- **Cost staleness on historic traces:** Cost is computed at read time. If a user edits pricing, all past traces' computed cost updates accordingly. This is intentional (matches how users think about "what would this cost now?").
- **Model-string collisions across providers (rare):** First override match wins, then most-specific global rule wins. Documented as a known edge case in the user guide.
- **`/all` window unbounded:** Capped at 365 days back from now to keep bucket count bounded.
- **Default range "7d":** Charts need a useful window by default; users who want full history pick "All" explicitly.
