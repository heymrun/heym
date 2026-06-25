# File Upload Trigger Node — Design

**Date:** 2026-06-25
**Status:** Approved (brainstorming) — ready for implementation plan
**Branch context:** `impl/file-save-node` (inverse of recent base64→Drive save work)

## Problem

Heym workflows can be invoked via HTTP `/execute`, the MCP tool interface, and the
canvas Run button. None of these channels support `multipart/form-data`, and large
binary files (e.g. a 75 MB video, a 20 MB voice recording) cannot be embedded as
base64 inside the workflow JSON payload. An LLM agent (Claude Code, ChatGPT) running
in a sandbox can execute `curl` and upload multipart, but has no way to hand a large
file to a Heym workflow today.

We need a trigger node that lets a workflow **accept a large file upload** without
adding multipart support to the existing HTTP/MCP invocation surface.

## Goals

- New trigger node `fileUploadTrigger` that is a workflow entry point.
- Invoking the workflow (HTTP / MCP / canvas) returns a **prefilled `curl`** plus a
  unique upload URL, instead of running the workflow body.
- The multipart upload to that URL **triggers a fresh run** with the file as the
  trigger payload, and the upload's HTTP response returns the workflow output
  **synchronously**.
- The upload link is **single-use** (max one successful upload) and has a
  **configurable TTL**.
- Hard file-size ceiling of **100 MB** (node-configurable, default 100 MB).
- Strong security posture: capability-URL token, audit logging of every attempt.

## Non-Goals

- Adding multipart support to the generic `/execute` / MCP / canvas invocation paths
  (they stay JSON-only by design).
- Resumable / chunked uploads, multi-file uploads, or upload progress streaming.
- Async/background run mode for the upload (synchronous run + response only).
- A standalone mint endpoint (the workflow invocation itself is the mint).

## Decisions (locked during brainstorming)

1. **Execution model:** mint-link, and the multipart upload triggers a **new run**
   with the file as the trigger payload. (Not HITL pause/resume.)
2. **Upload response:** **synchronous** — store file, run the workflow body to
   completion, return its output in the upload HTTP response.
3. **Link security:** **unguessable token + single-use + hard TTL**. The token is the
   capability — no Heym credentials needed to upload. Minting still requires normal
   workflow auth. Every attempt is audited.
4. **Mint seam:** **executor short-circuit** (Approach A) — existing invocation paths
   detect the `fileUploadTrigger` entry node and return a mint payload instead of
   running the body.
5. **Storage:** reuse `file_storage.store_file` + `GeneratedFile` (the upload becomes
   a normal Drive file), so downstream nodes reference `$label.file`.
6. **Size cap:** node-configurable, default 100 MB, hard ceiling 100 MB.

## Data Flow

```
PHASE 1 — MINT  (auth required: HTTP /execute, MCP tool, or canvas Run)
  invoke workflow whose entry node is fileUploadTrigger
    → executor short-circuits (does NOT run body)
    → create single-use upload slot (token, TTL, caps)
    → return:
        {
          "curl": "curl -F file=@<path> <upload_url>",
          "upload_url": "<base>/api/file-intake/u/<token>",
          "expires_at": "<iso8601>",
          "max_size_mb": 100,
          "allowed_types": ["audio/*", ...],   // [] = any
          "slot_id": "<uuid>"
        }

PHASE 2 — UPLOAD  (no Heym auth; the token IS the capability)
  curl -F file=@audio.m4a <upload_url>
    → guards: token valid? slot pending? not expired? size ≤ cap? mime allowed?
    → store file via file_storage → GeneratedFile (Drive)
    → atomically consume slot (single-use: guarded UPDATE)
    → run workflow body synchronously with
        $label.file = { id, name, mime, size, download_url }
        $label.uploaded_at, $label.client_ip
    → 200 { run_id, output: <workflow output> }
    → on guard failure: 4xx + audit row (slot consumed only on success)
```

## Data Model

### `file_upload_slot`
| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `workflow_id` | UUID FK | the workflow to run on upload |
| `token_hash` | str, indexed | hash of the raw token; raw token never persisted |
| `status` | enum | `pending` / `consumed` / `expired` |
| `max_size_bytes` | int | snapshot of node config at mint time |
| `allowed_mime` | JSON array, nullable | snapshot; null/empty = any |
| `expires_at` | datetime | hard TTL |
| `created_by_user_id` | UUID FK | minting user |
| `created_at` | datetime | |
| `consumed_at` | datetime, nullable | |
| `uploaded_file_id` | UUID FK→GeneratedFile, nullable | |
| `run_id` | str, nullable | run triggered by the upload |
| `mint_source` | enum | `http` / `mcp` / `canvas` |

