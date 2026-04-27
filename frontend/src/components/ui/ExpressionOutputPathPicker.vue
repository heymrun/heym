<script setup lang="ts">
import { ChevronDown, ChevronRight, Search } from "lucide-vue-next";
import {
  computed,
  inject,
  nextTick,
  provide,
  ref,
  watch,
  type InjectionKey,
  type Ref,
} from "vue";

import {
  flattenSearchHits,
  formatPathDisplay,
  matchesSearchHit,
  type SearchHit,
} from "@/lib/expressionOutputPathPickerSearch";
import { cn } from "@/lib/utils";

const MAX_DEPTH = 18;
const MAX_ENTRIES = 60;

const ROW_STATE_KEY: InjectionKey<Ref<Record<string, "open" | "closed">>> =
  Symbol("ExpressionOutputPathPicker.rowState");

const ROW_TOGGLE_TIMER_KEY: InjectionKey<Ref<ReturnType<typeof setTimeout> | null>> =
  Symbol("ExpressionOutputPathPicker.rowToggleTimer");

const CLOSE_QUERY_PANEL_KEY: InjectionKey<() => void> = Symbol(
  "ExpressionOutputPathPicker.closeQueryPanel",
);

const TOGGLE_DELAY_MS = 140;
const MAX_SEARCH_RESULTS = 200;

interface Entry {
  segment: string | number;
  val: unknown;
}

const props = withDefaults(
  defineProps<{
    value: unknown;
    pathPrefix?: (string | number)[];
    depth?: number;
    defaultCollapsed?: boolean;
    buildDragText?: ((segments: (string | number)[]) => string | null) | null;
  }>(),
  {
    pathPrefix: () => [],
    depth: 0,
    defaultCollapsed: false,
    buildDragText: null,
  },
);

const emit = defineEmits<{
  pick: [segments: (string | number)[]];
}>();

const queryPanelOpen = ref(false);
const queryText = ref("");
const queryInputRef = ref<HTMLInputElement | null>(null);
const queryHitsListRef = ref<HTMLUListElement | null>(null);
const querySelectedIndex = ref(0);

const injectedRowState = inject(ROW_STATE_KEY, undefined);
const ownRowState = ref<Record<string, "open" | "closed">>({});
const rowState = injectedRowState ?? ownRowState;

const injectedToggleTimer = inject(ROW_TOGGLE_TIMER_KEY, undefined);
const ownToggleTimer = ref<ReturnType<typeof setTimeout> | null>(null);
const pendingRowToggleTimer = injectedToggleTimer ?? ownToggleTimer;

const closeQueryPanelFromProvider = inject(CLOSE_QUERY_PANEL_KEY, null as (() => void) | null);

function requestCloseQueryPanel(): void {
  if (props.depth === 0) {
    queryPanelOpen.value = false;
    return;
  }
  closeQueryPanelFromProvider?.();
}

if (props.depth === 0) {
  provide(ROW_STATE_KEY, rowState);
  provide(ROW_TOGGLE_TIMER_KEY, pendingRowToggleTimer);
  provide(CLOSE_QUERY_PANEL_KEY, () => {
    queryPanelOpen.value = false;
  });
}

function rowId(prefix: readonly (string | number)[]): string {
  return prefix.join("\0");
}

function fullPath(segment: string | number): (string | number)[] {
  return [...props.pathPrefix, segment];
}

function valueAtLocalPath(segment: string | number): unknown {
  const v = props.value;
  if (Array.isArray(v)) {
    if (typeof segment === "number") {
      return v[segment];
    }
    return undefined;
  }
  if (v !== null && typeof v === "object") {
    return (v as Record<string, unknown>)[segment as string];
  }
  return undefined;
}

function valueAtRootPath(segments: readonly (string | number)[]): unknown {
  if (props.depth !== 0) {
    return undefined;
  }
  let cur: unknown = props.value;
  for (const seg of segments) {
    if (cur === null || cur === undefined) {
      return undefined;
    }
    if (typeof seg === "number") {
      if (!Array.isArray(cur) || seg < 0 || seg >= cur.length) {
        return undefined;
      }
      cur = cur[seg];
      continue;
    }
    if (Array.isArray(cur)) {
      return undefined;
    }
    if (typeof cur === "object") {
      cur = (cur as Record<string, unknown>)[seg];
      continue;
    }
    return undefined;
  }
  return cur;
}

function entriesForValue(v: unknown): Entry[] {
  if (Array.isArray(v)) {
    const n = Math.min(v.length, MAX_ENTRIES);
    return Array.from({ length: n }, (_, i) => ({ segment: i, val: v[i]! }));
  }
  if (v !== null && typeof v === "object") {
    const o = v as Record<string, unknown>;
    const keys = Object.keys(o).slice(0, MAX_ENTRIES);
    return keys.map((k) => ({ segment: k, val: o[k] }));
  }
  return [];
}

