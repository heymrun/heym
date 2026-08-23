# htmlOutputMapper node, HTTP method selection, and the WEB chip

Date: 2026-08-23
Baseline: `c7af349a` (PR #486, which added the `api` / `subWorkflow` / `portal` chips)

## Problem

Heym workflows can return JSON over their execute webhook (`jsonOutputMapper` as the sole
terminal) but cannot return a web page. A workflow that composes HTML — a status page, a
generated report, a form — has to be wrapped by something else to be viewable in a browser.

Three gaps follow from that:

1. There is no node that produces an HTML response body.
2. `/execute` is POST-only, so a browser cannot reach a workflow with a plain navigation.
3. Nothing in the dashboard tells you a workflow serves a page rather than an API payload.

A fourth, unrelated defect surfaced while scoping: any node wired to an agent's `tool-input`
handle becomes a callable tool, including terminal mappers that have no business being one.

## Scope

- New node type `htmlOutputMapper`.
- Per-workflow HTTP method (`GET` / `POST` / `PUT` / `DELETE`), enforced, default `POST`.
- `WEB` status chip in the workflow listing.
- Block terminal mappers from being used as agent tools, retroactively.
- Release tour entry, docs, DSL, backend tests, heymweb rollout and a template.

Out of scope: templating engines with loops/conditionals, HTML sanitization of user
expressions, serving static assets, and SSE-over-HTML.

## 1. The node

### Definition

```
htmlOutputMapper
  label     "HTML output mapper"
  icon      FileCode2     (distinct from the Code node's Code2)
  color     node-output
  inputs 1, outputs 0
  data      { label, html, statusCode, contentType }
```

Authoring is a single expression-capable `html` textarea. The whole page lives in one field
and `$node.field` spans are interpolated into it. Two scalar fields sit above it:
`statusCode` (default `200`) and `contentType` (default `text/html; charset=utf-8`).

The alternative — key/value mappings feeding a template — was rejected: it puts the answer to
"why is my page wrong?" in two places, and `jsonOutputMapper` already owns the mappings idiom.

### Execution

New handler `backend/app/services/node_execution/nodes/html_output_mapper_node.py`, registered
in `node_execution/registry.py`. It resolves the body with the executor's
`evaluate_message_template`, which is the per-span helper — the right one for a large body of
prose containing many independent `$…` references, as opposed to `jsonOutputMapper`'s
per-value single-expression path.

Node output is structured, not a bare string:

```python
{"html": "<!doctype html>...", "statusCode": 200, "contentType": "text/html; charset=utf-8"}
```

Structured output keeps the node introspectable on the canvas, in the debug panel, and in
execution history, and it lets the API layer read the status code without re-reading the graph.

### Turning that into an HTTP response

New module `backend/app/services/html_response.py` with two pure functions:

- `find_sole_html_terminal(nodes, edges) -> str | None` — the node id when the only active,
  non-sticky terminal is an `htmlOutputMapper`; `None` otherwise. Mirrors the shape of
  `unwrap_single_json_output_terminal_outputs`, which is the existing precedent for
  "sole terminal changes the response".
- `build_html_response(node_results, node_id) -> HTMLResponse | None`.

`/execute` calls these immediately before its `simple_response` returns. Rules:

- Sole terminal is `htmlOutputMapper` **and** `X-Simple-Response` is on (the default) →
  `HTMLResponse(body, status_code, media_type)`.
- `X-Simple-Response: false` → unchanged JSON envelope. That header is the editor and debug
  path; the canvas needs `node_results` and would break on a page body.
- Not the sole terminal → unchanged JSON. The node still runs and still reports its output.
- SSE `/execute/stream` → unchanged. HTML has no meaning as an event stream; the html string
  rides along in the `final_output` event like any other node output.

The executor also learns about the node where it already special-cases `output` and
`jsonOutputMapper`: `highlight_builder.OUTPUT_NODE_TYPES`, the final-output event emission,
and the terminal-node collection sites.

## 2. HTTP method

### Storage

New column `workflows.http_method`, `String(8)`, `NOT NULL`, server default `'POST'`, with an
Alembic migration. Default POST is what keeps every workflow that exists today working
untouched, and it is what a newly created workflow gets.

It has to be persisted rather than kept in the dialog, because the listing's preview panel
renders its own cURL from the stored workflow and has no access to editor state.

### Enforcement

`/execute` and `/execute/stream` become `@router.api_route(..., methods=["GET","POST","PUT","DELETE"])`.
After the workflow loads, a method other than the configured one returns `405` with an
`Allow` header naming the configured method.

Two deliberate exemptions:

- `test_run=true` requests skip enforcement, so the editor's Run button and the debug panel
  keep working no matter what the dropdown says. Without this, choosing GET would make the
  workflow untestable from inside the product.
- A workflow with no stored value (rows predating the migration read as `POST`) behaves
  exactly as it does today.

GET and DELETE carry no body. `parse_execute_body` already tolerates an empty body, and query
parameters already land in `enriched_inputs["query"]`, so a GET workflow reads its inputs from
`$input.query.*` with no new plumbing.

### The two cURL snippets

A method `<select>` goes above the Simple Response row in the editor's cURL dialog, saved on
change the way `sse_enabled` is. Both generators — `EditorView.curlCommand` and
`workflowPreview.buildWorkflowCurl` — read it and:

- emit `curl -X <METHOD>`,
- drop `-H "Content-Type: application/json"` and the `-d '...'` body for GET and DELETE,
- hide the request-body textarea in the dialog for GET and DELETE.

## 3. The WEB chip

`compute_trigger_status` gains an `edges` parameter and one rule: when the status it would
otherwise return is `manual`, and the sole active terminal is an `htmlOutputMapper`, return
`web` instead.

Since PR #486, `manual` is further narrowed by `refine_manual_status` into `api`,
`subWorkflow`, or `portal` based on the last run's trigger source. `web` is decided from the
graph, so it is applied **before** that refinement and short-circuits it: a page-serving
workflow reads `WEB` rather than `API`, which is what it would otherwise show after its first
HTTP call. Concretely, `compute_trigger_status` returns `web` and `refine_manual_status`
leaves any status that is not `manual` alone, which it already does.

Trigger-derived statuses still win. A cron- or Slack-triggered workflow keeps `Scheduled` /
`Listening`, because how a workflow *starts* is more useful on a list row than what it
returns, and a scheduled workflow's HTML body is a side effect rather than its point.

Frontend: `WorkflowTriggerStatus` gains `"web"`, `WorkflowStatusBadge` gains a `web` style
(label `WEB`), and `WorkflowStatusFilter` gains the matching option.

## 4. Terminal mappers are not agent tools

Frontend `BLOCKED_AS_TOOL_NODE_TYPES` gains `jsonOutputMapper` and `htmlOutputMapper`, which
stops new connections at the canvas.

That is not sufficient on its own. `WorkflowExecutor._build_node_tool_schemas` turns *every*
node on an agent's `tool-input` handle into a callable tool with no block list, so a workflow
saved before this change keeps offering its mapper to the agent. A matching
`BLOCKED_AS_TOOL_NODE_TYPES` frozenset in the backend, consulted in that builder, is what
makes the fix retroactive — this is the "geriye yönelik" half of the requirement.

A terminal mapper called mid-conversation by an agent produces a response body that nothing
reads, and burns a tool call doing it.

## 5. Release tour

A `html-output-mapper` section joins the current unreleased `2026.08` entry, listed in
`sectionOrder`, with an animated mock visual registered in `tourVisuals.ts` under the same
key. The seeded id in `frontend/e2e/support.ts` is realigned so the auto-open panel keeps out
of the way of E2E clicks.

## 6. Docs, DSL, tests, heymweb

heymrun:

- `docs/content/nodes/html-output-mapper-node.md`, registered in `docs/manifest.ts`.
- `reference/features.md` (per-node section and the node-types summary list),
  `reference/node-types.md`.
- `reference/webhooks.md` — method selection and the HTML response contract.
- `tabs/workflows-tab.md` — the WEB chip.
- `workflow_dsl_prompt.py` — a section `8c` beside `8b`, plus the same
  "never inside a loop iteration branch" hard rule the other terminals carry.

Backend tests:

- `test_html_output_mapper_node.py` — template resolution, defaults, status code, expressions.
- `test_html_response_api.py` — sole terminal returns `text/html`; `X-Simple-Response: false`
  returns the JSON envelope; a non-sole terminal returns JSON.
- `test_workflow_http_method.py` — 405 on mismatch with `Allow`, 200 on match, legacy rows
  default to POST, `test_run` bypasses.
- `test_workflow_trigger_status.py` — `web` beats `manual` and pre-empts the `api`
  refinement, loses to `cron`.
- Agent tool blocking — a `jsonOutputMapper` on a `tool-input` edge yields no schema.

heymweb (the six files from the node rollout checklist, plus the seven hardcoded node counts):
`marketingNodeCatalog.ts`, `node-doc-links.ts`, `NodesSection.tsx`, `nodePreviewTokens.ts`,
`TemplateCanvasNode.tsx`, `DocumentationSection.tsx`; count bumps 60 → 61 in
`tests/seo/invariants.test.ts` (twice), `README.md`, the `what-is-ai-workflow-automation.mdx`
post, and the three `public/readme-assets/` SVGs. Then `bun run sync-docs` and
`bun run sync-dsl-prompt`, and a new template that ends in an `htmlOutputMapper`.

## Verification

- `./check.sh` from the repo root (ruff format, lint, backend tests).
- `bun run lint`, `bun run typecheck`, `bun run test` in `frontend/`.
- heymweb: `bunx tsc --noEmit`, `bun test tests/seo/invariants.test.ts`, `bun run build`.
