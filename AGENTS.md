You are an expert full-stack AI/ML engineer building Heym, an n8n-like AI workflow automation platform with visual editor.

## AI Coding Agents (Required)
Read and follow this `AGENTS.md` at the start of every session. Repository conventions and policies override default agent behavior.

## Essential Commands

### Quick Start
```bash
./run.sh                    # Start all services (postgres, backend, frontend)
./run.sh --no-debug         # Start with INFO logging instead of DEBUG
./check.sh                  # Run frontend lint/typecheck, backend Ruff checks, and backend tests
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
Frontend: No tests yet (add when needed)
**New features must include backend tests** - run `./check.sh` before git push (includes backend tests via `./run_tests.sh`)

### Expression evaluation (avoid executor vs dialog drift)
The canvas **expression evaluate** dialog (`/expressions/evaluate`, `ExpressionEvaluatorService`) and **workflow execution** (`WorkflowExecutor`) must agree on the same semantics for `$…` templates.

- **Core entry points** (touch these with extra care; keep behavior aligned):
  - `WorkflowExecutor.resolve_expression` — single full `$expr` and nested `$` inside the body after the leading `$` (`_substitute_nested_dollar_refs_for_eval`).
  - `WorkflowExecutor.resolve_arithmetic_expression` — used when `_has_arithmetic` is true (e.g. set/output schema/variable value fields); nested `$` inside one span is expanded in `replace_dollar_ref` before eval.
  - `WorkflowExecutor.evaluate_message_template` — per-span `resolve_expression` for each top-level `$…` match.
  - `ExpressionEvaluatorService` (`backend/app/services/expression_evaluator.py`) — mirrors executor rules for the API; changes should stay consistent with `workflow_executor.py`.
- **When changing any of the above:** extend or add cases in `backend/tests/test_expression_evaluator_service.py` (and related executor tests if behavior crosses modules). Prefer one shared helper over node-specific string eval.
- **Anti-pattern:** Resolving user expressions with ad-hoc `eval` / string concat outside these paths — causes preview vs run mismatches.

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
- **Testing:** Backend uses pytest (tests in `backend/tests/`, run with `uv run pytest tests/`), no frontend tests yet. **New features and meaningful behavior changes must include or extend backend tests** covering the touched code paths; do not ship feature work without tests when the change is testable in pytest.
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
Commons Clause + MIT - open for use, not for commercial resale. See LICENSE file.

## Critical Notes
- **Git workflow:** Work directly on `main` branch — no worktrees, no feature branches. Commit and push to main.
- **Before git push:** Run `./check.sh` from the repo root (applies `ruff format` on the backend, then lint and tests). Commit any formatting-only diffs with your changes.
- **Schema changes:** Always run `uv run alembic upgrade head` after migrations
- **Order matters:** PostgreSQL must be running before backend starts (run.sh handles this)
- **Never commit:** Secrets, env files, or Turkish text in code/comments
- **Cursor Cloud:** Start Docker daemon → postgres → migrations → backend (PLAYWRIGHT_INSTALL_AT_STARTUP=false) → frontend
