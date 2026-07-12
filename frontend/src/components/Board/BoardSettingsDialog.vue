<script setup lang="ts">
import { computed, ref, watch } from "vue";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { boardApi, credentialsApi } from "@/services/api";
import { useBoardStore } from "@/stores/board";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "close"): void }>();

const boardStore = useBoardStore();
const credentialId = ref("");
const model = ref("");
const credentials = ref<{ id: string; name: string }[]>([]);
const models = ref<{ id: string; name: string }[]>([]);
const loadingModels = ref(false);
const saving = ref(false);

const credentialOptions = computed(() =>
  credentials.value.map((c) => ({ value: c.id, label: c.name })),
);
const modelOptions = computed(() => models.value.map((m) => ({ value: m.id, label: m.name })));

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
  () => props.open,
  async (open) => {
    if (!open || !boardStore.activeBoard) return;
    credentialId.value = boardStore.activeBoard.mapper_credential_id ?? "";
    model.value = boardStore.activeBoard.mapper_model ?? "";
    const creds = await credentialsApi.list();
    credentials.value = creds.map((c) => ({ id: c.id, name: c.name }));
    models.value = [];
    if (credentialId.value) await loadModels(credentialId.value);
  },
  { immediate: true },
);

async function onCredentialChange(value: string | undefined): Promise<void> {
  credentialId.value = value ?? "";
  model.value = "";
  models.value = [];
  if (credentialId.value) await loadModels(credentialId.value);
}

async function save(): Promise<void> {
  const board = boardStore.activeBoard;
  if (!board || saving.value) return;
  saving.value = true;
  try {
    await boardApi.update(board.id, {
      mapper_credential_id: credentialId.value || null,
      mapper_model: model.value || null,
    });
    await boardStore.refreshActiveBoard();
    await boardStore.fetchBoards();
    emit("close");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    title="Board settings"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-1 text-sm">
      <p class="text-xs text-muted-foreground">
        The AI mapper uses this model to map each task's context into a workflow's inputs
        when a card enters a column. Leave empty to pass the default payload.
      </p>
      <div>
        <label class="mb-1 block text-xs font-semibold uppercase text-muted-foreground">
          Mapper credential
        </label>
        <SearchableSelect
          :model-value="credentialId"
          :options="credentialOptions"
          placeholder="Select credential"
          search-placeholder="Search credentials…"
          @update:model-value="onCredentialChange"
        />
      </div>
      <div>
        <label class="mb-1 block text-xs font-semibold uppercase text-muted-foreground">
          Mapper model
        </label>
        <SearchableSelect
          :model-value="model"
          :options="modelOptions"
          placeholder="Select model"
          search-placeholder="Search models…"
          :disabled="!credentialId || loadingModels"
          @update:model-value="model = $event ?? ''"
        />
      </div>
      <div class="flex justify-end gap-2">
        <Button
          variant="ghost"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          :disabled="saving"
          data-testid="board-settings-save"
          @click="save"
        >
          Save
        </Button>
      </div>
    </div>
  </Dialog>
</template>
