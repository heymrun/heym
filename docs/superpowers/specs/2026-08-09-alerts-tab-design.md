# Alerts Tab — Design Spec

**Date:** 2026-08-09
**Status:** Approved for planning
**Repos touched:** `heymrun` (feature + docs), `heymweb` (solutions page, comparison tables, blog post)
**Git policy for this work:** local only. Nothing is committed or pushed.

---

## 1. Problem

Heym records everything an operator would want to be warned about — execution outcomes in
`execution_history`, LLM token spend in `llm_traces`, latency in
`execution_history.execution_time_ms` — but it never volunteers any of it. A workflow that starts
failing, gets slow, burns budget, or runs 100x more often than it should is only discovered when
somebody opens the Analytics or Traces tab and looks.

There is no way to say "tell me when this crosses a line."

## 2. Goal

A new **Alerts** tab where a user defines threshold conditions over a time window, in a step-by-step
wizard that AI can prefill from a plain-English description. Fired alerts are visible in-app and can
optionally execute a workflow. The Chat tab can answer questions about what alerts exist and why or
when a given alert fired.

## 3. Non-goals

- Anomaly detection, baselining, or forecasting. Every condition is an explicit user-set threshold.
- Native email / Slack / Telegram delivery. Routing is done by executing a workflow, which already
  has nodes for all of those.
- Per-node alerting. Conditions are workflow-level or account-level.
- Instance-wide (cross-tenant) metrics. See the scope decision in §5.2.
- Alert conditions on coding-agent (Codex / OpenCode) usage. Cost alerts read `llm_traces` only.

---

## 4. The four alert types

Every type is evaluated over a **user-defined time window**, never on a single event.

| Type | Question it answers | Metric source |
|---|---|---|
| `error_threshold` | "Did this workflow fail more than N times in the last X minutes?" | `execution_history` rows with `status = 'error'` |
| `workflow_duration` | "Did runs get slower than X ms in the last window?" | `execution_history.execution_time_ms`, aggregated |
| `token_cost` | "Did I burn more than N tokens / $N in the last window?" | `llm_traces` + `LLMPricing` / `LLMPricingOverride` |
| `execution_count` | "Did this run far more often than it should have?" | `execution_history` row count |

### 4.1 Why window-based and not event-based

A single failed run is noise. Twelve failed runs in ten minutes is an incident. Evaluating over a
window is what separates an alert from a log line, and it is the reason the `error_threshold` type
counts rows in a window rather than hooking the execution-failure path.

---

## 5. Data model

Four new tables. Migration lives in `backend/alembic/versions/`.

### 5.1 `alerts`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `owner_id` | UUID FK `users.id` ON DELETE CASCADE | indexed |
| `name` | String(255) | |
| `description` | Text, nullable | |
| `alert_type` | String(50) | `error_threshold` \| `workflow_duration` \| `token_cost` \| `execution_count`, indexed |
| `scope` | String(20) | `workflow` \| `system` |
| `workflow_id` | UUID FK `workflows.id` ON DELETE CASCADE, nullable | required when `scope = 'workflow'`, must be NULL when `scope = 'system'` |
| `config` | JSON | type-specific, validated by the Pydantic union in §6 |
| `enabled` | Boolean, default true | indexed |
| `notify_workflow_id` | UUID FK `workflows.id` ON DELETE SET NULL, nullable | workflow executed on fire |
| `state` | String(20), default `ok` | `ok` \| `triggered` |
| `renotify_mode` | String(20), default `on_recovery` | `on_recovery` \| `cooldown` |
| `cooldown_minutes` | Integer, nullable | required when `renotify_mode = 'cooldown'` |
| `check_interval_seconds` | Integer, default 60 | how often the evaluator re-checks; validated to a minimum of 60 |
| `next_check_at` | DateTime(tz), indexed | claim column, see §7.2 |
| `last_evaluated_at` | DateTime(tz), nullable | |
| `last_triggered_at` | DateTime(tz), nullable | |
| `last_observed_value` | Float, nullable | powers the listing's "currently at" column |
| `created_at` / `updated_at` | DateTime(tz) | |

Index on `(enabled, next_check_at)` — the evaluator's hot query.

### 5.2 Scope semantics

`scope: 'system'` means **every workflow the alert's owner can access**, resolved through the same
helper the Analytics tab uses (`get_accessible_workflow_ids`). It deliberately does *not* mean
"every workflow on this Heym instance."

