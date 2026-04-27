<script setup lang="ts">
import { computed, ref, watch, type ComponentPublicInstance } from "vue";

import type { WorkflowEdge, WorkflowNode, NodeResult } from "@/types/workflow";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";

interface Column {
  id: string;
  name: string;
  type: string;
}

interface Props {
  modelValue: string;
  columns?: Column[];
  inputMode: "raw" | "selective";
  nodes?: WorkflowNode[];
  nodeResults?: NodeResult[];
  edges?: WorkflowEdge[];
  currentNodeId?: string | null;
  placeholder?: string;
  rows?: number;
  showModeToggle?: boolean;
  label?: string;
  dialogNodeLabel?: string;
  dialogKeyLabel?: string;
  navigationEnabled?: boolean;
  navigationIndex?: number;
  navigationTotal?: number;
  /** Global evaluate-dialog field index of the first selective sub-field (id row). */
  selectiveNavigationBaseIndex?: number;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "{}",
  columns: () => [],
  nodes: () => [],
  nodeResults: () => [],
  edges: () => [],
  currentNodeId: null,
  placeholder: "{\n  \"key\": \"value\"\n}",
  rows: 4,
  showModeToggle: true,
  label: "",
  dialogNodeLabel: "",
  dialogKeyLabel: "",
  navigationEnabled: false,
  navigationIndex: 0,
  navigationTotal: 0,
  selectiveNavigationBaseIndex: 0,
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "update:inputMode", value: "raw" | "selective"): void;
  (e: "navigate", direction: "prev" | "next"): void;
  (e: "registerFieldIndex", index: number): void;
}>();

const selectiveValues = ref<Record<string, string>>({});
const rawExpressionRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const selectiveExpressionRefs = ref<Map<string, InstanceType<typeof ExpressionInput>>>(new Map());

const rawExpressionNavigationEnabled = computed((): boolean => {
  return props.inputMode === "raw" && props.navigationEnabled;
});

const selectiveExpressionNavigationEnabled = computed((): boolean => {
  return props.inputMode === "selective" && props.navigationEnabled && props.navigationTotal > 1;
});

function selectiveGlobalIndex(localIndex: number): number {
  return props.selectiveNavigationBaseIndex + localIndex;
}

function setSelectiveExpressionRef(
  key: string,
  el: Element | ComponentPublicInstance | null,
): void {
  const inst = el as InstanceType<typeof ExpressionInput> | null;
  if (inst && typeof inst.openExpandDialog === "function") {
    selectiveExpressionRefs.value.set(key, inst);
  } else {
    selectiveExpressionRefs.value.delete(key);
  }
}

function initializeSelectiveValues(): void {
  const parsed = parseJSON(props.modelValue);
  selectiveValues.value = {};
  for (const col of props.columns) {
    selectiveValues.value[col.name] = parsed[col.name] != null ? String(parsed[col.name]) : "";
  }
  if (parsed["id"] != null) {
    selectiveValues.value["id"] = String(parsed["id"]);
  }
}

