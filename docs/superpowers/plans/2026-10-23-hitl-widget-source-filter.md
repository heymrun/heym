# HITL widget source filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a HITL dashboard widget show reviews from one workflow, or one step of it, chosen in widget Settings (Heym and Work), on the canvas, or by AI fine-tune, without ever showing a review the viewer could not already see.

**Architecture:** The choice is two fields on the widget workflow's HITL `chartOutput` node (`hitlWorkflowId`, `hitlNodeId`). A light module `app/services/hitl_widget_filter.py` reads and writes them and knows which steps can wait. `hitl_service.review_scope_clause` is the one rule for whose reviews a user may see (owner today). Every read re-checks that scope; saves reject a changed out-of-scope choice.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Pydantic, Vue 3 + TS, Vitest, Playwright; Heym Work (Vue + FastAPI) over `vendor/heymrun`.

Spec: `docs/superpowers/specs/2026-10-23-hitl-widget-source-filter-design.md`

---

## File map

heymrun backend
- Create `backend/app/services/hitl_widget_filter.py`: `HitlWidgetFilter` dataclass, `REVIEW_STEP_KINDS`, `review_step_kind(node)`, `review_steps(nodes)`, `hitl_widget_filter(nodes)`, `with_hitl_widget_filter(nodes, filter)`, `strip_hitl_widget_filter(nodes)`, `hitl_filter_changed(old_nodes, new_nodes)`, access error texts. No DB, no settings.
- Modify `backend/app/services/hitl_service.py`: `review_scope_clause`, filters on `list_pending_hitl_for_owner`, `list_review_sources_for_owner`, `filter_in_review_scope`, `ensure_filter_in_review_scope`, `count_pending_by_step`.
- Modify `backend/app/models/schemas.py`: `HITLReviewSourceStep`, `HITLReviewSource`, `HITLReviewSourcesResponse`, `HITLDashboardCountsResponse`.
- Modify `backend/app/models/dashboard_schemas.py`: `HitlWidgetFilterModel`; `DashboardWidgetResponse.hitl_filter`; `WidgetUpdateRequest.hitl_filter`.
- Modify `backend/app/api/hitl.py`: inbox query params + 403, `GET /hitl/sources`, `GET /hitl/inbox/dashboard-counts` (declared before `/{token}`).
- Modify `backend/app/services/dashboard_data.py` + `chart_payload.py`: payload carries `filter`.
- Modify `backend/app/api/dashboards.py`: widget data access error, `hitl_filter` on responses, PATCH `hitl_filter`, AI create strip, AI refine sources context + validation.
- Modify `backend/app/api/workflows.py` `update_workflow`: reject changed out-of-scope filter on widget workflows.
- Modify `backend/app/services/workflow_dsl_prompt.py`: document the fields.
- Tests: `backend/tests/test_hitl_widget_filter.py` (new), extend `test_hitl_inbox.py`.

heymrun frontend
- Modify `src/types/dashboard.ts`, `src/types/workflow.ts`, `src/services/api.ts`, `src/ports/index.ts`, `src/ports/installHeymPorts.ts`(+test).
- Create `src/components/Dashboards/hitlFilter.ts` (+ `hitlFilter.test.ts`): API-free picker core.
- Create `src/components/Dashboards/HitlFilterFields.vue`: the two selects over `hitlApi.sources()`.
- Modify `WidgetSettingsDialog.vue`, `DashboardsPanel.vue` (save), `HitlCarousel.vue`, `ChartView.vue`, `Panels/propertiesPanel/nodes/ChartOutputNodeProperties.vue`.
- E2E: extend `e2e/tab-dashboard.spec.ts`.
- Docs: `docs/content/tabs/dashboard-tab.md`, `docs/content/nodes/chart-output-node.md`.

heym-work
- Create `frontend/src/components/widgets/WidgetSettingsDialog.vue`; delete `RenameWidgetDialog.vue`.
- Modify `WidgetCardActions.vue`, `WidgetCard.vue`, `WidgetGrid.vue`, `services/heymApi.ts`, `heym/installPorts.ts`(+test).
- Modify `backend/heym_work/api/heym_routes.py`, `api/menu.py`, `tests/fake_heym.py`, `tests/test_menu_badges.py`.