Rationale: alerts are shareable (§5.4). If `system` meant instance-wide, sharing an alert with a
teammate would hand them aggregate metrics for workflows they cannot open. Evaluating as the owner
keeps the alert's numbers consistent with what the owner sees in Analytics, and sharing grants
visibility into the alert, not into new data.

### 5.3 `alert_events`

One row per firing. This is the table the Chat tab's "why did it trigger" question reads.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `alert_id` | UUID FK `alerts.id` ON DELETE CASCADE | indexed |
| `triggered_at` | DateTime(tz) | indexed |
| `observed_value` | Float | what the metric actually was |
| `threshold_value` | Float | what it was compared against |
| `window_start` / `window_end` | DateTime(tz) | the exact window evaluated |
| `context` | JSON | contributing execution ids, per-workflow breakdown for system scope, top error messages for `error_threshold`, model breakdown for `token_cost` |
| `acknowledged_at` | DateTime(tz), nullable | drives the nav badge |
| `notify_execution_id` | UUID, nullable | execution history id of the notify workflow run |
| `notify_status` | String(20), nullable | `skipped` \| `queued` \| `succeeded` \| `failed` |

Index on `(alert_id, triggered_at DESC)`.

**Retention:** `alert_events` older than 90 days are deleted by a daily cleanup pass added to
`CronScheduler`, following the existing `_check_portal_session_cleanup` / `_cleanup_old_cron_slot_claims`
pattern. Without this the table grows without bound.

### 5.4 `alert_shares` and `alert_team_shares`

Direct structural mirrors of `credential_shares` / `credential_team_shares`:

- `alert_shares` — `(alert_id, user_id)` unique, both FKs cascade.
- `alert_team_shares` — `(alert_id, team_id)` unique, both FKs cascade, both indexed.

Shared users get read access to the alert and its events. Only the owner can edit, delete, enable,
disable, or re-share. This matches how credential sharing already behaves and avoids a permissions
model nobody asked for.

---

## 6. Config schemas

`backend/app/models/alert_schemas.py`. A discriminated union on `alert_type`, so an invalid
combination fails at the API boundary rather than inside the evaluator.

Shared by every type:

- `window_minutes: int` — 1 to 10080 (7 days).

Per type:

```
ErrorThresholdConfig:
    alert_type: Literal["error_threshold"]
    window_minutes: int
    threshold_count: int          # >= 1

WorkflowDurationConfig:
    alert_type: Literal["workflow_duration"]
    window_minutes: int
    threshold_ms: float           # > 0
    aggregation: Literal["max", "avg", "p95"] = "max"
    min_samples: int = 1          # don't fire on a single slow run in a quiet window

TokenCostConfig:
    alert_type: Literal["token_cost"]
    window_minutes: int
    metric: Literal["total_tokens", "usd"]
    threshold: float              # > 0

ExecutionCountConfig:
    alert_type: Literal["execution_count"]
    window_minutes: int
    threshold_count: int          # >= 1
```

All four fire on `observed_value >= threshold`. There is no comparison operator field; every one of
the four types is a ceiling by nature, and adding `<` would create conditions that fire forever on a
workflow that simply isn't running.

`min_samples` exists only on `workflow_duration` because it is the only aggregate where a tiny
sample is actively misleading — `max` over one run is that run.

---

## 7. Evaluation engine

### 7.1 Where it runs

A new `_check_alerts()` pass inside `CronScheduler._run_loop`, which is already leader-gated via
`lock_service.is_leader` and already runs every 30 seconds.

Considered and rejected:

- **A standalone background service.** Would need its own leader election and its own liveness story.
  A second loop that can silently die is a second thing to notice has died.
- **Lazy evaluation when the Alerts tab opens.** An alert that only fires while someone is watching
  is not an alert.

### 7.2 Claiming

The scheduler loop is leader-gated, but leadership can hand off mid-pass — this is exactly what
caused the cron duplicate-fire incident. Alerts use the same defense: an atomic claim.

```sql
UPDATE alerts
   SET next_check_at = now() + (check_interval_seconds * interval '1 second'),
       last_evaluated_at = now()
 WHERE id IN (
     SELECT id FROM alerts
      WHERE enabled = true AND next_check_at <= now()
      ORDER BY next_check_at
      LIMIT 50
      FOR UPDATE SKIP LOCKED
 )
RETURNING *;
```

