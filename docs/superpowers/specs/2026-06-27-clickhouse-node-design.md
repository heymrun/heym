# ClickHouse Node — Design

**Date:** 2026-06-27
**Status:** Approved (pending spec review)

## 1. Goal

Add a new `clickhouse` workflow node to heymrun that brings the DataTable node's
operation surface to an external ClickHouse database, plus a raw SQL escape hatch.
Sync docs and DSL to heymweb, introduce the node on heymweb's marketing surfaces,
and ship a related template.

## 2. Decisions

- **Node type:** `clickhouse`.
- **Operations:** `query` (raw SQL), `find`, `getAll`, `count`, `getById`,
  `insert`, `update`, `remove`, `upsert`.
- **Client library:** `clickhouse-connect` (official ClickHouse Inc., HTTP `:8123`,
  sync client). Runs in the executor's threadpool, mirroring the Supabase
  sync-httpx integration pattern.
- **update / remove semantics:** `update` → `ALTER TABLE … UPDATE … WHERE …`
  (mutation); `remove` → `DELETE FROM … WHERE …` (lightweight delete). Both are
  documented as asynchronous/costly ClickHouse mutations, not OLTP row ops.
- **upsert:** `INSERT` under a `ReplacingMergeTree` assumption; documented as such.
- **Input modes (insert/upsert):** `raw` (JSON array / row list) and `selective`
  (key→value mappings, mirroring BigQuery `bqMappings`).
- **getById:** assumes the target table has an `id` column (same assumption as
  DataTable). Documented in the node doc.

## 3. Backend

### New files
- `backend/app/services/clickhouse_service.py` — `ClickHouseService` (sync):
  `get_client(config)`, `query()`, `find()`, `count()`, `get_by_id()`,
  `insert()`, `update()`, `remove()`, `upsert()`. Table/column-name validation
  via regex (cf. Supabase `_TABLE_NAME_PATTERN`); parameterized queries to guard
  against SQL injection on filter/value paths. Raw `query` is the user's
  responsibility (read/write).
- `backend/tests/test_clickhouse_service.py` — unit tests with the ClickHouse
  client mocked. Cover every operation, both input modes, name validation, and
  error paths.

### Changes
- `pyproject.toml` — add `clickhouse-connect` dependency.
- `app/models/schemas.py` — `ClickHouseCredentialConfig`
  (host, port, username, password, database, secure/https flag) and any new
  `clickhouse*` node config fields not already on NodeData.
- `app/api/credentials.py` — register `clickhouse` credential type + validation.
- `app/services/workflow_executor.py` — add `elif node_type == "clickhouse":`
  block (credential decrypt + expression resolution + service dispatch),
  modeled on the existing Supabase block.
- `app/services/workflow_dsl_prompt.py` — node + operation + field DSL
  definitions, AI-autofill hints, expression-eligible field metadata.

## 4. Frontend

- `types/workflow.ts` — `"clickhouse"` node type, `clickhouse*` config fields,
  `ClickHouseOperation` union.
- `types/credential.ts` — `clickhouse` credential type, label, description, config
  interface.
- `types/node.ts`, `lib/nodeIcons.ts` — node registration + icon.
- `components/Panels/NodePanel.vue` & `PropertiesPanel.vue` — palette entry +
  operation/field editors (raw/selective toggle, expression-eligible fields wired
  to the expression dialog metadata).
- `components/Nodes/BaseNode.vue`, `components/Canvas/WorkflowCanvas.vue`,
  `components/Panels/DebugPanel.vue` — render/preview seams.
- `components/Credentials/CredentialDialog.vue` & `CredentialsPanel.vue` —
  credential form.
- `frontend/src/docs/content/nodes/clickhouse-node.md` plus ClickHouse rows in
  reference docs (`node-types.md`, `integrations.md`, `credentials.md`,
  `credentials-sharing.md`).

## 5. heymweb Sync + Introduction

- `bun run sync-docs` → push `clickhouse-node.md` and updated reference docs to
  heymweb `src/content/docs`.
- `bun run sync-dsl-prompt` → sync DSL prompt into `src/lib/heymDslPrompt.ts`.
- `src/components/sections/NodesSection.tsx` — new `clickhouse` MarketingNode
  entry (node count/listing derive automatically from `nodes.length`).
- `src/lib/node-doc-links.ts` — `clickhouse` → doc link.
- `src/components/templates/nodePreviewTokens.ts` & `TemplateCanvasNode.tsx` —
  template-canvas preview token for the node.

## 6. heymweb Template

- `src/lib/templates.ts` — a new ClickHouse-centric `StaticTemplate`, e.g.
  "Event Analytics → ClickHouse": a trigger → data-shaping → ClickHouse `insert`,
  with a reporting branch using `query`/`count`. Appropriate category + node
  preview tokens.

## 7. Test & Verification

- heymrun: `./check.sh` from repo root (ruff format + lint + pytest, incl.
  `clickhouse_service` tests) before any push.
- heymweb: `bunx tsc --noEmit` + `bun run build`.
- No frontend UI tests (no Vitest harness in heymrun) — verify frontend via
  lint + typecheck + manual; backend pytest is still required.

## 8. Open Notes / Assumptions

- `getById` assumes an `id` column; stated in the node doc.
- `find`/`count` filters are parameterized; raw `query` is user-controlled.
- No automatic git push — ask before pushing (heymrun and heymweb).
