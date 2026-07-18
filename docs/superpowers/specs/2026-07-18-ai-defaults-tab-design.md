# AI Defaults settings tab — design

Date: 2026-07-18
Status: Approved (ready for implementation planning)

## Summary

Add an **AI Defaults** tab to the user settings dialog with two capabilities:

1. **Preferred credential + model** — the user picks a default LLM credential and
   model. Every AI surface in the app (chat, AI assistant / analyzer / creation,
   board mapper, AI widgets, docs chat, expression builder, evals, data-table AI,
   dashboard AI, and any other credential+model picker) uses this as the starting
   default when the surface has no saved selection of its own.

2. **Coding-package usage bars** — for Codex credentials, show remaining rate-limit
   usage per active window (e.g. 5h and/or weekly) as horizontal percentage bars.
   OpenCode credentials are listed but marked "usage unavailable" (feasibility
   investigation showed the OpenCode zen gateway does not expose remaining-quota
   data).

## Feasibility findings (recorded from live probes, 2026-07-18)

A read-only probe was run against real Codex and OpenCode credentials.

### Codex — feasible

A minimal authenticated `POST https://chatgpt.com/backend-api/codex/responses`
(ChatGPT OAuth bundle: `access_token` + `account_id`) returns **HTTP 200** whose
**response headers** carry the usage data (the SSE body does NOT contain a
`rate_limits` object — headers are the source of truth):

```
x-codex-active-limit: premium
x-codex-plan-type: plus
x-codex-primary-used-percent: 34
x-codex-secondary-used-percent: 0
x-codex-primary-window-minutes: 10080      # 7 days => "Weekly"
x-codex-secondary-window-minutes: 0        # inactive on this plan
x-codex-primary-reset-after-seconds: 569620
x-codex-primary-reset-at: 1784966861
x-codex-secondary-reset-after-seconds: 0
x-codex-secondary-reset-at:
x-codex-credits-has-credits: False
x-codex-credits-balance: 0E-10
x-codex-credits-unlimited: False
```

Key consequences:

- **The number of windows is plan-dependent.** On the probed Plus plan only the
  primary window (10080 min = weekly) was active; `secondary-window-minutes` was 0.
  Other plans (e.g. Pro) may expose a 5h window plus a weekly window. The UI must
  render bars **dynamically** from whatever windows have `window-minutes > 0`.
- Window labels are derived from `window-minutes` (300 → "5 hours", 10080 →
  "Weekly", otherwise a generic `{minutes/60}h` / `{minutes/1440}d`).
- Usage headers appear **only on a 200 response**. The 400 model-validation errors
  did not include them, so a real (minimal) successful request is required.
- The Codex node runs via the `codex exec` CLI subprocess, which does not surface
  these HTTP headers. Therefore usage must come from a **dedicated backend HTTP
  probe**, not from harvesting node runs.

### OpenCode — not feasible this iteration

Against `https://opencode.ai/zen/go/v1`:

- `GET /usage`, `/rate_limits`, `/limits`, `/me`, `/key`, `/account`,
  `/billing/usage`, `/dashboard/billing/usage`, `/user` all returned **404** (the
  gateway root serves HTML, not an account API).
- `GET /models` returns 200 with the model list but **no** rate/usage headers.
- `POST /chat/completions` (real model `minimax-m3`) returns 200 whose body has
  only **per-request** token usage + cost
  (`usage.prompt_tokens`, `total_tokens`, `cost:"0"`) — **not** remaining quota —
  and **no** rate/usage/limit response headers.

The credential holds only the gateway API key, so no separate billing host is
reachable. Conclusion: there is no remaining-quota source. OpenCode is shown with
a "usage unavailable" note and can be revisited if the gateway later exposes usage.

## Decisions (from brainstorming)

- Preferred is a **credential + model pair** stored on the user.
- Priority when a surface picks its default: **saved selection > preferred > first
  credential** (a surface's own persisted choice, e.g. a chat conversation's
  `last_model`, always wins; preferred only fills the gap when nothing is saved).
- If the preferred credential/model can no longer be resolved (deleted, unshared,
  or the model is no longer offered), **silently fall back** to the old behavior
  (first credential + its default model) and show a "preferred no longer valid"
  note in the AI Defaults tab.
- Propagation mechanism: a **shared frontend composable** (`useAiDefaults`) plus the
  two user fields. No new backend resolver — every AI endpoint keeps receiving
  `credential_id` + `model` from the frontend.
- Codex usage refresh: **on tab open + a manual refresh button**, with a **60s
  backend cache** per credential.
- OpenCode: listed with a **"usage unavailable" note**.

## Security analysis

Storing/reading a preferred `credential_id` introduces **no new attack surface**:

- Only IDs and a model string are stored and transmitted — never secrets.
- Every AI request already sends `credential_id`, and the backend authorizes it
  per request via `get_accessible_credential`; the preferred value passes through
  the exact same authorization check.
- The preferred value is scoped to the owning user.

The Codex usage probe uses the user's own (or shared-with-them) credential,
authorized via `get_accessible_credential` — the same boundary as running a Codex
node. No new vector.

## Architecture

### Task 1 — Preferred defaults

**Backend**

- Alembic migration: add to `users`:
  - `preferred_credential_id UUID NULL REFERENCES credentials(id) ON DELETE SET NULL`
  - `preferred_model VARCHAR NULL`