`FOR UPDATE SKIP LOCKED` plus advancing `next_check_at` inside the claim means a second worker that
briefly believes it is leader claims nothing. Batched at 50 per pass so one pathological account
cannot starve the loop.

### 7.3 Module layout

Mirrors the `node_execution` registry pattern that AGENTS.md already mandates for the executor:

```
backend/app/services/alerts/
├── __init__.py
├── registry.py          # alert_type -> handler, one lookup
├── evaluator.py         # claim, dispatch, state machine, event write, notify dispatch
├── context.py           # AlertEvaluationContext, AlertObservation dataclasses
├── ai_draft.py          # natural language -> AlertDraft
├── cleanup.py           # alert_events retention pass
└── types/
    ├── __init__.py
    ├── error_threshold.py
    ├── workflow_duration.py
    ├── token_cost.py
    └── execution_count.py
```

Every handler implements exactly one function:

```python
async def evaluate(ctx: AlertEvaluationContext) -> AlertObservation
```

`AlertEvaluationContext` carries the db session, the resolved workflow id list, the window bounds,
and the parsed config. `AlertObservation` carries `observed_value`, `threshold_value`, and a
`context` dict.

Handlers own their metric and nothing else. Claiming, state transitions, event packaging, notify
dispatch, and error swallowing all live in `evaluator.py`. Adding a fifth alert type is one file
plus one registry line.

**This becomes an AGENTS.md rule** ("Alert type modularity"), for the same reason
`WorkflowExecutor` and `PropertiesPanel.vue` have theirs: without a written rule, the fifth alert
type gets added as an `if alert_type ==` branch in the evaluator, and by the eighth the evaluator is
unreadable.

### 7.4 Metric queries

**`error_threshold`** — `COUNT(*)` over `execution_history` where `workflow_id IN scope`,
`started_at >= window_start`, `status = 'error'`. Context captures up to 5 execution ids and their
distinct error messages.

**`workflow_duration`** — `execution_time_ms` over the same window. `max` and `avg` are SQL
aggregates; `p95` reuses `calculate_percentile` from `app/api/analytics.py` rather than
reimplementing percentile math. Returns `None` (no fire) when the sample count is below
`min_samples`.

**`token_cost`** — `llm_traces` filtered by `user_id = owner_id` and, for workflow scope,
`workflow_id`. `total_tokens` sums the column directly. `usd` reuses the existing pricing resolution
from `app/services/llm_pricing.py` so the number matches the Traces tab exactly — a cost alert that
disagrees with the cost page is worse than no alert. Context carries a per-model breakdown.

**`execution_count`** — `COUNT(*)` over `execution_history` in the window, all statuses. Context
carries a per-workflow breakdown for system scope and a per-`trigger_source` breakdown, since "why
did this run 2000 times" is usually answered by the trigger.

Both `execution_history.started_at` and `execution_history.workflow_id` are already indexed.

### 7.5 State machine

```
                  observed >= threshold
   ┌─────────┐ ──────────────────────────► ┌──────────────┐
   │   ok    │                             │  triggered   │
   └─────────┘ ◄────────────────────────── └──────────────┘
                  observed <  threshold
                    (recovery)
```

- `ok` + breach → write `alert_events` row, set `state = 'triggered'`, set `last_triggered_at`,
  dispatch notify workflow.
- `triggered` + breach + `renotify_mode = 'on_recovery'` → **silent**. Update `last_observed_value`
  only. This is the default.
- `triggered` + breach + `renotify_mode = 'cooldown'` → fire again only if
  `now() - last_triggered_at >= cooldown_minutes`.
- `triggered` + no breach → `state = 'ok'`. Recovery is a state change, not an event; it is not
  written to `alert_events` and does not run the notify workflow.

The user chose `on_recovery` as the sensible default and asked that the wizard expose the choice, so
step 4 offers both modes with `on_recovery` preselected.

Without this machine, a 60-second check interval on a genuinely broken workflow produces 60 events
and 60 notify-workflow runs per hour, which is how alerting systems get muted.

### 7.6 Notify workflow dispatch

When `notify_workflow_id` is set, the evaluator executes it through `execute_workflow` directly —
the same path `error_workflow_runner.py` uses, not the HTTP execute route.

Input body:

```json
{
  "alert_id": "…", "alert_name": "…", "alert_type": "error_threshold",
  "scope": "workflow", "workflow_id": "…", "workflow_name": "…",
  "observed_value": 12, "threshold_value": 5,
  "window_start": "…", "window_end": "…", "window_minutes": 10,
  "context": { … }
}
```

