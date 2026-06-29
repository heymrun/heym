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
Frontend: Playwright E2E specs live in `frontend/e2e/`; run them with `./run_e2e.sh` from the repository root
**New features must include backend tests** - run `./check.sh` before git push (includes backend tests via `./run_tests.sh`)
**New UI behavior should include Playwright E2E coverage when practical.** E2E tests run as a separate required job in PR checks and are intentionally excluded from `./check.sh` to keep the default local check path fast.
If the local environment does not export `SECRET_KEY`, prefix full-suite commands with `SECRET_KEY=test-secret-key-for-tests-only-32-bytes` (test-only value; never use it for runtime/prod).

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
OTel tracing is env-gated (`HEYM_OTEL_ENABLED`, disabled by default) and bootstrapped in `backend/app/observability/tracing.py` from `app/main.py`'s `setup_tracing(app)`. Spans are added at two seams only:
- `WorkflowExecutor.execute` wraps a `heym.workflow.execute` root span and stores the active OTel context in `self._otel_root_context`.
- `WorkflowExecutor.execute_node` wraps a `heym.node.execute` child span and re-attaches `self._otel_root_context` so node spans nest under the workflow span across `ThreadPoolExecutor` workers (see `tracing.run_with_context`).
- **When changing the executor's parallel/thread submit logic or these two methods:** preserve the context capture/re-attach, and extend `backend/tests/test_observability_tracing.py`. Custom attributes use the `heym.*` prefix. Tracing must never break execution (failures are swallowed); the read-only status lives at `GET /api/config/observability`.

## Repository Layout
```
heymrun/
├── frontend/src/
│   ├── components/{Canvas,Nodes,ui, Panels, Evals, MCP, Teams}/
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
- **Testing:** Backend uses pytest (tests in `backend/tests/`, run with `uv run pytest tests/`). Frontend E2E tests use Playwright (specs in `frontend/e2e/`, run with `./run_e2e.sh`). **New features and meaningful behavior changes must include or extend backend tests** covering the touched code paths; new UI behavior should include Playwright coverage when practical.
- **Tests use** unittest.TestCase and unittest.IsolatedAsyncioTestCase with AsyncMock for database mocking

## Tech Stack
- **Frontend:** Vue.js 3 + TypeScript (strict) + Vite + Bun + Shadcn Vue + Tailwind CSS
- **Backend:** Python 3.11+ + FastAPI + UV + SQLAlchemy 2.0 (async) + Pydantic
- **Database:** PostgreSQL 16 + AsyncPG
- **Auth:** JWT (access + refresh) + bcrypt

## MCP Tools & Skills
Use `sequentialthinking` for complex planning, `shadcn` for UI components. Always query for skills before starting. Use `heym-documentation` skill when documentation changes are involved.

## Feature Documentation Policy
Medium/large features (new UI, node types, APIs, UX) must update docs via `heym-documentation` skill. Small bug fixes/refactors do not require doc updates.

## Licensing
MIT with Commons Clause condition - open for use, not for commercial resale. See LICENSE and COMMONS-CLAUSE.md.

## Critical Notes
- **Git workflow:** Work directly on `main` branch — no worktrees, no feature branches. Commit and push to main.
- **Before git push:** Run `./check.sh` from the repo root (applies `ruff format` on the backend, then lint and tests). Commit any formatting-only diffs with your changes.
- **Schema changes:** Always run `uv run alembic upgrade head` after migrations
- **Order matters:** PostgreSQL must be running before backend starts (run.sh handles this)
- **Never commit:** Secrets, env files, or Turkish text in code/comments
- **Cursor Cloud:** Start Docker daemon → postgres → migrations → backend (PLAYWRIGHT_INSTALL_AT_STARTUP=false) → frontend
