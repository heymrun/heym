<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
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
