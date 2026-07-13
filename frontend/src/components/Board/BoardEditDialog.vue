<script setup lang="ts">
import { computed, ref, watch } from "vue";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { useBoardStore } from "@/stores/board";
import BoardMapperControls from "./BoardMapperControls.vue";
import BoardShareSection from "./BoardShareSection.vue";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ (e: "close"): void }>();

const boardStore = useBoardStore();
const name = ref("");
const description = ref("");
const credentialId = ref("");
const model = ref("");
const saving = ref(false);

watch(
  () => [props.open, boardStore.activeBoard?.id] as const,
  ([open]) => {
    const board = boardStore.activeBoard;
    if (!open || !board) return;
    name.value = board.name;
    description.value = board.description ?? "";
    credentialId.value = board.mapper_credential_id ?? "";
    model.value = board.mapper_model ?? "";
  },
  { immediate: true },
);

// The model is mandatory, so it cannot be cleared away from an existing board either.
const canSave = computed<boolean>(() =>
  Boolean(name.value.trim() && credentialId.value && model.value && !saving.value),
);

async function submit(): Promise<void> {
  if (!canSave.value || !boardStore.activeBoard) return;
  saving.value = true;
  try {
    await boardStore.updateBoard(boardStore.activeBoard.id, {
      name: name.value.trim(),
      description: description.value.trim() || null,
      mapper_credential_id: credentialId.value,
      mapper_model: model.value,
    });
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
    <div class="flex flex-col gap-4 p-1">
      <div class="flex flex-col gap-2">
        <Input
          v-model="name"
          placeholder="Board name"
          data-testid="board-edit-name"
          @keydown.enter="submit"
        />
        <Input
          v-model="description"
          placeholder="Description (optional)"
          data-testid="board-edit-description"
          @keydown.enter="submit"
        />
      </div>

      <BoardMapperControls
        v-model:credential-id="credentialId"
        v-model:model="model"
      />

      <BoardShareSection
        v-if="boardStore.activeBoard"
        :key="boardStore.activeBoard.id"
        :board-id="boardStore.activeBoard.id"
      />

      <div class="flex justify-end gap-2 border-t border-border/60 pt-4">
        <Button
          variant="ghost"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          data-testid="board-edit-save"
          :disabled="!canSave"
          @click="submit"
        >
          Save
        </Button>
      </div>
    </div>
  </Dialog>
</template>
