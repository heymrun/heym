You are an expert full-stack AI/ML engineer building Heym, an n8n-like AI workflow automation platform with visual editor.

## AI Coding Agents (Required)
Read and follow this `AGENTS.md` at the start of every session. Repository conventions and policies override default agent behavior.

## Essential Commands

### Quick Start
```bash
./run.sh                    # Start all services (postgres, backend, frontend)
./run.sh --no-debug         # Start with INFO logging instead of DEBUG
./check.sh                  # Run frontend lint/typecheck, backend Ruff checks, and backend tests
./run_e2e.sh                # Run frontend Playwright E2E tests separately
SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh  # Use when no SECRET_KEY is exported locally
```

### Frontend (Vue.js + Bun)
```bash
cd frontend && bun install && bun run dev    # Setup && start dev server (port 4017)
bun run lint                  # ESLint - must pass before commits
bun run typecheck             # TypeScript strict checks - must pass before commits
bun run test                  # Vitest unit tests (enforced in CI, not part of ./check.sh)
bun run build && bun run preview  # Build && test production build
```

### Backend (Python 3.11+ + FastAPI + UV)
```bash
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --port 10105
./run_tests.sh               # Run all backend unit tests in parallel (required before git push)
SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./run_tests.sh  # Full backend tests when no SECRET_KEY is exported
uv run pytest tests/test_file.py::ClassName::test_method  # Run specific test
uv run ruff check .           # Linting (fix with --fix) - must pass before commits
uv run ruff format .          # Auto-format code
uv run ruff format --check .  # Verify formatting without changing files
```

### Database & Docker
```bash
docker-compose up -d postgres  # Start PostgreSQL only (port 6543)
cd backend && uv run alembic upgrade head  # Run database migrations (required after schema changes)
docker-compose up -d          # Start all services (pg:6543, backend:10105, frontend:4017)
```

## Code Style Rules

### Import Order (CRITICAL)
**TypeScript:** Vue imports → External libs → Internal types → Internal code
**Python:** Standard library → Third-party → Internal

### TypeScript Requirements
- strict mode ONLY (noUnusedLocals, noUnusedParameters enabled)
- Explicit return types (`function getName(): string`)
- `interface` > `type` for objects
- `const` > `let`
- Unused params must be prefixed with `_`
- Async/await not Promise chains
- Vue: Composition API with `<script setup>`, file names: PascalCase, max 300 lines

### Python Requirements
- Type hints everywhere (returns included)
- Pydantic models for APIs, dataclasses for data (not dicts)
- Docstrings on public functions
- Ruff formatter only (line length: 100, double quotes, space indent)

### Error Handling
**Frontend:** Typed catches with axios error handling
**Backend:** FastAPI HTTPException only, never generic exceptions

### API Design
RESTful endpoints, Pydantic models for all requests/responses, paginated (limit/offset), OpenAPI docs at `/docs`

### Database
SQLAlchemy 2.0 async, UUID primary keys only, Alembic for migrations, index frequently queried columns

### Testing
Backend: pytest with unittest.TestCase/IsolatedAsyncioTestCase, AsyncMock for DB mocking
Frontend unit tests: Vitest specs live at `frontend/src/**/*.test.ts`; run with `bun run test`. Enforced in the CI `check` job, not in `./check.sh`.
Frontend E2E: Playwright specs live in `frontend/e2e/`; run them with `./run_e2e.sh` from the repository root
**New features must include backend tests** - run `./check.sh` before git push (includes backend tests via `./run_tests.sh`)
**New UI behavior should include Playwright E2E coverage when practical.** E2E tests run as a separate required job in PR checks and are intentionally excluded from `./check.sh` to keep the default local check path fast.
If the local environment does not export `SECRET_KEY`, prefix full-suite commands with `SECRET_KEY=test-secret-key-for-tests-only-32-bytes` (test-only value; never use it for runtime/prod).

### Secret handling (capability secrets)
A capability secret is any value that grants access on its own: API keys, session tokens, share links, webhook auth headers. `backend/app/services/secret_tokens.py` holds the one hashing helper; do not add a second.

