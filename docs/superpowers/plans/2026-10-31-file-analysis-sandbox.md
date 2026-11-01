# File Analysis Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `file_sandbox` core that lets Chat, the Agent node and the Code node inspect and process Drive files inside a hardened, network-less Docker container, without ever putting whole files into model context.

**Architecture:** A workspace (`in/` backend-only, `work/` sandbox-writable) is mounted into a fresh container per call (`/input` ro, `/work` rw). A stdlib runner shipped over stdin executes either the built-in inspector or user code; outputs under `/work/out` are collected with no-follow checks and stored in Drive. Chat workspaces are keyed by `(user_id, conversation_id)` and live with the conversation; Agent and Code node workspaces live for one node execution.

**Tech Stack:** FastAPI, SQLAlchemy (sync session in the executor, async in routers), Docker CLI, pandas/openpyxl/xlrd/pdfplumber/pypdf/python-docx/langdetect inside the sandbox image, Vue 3 + TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-31-file-analysis-sandbox-design.md`

**Repo rules that apply:** keep a local diff (no commits, no PR) per the user's standing rule; `./check.sh` before handing back; no frontend UI tests; release tour entry in the unreleased `2026.24` release; `audit()` only from `backend/app/api/`.

---

> **Revised 2026-11-01 (run scope, header rows):** Chat keeps every Drive file its user reaches. A workflow run opens only its own files: `GeneratedFile.workflow_id` in the run's `RunFileScope` (the workflow and, for sub-workflows, its parents) or a file id Chat handed in (`file_sandbox/scope.py`). A Drive id typed into an input, hardcoded in Files or assembled in a prompt fails like a missing file, so a Code node or agent cannot be used to read the actor's Drive. The agent's toolbox lists and opens only the run files its input carried. Chat's test runs and "run this workflow" feed the conversation's file to the workflow's File Upload trigger (`_initial_inputs`, `run_workflow_test.sample_file`) with that one id in scope, so a test behaves like a production upload. Spreadsheet inspection finds the real header row in the first 30 rows, returns `title_rows`, `first_column` and a pandas `read_hint`, and returns summary sheets as `key_values` with cell refs.

> **Revised 2026-11-01:** the Agent node has no `fileAnalysisEnabled` toggle. `file_sandbox/detect.py` turns the tools on when the agent's input carries a supported Drive file the actor reaches; agent placement stays skills-only; the release tour is enabled. Steps below that mention the toggle are superseded.

## File map

Create:

| File | Responsibility |
|---|---|
| `docker/sandbox-requirements.txt` | Pinned sandbox libraries, installed into the image's system Python |
| `backend/app/services/file_sandbox/__init__.py` | Public surface re-exports |
| `backend/app/services/file_sandbox/limits.py` | Constants only |
| `backend/app/services/file_sandbox/manifest.py` | `DriveFileRef`, `list_accessible_files`, `resolve_files` (sync, actor-scoped) |
| `backend/app/services/file_sandbox/workspace.py` | `FileWorkspace`: layout, copy-in, pruning, output collection, quota, delete |
| `backend/app/services/file_sandbox/executor.py` | Container command, semaphore, run, envelope parsing |
| `backend/app/services/file_sandbox/runner.py` | Stdlib bootstrap run inside the container |
| `backend/app/services/file_sandbox/heym_files.py` | Module importable by sandbox code |
| `backend/app/services/file_sandbox/inspector.py` | Per-type inspection, imported only inside the sandbox (and tests) |
| `backend/app/services/file_sandbox/tools.py` | Tool schemas, `FileToolbox` dispatcher, result shaping |
| `backend/app/services/file_sandbox/instructions.py` | Model rules text |
| `backend/app/services/file_sandbox/chat_workspaces.py` | Conversation workspace paths, deletion, idle sweep |
| `backend/app/api/chat_files.py` | `ChatFileTools` tool group for chat turns (+ audit) |
| `backend/tests/test_file_sandbox_workspace.py` | Layout, collection rejections, quota, pruning |
| `backend/tests/test_file_sandbox_inspector.py` | Inspector fixtures in-process |
| `backend/tests/test_file_sandbox_tools.py` | Toolbox dispatch, schemas, chat tool group, agent wiring |
| `backend/tests/test_file_sandbox_docker.py` | Real-container checks (skip without Docker / libs) |
| `backend/tests/test_advisory_file_sandbox_access.py` | Real-Postgres access scope + mutation check |
| `backend/tests/test_file_sandbox_chat_lifecycle.py` | Keying, delete hooks, sweep |
| `frontend/src/docs/content/reference/file-analysis.md` | Reference page |
| `frontend/src/features/release-tour/components/visuals/FileAnalysisTourVisual.vue` | Tour mock |

Modify:

| File | Change |
|---|---|
| `backend/Dockerfile`, `docker/release.Dockerfile` | Install `docker/sandbox-requirements.txt` into system Python |
| `backend/pyproject.toml`, `backend/uv.lock` | Same libraries in the dev group |
| `backend/app/services/llm_service.py` | `_load_skill_drive_files` uses the shared access fragment; `_unified_tool_executor` dispatches `_source == "file_sandbox"` |
| `backend/app/services/workflow_executor.py` | `_execute_agent_node` opens a run workspace when `fileAnalysisEnabled` and adds the tools |
| `backend/app/services/node_execution/nodes/code_node.py`, `backend/app/services/code_python_executor.py` | `codeFiles` support |
| `backend/app/services/cluster/node_placement.py` | Predicates for agent and code |
| `backend/app/api/ai_assistant.py` | `FileAttachment` kind `file`; user message for file refs; tool-group dispatch in `stream_dashboard_chat`; injection of `file_id` |
| `backend/app/api/chats.py` | Build `ChatFileTools` per persisted turn; validate attachment file ids; delete hooks |
| `backend/app/api/chat_build.py` | Test-run injection of the attached `file_id` |
| `backend/app/services/workflow_dsl_prompt.py` | `fileAnalysisEnabled`, `codeFiles`, builder rule |
| `backend/app/main.py` (or the existing periodic task host) | Start the idle sweep on the main instance |
| `frontend/src/composables/useFileAttachment.ts`, `frontend/src/services/api.ts`, `frontend/src/components/Chat/DashboardChatComposer.vue` | Upload document attachments to Drive and send a file ref |
| `frontend/src/types/workflow.ts`, `frontend/src/types/node.ts`, `frontend/src/components/Canvas/WorkflowCanvas.vue` | New fields + defaults |
| `frontend/src/components/Panels/propertiesPanel/nodes/AgentNodeProperties.vue` | Toggle + warning |
| `frontend/src/components/Panels/propertiesPanel/nodes/CodeNodeProperties.vue`, `usePropertiesPanelController.ts` | Files field + 1/n expression navigation |
| `frontend/src/features/release-tour/releaseRegistry.ts`, `tourVisuals.ts` | Section + visual (drop the oldest section to keep five) |
| Docs: `agent-node.md`, `code-node.md`, `chat-tab.md`, `drive.md`, `features.md`, `frontend/src/docs/manifest.ts` | Feature docs |

---

### Task 1: Sandbox libraries in the images and the dev group

**Files:** Create `docker/sandbox-requirements.txt`; modify `backend/Dockerfile`, `docker/release.Dockerfile`, `backend/pyproject.toml`.

- [ ] **Step 1:** Write `docker/sandbox-requirements.txt`:

```
# Libraries the file-analysis sandbox imports. Installed into the image's system
# Python because sandbox containers run plain `python`, not the backend venv.
pandas==2.3.3
openpyxl==3.1.5
xlrd==2.0.2
pdfplumber==0.11.7
pypdf==6.1.3
python-docx==1.2.0
langdetect==1.0.9
```

(Resolve exact current versions with `uv pip compile` before pinning; all must have cp314 wheels or be pure Python.)

- [ ] **Step 2:** In `backend/Dockerfile` after `RUN pip install uv`:

```dockerfile
COPY docker/sandbox-requirements.txt /tmp/sandbox-requirements.txt
RUN uv pip install --system --no-cache -r /tmp/sandbox-requirements.txt && rm /tmp/sandbox-requirements.txt
```

In `docker/release.Dockerfile`, the same two lines in the final stage after its `RUN pip install uv` (line ~139).

- [ ] **Step 3:** `cd backend && uv add --dev pandas openpyxl xlrd pdfplumber langdetect` (pypdf and python-docx are already runtime deps).
- [ ] **Step 4:** Local sandbox image for verification only (not committed): `FROM heym-backend:local` + the same install, tagged `heym-backend:local`.
- [ ] **Step 5:** Verify: `docker run --rm --entrypoint python heym-backend:local -c "import pandas, openpyxl, xlrd, pdfplumber, pypdf, docx, langdetect"` exits 0.

### Task 2: Limits and the shared access fragment

**Files:** Create `file_sandbox/limits.py`, `file_sandbox/manifest.py`; modify `llm_service.py::_load_skill_drive_files`.

`limits.py`:

```python
MEMORY_LIMIT = "2g"
CPU_LIMIT = "2"
PIDS_LIMIT = "256"
CALL_TIMEOUT_SECONDS = 120.0
TMPFS = "/tmp:rw,nosuid,size=512m"
MAX_WORKSPACE_BYTES = 2 * 1024**3
MAX_OUTPUT_FILES = 20
MAX_OUTPUT_FILE_BYTES = 100 * 1024**2
MAX_STDOUT_CHARS = 20_000
MAX_CONCURRENT_CONTAINERS = 4
CHAT_WORKSPACE_IDLE_DAYS = 30
LIST_FILES_MAX_LIMIT = 200
```

`manifest.py` (sync; the executor and the chat tools both call it through `asyncio.to_thread` or directly from executor threads):

```python
@dataclass(frozen=True)
class DriveFileRef:
    id: uuid.UUID
    name: str
    mime: str | None
    size: int | None
    created_at: datetime | None
    source: str | None
    shared: bool
    storage_path: Path   # never serialized to the model or the sandbox

    def public(self) -> dict[str, object]: ...  # id, name, mime, size, created_at, source, shared

