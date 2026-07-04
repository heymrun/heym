<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Search,
  Sparkles,
  X,
} from "lucide-vue-next";
import { renderMarkdown } from "@/lib/markdown";
import HighlightJsonView from "@/components/Canvas/HighlightJsonView.vue";
import type { HighlightPayload, HighlightRecord } from "@/types/workflow";

const props = withDefaults(
  defineProps<{ payload: HighlightPayload | null; collapsible?: boolean }>(),
  { collapsible: true },
);
const emit = defineEmits<{ close: [] }>();

const PREVIEW_LIMIT = 250;

const dismissed = ref(false);
const expanded = ref<Set<string>>(new Set());
const runIndexById = ref<Record<string, number>>({});
const copiedId = ref<string | null>(null);
const searchQuery = ref("");

const records = computed<HighlightRecord[]>(() => props.payload?.records ?? []);
const hasRecords = computed<boolean>(() => records.value.length > 0);
const visible = computed<boolean>(() => !dismissed.value && hasRecords.value);
const collapsedVisible = computed<boolean>(
  () => props.collapsible && dismissed.value && hasRecords.value,
);

const query = computed<string>(() => searchQuery.value.trim().toLowerCase());

const filteredRecords = computed<HighlightRecord[]>(() => {
  if (!query.value) {
    return records.value;
  }
  return records.value.filter(
    (r) =>
      r.node_label.toLowerCase().includes(query.value) ||
      r.runs.some((run) => run.toLowerCase().includes(query.value)),
  );
});

const kindLabel: Record<HighlightRecord["kind"], string> = {
  input: "Input",
  output: "Output",
  agent: "Agent",
  llm: "LLM",
  final: "Output",
};

watch(
  () => props.payload,
  () => {
    dismissed.value = false;
    expanded.value = new Set();
    runIndexById.value = {};
    copiedId.value = null;
    searchQuery.value = "";
  },
);

function runIndex(record: HighlightRecord): number {
  const idx = runIndexById.value[record.node_id] ?? 0;
  return Math.min(Math.max(idx, 0), Math.max(record.runs.length - 1, 0));
}

function setRunIndex(record: HighlightRecord, next: number): void {
  const clamped = Math.min(Math.max(next, 0), record.runs.length - 1);
  runIndexById.value = { ...runIndexById.value, [record.node_id]: clamped };
}

function currentRun(record: HighlightRecord): string {
  return record.runs[runIndex(record)] ?? "";
}

function toggle(record: HighlightRecord): void {
  const next = new Set(expanded.value);
  if (next.has(record.node_id)) {
    next.delete(record.node_id);
  } else {
    next.add(record.node_id);
  }
  expanded.value = next;
}

async function copy(record: HighlightRecord): Promise<void> {
  try {
    await navigator.clipboard.writeText(currentRun(record));
    copiedId.value = record.node_id;
    window.setTimeout(() => {
      if (copiedId.value === record.node_id) {
        copiedId.value = null;
      }
    }, 1500);
  } catch {
    // clipboard unavailable; ignore
  }
}

function close(): void {
  dismissed.value = true;
  emit("close");
}

// --- JSON detection (collapsible viewer for JSON messages) ---
const jsonCache = new Map<string, unknown>();
const JSON_SENTINEL = Symbol("not-json");

function parseJson(text: string): unknown {
  if (jsonCache.has(text)) {
    return jsonCache.get(text);
  }
  const trimmed = text.trim();
  let parsed: unknown = JSON_SENTINEL;
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const value = JSON.parse(trimmed);
      if (value !== null && typeof value === "object") {
        parsed = value;
      }
    } catch {
      parsed = JSON_SENTINEL;
    }
  }
  jsonCache.set(text, parsed);
  return parsed;
}

function isJson(text: string): boolean {
  return parseJson(text) !== JSON_SENTINEL;
}

// --- Search-aware preview (250 chars, centered on the match, matches marked) ---
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function markMatches(text: string): string {
  const q = query.value;
  if (!q) {
    return escapeHtml(text);
  }
  const lower = text.toLowerCase();
  let result = "";
  let cursor = 0;
  for (;;) {
    const idx = lower.indexOf(q, cursor);
    if (idx === -1) {
      result += escapeHtml(text.slice(cursor));
      break;
    }
    result += escapeHtml(text.slice(cursor, idx));
    result += `<mark class="hl-search-mark">${escapeHtml(text.slice(idx, idx + q.length))}</mark>`;
    cursor = idx + q.length;
  }
  return result;
}

function previewHtml(record: HighlightRecord): string {
  const full = currentRun(record).replace(/\s+/g, " ").trim();
  let start = 0;
  const q = query.value;
  if (q) {
    const idx = full.toLowerCase().indexOf(q);
    if (idx > PREVIEW_LIMIT - 40) {
      start = Math.max(0, idx - 40);
    }
  }
  const slice = full.slice(start, start + PREVIEW_LIMIT);
  const prefix = start > 0 ? "..." : "";
  const suffix = start + PREVIEW_LIMIT < full.length ? "..." : "";
  return prefix + markMatches(slice) + suffix;
}
</script>