- **Hash at rest, and never accept the stored form as a credential.** Persist `hash_secret(value)` and look rows up with a plain equality on the digest. A lookup that also tries the presented value verbatim will match a stored digest, which hands anyone who can read the database a working credential and defeats the point of hashing. Every such column gets a backfilling migration instead of a runtime fallback.
- **A migration that backfills digests can only be guarded when the plaintext is shape-distinguishable from a digest.** `secrets.token_hex(32)` is 64 lowercase hex characters, identical in shape to SHA-256, so a "skip if it looks hashed" guard would skip every real key. `secrets.token_urlsafe(n)` is distinguishable and can be guarded. Document which case applies, and that downgrade cannot restore plaintext.
- **Return once, at creation.** The endpoint that mints a secret returns it; nothing returns it again. List and config endpoints expose a `*_set: bool` flag so the UI can say "configured" without reading it, and the frontend holds the freshly minted value in a session-scoped ref for copy actions.
- **Keep credentials out of URLs.** Accept them from headers only. Query strings reach access logs, proxy logs, browser history and Referer headers. Short-lived in-memory handshake parameters such as the MCP `?session=` token are the exception.
- **Owner-only secrets stay owner-only for reads and writes.** Mask them for collaborators in the response schema and reject collaborator writes. Masking the read without guarding the write lets a masked, empty editor field autosave over the owner's value.
- **Redact at every persistence boundary, not just the obvious one.** A request-derived secret usually reaches more than one structure: run inputs, node outputs, `node_results`, and sub-workflow history are separate columns. Redacting one moves the secret rather than removing it. Use one recursive redactor per run and apply it at each write.
- **When touching any of the above:** add focused tests under `backend/tests/test_advisory_*.py`, including the negative case that the stored representation does not authenticate.

### Node and operation integration
When adding a new node type, operation, or operation-specific field, keep the canvas affordances in sync with the schema:

- Update the node/operation DSL(workflow_dsl_prompt.py) and schema metadata as the source of truth for new fields, including labels, defaults, dynamic/expression eligibility, and AI autofill hints.
- Agent node tool fields must be available to AI autofill. If a field can be configured on a tool attached to an agent node, clicking the agent icon should be able to populate that field automatically.
- Dynamic/expression-capable fields must be exposed to the expression dialog metadata. When a node is double-clicked, the expression dialog should be able to show `1/n` navigation and dynamically fill every eligible field for that node/operation.
- When adding a **new node type**, update the docs that enumerate nodes: add the node page under `frontend/src/docs/content/nodes/`, register it in `frontend/src/docs/manifest.ts`, and add the node to the reference docs — including `frontend/src/docs/content/reference/features.md` (both the per-node section and the node-types summary list), plus `node-types.md` and, for credential-backed nodes, `integrations.md` / `credentials.md` / `credentials-sharing.md`. 
- Add or extend frontend tests for meaningful UI behavior changes when practical, especially for autofill eligibility and expression dialog field discovery.

### PropertiesPanel modularity
`frontend/src/components/Panels/PropertiesPanel.vue` must stay a thin shell, not a node-specific implementation file. Node configuration UI belongs under `frontend/src/components/Panels/propertiesPanel/nodes/`, with one component per node type or shared paired node form (for example, `SetJsonOutputMapperNodeProperties.vue`). Node-specific helper state, computed values, API loading, and handlers should live with that node component or a sibling composable in the same `propertiesPanel/` module. Keep only cross-node panel orchestration, shared output/run handling, and context wiring in shared properties panel composables. When adding or changing a node property field, update the node-specific component instead of adding `selectedNode.type` branches to `PropertiesPanel.vue`.

### Expression evaluation (avoid executor vs dialog drift)
The canvas **expression evaluate** dialog (`/expressions/evaluate`, `ExpressionEvaluatorService`) and **workflow execution** (`WorkflowExecutor`) must agree on the same semantics for `$…` templates.

- **Core entry points** (touch these with extra care; keep behavior aligned):
  - `WorkflowExecutor.resolve_expression` — single full `$expr` and nested `$` inside the body after the leading `$` (`_substitute_nested_dollar_refs_for_eval`).
  - `WorkflowExecutor.resolve_arithmetic_expression` — used when `_has_arithmetic` is true (e.g. set/output schema/variable value fields); nested `$` inside one span is expanded in `replace_dollar_ref` before eval.
  - `WorkflowExecutor.evaluate_message_template` — per-span `resolve_expression` for each top-level `$…` match.
  - `ExpressionEvaluatorService` (`backend/app/services/expression_evaluator.py`) — mirrors executor rules for the API; changes should stay consistent with `workflow_executor.py`.
- **When changing any of the above:** extend or add cases in `backend/tests/test_expression_evaluator_service.py` (and related executor tests if behavior crosses modules). Prefer one shared helper over node-specific string eval.
- **Anti-pattern:** Resolving user expressions with ad-hoc `eval` / string concat outside these paths — causes preview vs run mismatches.

