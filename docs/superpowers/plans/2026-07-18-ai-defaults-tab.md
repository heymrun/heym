# AI Defaults Settings Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an "AI Defaults" user-settings tab that (1) sets a preferred LLM credential+model used as the default across every AI surface, and (2) shows Codex coding-package usage as horizontal percentage bars (OpenCode listed as "usage unavailable").

**Architecture:** Two new nullable user columns (`preferred_credential_id`, `preferred_model`) reused through the existing `/auth/me` update path. A shared frontend composable `useAiDefaults` centralizes the "saved > preferred > first credential" selection rule that each AI surface adopts. Codex usage comes from a dedicated backend probe that reads `x-codex-*` response headers from a minimal `/backend-api/codex/responses` call, cached 60s, exposed at `GET /api/credentials/{id}/codex-usage`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic (backend); Vue 3 `<script setup>` + TypeScript + Pinia (frontend); httpx for the Codex probe; pytest + Playwright for tests.

**Spec:** `docs/superpowers/specs/2026-07-18-ai-defaults-tab-design.md`

---

## File Structure

**Backend**
- `backend/alembic/versions/101_add_user_preferred_ai_defaults.py` — new migration (add two columns).
- `backend/app/db/models.py` — `User`: add `preferred_credential_id`, `preferred_model`.
- `backend/app/models/schemas.py` — `UserUpdate` + `UserResponse`: add both fields.
- `backend/app/api/auth.py` — `update_me`: persist/validate the preferred pair.
- `backend/app/services/codex_usage_service.py` — **new**: probe + parse `x-codex-*` headers, 60s cache.
- `backend/app/models/schemas.py` — new `CodexUsageResponse` / `CodexUsageWindow` / `CodexUsageCredits`.
- `backend/app/api/credentials.py` — new `GET /{credential_id}/codex-usage` endpoint.
- `backend/tests/test_auth_preferred_defaults.py` — **new**.
- `backend/tests/test_codex_usage_service.py` — **new**.

**Frontend**
- `frontend/src/types/auth.ts` — `User` + `UserUpdateRequest`: add both fields.
- `frontend/src/composables/useAiDefaults.ts` — **new**: `resolveDefault` / `resolveModel` / `preferredStatus`.
- `frontend/src/composables/useAiDefaults.test.ts` — **new** unit tests (Vitest if present, else Playwright-independent test runner used by repo).
- `frontend/src/services/api.ts` — `credentialsApi.getCodexUsage`.
- `frontend/src/types/credential.ts` — `CodexUsage` types.
- `frontend/src/components/Layout/UserSettingsDialog.vue` — add `"ai-defaults"` tab shell + preferred picker.
- `frontend/src/components/Layout/aiDefaults/AiDefaultsTab.vue` — **new**: preferred picker + usage section (keeps the dialog thin).
- `frontend/src/components/Layout/aiDefaults/CodexUsageCard.vue` — **new**: bars per credential.
- Surface adoption edits (Phase 4): `ChatConversation.vue` and the other AI credential+model pickers.

---

## Phase 1 — Backend: preferred credential + model

### Task 1: Migration for preferred columns

**Files:**
- Create: `backend/alembic/versions/101_add_user_preferred_ai_defaults.py`

- [ ] **Step 1: Write the migration**

```python
"""add user preferred ai defaults

Revision ID: 101_add_user_preferred_ai_defaults
Revises: 100_add_opencode_credential_type
Create Date: 2026-07-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "101_add_user_preferred_ai_defaults"
down_revision: Union[str, None] = "100_add_opencode_credential_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preferred_credential_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("users", sa.Column("preferred_model", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "fk_users_preferred_credential_id",
        "users",
        "credentials",
        ["preferred_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_preferred_credential_id", "users", type_="foreignkey")
    op.drop_column("users", "preferred_model")
    op.drop_column("users", "preferred_credential_id")
```

- [ ] **Step 2: Apply the migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: completes without error; `\d users` shows both new columns.

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/101_add_user_preferred_ai_defaults.py
git commit -m "feat(db): add user preferred_credential_id and preferred_model columns"
```

### Task 2: User model + schema fields

**Files:**
- Modify: `backend/app/db/models.py:85-90` (User, after `tts_voice_id`)
- Modify: `backend/app/models/schemas.py:51-64` (UserUpdate, UserResponse)

- [ ] **Step 1: Add ORM columns**

In `backend/app/db/models.py`, in `class User`, immediately after the `tts_voice_id` column (line ~90) add:

```python
    preferred_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    preferred_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
```

- [ ] **Step 2: Add schema fields**

In `backend/app/models/schemas.py`, add to `UserUpdate` (after `tts_voice_id`):

```python
    preferred_credential_id: uuid.UUID | None = None
    preferred_model: str | None = Field(None, max_length=128)
```

And to `UserResponse` (after `tts_voice_id`):

```python
    preferred_credential_id: uuid.UUID | None = None
    preferred_model: str | None = None
```

- [ ] **Step 3: Typecheck imports**

Run: `cd backend && uv run ruff check app/db/models.py app/models/schemas.py`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/app/models/schemas.py
git commit -m "feat(user): expose preferred credential/model on model and schemas"
```

### Task 3: Persist preferred pair in update_me (TDD)

**Files:**
- Test: `backend/tests/test_auth_preferred_defaults.py`
- Modify: `backend/app/api/auth.py:264-266` (inside `update_me`, after the `tts_voice_id` block)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth_preferred_defaults.py`. Mirror the mocking style of existing auth tests (AsyncMock db, `get_accessible_credential` patched). It must cover: (a) setting an accessible LLM credential + model persists both; (b) an unowned/inaccessible credential id returns 404; (c) clearing via explicit `None` credential does not raise.

```python
import uuid
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.auth import update_me
from app.db.models import CredentialType
from app.models.schemas import UserUpdate


def _user() -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.preferred_credential_id = None
    user.preferred_model = None
    return user