function defaultExpanded(_prefix: readonly (string | number)[]): boolean {
  return !props.defaultCollapsed;
}

function isRowExpanded(prefix: readonly (string | number)[]): boolean {
  const id = rowId(prefix);
  const s = rowState.value[id];
  if (s === "open") {
    return true;
  }
  if (s === "closed") {
    return false;
  }
  return defaultExpanded(prefix);
}

function toggleRow(prefix: readonly (string | number)[]): void {
  const id = rowId(prefix);
  const cur = isRowExpanded(prefix);
  rowState.value = { ...rowState.value, [id]: cur ? "closed" : "open" };
}

function collectExpandableRowIds(
  value: unknown,
  prefix: readonly (string | number)[],
  currentDepth: number,
  out: Set<string>,
): void {
  if (currentDepth >= MAX_DEPTH) {
    return;
  }
  for (const { segment, val } of entriesForValue(value)) {
    if (!isExpandable(val)) {
      continue;
    }
    const p = [...prefix, segment];
    out.add(rowId(p));
    collectExpandableRowIds(val, p, currentDepth + 1, out);
  }
}

function expandAllRows(): void {
  const ids = new Set<string>();
  collectExpandableRowIds(props.value, props.pathPrefix, props.depth, ids);
  const next: Record<string, "open" | "closed"> = { ...rowState.value };
  for (const id of ids) {
    next[id] = "open";
  }
  rowState.value = next;
}

function collapseAllRows(): void {
  const ids = new Set<string>();
  collectExpandableRowIds(props.value, props.pathPrefix, props.depth, ids);
  const next: Record<string, "open" | "closed"> = { ...rowState.value };
  for (const id of ids) {
    next[id] = "closed";
  }
  rowState.value = next;
}

function clearPendingRowToggle(): void {
  if (pendingRowToggleTimer.value !== null) {
    clearTimeout(pendingRowToggleTimer.value);
    pendingRowToggleTimer.value = null;
  }
}

watch(
  () => props.value,
  () => {
    rowState.value = {};
    clearPendingRowToggle();
    queryText.value = "";
    querySelectedIndex.value = 0;
  },
);

watch(queryPanelOpen, (open) => {
  if (open) {
    querySelectedIndex.value = 0;
    nextTick(() => {
      queryInputRef.value?.focus();
    });
  }
});

watch(queryText, () => {
  querySelectedIndex.value = 0;
});

const entries = computed((): Entry[] => entriesForValue(props.value));

const truncated = computed((): boolean => {
  const v = props.value;
  if (Array.isArray(v)) {
    return v.length > MAX_ENTRIES;
  }
  if (v !== null && typeof v === "object") {
    return Object.keys(v as object).length > MAX_ENTRIES;
  }
  return false;
});

function isExpandable(val: unknown): boolean {
  return val !== null && typeof val === "object";
}

function previewValue(val: unknown): string {
  if (val === null) {
    return "null";
  }
  if (val === undefined) {
    return "undefined";
  }
  if (Array.isArray(val)) {
    return `Array(${val.length})`;
  }
  if (typeof val === "object") {
    return "Object";
  }
  if (typeof val === "string") {
    const s = val.length > 48 ? `${val.slice(0, 45)}…` : val;
    return JSON.stringify(s);
  }
  return String(val);
}

function searchEntriesForValue(v: unknown): { segment: string | number; val: unknown }[] {
  return entriesForValue(v).map((e) => ({ segment: e.segment, val: e.val }));
}

const allSearchHits = computed((): SearchHit[] => {
  if (props.depth !== 0) {
    return [];
  }
  const out: SearchHit[] = [];
  flattenSearchHits(
    props.value,
    [],
    0,
    MAX_DEPTH,
    searchEntriesForValue,
    isExpandable,
    out,
  );
  return out;
});

const filteredSearchHits = computed((): SearchHit[] => {
  const q = queryText.value.trim().toLowerCase();
  if (!q) {
    return [];
  }
  return allSearchHits.value
    .filter((h) => matchesSearchHit(h, q))
    .slice(0, MAX_SEARCH_RESULTS);
});

watch(filteredSearchHits, (hits) => {
  if (querySelectedIndex.value >= hits.length) {
    querySelectedIndex.value = Math.max(0, hits.length - 1);
  }
});

function toggleQueryPanel(): void {
  queryPanelOpen.value = !queryPanelOpen.value;
}

function scrollQueryHitIntoView(): void {
  nextTick(() => {
    const root = queryHitsListRef.value;
    if (!root) {
      return;
    }
    const el = root.querySelector(`[data-query-hit-index="${querySelectedIndex.value}"]`);
    el?.scrollIntoView({ block: "nearest" });
  });
}

