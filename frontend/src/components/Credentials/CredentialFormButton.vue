<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, type Component } from "vue";
import { Check, KeyRound, Pencil } from "lucide-vue-next";

import type { ClarifyCredentialRef } from "@/types/clarify";
import type { Credential } from "@/types/credential";

import Button from "@/components/ui/Button.vue";
import { credentialsApi } from "@/services/api";
import { CREDENTIAL_TYPE_LABELS } from "@/types/credential";

const props = defineProps<{
  // A preset for a new credential, or the id of an existing one to edit.
  create?: ClarifyCredentialRef;
  editId?: string;
  saved?: ClarifyCredentialRef;
  disabled?: boolean;
}>();

const emit = defineEmits<{ (e: "saved", credential: Credential): void }>();

const dialogOpen = ref(false);
// Loaded on demand so the chat and editor bundles do not carry the credential dialog. It is
// mounted closed first: the dialog initializes its form when `open` turns true.
const dialogComponent = shallowRef<Component | null>(null);
const editing = ref<Credential | null>(null);
const loadError = ref("");

const ready = computed((): boolean => !!dialogComponent.value && (!props.editId || !!editing.value));

const buttonLabel = computed((): string => {
  if (props.create) return `Create ${CREDENTIAL_TYPE_LABELS[props.create.type]} credential…`;
  return editing.value ? `Update ${editing.value.name}…` : "Update credential…";
});

async function loadDialog(): Promise<void> {
  dialogComponent.value = (await import("@/components/Credentials/CredentialDialog.vue")).default;
}

async function loadCredential(id: string): Promise<void> {
  try {
    editing.value = await credentialsApi.get(id);
  } catch {
    loadError.value = "This credential could not be opened.";
  }
}

onMounted(() => {
  void loadDialog();
  if (props.editId) void loadCredential(props.editId);
});

function onSaved(credential: Credential): void {
  dialogOpen.value = false;
  emit("saved", credential);
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <Button
      type="button"
      variant="outline"
      size="sm"
      :disabled="props.disabled || !!props.saved || !ready"
      @click="dialogOpen = true"
    >
      <KeyRound
        v-if="props.create"
        class="h-3.5 w-3.5"
      />
      <Pencil
        v-else
        class="h-3.5 w-3.5"
      />
      {{ buttonLabel }}
    </Button>
    <span
      v-if="props.saved"
      class="inline-flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400"
    >
      <Check class="h-3.5 w-3.5" />
      {{ props.create ? "Created" : "Updated" }} {{ props.saved.name }}
    </span>
    <span
      v-else-if="loadError"
      class="text-xs text-destructive"
    >{{ loadError }}</span>
    <component
      :is="dialogComponent"
      v-if="dialogComponent"
      :open="dialogOpen"
      :credential="editing"
      :preset-type="props.create?.type"
      :preset-name="props.create?.name"
      complete-on-connect
      @close="dialogOpen = false"
      @saved="onSaved"
    />
  </div>
</template>