The event row is written and committed **before** dispatch. The notify run is then started as a
background task whose reference is retained so it is not garbage-collected mid-flight, and whose
result updates `notify_status`. Every failure is caught and recorded as
`notify_status = 'failed'`. **A broken notify workflow must never stop the evaluator loop or prevent
the event row from being written** — the record of the firing matters more than the delivery of it.

**Recursion guard:** if `notify_workflow_id` equals the alert's own `workflow_id`, dispatch is
skipped and recorded as `notify_status = 'skipped'`. Otherwise an `execution_count` alert on workflow
A that notifies workflow A is a runaway loop.

---

## 8. AI draft

`POST /api/alerts/ai-draft` takes `{ prompt, credential_id, model }` and returns an `AlertDraft`
matching the wizard's field set, plus a `filled_fields` list so the UI can mark what AI guessed.

Implementation: a single LLM call with the alert-type catalogue and field descriptions in the system
prompt, requesting structured JSON. The response is parsed into the same Pydantic union used by the
create endpoint, so an AI draft cannot produce a config the API would reject. On parse failure the
endpoint returns the raw text as `clarification` and no draft — the wizard then shows the message and
leaves the user on step 1 rather than prefilling garbage.

Workflow resolution: the prompt includes the user's accessible workflow names and ids, so
"alert me when the invoice sync starts failing" can resolve to a specific `workflow_id`.

Structured JSON is used rather than tool calling because there is exactly one output shape and no
multi-turn negotiation; tool calling would add a round trip for nothing.

---

## 9. API — `backend/app/api/alerts.py`

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/alerts` | list, `limit`/`offset`, filters: `enabled`, `alert_type`, `workflow_id`, `state` |
| POST | `/api/alerts` | create |
| GET | `/api/alerts/{id}` | detail |
| PATCH | `/api/alerts/{id}` | update (owner only) |
| DELETE | `/api/alerts/{id}` | delete (owner only) |
| POST | `/api/alerts/{id}/test` | evaluate now, return observation, **do not fire, do not write an event** |
| POST | `/api/alerts/preview` | same as `/test` but for an unsaved config — powers the wizard's Review step |
| GET | `/api/alerts/{id}/events` | firing history, paginated |
| GET | `/api/alerts/events` | recent events across all accessible alerts; `unacknowledged=true` for the nav badge |
| POST | `/api/alerts/events/{id}/acknowledge` | clear from badge |
| POST | `/api/alerts/ai-draft` | natural language → draft |
| GET/POST/DELETE | `/api/alerts/{id}/shares` | user shares, mirroring `credentials.py` |
| GET/POST/DELETE | `/api/alerts/{id}/team-shares` | team shares |

Access is resolved by a new `backend/app/services/alert_access.py`, structurally following
`credential_access.py`: owner, direct share, or membership in a team the alert is shared with.

All request and response models are Pydantic, paginated with `limit`/`offset`, errors raised as
`HTTPException`. Router registered in `app/main.py` under `/api/alerts`.

---

## 10. Frontend

### 10.1 Files

```
frontend/src/components/Alerts/
├── AlertsTab.vue              # thin shell: listing + events panel + wizard mount
├── AlertList.vue
├── AlertCard.vue              # name, type badge, scope, condition summary, state pill, current value
├── AlertEventsPanel.vue       # firing history with observed vs threshold
├── AlertShareDialog.vue       # mirrors the credential share dialog
└── wizard/
    ├── AlertWizardDialog.vue  # step orchestration + AI prefill
    ├── AlertAiPrompt.vue
    ├── StepType.vue
    ├── StepScope.vue
    ├── StepCondition.vue
    ├── StepResponse.vue
    └── StepReview.vue
