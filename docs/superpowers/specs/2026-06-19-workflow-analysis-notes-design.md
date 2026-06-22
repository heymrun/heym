# Workflow Analysis Notes — Design

**Date:** 2026-06-19
**Status:** Approved (pending spec review)

## Summary

Add a left-side **"Analyze my workflow"** panel to the workflow editor. The panel
holds one shared, persistent **markdown document per workflow** that:

- AI can **seed** ("Analyze my workflow") and **regenerate** ("Reanalyze") —
  explaining the workflow's purpose, what it does step by step, and improvement areas.
- Any user who can access the workflow can **read and edit**.
- Supports **edit + preview** of markdown.
- Is **deleted when the workflow is deleted**.

The panel opens on the left; opening it **closes the NodePanel** and **pushes the
canvas** using the existing left-slot flex layout. Closing it restores the NodePanel.

## Goals / Non-goals

**Goals**
- One shared markdown doc per workflow, persisted server-side.
- AI seeds the doc; humans edit and save it; both live in the same saved document.
- Concurrency-safe saves with a stale-edit warning (no silent clobbering).
- Reanalyze never silently destroys content (preview + Accept/Discard).

**Non-goals (YAGNI)**
- Real-time collaborative co-editing (CRDT/multi-cursor).
- Versioning/history of the notes doc.
- Per-user private notes — the doc is shared among all workflow accessors.

## Data Model

New 1:1 table `workflow_analysis_notes` (keeps the already-large `workflows` table
lean and cascade-deletes with the workflow):

| Column           | Type      | Notes                                                       |
|------------------|-----------|-------------------------------------------------------------|
| `id`             | uuid PK   | default uuid4                                               |
| `workflow_id`    | uuid FK   | → `workflows.id`, **unique**, `ondelete=CASCADE`, indexed   |
| `content`        | Text      | markdown body; may be empty                                 |
| `revision`       | int       | default 0; incremented on every successful save             |
| `updated_by_id`  | uuid FK   | → `users.id`, nullable (`ondelete=SET NULL`)                |
| `created_at`     | timestamptz | server default now()                                      |
| `updated_at`     | timestamptz | server default now(), onupdate now()                      |

Relationship on `Workflow`:
```python
analysis_note: Mapped["WorkflowAnalysisNote | None"] = relationship(
    "WorkflowAnalysisNote", back_populates="workflow",
    cascade="all, delete-orphan", uselist=False,
)
```
→ deleting a workflow deletes its note row.

Alembic migration creates the table + unique index on `workflow_id`.

## API

All workflow access checks reuse `get_workflow_for_user` (owner, `WorkflowShare`,
`WorkflowTeamShare`). **Any accessor can both read and write** the note.

### `GET /api/workflows/{workflow_id}/analysis-note`
Returns the note or an empty default:
```json
{
  "content": "…markdown…",
  "revision": 3,
  "updated_by": { "id": "…", "name": "Burak" },
  "updated_at": "2026-06-19T…Z"
}
```
If no row exists yet: `{ "content": "", "revision": 0, "updated_by": null, "updated_at": null }`.

### `PUT /api/workflows/{workflow_id}/analysis-note`
Body: `{ "content": "…", "base_revision": 3 }`

- If `base_revision != current revision` → **409 Conflict**, body includes the
  current server state (`content`, `revision`, `updated_by`, `updated_at`) so the
  client can show the stale warning and offer Reload/Overwrite.
- Else: upsert the row, `revision += 1`, set `updated_by_id = current_user.id`,
  return the new state (same shape as GET).
- Client can force-overwrite by re-sending `PUT` with `base_revision` equal to the
  server's current revision (obtained from the 409 response).

### `POST /ai/analyze-workflow`
Thin SSE endpoint reusing the existing assistant plumbing
(`get_credential_for_user`, `get_openai_client`, `stream_llm_response`,
`LLMTraceContext`, `_stream_sse_with_heartbeat`).

- Request mirrors the assistant request shape: `{ credential_id, model,
  current_workflow }` (+ optional `execution_log`).
- Uses a dedicated `WORKFLOW_ANALYZE_SYSTEM_PROMPT` instructing the model to output
  **markdown** with: purpose, what it does (step-by-step over nodes/edges), and
  improvement areas. No tool/builder behavior — explanation only.
- Streams markdown text via SSE. Requires an LLM credential
  (OpenAI/Google/Custom), same validation as `/ai/workflow-assistant`.
- Trace `node_label="Workflow Analyze"`, `source="assistant"`.

Pydantic schemas live alongside existing assistant/workflow schemas.

## Frontend

### `AnalysisPanel.vue` (new, `components/Panels/`, ≤300 lines)
- **Editor**: markdown `<textarea>` with an **Edit | Preview** toggle. Preview
  renders via `marked` + `DOMPurify` and `@/lib/markdown` helpers (same as
  `MarkdownTextContent.vue` / `StickyNoteNode.vue`).
- **Header**: title, "last edited by X · <relative time>", Save (enabled only when
  dirty), Analyze/Reanalyze button, close (X).
- **Analyze** (doc empty): stream AI markdown into the editor as an **unsaved
  draft**; user edits → Save.
- **Reanalyze** (doc has content): stream into a **preview region** with
  **Accept** (replace editor content) / **Discard** (keep current). Never silently
  overwrites.
- **Save**: `PUT` with `base_revision`. On 409 → stale warning with **Reload
  (discard mine)** and **Overwrite (force)**.
- Cancel any in-flight SSE stream when the panel closes.

### Editor integration (`EditorView.vue`)
- Add a **"Analyze my workflow"** canvas toolbar button (near the Ask AI / run
  controls).
- Track open state in the workflow store (`analysisPanelOpen`) so the button and
  panel coordinate.
- Opening the panel sets `leftPanelOpen = false` (**closes NodePanel**) and renders
  `AnalysisPanel` in the same left slot, **pushing the canvas** via the existing
  flex layout. Closing restores the NodePanel.
- LLM credential/model selection reuses the existing assistant mechanism.
- API client methods added to `services/api.ts`.

## Data Flow

1. Open panel → `GET …/analysis-note` → populate editor (Preview if content exists,
   Edit if empty).
2. Analyze/Reanalyze → choose credential/model → SSE stream → fill editor draft
   (Analyze) or preview+Accept/Discard (Reanalyze).
3. Save → `PUT` with `base_revision` → update revision + last-editor.
4. Delete workflow → cascade deletes the note row.

## Error Handling / Edge Cases

- **No LLM credential** → Analyze disabled with tooltip (mirrors current assistant).
- **Unsaved/new workflow** (no persisted `id`) → hint to save the workflow first;
  note API and analyze require a workflow id.
- **Stale save (409)** → warning with Reload (discard local) / Overwrite (force).
- **Empty doc** → saving an empty/cleared doc is allowed.
- **Stream cancelled** when the panel closes mid-analysis.

## Testing

Backend pytest (`backend/tests/`):
- GET returns empty default and persisted note.
- PUT creates then updates; `revision` increments; `updated_by` set.
- PUT with stale `base_revision` → 409 with current server state.
- Access control: non-accessor blocked; accessor (share/team) allowed read+write.
- Cascade delete: deleting a workflow removes its note row.
- `/ai/analyze-workflow` request validation (missing/invalid credential type).

No frontend/UI tests (repo policy — no Vitest harness).

## Documentation

Medium feature → update docs via the `heym-documentation` skill.