def list_accessible_files(db, user_id, *, query=None, limit=50, offset=0) -> tuple[list[DriveFileRef], int]
def resolve_files(db, user_id, refs: list[str]) -> list[DriveFileRef]   # id or exact name (newest match); raises FileAccessError
def still_accessible(db, user_id, file_ids: set[uuid.UUID]) -> set[uuid.UUID]
```

All three select from `drive_file_access_rows(user_id)` joined to `GeneratedFile` — the single rule. `FileAccessError("File not found or not accessible: <ref>")` is the uniform failure.

`_load_skill_drive_files` keeps its output shape but builds its rows from `drive_file_access_rows` (skills behavior unchanged, rule now shared).

### Task 3: Workspace

**Files:** Create `file_sandbox/workspace.py`; test `tests/test_file_sandbox_workspace.py`.

```python
class FileWorkspace:
    def __init__(self, root: Path, *, owner_id: uuid.UUID): ...
    @classmethod
    def for_run(cls, owner_id) -> "FileWorkspace"          # runs/<uuid4>
    @classmethod
    def for_chat(cls, user_id, conversation_id) -> "FileWorkspace"   # chats/<user>/<conv>
    in_dir, work_dir, out_dir: Path
    def ensure(self) -> None                 # mkdir in/ (0o755), work/ + work/out (0o777)
    def add_inputs(self, refs: list[DriveFileRef]) -> list[dict]   # copy once into in/<id>/<safe name>, update meta.json index
    def inputs(self) -> list[dict]           # index entries: id, name, mime, size, path (/input/<id>/<name>)
    def prune(self, keep_ids: set[uuid.UUID]) -> list[str]   # delete copies not in keep_ids
    def collect_outputs(self) -> list[CollectedFile]          # no-follow checks, removes collected files
    def usage_bytes(self) -> int
    def summary(self) -> str                 # short text for the chat dynamic block
    def touch(self) -> None                  # meta.json last_used_at
    def delete(self) -> None