function onQueryKeydown(event: KeyboardEvent): void {
  const q = queryText.value.trim();
  const hits = filteredSearchHits.value;
  const hasHits = Boolean(q && hits.length > 0);

  if (event.key === "ArrowDown" && hasHits) {
    event.preventDefault();
    event.stopPropagation();
    querySelectedIndex.value = (querySelectedIndex.value + 1) % hits.length;
    scrollQueryHitIntoView();
    return;
  }
  if (event.key === "ArrowUp" && hasHits) {
    event.preventDefault();
    event.stopPropagation();
    querySelectedIndex.value =
      querySelectedIndex.value === 0 ? hits.length - 1 : querySelectedIndex.value - 1;
    scrollQueryHitIntoView();
    return;
  }
  if (event.key === "Enter" && hasHits) {
    event.preventDefault();
    event.stopPropagation();
    const hit = hits[querySelectedIndex.value];
    if (hit) {
      emitPickSegments(hit.segments);
    }
    return;
  }
  if (event.key !== "Escape") {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  if (queryText.value.trim()) {
    queryText.value = "";
    querySelectedIndex.value = 0;
  } else {
    queryPanelOpen.value = false;
  }
}

function emitPickSegments(segments: readonly (string | number)[]): void {
  emit("pick", [...segments]);
  const picked = valueAtRootPath(segments);
  if (isExpandable(picked)) {
    requestCloseQueryPanel();
  }
}

function segmentLabel(segment: string | number): string {
  if (typeof segment === "number") {
    return `[${segment}]`;
  }
  return segment;
}

function emitPick(segment: string | number): void {
  emit("pick", fullPath(segment));
  const picked = valueAtLocalPath(segment);
  if (isExpandable(picked)) {
    requestCloseQueryPanel();
  }
}

function rowHintTitle(val: unknown): string {
  if (isExpandable(val)) {
    return "Click to expand or collapse. Double-click anywhere on the row to append this path to the expression.";
  }
  return "Double-click anywhere on the row to append this path to the expression.";
}

function onRowClick(event: MouseEvent, segment: string | number, val: unknown): void {
  if (!isExpandable(val)) {
    return;
  }
  requestCloseQueryPanel();
  if (event.detail >= 2) {
    clearPendingRowToggle();
    return;
  }
  clearPendingRowToggle();
  const path = fullPath(segment);
  pendingRowToggleTimer.value = setTimeout(() => {
    pendingRowToggleTimer.value = null;
    toggleRow(path);
  }, TOGGLE_DELAY_MS);
}

function onRowDblClick(event: MouseEvent, segment: string | number): void {
  clearPendingRowToggle();
  event.preventDefault();
  event.stopPropagation();
  emitPick(segment);
}

function handleRowDragStart(event: DragEvent, segment: string | number): void {
  if (!props.buildDragText || !event.dataTransfer) {
    event.preventDefault();
    return;
  }
  const text = props.buildDragText(fullPath(segment));
  if (!text) {
    event.preventDefault();
    return;
  }
  event.dataTransfer.setData("text/plain", text);
  event.dataTransfer.effectAllowed = "copy";
  event.stopPropagation();
}
</script>

<template>
  <div
    :class="
      cn(
        'flex min-h-0 min-w-0 flex-col gap-1',
        depth === 0 && 'pb-3',
      )
    "
  >
    <div
      v-if="depth === 0"
      class="shrink-0 font-sans space-y-1.5"
    >
      <div class="flex flex-wrap items-center justify-between gap-2 gap-y-1.5">
        <button
          type="button"
          :class="cn(
            'inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded transition-colors shrink-0',
            queryPanelOpen
              ? 'bg-muted text-foreground'
              : 'text-muted-foreground hover:text-foreground hover:bg-muted',
          )"
          title="Search keys and direct values in the output tree"
          @click.prevent="toggleQueryPanel"
        >
          <Search
            class="h-3 w-3 shrink-0 opacity-80"
            aria-hidden="true"
          />
          Query
        </button>
        <div class="flex flex-wrap gap-2 justify-end">
          <button
            type="button"
            class="text-[10px] font-medium text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded hover:bg-muted transition-colors"
            @click.prevent="expandAllRows"
          >
            Expand all
          </button>
          <button
            type="button"
            class="text-[10px] font-medium text-muted-foreground hover:text-foreground px-1.5 py-0.5 rounded hover:bg-muted transition-colors"
            @click.prevent="collapseAllRows"
          >
            Collapse all
          </button>
        </div>
      </div>
      <div
        v-if="queryPanelOpen"
        data-heym-expression-query-trap
        class="rounded-md border border-border bg-background/80 px-2 py-2 space-y-1.5"
      >
        <input
          ref="queryInputRef"
          v-model="queryText"
          type="search"
          autocomplete="off"
          placeholder="Search keys and values…"
          class="w-full rounded border border-input bg-background px-2 py-1 text-[11px] font-mono text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          @keydown="onQueryKeydown"
        >
        <p
          v-if="!queryText.trim()"
          class="text-[10px] text-muted-foreground m-0"
        >
          Matches key names and direct primitive values (up to {{ MAX_SEARCH_RESULTS }} results). Use
          <kbd class="px-0.5 rounded bg-muted text-[9px]">↑</kbd>
          <kbd class="px-0.5 rounded bg-muted text-[9px]">↓</kbd>
          and
          <kbd class="px-0.5 rounded bg-muted text-[9px]">Enter</kbd>
          when results are listed.
        </p>
        <p
          v-else-if="filteredSearchHits.length === 0"
          class="text-[10px] text-muted-foreground m-0"
        >
          No matches.
        </p>
        <ul
          v-else
          ref="queryHitsListRef"
          class="list-none m-0 max-h-36 space-y-0.5 overflow-auto p-0 font-mono text-[10px]"
          role="listbox"
          :aria-activedescendant="
            filteredSearchHits.length > 0 ? `query-hit-${querySelectedIndex}` : undefined
          "
        >
          <li
            v-for="(hit, idx) in filteredSearchHits"
            :id="`query-hit-${idx}`"
            :key="idx"
            :data-query-hit-index="idx"
            role="option"
            :aria-selected="idx === querySelectedIndex"
            :class="cn(
              'rounded px-1.5 py-1 cursor-pointer border',
              idx === querySelectedIndex
                ? 'bg-accent border-border'
                : 'border-transparent hover:bg-muted/60 hover:border-border/50',
            )"
            title="Enter or double-click to append this path"
            @mouseenter="querySelectedIndex = idx"
            @dblclick.prevent="emitPickSegments(hit.segments)"
          >
            <div class="text-cyan-600 dark:text-cyan-400 break-all">
              {{ formatPathDisplay(hit.segments) }}
            </div>
            <div class="text-muted-foreground break-all mt-0.5">
              {{ previewValue(hit.value) }}
            </div>
          </li>
        </ul>
      </div>
    </div>

    <div :class="depth === 0 ? 'min-h-0 min-w-0 overflow-x-auto' : ''">
      <div
        v-if="depth >= MAX_DEPTH"
        class="text-xs text-muted-foreground pl-2"
      >
        … max depth
      </div>
      <ul
        v-else-if="entries.length > 0"
        class="list-none m-0 min-w-0 max-w-full p-0 space-y-0.5 break-words font-mono text-xs"
        :class="depth > 0 ? 'pl-3 border-l border-border/60 ml-1' : ''"
      >
        <li
          v-for="{ segment, val } in entries"
          :key="String(segment)"
          class="group"
        >
          <div
            :draggable="buildDragText != null"
            class="flex items-center gap-1.5 py-0.5 rounded px-1 hover:bg-muted/50 min-h-7 cursor-pointer"
            :class="buildDragText != null ? 'cursor-grab active:cursor-grabbing' : ''"
            :title="buildDragText != null ? `${rowHintTitle(val)} Drag to insert path into expression.` : rowHintTitle(val)"
            @click="onRowClick($event, segment, val)"
            @dblclick="onRowDblClick($event, segment)"
            @dragstart="handleRowDragStart($event, segment)"
          >
            <span
              v-if="isExpandable(val)"
              class="flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground pointer-events-none"
              aria-hidden="true"
            >
              <ChevronDown
                v-if="isRowExpanded(fullPath(segment))"
                class="w-3.5 h-3.5"
              />
              <ChevronRight
                v-else
                class="w-3.5 h-3.5"
              />
            </span>
            <span
              v-else
              class="flex h-5 w-5 shrink-0 items-center justify-center"
              aria-hidden="true"
            />
            <span
              :class="cn(
                'shrink-0 text-cyan-600 dark:text-cyan-400 select-none',
                'underline-offset-2 decoration-dotted hover:underline',
              )"
            >{{ segmentLabel(segment) }}</span>
            <span class="text-muted-foreground shrink-0">:</span>
            <span class="text-foreground/80 break-all min-w-0">{{ previewValue(val) }}</span>
          </div>
          <ExpressionOutputPathPicker
            v-if="isExpandable(val) && isRowExpanded(fullPath(segment))"
            :value="val"
            :path-prefix="fullPath(segment)"
            :depth="depth + 1"
            :build-drag-text="buildDragText"
            @pick="emit('pick', $event)"
          />
        </li>
        <li
          v-if="truncated"
          class="text-muted-foreground pl-6 py-0.5"
        >
          … truncated ({{ MAX_ENTRIES }} max)
        </li>
      </ul>
      <p
        v-else
        class="text-xs text-muted-foreground m-0"
      >
        No keys
      </p>
    </div>
  </div>
</template>
