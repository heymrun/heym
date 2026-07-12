<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Plus, SquareKanban, Trash2 } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Select from "@/components/ui/Select.vue";
import { useBoardStore } from "@/stores/board";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import BoardCanvas from "./BoardCanvas.vue";
import BoardCardDetailDialog from "./BoardCardDetailDialog.vue";
import BoardColumnSettingsDialog from "./BoardColumnSettingsDialog.vue";
import BoardCreateDialog from "./BoardCreateDialog.vue";

const boardStore = useBoardStore();
const createOpen = ref(false);
const openCardId = ref<string | null>(null);
const settingsColumnId = ref<string | null>(null);

// The app's global Escape handler dispatches a dismiss-overlays event (and
// preventDefaults, which defeats each Dialog's own Esc handler), so overlays
// close by subscribing here.
let removeOverlayDismiss: (() => void) | null = null;

onMounted(async () => {
  removeOverlayDismiss = onDismissOverlays(() => {
    createOpen.value = false;
    openCardId.value = null;
    settingsColumnId.value = null;
  });
  await boardStore.fetchBoards();
  if (!boardStore.activeBoard && boardStore.boards.length > 0) {
    await boardStore.openBoard(boardStore.boards[0].id);
  }
});

onUnmounted(() => {
  boardStore.stopPolling();
  removeOverlayDismiss?.();
});

const boardOptions = computed(() =>
  boardStore.boards.map((board) => ({ value: board.id, label: board.name })),
);

async function selectBoard(boardId: string | undefined): Promise<void> {
  if (boardId) await boardStore.openBoard(boardId);
}

async function removeActiveBoard(): Promise<void> {
  const board = boardStore.activeBoard;
  if (!board) return;
  if (!window.confirm(`Delete board "${board.name}" and all of its cards?`)) return;
  await boardStore.deleteBoard(board.id);
}

async function onBoardCreated(boardId: string): Promise<void> {
  await boardStore.openBoard(boardId);
}
</script>

<template>
  <div
    class="flex h-full flex-col"
    data-testid="board-panel"
  >
    <div class="flex items-center gap-3 border-b border-border/60 px-4 py-2.5">
      <SquareKanban class="h-5 w-5 text-primary" />
      <h2 class="text-sm font-semibold">
        Board
      </h2>
      <Select
        v-if="boardStore.boards.length"
        class="min-w-40"
        :model-value="boardStore.activeBoard?.id ?? ''"
        :options="boardOptions"
        placeholder="Select board"
        aria-label="Select board"
        @update:model-value="selectBoard"
      />
      <Button
        size="sm"
        variant="outline"
        data-testid="board-new"
        @click="createOpen = true"
      >
        <Plus class="mr-1 h-4 w-4" /> New board
      </Button>
      <Button
        v-if="boardStore.activeBoard"
        size="sm"
        variant="ghost"
        aria-label="Delete board"
        @click="removeActiveBoard"
      >
        <Trash2 class="h-4 w-4 text-muted-foreground" />
      </Button>
    </div>

    <div
      v-if="!boardStore.loading && boardStore.boards.length === 0"
      class="flex flex-1 flex-col items-center justify-start gap-3 px-4 pt-16 text-center"
    >
      <SquareKanban class="h-10 w-10 text-muted-foreground" />
      <p class="max-w-md text-sm text-muted-foreground">
        No boards yet. Cards are agentic jobs — moving one into a column runs that column's
        workflows with the card's full context.
      </p>
      <Button
        data-testid="board-empty-create"
        @click="createOpen = true"
      >
        Create your first board
      </Button>
    </div>

    <BoardCanvas
      v-else-if="boardStore.activeBoard"
      @open-card="openCardId = $event"
      @open-settings="settingsColumnId = $event"
    />

    <BoardCreateDialog
      :open="createOpen"
      @close="createOpen = false"
      @created="onBoardCreated"
    />
    <BoardCardDetailDialog
      :open="openCardId !== null"
      :card-id="openCardId"
      @close="openCardId = null"
    />
    <BoardColumnSettingsDialog
      :open="settingsColumnId !== null"
      :column-id="settingsColumnId"
      @close="settingsColumnId = null"
    />
  </div>
</template>