<template>
  <div
    v-if="visible"
    data-testid="execution-highlights-panel"
    class="absolute right-4 top-4 z-20 flex max-h-[calc(100%-2rem)] w-80 flex-col rounded-lg border border-border bg-background shadow-lg"
  >
    <div class="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
      <span class="shrink-0 text-sm font-medium">Execution Highlights</span>
      <button
        type="button"
        class="shrink-0 text-muted-foreground hover:text-foreground"
        aria-label="Close highlights"
        @click="close"
      >
        <X class="h-4 w-4" />
      </button>
    </div>

    <div class="border-b border-border px-2 py-1.5">
      <div class="flex items-center gap-1.5 rounded-md bg-muted/50 px-2 py-1">
        <Search class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search highlights..."
          class="w-full bg-transparent text-xs outline-none placeholder:text-muted-foreground"
        >
        <button
          v-if="searchQuery"
          type="button"
          class="shrink-0 text-muted-foreground hover:text-foreground"
          aria-label="Clear search"
          @click="searchQuery = ''"
        >
          <X class="h-3 w-3" />
        </button>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto p-2">
      <p
        v-if="filteredRecords.length === 0"
        class="px-2 py-4 text-center text-xs text-muted-foreground"
      >
        No matching highlights.
      </p>
      <div
        v-for="record in filteredRecords"
        :key="record.node_id"
        class="mb-1 rounded-md border"
        :class="
          query
            ? 'border-violet-500/40 bg-violet-500/10 dark:border-violet-400/40 dark:bg-violet-400/10'
            : 'border-transparent hover:border-border'
        "
      >
        <button
          type="button"
          class="flex w-full items-start gap-2 px-2 py-1.5 text-left"
          @click="toggle(record)"
        >
          <span
            class="shrink-0 rounded bg-muted px-1 text-[10px] uppercase leading-4 text-muted-foreground"
          >
            {{ kindLabel[record.kind] }}
          </span>
          <span class="min-w-0 flex-1 text-xs">
            <span class="font-medium">
              {{ record.node_label
              }}<template v-if="record.runs.length > 1"> ({{ record.runs.length }})</template>
            </span>
            <!-- eslint-disable vue/no-v-html -->
            <span
              class="text-muted-foreground"
              v-html="' — ' + previewHtml(record)"
            />
            <!-- eslint-enable vue/no-v-html -->
          </span>
        </button>

        <div
          v-if="expanded.has(record.node_id)"
          class="px-2 pb-2"
        >
          <div
            v-if="record.runs.length > 1"
            class="mb-1 flex items-center justify-center gap-2 text-xs text-muted-foreground"
          >
            <button
              type="button"
              class="rounded p-0.5 hover:bg-muted disabled:opacity-40"
              :disabled="runIndex(record) === 0"
              @click.stop="setRunIndex(record, runIndex(record) - 1)"
            >
              <ChevronLeft class="h-3 w-3" />
            </button>
            <div class="relative inline-flex items-center">
              <select
                class="min-w-[5rem] appearance-none rounded border border-border bg-background py-0.5 pl-3 pr-7 text-center text-xs"
                :value="runIndex(record)"
                @change.stop="setRunIndex(record, Number(($event.target as HTMLSelectElement).value))"
              >
                <option
                  v-for="(_, i) in record.runs"
                  :key="i"
                  :value="i"
                >
                  {{ i + 1 }} / {{ record.runs.length }}
                </option>
              </select>
              <ChevronDown
                class="pointer-events-none absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground"
              />
            </div>
            <button
              type="button"
              class="rounded p-0.5 hover:bg-muted disabled:opacity-40"
              :disabled="runIndex(record) === record.runs.length - 1"
              @click.stop="setRunIndex(record, runIndex(record) + 1)"
            >
              <ChevronRight class="h-3 w-3" />
            </button>
          </div>

          <div class="relative rounded-md bg-muted/50 p-2">
            <button
              type="button"
              class="absolute right-1 top-1 z-10 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
              aria-label="Copy message"
              @click.stop="copy(record)"
            >
              <Check
                v-if="copiedId === record.node_id"
                class="h-3.5 w-3.5"
              />
              <Copy
                v-else
                class="h-3.5 w-3.5"
              />
            </button>
            <HighlightJsonView
              v-if="isJson(currentRun(record))"
              :value="parseJson(currentRun(record))"
              class="overflow-x-auto pr-6"
            />
            <!-- eslint-disable vue/no-v-html -->
            <div
              v-else
              class="max-w-none break-words pr-6 text-xs leading-relaxed [&_a]:underline [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_p]:my-1 [&_pre]:overflow-x-auto"
              v-html="renderMarkdown(currentRun(record))"
            />
            <!-- eslint-enable vue/no-v-html -->
          </div>
        </div>
      </div>
    </div>
  </div>

  <button
    v-else-if="collapsedVisible"
    type="button"
    data-testid="execution-highlights-open"
    class="absolute right-4 top-4 z-20 rounded-lg border border-border bg-background p-2 shadow-lg hover:bg-muted"
    title="Execution Highlights"
    aria-label="Open Execution Highlights"
    @click="dismissed = false"
  >
    <Sparkles class="h-4 w-4 text-violet-400" />
  </button>
</template>

<!-- Non-scoped so it also styles <mark> rendered via v-html. Light mode: darker
     violet; dark mode: lighter/brighter violet. -->
<style>
.hl-search-mark {
  background-color: rgba(124, 58, 237, 0.32);
  color: inherit;
  border-radius: 3px;
  padding: 0 2px;
}
.dark .hl-search-mark {
  background-color: rgba(167, 139, 250, 0.5);
}
</style>
