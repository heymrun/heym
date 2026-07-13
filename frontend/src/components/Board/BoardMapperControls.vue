<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import type { CredentialType } from "@/types/credential";
import { credentialsApi } from "@/services/api";

// The mapper runs an LLM chat completion, so only chat-capable providers apply.
const MAPPER_CREDENTIAL_TYPES: CredentialType[] = ["openai", "google", "custom"];

const props = defineProps<{ credentialId: string; model: string }>();
const emit = defineEmits<{
  (e: "update:credentialId", value: string): void;
  (e: "update:model", value: string): void;
}>();

const credentials = ref<{ id: string; name: string }[]>([]);
const models = ref<{ id: string; name: string }[]>([]);
const loadingModels = ref(false);

const credentialOptions = computed(() =>
  credentials.value.map((c) => ({ value: c.id, label: c.name })),
);
const modelOptions = computed(() => models.value.map((m) => ({ value: m.id, label: m.name })));
const configured = computed(() => Boolean(props.credentialId && props.model));

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

onMounted(async () => {
  const creds = await credentialsApi.list();
  credentials.value = creds
    .filter((c) => MAPPER_CREDENTIAL_TYPES.includes(c.type))
    .map((c) => ({ id: c.id, name: c.name }));
});

watch(
  () => props.credentialId,
  async (credId) => {
    models.value = [];
    if (credId) await loadModels(credId);
  },
  { immediate: true },
);

function onCredentialChange(value: string | undefined): void {
  emit("update:credentialId", value ?? "");
  emit("update:model", "");
}

function onModelChange(value: string | undefined): void {
  emit("update:model", value ?? "");
}
</script>

<template>
  <!-- The model is mandatory: without it the board's actions stay disabled. -->
  <div class="flex flex-col gap-2">
    <div class="flex items-center gap-2">
      <span class="text-xs font-semibold uppercase text-muted-foreground">
        Agentic Kanban Model
      </span>
      <span
        v-if="!configured"
        class="text-xs font-medium text-amber-500"
      >
        Required
      </span>
    </div>
    <SearchableSelect
      :model-value="credentialId"
      :options="credentialOptions"
      placeholder="Credential"
      search-placeholder="Search credentials…"
      aria-label="Agentic Kanban Model credential"
      @update:model-value="onCredentialChange"
    />
    <SearchableSelect
      :model-value="model"
      :options="modelOptions"
      placeholder="Model"
      search-placeholder="Search models…"
      :disabled="!credentialId || loadingModels"
      aria-label="Agentic Kanban Model model"
      @update:model-value="onModelChange"
    />
  </div>
</template>