class UpdatePreferredDefaultsTest(IsolatedAsyncioTestCase):
    async def test_sets_preferred_credential_and_model(self) -> None:
        user = _user()
        cred_id = uuid.uuid4()
        db = AsyncMock()
        cred = MagicMock()
        cred.type = CredentialType.openai
        with patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=cred)), \
             patch("app.api.auth.UserResponse") as resp:
            resp.model_validate.return_value = "ok"
            data = UserUpdate(preferred_credential_id=cred_id, preferred_model="gpt-4o")
            await update_me(data, current_user=user, db=db)
        self.assertEqual(user.preferred_credential_id, cred_id)
        self.assertEqual(user.preferred_model, "gpt-4o")

    async def test_inaccessible_credential_raises_404(self) -> None:
        user = _user()
        db = AsyncMock()
        with patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=None)):
            data = UserUpdate(preferred_credential_id=uuid.uuid4(), preferred_model="gpt-4o")
            with self.assertRaises(HTTPException) as ctx:
                await update_me(data, current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_model_only_update_persists_without_credential_lookup(self) -> None:
        user = _user()
        user.preferred_credential_id = uuid.uuid4()
        db = AsyncMock()
        with patch("app.api.auth.get_accessible_credential", AsyncMock()) as get_cred, \
             patch("app.api.auth.UserResponse") as resp:
            resp.model_validate.return_value = "ok"
            data = UserUpdate(preferred_model="gpt-4o-mini")
            await update_me(data, current_user=user, db=db)
        get_cred.assert_not_awaited()
        self.assertEqual(user.preferred_model, "gpt-4o-mini")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_auth_preferred_defaults.py -v`
Expected: FAIL (update_me ignores the new fields; credential not persisted / model not set).

- [ ] **Step 3: Implement in update_me**

In `backend/app/api/auth.py`, inside `update_me`, after the `tts_voice_id` block (line ~265) and before `await db.flush()`, add:

```python
    if user_data.preferred_credential_id is not None:
        preferred = await get_accessible_credential(
            db, user_data.preferred_credential_id, current_user.id
        )
        if preferred is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preferred credential not found",
            )
        current_user.preferred_credential_id = user_data.preferred_credential_id
    if user_data.preferred_model is not None:
        current_user.preferred_model = user_data.preferred_model or None
```

Note: an explicit `preferred_credential_id=None` in the payload is Pydantic-indistinguishable from "omitted" here (both arrive as `None`), matching the existing `tts_credential_id` behavior. Clearing the preferred credential is done from the UI by clearing the model select and is out of scope for this endpoint change; the FK `ON DELETE SET NULL` covers credential deletion.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_auth_preferred_defaults.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/auth.py backend/tests/test_auth_preferred_defaults.py
git commit -m "feat(auth): persist preferred credential/model in update_me"
```

---

## Phase 2 — Frontend: types, store, composable

### Task 4: Extend auth types + store payload

**Files:**
- Modify: `frontend/src/types/auth.ts:1-16`

- [ ] **Step 1: Add fields to User and UserUpdateRequest**

In `frontend/src/types/auth.ts`, add to `interface User` (after `tts_voice_id`):

```typescript
  preferred_credential_id: string | null;
  preferred_model: string | null;
```

And to `interface UserUpdateRequest` (after `tts_voice_id`):

```typescript
  preferred_credential_id?: string | null;
  preferred_model?: string | null;
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: passes (the store's `updateUser(data: UserUpdateRequest)` now accepts the new fields).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/auth.ts
git commit -m "feat(types): add preferred credential/model to auth types"
```

### Task 5: useAiDefaults composable (TDD)

**Files:**
- Create: `frontend/src/composables/useAiDefaults.ts`
- Test: `frontend/src/composables/useAiDefaults.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/composables/useAiDefaults.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import type { CredentialListItem } from "@/types/credential";

import { createAiDefaultsResolver } from "./useAiDefaults";

function cred(id: string): CredentialListItem {
  return { id, name: id, type: "openai", masked_value: null, header_key: null, created_at: "" };
}

const creds = [cred("c1"), cred("c2")];

describe("createAiDefaultsResolver", () => {
  it("prefers a saved selection over preferred and first", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "c2", preferredModel: "m2" });
    expect(r.resolveCredentialId(creds, { savedCredentialId: "c1" })).toBe("c1");
  });

  it("falls back to preferred when nothing is saved", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "c2", preferredModel: "m2" });
    expect(r.resolveCredentialId(creds, {})).toBe("c2");
  });

  it("falls back to first credential when preferred is not accessible", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "gone", preferredModel: "m2" });
    expect(r.resolveCredentialId(creds, {})).toBe("c1");
  });

  it("resolveModel: saved wins, then preferred when its credential is chosen", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "c2", preferredModel: "m2" });
    const models = [{ id: "mA", name: "mA", is_reasoning: false, supports_batch: false }];
    expect(r.resolveModel("c2", [...models, { id: "m2", name: "m2", is_reasoning: false, supports_batch: false }], {})).toBe("m2");
    expect(r.resolveModel("c2", models, { savedModel: "mA" })).toBe("mA");
    // preferred model not in list, no saved -> null (caller keeps its own default)
    expect(r.resolveModel("c2", models, {})).toBeNull();
    // credential is not the preferred credential -> preferred model ignored
    expect(r.resolveModel("c1", [...models, { id: "m2", name: "m2", is_reasoning: false, supports_batch: false }], {})).toBeNull();
  });

  it("preferredStatus flags an unresolvable preferred credential", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "gone", preferredModel: "m2" });
    expect(r.preferredStatus(creds)).toBe("invalid");
    const ok = createAiDefaultsResolver({ preferredCredentialId: "c1", preferredModel: "m2" });
    expect(ok.preferredStatus(creds)).toBe("ok");
    const none = createAiDefaultsResolver({ preferredCredentialId: null, preferredModel: null });
    expect(none.preferredStatus(creds)).toBe("unset");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && bunx vitest run src/composables/useAiDefaults.test.ts`
