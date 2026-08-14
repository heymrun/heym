# Code Node — Sandboxed Python Execution

**Date:** 2026-08-14
**Status:** Approved design, ready for implementation planning

## Problem

Heym has no standalone Python node. Python only exists inside Agent nodes, as
user-defined *tools* (`python_tool_executor.py`) and *skills*
(`skill_python_executor.py`). A workflow author who wants to run a plain script
between two nodes has to wrap it in an Agent, which pulls in an LLM call, a
system prompt, and non-deterministic tool selection for what should be a
deterministic transform.

The gap is visible in the DSL prompt itself, which carries several warnings of
the form "Do NOT write Python in an `execute` node" — the LLM keeps reaching for
a Python node that does not exist. (`execute` runs a sub-workflow, not code.)

## Goal

A `code` node that runs arbitrary user Python in a disposable, hardened
container. Two inputs: the code, and a `requirements.txt`. Every execution gets
a fresh sandbox. No process is ever spawned on the host, and the sandbox has no
route to the backend's environment, secrets, or Docker daemon.

## Non-goals (v1)

- Heym Drive file access from the sandbox
- Availability as an Agent node tool
- Any dependency caching between runs
- A non-Docker execution path of any kind

## Why containers, not a native Python sandbox

The user asked whether a sufficiently secure native Python option exists. It
does not — not one that also honors an arbitrary `requirements.txt`:

| Option | Real security boundary? | Arbitrary requirements.txt? |
|---|---|---|
| `RestrictedPython` / AST allowlist | No — in-process CPython sandboxes are escapable by design | Yes |
| Pyodide / WASM (`wasmtime`) | Yes | No — pure-Python and Pyodide-built wheels only; manylinux C extensions fail |
| `nsjail` / `bubblewrap` / seccomp | Yes | Yes, but host-installed Linux binaries |
| gVisor (`runsc`) | Strongest | Yes, but a host runtime that cannot ship inside an image |

The repository already states this conclusion in
`backend/app/services/python_tool_executor.py`: the in-process allowlist is
"best effort and NOT a security boundary." The `nsjail` and gVisor options
additionally conflict with the standing rule that platform dependencies ship in
`run.sh` / the images rather than becoming operator setup steps.

So: a disposable hardened container, modeled on the two working precedents
already in the codebase.

## Execution architecture

New service `backend/app/services/code_python_executor.py`, patterned on
`skill_python_executor.py` (which already solves per-run workspaces,
`volume-subpath` mounting, and image resolution).

### How the runner reaches the container

`code_runner.py` is **not** read from a baked image path. The two images place
the backend differently (`backend/Dockerfile` puts it at `/app`,
`docker/release.Dockerfile` at `/app/backend`), and `python_tool_executor.py`
papers over that with a `HEYM_PYTHON_TOOL_RUNNER_PATH` override — a variable
this node is not allowed to add.

Instead the backend reads its own `code_runner.py` source and ships it inside
the stdin payload. The container entrypoint is a short bootstrap:

```
--entrypoint python <image> -c "import sys,json;p=json.loads(sys.stdin.read());
g={'__name__':'__heym_runner__'};exec(compile(p['runner'],'code_runner.py','exec'),g);g['run'](p)"
```

No path guessing, no environment variable, and — importantly — the run phase
needs no mounted filesystem at all when there are no dependencies.

### Fast path — empty `requirements.txt`

The install phase is skipped entirely, and because the runner arrives over
stdin the container needs **no volume and no mount**:

```
Phase 2  [--network none]  python -c <bootstrap> < payload  ->  JSON envelope
```

This is the common case (pure transforms). With `codeAllowNetwork` left at its
`false` default it never touches the network at all; setting the toggle makes
this single container `--network bridge`, exactly as it does in the two-phase
path below.

### With dependencies — two containers sharing one per-run directory

The backend creates a per-run directory and writes `requirements.txt` into it.
When the backend is containerised that directory lives on the shared workspace
volume the skill sandbox rides, mounted via `volume-subpath`; a native
(`run.sh`) backend already holds a real host path, so it bind-mounts a local
temporary directory straight through instead and needs no volume. Both
containers mount only that subtree, so a run never sees another run's files.

```
run_dir = <codex-workspace-volume>/_code-runs/<uuid>/

Phase 1  [--network bridge]
    entrypoint uv  ->  pip install --no-cache --target run_dir/.deps
                       -r run_dir/requirements.txt
    on any non-zero exit, a second container retries with
    entrypoint pip  ->  install --no-cache-dir --target ... -r ...
    no cache mount — every run installs from scratch

Phase 2  [--network none  |  --network bridge if codeAllowNetwork]
    PYTHONPATH=run_dir/.deps  python -c <bootstrap> < payload

finally: shutil.rmtree(run_dir)     # every container already --rm
```

Phase 1 mounts `run_dir` read-write, because that is where the packages land.
Phase 2 mounts the same subtree with `readonly`, so the user's code can read
`.deps` but cannot modify it. In both phases the container root filesystem is
`--read-only` and the only writable location for the code itself is a
`--tmpfs /tmp`.

