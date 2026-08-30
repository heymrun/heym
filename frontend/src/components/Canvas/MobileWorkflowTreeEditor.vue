<script setup lang="ts">
import { computed, ref } from "vue";
import { Check, Pencil, Plus, Search, Trash2, X } from "lucide-vue-next";

import { isTileFillingIcon, nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { NODE_DEFINITIONS } from "@/types/node";
import type { NodeType } from "@/types/workflow";

interface Props {
  nodeCount: number;
  selectedLabel: string | null;
}

defineProps<Props>();
const emit = defineEmits<{
  (event: "add", nodeType: NodeType): void;
  (event: "remove"): void;
  (event: "edit-mode", value: boolean): void;
}>();

const isEditing = ref(false);
const pickerOpen = ref(false);
const query = ref("");
const nodeOptions = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase();
  return Object.values(NODE_DEFINITIONS).filter((definition) => {
    if (!normalizedQuery) return true;
    return `${definition.label} ${definition.description}`.toLowerCase().includes(normalizedQuery);
  });
});

function toggleEditMode(): void {
  isEditing.value = !isEditing.value;
  emit("edit-mode", isEditing.value);
}

function openPicker(): void {
  pickerOpen.value = true;
  query.value = "";
}

function addNode(nodeType: NodeType): void {
  emit("add", nodeType);
  pickerOpen.value = false;
}
</script>

<template>
  <section class="rounded-xl border border-border/70 bg-card p-2.5">
    <div class="flex items-center justify-between gap-2">
      <p class="text-xs font-semibold text-muted-foreground">
        {{ nodeCount }} {{ nodeCount === 1 ? "node" : "nodes" }}
      </p>
      <div class="flex items-center gap-1.5">
        <button
          type="button"
          class="mobile-tree-editor-button"
          @click="openPicker"
        >
          <Plus class="h-4 w-4" />Add node
        </button>
        <button
          type="button"
          class="mobile-tree-icon-button"
          :class="isEditing ? 'bg-violet-500/15 text-violet-600 dark:text-violet-300' : ''"
          :aria-pressed="isEditing"
          aria-label="Edit workflow nodes"
          @click="toggleEditMode"
        >
          <Check
            v-if="isEditing"
            class="h-4 w-4"
          />
          <Pencil
            v-else
            class="h-4 w-4"
          />
        </button>
      </div>
    </div>

    <div
      v-if="isEditing"
      class="mt-2 flex items-center gap-1.5 border-t border-border/60 pt-2"
    >
      <p class="min-w-0 flex-1 truncate text-xs text-muted-foreground">
        {{ selectedLabel ? `Tap ${selectedLabel} to change its connection` : "Tap a node to change its connection" }}
      </p>
      <button
        type="button"
        class="mobile-tree-icon-button text-destructive"
        :disabled="!selectedLabel"
        aria-label="Remove selected node"
        @click="emit('remove')"
      >
        <Trash2 class="h-4 w-4" />
      </button>
    </div>

    <div
      v-if="pickerOpen"
      class="mt-3 border-t border-border/60 pt-3"
    >
      <div class="flex h-9 items-center gap-2 rounded-lg border border-border/70 bg-background px-2">
        <Search class="h-4 w-4 text-muted-foreground" />
        <input
          v-model="query"
          class="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
          placeholder="Search nodes..."
          aria-label="Search nodes"
        >
        <button
          type="button"
          class="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Close node picker"
          @click="pickerOpen = false"
        >
          <X class="h-4 w-4" />
        </button>
      </div>
      <div class="mt-2 grid max-h-56 grid-cols-2 gap-1.5 overflow-y-auto pr-0.5">
        <button
          v-for="definition in nodeOptions"
          :key="definition.type"
          type="button"
          class="flex min-w-0 items-center gap-2 rounded-lg border border-border/60 bg-background p-2 text-left transition-colors hover:border-primary/50 hover:bg-primary/5"
          @click="addNode(definition.type)"
        >
          <span
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted"
            :class="nodeIconColorClass[definition.type]"
          >
            <component
              :is="nodeIcons[definition.type]"
              :class="isTileFillingIcon(definition.type) ? 'h-full w-full' : 'h-3.5 w-3.5'"
            />
          </span>
          <span class="min-w-0">
            <span class="block truncate text-xs font-medium">{{ definition.label }}</span>
            <span class="block truncate text-[10px] text-muted-foreground">{{ definition.description }}</span>
          </span>
        </button>
        <p
          v-if="nodeOptions.length === 0"
          class="col-span-2 py-3 text-center text-xs text-muted-foreground"
        >
          No nodes found.
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.mobile-tree-editor-button { @apply inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-2.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90; }
.mobile-tree-icon-button { @apply inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-35; }
</style>