Expected: FAIL ("createAiDefaultsResolver" not found). (Vitest 4.1.0 is already a devDependency and other `src/**/*.test.ts` files use it; there is no `test` npm script, so invoke `bunx vitest run` directly.)

- [ ] **Step 3: Implement the composable**

Create `frontend/src/composables/useAiDefaults.ts`:

```typescript
import { computed } from "vue";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import { useAuthStore } from "@/stores/auth";

export type PreferredStatus = "unset" | "ok" | "invalid";

interface SavedSelection {
  savedCredentialId?: string | null;
  savedModel?: string | null;
}

interface Preferred {
  preferredCredentialId: string | null;
  preferredModel: string | null;
}

export interface AiDefaultsResolver {
  resolveCredentialId(credentials: CredentialListItem[], saved: SavedSelection): string | null;
  resolveModel(credentialId: string, models: LLMModel[], saved: SavedSelection): string | null;
  preferredStatus(credentials: CredentialListItem[]): PreferredStatus;
}

/** Pure resolver — unit-testable without a Pinia instance. */
export function createAiDefaultsResolver(preferred: Preferred): AiDefaultsResolver {
  return {
    resolveCredentialId(credentials, saved) {
      if (saved.savedCredentialId && credentials.some((c) => c.id === saved.savedCredentialId)) {
        return saved.savedCredentialId;
      }
      if (
        preferred.preferredCredentialId &&
        credentials.some((c) => c.id === preferred.preferredCredentialId)
      ) {
        return preferred.preferredCredentialId;
      }
      return credentials.length > 0 ? credentials[0].id : null;
    },
    resolveModel(credentialId, models, saved) {
      if (saved.savedModel && models.some((m) => m.id === saved.savedModel)) {
        return saved.savedModel;
      }
      if (
        credentialId === preferred.preferredCredentialId &&
        preferred.preferredModel &&
        models.some((m) => m.id === preferred.preferredModel)
      ) {
        return preferred.preferredModel;
      }
      return null;
    },
    preferredStatus(credentials) {
      if (!preferred.preferredCredentialId) return "unset";
      return credentials.some((c) => c.id === preferred.preferredCredentialId) ? "ok" : "invalid";
    },
  };
}

/** Store-bound accessor used by components/surfaces. */
export function useAiDefaults(): AiDefaultsResolver {
  const authStore = useAuthStore();
  const preferred = computed<Preferred>(() => ({
    preferredCredentialId: authStore.user?.preferred_credential_id ?? null,
    preferredModel: authStore.user?.preferred_model ?? null,
  }));
  return {
    resolveCredentialId: (credentials, saved) =>
      createAiDefaultsResolver(preferred.value).resolveCredentialId(credentials, saved),
    resolveModel: (credentialId, models, saved) =>
      createAiDefaultsResolver(preferred.value).resolveModel(credentialId, models, saved),
    preferredStatus: (credentials) =>
      createAiDefaultsResolver(preferred.value).preferredStatus(credentials),
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && bunx vitest run src/composables/useAiDefaults.test.ts`
Expected: PASS.