frontend/src/stores/alerts.ts
frontend/src/services/alerts.ts
frontend/src/types/alerts.ts
```

`AlertsTab.vue` stays a shell. Per-alert-type condition fields live in `StepCondition.vue` as a
`<component :is>` switch over small per-type field components, not as a chain of `v-if` on the type,
for the same reason the backend uses a registry.

### 10.2 Registration points

- `frontend/src/components/Layout/DashboardNav.vue` — add `{ id: "alerts", label: "Alerts", icon: BellRing }` to `tabs`, and `alerts` to the `activeTab` tabParam check.
- `frontend/src/views/DashboardView.vue` — add to `validTabs`, to the `TabKey` union, and to the tab render switch.
- `frontend/src/router/index.ts` — add `"alerts"` to `DASHBOARD_TAB_PATHS` so `/alerts` redirects to `/?tab=alerts`.
- Command palette tab list (`handleTabSelectFromPalette` path in `DashboardView.vue`).

### 10.3 Badge

Unacknowledged event count from `GET /api/alerts/events?unacknowledged=true`, rendered on the nav
item. Polled on the same cadence the nav already uses for other live counts; no new socket.

### 10.4 Wizard

Five steps, forward via **Next**, back allowed, state held in the dialog until Review.

1. **Type** — four cards with a one-line description each. The AI prompt box sits above them.
2. **Scope** — this workflow (with a picker) or all my workflows.
3. **Condition** — window (value + unit selector, stored as minutes) and the type-specific threshold fields.
4. **Response** — optional notify workflow picker, plus the re-notify choice: *notify once until it recovers* (default) or *keep notifying every N minutes*.
5. **Review** — full summary plus the backtest.

**The Review backtest is the feature that makes this a wizard rather than a form.** It calls
`POST /api/alerts/preview` and answers: *"Over the last 24 hours, this condition would have fired 3
times. Highest observed value: 14 errors."* A user who sets a threshold of 5 and sees "would have
fired 400 times" fixes the threshold before saving instead of after being paged.

### 10.5 AI assist flow

User types "warn me if the invoice sync fails more than 5 times in 10 minutes" → `POST /ai-draft` →
every step prefilled → wizard jumps to Review with AI-filled fields visually marked → user confirms
or steps back to edit. The wizard is never bypassed; AI fills it in, the user still approves it.

---

## 11. Chat tab integration

Three tools appended to `DASHBOARD_CHAT_TOOLS` in `backend/app/api/ai_assistant.py`, with handlers
alongside the existing `get_analytics_stats` / `get_recent_executions` handlers.

**`list_alerts`** — optional `workflow_id`, `alert_type`, `state`, `enabled_only`. Returns id, name,
type, scope, workflow name, a human-readable condition summary, state, enabled, `last_triggered_at`,
`last_observed_value`. Answers "what alerts do I have."

**`get_alert_detail`** — by `alert_id`. Full config, notify workflow, share list, and a count of
firings in the last 7 days.

**`get_alert_events`** — the "why and when did it trigger" tool. Optional `alert_id`, `time_range`
(`24h` / `7d` / `30d` / `all`), `limit`. Returns per event: `triggered_at`, `observed_value` vs
`threshold_value`, window bounds, and the `context` payload — contributing execution ids, error
messages, per-model cost breakdown, or trigger-source breakdown depending on type. This is why §5.3
stores `context` at firing time rather than recomputing: the window has passed, and recomputing it
later can give a different answer.

A new numbered rule is added to `DASHBOARD_CHAT_SYSTEM_PROMPT` instructing the model to use these
tools for alert questions, to cite the specific window and observed value when explaining a firing,
and to answer in the user's language.

---

## 12. Documentation (heymrun)

Per the AGENTS.md Feature Documentation Policy, this is a large feature and requires doc updates via
the `heym-documentation` skill.

- **New:** `frontend/src/docs/content/tabs/alerts-tab.md` — the four types, the wizard, AI drafting, re-notify semantics, notify workflows, sharing, and the backtest.
- `frontend/src/docs/manifest.ts` — register `{ slug: "alerts-tab", title: "Alerts" }` under `tabs`.
- `frontend/src/docs/content/reference/features.md` — an Alerts section plus the entry in the tab summary list.
- `frontend/src/docs/content/tabs/chat-tab.md` — the three new alert questions Chat can answer.
- `frontend/src/docs/content/reference/execution-history.md` and `analytics-tab.md` — cross-links to Alerts, since that is where a user goes looking for this.
- `README.md` — an Alerts subsection under Observability, and a comparison-table row.
- `AGENTS.md` — the "Alert type modularity" rule (§7.3).

### 12.1 Comparison table row

heymrun `README.md`, in the Why Heym table:

```
| Metric alerts (errors, duration, cost, run count) | ✅ | limited²⁵ | limited²⁵ | limited²⁵ |
```

with footnote 25 sourced from official docs at time of writing and dated, matching the convention of
footnotes 15 through 24. The claim to verify before writing the footnote is specifically whether each
competitor offers **user-defined threshold alerts over a time window on cost and duration**, not
merely per-execution failure notifications, which all three have.

---

## 13. heymweb rollout

Separate repo, same session, local only.

1. **Solutions** — a new `SolutionDefinition` in `src/lib/solutions.ts` using the `productSurface`
   variant (the story lives in a tab, not on a canvas), pointing at `/alerts`, with the four types as
   `steps`. Registered wherever the solutions list feeds nav, search index, and agent discovery.
2. **Comparison tables** — a matching row in `src/lib/comparisons.ts` and
   `src/components/sections/ComparisonSection.tsx`, with per-competitor notes in the same evidenced,
   dated style as the existing rows.
3. **Blog post** — full SEO pipeline, in order: `serp-analysis` → `content-gap-analysis` →
   `keyword-research` → `seo-content-writer` → `geo-content-optimizer` → `meta-tags-optimizer` →
   `content-quality-auditor` → `on-page-seo-auditor` → `schema-markup-generator` →
   `internal-linking-optimizer` → `competitor-analysis`. Author **Ceren**. Constraints carried from
   standing preferences: minimal em dashes and natural English, a `FlowDiagram` with `steps` /
   `branches` passed as single-quoted JSON strings, exact-phrase keyword occurrence verified
   programmatically on the rendered string, citations 2025 or newer only, reciprocal template links,
   no competitor roundups, and no year in the title if the previous post has one. Research uses
   `brave_search_api` and `website_loader`, with `heym_google_analytics` and
   `heym_google_search_console` consulted where they inform the topic choice.
4. Verify with `bunx tsc --noEmit` and `bun run build`. Watch `tests/seo/invariants.test.ts`, which
   hardcodes counts and breaks type-checking rather than just failing a test.
5. Writing plans stay under the heymweb research memory directory. Nothing is committed.

---

## 14. Testing

Backend pytest, `unittest.IsolatedAsyncioTestCase` with `AsyncMock`, per AGENTS.md:

- `test_alert_metrics.py` — each of the four handlers: correct window boundary, correct scope filter, empty-window behaviour, `min_samples` suppression, `p95` agreement with `calculate_percentile`, USD agreement with the pricing service.
- `test_alert_evaluator.py` — the state machine: fire on breach, silence while triggered under `on_recovery`, re-fire after `cooldown_minutes` under `cooldown`, recovery back to `ok`, re-fire after recovery. Plus: notify dispatch failure does not prevent the event row, and self-referential notify is skipped.
- `test_alert_claiming.py` — `next_check_at` advances inside the claim; a disabled alert is never claimed.
- `test_alerts_api.py` — CRUD, validation rejects `scope=workflow` without `workflow_id` and `renotify_mode=cooldown` without `cooldown_minutes`, share/team-share read access, non-owner cannot mutate.
- `test_alert_ai_draft.py` — valid JSON parses into the union, malformed output returns `clarification` and no draft.
- `test_alert_chat_tools.py` — the three tools return the documented shape and respect access control.
- `test_alert_cleanup.py` — retention deletes events past 90 days and nothing newer.

Run via `./check.sh` from the repo root before any push, prefixed with `HEYM_OTEL_ENABLED=false` to
avoid the collector-less hang, and never concurrently with another full-suite run.

**No Playwright E2E spec**, per the standing "no frontend/UI tests for heymrun" preference. The
frontend is verified with `bun run lint`, `bun run typecheck`, and manual walkthrough of the wizard.
This is a deliberate departure from the AGENTS.md "when practical" guidance and is called out here so
it is a recorded decision rather than an omission.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Evaluator adds load to a loop that also runs cron | Batch of 50 per pass, indexed claim query, `check_interval_seconds` floor of 60 |
| Cost alert disagrees with the Traces tab | Reuse `llm_pricing.py` resolution rather than reimplementing |
| Notify workflow loops | Self-reference guard, plus notify runs are ordinary executions and so are themselves visible in history |
| Alert spam | `on_recovery` default; the wizard backtest surfaces a bad threshold before it is saved |
| `alert_events` unbounded growth | 90-day retention pass in the scheduler |
| Leader handoff double-fires | `FOR UPDATE SKIP LOCKED` claim advancing `next_check_at` in the same statement |

---

## 16. Open items

None. All four clarifying decisions are resolved: in-app plus notify-workflow delivery, per-user
ownership with team sharing, `on_recovery` default with the choice exposed in the wizard, and
LLM-traces-only cost.
