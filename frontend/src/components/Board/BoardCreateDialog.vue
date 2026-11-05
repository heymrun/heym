<script setup lang="ts">
import { computed, ref } from "vue";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { useBoardStore } from "@/stores/board";
import BoardAutoAdvanceToggle from "./BoardAutoAdvanceToggle.vue";
import BoardMapperControls from "./BoardMapperControls.vue";

defineProps<{ open: boolean }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "created", boardId: string): void;
}>();

const boardStore = useBoardStore();
const name = ref("");
const description = ref("");
const credentialId = ref("");
const model = ref("");
const autoAdvance = ref(true);
const saving = ref(false);

// A board without its Agentic Kanban Model cannot run anything, so it is required up front.
const canCreate = computed<boolean>(() =>
  Boolean(name.value.trim() && credentialId.value && model.value && !saving.value),
);

async function submit(): Promise<void> {
  if (!canCreate.value) return;
  saving.value = true;
  try {
    const board = await boardStore.createBoard({
      name: name.value.trim(),
      description: description.value.trim() || null,
      mapper_credential_id: credentialId.value,
      mapper_model: model.value,
      auto_advance: autoAdvance.value,
    });
    name.value = "";
    description.value = "";
    credentialId.value = "";
    model.value = "";
    autoAdvance.value = true;
    emit("created", board.id);
    emit("close");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    title="New board"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-1">
      <div class="flex flex-col gap-2">
        <Input
          v-model="name"
          placeholder="Board name"
          @keydown.enter="submit"
        />
        <Input
          v-model="description"
          placeholder="Description (optional)"
        />
      </div>

      <BoardMapperControls
        v-model:credential-id="credentialId"
        v-model:model="model"
      />

      <BoardAutoAdvanceToggle v-model="autoAdvance" />

      <div class="flex justify-end gap-2">
        <Button
          variant="ghost"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          :disabled="!canCreate"
          @click="submit"
        >
          Create board
        </Button>
      </div>
    </div>
  </Dialog>
</template>