Two separate containers for uv and pip, rather than one `uv || pip` shell, so
the result records which tool actually installed the packages.

### Container hardening (both phases)

`--rm`, `--user 65534:65534`, `--cap-drop ALL`,
`--security-opt no-new-privileges`, `--read-only` root filesystem,
`--tmpfs /tmp:rw,nosuid`, `--pids-limit`, `--memory` with matching
`--memory-swap`, `--cpus`. No Docker socket. No backend secrets — only the
portable proxy/CA/locale forward list already used by the skill sandbox.

### Fail-closed, no fallback

Unlike the tool and skill sandboxes, the Code node has **no subprocess mode**
and reads **no sandbox-mode environment variable**. If no Docker daemon is
reachable it raises:

> Code node execution requires Docker. No fallback exists for this node.

Consequence, accepted deliberately: on native `run.sh` development (which sets
`HEYM_PYTHON_TOOL_SANDBOX=subprocess` for the other paths) the Code node fails
unless a Docker daemon is running. Docker Compose and the GHCR single-container
deployments are unaffected.

Image resolution reuses the existing chain with no new variable:
`HEYM_PYTHON_TOOL_IMAGE` -> `HEYM_CODEX_DOCKER_IMAGE` -> inspect this
container's own image.

### Why uv, with a pip fallback

`uv` is already present in both images (`backend/Dockerfile`,
`docker/release.Dockerfile`), so it is not a new platform dependency.
`uv pip install --target` is a drop-in for the pip form, implements PEP
517/508/440, and pulls the same PyPI wheels. It matters here because installs
are per-execution and uncached: uv finishes in 1-3s where pip takes 15-40s.

uv is stricter than pip about malformed package metadata, and rare
`setup.py`-only packages can behave differently. Falling back to pip on install
failure keeps compatibility at pip's level while getting uv's speed in the
common case. The fallback attempt is recorded in the install log.

## Code contract

```python
# Node config -> Parameters (JSON, $ expressions supported):
#   { "name": $trigger.customer.name, "orders": $fetch.result }

def main(params):
    name = params.name              # dot notation
    total = len(params.orders)      # list elements are wrapped too
    return {"greeting": f"hi {name}", "total": total}
```

`code_runner.py` wraps the resolved parameters in a `DotDict` that recursively
wraps nested dicts and list elements. Rules:

- `params.foo` returns the wrapped value
- `params["my key"]` also works, for keys that are not valid identifiers
- A missing key raises `AttributeError` naming the key and listing the
  available top-level keys
- `params.to_dict()` returns the plain unwrapped dict

If the module defines no `main`, or `main` is not callable, the node fails with
a clear message. `main`'s return value must be JSON-serializable; if it is not,
the node fails rather than silently stringifying.

`print()` output is captured by redirecting `sys.stdout` to a buffer for the
duration of `main()`. The JSON envelope is written to the real stdout
afterwards, so user prints can never corrupt the protocol.

## Node output

```json
{
  "result":  "<return value of main()>",
  "logs":    "captured stdout\n",
  "install": { "ok": true, "tool": "uv", "log": "Installed 3 packages in 1.2s" }
}
```

Downstream nodes read `$code1.result.greeting`. When `requirements.txt` is
empty, `install` is `{"ok": true, "tool": "none", "log": ""}`. When uv fails and
pip succeeds, `tool` is `"pip"` and `log` contains both attempts.

## Node fields

| Field | Type | Default | Notes |
|---|---|---|---|
| `codeSource` | string | Hello example below | The Python source |
| `codeRequirements` | string | `""` | `requirements.txt` contents |
| `codeParameters` | string (JSON) | `{"name": "Heym"}` | `$` expressions resolved before execution |
| `codeAllowNetwork` | boolean | `false` | Phase 2 network. Install always has network. |

### Canvas default

```python
def main(params):
    name = params.name
    return {"message": f"Hello, {name}!", "length": len(name)}
```

With `codeParameters` defaulting to `{"name": "Heym"}` and empty requirements,
a freshly dropped node runs successfully, demonstrates dot notation, and takes
the single-container no-network fast path.

## Limits

Constants in the executor module, not environment variables: memory 512m,
cpus 1, pids 256, install timeout 120s, run timeout 60s. This follows the
standing rule that platform limits are constants rather than operator
configuration.

## File map

### Backend, new

- `app/services/code_python_executor.py` — phase orchestration, hardened
  `docker run` construction, run-dir lifecycle, fail-closed check, uv/pip
  fallback
- `app/services/code_runner.py` — runs inside the container: reads the stdin
  payload, wraps params, imports the user module, calls `main`, captures
  stdout, emits the JSON envelope
- `app/services/node_execution/nodes/code_node.py` — resolves `$` expressions
  in `codeParameters`, calls the executor, packages `{result, logs, install}`

### Backend, edited

- `app/services/node_execution/registry.py` — one entry, `"code": "code_node"`
- `app/services/workflow_dsl_prompt.py` — new `code` section
- `ENVIRONMENT-VARIABLES.md` — note that the Code node requires Docker, adds no
  variables, and has no fallback

