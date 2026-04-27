<script setup lang="ts">
import { computed, ref, watch, type ComponentPublicInstance } from "vue";

import type { WorkflowEdge, WorkflowNode, NodeResult } from "@/types/workflow";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import {
  clampIntString,
  colLetter,
  GS_VALUES_MAX_COLS,
  matrixToJson,
  parse2d,
} from "@/lib/googleSheetsValuesMatrix";

interface Props {
  modelValue: string;
  inputMode: "raw" | "selective";
  selectiveCols: string;
  /** Selective mode always edits a single logical row (one sheet row). */
  selectiveSingleRow: boolean;
  nodes?: WorkflowNode[];
  nodeResults?: NodeResult[];
  edges?: WorkflowEdge[];
  currentNodeId?: string | null;
  dialogNodeLabel?: string;
  navigationEnabled?: boolean;
  navigationIndex?: number;
  navigationTotal?: number;
  selectiveNavigationBaseIndex?: number;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "[]",
  inputMode: "raw",
  selectiveCols: "3",
  selectiveSingleRow: true,
  nodes: () => [],
  nodeResults: () => [],
  edges: () => [],
  currentNodeId: null,
  dialogNodeLabel: "",
  navigationEnabled: false,
  navigationIndex: 0,
  navigationTotal: 0,
  selectiveNavigationBaseIndex: 2,
});

const emit = defineEmits<{
  "update:modelValue": [value: string];
  "update:inputMode": [value: "raw" | "selective"];
  "update:selectiveCols": [value: string];
  navigate: [direction: "prev" | "next"];
  registerFieldIndex: [index: number];
}>();

const rawExpressionRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const selectiveColExpressionRefs = ref<Map<number, InstanceType<typeof ExpressionInput>>>(
  new Map(),
);

const numCols = computed((): number =>
  clampIntString(props.selectiveCols, 1, GS_VALUES_MAX_COLS),
);

const rawExpressionNavigationEnabled = computed((): boolean => {
  return props.inputMode === "raw" && props.navigationEnabled;
});

const selectiveExpressionNavigationEnabled = computed((): boolean => {
  return (
    props.inputMode === "selective" &&
    props.navigationEnabled &&
    props.navigationTotal > 1
  );
});

const rowCells = ref<string[]>([]);

function syncRowFromProps(): void {
  const cols = numCols.value;
  const parsed = parse2d(props.modelValue);
  const first = parsed[0] && Array.isArray(parsed[0]) ? parsed[0] : [];
  const line: string[] = [];
  for (let c = 0; c < cols; c++) {
    line.push(c < first.length && first[c] != null ? String(first[c]) : "");
  }
  rowCells.value = line;
}

watch(
  () => [props.modelValue, props.inputMode, props.selectiveCols],
  () => {
    if (props.inputMode === "selective" && props.selectiveSingleRow) {
      syncRowFromProps();
      emitRow();
    }
  },
  { immediate: true },
);

function emitRow(): void {
  const next = matrixToJson([rowCells.value]);
  if (next === props.modelValue) {
    return;
  }
  emit("update:modelValue", next);
}

function onCellChange(colIndex: number, value: string): void {
  const next = [...rowCells.value];
  if (next[colIndex] !== undefined) {
    next[colIndex] = value;
  }
  rowCells.value = next;
  emitRow();
}

function handleFormat(): void {
  try {
    const parsed = JSON.parse(props.modelValue || "[]") as unknown;
    const compact = JSON.stringify(parsed);
    const pretty = JSON.stringify(parsed, null, 2);
    emit("update:modelValue", props.modelValue.includes("\n") ? compact : pretty);
  } catch {
    // ignore
  }
}

function setSelectiveColRef(
  colIndex: number,
  el: Element | ComponentPublicInstance | null,
): void {
  const inst = el as InstanceType<typeof ExpressionInput> | null;
  if (inst && typeof inst.openExpandDialog === "function") {
    selectiveColExpressionRefs.value.set(colIndex, inst);
  } else {
    selectiveColExpressionRefs.value.delete(colIndex);
  }
}

function selectiveGlobalIndex(localIndex: number): number {
  return props.selectiveNavigationBaseIndex + localIndex;
}

