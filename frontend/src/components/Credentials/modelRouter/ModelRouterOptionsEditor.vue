<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Plus, Trash2 } from "lucide-vue-next";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { credentialsApi } from "@/services/api";
import { createEmptyOption, type ModelRouterOptionForm } from "./modelRouterConfig";

const props = defineProps<{
  options: ModelRouterOptionForm[];
  credentials: CredentialListItem[];
}>();

const emit = defineEmits<{
  "update:options": [value: ModelRouterOptionForm[]];
}>();

const modelsByCredential = ref<Record<string, LLMModel[]>>({});
const loadingFor = ref<Record<string, boolean>>({});

const credentialOptions = computed((): { value: string; label: string }[] => [
  { value: "", label: "Select credential..." },
  ...props.credentials.map((credential) => ({
    value: credential.id,
    label: credential.is_shared
      ? `${credential.name} (${credential.type}) - shared`
      : `${credential.name} (${credential.type})`,
  })),
]);

function modelOptionsFor(credentialId: string): { value: string; label: string }[] {
  return (modelsByCredential.value[credentialId] ?? []).map((model) => ({
    value: model.id,
    label: model.name,
  }));
}

async function loadModels(credentialId: string): Promise<void> {
  if (!credentialId || modelsByCredential.value[credentialId]) return;
  loadingFor.value = { ...loadingFor.value, [credentialId]: true };
  try {
    const models = await credentialsApi.getModels(credentialId);
    modelsByCredential.value = { ...modelsByCredential.value, [credentialId]: models };
  } catch {
    modelsByCredential.value = { ...modelsByCredential.value, [credentialId]: [] };
  } finally {
    loadingFor.value = { ...loadingFor.value, [credentialId]: false };
  }
}

function patch(index: number, changes: Partial<ModelRouterOptionForm>): void {
  emit(
    "update:options",
    props.options.map((option, i) => (i === index ? { ...option, ...changes } : option)),
  );
}

async function handleCredentialChange(index: number, credentialId: string): Promise<void> {
  patch(index, { credentialId, model: "" });
  await loadModels(credentialId);
}

function handleDefaultChange(index: number, isDefault: boolean): void {
  // Exactly one fallback, so picking one clears the rest.
  emit(
    "update:options",
    props.options.map((option, i) => ({ ...option, isDefault: isDefault && i === index })),
  );
}

function addOption(): void {
  emit("update:options", [...props.options, createEmptyOption()]);
}

function removeOption(index: number): void {
  emit(
    "update:options",
    props.options.filter((_, i) => i !== index),
  );
}

onMounted(() => {
  props.options.forEach((option) => {
    if (option.credentialId) void loadModels(option.credentialId);
  });
});
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center justify-between">
      <Label>Model options</Label>
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-testid="model-router-add-option"
        @click="addOption"
      >
        <Plus class="mr-1 h-3.5 w-3.5" />
        Add option
      </Button>
    </div>
    <p class="text-xs text-muted-foreground">
      The decision model picks between these by name, so give each one a short, distinct
      name and say plainly when it should win.
    </p>

    <div
      v-for="(option, index) in options"
      :key="option.id"
      class="space-y-3 rounded-xl border border-border/60 p-3"
      :data-testid="`model-router-option-${index}`"
    >
      <div class="flex items-start gap-2">
        <div class="flex-1 space-y-1">
          <Label :for="`router-option-label-${option.id}`">Name</Label>
          <Input
            :id="`router-option-label-${option.id}`"
            :model-value="option.label"
            placeholder="Fast"
            @update:model-value="patch(index, { label: String($event) })"
          />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          class="mt-6"
          :disabled="options.length <= 2"
          :title="options.length <= 2 ? 'A router needs at least two options' : 'Remove option'"
          :aria-label="`Remove option ${index + 1}`"
          @click="removeOption(index)"
        >
          <Trash2 class="h-3.5 w-3.5" />
        </Button>
      </div>

      <div class="grid gap-3 sm:grid-cols-2">
        <div class="space-y-1">
          <Label>Credential</Label>
          <Select
            :model-value="option.credentialId"
            :options="credentialOptions"
            @update:model-value="handleCredentialChange(index, String($event ?? ''))"
          />
        </div>
        <div class="space-y-1">
          <Label>Model</Label>
          <SearchableSelect
            :model-value="option.model"
            :options="modelOptionsFor(option.credentialId)"
            placeholder="Select model..."
            search-placeholder="Search models..."
            empty-text="No models found."
            :disabled="!option.credentialId || loadingFor[option.credentialId]"
            @update:model-value="patch(index, { model: String($event ?? '') })"
          />
        </div>
      </div>

      <div class="space-y-1">
        <Label :for="`router-option-criteria-${option.id}`">Use this when</Label>
        <Textarea
          :id="`router-option-criteria-${option.id}`"
          :model-value="option.criteria"
          :rows="2"
          placeholder="Short factual questions. No code, no long documents."
          @update:model-value="patch(index, { criteria: String($event) })"
        />
      </div>

      <div class="flex items-center gap-2">
        <input
          :id="`router-option-default-${option.id}`"
          type="radio"
          class="h-4 w-4 border-input"
          :checked="option.isDefault"
          @change="handleDefaultChange(index, ($event.target as HTMLInputElement).checked)"
        >
        <Label
          :for="`router-option-default-${option.id}`"
          class="text-sm font-normal"
        >
          Use this option when routing fails
        </Label>
      </div>
    </div>
  </div>
</template>
