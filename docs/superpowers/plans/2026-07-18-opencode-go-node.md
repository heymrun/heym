# OpenCode Go Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `opencodeGo` workflow node that runs the OpenCode CLI against a Git repo inside a hardened, fail-closed Docker container, using an OpenCode Go gateway credential + a GitHub credential, mirroring the Codex node's publish flow and agent-tool integration (lean HITL — no needs_input pause/resume).

**Architecture:** Host owns all git (clone/commit/push/PR); only `opencode run` executes in a throwaway hardened sibling container with network egress but no GitHub token inside. Reusable git/workspace/publish logic is extracted from `CodexRunnerService` into shared services that both runners use. Model list is fetched live from the keyless Go gateway `/models` endpoint with a hardcoded fallback.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.0 (async) + Pydantic + Alembic + pytest; Vue 3 + TypeScript (strict) + Bun; Docker sibling containers; OpenCode CLI (Go).

**Spec:** `docs/superpowers/specs/2026-07-18-opencode-go-node-design.md`

**Conventions:**
- Work on `main` (repo policy: no feature branches/worktrees).
- Backend tests: `unittest.TestCase`/`IsolatedAsyncioTestCase` + `AsyncMock`, run with `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/<file> -v`.
- No frontend UI tests (repo rule) — verify frontend via `cd frontend && bun run lint && bun run typecheck`.
- Before final push: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh` from repo root.
- Ruff: `cd backend && uv run ruff format . && uv run ruff check .`.

---

## File Structure

**Backend — new:**
- `backend/app/services/coding_agent/__init__.py` — shared coding-agent package.
- `backend/app/services/coding_agent/repo_workspace.py` — `RepoWorkspaceService` (clone, token-url, owner/repo parse, changed files, diff, cleanup, exclude scaffolding).
- `backend/app/services/coding_agent/git_publish.py` — `GitPublishService` (commit/push/PR across publish modes + PR-screenshot upload).
- `backend/app/services/opencode_catalog.py` — `OPENCODE_MODEL_FALLBACK`, `OPENCODE_DEFAULT_MODEL`, `normalize_opencode_models`.
- `backend/app/services/opencode_runner_service.py` — `OpenCodeRunnerService`, `OpenCodeRunRequest`, `OpenCodeRunResult`, container exec + auth/config + JSON parse.
- `backend/app/services/node_execution/nodes/opencode_go_node.py` — node handler.
- `backend/app/api/opencode_go.py` — `GET /api/opencode-go/models` endpoint.
- `backend/alembic/versions/100_add_opencode_credential_type.py` — enum migration.
- Tests: `backend/tests/test_repo_workspace_service.py`, `test_git_publish_service.py`, `test_opencode_runner_service.py`, `test_opencode_go_node.py`, `test_opencode_models_endpoint.py`, `test_opencode_catalog.py`.

**Backend — modify:**
- `backend/app/config.py` — new `opencode_*` settings.
- `backend/app/db/models.py:29` — `CredentialType.opencode`.
- `backend/app/models/schemas.py:473,509` — `opencode` literal + `CredentialConfigOpenCode`.
- `backend/app/api/credentials.py` — masking group + config merge.
- `backend/app/services/codex_runner_service.py` — delegate to shared services (behavior-preserving).
- `backend/app/services/node_execution/registry.py` — register `opencodeGo`.
- `backend/app/main.py` — include the opencode_go router.
- `backend/app/services/workflow_dsl_prompt.py` — DSL node section + rule 23a entry.
- `backend/Dockerfile` — install the `opencode` binary.

**Frontend — new:**
- `frontend/src/lib/opencodeCatalog.ts` — fallback model list + variant options.
- `frontend/src/components/Panels/propertiesPanel/nodes/OpenCodeGoNodeProperties.vue` — node config UI + dynamic model dropdown.

**Frontend — modify:**
- `frontend/src/types/node.ts` — `opencodeGo` node definition.
- `frontend/src/types/credential.ts` — `opencode` type + `CredentialConfigOpenCode`.
- `frontend/src/lib/nodeIcons.ts` — icon + color class.
- `frontend/src/components/Nodes/BaseNode.vue`, `Panels/NodePanel.vue`, `Canvas/WorkflowCanvas.vue` — register node (mirror `codex`).
- `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts` — route `opencodeGo` to its component.
- `frontend/src/components/Panels/PropertiesPanel.vue` — render the new node component (thin wiring only).
- `frontend/src/components/Credentials/CredentialDialog.vue`, `Credentials/CredentialsPanel.vue` — `opencode` credential entry.
- `frontend/src/services/api.ts` — `fetchOpenCodeModels()`.
- Expression-dialog metadata + agent-autofill eligibility maps (wherever `codex` fields are declared).

**Docs — new/modify (via heym-documentation skill):**
- `frontend/src/docs/content/nodes/opencode-go.md` + `frontend/src/docs/manifest.ts`.
- `frontend/src/docs/content/reference/features.md`, `node-types.md`, `integrations.md`, `credentials.md`, `credentials-sharing.md`.

---

## Phase 1 — Backend foundation

### Task 1: Config settings

**Files:**
- Modify: `backend/app/config.py` (after the `codex_git_author_email` block, ~line 87)

- [ ] **Step 1: Add settings**

Insert after the `codex_git_author_email` field:

```python
    # OpenCode Go coding-agent node. OpenCode has no built-in OS sandbox, so it runs inside a
    # hardened, throwaway sibling container (fail-closed). Git is host-side; only `opencode run`
    # is containerized. Network egress is required for the model API, so unlike the python-tool
    # sandbox this allows egress — the GitHub token is never placed in the container.
    opencode_cli_command: str = Field(
        default="opencode", validation_alias="HEYM_OPENCODE_CLI_COMMAND"
    )
    opencode_workspace_dir: str = Field(
        default="./data/opencode-workspaces", validation_alias="HEYM_OPENCODE_WORKSPACE_DIR"
    )
    # "docker" (default, fail-closed): require a hardened container. "subprocess": run opencode on
    # the host (operator opt-in; weaker isolation).
    opencode_sandbox: str = Field(default="docker", validation_alias="HEYM_OPENCODE_SANDBOX")
    # Empty resolves to the backend's own running image (like the python tool sandbox).
    opencode_image: str = Field(default="", validation_alias="HEYM_OPENCODE_IMAGE")
    opencode_network: str = Field(default="bridge", validation_alias="HEYM_OPENCODE_NETWORK")
    opencode_memory: str = Field(default="2g", validation_alias="HEYM_OPENCODE_MEMORY")
    opencode_cpus: str = Field(default="2", validation_alias="HEYM_OPENCODE_CPUS")
    opencode_pids: str = Field(default="512", validation_alias="HEYM_OPENCODE_PIDS")
    opencode_zen_base_url: str = Field(
        default="https://opencode.ai/zen/go/v1", validation_alias="HEYM_OPENCODE_ZEN_BASE_URL"
    )
    opencode_git_author_name: str = Field(
        default="Heym OpenCode", validation_alias="HEYM_OPENCODE_GIT_AUTHOR_NAME"
    )
    opencode_git_author_email: str = Field(
        default="support@heym.run", validation_alias="HEYM_OPENCODE_GIT_AUTHOR_EMAIL"
    )
```

- [ ] **Step 2: Verify import**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "from app.config import settings; print(settings.opencode_zen_base_url, settings.opencode_sandbox)"`
Expected: `https://opencode.ai/zen/go/v1 docker`

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat(opencode): add OpenCode Go runner settings"
```

### Task 2: Credential type + migration

**Files:**
- Modify: `backend/app/db/models.py:29` (CredentialType enum)
- Modify: `backend/app/models/schemas.py:473` (Literal) and `:509` (config models)
- Create: `backend/alembic/versions/100_add_opencode_credential_type.py`

- [ ] **Step 1: Add enum value**

In `backend/app/db/models.py`, in `class CredentialType`, add after `clickhouse = "clickhouse"`:

```python
    opencode = "opencode"
```

- [ ] **Step 2: Add Pydantic config model + literal**

In `backend/app/models/schemas.py`, add after `CredentialConfigCodex` (line 509-510):

```python
class CredentialConfigOpenCode(BaseModel):
    api_key: str
    base_url: str | None = None