- `app/db/models.py` `User`: two mapped columns (mirror `tts_credential_id`).
- `app/models/schemas.py`: add both fields to `UserResponse` and `UserUpdate`.
- `app/api/auth.py` `update_user`: handle both, validating the credential with
  `get_accessible_credential` exactly like `tts_credential_id`. Setting
  `preferred_credential_id` to null clears the pair.

**Frontend**

- `stores/auth.ts`: extend the `User` type and the `updateUser` payload with
  `preferred_credential_id` and `preferred_model`.
- New `components/Layout/aiDefaults/useAiDefaults.ts` (or a `settings`/shared
  location) exposing:
  - `resolveDefault(credentials, { savedCredentialId?, savedModel? }) => { credentialId, model }`
    implementing **saved > preferred > first credential**.
  - `resolveModel(credentialId, models, { savedModel? }) => string` implementing
    **saved > preferred (when credentialId is the preferred credential) > existing
    per-surface default**.
  - A boolean/status helper for "preferred is set but not resolvable" so the tab
    can show the warning.
- New AI Defaults tab in `UserSettingsDialog.vue` (follows the Voice tab pattern):
  credential dropdown (`credentialsApi.listLLM()`) → model dropdown
  (`credentialsApi.getModels(id)`) → Save (`authStore.updateUser`). Shows the
  "preferred no longer valid" warning when applicable.
- Adopt `resolveDefault` / `resolveModel` in each AI surface's default-selection
  code, replacing ad-hoc "first credential / last model" logic. Confirmed
  surfaces: `ChatConversation.vue`, dashboard chat / analyzer / creation
  (`ai_assistant` surfaces), board mapper config, `AiWidgetDialog.vue`,
  `DocsChatDialog`/`useDocsChatDialog`, `AIExpressionBuilderModal.vue`,
  evals (`EvalsLeftPanel.vue`/`EvalsView.vue`), data-table AI, dashboard AI. The
  implementation plan will enumerate the exact call sites.

### Task 2 — Codex usage bars

**Backend**

- `app/services/codex_usage_service.py`:
  - Input: a decrypted Codex credential config.
  - Ensure a fresh access token: if expired, refresh via the existing
    `codex_oauth_service.refresh_tokens` and persist the rotated bundle.
  - `POST /backend-api/codex/responses` with a minimal valid body (tiny input,
    `stream:true`, `store:false`, **no** `max_output_tokens`), read the
    `x-codex-*` **response headers**, and drain/close the stream promptly.
  - Model selection is **plan-dependent** (the probe saw `gpt-5.6` rejected but
    `gpt-5.5` accepted on a Plus plan). Try candidate models from
    `codex_catalog.CODEX_MODEL_SUGGESTIONS` in order, stopping at the first that
    does not return a `"model is not supported"` 400; cache the working model per
    credential to avoid re-probing. If the credential has a configured/preferred
    Codex model, try it first.
  - Parse into a structured result:
    - `plan_type`, `active_limit`
    - `windows`: list of `{ key: "primary"|"secondary", used_percent,
      window_minutes, reset_after_seconds, reset_at, label }` — **omit** any window
      with `window_minutes == 0`; derive `label` from `window_minutes`.
    - `credits`: `{ has_credits, balance, unlimited }`
  - 60s in-memory cache keyed by credential id. Failures degrade to
    `available: false` (never raise into the request).
- Endpoint `GET /api/credentials/{id}/codex-usage` in the credentials/api layer,
  authorized with `get_accessible_credential`, returning the structured result or
  an `available: false` payload. OpenCode credentials do not get a usage probe.
- Pydantic response models for the usage payload.

**Frontend**

- In the AI Defaults tab, a "Coding usage" section that lists the user's Codex and
  OpenCode credentials (owned + shared, via `credentialsApi.listByType` /
  existing shared-credential listing).
- Per **Codex** credential: a card showing the plan badge + credits and one
  horizontal bar per active window (label `5h` / `Weekly` / derived, `used_percent`
  fill, and a reset countdown from `reset_after_seconds`/`reset_at`). Multiple
  Codex credentials each render their own card.
- Per **OpenCode** credential: a card with a "usage unavailable — this gateway does
  not expose usage data" note.
- Refresh: fetch on tab open; a manual "Refresh" button; the backend 60s cache
  smooths repeated opens.

## Testing

- **Backend**
  - `auth.update_user` accepts/validates/clears the preferred pair (accessible vs
    unowned credential).
  - `codex_usage_service` header parsing with mocked httpx: multi-window,
    `window_minutes == 0` skipped, label mapping (300→5h, 10080→weekly, generic),
    credits parsing, refresh-on-expiry path, and failure → `available: false`.
  - `GET /api/credentials/{id}/codex-usage` authorization (accessible / not found /
    non-codex type).
- **Frontend**
  - `resolveDefault` / `resolveModel` priority unit tests (saved > preferred >
    first; unresolvable preferred → fallback + warning flag).
  - AI Defaults tab renders and saves.
  - Usage section renders dynamic Codex bars and the OpenCode "unavailable" note.
  - Playwright coverage for the tab where practical (per repo policy).

## Documentation

Update via the `heym-documentation` skill: `user-settings.md` (new AI Defaults
tab) and the credentials reference (Codex usage bars; OpenCode usage limitation).

## Out of scope

- OpenCode usage bars (no data source; deferred).
- A backend "omit credential_id/model and let the server apply preferred" resolver.
- Changing how any AI feature authorizes or executes; only the frontend default
  selection changes.