### OpenTelemetry tracing (keep span seams aligned)
OTel tracing is env-gated (`HEYM_OTEL_ENABLED`, disabled by default) and bootstrapped in `backend/app/observability/tracing.py` from `app/main.py`'s `setup_tracing(app)`. Spans are added at three seams only:
- `WorkflowExecutor.execute` wraps a `heym.workflow.execute` root span and stores the active OTel context in `self._otel_root_context`.
- `WorkflowExecutor.execute_node` wraps a `heym.node.execute` child span and re-attaches `self._otel_root_context` so node spans nest under the workflow span across `ThreadPoolExecutor` workers (see `tracing.run_with_context`).
- `LLMService.execute_with_tools` wraps each Agent tool invocation in a `heym.agent.tool.execute` child span while the Agent node span is active. Tool spans contain bounded identity, status, timing, and size metadata only; raw arguments and results are not span attributes.
- **When changing the executor's parallel/thread submit logic or any of these three seams:** preserve the context capture/re-attach and Agent node → tool parentage, and extend `backend/tests/test_observability_tracing.py`. Custom attributes use the `heym.*` prefix. Tracing must never break execution (failures are swallowed); the read-only status lives at `GET /api/config/observability`.

### WorkflowExecutor modularity
`backend/app/services/workflow_executor.py` must stay responsible for workflow orchestration, retries, tracing, cancellation, expression helpers, and shared result packaging. Node-specific execution logic belongs under `backend/app/services/node_execution/nodes/`, with one handler module per node type and registration in `backend/app/services/node_execution/registry.py`.

- Do not add new `node_type` branches or node-specific business logic to `WorkflowExecutor._execute_node_logic`; route new or changed node behavior through a modular node handler.
- Keep handler changes behavior-preserving unless the task explicitly asks for product behavior changes. Handlers may use `NodeExecutionContext.executor` for shared executor services, but should not duplicate retry, tracing, cancellation, or final `NodeResult` packaging.
- When adding a new node type, add its handler, register it in the node execution registry, update the node DSL/schema/docs required by the node integration policy, and add focused backend tests for the handler behavior.

### Alert type modularity
`backend/app/services/alerts/evaluator.py` owns claiming, the fire/recover state machine, event packaging, notify dispatch, and error containment. Metric computation for each alert type belongs under `backend/app/services/alerts/types/`, one module per alert type, registered in `backend/app/services/alerts/registry.py`.

- Do not add `alert_type` branches to the evaluator. A new alert type is one handler module, one registry entry, one config model in `backend/app/models/alert_schemas.py`, and focused tests.
- Handlers compute a metric over a window and return an `AlertObservation`. They must not write events, dispatch notifications, mutate alert state, or re-derive scope — `workflow_ids` arrives already resolved on the `AlertEvaluationContext`.
- Cost metrics must resolve USD through `app/services/llm_pricing.py`, and duration percentiles through `app/api/analytics.py::calculate_percentile`. An alert that disagrees with the Traces or Analytics tab about the same window is worse than no alert.
- Evaluation runs inside the leader-gated `CronScheduler` loop and claims rows with `FOR UPDATE SKIP LOCKED` while advancing `next_check_at` in the same statement. Preserve that claim when touching the loop; without it a leader handoff mid-pass double-fires.
- The frontend mirrors this: `StepCondition.vue` selects per-type field components from a lookup map, not a `v-if` chain, and node-type-style branching does not belong in `AlertsTab.vue`.
- When adding a new alert type, also update `frontend/src/docs/content/tabs/alerts-tab.md`, `reference/features.md`, and the alert tool descriptions in `backend/app/api/ai_assistant.py`.

### Release tour (announce user-visible work)
**Any change a user can see must ship with its release tour entry in the same change.** A feature nobody discovers was not delivered. This covers new UI, new node types, new tabs or panels, and reworked UX flows. Pure refactors, backend-only changes, and bug fixes with no visible surface are exempt.

The system lives in `frontend/src/features/release-tour/`, mounted through `ReleaseTourHost.vue`. It is **desktop only** (above the 768px breakpoint) and is mounted on three screens: the dashboard (every tab), Chat, and Docs. The launcher button teleports into `#release-tour-launcher-slot`, which each of those views puts in `AppHeader`'s `before-docs` slot. The header button appears immediately; only the *automatic* popup waits for a screen's intro video to be dismissed. `releaseRegistry.ts` is the source of truth; `releaseTourMapper.ts` holds the pure logic and must stay side-effect free.