```

Then find the credential-type `Literal[...]` union that contains `"codex"` (near line 473) and add `"opencode"` to it.

- [ ] **Step 3: Create migration**

`backend/alembic/versions/100_add_opencode_credential_type.py`:

```python
"""add opencode credential type

Revision ID: 100_add_opencode_credential_type
Revises: 099_add_board_shares
Create Date: 2026-07-18 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "100_add_opencode_credential_type"
down_revision: Union[str, None] = "099_add_board_shares"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'opencode'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; downgrade is a no-op.
    pass
```

- [ ] **Step 4: Apply migration**

Run: `cd backend && docker-compose -f ../docker-compose.yml up -d postgres && uv run alembic upgrade head`
Expected: upgrade runs to `100_add_opencode_credential_type` without error.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/app/models/schemas.py backend/alembic/versions/100_add_opencode_credential_type.py
git commit -m "feat(opencode): add opencode credential type + migration"
```

### Task 3: Credential wiring (masking + merge)

**Files:**
- Modify: `backend/app/api/credentials.py` (masking group ~line 183; config merge for `base_url`)

- [ ] **Step 1: Add opencode to the api_key masking group**

In `get_masked_value`, add `CredentialType.opencode` to the tuple that includes `CredentialType.openai, google, github, custom, elevenlabs` (line 183-189).

- [ ] **Step 2: Ensure base_url merge for opencode**

Confirm the generic merge path at the end of `merge_credential_config` preserves `base_url` for unknown types (it copies `incoming_config`). If there is a `custom`/`github` branch that special-cases `base_url`, add an analogous branch for `opencode` that keeps `api_key` and optional `base_url`. Otherwise no change needed.

- [ ] **Step 3: Verify**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run python -c "from app.api.credentials import get_masked_value; from app.db.models import CredentialType; print(get_masked_value(CredentialType.opencode, {'api_key':'sk-abcdef123456'}))"`
Expected: a masked string (not the raw key).

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/credentials.py
git commit -m "feat(opencode): mask opencode credential api_key"
```

### Task 4: Model catalog + fallback (TDD)

**Files:**
- Create: `backend/app/services/opencode_catalog.py`
- Test: `backend/tests/test_opencode_catalog.py`

- [ ] **Step 1: Write failing test**

`backend/tests/test_opencode_catalog.py`:

```python
import unittest

from app.services.opencode_catalog import (
    OPENCODE_DEFAULT_MODEL,
    OPENCODE_MODEL_FALLBACK,
    normalize_opencode_models,
)


class TestOpenCodeCatalog(unittest.TestCase):
    def test_default_is_in_fallback(self):
        ids = [m["id"] for m in OPENCODE_MODEL_FALLBACK]
        self.assertIn(OPENCODE_DEFAULT_MODEL, ids)
        self.assertEqual(OPENCODE_DEFAULT_MODEL, "opencode/kimi-k3")

    def test_normalize_openai_style_payload(self):
        payload = {"object": "list", "data": [{"id": "kimi-k3"}, {"id": "deepseek-v4-pro"}]}
        models = normalize_opencode_models(payload)
        self.assertEqual(models[0]["id"], "opencode/kimi-k3")
        self.assertEqual(models[1]["id"], "opencode/deepseek-v4-pro")

    def test_normalize_skips_blank_and_dedupes(self):
        payload = {"data": [{"id": "kimi-k3"}, {"id": "kimi-k3"}, {"id": ""}, {"id": None}]}
        models = normalize_opencode_models(payload)
        self.assertEqual([m["id"] for m in models], ["opencode/kimi-k3"])

    def test_normalize_already_prefixed(self):
        payload = {"data": [{"id": "opencode/kimi-k3"}]}
        self.assertEqual(normalize_opencode_models(payload)[0]["id"], "opencode/kimi-k3")

    def test_normalize_bad_input_returns_empty(self):
        self.assertEqual(normalize_opencode_models({"data": "nope"}), [])
        self.assertEqual(normalize_opencode_models(None), [])
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_catalog.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement**

`backend/app/services/opencode_catalog.py`:

```python
"""OpenCode Go (zen) model catalog: hardcoded fallback + live-list normalization."""

from __future__ import annotations

# Small known-good set of Go-gateway models; used when the live /models fetch fails.
OPENCODE_MODEL_FALLBACK: tuple[dict[str, str], ...] = (
    {"id": "opencode/kimi-k3", "name": "Kimi K3"},
    {"id": "opencode/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
    {"id": "opencode/qwen3.7-max", "name": "Qwen3.7 Max"},
    {"id": "opencode/minimax-m3", "name": "MiniMax M3"},
)

OPENCODE_DEFAULT_MODEL = "opencode/kimi-k3"


def normalize_opencode_models(payload: object) -> list[dict[str, str]]:
    """Normalize an OpenAI-style {"data":[{"id": ...}]} payload to opencode/<id> entries."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    seen: set[str] = set()
    models: list[dict[str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("id")
        if not isinstance(raw, str) or not raw.strip():
            continue
        bare = raw.strip()
        model_id = bare if bare.startswith("opencode/") else f"opencode/{bare}"
        if model_id in seen:
            continue
        seen.add(model_id)
        name = entry.get("name")
        models.append(
            {"id": model_id, "name": name if isinstance(name, str) and name.strip() else bare}
        )
    return models
```

- [ ] **Step 4: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/opencode_catalog.py backend/tests/test_opencode_catalog.py
git commit -m "feat(opencode): model fallback catalog + normalization"
```

---

## Phase 2 — Shared coding-agent services (extract from Codex)

> Goal: move reusable git/workspace/publish logic out of `CodexRunnerService` into shared services, then refactor Codex to delegate. **Behavior must be preserved** — the existing Codex tests are the regression guard. Run them after each refactor step.

### Task 5: RepoWorkspaceService (extract, TDD)

**Files:**
- Create: `backend/app/services/coding_agent/__init__.py` (empty)
- Create: `backend/app/services/coding_agent/repo_workspace.py`
- Test: `backend/tests/test_repo_workspace_service.py`

- [ ] **Step 1: Write failing tests** (pure functions, no subprocess)

`backend/tests/test_repo_workspace_service.py`:

```python
import unittest

from app.services.coding_agent.repo_workspace import RepoWorkspaceService


class TestRepoWorkspaceService(unittest.TestCase):
    def setUp(self):
        self.svc = RepoWorkspaceService(workspace_root="/tmp/heym-test-ws")

    def test_clone_url_injects_token(self):
        url = self.svc.clone_url_with_token(
            "https://github.com/acme/repo.git", {"api_key": "ghp_secret"}
        )
        self.assertEqual(url, "https://x-access-token:ghp_secret@github.com/acme/repo.git")

    def test_clone_url_no_token_unchanged(self):
        url = self.svc.clone_url_with_token("https://github.com/acme/repo.git", {})
        self.assertEqual(url, "https://github.com/acme/repo.git")

    def test_clone_url_skips_when_userinfo_present(self):
        original = "https://user@github.com/acme/repo.git"
        self.assertEqual(self.svc.clone_url_with_token(original, {"api_key": "x"}), original)

    def test_parse_owner_repo(self):
        self.assertEqual(
            self.svc.parse_github_owner_repo("https://github.com/acme/repo.git"), ("acme", "repo")
        )

    def test_parse_owner_repo_rejects_short(self):
        with self.assertRaises(ValueError):
            self.svc.parse_github_owner_repo("https://github.com/acme")

    def test_mask_sensitive(self):
        self.assertEqual(self.svc.mask_sensitive("token=abc", ["abc"]), "token=[masked]")
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_repo_workspace_service.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement by moving methods from `codex_runner_service.py`**

Create `backend/app/services/coding_agent/__init__.py` (empty file).

Create `backend/app/services/coding_agent/repo_workspace.py` containing a `RepoWorkspaceService` whose methods are **moved verbatim** (renamed to public where noted) from `CodexRunnerService`:
- `__init__(self, workspace_root: str)` → `self.workspace_root = Path(workspace_root)`.
- `clone_url_with_token(repository_url, github_config)` ← `_clone_url_with_token` (static logic).
- `parse_github_owner_repo(repository_url)` ← `_parse_github_owner_repo`.
- `mask_sensitive(text, values)` ← `_mask_sensitive`.
- `safe_env()` ← `_safe_env`.
- `run_command(cmd, *, cwd, timeout_seconds=600, env=None, sensitive_values=None, cli_command_hint=None)` ← `_run_command` (drop the codex-specific "install @openai/codex" hint; accept a generic `cli_command_hint`).
- `git_output(cmd, workspace)` ← `_git_output`.
- `changed_files(workspace)` ← `_changed_files`.
- `git_diff(workspace)` → `self.git_output(["git", "diff", "--binary"], workspace)`.
- `exclude_runner_files(workspace, extra_paths: list[str])` ← `_exclude_runner_files`, generalized to accept the ignore lines to write (Codex passes `["/.codex-home/", "/.codex-output-schema.json"]`).
- `clone_branch(workspace, repository_url, github_config, branch, timeout_seconds)` ← `_clone_branch`.
- `cleanup_workspace(workspace_path, extra_dirs: list[str])` ← `cleanup_workspace`, where `extra_dirs` are sibling dirs to also remove (Codex passes `[str(codex_home_dir)]`).

Copy the exact bodies from `backend/app/services/codex_runner_service.py` (lines referenced in the spec), adapting `self.cli_command`/codex-specific hints to parameters.

- [ ] **Step 4: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_repo_workspace_service.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor CodexRunnerService to delegate**

In `backend/app/services/codex_runner_service.py`, instantiate `self.repo = RepoWorkspaceService(str(self.workspace_root))` in `__init__` and replace the moved methods' call sites with `self.repo.<method>(...)`. Keep Codex's own `_codex_home_dir`, `_exclude_runner_files` wrapper (calls `self.repo.exclude_runner_files(ws, ["/.codex-home/", "/.codex-output-schema.json"])`), and `cleanup_workspace` wrapper (calls `self.repo.cleanup_workspace(path, [str(self._codex_home_dir(path))])`). Do not change behavior.

- [ ] **Step 6: Run full Codex suite (regression guard)**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_codex_runner_service.py tests/test_codex_runner_auth.py tests/test_codex_node.py -v`
Expected: PASS (all existing Codex tests green).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/coding_agent/ backend/app/services/codex_runner_service.py backend/tests/test_repo_workspace_service.py
git commit -m "refactor(coding-agent): extract RepoWorkspaceService, Codex delegates"
```

### Task 6: GitPublishService (extract, TDD)

**Files:**
- Create: `backend/app/services/coding_agent/git_publish.py`
- Test: `backend/tests/test_git_publish_service.py`

- [ ] **Step 1: Write failing tests** (pure helpers + one publish path with mocked subprocess/GitHubService)

`backend/tests/test_git_publish_service.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from app.services.coding_agent.git_publish import GitPublishService, PublishRequest


class TestGitPublishHelpers(unittest.TestCase):
    def setUp(self):
        self.svc = GitPublishService(
            repo=MagicMock(), git_author_name="Heym OpenCode", git_author_email="support@heym.run"
        )

    def test_commit_title_prefers_pr_title(self):
        self.assertEqual(
            self.svc.commit_title(pr_title="Add feature", summary="ignored"), "Add feature"
        )

    def test_commit_title_falls_back_to_first_sentence(self):
        self.assertEqual(
            self.svc.commit_title(pr_title="", summary="Fix the bug. More detail."), "Fix the bug."
        )

    def test_inject_screenshot_markdown_appends_section(self):
        out = self.svc.inject_screenshot_markdown("Body", [("a.png", "http://x/a.png")])
        self.assertIn("## Screenshots", out)
        self.assertIn("![a.png](http://x/a.png)", out)

    def test_pr_number_from_url(self):
        self.assertEqual(self.svc.pr_number_from_url("https://github.com/a/b/pull/42"), 42)
        self.assertIsNone(self.svc.pr_number_from_url("https://github.com/a/b"))
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_git_publish_service.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement by moving publish logic from Codex**

Create `backend/app/services/coding_agent/git_publish.py`. Define:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.coding_agent.repo_workspace import RepoWorkspaceService


@dataclass(frozen=True)
class PublishRequest:
    repository_url: str
    base_branch: str
    branch_name: str
    publish_mode: str
    github_config: dict


@dataclass
class PublishResult:
    summary: str = ""
    validation: str = ""
    pull_request_title: str = ""
    pull_request_body: str = ""
    changed_files: list[str] | None = None
    pull_request_url: str | None = None
    pushed_branch: str = ""
```

Then a `GitPublishService(repo: RepoWorkspaceService, git_author_name: str, git_author_email: str)` with methods **moved from `CodexRunnerService`** (bodies verbatim, `self._run_command`→`self.repo.run_command`, `self._git_output`→`self.repo.git_output`, `self._parse_github_owner_repo`→`self.repo.parse_github_owner_repo`, `self._clone_url_with_token`→`self.repo.clone_url_with_token`, and `settings.codex_git_author_*`→`self.git_author_*`):
- `publish(workspace, request, result)` ← `_publish` (the 7-mode dispatch; the `_CODEX_REMOTE_PUBLISH_MODES` gate moves here as `REMOTE_PUBLISH_MODES`).
- `commit_changes`, `push_branch`, `current_branch` ← `_commit_changes`/`_push_branch`/`_current_branch`.
- `create_pr`, `open_pr_url_for_head` ← `_create_pr`/`_open_pr_url_for_head`.
- `discover_pr_screenshots`, `attach_pr_screenshots`, `ensure_pr_screenshot_release`, `release_asset_name`, `inject_screenshot_markdown`, `pr_number_from_url` ← the screenshot helpers (verbatim, plus the module-level `_PR_SCREENSHOT_*` constants move to this module).
- `commit_title`, `commit_body` ← `_commit_title`/`_commit_body`.

Move `CODEX_PUBLISH_MODES` → keep a shared `PUBLISH_MODES` frozenset here and re-export from `codex_runner_service` for back-compat (`from app.services.coding_agent.git_publish import PUBLISH_MODES as CODEX_PUBLISH_MODES`).

- [ ] **Step 4: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_git_publish_service.py -v`
Expected: PASS.

- [ ] **Step 5: Refactor CodexRunnerService.`_finalize_result`/`_publish` to delegate**

Replace Codex's `_publish`/publish helpers with a `GitPublishService` instance built in `__init__`:
`self.publisher = GitPublishService(self.repo, settings.codex_git_author_name, settings.codex_git_author_email)`. In `_finalize_result`, build a `PublishRequest` + copy result fields into/out of a `PublishResult`, or (simpler) have `publish()` accept the existing `CodexRunResult` duck-typed object. Choose the adapter that keeps `CodexRunResult` fields identical. Keep `CODEX_PUBLISH_MODES` importable from `codex_runner_service`.

- [ ] **Step 6: Run full Codex suite (regression guard)**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_codex_runner_service.py tests/test_codex_runner_auth.py tests/test_codex_node.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/coding_agent/git_publish.py backend/app/services/codex_runner_service.py backend/tests/test_git_publish_service.py
git commit -m "refactor(coding-agent): extract GitPublishService, Codex delegates"
```

---

## Phase 3 — OpenCode runner service

### Task 7: OpenCodeRunnerService — docker command + fail-closed (TDD)

**Files:**
- Create: `backend/app/services/opencode_runner_service.py`
- Test: `backend/tests/test_opencode_runner_service.py`

- [ ] **Step 1: Write failing tests (container command shape + fail-closed)**

`backend/tests/test_opencode_runner_service.py`:

```python
import unittest
from unittest.mock import patch

from app.services.opencode_runner_service import OpenCodeRunnerService


class TestOpenCodeDockerCommand(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_docker_command_is_hardened_with_egress(self):
        cmd = self.svc.build_docker_command(
            image="heym-backend:latest",
            name="heym-oc-abc",
            workspace="/tmp/heym-oc-ws/run1",
            config_dir="/tmp/heym-oc-ws/run1.oc-home",
        )
        joined = " ".join(cmd)
        self.assertIn("--rm", cmd)
        self.assertIn("--read-only", cmd)
        self.assertIn("ALL", cmd)  # --cap-drop ALL
        self.assertIn("no-new-privileges", joined)
        self.assertIn("--network", cmd)
        # egress allowed (NOT "none")
        idx = cmd.index("--network")
        self.assertEqual(cmd[idx + 1], "bridge")
        # workspace bind-mounted rw
        self.assertTrue(any(":/workspace" in a for a in cmd))
        # docker socket never mounted
        self.assertNotIn("/var/run/docker.sock", joined)

    def test_sandbox_fail_closed_when_docker_unavailable(self):
        with patch.object(self.svc, "_docker_available", return_value=False), patch.object(
            self.svc, "_resolve_image", return_value=None
        ):
            with self.assertRaises(ValueError) as ctx:
                self.svc._resolve_execution_mode()
            self.assertIn("Docker", str(ctx.exception))

    def test_subprocess_mode_opt_in(self):
        svc = OpenCodeRunnerService(workspace_root="/tmp/x", sandbox_mode="subprocess")
        self.assertEqual(svc._resolve_execution_mode(), "subprocess")
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_runner_service.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement the service skeleton + docker command + mode resolution**

`backend/app/services/opencode_runner_service.py` (core; parsing/auth added in Tasks 8-9):

```python
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.services.coding_agent.git_publish import GitPublishService, PublishRequest
from app.services.coding_agent.repo_workspace import RepoWorkspaceService
from app.services.opencode_catalog import OPENCODE_DEFAULT_MODEL

_LOCAL_ONLY_RULES = (
    "Apply ALL changes by editing files on disk in the current working directory. Do NOT run git; "
    "do NOT commit, push, or create branches; and do NOT use the GitHub API or any remote tool to "
    "modify the repository — Heym performs every git and GitHub operation after you finish. For "
    "UI/frontend visual changes, save at least one PNG screenshot under a gitignored path such as "
    "`frontend/.e2e-artifacts/`; Heym uploads those images onto the pull request afterward."
)


@dataclass(frozen=True)
class OpenCodeRunRequest:
    repository_url: str
    base_branch: str
    task_prompt: str
    branch_name: str
    publish_mode: str
    setup_command: str
    timeout_seconds: float
    api_key: str
    base_url: str
    github_config: dict
    model: str = ""
    variant: str = ""


@dataclass
class OpenCodeRunResult:
    status: str = "completed"
    summary: str = ""
    validation: str = ""
    pull_request_title: str = ""
    pull_request_body: str = ""
    diff: str = ""
    changed_files: list[str] = field(default_factory=list)
    workspace_path: str | None = None
    branch_name: str = ""
    pull_request_url: str | None = None
    pushed_branch: str = ""
    raw_events: list[dict] = field(default_factory=list)

    def to_output(self) -> dict:
        # No workspacePath in output: there is no resume path (lean HITL) and the handler cleans
        # up the workspace after building the result.
        output = {
            "status": self.status,
            "summary": self.summary,
            "validation": self.validation,
            "diff": self.diff,
            "changedFiles": self.changed_files,
            "branchName": self.branch_name,
            "pullRequestUrl": self.pull_request_url,
            "pushedBranch": self.pushed_branch,
        }
        return {k: v for k, v in output.items() if v not in (None, "", [])}


class OpenCodeRunnerService:
    """Run the OpenCode CLI inside a hardened container; git/publish stays host-side."""

    def __init__(
        self,
        cli_command: str | None = None,
        workspace_root: str | None = None,
        sandbox_mode: str | None = None,
    ) -> None:
        self.cli_command = cli_command or settings.opencode_cli_command
        self.workspace_root = Path(workspace_root or settings.opencode_workspace_dir)
        self.sandbox_mode = (sandbox_mode or settings.opencode_sandbox or "docker").strip().lower()
        self.repo = RepoWorkspaceService(str(self.workspace_root))
        self.publisher = GitPublishService(
            self.repo,
            settings.opencode_git_author_name,
            settings.opencode_git_author_email,
        )

    # --- execution mode / docker ---
    @staticmethod
    def _docker_available() -> bool:
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            return False

    def _resolve_image(self) -> str | None:
        override = settings.opencode_image.strip()
        if override:
            return override
        import socket

        try:
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{.Config.Image}}", socket.gethostname()],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            image = result.stdout.strip()
            if result.returncode == 0 and image:
                return image
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    def _resolve_execution_mode(self) -> str:
        if self.sandbox_mode == "subprocess":
            return "subprocess"
        if not self._docker_available() or not self._resolve_image():
            raise ValueError(
                "OpenCode Go requires a Docker sandbox but Docker or the runner image is "
                "unavailable. Install/enable Docker, set HEYM_OPENCODE_IMAGE, or set "
                "HEYM_OPENCODE_SANDBOX=subprocess to run on the host (weaker isolation)."
            )
        return "docker"

    def build_docker_command(
        self, *, image: str, name: str, workspace: str, config_dir: str
    ) -> list[str]:
        """Hardened, throwaway `docker run` for `opencode run`; egress allowed for the model API."""
        memory = settings.opencode_memory
        return [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--network",
            settings.opencode_network,  # egress required for model API (default "bridge")
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace",
            "--mount",
            f"type=bind,src={config_dir},dst=/oc-home",
            "--workdir",
            "/workspace",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            settings.opencode_pids,
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--cpus",
            settings.opencode_cpus,
            "--env",
            "HOME=/oc-home",
            "--env",
            "XDG_CONFIG_HOME=/oc-home/.config",
            "--env",
            "XDG_DATA_HOME=/oc-home/.local/share",
            "--entrypoint",
            self.cli_command,
            image,
        ]
```

Note: the container user is intentionally left as the image default so the bind-mounted `/workspace` (owned by the backend uid) stays writable; hardening comes from `--read-only` + `--cap-drop ALL` + `no-new-privileges` + `--network`-scoped egress + no docker socket. If the backend runs as non-root, that same uid owns the workspace and OpenCode writes fine.

- [ ] **Step 4: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_runner_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/opencode_runner_service.py backend/tests/test_opencode_runner_service.py
git commit -m "feat(opencode): runner skeleton with hardened docker command + fail-closed"
```

### Task 8: OpenCode auth/config generation (TDD)

**Files:**
- Modify: `backend/app/services/opencode_runner_service.py`
- Modify: `backend/tests/test_opencode_runner_service.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
import tempfile
from pathlib import Path as _Path


class TestOpenCodeAuthConfig(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_write_config_writes_auth_and_opencode_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = _Path(tmp)
            self.svc._write_opencode_config(
                home, api_key="sk-secret", base_url="https://opencode.ai/zen/go/v1",
                model="opencode/kimi-k3",
            )
            auth = json.loads((home / ".local" / "share" / "opencode" / "auth.json").read_text())
            self.assertEqual(auth["opencode"], {"type": "api", "key": "sk-secret"})
            cfg = json.loads((home / ".config" / "opencode" / "opencode.json").read_text())
            self.assertEqual(cfg["permission"]["edit"], "allow")
            self.assertEqual(cfg["permission"]["bash"], "allow")
            self.assertEqual(cfg["model"], "opencode/kimi-k3")
            self.assertEqual(
                cfg["provider"]["opencode"]["options"]["baseURL"], "https://opencode.ai/zen/go/v1"
            )
            self.assertEqual(cfg["provider"]["opencode"]["options"]["apiKey"], "sk-secret")

    def test_default_model_when_empty(self):
        self.assertEqual(self.svc._resolve_model(""), "opencode/kimi-k3")
        self.assertEqual(self.svc._resolve_model("opencode/deepseek-v4-pro"), "opencode/deepseek-v4-pro")
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_runner_service.py::TestOpenCodeAuthConfig -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `OpenCodeRunnerService`:

```python
    def _resolve_model(self, model: str) -> str:
        return model.strip() or OPENCODE_DEFAULT_MODEL

    def _write_opencode_config(
        self, home: Path, *, api_key: str, base_url: str, model: str
    ) -> None:
        data_dir = home / ".local" / "share" / "opencode"
        config_dir = home / ".config" / "opencode"
        data_dir.mkdir(parents=True, exist_ok=True)
        config_dir.mkdir(parents=True, exist_ok=True)
        auth_path = data_dir / "auth.json"
        auth_path.write_text(json.dumps({"opencode": {"type": "api", "key": api_key}}))
        auth_path.chmod(0o600)
        config = {
            "$schema": "https://opencode.ai/config.json",
            "model": model,
            "permission": {"edit": "allow", "bash": "allow", "webfetch": "allow"},
            "provider": {
                "opencode": {
                    "options": {
                        "baseURL": base_url or settings.opencode_zen_base_url,
                        "apiKey": api_key,
                    }
                }
            },
        }
        config_path = config_dir / "opencode.json"
        config_path.write_text(json.dumps(config))
        config_path.chmod(0o600)
```

- [ ] **Step 4: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_runner_service.py::TestOpenCodeAuthConfig -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/opencode_runner_service.py backend/tests/test_opencode_runner_service.py
git commit -m "feat(opencode): auth.json + opencode.json generation"
```

### Task 9: JSON-event parsing + run orchestration (TDD)

**Files:**
- Modify: `backend/app/services/opencode_runner_service.py`
- Modify: `backend/tests/test_opencode_runner_service.py`

- [ ] **Step 1: Add failing tests for the parser**

Append:

```python
class TestOpenCodeParser(unittest.TestCase):
    def setUp(self):
        self.svc = OpenCodeRunnerService(workspace_root="/tmp/heym-oc-ws")

    def test_parse_extracts_last_assistant_text(self):
        stdout = "\n".join([
            json.dumps({"type": "message.updated", "text": "thinking"}),
            json.dumps({"type": "message", "role": "assistant", "text": "Implemented the change."}),
        ])
        result = self.svc.parse_events(stdout)
        self.assertEqual(result.summary, "Implemented the change.")
        self.assertEqual(result.status, "completed")

    def test_parse_tolerates_non_json_lines(self):
        stdout = "not json\n" + json.dumps({"role": "assistant", "text": "Done."})
        self.assertEqual(self.svc.parse_events(stdout).summary, "Done.")

    def test_parse_empty_gives_default_summary(self):
        result = self.svc.parse_events("")
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.summary)
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_runner_service.py::TestOpenCodeParser -v`
Expected: FAIL.

- [ ] **Step 3: Implement parser + orchestration**

Add to `OpenCodeRunnerService`. The parser scans JSONL events (from `opencode run --format json`) for the last assistant text; be defensive about event shapes (assistant `text`, or `part.text`, or a `message` object). Then add `run_task`:

```python
    def parse_events(self, stdout: str) -> OpenCodeRunResult:
        events: list[dict] = []
        summary = ""
        for raw in (stdout or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(event)
            text = self._event_assistant_text(event)
            if text:
                summary = text
        if not summary:
            summary = "OpenCode completed without a final assistant message."
        return OpenCodeRunResult(status="completed", summary=summary, raw_events=events)

    @staticmethod
    def _event_assistant_text(event: dict) -> str:
        role = str(event.get("role") or (event.get("message") or {}).get("role") or "")
        if role and role != "assistant":
            return ""
        for key in ("text", "content"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        part = event.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            return part["text"].strip()
        return ""

    def run_task(self, request: OpenCodeRunRequest) -> OpenCodeRunResult:
        mode = self._resolve_execution_mode()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = (self.workspace_root / str(uuid.uuid4())).resolve()
        home = Path(f"{workspace}.oc-home")
        home.mkdir(parents=True, exist_ok=True)
        try:
            # Host-side clone (update_existing_pr tries the PR branch first, else base).
            branch = request.branch_name if request.publish_mode == "update_existing_pr" else request.base_branch
            try:
                self.repo.clone_branch(
                    workspace, request.repository_url, request.github_config, branch,
                    request.timeout_seconds,
                )
            except ValueError:
                self.repo.clone_branch(
                    workspace, request.repository_url, request.github_config,
                    request.base_branch, request.timeout_seconds,
                )
            self.repo.exclude_runner_files(workspace, [])  # home is a sibling dir, not in repo
            if request.setup_command.strip():
                self.repo.run_command(
                    ["/bin/sh", "-lc", request.setup_command],
                    cwd=workspace,
                    timeout_seconds=min(request.timeout_seconds, 600),
                )
            model = self._resolve_model(request.model)
            self._write_opencode_config(
                home, api_key=request.api_key, base_url=request.base_url, model=model
            )
            stdout = self._exec_opencode(mode, workspace, home, request, model)
            result = self.parse_events(stdout)
            result.workspace_path = str(workspace)
            result.branch_name = request.branch_name
            result.diff = self.repo.git_diff(workspace)
            result.changed_files = self.repo.changed_files(workspace)
            if result.status == "completed":
                self.publisher.publish(
                    workspace,
                    PublishRequest(
                        repository_url=request.repository_url,
                        base_branch=request.base_branch,
                        branch_name=request.branch_name,
                        publish_mode=request.publish_mode,
                        github_config=request.github_config,
                    ),
                    result,
                )
            return result
        finally:
            pass  # workspace cleanup handled by the node handler after artifact storage

    def _exec_opencode(
        self, mode: str, workspace: Path, home: Path, request: OpenCodeRunRequest, model: str
    ) -> str:
        prompt = f"{_LOCAL_ONLY_RULES}\n\nTask:\n{request.task_prompt}"
        run_args = ["run", "--format", "json", "--model", model, "--agent", "build"]
        if request.variant.strip():
            run_args.extend(["--variant", request.variant.strip()])
        run_args.append(prompt)
        if mode == "subprocess":
            env = self.repo.safe_env()
            env["HOME"] = str(home)
            env["XDG_CONFIG_HOME"] = str(home / ".config")
            env["XDG_DATA_HOME"] = str(home / ".local" / "share")
            cmd = [self.cli_command, *run_args]
            cwd = workspace
        else:
            image = self._resolve_image()
            name = f"heym-opencode-{uuid.uuid4().hex}"
            cmd = self.build_docker_command(
                image=image, name=name, workspace=str(workspace), config_dir=str(home)
            ) + run_args
            env = self.repo.safe_env()
            cwd = None
        try:
            completed = subprocess.run(
                cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=request.timeout_seconds, check=False,
            )
        except FileNotFoundError as exc:
            raise ValueError("OpenCode CLI/docker not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"OpenCode timed out after {request.timeout_seconds:.0f} seconds"
            ) from exc
        if completed.returncode != 0:
            detail = self.repo.mask_sensitive(
                completed.stderr or completed.stdout or "OpenCode exec failed", [request.api_key]
            )
            raise ValueError(detail)
        return completed.stdout

    def cleanup_workspace(self, workspace_path: str | None) -> None:
        if not workspace_path:
            return
        self.repo.cleanup_workspace(workspace_path, [f"{workspace_path}.oc-home"])
```

Note: when running in docker, `opencode run` operates on `/workspace` inside the container (the bind mount), and the resulting file edits land in the host `workspace` dir; the host then computes the diff and publishes. `--dir` is unnecessary because `--workdir /workspace` is set.

- [ ] **Step 4: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_runner_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/opencode_runner_service.py backend/tests/test_opencode_runner_service.py
git commit -m "feat(opencode): event parsing + run orchestration"
```

---

## Phase 4 — Node handler + registry

### Task 10: opencode_go node handler (TDD)

**Files:**
- Create: `backend/app/services/node_execution/nodes/opencode_go_node.py`
- Modify: `backend/app/services/node_execution/registry.py`
- Test: `backend/tests/test_opencode_go_node.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/test_opencode_go_node.py`:

```python
import unittest
from unittest.mock import MagicMock, patch

from app.services.node_execution.base import NodeExecutionContext


def _ctx(node_data, inputs=None):
    executor = MagicMock()
    executor.evaluate_nonempty_message_template.side_effect = lambda v, *_a, **_k: v
    executor.evaluate_message_template.side_effect = lambda v, *_a, **_k: v
    executor.execution_id = "exec1234abcd"
    ctx = NodeExecutionContext(
        executor=executor,
        node_id="oc_1",
        node_type="opencodeGo",
        node_label="opencodeFix",
        node_data=node_data,
        inputs=inputs or {"text": "do the thing"},
        start_time=0.0,
    )
    return ctx, executor


class TestOpenCodeGoNode(unittest.TestCase):
    def test_missing_credential_raises(self):
        from app.services.node_execution.nodes import opencode_go_node

        ctx, _ = _ctx({"repositoryUrl": "https://github.com/a/b", "githubCredentialId": "gh"})
        with self.assertRaises(ValueError):
            opencode_go_node.execute(ctx)

    def test_missing_repo_url_raises(self):
        from app.services.node_execution.nodes import opencode_go_node

        with patch.object(opencode_go_node, "_load_credentials",
                          return_value=({"api_key": "sk", "base_url": ""}, {"api_key": "gh"})):
            ctx, _ = _ctx({"credentialId": "oc", "githubCredentialId": "gh", "repositoryUrl": ""})
            with self.assertRaises(ValueError):
                opencode_go_node.execute(ctx)

    def test_completed_run_returns_output(self):
        from app.services.node_execution.nodes import opencode_go_node
        from app.services.opencode_runner_service import OpenCodeRunResult

        result = OpenCodeRunResult(status="completed", summary="done", branch_name="opencode/x")
        with patch.object(opencode_go_node, "_load_credentials",
                          return_value=({"api_key": "sk", "base_url": ""}, {"api_key": "gh"})), \
             patch("app.services.opencode_runner_service.OpenCodeRunnerService.run_task",
                   return_value=result):
            ctx, _ = _ctx({
                "credentialId": "oc", "githubCredentialId": "gh",
                "repositoryUrl": "https://github.com/a/b", "taskPrompt": "$input.text",
                "publishMode": "diff_only",
            })
            output = opencode_go_node.execute(ctx)
            self.assertEqual(output["status"], "completed")
            self.assertEqual(output["summary"], "done")
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_go_node.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement the handler**

`backend/app/services/node_execution/nodes/opencode_go_node.py` — mirror `codex_node.py` minus the resume/needs_input path. Reuse the `_store_patch_artifact` helper (copy it verbatim from `codex_node.py`, renaming metadata `kind` to `opencode_patch`). Key differences:
- `_load_credentials` validates `CredentialType.opencode` (returns `{api_key, base_url}`) + `CredentialType.github`. Require `api_key`.
- Resolve fields: `repositoryUrl` (req), `baseBranch` (default `main`), `taskPrompt` (default `$input.text`, req), `branchName` (default `opencode/<exec8>`, sanitized like `_resolve_branch_name`), `publishMode` (validate against `PUBLISH_MODES`), `setupCommand`, `timeoutSeconds` (`_coerce_timeout`), `opencodeModel`, `opencodeVariant`.
- Build `OpenCodeRunRequest`, call `OpenCodeRunnerService().run_task(...)`.
- On `patch_artifact`, store the diff via `_store_patch_artifact` and set `output["patchUrl"]`.
- Return `result.to_output()` with `output["status"] = "completed"`.

```python
from __future__ import annotations

import re
import time

from app.services.coding_agent.git_publish import PUBLISH_MODES
from app.services.node_execution.base import NodeExecutionContext
from app.services.opencode_runner_service import OpenCodeRunnerService, OpenCodeRunRequest


def execute(ctx: NodeExecutionContext) -> object:
    self = ctx.executor
    node_data = ctx.node_data
    inputs = ctx.inputs
    node_id = ctx.node_id

    opencode_config, github_config = _load_credentials(self, node_data)
    repository_url = self.evaluate_nonempty_message_template(
        str(node_data.get("repositoryUrl") or ""), inputs, node_id
    ).strip()
    if not repository_url:
        raise ValueError("OpenCode Go node requires a repository URL")
    base_branch = self.evaluate_nonempty_message_template(
        str(node_data.get("baseBranch") or "main"), inputs, node_id
    ).strip() or "main"
    task_prompt = self.evaluate_nonempty_message_template(
        str(node_data.get("taskPrompt") or "$input.text"), inputs, node_id
    ).strip()
    if not task_prompt:
        raise ValueError("OpenCode Go node requires a task prompt")
    publish_mode = str(node_data.get("publishMode") or "diff_only").strip()
    if publish_mode not in PUBLISH_MODES:
        publish_mode = "diff_only"
    setup_command = self.evaluate_nonempty_message_template(
        str(node_data.get("setupCommand") or ""), inputs, node_id
    ).strip()
    branch_name = _resolve_branch_name(self, node_data, inputs, node_id)
    model = self.evaluate_nonempty_message_template(
        str(node_data.get("opencodeModel") or ""), inputs, node_id
    ).strip()
    variant = str(node_data.get("opencodeVariant") or "").strip()
    timeout_seconds = _coerce_timeout(node_data.get("timeoutSeconds"))

    runner = OpenCodeRunnerService()
    result = runner.run_task(
        OpenCodeRunRequest(
            repository_url=repository_url,
            base_branch=base_branch,
            task_prompt=task_prompt,
            branch_name=branch_name,
            publish_mode=publish_mode,
            setup_command=setup_command,
            timeout_seconds=timeout_seconds,
            api_key=str(opencode_config.get("api_key") or ""),
            base_url=str(opencode_config.get("base_url") or ""),
            github_config=github_config,
            model=model,
            variant=variant,
        )
    )
    output = result.to_output()
    if publish_mode == "patch_artifact":
        patch_url = _store_patch_artifact(self, node_id, ctx.node_label, result.diff)
        if patch_url:
            output["patchUrl"] = patch_url
    output["status"] = "completed"
    # No resume path — reclaim the workspace + sibling opencode home now that diff/patch are captured.
    runner.cleanup_workspace(result.workspace_path)
    return output
```

Plus `_load_credentials`, `_resolve_branch_name` (using `opencode/` prefix), `_coerce_timeout`, and `_store_patch_artifact` (copied from codex_node, `kind="opencode_patch"`). Reference `backend/app/services/node_execution/nodes/codex_node.py:161-284` for the exact helper bodies.

- [ ] **Step 4: Register the handler**

In `backend/app/services/node_execution/registry.py`, add to `_HANDLER_MODULES` (alphabetical near `output`):

```python
    "opencodeGo": "opencode_go_node",
```

- [ ] **Step 5: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_go_node.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/node_execution/nodes/opencode_go_node.py backend/app/services/node_execution/registry.py backend/tests/test_opencode_go_node.py
git commit -m "feat(opencode): opencodeGo node handler + registry"
```

---

## Phase 5 — Models API endpoint

### Task 11: GET /api/opencode-go/models (TDD)

**Files:**
- Create: `backend/app/api/opencode_go.py`
- Modify: `backend/app/main.py` (include router)
- Test: `backend/tests/test_opencode_models_endpoint.py`

- [ ] **Step 1: Write failing test**

`backend/tests/test_opencode_models_endpoint.py`:

```python
import unittest
from unittest.mock import AsyncMock, patch

from app.services.opencode_models import fetch_opencode_models


class TestFetchOpenCodeModels(unittest.IsolatedAsyncioTestCase):
    async def test_live_success(self):
        payload = {"object": "list", "data": [{"id": "kimi-k3"}, {"id": "deepseek-v4-pro"}]}
        with patch("app.services.opencode_models._get_json", new=AsyncMock(return_value=payload)):
            models, source = await fetch_opencode_models(base_url="https://opencode.ai/zen/go/v1")
        self.assertEqual(source, "live")
        self.assertEqual(models[0]["id"], "opencode/kimi-k3")

    async def test_fallback_on_error(self):
        with patch("app.services.opencode_models._get_json", new=AsyncMock(side_effect=RuntimeError)):
            models, source = await fetch_opencode_models(base_url="https://opencode.ai/zen/go/v1")
        self.assertEqual(source, "fallback")
        self.assertTrue(any(m["id"] == "opencode/kimi-k3" for m in models))

    async def test_fallback_on_empty(self):
        with patch("app.services.opencode_models._get_json", new=AsyncMock(return_value={"data": []})):
            models, source = await fetch_opencode_models(base_url="https://opencode.ai/zen/go/v1")
        self.assertEqual(source, "fallback")
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_models_endpoint.py -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implement the fetch service + endpoint**

Create `backend/app/services/opencode_models.py`:

```python
from __future__ import annotations

import time

import httpx

from app.config import settings
from app.services.opencode_catalog import OPENCODE_MODEL_FALLBACK, normalize_opencode_models

_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_TTL_SECONDS = 600


async def _get_json(url: str) -> object:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def fetch_opencode_models(
    *, base_url: str | None = None
) -> tuple[list[dict[str, str]], str]:
    base = (base_url or settings.opencode_zen_base_url).rstrip("/")
    cached = _CACHE.get(base)
    if cached and (time.time() - cached[0]) < _TTL_SECONDS:
        return cached[1], "live"
    try:
        payload = await _get_json(f"{base}/models")
        models = normalize_opencode_models(payload)
        if models:
            _CACHE[base] = (time.time(), models)
            return models, "live"
    except Exception:
        pass
    return [dict(m) for m in OPENCODE_MODEL_FALLBACK], "fallback"
```

Create `backend/app/api/opencode_go.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.db.models import User
from app.services.opencode_models import fetch_opencode_models

router = APIRouter(prefix="/api/opencode-go", tags=["opencode-go"])


@router.get("/models")
async def list_opencode_models(
    base_url: str | None = Query(default=None),
    _user: User = Depends(get_current_user),
) -> dict:
    models, source = await fetch_opencode_models(base_url=base_url)
    return {"models": models, "source": source}
```

In `backend/app/main.py`, import and include the router alongside the other routers:

```python
from app.api import opencode_go
app.include_router(opencode_go.router)
```

(Match the exact include pattern already used in `main.py`.)

- [ ] **Step 4: Run — expect pass**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_opencode_models_endpoint.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/opencode_models.py backend/app/api/opencode_go.py backend/app/main.py backend/tests/test_opencode_models_endpoint.py
git commit -m "feat(opencode): GET /api/opencode-go/models with fallback"
```

---

## Phase 6 — DSL

### Task 12: Workflow DSL node section + rule 23a

**Files:**
- Modify: `backend/app/services/workflow_dsl_prompt.py`

- [ ] **Step 1: Add the node section**

After the Codex node section (ends ~line 4295), add a new numbered section:

```
### 41. opencodeGo (OpenCode Go Coding Agent)
- **Type**: `opencodeGo`
- **Purpose**: Run a coding task against a Git repository using the OpenCode CLI inside Heym's
  hardened, isolated Docker sandbox (git/GitHub operations are performed by Heym, not OpenCode).
- **Inputs**: 1 | **Outputs**: 1
- **Fields**:
  - `credentialId`: UUID of an owned `opencode` credential (OpenCode Go gateway API key)
  - `githubCredentialId`: UUID of an owned `github` credential used for clone/commit/push/PR
  - `repositoryUrl`: HTTPS Git URL (expression-capable), required
  - `baseBranch` (default `main`): branch to clone and target
  - `taskPrompt` (default `$input.text`): the coding task, required
  - `branchName` (default `opencode/$executionId`): working branch for PR/commit modes
  - `publishMode` (default `diff_only`): `diff_only`, `draft_pr`, `open_pr`, `commit_push`,
    `direct_commit`, `update_existing_pr`, `patch_artifact`
  - `setupCommand`: optional repository setup command before OpenCode runs
  - `opencodeModel`: OpenCode Go model id, e.g. `opencode/kimi-k3`, `opencode/deepseek-v4-pro`;
    empty uses the runner default (`opencode/kimi-k3`)
  - `opencodeVariant`: optional model reasoning variant passed to `opencode run --variant`
  - `timeoutSeconds` (default 3600)
- **As an agent tool**: The OpenCode Go node can be attached to an agent's `tool-input` handle; the
  agent supplies `taskPrompt` (and optionally `repositoryUrl`).
- **Output**: `{status:"completed", summary, validation, diff, changedFiles, branchName,
  pullRequestUrl?, pushedBranch?}`.
```

Then add a minimal example workflow block (mirror the Codex example, node type `opencodeGo`, credential placeholders `opencode-credential-uuid` / `github-credential-uuid`, no `question` branch).

- [ ] **Step 2: Add to credential rule 23a**

In the rule 23a list of integration node types (line ~4437), add `opencodeGo` and `opencode` to the enumerated applies-to list and add the placeholder `opencode-credential-uuid`.

- [ ] **Step 3: Verify the heymweb sync guard still passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/ -k "dsl_prompt or workflow_dsl or convert_sync" -v`
Expected: PASS (no diff regression in the synced-prompt guard).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/workflow_dsl_prompt.py
git commit -m "feat(opencode): DSL node section + credential rule"
```

---

## Phase 7 — Frontend

### Task 13: Types, catalog, icon, node registration

**Files:**
- Modify: `frontend/src/types/credential.ts`, `frontend/src/types/node.ts`, `frontend/src/lib/nodeIcons.ts`
- Create: `frontend/src/lib/opencodeCatalog.ts`
- Modify: `frontend/src/components/Nodes/BaseNode.vue`, `Panels/NodePanel.vue`, `Canvas/WorkflowCanvas.vue`

- [ ] **Step 1: credential.ts**

Add `"opencode"` to the credential-type union (near `"codex"`, line ~3) and:

```typescript
export interface CredentialConfigOpenCode {
  api_key: string;
  base_url?: string;
}
```

- [ ] **Step 2: opencodeCatalog.ts**

```typescript
/** OpenCode Go (zen) fallback model catalog + reasoning variants. */

export const OPENCODE_MODEL_FALLBACK = [
  { id: "opencode/kimi-k3", name: "Kimi K3" },
  { id: "opencode/deepseek-v4-pro", name: "DeepSeek V4 Pro" },
  { id: "opencode/qwen3.7-max", name: "Qwen3.7 Max" },
  { id: "opencode/minimax-m3", name: "MiniMax M3" },
] as const;

export const OPENCODE_DEFAULT_MODEL = "opencode/kimi-k3";

export const OPENCODE_VARIANT_OPTIONS = [
  { value: "", label: "Default" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
] as const;
```

- [ ] **Step 3: node.ts**

Add after the `codex` block (line 193):

```typescript
  opencodeGo: {
    type: "opencodeGo",
    label: "OpenCode Go",
    description: "Run OpenCode Go coding tasks in a repository (isolated container)",
    color: "node-opencode",
    icon: "Terminal",
    inputs: 1,
    outputs: 1,
    defaultData: {
      label: "opencodeGo",
      credentialId: "",
      githubCredentialId: "",
      repositoryUrl: "",
      baseBranch: "main",
      taskPrompt: "$input.text",
      publishMode: "diff_only",
      branchName: "opencode/$executionId",
      timeoutSeconds: 3600,
      setupCommand: "",
      opencodeModel: "",
      opencodeVariant: "",
    },
  },
```

- [ ] **Step 4: nodeIcons.ts**

Add `opencodeGo: Terminal,` (line ~56) and `opencodeGo: "text-node-opencode",` (line ~115). If a distinct color token is desired, add `node-opencode` / `text-node-opencode` to the Tailwind/theme config mirroring `node-codex`; otherwise reuse `node-codex`/`text-node-codex`.

- [ ] **Step 5: Register the node in canvas/panel**

In `BaseNode.vue`, `NodePanel.vue`, `WorkflowCanvas.vue`, add `opencodeGo` everywhere `codex` is referenced for static node registration/category/handles (grep each file for `codex` and mirror, minus any `question`-handle branch — the OpenCode node has a single output).

- [ ] **Step 6: Verify**

Run: `cd frontend && bun run typecheck`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/credential.ts frontend/src/types/node.ts frontend/src/lib/nodeIcons.ts frontend/src/lib/opencodeCatalog.ts frontend/src/components/Nodes/BaseNode.vue frontend/src/components/Panels/NodePanel.vue frontend/src/components/Canvas/WorkflowCanvas.vue
git commit -m "feat(opencode): frontend node type, credential type, catalog, icon"
```

### Task 14: Properties panel + dynamic model dropdown

**Files:**
- Create: `frontend/src/components/Panels/propertiesPanel/nodes/OpenCodeGoNodeProperties.vue`
- Modify: `frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts`, `frontend/src/components/Panels/PropertiesPanel.vue`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: api.ts fetch method**

Add:

```typescript
export async function fetchOpenCodeModels(
  baseUrl?: string,
): Promise<{ models: { id: string; name: string }[]; source: string }> {
  const params = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : "";
  const { data } = await apiClient.get(`/api/opencode-go/models${params}`);
  return data;
}
```

(Match the existing `apiClient` import/usage pattern in `api.ts`.)

- [ ] **Step 2: OpenCodeGoNodeProperties.vue**

Create the component by adapting `frontend/src/components/Panels/propertiesPanel/nodes/CodexNodeProperties.vue`:
- Same fields (credential picker filtered to `opencode` type, github credential picker, repositoryUrl, baseBranch, taskPrompt, branchName, publishMode select, setupCommand, timeoutSeconds).
- Replace the `codexModel`/`codexReasoningEffort` inputs with:
  - a **searchable model dropdown** bound to `opencodeModel`, populated via `fetchOpenCodeModels()` on mount, seeded with `OPENCODE_MODEL_FALLBACK` from `opencodeCatalog.ts`, and **falling back to that list on request error** (show a small "using fallback list" hint when `source === "fallback"` or the request throws). Reuse the existing searchable-select component used by the canvas AI model dropdowns (the one added in commit `2d8c4044`; grep `frontend/src` for the searchable model select component and reuse it).
  - a `opencodeVariant` select bound to `OPENCODE_VARIANT_OPTIONS`.
- Emit `update:data` the same way `CodexNodeProperties.vue` does.

- [ ] **Step 3: Wire it in**

In `usePropertiesPanelController.ts` and `PropertiesPanel.vue`, route `selectedNode.type === "opencodeGo"` to `OpenCodeGoNodeProperties` exactly as `codex` → `CodexNodeProperties` is wired (thin wiring; keep node-specific logic in the component per the PropertiesPanel modularity rule).

- [ ] **Step 4: Verify**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Panels/propertiesPanel/nodes/OpenCodeGoNodeProperties.vue frontend/src/components/Panels/propertiesPanel/usePropertiesPanelController.ts frontend/src/components/Panels/PropertiesPanel.vue frontend/src/services/api.ts
git commit -m "feat(opencode): properties panel with dynamic model dropdown + fallback"
```

### Task 15: Credential dialog + expression/autofill metadata

**Files:**
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue`, `Credentials/CredentialsPanel.vue`
- Modify: expression-dialog metadata + agent-autofill eligibility maps (grep for where `codex` fields are declared)

- [ ] **Step 1: Credential dialog**

Add an `opencode` credential option (label "OpenCode Go") with an `api_key` field (required) and an optional `base_url` field, mirroring how `codex`/`github` credentials appear in `CredentialDialog.vue` and `CredentialsPanel.vue`.

- [ ] **Step 2: Expression-dialog metadata**

Wherever node fields are registered for the expression dialog `1/n` navigation and dynamic fill (grep `frontend/src` for `codexModel` / `repositoryUrl` field metadata), add the `opencodeGo` fields (`repositoryUrl`, `baseBranch`, `taskPrompt`, `branchName`, `setupCommand`, `opencodeModel`) as expression-capable.

- [ ] **Step 3: Agent-autofill eligibility**

Wherever agent tool-field autofill eligibility is declared for `codex` (grep for the agent autofill field map), add `opencodeGo` with its autofillable fields (`taskPrompt`, `repositoryUrl`, `baseBranch`) so clicking the agent icon can populate them.

- [ ] **Step 4: Verify**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Credentials/ frontend/src
git commit -m "feat(opencode): credential dialog + expression/autofill metadata"
```

---

## Phase 8 — Docs

### Task 16: Documentation (heym-documentation skill)

**Files:**
- Create: `frontend/src/docs/content/nodes/opencode-go.md`
- Modify: `frontend/src/docs/manifest.ts`, `frontend/src/docs/content/reference/features.md`, `node-types.md`, `integrations.md`, `credentials.md`, `credentials-sharing.md`

- [ ] **Step 1: Invoke the heym-documentation skill**

Use the `heym-documentation` skill to author the docs (per repo policy). Provide it the node fields, publish modes, the `opencode` credential (api_key + optional base_url), the isolated-container behavior, and the dynamic model list.

- [ ] **Step 2: Node page + manifest**

Create `frontend/src/docs/content/nodes/opencode-go.md` (mirror `nodes/*` for Codex) and register it in `frontend/src/docs/manifest.ts`.

- [ ] **Step 3: Reference docs**

Update `reference/features.md` (per-node section + the node-types summary list), `node-types.md`, and the credential-backed pages `integrations.md`, `credentials.md`, `credentials-sharing.md` to include the OpenCode Go node + `opencode` credential.

- [ ] **Step 4: Verify docs build**

Run: `cd frontend && bun run typecheck` (and `bun run build` if docs are compiled).
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/docs
git commit -m "docs(opencode): OpenCode Go node + credential documentation"
```

---

## Phase 9 — Dockerfile + full verification

### Task 17: Install OpenCode binary in the backend image

**Files:**
- Modify: `backend/Dockerfile`

- [ ] **Step 1: Add the opencode install**

Add a step that installs the `opencode` Go binary onto PATH in the backend image (so the sibling container has it). Use the official install script pinned to a version, e.g.:

```dockerfile
# OpenCode CLI (Go) for the opencodeGo node's sandboxed runner.
ARG OPENCODE_VERSION=latest
RUN curl -fsSL https://opencode.ai/install | VERSION="${OPENCODE_VERSION}" bash \
    && ln -sf /root/.opencode/bin/opencode /usr/local/bin/opencode \
    && opencode --version
```

Adjust the install path/symlink to match the actual installer output and the image's user model (verify `opencode --version` succeeds during build). If the base image lacks `curl`/`unzip`, add them to the existing apt/apk install step.

- [ ] **Step 2: Build the image**

Run: `docker build -t heym-backend:opencode-test backend`
Expected: build succeeds and the `opencode --version` line prints a version.

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile
git commit -m "build(opencode): install OpenCode CLI in backend image"
```

### Task 18: Full verification

- [ ] **Step 1: Backend full suite**

Run: `SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: ruff format clean, ruff check clean, frontend lint+typecheck clean, backend tests PASS (including all new + existing Codex tests).

- [ ] **Step 2: Manual smoke (optional, requires Docker + a real OpenCode Go key)**

Create an `opencode` credential + `github` credential, add an `opencodeGo` node with `publishMode: diff_only`, run a trivial task against a scratch repo, confirm the node returns a `diff`/`summary` and that the container ran (`docker ps -a` shows a removed `heym-opencode-*`).

- [ ] **Step 3: Commit any formatting-only diffs**

```bash
git add -A && git commit -m "chore(opencode): formatting" || true
```

- [ ] **Step 4: Report completion** (do not push — repo rule: never push without explicit approval).

---

## Self-Review Notes

- **Spec coverage:** credential (T2/T3/T13/T15), optional-key → required-key (T2 model requires `api_key`; handler T10 requires it), dynamic models + fallback (T4/T11/T14), hardened fail-closed container (T7), egress + no-token-in-container (T7/T9), shared extraction (T5/T6), publish modes (via shared GitPublishService; handler validates `PUBLISH_MODES`), agent-tool + expression metadata (T15), DSL (T12), docs (T16), Dockerfile (T17), tests each phase.
- **Lean HITL:** no `needs_input`/resume, no `question` handle, no followups table — reflected in T10 (no pending branch) and T13 (single output).
- **Regression guard:** existing Codex tests run after T5 and T6.
- **No push:** final step stops at reporting; pushing requires explicit user approval (repo rule).
