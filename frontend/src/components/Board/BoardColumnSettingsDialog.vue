<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ArrowDown, ArrowUp, ExternalLink, Trash2, X } from "lucide-vue-next";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Textarea from "@/components/ui/Textarea.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { boardApi, workflowApi } from "@/services/api";
import { useBoardStore } from "@/stores/board";

const router = useRouter();

function openWorkflow(workflowId: string): void {
  const href = router.resolve({ name: "editor", params: { id: workflowId } }).href;
  window.open(href, "_blank", "noopener,noreferrer");
}

const props = defineProps<{ open: boolean; columnId: string | null }>();
const emit = defineEmits<{ (e: "close"): void }>();

const COLORS = ["#8b5cf6", "#22d3ee", "#10d9a0", "#f59e0b", "#ef4444", null];

const boardStore = useBoardStore();
const name = ref("");
const color = ref<string | null>(null);
const aiInstructions = ref("");
const chain = ref<{ id: string; name: string }[]>([]);
const available = ref<{ id: string; name: string }[]>([]);
const saving = ref(false);

const column = computed(() =>
  boardStore.activeBoard?.columns.find((c) => c.id === props.columnId),
);

watch(
  () => [props.open, props.columnId] as const,
  async ([open]) => {
    if (!open || !column.value) return;
    name.value = column.value.name;
    color.value = column.value.color;
    aiInstructions.value = column.value.ai_instructions ?? "";
    chain.value = column.value.workflows.map((w) => ({
      id: w.workflow_id,
      name: w.workflow_name,
    }));
    const workflows = await workflowApi.list();
    available.value = workflows.map((w) => ({ id: w.id, name: w.name }));
  },
  { immediate: true },
);

const availableOptions = computed(() =>
  available.value
    .filter((w) => !chain.value.some((c) => c.id === w.id))
    .map((w) => ({ value: w.id, label: w.name })),
);

function addToChain(workflowId: string | undefined): void {
  if (!workflowId) return;
  const workflow = available.value.find((w) => w.id === workflowId);
  if (!workflow || chain.value.some((w) => w.id === workflowId)) return;
  chain.value.push(workflow);
}

function moveLink(index: number, delta: number): void {
  const target = index + delta;
  if (target < 0 || target >= chain.value.length) return;
  const copy = [...chain.value];
  [copy[index], copy[target]] = [copy[target], copy[index]];
  chain.value = copy;
}

async function save(): Promise<void> {
  const board = boardStore.activeBoard;
  if (!board || !props.columnId || saving.value) return;
  saving.value = true;
  try {
    await boardApi.updateColumn(board.id, props.columnId, {
      name: name.value.trim() || undefined,
      color: color.value,
      ai_instructions: aiInstructions.value.trim() || null,
      workflow_ids: chain.value.map((w) => w.id),
    });
    await boardStore.refreshActiveBoard();
    emit("close");
  } finally {
    saving.value = false;
  }
}

async function removeColumn(): Promise<void> {
  const board = boardStore.activeBoard;
  if (!board || !props.columnId) return;
  if (!window.confirm("Delete this column? It must be empty.")) return;
  try {
    await boardApi.deleteColumn(board.id, props.columnId);
    await boardStore.refreshActiveBoard();
    emit("close");
  } catch {
    window.alert("Move or delete the cards in this column first.");
  }
}
</script>

<template>
  <Dialog
    :open="open"
    title="Column settings"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 p-1 text-sm">
      <div>
        <label class="mb-1 block text-xs font-semibold uppercase text-muted-foreground">
          Name
        </label>
        <Input
          v-model="name"
          placeholder="Column name"
        />
      </div>
      <div>
        <span class="mb-1 block text-xs font-semibold uppercase text-muted-foreground">
          Color
        </span>
        <div class="flex gap-2">
          <button
            v-for="(option, index) in COLORS"
            :key="index"
            class="h-6 w-6 rounded-full border"
            :class="color === option ? 'ring-2 ring-primary ring-offset-1' : ''"
            :style="{ backgroundColor: option ?? 'transparent' }"
            :aria-label="option ?? 'No color'"
            @click="color = option"
          />
        </div>
      </div>
      <div>
        <span class="mb-1 block text-xs font-semibold uppercase text-muted-foreground">
          Workflow chain (runs in order when a card enters)
        </span>
        <div class="flex flex-col gap-1.5">
          <div
            v-for="(workflow, index) in chain"
            :key="workflow.id"
            class="flex items-center gap-2 rounded-md border border-border/60 px-2 py-1.5"
          >
            <span
              class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-foreground"
            >
              {{ index + 1 }}
            </span>
            <span class="truncate">{{ workflow.name }}</span>
            <button
              class="ml-auto p-0.5 text-foreground hover:text-primary"
              aria-label="Open workflow in new tab"
              title="Open workflow in new tab"
              @click="openWorkflow(workflow.id)"
            >
              <ExternalLink class="h-3.5 w-3.5" />
            </button>
            <button
              class="p-0.5"
              aria-label="Move up"
              @click="moveLink(index, -1)"
            >
              <ArrowUp class="h-3.5 w-3.5" />
            </button>
            <button
              class="p-0.5"
              aria-label="Move down"
              @click="moveLink(index, 1)"
            >
              <ArrowDown class="h-3.5 w-3.5" />
            </button>
            <button
              class="p-0.5 text-red-500"
              aria-label="Remove"
              @click="chain = chain.filter((w) => w.id !== workflow.id)"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </div>
          <SearchableSelect
            :model-value="''"
            :options="availableOptions"
            placeholder="Add workflow…"
            search-placeholder="Search workflows…"
            aria-label="Add workflow to chain"
            @update:model-value="addToChain"
          />
        </div>
      </div>
      <div>
        <span class="mb-1 block text-xs font-semibold uppercase text-muted-foreground">
          AI Instructions
        </span>
        <Textarea
          v-model="aiInstructions"
          :rows="3"
          placeholder="Command for the AI mapper when this column runs (e.g. what this column should achieve)"
          data-testid="column-ai-instructions"
        />
      </div>
      <div class="flex items-center justify-between">
        <Button
          variant="ghost"
          class="text-red-500"
          @click="removeColumn"
        >
          <Trash2 class="mr-1 h-4 w-4" /> Delete column
        </Button>
        <div class="flex gap-2">
          <Button
            variant="ghost"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            :disabled="saving"
            data-testid="column-settings-save"
            @click="save"
          >
            Save
          </Button>
        </div>
      </div>
    </div>
  </Dialog>
</template>
