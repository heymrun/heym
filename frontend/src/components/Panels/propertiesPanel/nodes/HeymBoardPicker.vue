<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch } from "vue";

import type { BoardState, BoardSummary } from "@/types/board";
import type { HeymBoardFieldKey } from "@/lib/heymOperations";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { boardApi } from "@/services/api";

const props = defineProps<{ fieldKey: HeymBoardFieldKey; modelValue: string }>();
const emit = defineEmits<{ select: [id: string] }>();

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const boards = shallowRef<BoardSummary[]>([]);
const board = shallowRef<BoardState | null>(null);
const chosenBoardId = ref("");
const loadingBoards = ref(true);
const loadingItems = ref(false);
const boardsError = ref(false);
const itemsError = ref(false);
let boardSelectionVersion = 0;

const isBoardField = computed(() => props.fieldKey === "heymBoardId");
const itemName = computed(() => props.fieldKey === "heymBoardColumnId" ? "column" : "card");
const targetId = computed((): string =>
  typeof props.modelValue === "string" ? props.modelValue.trim().toLowerCase() : "",
);
const boardOptions = computed(() => boards.value.map(({ id, name }) => ({ value: id, label: name })));
const browseBoardId = computed((): string => {
  if (isBoardField.value) return "";
  return chosenBoardId.value || (boards.value.length === 1 ? boards.value[0].id : "");
});
const itemOptions = computed(() => {
  const state = board.value;
  if (!state) return [];
  if (props.fieldKey === "heymBoardColumnId") {
    return state.columns.map(({ id, name }) => ({ value: id, label: name }));
  }
  const columnNames = new Map(state.columns.map(({ id, name }) => [id, name]));
  return state.cards.map(({ id, title, column_id }) => ({
    value: id, label: title, hint: columnNames.get(column_id),
  }));
});

onMounted(async () => {
  try {
    boards.value = await boardApi.list();
  } catch {
    boardsError.value = true;
  } finally {
    loadingBoards.value = false;
  }
});

watch([() => props.fieldKey, targetId], async ([field, id], _previous, onCleanup) => {
  if (field === "heymBoardId" || !uuidPattern.test(id)) return;
  if (itemOptions.value.some((option) => option.value === id)) return;

  const selectionVersion = boardSelectionVersion;
  let current = true;
  onCleanup(() => { current = false; });
  try {
    const [parent] = await boardApi.list(field === "heymBoardColumnId" ? { column_id: id } : { card_id: id });
    if (parent && current && selectionVersion === boardSelectionVersion) {
      chosenBoardId.value = parent.id;
    }
  } catch {
    // A failed lookup leaves the saved ID available in the expression field.
  }
}, { immediate: true });

watch(browseBoardId, async (id, _previous, onCleanup) => {
  board.value = null;
  itemsError.value = false;
  loadingItems.value = Boolean(id);
  if (!id) return;

  let current = true;
  onCleanup(() => { current = false; });
  try {
    const state = await boardApi.getState(id);
    if (current) board.value = state;
  } catch {
    if (current) itemsError.value = true;
  } finally {
    if (current) loadingItems.value = false;
  }
});

function onBoardSelected(id: string | undefined): void {
  if (!id) return;
  boardSelectionVersion += 1;
  chosenBoardId.value = id;
  if (isBoardField.value) emit("select", id);
}
</script>

<template>
  <div class="space-y-2">
    <SearchableSelect
      :model-value="isBoardField ? targetId : browseBoardId"
      :options="boardOptions"
      :placeholder="loadingBoards ? 'Loading boards…' : 'Select a board…'"
      :disabled="loadingBoards || boardsError"
      search-placeholder="Search boards…"
      empty-text="No boards available."
      @update:model-value="onBoardSelected"
    />
    <SearchableSelect
      v-if="!isBoardField"
      :model-value="targetId"
      :options="itemOptions"
      :placeholder="loadingItems ? `Loading ${itemName}s…` : `Select a ${itemName}…`"
      :disabled="!board"
      :search-placeholder="`Search ${itemName}s…`"
      :empty-text="`No ${itemName}s available.`"
      @update:model-value="(id) => { if (id) emit('select', id); }"
    />
    <p
      v-if="boardsError || itemsError"
      class="text-xs text-muted-foreground"
      role="status"
    >
      {{ boardsError ? "Could not load boards." : `Could not load ${itemName}s.` }} You can enter the ID below.
    </p>
  </div>
</template>