function parseJSON(value: string): Record<string, unknown> {
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

function syncSelectiveToJSON(): void {
  const obj: Record<string, unknown> = {};
  for (const col of props.columns) {
    if (selectiveValues.value[col.name]) {
      try {
        obj[col.name] = JSON.parse(selectiveValues.value[col.name]);
      } catch {
        obj[col.name] = selectiveValues.value[col.name];
      }
    }
  }
  if (selectiveValues.value["id"]) {
    const idValue = selectiveValues.value["id"];
    const numericId = parseInt(idValue, 10);
    if (!isNaN(numericId) && idValue === String(numericId)) {
      obj["id"] = numericId;
    } else {
      obj["id"] = idValue;
    }
  }
  emit("update:modelValue", JSON.stringify(obj, null, 2));
}

function handleFormat(): void {
  try {
    const parsed = parseJSON(props.modelValue);
    const current = parseJSON(props.modelValue);
    const isFormatted = JSON.stringify(current) === JSON.stringify(parsed, null, 2);
    const result = isFormatted ? JSON.stringify(parsed) : JSON.stringify(parsed, null, 2);
    emit("update:modelValue", result);
  } catch {
    // Silently fail on invalid JSON
  }
}

function handleSelectiveValueChange(colName: string, value: string): void {
  selectiveValues.value[colName] = value;
  syncSelectiveToJSON();
}

function getColumnType(colType: string): string {
  const typeMap: Record<string, string> = {
    Text: "Text",
    Int: "Number",
    Numeric: "Number",
    Bool: "Boolean",
    Date: "Date",
    DateTime: "DateTime",
    Choice: "Choice",
    Reference: "Reference",
    Attachments: "Attachments",
    Any: "Any",
  };
  return typeMap[colType] || colType;
}

function getPlaceholder(colType: string): string {
  const typeMap: Record<string, string> = {
    Text: "Enter text",
    Int: "0",
    Numeric: "0.0",
    Bool: "true / false",
    Date: "YYYY-MM-DD",
    DateTime: "YYYY-MM-DD HH:MM",
    Choice: "Select option",
    Reference: "Record ID",
    Attachments: "File path",
    Any: "Any value",
    json: "{}",
    boolean: "true / false",
    number: "0",
  };
  return typeMap[colType] || "";
}

function selectiveFieldKeys(): string[] {
  return ["id", ...props.columns.map((c) => c.name)];
}

watch(
  () => props.columns,
  () => {
    if (props.inputMode === "selective") {
      initializeSelectiveValues();
    }
  },
  { immediate: true },
);

watch(
  () => props.inputMode,
  (newMode) => {
    if (newMode === "selective") {
      initializeSelectiveValues();
    }
  },
);

watch(
  () => props.modelValue,
  (newValue) => {
    if (props.inputMode === "selective") {
      const parsed = parseJSON(newValue);
      for (const col of props.columns) {
        const strValue = parsed[col.name] != null ? String(parsed[col.name]) : "";
        if (selectiveValues.value[col.name] !== strValue) {
          selectiveValues.value[col.name] = strValue;
        }
      }
    }
  },
);

defineExpose({
  openExpandDialog: (localIndex?: number): void => {
    if (props.inputMode === "raw") {
      rawExpressionRef.value?.openExpandDialog();
      return;
    }
    const keys = selectiveFieldKeys();
    if (keys.length === 0) {
      return;
    }
    const idx = Math.max(0, Math.min(localIndex ?? 0, keys.length - 1));
    const key = keys[idx];
    if (!key) {
      return;
    }
    selectiveExpressionRefs.value.get(key)?.openExpandDialog();
  },
  closeExpandDialog: (): void => {
    rawExpressionRef.value?.closeExpandDialog();
    for (const inst of selectiveExpressionRefs.value.values()) {
      inst.closeExpandDialog();
    }
  },
});
</script>

<template>
  <div class="space-y-2">
    <div
      v-if="label"
      class="font-medium text-sm"
    >
      {{ label }}
    </div>

    <div
      v-if="showModeToggle && columns.length > 0"
      class="inline-flex items-center rounded-md bg-muted p-0.5"
    >
      <button
        class="px-2 py-0.5 text-sm transition-colors"
        :class="inputMode === 'raw' ? 'bg-background shadow-sm' : ''"
        @click="emit('update:inputMode', 'raw')"
      >
        Raw
      </button>
      <button
        class="px-2 py-0.5 text-sm transition-colors"
        :class="inputMode === 'selective' ? 'bg-background shadow-sm' : ''"
        @click="() => { emit('update:inputMode', 'selective'); initializeSelectiveValues(); }"
      >
        Selective
      </button>
    </div>

    <template v-if="inputMode === 'raw'">
      <ExpressionInput
        ref="rawExpressionRef"
        :model-value="modelValue"
        :placeholder="placeholder"
        :rows="rows"
        :nodes="nodes"
        :node-results="nodeResults"
        :edges="edges"
        :current-node-id="currentNodeId"
        :dialog-node-label="dialogNodeLabel"
        :dialog-key-label="dialogKeyLabel"
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
          JSON object (supports expressions)
        </p>
        <button
          class="text-xs text-primary hover:underline"
          @click="handleFormat"
        >
          Format
        </button>
      </div>
    </template>

    <template v-else>
      <div class="space-y-2">
        <div class="space-y-1">
          <label class="flex items-center gap-1 text-xs text-muted-foreground">
            id
            <span class="text-[10px] text-muted-foreground/60">(ID)</span>
          </label>
          <ExpressionInput
            :ref="(el) => setSelectiveExpressionRef('id', el)"
            :model-value="selectiveValues['id'] || ''"
            placeholder="Record ID"
            :rows="1"
            :nodes="nodes"
            :node-results="nodeResults"
            :edges="edges"
            :current-node-id="currentNodeId"
            :dialog-node-label="dialogNodeLabel"
            dialog-key-label="id"
            :navigation-enabled="selectiveExpressionNavigationEnabled"
            :navigation-index="selectiveGlobalIndex(0)"
            :navigation-total="navigationTotal"
            @update:model-value="handleSelectiveValueChange('id', $event)"
            @navigate="emit('navigate', $event)"
            @register-field-index="emit('registerFieldIndex', $event)"
          />
        </div>
        <div
          v-for="(col, colIdx) in columns"
          :key="col.id"
          class="space-y-1"
        >
          <label class="flex items-center gap-1 text-xs text-muted-foreground">
            {{ col.name }}
            <span class="text-[10px] text-muted-foreground/60">({{ getColumnType(col.type) }})</span>
          </label>
          <ExpressionInput
            :ref="(el) => setSelectiveExpressionRef(col.name, el)"
            :model-value="selectiveValues[col.name] || ''"
            :placeholder="getPlaceholder(col.type)"
            :rows="col.type === 'json' ? 2 : 1"
            :nodes="nodes"
            :node-results="nodeResults"
            :edges="edges"
            :current-node-id="currentNodeId"
            :dialog-node-label="dialogNodeLabel"
            :dialog-key-label="col.name"
            :navigation-enabled="selectiveExpressionNavigationEnabled"
            :navigation-index="selectiveGlobalIndex(1 + colIdx)"
            :navigation-total="navigationTotal"
            @update:model-value="handleSelectiveValueChange(col.name, $event)"
            @navigate="emit('navigate', $event)"
            @register-field-index="emit('registerFieldIndex', $event)"
          />
        </div>
      </div>
    </template>
  </div>
</template>