- [ ] **Step 5: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/composables/useAiDefaults.ts frontend/src/composables/useAiDefaults.test.ts
git commit -m "feat(frontend): add useAiDefaults resolver (saved > preferred > first)"
```

---

## Phase 3 — AI Defaults tab UI (preferred picker)

### Task 6: AiDefaultsTab component — preferred picker

**Files:**
- Create: `frontend/src/components/Layout/aiDefaults/AiDefaultsTab.vue`
- Modify: `frontend/src/components/Layout/UserSettingsDialog.vue` (tab type, tab button, panel mount)

- [ ] **Step 1: Create the tab component (preferred picker only; usage section added in Phase 6)**

Create `frontend/src/components/Layout/aiDefaults/AiDefaultsTab.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { credentialsApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { useAiDefaults } from "@/composables/useAiDefaults";

const emit = defineEmits<{ close: [] }>();

const authStore = useAuthStore();
const aiDefaults = useAiDefaults();

const credentials = ref<CredentialListItem[]>([]);
const models = ref<LLMModel[]>([]);
const selectedCredentialId = ref<string>("");
const selectedModel = ref<string>("");
const loadingModels = ref(false);
const saving = ref(false);

const credentialOptions = computed(() => [
  { value: "", label: "No preference" },
  ...credentials.value.map((c) => ({ value: c.id, label: c.name })),
]);
const modelOptions = computed(() => [
  { value: "", label: "Select a model" },
  ...models.value.map((m) => ({ value: m.id, label: m.name })),
]);

const preferredInvalid = computed(
  () =>
    aiDefaults.preferredStatus(credentials.value) === "invalid",
);

async function loadModels(credId: string): Promise<void> {
  models.value = [];
  if (!credId) return;
  loadingModels.value = true;
  try {
    models.value = await credentialsApi.getModels(credId);
  } catch {
    models.value = [];
  } finally {
    loadingModels.value = false;
  }
}

async function onCredentialChange(value: string | undefined): Promise<void> {
  selectedCredentialId.value = value ?? "";
  selectedModel.value = "";
  await loadModels(selectedCredentialId.value);
}

async function handleSave(): Promise<void> {
  saving.value = true;
  try {
    await authStore.updateUser({
      preferred_credential_id: selectedCredentialId.value || null,
      preferred_model: selectedCredentialId.value ? selectedModel.value || null : null,
    });
    emit("close");
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  credentials.value = await credentialsApi.listLLM();
  selectedCredentialId.value = authStore.user?.preferred_credential_id ?? "";
  if (selectedCredentialId.value) {
    await loadModels(selectedCredentialId.value);
    selectedModel.value = authStore.user?.preferred_model ?? "";
  }
});
</script>

<template>
  <div class="space-y-5">
    <div class="space-y-2">
      <Label>Preferred LLM credential</Label>
      <p class="text-xs text-muted-foreground">
        Used as the default for every AI feature (chat, assistant, board, widgets, and more)
        when a surface has no saved selection. You can always change it per surface.
      </p>
      <Select
        :model-value="selectedCredentialId"
        :options="credentialOptions"
        @update:model-value="onCredentialChange"
      />
    </div>

    <div
      v-if="selectedCredentialId"
      class="space-y-2"
    >
      <Label>Preferred model</Label>
      <Select
        v-model="selectedModel"
        :options="modelOptions"
        :disabled="loadingModels"
      />
    </div>

    <p
      v-if="preferredInvalid"
      class="text-xs text-amber-500"
    >
      Your previously preferred credential is no longer available. Pick a new one, or leave it
      as "No preference".
    </p>

    <div class="flex justify-end gap-3 pt-2">
      <Button variant="outline" type="button" @click="emit('close')">Cancel</Button>
      <Button type="button" :loading="saving" @click="handleSave">Save AI Defaults</Button>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Wire the tab into UserSettingsDialog**

In `frontend/src/components/Layout/UserSettingsDialog.vue`:

1. Extend the tab type (line 32):

```typescript
type SettingsTab = "profile" | "security" | "voice" | "ai-defaults" | "observability" | "plugins";
```

2. Add the import near the other component imports:

```typescript
import AiDefaultsTab from "@/components/Layout/aiDefaults/AiDefaultsTab.vue";
```

3. Add a tab button after the "Voice" button (after line 349):

```vue
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
          :class="activeTab === 'ai-defaults' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'ai-defaults'"
        >
          AI Defaults
        </button>
```

4. Add the panel mount after the voice `</div>` block (after line 541), before the observability block:

```vue
      <AiDefaultsTab
        v-else-if="activeTab === 'ai-defaults'"
        @close="emit('close')"
      />
```

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes.

- [ ] **Step 4: Manual smoke (via /run or dev server)**

Open Settings → AI Defaults, pick a credential + model, Save, reopen: selection persists.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout/aiDefaults/AiDefaultsTab.vue frontend/src/components/Layout/UserSettingsDialog.vue
git commit -m "feat(settings): add AI Defaults tab with preferred credential/model picker"
```

---

## Phase 4 — Adopt preferred defaults across AI surfaces

Each surface task follows the same recipe: find where the surface first chooses a credential and model, and route it through `useAiDefaults`. Adopt **chat first** (fully specified), then repeat per surface.

### Task 7: Adopt in ChatConversation (reference implementation)

**Files:**
- Modify: `frontend/src/components/Chat/ChatConversation.vue` (imports, `_applyConversationSession`, `loadCredentials`, `loadModels`)

- [ ] **Step 1: Import the composable**

Add near the other imports in `ChatConversation.vue`:

```typescript
import { useAiDefaults } from "@/composables/useAiDefaults";
```

And after the other store/composable setup (near `const selectedCredentialId = ref("")`):

```typescript
const aiDefaults = useAiDefaults();
```

- [ ] **Step 2: Use preferred when no conversation credential is saved**

In `_applyConversationSession` (line ~741), replace the trailing fallback block:

```typescript
  if (!selectedCredentialId.value) {
    selectedCredentialId.value = credentials.value[0].id;
    void loadModels(credentials.value[0].id);
  }
```

with:

```typescript
  if (!selectedCredentialId.value) {
    const resolved = aiDefaults.resolveCredentialId(credentials.value, {});
    if (resolved) {
      selectedCredentialId.value = resolved;
      void loadModels(resolved);
    }
  }
```

And in `loadCredentials` (line ~767), replace:

```typescript
      } else if (!selectedCredentialId.value) {
        selectedCredentialId.value = credentials.value[0].id;
        await loadModels(credentials.value[0].id);
      }
```

with:

```typescript
      } else if (!selectedCredentialId.value) {
        const resolved = aiDefaults.resolveCredentialId(credentials.value, {});
        if (resolved) {
          selectedCredentialId.value = resolved;
          await loadModels(resolved);
        }
      }
```

- [ ] **Step 3: Use preferred model when the credential is the preferred one**

In `loadModels` (line ~777), replace the selection line:

```typescript
      selectedModel.value = match ? match.id : models.value[models.value.length - 1].id;
```

with:

```typescript
      const preferredModel = aiDefaults.resolveModel(credId, models.value, {
        savedModel: preferredModelId ?? null,
      });
      selectedModel.value =
        preferredModel ?? (match ? match.id : models.value[models.value.length - 1].id);
```

(`resolveModel` returns the saved `preferredModelId` when it exists in the list, otherwise the user's preferred model when `credId` is the preferred credential, otherwise `null` → keeps the existing "last model" default.)

- [ ] **Step 4: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes.

- [ ] **Step 5: Manual smoke**

With a preferred set, open a brand-new chat conversation → the preferred credential+model are pre-selected. An existing conversation with a saved `last_model` keeps its saved selection.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/ChatConversation.vue
git commit -m "feat(chat): default new sessions to preferred credential/model"
```

### Task 8: Adopt in remaining AI surfaces

For each surface below, do a self-contained sub-task: **(a)** read the file and find where it defaults the credential and/or model (search for the credential/model refs already present per the grep in Step 1); **(b)** import `useAiDefaults`; **(c)** replace the "first credential" default with `aiDefaults.resolveCredentialId(list, { savedCredentialId })` and the model default with `aiDefaults.resolveModel(credId, models, { savedModel }) ?? <existing default>`, preserving any surface-specific saved value as `savedCredentialId`/`savedModel`; **(d)** lint + typecheck; **(e)** commit `feat(<surface>): default to preferred credential/model`.

- [ ] **Step 1: Enumerate exact call sites**

Run:
```bash
cd frontend && grep -rnE "selectedCredential|selectedModel|credentials\.value\[0\]|models\.value\[" \
  src/components/Panels/DebugPanel.vue \
  src/components/ui/AIExpressionBuilderModal.vue \
  src/components/Dashboards/AiWidgetDialog.vue \
  src/components/Docs/useDocsChatDialog.ts \
  src/components/Docs/DocsChatDialog.vue \
  src/components/Evals/EvalsLeftPanel.vue \
  src/views/EvalsView.vue
```

