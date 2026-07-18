# OpenCode Go coding-agent node — Design

Date: 2026-07-18
Status: Approved (pending spec review)

## 1. Summary

Add a new workflow node type **`opencodeGo`** ("OpenCode Go") that runs the
[OpenCode](https://opencode.ai) CLI (Go) against a Git repository to implement a coding task,
mirroring the existing **Codex** node's publish flow and agent-tool integration. Two deliberate
differences from Codex:

1. **Model provider = OpenCode Go gateway** (`https://opencode.ai/zen/go/v1/`), with `opencode/<model>`
   model ids (e.g. `opencode/kimi-k3`, `opencode/deepseek-v4-pro`, `opencode/qwen3.7-max`). Running
   OpenCode **requires an API key** (the credential's `api_key` is required); the gateway's model
   *listing* endpoint happens to be keyless, which is used only to populate the dropdown. Because the
   roster changes often, the node **fetches the live model list** and shows it in a searchable
   dropdown, with a **hardcoded fallback** when the fetch fails.
2. **Isolation = hardened, throwaway Docker container, fail-closed.** OpenCode has no built-in OS
   sandbox (unlike Codex's `--sandbox workspace-write`), so the `opencode run` step executes inside a
   hardened sibling container. If Docker/the image is unavailable, the node errors (no silent
   host execution).

Scope: all 7 Codex publish modes + agent-tool + PR screenshots. **No** `needs_input` pause/resume
(lean HITL) in v1 — the node always completes.

## 2. Credential

New `CredentialType.opencode` = `"opencode"`, config `{ api_key: str, base_url?: str }`.
- `api_key` — OpenCode Go gateway key, **required**.
- `base_url` — optional gateway override (default `https://opencode.ai/zen/go/v1`) for self-host/proxy.

The opencode credential is **required** on the node (`credentialId`). The node also references an
existing `github` credential via `githubCredentialId` (unchanged, **required**), exactly like Codex.
Frontend adds the `opencode` type to credential dialog/panel/config unions.

## 3. Node fields

Mirror the Codex node (minus resume-specific fields):

| Field | Default | Notes |
|-------|---------|-------|
| `credentialId` | — | opencode credential (required) |
| `githubCredentialId` | — | github credential (required) |
| `repositoryUrl` | — | expression-capable, required |
| `baseBranch` | `main` | expression-capable |
| `taskPrompt` | `$input.text` | expression-capable, required |
| `branchName` | `opencode/$executionId` | expression-capable; sanitized |
| `publishMode` | `diff_only` | 7 modes: `diff_only`, `draft_pr`, `open_pr`, `commit_push`, `direct_commit`, `update_existing_pr`, `patch_artifact` |
| `setupCommand` | `` | optional; runs on host before container exec |
| `timeoutSeconds` | `3600` | clamped `[60, 21600]` |
| `opencodeModel` | `opencode/kimi-k3` (fallback head) | dynamic dropdown; empty → runner default |
| `opencodeVariant` | `` | optional → `opencode run --variant` (model reasoning effort) |

## 4. Dynamic model list + fallback

- **Backend endpoint** `GET /api/opencode-go/models` (optional `?credentialId=` to honor a
  credential's `base_url`). Fetches `{base_url}/models` (default
  `https://opencode.ai/zen/go/v1/models`), which is keyless and OpenAI-style
  (`{"object":"list","data":[{"id":"kimi-k3"},…]}`). Each bare `id` is normalized to
  `opencode/<id>`; result cached in-memory briefly (~10 min TTL). **On any error (network, non-200,
  parse) returns the hardcoded `OPENCODE_MODEL_FALLBACK` catalog** with `source: "fallback"` so the UI
  degrades gracefully.
- **Frontend** `OpenCodeGoNodeProperties.vue` populates a searchable dropdown from that endpoint,
  itself falling back to the static `opencodeCatalog.ts` list on request error.
- **Runner** default: empty `opencodeModel` → `opencode/kimi-k3` (fallback head); the chosen id is
  passed verbatim to `opencode run --model`.

`OPENCODE_MODEL_FALLBACK` (backend catalog + mirrored `opencodeCatalog.ts`) seeds a small, known-good
set of Go-gateway models, e.g. `opencode/kimi-k3`, `opencode/deepseek-v4-pro`, `opencode/qwen3.7-max`,
`opencode/minimax-m3`.

## 5. Execution — security core

Git clone/commit/push/PR all happen **on the host** (Heym owns git, same policy as Codex). **Only** the
`opencode run` step runs in a container.

Flow (`OpenCodeRunnerService`):
1. Host clone of the repo into `HEYM_OPENCODE_WORKSPACE_DIR` (shared workspace helper — see §6),
   excluding runner scaffolding from git.
2. Write an isolated OpenCode home into a per-run dir mounted into the container:
   - `opencode.json` → `provider.opencode.options.baseURL` = the Go gateway URL, inline `apiKey` from
     the credential, `permission.edit/bash = "allow"`, and the default model.
   - `auth.json` → `{"opencode": {"type": "api", "key": "<key>"}}`.
3. Host runs the optional `setupCommand` (bounded, host-side, not in container).
4. Hardened `docker run --rm` executing `opencode run --format json --dir <ws> --model <id> [--variant …] --agent build <prompt>`:
   - `--read-only` root; the workspace bind is the only writable mount; `--tmpfs /tmp`;
     `--cap-drop ALL`; `--security-opt no-new-privileges`; non-root user; `--pids-limit`,
     `--memory`/`--memory-swap`, `--cpus`; **no docker socket** — reusing the hardening pattern from
     `python_tool_executor._build_docker_command`.
   - **Network egress allowed** (`--network bridge`, env `HEYM_OPENCODE_NETWORK`) because OpenCode must
     reach the model API. Mitigation: **the GitHub token is never placed in the container** (git ops
     are host-side), so generated code cannot exfiltrate push credentials. Only the opencode key and
     repo files are inside; the key is masked in all logs.
   - Image: the backend image with the `opencode` binary baked in (added to the Dockerfile), overridable
     via `HEYM_OPENCODE_IMAGE`, resolved like `python_tool_executor._resolve_image`.
   - **Fail-closed:** `HEYM_OPENCODE_SANDBOX=docker` (default) errors if Docker/image is unavailable; an
     explicit `subprocess` opt-out runs `opencode` on the host for operators who accept that risk.
5. Parse the `--format json` event stream for the final assistant summary; compute diff/changed files
   from git on the host.
6. Publish per `publishMode` via the shared publish helper (§6), including PR screenshots.

Local-only rules prompt (like Codex `_CODEX_LOCAL_ONLY_RULES`): OpenCode edits files only; Heym performs
all git/GitHub operations; screenshots saved under a gitignored path are attached to the PR after the run.

## 6. Shared code with Codex (approved)

Extract the repo/workspace + git-publish + PR-screenshot logic out of `CodexRunnerService` into shared
modules used by **both** runners:
- `RepoWorkspaceService` — clone/exclude, `_clone_url_with_token`, `_parse_github_owner_repo`,
  `_changed_files`, git diff, `cleanup_workspace`.
- `GitPublishService` — commit/push/PR creation across the 7 publish modes + PR-screenshot upload.

`CodexRunnerService` is refactored to delegate; behavior is **preserved** and guarded by the existing
Codex tests plus new shared-helper tests. `OpenCodeRunnerService` then owns only: container exec,
opencode auth/config generation, and JSON-event parsing.

## 7. Handler, registry, config

- `backend/app/services/node_execution/nodes/opencode_go_node.py` — mirrors `codex_node.py` minus the
  `needs_input`/resume branch; reuses `patch_artifact` Drive storage; validates the required opencode +
  github credentials; resolves expression fields; returns the normalized output.
- Register `"opencodeGo": "opencode_go_node"` in `node_execution/registry.py`.
- New settings (all env-aliased): `HEYM_OPENCODE_CLI_COMMAND` (default `opencode`),
  `HEYM_OPENCODE_WORKSPACE_DIR` (`./data/opencode-workspaces`), `HEYM_OPENCODE_IMAGE`,
  `HEYM_OPENCODE_SANDBOX` (`docker`|`subprocess`, default `docker`), `HEYM_OPENCODE_NETWORK` (`bridge`),
  `HEYM_OPENCODE_MEMORY`/`_CPUS`/`_PIDS`, `HEYM_OPENCODE_GIT_AUTHOR_NAME` (`Heym OpenCode`),
  `HEYM_OPENCODE_GIT_AUTHOR_EMAIL` (`support@heym.run`), `HEYM_OPENCODE_ZEN_BASE_URL`
  (`https://opencode.ai/zen/go/v1`).

## 8. DSL (source of truth per AGENTS.md)

`workflow_dsl_prompt.py`: add a new `### opencodeGo (OpenCode Go Coding Agent)` node section (fields,
publish modes, agent-tool note, model note, example workflow), add `opencodeGo`/`opencode` to the
credential rule 23a integration list, and note the `opencode/<model>` catalog. Keep the `heymweb`
`/convert` sync guard green.

## 9. Frontend

- `types/node.ts` — `opencodeGo` node type + data interface.
- `types/credential.ts` — `"opencode"` type + `CredentialConfigOpenCode { api_key; base_url? }`.
- `lib/opencodeCatalog.ts` — fallback model suggestions + variant options.
- `lib/nodeIcons.ts` — node icon.
- Canvas/panel registration (`BaseNode.vue`, `NodePanel.vue`, `WorkflowCanvas.vue`, static node type,
  category, output handles) mirroring Codex minus the `question` handle.
- `components/Panels/propertiesPanel/nodes/OpenCodeGoNodeProperties.vue` — node config UI + dynamic
  model dropdown; wired via `usePropertiesPanelController.ts`.
- Credential dialog/panel entries for `opencode`.
- Expression-dialog metadata + agent-autofill eligibility for **every** eligible field, per the
  AGENTS.md node-integration policy.
- API client method in `services/api.ts` for `GET /api/opencode-go/models`.

Per the standing "no frontend UI tests" rule, verify frontend via lint + typecheck (+ optional E2E).

## 10. Backend tests (required)

- `tests/test_opencode_runner_service.py` — docker command hardening flags + egress network + image
  resolution + **fail-closed** when Docker/image missing; auth.json/opencode.json generation + secret
  masking; JSON-event parsing → summary/changed files; token-injected clone url, owner/repo parse,
  sensitive masking.
- `tests/test_opencode_go_node.py` — credential load/validate (wrong type, missing key), field
  resolution, `patch_artifact` storage, output shape, agent-tool eligibility, error cases (missing repo
  URL / prompt / creds).
- `tests/test_opencode_models_endpoint.py` — live fetch normalization + **fallback on error**.
- Shared-helper tests for `RepoWorkspaceService`/`GitPublishService`; existing Codex tests stay green
  (regression guard for the refactor).

## 11. Docs (heym-documentation skill)

- New `frontend/src/docs/content/nodes/opencode-go.md` + register in `frontend/src/docs/manifest.ts`.
- Update reference docs: `reference/features.md` (per-node section + node-types summary list),
  `node-types.md`, and credential-backed pages `integrations.md` / `credentials.md` /
  `credentials-sharing.md`.

## 12. Dockerfile

Add the `opencode` Go binary install to the backend Dockerfile so the sibling container has it; the
runner resolves the backend's own image by default (overridable via `HEYM_OPENCODE_IMAGE`).

## 13. Out of scope (v1)

- `needs_input` pause/resume follow-up flow and the `question` output handle.
- OpenCode session continuity (`--continue`/`--session`) across runs.
- Non-zen providers (anthropic/openai/etc.) as first-class node credentials.