---

### Task 1: Filter module (pure)

**Files:** Create `backend/app/services/hitl_widget_filter.py`, `backend/tests/test_hitl_widget_filter.py`

- [ ] Write tests: `review_step_kind` returns `"agent"` only for `hitlEnabled` agents, `"slack"` only for `requestApproval`/`sendButtons`/`sendForm`, `None` for codex, plain slack `sendMessage`, disabled agent. `hitl_widget_filter` reads the HITL chartOutput (ignores non-hitl chartOutputs, blank values, node id without workflow id). `with_hitl_widget_filter` sets/clears on a deep copy and leaves other nodes alone. `strip_hitl_widget_filter` removes both keys. `hitl_filter_changed` compares old vs new.
- [ ] Run, see them fail (`uv run pytest tests/test_hitl_widget_filter.py -q`).
- [ ] Implement:

```python
WAITING_SLACK_OPERATIONS = frozenset({"requestApproval", "sendButtons", "sendForm"})

@dataclass(frozen=True)
class HitlWidgetFilter:
    workflow_id: uuid.UUID
    node_id: str | None = None

def review_step_kind(node: object) -> str | None: ...
def review_steps(nodes: object) -> list[tuple[str, str, str]]:  # (node_id, label, kind)
def hitl_widget_filter(nodes: object) -> HitlWidgetFilter | None: ...
def with_hitl_widget_filter(nodes: list, value: HitlWidgetFilter | None) -> list: ...
def strip_hitl_widget_filter(nodes: list) -> list: ...
def hitl_filter_changed(old_nodes: object, new_nodes: object) -> bool: ...
```

`WAITING_SLACK_OPERATIONS` is asserted equal to `slack_operations.WAITING_OPERATIONS` in the test, so the two cannot drift (importing `slack_operations` here would pull the node runtime into a module dashboards import).

- [ ] Run tests, pass. Commit.

### Task 2: Review scope, sources, filtered inbox, counts (service + API)

**Files:** Modify `hitl_service.py`, `schemas.py`, `api/hitl.py`; extend `tests/test_hitl_inbox.py`

- [ ] Tests (AsyncMock db, SQL-string assertions as the file already does):
  - `list_pending_hitl_for_owner(db, owner, workflow_id=W, node_id="n2")` puts both columns in the WHERE of count and rows
  - `list_hitl_inbox(user, db, workflow_id=W, node_id=None)` with `filter_in_review_scope` False raises 403 with `HITL_FILTER_ACCESS_ERROR` and never lists
  - `node_id` without `workflow_id` → 422
  - `list_review_sources_for_owner` keeps only workflows with review steps, skips `dashboard_widget`, SQL has the owner clause
  - `count_pending_by_step` groups by workflow and node
  - `dashboard_hitl_counts`: unfiltered widget counts all, filtered counts its workflow/step, out-of-scope filter adds 0, unreadable dashboards left out
- [ ] Implement `review_scope_clause(user_id) -> ColumnElement[bool]` (`Workflow.owner_id == user_id`) and switch `_owned_pending_filters` to it; keyword filters on `list_pending_hitl_for_owner`; `list_review_sources_for_owner(db, user_id) -> list[ReviewSource]`; `filter_in_review_scope(db, user_id, value) -> bool`; `ensure_filter_in_review_scope(db, user_id, value)` raising 422 `"Pick one of your workflows that waits for a review"` when the workflow or step is not a source; `count_pending_by_step(db, user_id) -> dict[tuple[uuid, str], int]`.
- [ ] API: `GET /hitl/inbox` gets `workflow_id: uuid.UUID | None = Query(None)`, `node_id: str | None = Query(None, max_length=64)`; `GET /hitl/sources`; `GET /hitl/inbox/dashboard-counts` with `dashboard_id: list[uuid.UUID] = Query(default=[], max_length=100)` → reachable dashboards (`reachable_dashboard_ids`), their HITL widgets' workflows' nodes, filters, matched against `count_pending_by_step`. Routes declared before `/{token}`.
- [ ] Run tests, pass. Commit.

### Task 3: Widget payload, access error, responses, Settings save

**Files:** Modify `dashboard_data.py`, `chart_payload.py`, `dashboard_schemas.py`, `api/dashboards.py`; tests in `test_hitl_widget_filter.py`