- [ ] **Step 2: Adopt per surface (one commit each)**

Surfaces to convert (the AI credential+model pickers named in the spec):
  - Dashboard chat / analyzer / workflow-creation assistant (`DebugPanel.vue` and any AI-assistant entry that selects a credential/model)
  - `AIExpressionBuilderModal.vue`
  - `AiWidgetDialog.vue`
  - Docs chat: `useDocsChatDialog.ts` / `DocsChatDialog.vue`
  - Evals: `EvalsLeftPanel.vue` / `EvalsView.vue`
  - Board mapper config (find the mapper credential/model select component under `components/Board/`)
  - Data-table AI and dashboard AI credential pickers (search `grep -rnE "listLLM|getModels" src/components/DataTables src/components/Dashboards`)

Apply the recipe (a)–(e) to each. Example concrete edit shape (identical structure everywhere):

```typescript
// before
selectedCredentialId.value = creds[0]?.id ?? "";
// after
import { useAiDefaults } from "@/composables/useAiDefaults";
const aiDefaults = useAiDefaults();
selectedCredentialId.value =
  aiDefaults.resolveCredentialId(creds, { savedCredentialId: savedCredId }) ?? "";
```

```typescript
// before
selectedModel.value = models[models.length - 1]?.id ?? "";
// after
selectedModel.value =
  aiDefaults.resolveModel(selectedCredentialId.value, models, { savedModel: savedModel }) ??
  (models[models.length - 1]?.id ?? "");
```

- [ ] **Step 3: Full frontend gate**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes after all surfaces converted.

- [ ] **Step 4: Confirm no surface left behind**

Run: `cd frontend && grep -rnE "credentials\.value\[0\]|creds\[0\]" src/components src/views | grep -iE "credential"`
Expected: only intentional non-AI usages remain; every AI credential+model picker now calls `aiDefaults.resolveCredentialId`.

---

## Phase 5 — Backend: Codex usage service + endpoint

### Task 9: Codex usage service (TDD)

**Files:**
- Create: `backend/app/services/codex_usage_service.py`
- Test: `backend/tests/test_codex_usage_service.py`
- Modify: `backend/app/models/schemas.py` (add response models)

- [ ] **Step 1: Add response schemas**

In `backend/app/models/schemas.py` (near the other response models), add:

```python
class CodexUsageWindow(BaseModel):
    key: str  # "primary" | "secondary"
    label: str  # e.g. "5 hours", "Weekly"
    used_percent: float
    window_minutes: int
    reset_after_seconds: int | None = None
    reset_at: int | None = None


class CodexUsageCredits(BaseModel):
    has_credits: bool = False
    balance: str | None = None
    unlimited: bool = False


class CodexUsageResponse(BaseModel):
    available: bool
    plan_type: str | None = None
    active_limit: str | None = None
    windows: list[CodexUsageWindow] = []
    credits: CodexUsageCredits | None = None
    error: str | None = None
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_codex_usage_service.py`:

```python
from unittest import TestCase

from app.services.codex_usage_service import parse_codex_usage_headers, window_label


class WindowLabelTest(TestCase):
    def test_known_labels(self) -> None:
        self.assertEqual(window_label(300), "5 hours")
        self.assertEqual(window_label(10080), "Weekly")

    def test_generic_hours_and_days(self) -> None:
        self.assertEqual(window_label(60), "1h")
        self.assertEqual(window_label(2880), "2d")


class ParseHeadersTest(TestCase):
    def _headers(self) -> dict[str, str]:
        return {
            "x-codex-active-limit": "premium",
            "x-codex-plan-type": "plus",
            "x-codex-primary-used-percent": "34",
            "x-codex-secondary-used-percent": "0",
            "x-codex-primary-window-minutes": "10080",
            "x-codex-secondary-window-minutes": "0",
            "x-codex-primary-reset-after-seconds": "569620",
            "x-codex-primary-reset-at": "1784966861",
            "x-codex-secondary-reset-after-seconds": "0",
            "x-codex-secondary-reset-at": "",
            "x-codex-credits-has-credits": "False",
            "x-codex-credits-balance": "0E-10",
            "x-codex-credits-unlimited": "False",
        }

    def test_skips_zero_minute_window(self) -> None:
        usage = parse_codex_usage_headers(self._headers())
        self.assertTrue(usage.available)
        self.assertEqual(usage.plan_type, "plus")
        self.assertEqual([w.key for w in usage.windows], ["primary"])
        w = usage.windows[0]
        self.assertEqual(w.label, "Weekly")
        self.assertEqual(w.used_percent, 34.0)
        self.assertEqual(w.reset_at, 1784966861)

    def test_credits_parsed(self) -> None:
        usage = parse_codex_usage_headers(self._headers())
        assert usage.credits is not None
        self.assertFalse(usage.credits.has_credits)
        self.assertFalse(usage.credits.unlimited)

    def test_missing_headers_yield_unavailable(self) -> None:
        usage = parse_codex_usage_headers({})
        self.assertFalse(usage.available)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_codex_usage_service.py -v`
Expected: FAIL (module/functions not defined).

- [ ] **Step 4: Implement the service**

Create `backend/app/services/codex_usage_service.py`:

```python
"""Fetch Codex (ChatGPT-account) rate-limit usage via a minimal /responses probe.

The usage data is only exposed as ``x-codex-*`` response headers on a 200 from
``POST https://chatgpt.com/backend-api/codex/responses``. The Codex CLI subprocess
does not surface these headers, so we make a direct minimal request here. Results
are cached for 60s per credential id. Model support is plan-dependent, so we try
candidate models until one is accepted.
"""

from __future__ import annotations

import time
import uuid

import httpx

from app.http_identity import merge_outbound_headers
from app.models.schemas import (
    CodexUsageCredits,
    CodexUsageResponse,
    CodexUsageWindow,
)
from app.services.codex_catalog import CODEX_MODEL_SUGGESTIONS

_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, CodexUsageResponse]] = {}
_working_model: dict[str, str] = {}

_KNOWN_LABELS = {300: "5 hours", 10080: "Weekly"}


def window_label(minutes: int) -> str:
    if minutes in _KNOWN_LABELS:
        return _KNOWN_LABELS[minutes]
    if minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def _to_int(value: str | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: str | None) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_codex_usage_headers(headers: dict[str, str]) -> CodexUsageResponse:
    lower = {k.lower(): v for k, v in headers.items()}
    if "x-codex-plan-type" not in lower and "x-codex-primary-window-minutes" not in lower:
        return CodexUsageResponse(available=False, error="no usage headers")

    windows: list[CodexUsageWindow] = []
    for key in ("primary", "secondary"):
        minutes = _to_int(lower.get(f"x-codex-{key}-window-minutes"))
        percent = _to_float(lower.get(f"x-codex-{key}-used-percent"))
        if not minutes or minutes <= 0 or percent is None:
            continue
        windows.append(
            CodexUsageWindow(
                key=key,
                label=window_label(minutes),
                used_percent=percent,
                window_minutes=minutes,
                reset_after_seconds=_to_int(lower.get(f"x-codex-{key}-reset-after-seconds")),
                reset_at=_to_int(lower.get(f"x-codex-{key}-reset-at")),
            )
        )

    credits = CodexUsageCredits(
        has_credits=str(lower.get("x-codex-credits-has-credits", "")).strip().lower() == "true",
        balance=lower.get("x-codex-credits-balance") or None,
        unlimited=str(lower.get("x-codex-credits-unlimited", "")).strip().lower() == "true",
    )
    return CodexUsageResponse(
        available=True,
        plan_type=lower.get("x-codex-plan-type") or None,
        active_limit=lower.get("x-codex-active-limit") or None,
        windows=windows,
        credits=credits,
    )


async def fetch_codex_usage(
    *, credential_id: str, access_token: str, account_id: str | None
) -> CodexUsageResponse:
    """Probe the Codex backend and return parsed usage. Never raises."""
    cached = _cache.get(credential_id)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    result = await _probe(credential_id, access_token, account_id)
    _cache[credential_id] = (time.time(), result)
    return result


async def _probe(
    credential_id: str, access_token: str, account_id: str | None
) -> CodexUsageResponse:
    headers = merge_outbound_headers(
        {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "session_id": str(uuid.uuid4()),
        }
    )
    if account_id:
        headers["chatgpt-account-id"] = account_id

    candidates: list[str] = []
    if credential_id in _working_model:
        candidates.append(_working_model[credential_id])
    candidates.extend(m for m in CODEX_MODEL_SUGGESTIONS if m not in candidates)

    last_error = "no candidate model accepted"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for model in candidates:
                body = {
                    "model": model,
                    "instructions": "ping",
                    "input": [
                        {"role": "user", "content": [{"type": "input_text", "text": "hi"}]}
                    ],
                    "stream": True,
                    "store": False,
                }
                async with client.stream(
                    "POST", _RESPONSES_URL, headers=headers, json=body
                ) as resp:
                    if resp.status_code == 200:
                        _working_model[credential_id] = model
                        usage = parse_codex_usage_headers(dict(resp.headers))
                        await resp.aclose()
                        return usage
                    text = (await resp.aread()).decode("utf-8", "replace")
                    last_error = f"HTTP {resp.status_code}: {text[:120]}"
                    if "model is not supported" not in text:
                        # Auth/other error — stop trying more models.
                        break
    except Exception as exc:  # noqa: BLE001 — usage must never break the request
        last_error = f"{type(exc).__name__}: {exc}"

    return CodexUsageResponse(available=False, error=last_error)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_codex_usage_service.py -v`
Expected: PASS.

- [ ] **Step 6: Format + lint**

Run: `cd backend && uv run ruff format app/services/codex_usage_service.py app/models/schemas.py && uv run ruff check app/services/codex_usage_service.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/codex_usage_service.py backend/tests/test_codex_usage_service.py backend/app/models/schemas.py
git commit -m "feat(codex): add usage service parsing x-codex-* headers with 60s cache"
```

### Task 10: Codex usage endpoint (TDD)

**Files:**
- Modify: `backend/app/api/credentials.py` (new endpoint near `get_credential_models`, ~line 1321)
- Test: `backend/tests/test_codex_usage_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_codex_usage_endpoint.py`:

```python
import uuid
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.credentials import get_codex_usage
from app.db.models import CredentialType
from app.models.schemas import CodexUsageResponse


class CodexUsageEndpointTest(IsolatedAsyncioTestCase):
    async def test_non_codex_returns_400(self) -> None:
        cred = MagicMock()
        cred.type = CredentialType.openai
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid.uuid4()
        with patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=cred)):
            with self.assertRaises(HTTPException) as ctx:
                await get_codex_usage(uuid.uuid4(), current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_not_found_returns_404(self) -> None:
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid.uuid4()
        with patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await get_codex_usage(uuid.uuid4(), current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_codex_returns_usage(self) -> None:
        cred = MagicMock()
        cred.id = uuid.uuid4()
        cred.type = CredentialType.codex
        cred.encrypted_config = "enc"
        db = AsyncMock()
        user = MagicMock()
        user.id = uuid.uuid4()
        with patch("app.api.credentials._get_accessible_credential", AsyncMock(return_value=cred)), \
             patch("app.api.credentials.decrypt_config", return_value={"access_token": "t", "account_id": "a"}), \
             patch(
                 "app.api.credentials.fetch_codex_usage",
                 AsyncMock(return_value=CodexUsageResponse(available=True, plan_type="plus")),
             ):
            result = await get_codex_usage(cred.id, current_user=user, db=db)
        self.assertTrue(result.available)
        self.assertEqual(result.plan_type, "plus")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_codex_usage_endpoint.py -v`