```

Collection rules (each failing entry is skipped and reported in `rejected`): `os.lstat` → not `S_ISREG` or `S_ISLNK` → reject; `st_nlink > 1` → reject; size > `MAX_OUTPUT_FILE_BYTES` → reject; open with `os.open(path, O_RDONLY | O_NOFOLLOW)`, `fstat` again and compare inode; name through `_normalize_storage_filename`; nested dirs under `out/` are walked with `os.scandir(follow_symlinks=False)`; more than `MAX_OUTPUT_FILES` → the rest rejected. Root resolution follows `code_python_executor._is_containerized()`: temp dir natively, `<workspace mount>/_file-sandbox` in containers.

Tests: symlink to `/etc/passwd` rejected; hardlink rejected; fifo rejected; normal file collected and removed; name with `..` rejected; quota counts `in/` + `work/`; prune removes only non-kept ids; `for_chat` path contains both ids; `delete` removes the tree.

### Task 4: Runner, `heym_files`, inspector

**Files:** Create `file_sandbox/runner.py`, `heym_files.py`, `inspector.py`; test `tests/test_file_sandbox_inspector.py`.

Runner payload: `{"runner": src, "modules": {"heym_files": src, "heym_inspector": src}, "mode": "inspect"|"python", "code": str, "target": {...}, "options": {...}, "inputs": [...]}`. The bootstrap registers the shipped modules in `sys.modules` (via `types.ModuleType` + `exec`), captures stdout/stderr into a bounded buffer, and prints one JSON envelope `{"success", "result", "stdout", "error"}`. `python` mode executes the code with `__name__ == "__main__"`; a traceback is returned as `error`.

`heym_files`: reads `/input/_manifest.json` written by the workspace: `list_files()`, `path(name_or_id)` (raises `FileNotFoundError` naming the available files), `out_dir()`.

`inspector.inspect(path, mime, name, options) -> dict` with `kind` in `pdf|spreadsheet|csv|docx|json|text|binary` and the per-type fields from the spec. Detection by extension first, then magic bytes. Encrypted PDF → `{"encrypted": true, "error": ...}`. Scanned → `{"text_extractable": false, "scanned": true, "suggestion": "Converter node pdfToText (OCR)"}`. CSV encoding: try utf-8-sig, utf-8, cp1254, latin-1; delimiter via `csv.Sniffer` on the first 64 KB. Language via `langdetect` (seeded `DetectorFactory.seed = 0`) on ≤ 5,000 chars. Samples truncated to 2,000 chars per field.

Tests build fixtures in-process (openpyxl workbook with two sheets, cp1254 `;` CSV with Turkish text, python-docx document with headings and a table, pypdf-written PDF with text, encrypted PDF via `PdfWriter.encrypt`, blank-page PDF, JSON array of 10k records, corrupt xlsx bytes) and assert the summary fields.

### Task 5: Executor

**Files:** Create `file_sandbox/executor.py`; test `tests/test_file_sandbox_docker.py`.

```python
def run_in_sandbox(workspace: FileWorkspace, payload: dict) -> SandboxOutcome
```

- Requires `docker_available()` and `resolve_sandbox_image()` (from `code_python_executor`), else `RuntimeError` (fail closed).
- `hardening_args(name, "none", TMPFS)` then replace the memory/cpu values with the file-sandbox limits (add a `limits` parameter to `hardening_args` with the Code node defaults so both share one function).
- Mounts: `in/` → `/input` readonly, `work/` → `/work` rw, each through `_resolve_workspace_mount`-style resolution generalized to `(host_path, container_path, readonly)`.
- `--workdir /work --entrypoint python image -c BOOTSTRAP`.
- Module-level `threading.BoundedSemaphore(MAX_CONCURRENT_CONTAINERS)`; per-workspace `threading.Lock` registry.
- Envelope parse; stdout truncated to `MAX_STDOUT_CHARS` with a "print less" note.

Docker tests (skip when `docker_available()` is false or the image lacks pandas): network blocked (`socket.create_connection` fails), env has no `SECRET_KEY`/`DATABASE_URL`/`ENCRYPTION_KEY` even when set in the backend env, `/input` not writable, `/work` persists between two calls, inspector on an xlsx returns sheets.

### Task 6: Toolbox

**Files:** Create `file_sandbox/tools.py`, `instructions.py`, `__init__.py`; test `tests/test_file_sandbox_tools.py`.

```python
LIST_FILES_TOOL, INSPECT_FILE_TOOL, RUN_PYTHON_TOOL, CLEAR_WORKSPACE_TOOL = ...
def tool_schemas(*, include_clear: bool) -> list[dict]       # OpenAI function format
def agent_tool_defs(toolbox: "FileToolbox") -> list[dict]     # {"name", "description", "parameters", "_source": "file_sandbox", "_file_toolbox": toolbox}