- Add a section to the **current unreleased** entry in `releaseRegistry.ts`: `id`, `title`, a `blocks` prose summary, and `tour` metadata (`description`, `useCases`, `tourVisual`).
- List the new section's `id` in that release's `sectionOrder`. A section missing from `sectionOrder` never reaches the tour.
- Build a matching animated mock under `components/visuals/` and register it in `tourVisuals.ts` under the same `tourVisual` key. An unregistered key silently falls back to the neutral visual, so the registry test in `releaseTourMapper.test.ts` guards this — keep it passing.
- Visuals are **mock UI, never live UI**: Tailwind semantic tokens, no production API calls, no host-page state. Animate with CSS transitions, Vue `<Transition>`, and `useCycleStep` for looping demo states; there is no motion library and adding one needs a separate decision.
- Keep `tourEnabled: false` on a release that is still in progress, then flip it to `true` in the release commit. The registry still renders release notes while the flag is off — it only gates the automatic popup.
- Start a new release entry (new `releaseId`, newer `publishedAt`) once the previous one has shipped. Only the newest enabled release is ever shown, so old unseen releases do not queue up behind it.
- Bump `TOUR_REVISION` only to deliberately re-show an already-announced release; it invalidates every user's stored "seen" state.
- E2E: `prepareAuthenticatedPage` marks the current tour seen (`heym-release-tour-seen`, same idea as `showcase_seen_*`) so the auto-open panel does not intercept clicks. Specs that cover the popup pass `{ allowReleaseTour: true }`. Keep the seeded versioned id in `frontend/e2e/support.ts` aligned with the newest enabled `releaseId` and `TOUR_REVISION`.

## Repository Layout
```
heymrun/
├── frontend/src/
│   ├── components/{Canvas,Nodes,ui, Panels, Evals, MCP, Teams}/
│   ├── features/       # Self-contained feature modules (release-tour, showcase, templates, runbook)
│   ├── stores/         # Pinia stores (workflow, auth, folder)
│   ├── views/          # DashboardView, EditorView, ChatPortalView
│   ├── services/       # API clients
│   └── types/          # TypeScript types
├── backend/app/
│   ├── api/            # Routes: workflows, auth, mcp, portal, evals, traces
│   ├── models/         # Pydantic schemas (schemas.py, eval_schemas.py)
│   ├── services/       # Executor, LLM, RAG, agent engine
│   └── db/             # Database configuration
├── backend/tests/      # pytest unit tests
├── backend/alembic/    # Database migrations
└── run.sh / run_tests.sh / check.sh  # Development scripts
```

## Tech Guidelines
- **Vue Flow:** Use `@vue-flow/core`, custom nodes extend `BaseNode.vue`, store nodes/edges in Pinia
- **Pinia:** Stores in `frontend/src/stores/`, use composition API `defineStore`, export typed interfaces
- **FastAPI:** Use dependency injection via `app/api/deps.py`, sessions via `get_db()`, auth via `get_current_user()`
- **Testing:** Backend uses pytest (tests in `backend/tests/`, run with `uv run pytest tests/`). Frontend unit tests use Vitest (`frontend/src/**/*.test.ts`, `bun run test`, enforced in CI). Frontend E2E tests use Playwright (specs in `frontend/e2e/`, run with `./run_e2e.sh`). **New features and meaningful behavior changes must include or extend backend tests** covering the touched code paths; new UI behavior should include Playwright coverage when practical.
- **Tests use** unittest.TestCase and unittest.IsolatedAsyncioTestCase with AsyncMock for database mocking

## Tech Stack
- **Frontend:** Vue.js 3 + TypeScript (strict) + Vite + Bun + Shadcn Vue + Tailwind CSS
- **Backend:** Python 3.11+ + FastAPI + UV + SQLAlchemy 2.0 (async) + Pydantic
- **Database:** PostgreSQL 16 + AsyncPG
- **Auth:** JWT (access + refresh) + bcrypt

## MCP Tools & Skills
Use `sequentialthinking` for complex planning, `shadcn` for UI components. Always query for skills before starting. Use `heym-documentation` skill when documentation changes are involved.

## Feature Documentation Policy
Medium/large features (new UI, node types, APIs, UX) must update docs via `heym-documentation` skill. Small bug fixes/refactors do not require doc updates. The same threshold triggers a release tour entry — see **Release tour (announce user-visible work)**.

## Licensing
MIT with Commons Clause condition - open for use, not for commercial resale. See LICENSE and COMMONS-CLAUSE.md.

## Critical Notes
- **Git workflow:** Work directly on `main` branch — no worktrees, no feature branches. Commit and push to main.
- **Before git push:** Run `./check.sh` from the repo root (applies `ruff format` on the backend, then lint and tests). Commit any formatting-only diffs with your changes.
- **Schema changes:** Always run `uv run alembic upgrade head` after migrations
- **Order matters:** PostgreSQL must be running before backend starts (run.sh handles this)
- **Never commit:** Secrets, env files, or Turkish text in code/comments
- **Cursor Cloud:** Start Docker daemon → postgres → migrations → backend (PLAYWRIGHT_INSTALL_AT_STARTUP=false) → frontend
