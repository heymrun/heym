<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { CodexUsage, CredentialListItem, LLMModel } from "@/types/credential";

import CodexUsageCard from "@/components/Layout/aiDefaults/CodexUsageCard.vue";
import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { useAiDefaults } from "@/composables/useAiDefaults";
import { credentialsApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

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

const preferredInvalid = computed(() => aiDefaults.preferredStatus(credentials.value) === "invalid");

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
        usageByCred.value = {
          ...usageByCred.value,
          [c.id]: await credentialsApi.getCodexUsage(c.id),
        };
      } catch {
        usageByCred.value = { ...usageByCred.value, [c.id]: null };
      } finally {
        usageLoading.value = { ...usageLoading.value, [c.id]: false };
      }
    }),
  );
}

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
  void loadCodexUsage();
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
      <SearchableSelect
        :model-value="selectedCredentialId"
        :options="credentialOptions"
        placeholder="No preference"
        search-placeholder="Search credentials…"
        @update:model-value="onCredentialChange"
      />
    </div>

    <div
      v-if="selectedCredentialId"
      class="space-y-2"
    >
      <Label>Preferred model</Label>
      <SearchableSelect
        v-model="selectedModel"
        :options="modelOptions"
        placeholder="Select a model"
        search-placeholder="Search models…"
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

    <div
      v-if="codexCreds.length || openCodeCreds.length"
      class="space-y-2 pt-2 border-t border-border"
    >
      <div class="flex items-center justify-between">
        <Label>Coding package usage</Label>
        <Button
          variant="outline"
          size="sm"
          type="button"
          @click="loadCodexUsage"
        >
          Refresh
        </Button>
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
          <span class="text-[10px] rounded px-1.5 py-0.5 bg-muted text-muted-foreground">
            OpenCode
          </span>
        </div>
        <p class="text-xs text-muted-foreground mt-1">
          Usage unavailable — this gateway does not expose usage data.
        </p>
      </div>
    </div>

    <div class="flex justify-end gap-3 pt-2">
      <Button
        variant="outline"
        type="button"
        @click="emit('close')"
      >
        Cancel
      </Button>
      <Button
        type="button"
        :loading="saving"
        @click="handleSave"
      >
        Save AI Defaults
      </Button>
    </div>
  </div>
</template>