`workflow_executor.py` is not touched, per the executor modularity rule.

### Backend tests, new

- `tests/test_code_python_executor.py` — empty requirements selects the single
  phase; two-phase ordering; hardening flags present in the built command
  (`--network none`, `--cap-drop ALL`, `--user`, no Docker socket); uv failure
  falls back to pip; timeouts kill and force-remove the container; run dir is
  removed in `finally`; `RuntimeError` when Docker is unreachable
- `tests/test_code_runner.py` — DotDict semantics (nested dicts, lists, missing
  key message, non-identifier keys, `to_dict()`), missing `main`,
  non-serializable return, stdout capture isolation
- `tests/test_code_node.py` — parameter expression resolution, output
  packaging, error paths

Tests mock `subprocess.Popen`; nothing in the suite requires a live Docker
daemon, so `./check.sh` stays clean in CI.

### Frontend

- `types/workflow.ts` — `"code"` in the node type union plus the four fields
- `types/node.ts` — node schema entry: label, one input and one output,
  defaults, AI-autofill hints, expression-dialog eligibility metadata
- `components/Canvas/WorkflowCanvas.vue` — canvas default data
- `components/Panels/NodePanel.vue` and `lib/nodeIcons.ts` — palette entry,
  `Code2` lucide icon, color token
- `components/Panels/propertiesPanel/nodes/CodeNodeProperties.vue` — new: code
  editor, requirements textarea, parameters JSON field, network switch
- `components/Panels/propertiesPanel/nodes/NodePropertiesForm.vue` — one
  `v-else-if` line
- `styles/globals.css` — color variable if a new token is needed

`PropertiesPanel.vue` is not touched, per the thin-shell rule.

No Playwright E2E spec: per standing instruction, heymrun frontend changes are
verified with `bun run lint`, `bun run typecheck`, and manual checks.

### Docs, heymrun

- `docs/content/nodes/code-node.md` — new page
- `docs/manifest.ts` — register the page
- `docs/content/reference/node-types.md` — table row
- `docs/content/reference/features.md` — per-node section and the node-types
  summary list
- `docs/content/reference/security.md` — new "Code node sandbox" section

No credential-backed surfaces, so `credentials.md`, `credentials-sharing.md`,
and `integrations.md` are untouched.

### Docs, heymweb sync

Six files, none of which `AGENTS.md` documents:

1. `src/lib/marketingNodeCatalog.ts`
2. `src/lib/node-doc-links.ts`
3. `src/components/sections/NodesSection.tsx`
4. `src/components/templates/nodePreviewTokens.ts`
5. `src/components/templates/TemplateCanvasNode.tsx`
6. `src/components/sections/DocumentationSection.tsx`

Then `bun run sync-docs` and `bun run sync-dsl-prompt`.

Trap: `tests/seo/invariants.test.ts` hardcodes the node count in two places —
the test title and `expect(MARKETING_NODE_COUNT).toBe(N)`. Missing the bump
breaks `bunx tsc --noEmit`, not just the test run. Mirror the heymrun icon and
color choices rather than inventing new ones.

## DSL support

A new section in `workflow_dsl_prompt.py` so the assistant can author Code
nodes correctly. It must cover:

- The four fields and their types
- The `def main(params)` requirement, dot notation, JSON-serializable return
- A complete worked example workflow
- When *not* to use it: CSV and XML belong in `converter`, HTTP calls belong in
  the `http` node, sub-workflows belong in `execute`
- No backticks inside `codeSource`, mirroring existing agent-tool rule 36b —
  backticks break workflow JSON extraction
- `codeAllowNetwork` stays `false` unless the code genuinely needs egress

## Error handling

| Condition | Behavior |
|---|---|
| No Docker daemon | `RuntimeError`, node fails, message states no fallback exists |
| Install fails under both uv and pip | Node fails; `install.log` carries both attempts |
| Install exceeds 120s | `TimeoutError`; container killed and force-removed |
| Code raises | Node fails with the traceback; stdout captured before the raise is preserved in the failure message, since no `logs` field is produced on a failed run |
| Code exceeds 60s | `TimeoutError`; container killed and force-removed |
| No `main`, or `main` not callable | Node fails with a clear message |
| Return value not JSON-serializable | Node fails rather than stringifying |
| Docker exit 125/126/127 | Sandbox never started — fail closed, never treated as a completed run |

The run directory is removed in a `finally` block on every path.

## Verification

- `SECRET_KEY=test-secret-key-for-tests-only-32-bytes HEYM_OTEL_ENABLED=false ./check.sh`
  from the repo root — Ruff format, lint, and the full backend suite
- `bun run lint` and `bun run typecheck` in `frontend/`
- Manual: drop the node on the canvas, run the default, confirm the JSON
  output; add `requests` to requirements and confirm the install log; toggle
  Allow network and confirm egress behavior flips
- heymweb: `bunx tsc --noEmit`, `bun test tests/seo/invariants.test.ts`,
  `bun run build`