function onModeSelect(mode: "raw" | "selective"): void {
  if (mode === "selective") {
    const parsed = parse2d(props.modelValue);
    const first = parsed[0] && Array.isArray(parsed[0]) ? parsed[0] : [];
    const inferredCols = Math.max(1, Math.min(GS_VALUES_MAX_COLS, first.length || 1));
    emit("update:selectiveCols", String(inferredCols));
    emit("update:inputMode", "selective");
  } else {
    emit("update:inputMode", "raw");
  }
}

defineExpose({
  openExpandDialog: (localIndex?: number): void => {
    if (props.inputMode === "raw") {
      rawExpressionRef.value?.openExpandDialog();
      return;
    }
    const cols = numCols.value;
    const idx = Math.max(0, Math.min(localIndex ?? 0, cols - 1));
    selectiveColExpressionRefs.value.get(idx)?.openExpandDialog();
  },
  closeExpandDialog: (): void => {
    rawExpressionRef.value?.closeExpandDialog();
    for (const inst of selectiveColExpressionRefs.value.values()) {
      inst.closeExpandDialog();
    }
  },
});
</script>

<template>
  <div class="space-y-2">
    <div class="inline-flex items-center rounded-md bg-muted p-0.5">
      <button
        type="button"
        class="px-2 py-0.5 text-sm transition-colors"
        :class="inputMode === 'raw' ? 'bg-background shadow-sm' : ''"
        @click="onModeSelect('raw')"
      >
        Raw
      </button>
      <button
        type="button"
        class="px-2 py-0.5 text-sm transition-colors"
        :class="inputMode === 'selective' ? 'bg-background shadow-sm' : ''"
        @click="onModeSelect('selective')"
      >
        Selective
      </button>
    </div>

    <template v-if="inputMode === 'raw'">
      <ExpressionInput
        ref="rawExpressionRef"
        :model-value="modelValue"
        placeholder="[[&quot;Alice&quot;,30],[&quot;Bob&quot;,25]]"
        :rows="5"
        :nodes="nodes"
        :node-results="nodeResults"
        :edges="edges"
        :current-node-id="currentNodeId"
        :dialog-node-label="dialogNodeLabel"
        dialog-key-label="Values (JSON)"
        :navigation-enabled="rawExpressionNavigationEnabled"
        :navigation-index="navigationIndex"
        :navigation-total="navigationTotal"
        class="font-mono text-xs"
        @update:model-value="emit('update:modelValue', $event)"
        @navigate="emit('navigate', $event)"
        @register-field-index="emit('registerFieldIndex', $event)"
      />
      <div class="flex items-center justify-between">
        <p class="text-xs text-muted-foreground">
          JSON array of rows (supports expressions)
        </p>
        <button
          type="button"
          class="text-xs text-primary hover:underline"
          @click="handleFormat"
        >
          Format
        </button>
      </div>
    </template>

    <template v-else-if="selectiveSingleRow">
      <div class="space-y-1">
        <label class="text-xs text-muted-foreground">Columns</label>
        <input
          type="number"
          min="1"
          :max="GS_VALUES_MAX_COLS"
          class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
          :value="selectiveCols"
          @change="
            emit('update:selectiveCols', String(($event.target as HTMLInputElement).value))
          "
        >
      </div>
      <div class="flex w-full min-w-0 flex-col gap-3">
        <div
          v-for="idx in numCols"
          :key="'col-' + idx"
          class="w-full min-w-0 space-y-1"
        >
          <label class="text-xs text-muted-foreground">{{ colLetter(idx - 1) }}</label>
          <ExpressionInput
            :ref="(el) => setSelectiveColRef(idx - 1, el)"
            :model-value="rowCells[idx - 1] ?? ''"
            placeholder="value or $expression"
            :rows="1"
            class="w-full min-w-0"
            :nodes="nodes"
            :node-results="nodeResults"
            :edges="edges"
            :current-node-id="currentNodeId"
            :dialog-node-label="dialogNodeLabel"
            :dialog-key-label="colLetter(idx - 1)"
            :navigation-enabled="selectiveExpressionNavigationEnabled"
            :navigation-index="selectiveGlobalIndex(idx - 1)"
            :navigation-total="navigationTotal"
            @update:model-value="onCellChange(idx - 1, $event)"
            @navigate="emit('navigate', $event)"
            @register-field-index="emit('registerFieldIndex', $event)"
          />
        </div>
      </div>
    </template>
  </div>
</template>
