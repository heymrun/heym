# HITL widget source filter

Date: 2026-10-23
Repos: heymrun (this repo), heym-work

## Problem

A HITL dashboard widget shows every pending review the signed-in user owns, wherever it is
placed. A page about invoices shows the HR approvals too, and one workflow can have two steps
waiting at the same time. People need to point a widget at one workflow, and at one step inside
it.

## Goals

- A HITL widget can show reviews from all workflows (today's behaviour, the default), one
  workflow, or one step of one workflow.
- The choice is made in widget Settings, in Heym and in Heym Work. In Work, the card's Rename
  action becomes Settings and keeps the title field.
- AI fine-tune can change the choice ("show only the invoice approvals").
- A widget created by AI starts unfiltered unless its description names a workflow.
- The Workflow field has an icon that opens the chosen workflow in a new tab (Heym's editor,
  Work's Home with the workflow highlighted).

## Non-goals

- Codex follow-ups. They live in `codex_followup_requests`, are answered with free text and are
  not in the inbox today. Codex steps are not offered as a source until they are; adding the
  node type to the source list is the only change the picker needs then.
- Choosing several workflows or several steps. One workflow, and inside it one step or all.
- Release tour entry (the user's call for this change).

## Where the choice lives

On the widget workflow's `chartOutput` node, next to `chartType: "hitl"`:

| Field | Meaning |
|---|---|
| `hitlWorkflowId` | Workflow whose reviews the widget shows. Absent: all workflows. |
| `hitlNodeId` | Step inside that workflow. Absent: every step of it. Ignored without `hitlWorkflowId`. |

Settings, AI fine-tune and the canvas all edit this one place, so a change is an ordinary
workflow edit: it shows in Edit History and Revert undoes it. No migration.

One backend helper, `hitl_widget_filter(nodes) -> HitlWidgetFilter | None`, reads the fields
from a widget workflow's nodes. Every reader below uses it.

## Review sources

A review source is a workflow the caller can open (see Security), not
`kind == "dashboard_widget"`, with at least one step that can wait for a person:

- `agent` with `data.hitlEnabled` true (`kind: "agent"`)
- `slack` with `data.operation` in `slack_operations.WAITING_OPERATIONS`, which are
  `requestApproval`, `sendButtons` and `sendForm`, the steps Work Flows create
  (`kind: "slack"`)

Both write `hitl_requests` rows with `agent_node_id` set to the step's node id, so filtering
by workflow and node needs no new column.

## Security

The stored filter never grants anything; every read re-checks the viewer.

- **Two scopes.** `hitl_service.own_reviews_clause` is the user's own queue (workflows they
  own): the unfiltered inbox, an unfiltered widget and the review link use it.
  `review_access_clause` is every workflow the user can open (owner, direct share, team share,
  instance admin), the reach that lets them run it: review sources, a filtered inbox, filtered
  widgets, page counts and deciding a review from the inbox use it. Deciding resumes the run,
  which a read share may already do.
- **Scenario.** A owns a workflow with a HITL agent and shares it with B. B points a HITL widget
  at it and shares the dashboard with C, who cannot open A's workflow. B sees and decides A's
  workflow's reviews in the widget; C does not see the widget at all.
- **Only reachable choices.** The picker lists workflows the user can open. Settings, AI create
  and fine-tune, and canvas saves reject a *changed* filter on a workflow the saver cannot open
  (422). An unchanged filter is not revalidated, so a shared editor can still save other settings.
- **Read time is the boundary.** Writes reach a widget workflow through more paths than these
  (imports, clones, templates, chat build), so save-time checks are a convenience. Every read
  re-checks the viewer:
  - dashboard listing: a widget filtered on a workflow the viewer cannot open is left out,
    except for the dashboard's owner
  - widget data: the owner gets `error` = "You no longer have access to the workflow this
    widget shows. Pick another one in widget Settings."; anyone else gets 404 "Widget not found"
  - `GET /hitl/inbox?workflow_id=…`: 403 with the same text
  - dashboard counts: such a widget adds nothing
- **No existence leak.** A deleted workflow and one the viewer cannot open give the same answer,
  which never names the workflow.
- The inbox review link (public token) stays owner-only.

## Backend (heymrun)

### Inbox

`GET /hitl/inbox` takes optional `workflow_id` (UUID) and `node_id` (string, max 64).
`node_id` without `workflow_id` is a 422. `pending_total` counts the filtered queue.
`list_pending_hitl_for_owner` gains the two keyword filters.

### Sources

`GET /hitl/sources` returns the caller's review sources, ordered by workflow name:

```json
{"sources": [{"workflow_id": "…", "workflow_name": "Invoice approval",
  "steps": [{"node_id": "…", "label": "Approver", "kind": "agent"},
            {"node_id": "…", "label": "Ask finance", "kind": "slack"}]}]}
```

Scanning lives in `hitl_service` (`list_review_sources_for_owner`), not in the router.

### Widget payload

The widget data endpoint keeps returning the HITL marker without caching it, now with the
filter when one is set: `{"type": "hitl", "filter": {"workflow_id": "…", "node_id": "…"}}`.
`build_chart_payload` adds the same key for a `chartOutput` run on the canvas.

### Widget responses

`DashboardWidgetResponse` gains `hitl_filter: {workflow_id, node_id} | null`, filled for HITL
widgets only, with one extra query over those widgets' workflows. Settings opens with it.

### Saving from Settings

`WidgetUpdateRequest` gains `hitl_filter`, with the same tri-state as the row link: left out
keeps the current filter, `null` clears it, an object sets it.

- Only on a widget whose chart type is `hitl`; otherwise 400.
- The workflow must be one of the caller's review sources and the node, when given, one of
  its steps; otherwise 422 ("Pick one of your workflows that waits for a review").
- The update writes the fields onto the HITL `chartOutput` node, records the pre-edit version
  with `add_workflow_version` (as AI fine-tune does), and bumps `updated_at`, so the card
  reloads.

A shared editor who does not own the filtered workflow can still save other settings: the
frontend sends `hitl_filter` only when it changed, so validation never sees the untouched value.

### Work's page badges

`GET /hitl/inbox/dashboard-counts?dashboard_id=…` (repeatable, at most 100) returns
`{"counts": {"<dashboard id>": n}}` for the dashboards the caller can open that hold a HITL
widget. `n` counts the caller's pending reviews that match any HITL widget on that dashboard
(an unfiltered widget matches all). One grouped query of the caller's pending reviews by
`(workflow_id, agent_node_id)`, matched in Python.

### AI

- **Create** (`ai_generate_widget`): the prompt gets the caller's review sources, so a
  description that names a workflow ("pending reviews of Discount approval") points the new
  widget at it; otherwise it shows every review. An invented id is a 422, as in fine-tune.
- **Fine-tune** (`ai_refine_widget`) of a HITL widget: the prompt gets the caller's review
  sources (workflow names, ids, step labels, node ids, kinds). After generation, if the filter
  differs from the current one, it is validated like a Settings save. An invalid choice is a
  422 ("The model chose a workflow or step with no reviews to show. Try again."), never a silent
  fall back to all.
- `workflow_dsl_prompt.py` documents both fields in the HITL chartOutput section.

## Frontend (heymrun)

- `types/dashboard.ts`: `HitlFilter`, `HitlSource`, `HitlSourceStep`; `ChartPayload.filter`,
  `DashboardWidget.hitl_filter`, `WidgetUpdateRequest.hitl_filter`.
- `components/Dashboards/hitlFilter.ts`: API-free core both apps use.
  - `stepOptions(source)`: "All agents" plus each step's label when there are two or more; the
    single step alone when there is one. Slack steps are labelled `"<label> (Slack)"`.
  - `pickWorkflow(source)`: the filter after a workflow is chosen; with one step that step is
    selected.
  - Placeholders for a stored workflow or step the editor cannot see: "A workflow you cannot
    open", "A step that no longer exists", so it can be cleared (same pattern as the row link).
- `HitlFilterFields.vue`: Workflow select ("All workflows", clearable) and, once a workflow is
  chosen, a "Select agent" select showing node labels. It loads sources through `hitlApi` and
  `v-model`s a `HitlFilter | null`. Used by:
  - `WidgetSettingsDialog.vue` for HITL widgets (in a "Reviews" section)
  - `ChartOutputNodeProperties.vue` for `chartType: "hitl"`, writing the node fields directly
- `HitlCarousel.vue` takes a `filter` prop (from `ChartView` via `chartPayload.filter`), passes
  it to the port and reloads when it changes. "n pending" follows the filter.
- `ports/index.ts`: `HitlPort.inbox(filter?: HitlFilter)`; `installHeymPorts.ts` and
  `hitlApi.inbox` pass it as query parameters.

## Heym Work

- `WidgetSettingsDialog.vue` replaces `RenameWidgetDialog.vue`: Title, and for HITL widgets the
  same Workflow and Select agent fields, built with Work's `UiSelect` over the shared
  `hitlFilter.ts` core. Saves through `heymDashboards.updateWidget`.
- `WidgetCardActions.vue`: the Pencil "Rename" button becomes a Settings button
  (`aria-label="Settings for <title>"`); `rename` events become `settings` through `WidgetCard`
  and `WidgetGrid`.
- `services/heymApi.ts`: `heymHitl.inbox(filter?)` with query parameters, `heymHitl.sources()`.
- `heym/installPorts.ts`: the HITL port passes the filter through.
- `api/heym_routes.py`: `GET /hitl/sources` for editors. The inbox route already forwards query
  parameters.
- `api/menu.py`: page badges come from Heym's `/api/hitl/inbox/dashboard-counts` instead of
  copying one total onto every page.
- After the heymrun change merges, re-pin `vendor/heymrun`.

## Edge cases

- Filtered workflow deleted or no longer reachable: the owner sees the access error, others do
  not see the widget. Step removed while the workflow is still reachable: "No pending reviews".
  Settings shows the placeholder either way so it can be changed.
- Shared dashboard: an unfiltered widget shows each viewer their own queue; a filtered widget
  shows its workflow's reviews to viewers who can open it and is hidden from the rest.
- A cloned widget copies its workflow, filter included.
- A paused sub-workflow step is recorded on the top-level run's workflow, so it is not offered
  as a step of the sub-workflow. Unchanged by this work.

## Tests

Backend (heymrun):
- inbox filters by workflow, by workflow and node, `pending_total` follows; `node_id` alone is
  422; a workflow outside the caller's scope is 403 and returns no rows
- widget data with a filter outside the viewer's scope returns the access error (editor and
  read-only texts), for a deleted workflow and for another user's workflow alike
- canvas save (workflow update) of a widget workflow rejects a changed out-of-scope filter and
  accepts an unchanged one
- sources: `hitlEnabled` agents only, waiting Slack operations only, Codex and widget workflows
  excluded, other users' workflows excluded
- Settings save: non-HITL widget 400, foreign workflow 422, node outside the workflow 422,
  `null` clears, version recorded, untouched filter not revalidated
- payload and widget response carry the filter
- AI create strips the fields; fine-tune gets sources in its prompt and rejects an invented id
- dashboard counts: union of widget filters, unfiltered widget counts all, unreadable dashboards
  left out

Frontend (heymrun): Vitest for `hitlFilter.ts`, the carousel passing its filter to the port,
and the Settings section; Playwright: a workflow with two HITL agents, pick one in Settings,
the carousel shows only its review.

Heym Work: Vitest for the Settings dialog and actions; backend test for page badges against
`fake_heym`.

## Docs

`frontend/src/docs/content/tabs/dashboard-tab.md` (HITL widget bullet and widget Settings) and
`nodes/chart-output-node.md` (the `hitl` chart type and the two new fields).
