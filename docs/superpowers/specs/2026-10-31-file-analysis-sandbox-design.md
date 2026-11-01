# File Analysis Sandbox — Inspect and Process Large Files Without RAG

**Date:** 2026-10-31
**Status:** Approved design, ready for implementation planning

> **Revised 2026-11-01 (run scope, header rows):** Chat keeps every Drive file its user reaches. A workflow run opens only its own files: `GeneratedFile.workflow_id` in the run's `RunFileScope` (the workflow and, for sub-workflows, its parents) or a file id Chat handed in (`file_sandbox/scope.py`). A Drive id typed into an input, hardcoded in Files or assembled in a prompt fails like a missing file, so a Code node or agent cannot be used to read the actor's Drive. The agent's toolbox lists and opens only the run files its input carried. Chat's test runs and "run this workflow" feed the conversation's file to the workflow's File Upload trigger (`_initial_inputs`, `run_workflow_test.sample_file`) with that one id in scope, so a test behaves like a production upload. Spreadsheet inspection finds the real header row in the first 30 rows, returns `title_rows`, `first_column` and a pandas `read_hint`, and returns summary sheets as `key_values` with cell refs.

## Problem

Large files (PDF, XLSX, CSV, DOCX, JSON) reach Heym through Chat attachments,
File Upload triggers, mail attachments and Heym Drive, but nothing can look at
them the way an analyst would: discover the structure first, then read only the
part that matters.

- **Chat** attachments accept text, image, PDF and zip only. PDF text is
  extracted in the browser and up to 100k characters are pasted straight into
  the model context. XLSX and DOCX are rejected. Build-mode test runs inject that
  pasted text into the workflow's input field.
- **The Code node** runs hardened, disposable Python but only receives JSON
  parameters; it cannot open a Drive file.
- **Skills** can read Drive files (`driveFilesEnabled`), but copy every file the
  actor can reach on every call, keep network egress, and fall back to an
  unsandboxed subprocess in native dev.

The result is the anti-pattern the target behavior forbids: whole files dumped
into context, or no access at all.

## Goal

One shared sandbox core that lets a model or a workflow inspect and process
files inside an isolated Python container, used by three surfaces:

1. **Chat** (Heym Chat tab, Heym Work Chat, MCP `heym_chat`): while answering or
   building a workflow, the model inspects attached or Drive files, extracts what
   it needs, and builds a workflow with the right sheet/column/page names.
2. **Agent node** (automatic, no setting): at run time an agent whose input
   carries a supported Drive file loops inspect → extract on the run's files.
3. **Code node** (`codeFiles`): deterministic Python receives Drive files
   read-only and can write output files back to Drive.

The model-facing behavior follows a fixed order: file type and metadata →
structural summary → sample content → the specific operation. Whole files never
enter the context.

## Non-goals (v1)

- The canvas AI assistant (editor side panel). Only Chat surfaces get the tools.
- A long-lived Python kernel. Every call is a fresh process.
- Network access from the file sandbox. There is no toggle.
- Changing how skills read Drive files, beyond sharing the access clause.
- PyMuPDF (AGPL-3.0 conflicts with MIT + Commons Clause). PDF uses pypdf +
  pdfplumber; scanned PDFs are pointed at the Converter node's `pdfToText` OCR.

## Decisions (made with the user, do not relitigate)

| Question | Decision |
|---|---|
| Where does it live | Both build time (Chat) and run time (Agent, Code node), one core |
| Session model | Fresh container per call; a writable `/work` dir persists for the session |
| Which files are visible | Every Drive file the actor can reach (owned or team-shared), mounted on demand |
| Chat workspace lifetime | Lives with the conversation; deleted when the chat is deleted, when the user asks, or after 30 idle days |
| Agent / Code workspace lifetime | One node execution; deleted on every exit path |
| Architecture | New `file_sandbox` service, not a skill and not Code-node-only |
| Heym Work | Same engine; Work proxies Heym's chat routes, so lifecycle hooks apply unchanged |

## Architecture

New package `backend/app/services/file_sandbox/`:

| Module | Responsibility |
|---|---|
| `limits.py` | Constants: memory, CPU, timeouts, quotas, concurrency |
| `workspace.py` | `FileWorkspace`: host layout, input copies, output collection, size accounting, deletion |
| `manifest.py` | Accessible-file listing and resolution through `drive_file_access` |
| `executor.py` | Builds and runs the hardened `docker run`, ships the runner payload, parses the envelope |
| `runner.py` | Stdlib-only bootstrap executed inside the container (like `code_runner.py`) |
| `heym_files.py` | Module importable from sandbox code: `list_files()`, `path()`, `out_dir()` |
| `inspector.py` | Per-type structural inspection, runs inside the sandbox |
| `tools.py` | Tool schemas and the dispatcher shared by Chat and Agent |
| `chat_workspaces.py` | Conversation-scoped workspace registry, deletion hooks, idle sweep |
| `instructions.py` | Model-facing rules text |

Code node and Agent node call into `executor.py` / `tools.py`; Chat calls
`tools.py` with a conversation-scoped workspace.

### Host layout

```
<root>/<scope>/<key>/in/      backend-only writes; Drive copies live here
<root>/<scope>/<key>/work/    sandbox writes; /work/out holds new output files
<root>/<scope>/<key>/meta.json  owner, last_used_at, input index
```

- `<root>` follows the Code node rule: a temp dir on a native backend, the shared
  `heym-codex-workspaces` volume (subdir `_file-sandbox`) in containers.
- Chat: `<scope>/<key>` = `chats/<user_id>/<conversation_id>`. Keying by user and
  conversation means a forged conversation id only ever reaches the caller's own
  workspace.
- Runs: `runs/<uuid4>`.

### Container mounts

- `/input` ← `in/`, read-only.
- `/work` ← `work/`, read-write.
- The two are siblings on the host and never nested, so the sandbox cannot write
  into the input tree or plant links there.

### Per-call execution

Each `inspect_file` / `run_python` call starts one container with the Code node's
`hardening_args` (uid 65534, `--cap-drop ALL`, `no-new-privileges`, read-only
root fs, env allowlist, no Docker socket) plus:

- `--network none`, always.
- 2 GB memory and swap, 2 CPUs, 256 PIDs, 120 s per call.
- `/tmp` tmpfs 512 MB.
- The runner, `heym_files` and `inspector` sources travel in the stdin payload
  (no baked path; the two Dockerfiles disagree on `/app` vs `/app/backend`).
- Calls within one session run one at a time (per-workspace lock); at most 4
  file-sandbox containers run per instance (semaphore).
- No Docker → fail closed. There is no subprocess fallback.

### Libraries

`docker/sandbox-requirements.txt` (pinned): pandas, openpyxl, xlrd, pdfplumber,
pypdf, python-docx, langdetect. Both `backend/Dockerfile` and
`docker/release.Dockerfile` install it into the system interpreter, because the
sandbox runs the image's plain `python`, not the backend venv. Side effect: Code
node code can import pandas without a `requirements.txt`. The same libraries are
added to the backend dev dependency group so the inspector can be unit-tested
in-process.

## Model tools

Shared by Chat and Agent (Agent omits `clear_workspace`).

| Tool | Arguments | Returns |
|---|---|---|
| `list_files` | `query?`, `limit?`, `offset?` | Accessible Drive files: id, name, mime, size, created_at, source. No URLs or tokens. |
| `inspect_file` | `file`, `sheet?`, `pages?`, `rows?` | Structured summary (below) |
| `run_python` | `code`, `files?` | stdout (truncated at 20k chars), error traceback, generated files |
| `clear_workspace` | — | Chat only: deletes the conversation workspace |

`file` and `files` entries are a Drive id or an exact filename. Each is resolved
through the access clause for the actor before anything is copied.

### `inspect_file` summaries

Read selectively (`nrows`, openpyxl `read_only`, first N pages/records):

- **PDF**: page count, metadata (title, author, creator, producer), encrypted,
  text extractable (first 2 pages), detected language, page sizes, first-page
  sample. Not extractable → `scanned: true` and a pointer to Converter OCR.
