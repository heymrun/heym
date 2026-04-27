<script setup lang="ts">
import { computed, ref } from "vue";
import { ChevronRight, ChevronDown } from "lucide-vue-next";

const props = defineProps<{
  data: unknown;
  rootExpanded?: boolean;
  depth?: number;
  /** Levels expanded by default (1 matches legacy). Use a large value (e.g. 512) for expand-all. Use 0 for collapse-all. */
  autoExpandDepth?: number;
}>();

const depth = computed(() => props.depth ?? 0);
const effectiveMaxDepth = computed(() =>
  props.autoExpandDepth !== undefined ? props.autoExpandDepth : 1,
);

function isExpandable(val: unknown): val is Record<string, unknown> | unknown[] {
  return val !== null && typeof val === "object";
}

function entries(val: unknown): [string, unknown][] {
  if (Array.isArray(val)) return val.map((v, i) => [String(i), v]);
  if (val && typeof val === "object") return Object.entries(val as Record<string, unknown>);
  return [];
}

function preview(val: unknown): string {
  if (Array.isArray(val)) return `Array(${val.length})`;
  if (val && typeof val === "object") {
    const keys = Object.keys(val as Record<string, unknown>);
    return `{${keys.length}}`;
  }
  return "";
}

function formatValue(val: unknown): string {
  if (val === null) return "null";
  if (val === undefined) return "undefined";
  if (typeof val === "string") return `"${val}"`;
  return String(val);
}

const expanded = ref<Set<string>>(new Set());

function isExpanded(key: string): boolean {
  if (depth.value < effectiveMaxDepth.value && props.rootExpanded !== false) {
    return !expanded.value.has(`collapsed:${key}`);
  }
  return expanded.value.has(key);
}

function toggle(key: string): void {
  if (depth.value < effectiveMaxDepth.value && props.rootExpanded !== false) {
    const collapseKey = `collapsed:${key}`;
    if (expanded.value.has(collapseKey)) {
      expanded.value.delete(collapseKey);
    } else {
      expanded.value.add(collapseKey);
    }
  } else {
    if (expanded.value.has(key)) {
      expanded.value.delete(key);
    } else {
      expanded.value.add(key);
    }
  }
}
</script>

<template>
  <div class="json-tree">
    <template v-if="isExpandable(data)">
      <div
        v-for="[key, val] in entries(data)"
        :key="key"
        class="json-tree-entry"
      >
        <div
          v-if="isExpandable(val)"
          class="flex items-start cursor-pointer hover:bg-muted/50 rounded px-0.5 -mx-0.5"
          @click="toggle(key)"
        >
          <component
            :is="isExpanded(key) ? ChevronDown : ChevronRight"
            class="w-3 h-3 mt-0.5 shrink-0 text-muted-foreground"
          />
          <span class="jt-key mr-1">{{ key }}:</span>
          <span
            v-if="!isExpanded(key)"
            class="text-muted-foreground truncate"
          >{{ preview(val) }}</span>
        </div>
        <div
          v-if="isExpandable(val) && isExpanded(key)"
          class="pl-3 border-l border-border ml-1.5"
        >
          <JsonTree
            :data="val"
            :depth="depth + 1"
            :auto-expand-depth="props.autoExpandDepth"
            :root-expanded="rootExpanded"
          />
        </div>
        <div
          v-if="!isExpandable(val)"
          class="flex items-start pl-3"
        >
          <span class="jt-key mr-1">{{ key }}:</span>
          <span
            class="jt-val break-all"
            :data-type="val === null ? 'null' : typeof val"
          >{{ formatValue(val) }}</span>
        </div>
      </div>
    </template>
    <span
      v-else
      class="jt-val"
      :data-type="data === null ? 'null' : typeof data"
    >{{ formatValue(data) }}</span>
  </div>
</template>

<style scoped>
.jt-key {
  color: hsl(var(--foreground));
  font-weight: 500;
}

.jt-val[data-type="string"] {
  color: hsl(var(--accent-green));
}

.jt-val[data-type="number"] {
  color: hsl(var(--accent-blue));
}

.jt-val[data-type="boolean"] {
  color: hsl(var(--accent-orange));
}

.jt-val[data-type="null"],
.jt-val[data-type="undefined"] {
  color: hsl(var(--muted-foreground));
  font-style: italic;
}
</style>
