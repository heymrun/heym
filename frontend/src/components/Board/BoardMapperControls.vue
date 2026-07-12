<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Sparkles } from "lucide-vue-next";

import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import type { CredentialType } from "@/types/credential";
import { boardApi, credentialsApi } from "@/services/api";
import { useBoardStore } from "@/stores/board";

// The mapper runs an LLM chat completion, so only chat-capable providers apply.
const MAPPER_CREDENTIAL_TYPES: CredentialType[] = ["openai", "google", "custom"];

const boardStore = useBoardStore();
const credentialId = ref("");
const model = ref("");
const credentials = ref<{ id: string; name: string }[]>([]);
const models = ref<{ id: string; name: string }[]>([]);
const loadingModels = ref(false);

const credentialOptions = computed(() =>
  credentials.value.map((c) => ({ value: c.id, label: c.name })),
);
const modelOptions = computed(() => models.value.map((m) => ({ value: m.id, label: m.name })));
const configured = computed(() => Boolean(credentialId.value && model.value));

async function loadModels(credId: string): Promise<void> {
  loadingModels.value = true;
  try {
    const list = await credentialsApi.getModels(credId);
    models.value = list.map((m) => ({ id: m.id, name: m.name }));
  } catch {
    models.value = [];
  } finally {
    loadingModels.value = false;
  }
}

watch(
  () => boardStore.activeBoard?.id,
  async (boardId) => {
    if (!boardId || !boardStore.activeBoard) return;
    credentialId.value = boardStore.activeBoard.mapper_credential_id ?? "";
    model.value = boardStore.activeBoard.mapper_model ?? "";
    if (!credentials.value.length) {
      const creds = await credentialsApi.list();
      credentials.value = creds
        .filter((c) => MAPPER_CREDENTIAL_TYPES.includes(c.type))
        .map((c) => ({ id: c.id, name: c.name }));
    }
    models.value = [];
    if (credentialId.value) await loadModels(credentialId.value);
  },
  { immediate: true },
);

async function persist(): Promise<void> {
  const board = boardStore.activeBoard;
  if (!board) return;
  await boardApi.update(board.id, {
    mapper_credential_id: credentialId.value || null,
    mapper_model: model.value || null,
  });
  await boardStore.refreshActiveBoard();
  await boardStore.fetchBoards();
}

async function onCredentialChange(value: string | undefined): Promise<void> {
  credentialId.value = value ?? "";
  model.value = "";
  models.value = [];
  if (credentialId.value) await loadModels(credentialId.value);
  await persist();
}

async function onModelChange(value: string | undefined): Promise<void> {
  model.value = value ?? "";
  await persist();
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-2">
    <span class="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <Sparkles class="h-3.5 w-3.5 text-primary" /> AI Mapper
    </span>
    <SearchableSelect
      class="w-52 shrink-0"
      :model-value="credentialId"
      :options="credentialOptions"
      placeholder="Credential (required)"
      search-placeholder="Search credentials…"
      aria-label="Mapper credential"
      @update:model-value="onCredentialChange"
    />
    <SearchableSelect
      class="w-52 shrink-0"
      :model-value="model"
      :options="modelOptions"
      placeholder="Model (required)"
      search-placeholder="Search models…"
      :disabled="!credentialId || loadingModels"
      aria-label="Mapper model"
      @update:model-value="onModelChange"
    />
    <span
      v-if="!configured"
      class="text-xs text-amber-500"
    >
      Select a credential and model to enable AI mapping.
    </span>
  </div>
</template>