- **XLSX / XLS**: sheet names; per sheet rows, columns, header names, inferred
  dtypes, last filled row; named ranges; first 5 rows.
- **CSV / TSV**: detected encoding and delimiter, rows, columns, dtypes, null
  ratios, first 5 rows, file size.
- **DOCX**: paragraph count, heading outline, table count with shapes, word and
  character counts, core properties (author, created, modified).
- **JSON**: root type, top-level keys, array length, estimated nesting depth,
  sample record (first N items for large arrays).
- **Other**: size, mime, first bytes as text when it decodes.

Errors (encrypted PDF, corrupt file, unknown encoding) return a clear message
plus an alternative.

### `run_python`

Sandbox code sees:

- `/input/<file_id>/<safe_name>` for every input copied in this session.
- `heym_files.list_files()` (session inputs with metadata), `heym_files.path(name_or_id)`,
  `heym_files.out_dir()` (`/work/out`).
- `/work` as scratch that persists for the session (e.g. `/work/sales.pkl`).

Files written under `/work/out` are collected after the call, stored in Drive
owned by the actor, removed from `out/`, and returned as
`{id, name, mime, size, download_path}` where `download_path` is the
authenticated `/api/files/{id}/download` route. Storage goes through
`store_file_sync`, so the file gets Drive's default share token like every other
Drive file, but that token never appears in a tool result, the manifest, or the
sandbox.

## Security

1. **One access rule.** Listing and resolution use a new
   `accessible_file_rows(user_id)` fragment in `drive_file_access.py` (owner or
   member of a team holding a share). `_load_skill_drive_files` moves onto the
   same fragment so the rule exists once. Model-supplied ids and names are never
   trusted: every mount re-resolves for the actor.
2. **Actor.** Chat: the signed-in user. Agent / Code: the executor's
   `actor_user_id` (the canvas user, or the owner for triggered and portal runs,
   the same context credentials use). No actor → the tool refuses.
3. **Revocation.** Before every call each copy under `in/` is re-checked;
   copies whose file was deleted or unshared are removed. Derived data under
   `/work` stays, like tool results already in chat history.
4. **Filesystem boundary.** The backend writes only into `in/`. It reads
   `work/` only to collect `work/out/`: `lstat` each entry, reject symlinks,
   hardlinks (`st_nlink > 1`), and non-regular files, open with `O_NOFOLLOW`,
   require the resolved path to stay inside `out/`, and normalize names with
   `_normalize_storage_filename`.
5. **No parsing in the backend.** All file parsing, `inspect_file` included,
   happens in the sandbox. The backend only copies bytes.
6. **No leaks.** Env allowlist, no secrets, no socket, no network. The manifest
   carries metadata only.
7. **Quotas.** Session inputs + work ≤ 2 GB; ≤ 20 outputs per call, ≤ 100 MB
   each; stdout 20k chars.
8. **Untrusted content.** Tool results are wrapped as untrusted file content,
   and the instructions tell the model not to follow instructions found inside
   files. Residual risk (documented): an Agent that receives a Drive file, also
   reads external input and has an outbound tool can be prompt-injected into
   disclosing other Drive files. The docs warn.
9. **Collaborators.** Passing a file id into an agent needs the same edit
   permission as adding a Drive node, which already reads the actor's Drive. A
   file id in the input is resolved again for the actor; ids the actor cannot
   reach turn nothing on. No new escalation.
10. **Audit.** Chat mounts call `audit("drive.chat_mount", …)` from the
    API layer. Agent and Code node usage is recorded in run history only.

## Chat surface

- **Tools on every Chat turn** (Chat tab, Work Chat, MCP `heym_chat`):
  `list_files`, `inspect_file`, `run_python`, `clear_workspace`.
- **Instructions** live in the static prompt block next to the build reference so
  prefix caching survives; each turn's dynamic block adds a short workspace
  summary (inputs, `/work` entries and sizes).