class FileToolbox:
    def __init__(self, workspace: FileWorkspace, actor_id: uuid.UUID, *, workflow_id=None, source_label: str): ...
    def call(self, name: str, args: dict) -> dict      # sync; opens its own SessionLocal
```

`call` flow for `inspect_file` / `run_python`: resolve requested refs for the actor → `prune(still_accessible(...))` → quota check → `add_inputs` → `run_in_sandbox` → `collect_outputs` → `store_file_sync(owner=actor, source_node_label=source_label, workflow_id=...)` → return `{"untrusted_file_content": true, ...}` with `generated_files: [{id, name, mime, size, download_path}]`. `list_files` returns `{files, total, limit, offset}` of `DriveFileRef.public()`. `clear_workspace` deletes the workspace. Errors come back as `{"error": "..."}` (never raise into the model loop).

Tests (mock `run_in_sandbox`, real SQLite-free unit level with patched manifest): unknown name → uniform error; resolved file copied once across two calls; outputs stored with actor as owner and no token in the result; `untrusted_file_content` marker present; `clear_workspace` deletes.

### Task 7: Advisory tests for access (real Postgres)

**Files:** Create `tests/test_advisory_file_sandbox_access.py`.

Pattern: copy the real-Postgres harness used by `test_advisory_folder_share_real_postgres.py`. Cases: user B cannot resolve user A's private file by id or by name; B in team T2 cannot resolve a file shared with T1; after the share row is deleted `still_accessible` drops it; `list_accessible_files` returns no `storage_path`, URL or token keys; mutation check: monkeypatch `drive_file_access_rows` to a version without the team filter and assert the cross-team case now fails (proves the test can fail).

### Task 8: Agent node

**Files:** Modify `workflow_executor.py`, `llm_service.py`, `node_placement.py`; tests in `test_file_sandbox_tools.py` and `test_cluster_node_placement.py`.

- `_execute_agent_node` → when `node_data.get("fileAnalysisEnabled")`: `actor = self._require_actor_user_id("File analysis")`, `workspace = FileWorkspace.for_run(actor)`, `toolbox = FileToolbox(...)`, extend `merged_tools` with `agent_tool_defs(toolbox)`, append `agent_instructions()` to `system_instruction`, and wrap the remainder in `try/finally: workspace.delete()`. Implemented by renaming the current body to `_run_agent_node(..., file_toolbox)` and keeping `_execute_agent_node` as the wrapper so the sub-agent call site (`_execute_agent_node(target_node_id, ...)`) gets the same behavior.
- `_unified_tool_executor`: `if tool_def.get("_source") == "file_sandbox": return tool_def["_file_toolbox"].call(name, args)`; generated files also go under `_generated_files` so `agent_node._collect_generated_files_from_output` surfaces them.
- `node_placement._agent_placement`: MAIN when skills or `fileAnalysisEnabled`.

Tests: toggle off → no file tools in merged tools; toggle on without actor → refusal error; workspace deleted when the agent body raises (patch `_run_agent_node` to raise); placement predicates.

### Task 9: Code node `codeFiles`

**Files:** Modify `code_node.py`, `code_python_executor.py`, `node_placement.py`; tests in `test_file_sandbox_tools.py` (or a new `test_code_node_files.py`).

- `code_node.execute`: resolve `codeFiles` with `_resolve_value` (`preserve_type=True`) → normalize to a list of id strings (accept str, list[str], dicts with `id`, comma/newline-separated text) → if non-empty, `execute_code_with_files(...)`, else the existing `execute_code` unchanged.
- `execute_code_with_files`: run workspace, resolve for actor (`ctx.executor.actor_user_id`, refuse when None), add inputs, run the Code runner with file-sandbox limits and the `/input` + `/work` mounts, `params["files"] = workspace.inputs()` metadata, collect outputs to Drive, return `{"result", "logs", "install", "files"}`; always `workspace.delete()`.
- Dependencies: keep the install phase; its `.deps` dir lives under `work/.deps` and is mounted readonly in the run phase via `PYTHONPATH`.
- Placement: `_code_placement(data)` → MAIN when `codeFiles` is a non-blank value.

Tests: id list normalization; inaccessible id → "File not found or not accessible"; no files → `execute_code` called exactly as before; placement predicate.

### Task 10: Chat tool group, attachments and lifecycle

**Files:** Create `api/chat_files.py`, `file_sandbox/chat_workspaces.py`; modify `ai_assistant.py`, `chats.py`, `chat_build.py`, `main.py`; tests `test_file_sandbox_chat_lifecycle.py`, `test_file_sandbox_tools.py`.

- `ChatFileTools(user, conversation_id)` mirrors `ChatEvalTools`: `schemas()`, `handles(name)`, `display_args`, `step_label` (`Listing Drive files...`, `Inspecting "<name>"...`, `Running Python on N files...`, `Clearing the workspace...`), `async call(name, args) -> BuildToolOutcome` (runs `FileToolbox.call` in `asyncio.to_thread`), `prompt_block()` (workspace summary), and calls `audit("drive.chat_mount", actor=user, target_type="file", ...)` for each newly mounted file.
- `stream_dashboard_chat` gets `files: ChatFileTools | None = None`. `_call_kwargs` appends `files.schemas()`. The dispatch branch becomes `group = next(g for g in (build, files) if g is not None and g.handles(name))`, reusing the existing build branch body unchanged.
- `chats.py` turn runner: build `ChatFileTools(user, conv_uuid)` for every persisted turn; add `file_sandbox_instructions()` to the static prompt and the workspace summary to the dynamic part.
- `FileAttachment`: kind adds `"file"`, new optional `file_id: uuid.UUID | None`, `size: int | None`, `mime: str | None`. Message POST validates `file_id` through `get_accessible_file` and overwrites name/size/mime from the row (404 otherwise). `_build_user_message` for `file`: `[ATTACHED DRIVE FILE: <name> · id <id> · <size> · <mime>]` plus "Use inspect_file / run_python; the content is not in this message." The persisted `attachment_data` keeps `file_id`.
- Injection: `execute_workflow` and `run_workflow_test` inject `str(file_id)` for `kind == "file"` into the field picked by `_find_injection_field(field_keys, "file")` (keywords `file`, `document`, `attachment`, `data`).
- Lifecycle: `delete_conversation` and the bulk delete call `delete_chat_workspace(user_id, conversation_id)` / `delete_user_chat_workspaces(user_id, ids)` after commit. `sweep_idle_chat_workspaces(now)` deletes workspaces whose `meta.json` `last_used_at` is older than 30 days; started as a background loop (every 6 h) only when `cluster.identity.is_main()`.

Tests: two users with the same conversation id get different paths; delete hook removes the dir; sweep deletes old and keeps fresh; attachment with someone else's `file_id` → 404; `_build_user_message` never contains file bytes; tool group dispatch reaches `ChatFileTools` (mock toolbox).

### Task 11: DSL prompt and frontend fields

**Files:** `workflow_dsl_prompt.py`, `types/workflow.ts`, `types/node.ts`, `WorkflowCanvas.vue`, `AgentNodeProperties.vue`, `CodeNodeProperties.vue`, `usePropertiesPanelController.ts`.

- DSL: agent field `fileAnalysisEnabled` (default false; when to use; tools it adds; MAIN-only note not needed), code field `codeFiles` (examples `"$Upload.file.id"`, `"$fetch.files"`; `heym_files.path`, `/work/out`), and a builder rule in the build-mode instructions: deterministic extraction → Code node with `codeFiles`; open-ended → Agent with `fileAnalysisEnabled`; test with the real file id.
- Types/defaults: `fileAnalysisEnabled?: boolean`, `codeFiles?: string`; defaults `false` / `""`.
- Agent panel: a `Switch` row "File analysis" with help text and the warning line.
- Code panel: `ExpressionInput` "Files" with `field-key="codeFiles"`; controller adds `codeFilesInputRef` and code-node 1/n navigation over `codeParameters` + `codeFiles` following the converter pattern.

### Task 12: Chat composer upload

**Files:** `useFileAttachment.ts`, `api.ts`, `DashboardChatComposer.vue` (Heym); Work follows in its own repo after heymrun.

- Document extensions (`pdf, xlsx, xls, csv, tsv, docx, json, txt, md`) upload through `filesApi.upload(file)` (existing `/files/upload`), then the attachment becomes `{name, kind: "file", content: "", file_id, size, mime}`. Size limit is the server's. Images and zip unchanged.
- `FileAttachmentPayload` type gains `file_id?`, `size?`, `mime?`.

### Task 13: Docs and release tour

- `reference/file-analysis.md` (tools, limits, lifecycle, security model, residual risk), manifest registration, updates to `agent-node.md`, `code-node.md`, `chat-tab.md`, `drive.md`, `features.md`.
- `releaseRegistry.ts` 2026.24: section `file-analysis` + `sectionOrder`; drop the oldest of the five kept sections (and its visual + registration); `FileAnalysisTourVisual.vue` with `useCycleStep`; register in `tourVisuals.ts`.

### Task 14: Verification

- [ ] `cd backend && uv run ruff format . && uv run ruff check .`
- [ ] `HEYM_OTEL_ENABLED=false uv run pytest tests/test_file_sandbox_*.py tests/test_advisory_file_sandbox_access.py tests/test_cluster_node_placement.py -q`
- [ ] `cd frontend && bun run lint && bun run typecheck && bun run build`
- [ ] `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
- [ ] Manual end-to-end against the local image: an xlsx in Drive → `FileToolbox` inspect → run_python sum → output csv lands in Drive.