Single-use is enforced by an **atomic guarded UPDATE**:
`UPDATE file_upload_slot SET status='consumed', ... WHERE id=:id AND status='pending'`
→ exactly one concurrent upload sees 1 row affected and wins; the rest are rejected.

### `file_upload_audit` (append-only)
| column | type | notes |
|---|---|---|
| `id` | UUID PK | |
| `slot_id` | UUID, nullable | null for unknown-token hits |
| `workflow_id` | UUID, nullable | |
| `event` | enum | see below |
| `client_ip` | str, nullable | |
| `user_agent` | str, nullable | |
| `file_name` | str, nullable | |
| `file_size` | int, nullable | |
| `mime` | str, nullable | |
| `created_at` | datetime | |

`event` ∈ { `minted`, `upload_accepted`, `rejected_expired`, `rejected_consumed`,
`rejected_oversize`, `rejected_mime`, `rejected_unknown_token`, `run_failed` }.

## Endpoints

- **Mint** — no new caller-facing endpoint. Handled inside the existing
  `/workflows/{id}/execute`, the MCP tool invocation, and canvas Run, when the
  workflow's entry node type is `fileUploadTrigger`. Returns the mint payload.
- **Upload** — `POST /api/file-intake/u/{token}`:
  - `multipart/form-data`, field `file`.
  - Unauthenticated (token is the capability).
  - Per-IP rate limit.
  - **Streams to disk with a hard byte-cap cutoff** — reject mid-stream when the
    running byte count exceeds `max_size_bytes`; never buffer the whole file in
    memory.
  - Reuses `file_storage.store_file`; produces a `GeneratedFile`.
  - On success: consume slot atomically, run workflow synchronously, return
    `{ run_id, output }`.

## Node Configuration

Per `AGENTS.md` node-integration rules, the new fields are wired into all four
surfaces (DSL source of truth, schema metadata, expression dialog field discovery,
agent-icon autofill eligibility):

| field | default | bounds | notes |
|---|---|---|---|
| `ttlMinutes` | 60 | 1 – 10080 (7 d) | upload-link TTL |
| `maxSizeMb` | 100 | 1 – 100 | hard ceiling 100 |
| `allowedTypes` | (empty) | — | optional CSV of mime/extension; empty = any |
| `label` | — | — | node label used in `$label.*` references |

Outputs available downstream:
`$label.file.{id,name,mime,size,download_url}`, `$label.uploaded_at`,
`$label.client_ip`.

MCP tool description must instruct the agent: "This returns a `curl` command. Run it
with your file attached; the `curl` response contains the workflow result."

## Security Posture

- Token: ≥32 bytes from `secrets.token_urlsafe`; only the **hash** is stored;
  constant-time lookup by hash.
- Capability URL — no Heym credentials needed to upload; minting requires normal
  workflow auth, so only authorized callers can create slots.
- Hard TTL + single-use + size cap + optional mime allowlist.
- Per-IP rate limit on the upload route.
- Every mint and every upload attempt (accepted **or** rejected, including
  unknown-token probes) writes an audit row.
- Mint/audit failures are logged but never break the primary flow; the upload run
  follows the executor's normal error handling.

## Testing (backend pytest required)

- Slot lifecycle: mint → upload → consume; replay rejected (`rejected_consumed`);
  expired rejected (`rejected_expired`); oversize rejected mid-stream
  (`rejected_oversize`); mime-allowlist rejected (`rejected_mime`); unknown token
  audited (`rejected_unknown_token`).
- Concurrency: two simultaneous uploads to one slot → exactly one wins (atomic
  guard), the other gets `rejected_consumed`.
- Executor short-circuit: entry `fileUploadTrigger` returns mint payload and does
  **not** run the body; upload path runs the body with `$label.file` resolvable.
- Audit: a row is written for each event; token is never stored in plaintext
  (assert `token_hash` ≠ raw token, raw token absent from DB).
- Expression-evaluator / dialog parity for the new `$label.file.*` fields
  (`test_expression_evaluator_service.py`).
- E2E (Playwright) where practical: node appears on canvas, config fields editable.

## Open Items / Follow-ups

- Cleanup of expired `pending` slots and orphaned files — a periodic sweep
  (reuse cron scheduler) marks `expired` and optionally deletes the staged file.
  Out of scope for v1 unless trivially cheap; note for the plan.
- Documentation update via `heym-documentation` skill (medium/large feature → new
  node type and API surface).
