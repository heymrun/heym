<script setup lang="ts">
import { ref } from "vue";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { useBoardStore } from "@/stores/board";

defineProps<{ open: boolean }>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "created", boardId: string): void;
}>();

const boardStore = useBoardStore();
const name = ref("");
const description = ref("");
const saving = ref(false);

async function submit(): Promise<void> {
  const trimmed = name.value.trim();
  if (!trimmed || saving.value) return;
  saving.value = true;
  try {
    const board = await boardStore.createBoard(trimmed, description.value.trim() || undefined);
    name.value = "";
    description.value = "";
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
    <div class="flex flex-col gap-3 p-1">
      <Input
        v-model="name"
        placeholder="Board name"
        @keydown.enter="submit"
      />
      <Input
        v-model="description"
        placeholder="Description (optional)"
      />
      <div class="flex justify-end gap-2">
        <Button
          variant="ghost"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          :disabled="!name.trim() || saving"
          @click="submit"
        >
          Create board
        </Button>
      </div>
    </div>
  </Dialog>
</template>