Expected: FAIL (`get_codex_usage` not defined).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/credentials.py`, add the import near the other service imports at the top:

```python
from app.services.codex_usage_service import fetch_codex_usage
```

And add the endpoint after `get_credential_models` (after line ~1321):

```python
@router.get("/{credential_id}/codex-usage", response_model=CodexUsageResponse)
async def get_codex_usage(
    credential_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CodexUsageResponse:
    credential = await _get_accessible_credential(db, credential_id, current_user)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found",
        )
    if credential.type != CredentialType.codex:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usage is only available for Codex credentials",
        )
    config = decrypt_config(credential.encrypted_config)
    return await fetch_codex_usage(
        credential_id=str(credential.id),
        access_token=str(config.get("access_token") or ""),
        account_id=str(config.get("account_id") or "") or None,
    )
```

Ensure `CodexUsageResponse` is imported from `app.models.schemas` at the top of `credentials.py` (add to the existing schemas import group).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && SECRET_KEY=test-secret-key-for-tests-only-32-bytes uv run pytest tests/test_codex_usage_endpoint.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Format + lint**

Run: `cd backend && uv run ruff format app/api/credentials.py && uv run ruff check app/api/credentials.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/credentials.py backend/tests/test_codex_usage_endpoint.py
git commit -m "feat(api): add GET /credentials/{id}/codex-usage endpoint"
```

---

## Phase 6 — Frontend: usage bars in the AI Defaults tab

### Task 11: API client + types for Codex usage

**Files:**
- Modify: `frontend/src/types/credential.ts` (add usage types)
- Modify: `frontend/src/services/api.ts` (add `credentialsApi.getCodexUsage`)

- [ ] **Step 1: Add usage types**

In `frontend/src/types/credential.ts`, add:

```typescript
export interface CodexUsageWindow {
  key: string;
  label: string;
  used_percent: number;
  window_minutes: number;
  reset_after_seconds?: number | null;
  reset_at?: number | null;
}

export interface CodexUsageCredits {
  has_credits: boolean;
  balance?: string | null;
  unlimited: boolean;
}

export interface CodexUsage {
  available: boolean;
  plan_type?: string | null;
  active_limit?: string | null;
  windows: CodexUsageWindow[];
  credits?: CodexUsageCredits | null;
  error?: string | null;
}
```

- [ ] **Step 2: Add the API method**

In `frontend/src/services/api.ts`, inside the `credentialsApi` object (near `getModels`, line ~1174):

```typescript
  getCodexUsage: async (id: string): Promise<CodexUsage> => {
    const response = await api.get<CodexUsage>(`/credentials/${id}/codex-usage`);
    return response.data;
  },
```

Add `CodexUsage` to the `@/types/credential` import in `api.ts`.

- [ ] **Step 3: Typecheck**

Run: `cd frontend && bun run typecheck`
Expected: passes.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/credential.ts frontend/src/services/api.ts
git commit -m "feat(frontend): add Codex usage types and API client method"
```

### Task 12: CodexUsageCard + usage section in AiDefaultsTab

**Files:**
- Create: `frontend/src/components/Layout/aiDefaults/CodexUsageCard.vue`
- Modify: `frontend/src/components/Layout/aiDefaults/AiDefaultsTab.vue` (add usage section)

- [ ] **Step 1: Create the usage card**

Create `frontend/src/components/Layout/aiDefaults/CodexUsageCard.vue`:

```vue
<script setup lang="ts">
import { computed } from "vue";

import type { CodexUsage } from "@/types/credential";

const props = defineProps<{ name: string; usage: CodexUsage | null; loading: boolean }>();

const bars = computed(() => props.usage?.windows ?? []);

function remaining(percent: number): number {
  return Math.max(0, Math.min(100, 100 - percent));
}

function resetText(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const hours = Math.floor(seconds / 3600);
  if (hours >= 24) return `resets in ${Math.floor(hours / 24)}d`;
  if (hours >= 1) return `resets in ${hours}h`;
  return `resets in ${Math.floor(seconds / 60)}m`;
}
</script>

<template>
  <div class="rounded-lg border border-border bg-card/60 p-3 space-y-2">
    <div class="flex items-center justify-between gap-2">
      <span class="text-sm font-medium truncate">{{ props.name }}</span>
      <span
        v-if="props.usage?.plan_type"
        class="text-[10px] rounded px-1.5 py-0.5 bg-muted text-muted-foreground uppercase"
      >
        {{ props.usage.plan_type }}
      </span>
    </div>

    <p
      v-if="props.loading"
      class="text-xs text-muted-foreground"
    >
      Loading usage…
    </p>

    <p
      v-else-if="!props.usage || !props.usage.available"
      class="text-xs text-muted-foreground"
    >
      Usage unavailable.
    </p>

    <template v-else>
      <div
        v-for="w in bars"
        :key="w.key"
        class="space-y-1"
      >
        <div class="flex items-center justify-between text-xs">
          <span>{{ w.label }}</span>
          <span class="text-muted-foreground">
            {{ remaining(w.used_percent).toFixed(0) }}% left
            <template v-if="resetText(w.reset_after_seconds)"> · {{ resetText(w.reset_after_seconds) }}</template>
          </span>
        </div>
        <div class="h-2 w-full rounded-full bg-muted overflow-hidden">
          <div
            class="h-full rounded-full bg-primary transition-all"
            :style="{ width: `${remaining(w.used_percent)}%` }"
          />
        </div>
      </div>
    </template>
  </div>
</template>
```

- [ ] **Step 2: Add the usage section to AiDefaultsTab**

In `AiDefaultsTab.vue`, extend the `<script setup>` to load coding credentials + usage:

```typescript
import type { CodexUsage } from "@/types/credential";

const codexCreds = ref<CredentialListItem[]>([]);
const openCodeCreds = ref<CredentialListItem[]>([]);
const usageByCred = ref<Record<string, CodexUsage | null>>({});
const usageLoading = ref<Record<string, boolean>>({});

async function loadCodexUsage(): Promise<void> {
  codexCreds.value = await credentialsApi.listByType("codex");
  openCodeCreds.value = await credentialsApi.listByType("opencode");
  await Promise.all(
    codexCreds.value.map(async (c) => {
      usageLoading.value = { ...usageLoading.value, [c.id]: true };
      try {
        usageByCred.value = { ...usageByCred.value, [c.id]: await credentialsApi.getCodexUsage(c.id) };
      } catch {
        usageByCred.value = { ...usageByCred.value, [c.id]: null };
      } finally {
        usageLoading.value = { ...usageLoading.value, [c.id]: false };
      }
    }),
  );
}
```

Call `void loadCodexUsage()` at the end of the existing `onMounted`, and add a manual refresh. Add the import for `CodexUsageCard`:

```typescript
import CodexUsageCard from "@/components/Layout/aiDefaults/CodexUsageCard.vue";
```

Add the template section before the action buttons:

```vue
    <div
      v-if="codexCreds.length || openCodeCreds.length"
      class="space-y-2 pt-2 border-t border-border"
    >
      <div class="flex items-center justify-between">
        <Label>Coding package usage</Label>
        <Button variant="outline" size="sm" type="button" @click="loadCodexUsage">Refresh</Button>
      </div>
      <CodexUsageCard
        v-for="c in codexCreds"
        :key="c.id"
        :name="c.name"
        :usage="usageByCred[c.id] ?? null"
        :loading="usageLoading[c.id] ?? false"
      />
      <div
        v-for="c in openCodeCreds"
        :key="c.id"
        class="rounded-lg border border-border bg-card/60 p-3"
      >
        <div class="flex items-center justify-between gap-2">
          <span class="text-sm font-medium truncate">{{ c.name }}</span>
          <span class="text-[10px] rounded px-1.5 py-0.5 bg-muted text-muted-foreground">OpenCode</span>
        </div>
        <p class="text-xs text-muted-foreground mt-1">
          Usage unavailable — this gateway does not expose usage data.
        </p>
      </div>
    </div>
```

- [ ] **Step 3: Lint + typecheck**

Run: `cd frontend && bun run lint && bun run typecheck`
Expected: passes.

- [ ] **Step 4: Manual smoke**

Open AI Defaults with a Codex credential present → a horizontal bar per active window renders with "% left" and reset text; OpenCode credential shows the unavailable note. Refresh re-fetches.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout/aiDefaults/CodexUsageCard.vue frontend/src/components/Layout/aiDefaults/AiDefaultsTab.vue
git commit -m "feat(settings): show Codex usage bars and OpenCode unavailable note"
```

---

## Phase 7 — Docs, E2E, full gate

### Task 13: Documentation

**Files:**
- Modify: `frontend/src/docs/content/reference/user-settings.md`
- Modify: `frontend/src/docs/content/reference/credentials.md`

- [ ] **Step 1: Invoke the heym-documentation skill**

Use the `heym-documentation` skill to document: the new AI Defaults tab (preferred credential/model + how it flows to all AI surfaces) and the Codex usage bars (with the OpenCode "usage unavailable" limitation). Update `user-settings.md` and `credentials.md` accordingly.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/docs/content/reference/user-settings.md frontend/src/docs/content/reference/credentials.md
git commit -m "docs: document AI Defaults tab and Codex usage bars"
```

### Task 14: E2E coverage (Playwright)

**Files:**
- Create: `frontend/e2e/ai-defaults.spec.ts`

- [ ] **Step 1: Add a Playwright spec**

Cover: open Settings → AI Defaults, select a credential + model, save, reopen, assert the selection persists. Follow existing specs in `frontend/e2e/` for auth/setup helpers.

- [ ] **Step 2: Run E2E**

Run: `./run_e2e.sh`
Expected: the new spec passes (or is appropriately skipped when no LLM credential is seeded — follow existing spec conventions).

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/ai-defaults.spec.ts
git commit -m "test(e2e): cover AI Defaults tab persistence"
```

### Task 15: Full repository gate

- [ ] **Step 1: Run check.sh**

Run: `cd /Users/cerenakgun/Documents/Projects/heym_workspace/heym && SECRET_KEY=test-secret-key-for-tests-only-32-bytes ./check.sh`
Expected: backend `ruff format`/lint/tests pass; frontend lint/typecheck pass. Commit any formatting-only diffs.

- [ ] **Step 2: Commit any formatting diffs**

```bash
git add -A
git commit -m "chore: apply ruff formatting for AI Defaults feature" || echo "nothing to format"
```

---

## Self-Review notes

- **Spec coverage:** preferred pair (Tasks 1–3, 4–5, 6), propagation to all surfaces (Tasks 7–8), silent fallback + warning (composable `preferredStatus` + Task 6 warning), Codex usage via `x-codex-*` (Tasks 9–10, 12), dynamic windows / `window_minutes==0` skip (Task 9 parser + test), 60s cache (Task 9), OpenCode "unavailable" (Task 12), security (no secrets stored/transmitted — only IDs; authorization via `get_accessible_credential` reused in Tasks 3 & 10), tests (Tasks 3, 5, 9, 10, 14), docs (Task 13).
- **Model-name fragility:** handled by trying `CODEX_MODEL_SUGGESTIONS` and caching the working model (Task 9), because `gpt-5.6` was rejected but `gpt-5.5` accepted on the probed plan.
- **Type consistency:** `resolveCredentialId` / `resolveModel` / `preferredStatus` names are used identically in Tasks 5, 7, 8. `CodexUsageResponse` / `CodexUsageWindow` / `CodexUsageCredits` names match across schemas (Task 9), endpoint (Task 10), and frontend types (Task 11).
- **Test runner:** Vitest 4.1.0 is already present with existing `src/**/*.test.ts` files; unit tests run via `bunx vitest run` (no `test` npm script exists).