- [ ] Tests: `compute_widget_data` returns `{"type": "hitl", "filter": {"workflow_id": W, "node_id": "n1"}}`; `build_chart_payload` adds the same; `get_widget_data` replaces it with the editor or read-only access error when out of scope (deleted and foreign alike) and keeps it when in scope; `update_widget` with `hitl_filter` on a bar widget → 400, out of scope → 422, valid → nodes written + `add_workflow_version` awaited, `None` clears, omitted leaves nodes untouched; `_widget_to_response` carries `hitl_filter`.
- [ ] Implement. `HitlWidgetFilterModel(workflow_id: uuid.UUID, node_id: str | None = Field(None, max_length=64))`. `WidgetUpdateRequest.hitl_filter` uses `model_fields_set` for the tri-state. `_hitl_filters(db, widgets) -> dict[uuid, HitlWidgetFilterModel]` one query over HITL widgets' workflows; used by dashboard GET, update, refine, revert.
- [ ] Run tests, pass. Commit.

### Task 4: AI create / fine-tune, canvas save, DSL prompt

**Files:** Modify `api/dashboards.py`, `api/workflows.py`, `workflow_dsl_prompt.py`; tests in `test_hitl_widget_filter.py`

- [ ] Tests: `ai_generate_widget` strips `hitlWorkflowId`/`hitlNodeId`; `_hitl_sources_context(sources)` lists names, ids, steps and kinds; `ai_refine_widget` on a HITL widget passes that context into `generate_widget_dsl` and raises 422 `"The model chose a workflow or step with no reviews to show. Try again."` for an invented id, accepts an unchanged foreign filter; `update_workflow` on a `dashboard_widget` with a changed out-of-scope filter → 422, unchanged → passes.
- [ ] Implement; DSL prompt HITL section documents `hitlWorkflowId` / `hitlNodeId` ("only ids from the review sources you are given; leave both out to show every review").
- [ ] Run `uv run pytest tests/test_hitl_widget_filter.py tests/test_hitl_inbox.py tests/test_dashboards_api.py tests/test_dashboard_widget_revert.py -q`, pass. Commit.

### Task 5: Heym frontend

**Files:** see file map

- [ ] Vitest `hitlFilter.test.ts`: `stepOptions` (one step → only it; two → "All agents" first; Slack suffix), `pickWorkflow` (one step selected, several → node null), `workflowOptions` adds "A workflow you cannot open" for a stored id not in sources, `stepOptionsFor` adds "A step that no longer exists", `sameFilter`.
- [ ] Implement `hitlFilter.ts`, types, `hitlApi.inbox(filter?)` (params `workflow_id`, `node_id`), `hitlApi.sources()`, port `inbox(filter?)`, `installHeymPorts` passes it (extend its test), `HitlCarousel` `filter` prop + watch, `ChartView` passes `chartPayload.filter`, `HitlFilterFields.vue`, Settings section (sends `hitl_filter` only when changed), `ChartOutputNodeProperties` fields for `hitl`.
- [ ] `bun run lint && bun run typecheck && bun run test` pass. Commit.

### Task 6: E2E + docs

- [ ] `tab-dashboard.spec.ts`: two workflows each with a HITL agent, one seeded review each (`POST /workflows/{id}/pending-review`), a HITL widget shows 2 pending; Settings → pick workflow A → saves → `1/1 pending` and A's name only.
- [ ] Docs: dashboard-tab HITL bullet + Settings; chart-output-node `hitl` fields.
- [ ] `./run_e2e.sh` for the spec if the stack runs; `./check.sh`. Commit.

### Task 7: Heym Work

- [ ] Point `vendor/heymrun` at the local heymrun branch commit (not committed in Work).
- [ ] `WidgetSettingsDialog.vue` (Title + HITL fields with `UiSelect` over `@heym/components/Dashboards/hitlFilter`), actions/card/grid `settings` event, `heymHitl.inbox(filter?)` + `sources()`, ports pass filter, `heym_routes` `GET /hitl/sources` (EDITOR), menu badges from Heym dashboard counts, fake + tests.
- [ ] Work `./check.sh` (or its frontend lint/typecheck/test + backend tests). Commit locally on Work main.