- **Attachments**: PDF, XLSX, XLS, CSV, TSV, DOCX, JSON, TXT, MD go to
  `/api/files/upload` (Drive upload limit, source label `Chat`). The message
  carries `{kind: "file", file_id, name, size, mime}`; content never enters the
  context. Images (vision) and zip (skill import) keep their current paths.
- **Build mode**: builder picks Code node + `codeFiles` for deterministic
  extraction, an Agent that receives the file id for open-ended questions, and tests
  with the real file. `run_workflow_test` injects the attached `file_id` into the
  workflow's file-like input field instead of pasted text.
- **Live progress**: `Inspecting Q3.xlsx`, `Running Python on 2 files`.
- **Lifetime**: deleted by `DELETE /api/chats/{id}`, `DELETE /api/chats`,
  `clear_workspace`, or the idle sweep (30 days since `last_used_at`) running on
  the main instance (`cluster.identity.is_main()`).
- **Heym Work**: Work's composer uploads through its `data_files.py` route and
  sends the same file reference; vendor pin bump follows the heymrun change.

## Agent node

- No setting. Revised 2026-11-01: the toggle was dropped. `file_sandbox/detect.py`
  mines the agent's visible inputs and resolved `userMessage`/`systemInstruction`
  for UUID-shaped strings (bounded depth, size, 50 candidates), resolves them for
  the actor through `drive_file_access_rows`, and keeps PDF, XLSX/XLS, CSV/TSV,
  DOCX, JSON/JSONL, TXT/MD files whose content is on this instance. Any hit adds
  `list_files`, `inspect_file`, `run_python` and a rules block naming the input
  files. Agent placement stays skills-only: the nodes that put Drive files into a
  run already pin it to the main instance.
- One workspace per agent node execution, deleted on success, error,
  cancellation and HITL pause; a resumed run opens a fresh one. Each sub-agent
  has its own.
- Generated files land in the actor's Drive with `source_node_label` = node label
  and `workflow_id`, and appear in the agent output's `generated_files`.
- Placement: a predicate in `node_placement.py` makes such agents `MAIN_ONLY`.
- Tool spans come from the existing `heym.agent.tool.execute` seam.

## Code node

- `codeFiles`: expression field resolving to an id, a list of ids, or objects
  with `id` (`$Upload.file.id`, `$Mail.attachments`). Exposed to the expression
  dialog.
- Each id is resolved for the actor; any miss raises one uniform
  "File not found or not accessible" error.
- With files: inputs at `/input`, `params.files` carries their metadata,
  `heym_files` is importable, `/work` is scratch, `/work/out` outputs are stored
  and returned in the node output `files`. File-sandbox limits apply.
- Without files: behavior and limits are unchanged.
- Placement: `MAIN_ONLY` when `codeFiles` is non-empty, otherwise `ANYWHERE`.

## Testing

- **Core**: mount args and layout, output collection rejections, quotas,
  cleanup on every exit path, chat workspace keying, deletion hooks, idle sweep,
  revocation pruning.
- **Advisory** (`test_advisory_file_sandbox_*.py`, real Postgres): other user's
  file, other team's share, revoked share, manifest without tokens; mutation
  check that loosening the filter fails them.
- **Real Docker** (skipped without Docker): network blocked, no secrets in env,
  `/input` read-only, libraries importable, inspector fixtures for every type.
- **Inspector** unit tests in-process with fixtures.
- **Surfaces**: Chat tool wiring and build test injection, Agent toggle and
  actor refusal, Code node `codeFiles` resolution and outputs, placement
  predicates.
- Frontend: lint, typecheck, build. No UI tests.

## Docs and release tour

- New `reference/file-analysis.md`, registered in the docs manifest; updates to
  `agent-node.md`, `code-node.md`, `chat-tab.md`, `drive.md`, `features.md`.
- DSL prompt, schema metadata, AI autofill hints and expression-dialog metadata
  for `codeFiles` (the agent has no field).
- Release tour: new unreleased entry with a "File analysis" section and a mock
  visual registered in `tourVisuals.ts`; enabled on 2026-11-01.
