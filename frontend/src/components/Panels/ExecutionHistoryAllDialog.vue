<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  ArrowDownToLine,
  ChevronDown,
  ChevronRight,
  Clock,
  Loader2,
  Trash2,
  CheckCircle2,
  XCircle,
  SkipForward,
  Circle,
  Copy,
  Check,
  ExternalLink,
  Search,
  X,
  RefreshCw,
} from "lucide-vue-next";

import type {
  ActiveExecutionItem,
  AllExecutionHistoryEntry,
  AllExecutionHistoryEntryLight,
  NodeResult,
} from "@/types/workflow";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Select from "@/components/ui/Select.vue";
import { buildDisplayNodeResults, type DisplayNodeResult } from "@/lib/executionLog";
import { cn } from "@/lib/utils";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

interface Props {
  open: boolean;
  workflowId?: string;
  initialStatus?: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "close"): void;
}>();

const router = useRouter();
const workflowStore = useWorkflowStore();

const executionHistory = ref<AllExecutionHistoryEntryLight[]>([]);
const totalCount = ref(0);
const entryDetailsCache = ref<Map<string, AllExecutionHistoryEntry>>(new Map());
const selectedId = ref<string | null>(null);
const loading = ref(false);
const isRefreshing = ref(false);
const detailLoading = ref(false);
const clearing = ref(false);
const error = ref("");
const expandedNodes = ref<Set<string>>(new Set());
const detailContainerRef = ref<HTMLDivElement | null>(null);
const capturedMinHeight = ref<number | null>(null);
const searchActive = ref(false);
const searchQuery = ref("");
const selectedTriggerSource = ref<string | undefined>(undefined);
const searchInputRef = ref<HTMLInputElement | null>(null);
let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;
const activeExecutions = ref<ActiveExecutionItem[]>([]);
const isCancellingId = ref<string | null>(null);

const selectedEntry = computed<AllExecutionHistoryEntry | null>(() => {
  if (!selectedId.value) return null;
  return entryDetailsCache.value.get(selectedId.value) ?? null;
});

const nodeResults = computed<NodeResult[]>(() => {
  if (!selectedEntry.value?.node_results) return [];
  return selectedEntry.value.node_results.filter(
    (node) => node.status !== "skipped"
  );
});

const isChatRun = computed<boolean>(() => {
  const runType = selectedEntry.value?.run_type;
  return runType === "dashboard_chat" || runType === "workflow_assistant";
});

/** Steps to show: node_results for workflow, or one synthetic step for chat. */
const stepsForDisplay = computed<NodeResult[]>(() => {
  if (!selectedEntry.value) return [];
  if (nodeResults.value.length > 0) return nodeResults.value;
  if (isChatRun.value && selectedEntry.value.outputs) {
    const out = selectedEntry.value.outputs as { text?: string };
    const errMsg = selectedEntry.value.status === "error" ? (out.text ?? "Error") : null;
    return [
      {
        node_id: "chat-response",
        node_label: "Assistant response",
        node_type: "chat",
        status: (selectedEntry.value.status === "error" ? "error" : "success") as NodeResult["status"],
        output: selectedEntry.value.outputs as Record<string, unknown>,
        execution_time_ms: selectedEntry.value.execution_time_ms,
        error: errMsg,
      },
    ];
  }
  return [];
});

const triggerSourceOptions = computed<Array<{ value: string | undefined; label: string }>>(() => {
  const sourceSet = new Set<string>();

  for (const entry of executionHistory.value) {
    const source = entry.trigger_source?.trim();
    if (source) {
      sourceSet.add(source);
    }
  }

  const selectedSource = selectedTriggerSource.value?.trim();
  if (selectedSource) {
    sourceSet.add(selectedSource);
  }

  return [
    { value: undefined, label: "All Tags" },
    ...Array.from(sourceSet)
      .sort((left, right) => left.localeCompare(right))
      .map((source) => ({ value: source, label: source })),
  ];
});

const displaySteps = computed<DisplayNodeResult[]>(() =>
  buildDisplayNodeResults(stepsForDisplay.value),
);

const filteredExecutionHistory = computed<AllExecutionHistoryEntryLight[]>(() => {
  if (!selectedTriggerSource.value) {
    return executionHistory.value;
  }

  return executionHistory.value.filter(
    (entry) => entry.trigger_source === selectedTriggerSource.value,
  );
});

const hasActiveFilters = computed<boolean>(
  () => Boolean(searchQuery.value.trim()) || Boolean(selectedTriggerSource.value),
);

async function ensureEntryLoaded(entryId: string): Promise<void> {
  if (entryDetailsCache.value.has(entryId)) return;
  detailLoading.value = true;
  try {
    const entry = await workflowApi.getHistoryEntry(entryId);
    const cache = new Map(entryDetailsCache.value);
    cache.set(entryId, entry);
    entryDetailsCache.value = cache;
  } catch {
    error.value = "Failed to load entry details";
  } finally {
    detailLoading.value = false;
  }
}

async function loadHistory(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [historyResult, activeResult] = await Promise.allSettled([
      workflowApi.getAllHistory(
        50,
        0,
        searchQuery.value || undefined,
        props.initialStatus || undefined,
        selectedTriggerSource.value,
        props.workflowId,
      ),
      workflowApi.getActiveExecutions(),
    ]);
    if (historyResult.status === "fulfilled") {
      executionHistory.value = historyResult.value.items;
      totalCount.value = historyResult.value.total;
      selectedId.value = historyResult.value.items[0]?.id ?? null;
      if (selectedId.value) {
        await ensureEntryLoaded(selectedId.value);
      }
    } else {
      executionHistory.value = [];
      totalCount.value = 0;
      error.value = "Failed to load history";
    }
    activeExecutions.value =
      activeResult.status === "fulfilled" ? activeResult.value : [];
  } finally {
    loading.value = false;
  }
}

function handleKeyDown(event: KeyboardEvent): void {
  if (!props.open) return;
  const tag = (event.target as HTMLElement)?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (event.key === "s" || event.key === "S") {
    event.preventDefault();
    toggleSearch();
  }
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
    } else {
      document.removeEventListener("keydown", handleKeyDown);
      searchActive.value = false;
      searchQuery.value = "";
      selectedTriggerSource.value = undefined;
      delete document.body.dataset.heymOverlayEscapeTrap;
      return;
    }
    capturedMinHeight.value = null;
    loading.value = true;
    error.value = "";
    expandedNodes.value = new Set();
    entryDetailsCache.value = new Map();
    searchActive.value = false;
    searchQuery.value = "";
    selectedTriggerSource.value = undefined;
    await loadHistory();
  }
);

watch(
  [() => props.open, searchActive, searchQuery],
  ([open, active, query]) => {
    if (open && active && query.length > 0) {
      document.body.dataset.heymOverlayEscapeTrap = "true";
      return;
    }

    delete document.body.dataset.heymOverlayEscapeTrap;
  },
  { immediate: true },
);

watch(selectedTriggerSource, async () => {
  if (!props.open) return;

  entryDetailsCache.value = new Map();
  expandedNodes.value = new Set();
  await loadHistory();
});

watch(filteredExecutionHistory, async (items) => {
  if (items.some((entry) => entry.id === selectedId.value)) {
    return;
  }

  const nextId = items[0]?.id ?? null;
  selectedId.value = nextId;
  expandedNodes.value = new Set();

  if (nextId) {
    await ensureEntryLoaded(nextId);
  }
});

onUnmounted(() => {
  document.removeEventListener("keydown", handleKeyDown);
  delete document.body.dataset.heymOverlayEscapeTrap;
});

watch(
  [() => selectedEntry.value, () => detailLoading.value],
  ([entry, loading]) => {
    if (entry && !loading && capturedMinHeight.value === null) {
      nextTick(() => {
        if (detailContainerRef.value) {
          capturedMinHeight.value = detailContainerRef.value.offsetHeight;
        }
      });
    }
  },
  { flush: "post" }
);

function formatTime(value: string): string {
  return new Date(value).toLocaleString();
}

async function selectEntry(entryId: string): Promise<void> {
  selectedId.value = entryId;
  expandedNodes.value = new Set();
  await ensureEntryLoaded(entryId);
}

async function refreshHistory(): Promise<void> {
  isRefreshing.value = true;
  const previousSelectedId = selectedId.value;
  const previousCache = new Map(entryDetailsCache.value);
  error.value = "";
  try {
    const [historyResult, activeResult] = await Promise.allSettled([
      workflowApi.getAllHistory(
        50,
        0,
        searchQuery.value || undefined,
        props.initialStatus || undefined,
        selectedTriggerSource.value,
        props.workflowId,
      ),
      workflowApi.getActiveExecutions(),
    ]);
    if (historyResult.status === "fulfilled") {
      const newItems = historyResult.value.items;
      executionHistory.value = newItems;
      totalCount.value = historyResult.value.total;
      // Keep only cache entries that are still in the new list.
      const newCache = new Map<string, AllExecutionHistoryEntry>();
      for (const [k, v] of previousCache) {
        if (newItems.some((item) => item.id === k)) {
          newCache.set(k, v);
        }
      }
      entryDetailsCache.value = newCache;
      // Keep current selection if still present, else pick first.
      const stillExists =
        previousSelectedId !== null && newItems.some((item) => item.id === previousSelectedId);
      if (!stillExists) {
        const firstId = newItems[0]?.id ?? null;
        selectedId.value = firstId;
        expandedNodes.value = new Set();
        if (firstId) {
          await ensureEntryLoaded(firstId);
        }
      } else if (!newCache.has(previousSelectedId!)) {
        await ensureEntryLoaded(previousSelectedId!);
      }
    } else {
      error.value = "Failed to refresh history";
    }
    activeExecutions.value =
      activeResult.status === "fulfilled" ? activeResult.value : [];
  } finally {
    isRefreshing.value = false;
  }
}

async function clearAllHistory(): Promise<void> {
  if (!confirm("Are you sure you want to clear all execution history?")) return;
  clearing.value = true;
  try {
    await workflowApi.clearAllHistory();
    executionHistory.value = [];
    totalCount.value = 0;
    entryDetailsCache.value = new Map();
    selectedId.value = null;
    selectedTriggerSource.value = undefined;
  } catch {
    error.value = "Failed to clear history";
  } finally {
    clearing.value = false;
  }
}

async function cancelActiveExecution(item: ActiveExecutionItem): Promise<void> {
  isCancellingId.value = item.execution_id;
  try {
    await workflowApi.cancelExecution(item.workflow_id, item.execution_id);
  } catch {
    // 404 = already finished
  } finally {
    isCancellingId.value = null;
    // If the cancelled execution belongs to the currently open workflow,
    // also abort the live SSE stream so the canvas stops mid-run.
    if (workflowStore.isExecuting && workflowStore.currentWorkflow?.id === item.workflow_id) {
      await workflowStore.stopExecution();
    }
    await loadHistory();
  }
}

function toggleSearch(): void {
  searchActive.value = !searchActive.value;
  if (searchActive.value) {
    nextTick(() => searchInputRef.value?.focus());
  } else if (searchQuery.value) {
    searchQuery.value = "";
    loadHistory();
  }
}

function onSearchInput(event: Event): void {
  searchQuery.value = (event.target as HTMLInputElement).value;
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    loadHistory();
  }, 300);
}

function clearSearch(): void {
  searchQuery.value = "";
  loadHistory();
  searchInputRef.value?.focus();
}

function handleDialogEscape(event: KeyboardEvent): void {
  if (!searchActive.value || !searchQuery.value) {
    return;
  }

  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
  }

  event.preventDefault();
  event.stopImmediatePropagation();
  searchQuery.value = "";
  searchActive.value = false;
  void loadHistory();
}

function toggleNode(nodeKey: string): void {
  const newSet = new Set(expandedNodes.value);
  if (newSet.has(nodeKey)) {
    newSet.delete(nodeKey);
  } else {
    newSet.add(nodeKey);
  }
  expandedNodes.value = newSet;
  if (newSet.has(nodeKey)) {
    nextTick(() => {
      const el = document.querySelector(`[data-node-key="${nodeKey}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }
}

function isNodeExpanded(nodeKey: string): boolean {
  return expandedNodes.value.has(nodeKey);
}

function getStatusIcon(status: string): typeof CheckCircle2 {
  switch (status) {
    case "success":
      return CheckCircle2;
    case "error":
      return XCircle;
    case "pending":
      return Clock;
    case "skipped":
      return SkipForward;
    default:
      return Circle;
  }
}

function getStatusColor(status: string): string {
  switch (status) {
    case "success":
      return "text-emerald-500";
    case "error":
      return "text-red-500";
    case "pending":
      return "text-amber-500";
    case "skipped":
      return "text-amber-500";
    default:
      return "text-muted-foreground";
  }
}

function formatOutput(output: Record<string, unknown>): string {
  return JSON.stringify(output, null, 2);
}

interface ToolCallEntry {
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
}

function getToolCalls(output: unknown): ToolCallEntry[] | undefined {
  const o = output as Record<string, unknown> | undefined;
  const arr = o?.tool_calls;
  return Array.isArray(arr) ? (arr as ToolCallEntry[]) : undefined;
}

function getSkillsUsed(output: unknown): string[] | undefined {
  const o = output as Record<string, unknown> | undefined;
  const arr = o?.skills_used;
  return Array.isArray(arr) ? (arr as string[]) : undefined;
}

/** True when step is from chat run (tool/assistant step with request + response_summary). */
function isChatStepOutput(output: Record<string, unknown>): boolean {
  return typeof (output as { response_summary?: unknown }).response_summary !== "undefined";
}

function getStepRequest(output: Record<string, unknown>): Record<string, unknown> {
  const req = (output as { request?: Record<string, unknown> }).request;
  return req && typeof req === "object" ? req : {};
}

function getStepResponseSummary(output: Record<string, unknown>): string {
  const s = (output as { response_summary?: string }).response_summary;
  return typeof s === "string" ? s : "";
}

function getHitlReviewUrl(output: unknown): string | null {
  const reviewUrl = (output as { reviewUrl?: unknown } | undefined)?.reviewUrl;
  return typeof reviewUrl === "string" ? reviewUrl : null;
}

function getHitlShareMarkdown(output: unknown): string | null {
  const shareMarkdown = (output as { shareMarkdown?: unknown } | undefined)?.shareMarkdown;
  return typeof shareMarkdown === "string" ? shareMarkdown : null;
}

interface HITLResolvedPayload {
  decision: "accepted" | "edited" | "refused";
  summary?: string;
  reviewText?: string;
  originalDraft?: string;
  editedText?: string;
  refusalReason?: string;
  approvedMarkdown?: string;
  requestId?: string;
}

function normalizeHitlResolvedPayload(output: unknown): HITLResolvedPayload | null {
  const o = output as Record<string, unknown> | undefined;
  if (!o || typeof o.decision !== "string") return null;
  if (!["accepted", "edited", "refused"].includes(o.decision)) return null;
  return {
    decision: o.decision as HITLResolvedPayload["decision"],
    summary: typeof o.summary === "string" ? o.summary : undefined,
    reviewText: typeof o.reviewText === "string" ? o.reviewText : undefined,
    originalDraft: typeof o.originalDraft === "string" ? o.originalDraft : undefined,
    editedText: typeof o.editedText === "string" ? o.editedText : undefined,
    refusalReason: typeof o.refusalReason === "string" ? o.refusalReason : undefined,
    approvedMarkdown:
      typeof o.approvedMarkdown === "string" ? o.approvedMarkdown : undefined,
    requestId: typeof o.requestId === "string" ? o.requestId : undefined,
  };
}

function getHitlHistory(output: unknown): HITLResolvedPayload[] {
  const o = output as Record<string, unknown> | undefined;
  const rawHistory = o?.hitlHistory;
  if (Array.isArray(rawHistory)) {
    return rawHistory
      .map(entry => normalizeHitlResolvedPayload(entry))
      .filter((entry): entry is HITLResolvedPayload => entry !== null);
  }
  const single = normalizeHitlResolvedPayload(output);
  return single ? [single] : [];
}

function getHitlDecisionLabel(decision: HITLResolvedPayload["decision"]): string {
  switch (decision) {
    case "accepted":
      return "Accepted";
    case "edited":
      return "Edited";
    case "refused":
      return "Refused";
  }
}

function getHitlDecisionText(payload: HITLResolvedPayload): string | null {
  if (payload.decision === "edited") {
    return payload.editedText || payload.reviewText || payload.approvedMarkdown || null;
  }
  if (payload.decision === "accepted") {
    return payload.reviewText || payload.approvedMarkdown || payload.originalDraft || null;
  }
  return payload.refusalReason || payload.reviewText || null;
}

function expandAll(): void {
  const newSet = new Set<string>();
  for (const node of displaySteps.value) {
    newSet.add(node.displayKey);
  }
  expandedNodes.value = newSet;
}

function collapseAll(): void {
  expandedNodes.value = new Set();
}

const copiedField = ref<string | null>(null);

async function copyToClipboard(content: unknown, field: string): Promise<void> {
  try {
    const text = typeof content === "string" ? content : JSON.stringify(content, null, 2);
    await navigator.clipboard.writeText(text);
    copiedField.value = field;
    setTimeout(() => {
      copiedField.value = null;
    }, 2000);
  } catch {
    // Clipboard API failed
  }
}

const pendingHitlUrl = computed<string | null>(() => {
  if (selectedEntry.value?.status !== "pending") return null;
  for (const node of nodeResults.value) {
    const url = getHitlReviewUrl(node.output);
    if (url) return url;
  }
  return null;
});

function openExternal(url: string): void {
  window.open(url, "_blank", "noopener");
}

function bringToCanvas(): void {
  if (!selectedEntry.value?.workflow_id) return;
  workflowStore.pendingHistoryInputs = selectedEntry.value.inputs;
  workflowStore.pendingHistoryNodeResults = selectedEntry.value.node_results || [];
  workflowStore.pendingHistoryExecutionResult = {
    workflow_id: selectedEntry.value.workflow_id,
    status:
      selectedEntry.value.status === "error"
        ? "error"
        : selectedEntry.value.status === "pending"
          ? "pending"
        : "success",
    outputs: selectedEntry.value.outputs,
    execution_time_ms: selectedEntry.value.execution_time_ms,
    node_results: selectedEntry.value.node_results || [],
    execution_history_id: selectedEntry.value.id,
  };
  router.push({ name: "editor", params: { id: selectedEntry.value.workflow_id } });
  emit("close");
}
</script>

<template>
  <Dialog
    :open="open"
    title="All Execution History"
    size="4xl"
    :close-on-escape="!searchActive || !searchQuery"
    @close="emit('close')"
    @escape="handleDialogEscape"
  >
    <div class="space-y-4">
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
          <p class="text-sm text-muted-foreground shrink-0">
            {{ totalCount }} run(s)
          </p>
          <Select
            v-if="triggerSourceOptions.length > 1 || selectedTriggerSource"
            v-model="selectedTriggerSource"
            :options="triggerSourceOptions"
            placeholder=""
            class="w-full sm:w-56"
            clearable
            clear-aria-label="Clear tag filter"
          />
        </div>
        <div class="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            :disabled="loading"
            @click="refreshHistory"
          >
            <RefreshCw
              class="w-4 h-4"
              :class="{ 'animate-spin': loading }"
            />
          </Button>
          <Button
            v-if="totalCount > 0 || selectedTriggerSource || searchQuery"
            variant="outline"
            size="sm"
            :class="searchActive ? 'border-primary/60 bg-primary/10' : ''"
            @click="toggleSearch"
          >
            <Search class="w-4 h-4" />
          </Button>
          <Button
            v-if="totalCount > 0 || selectedTriggerSource || searchQuery"
            variant="destructive"
            size="sm"
            :loading="clearing"
            @click="clearAllHistory"
          >
            <Trash2 class="w-4 h-4 mr-1" />
            Clear All
          </Button>
        </div>
      </div>

      <div
        v-if="searchActive"
        class="flex flex-col gap-3 sm:flex-row sm:items-center"
      >
        <div
          class="relative flex-1"
        >
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
          <input
            ref="searchInputRef"
            :value="searchQuery"
            type="text"
            placeholder="Search by workflow name, trigger, status..."
            class="w-full pl-9 pr-8 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
            @input="onSearchInput"
          >
          <button
            v-if="searchQuery"
            class="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            type="button"
            @click="clearSearch"
          >
            <X class="w-4 h-4" />
          </button>
        </div>
      </div>

      <div
        v-if="loading && !isRefreshing"
        class="text-sm text-muted-foreground text-center py-8"
      >
        Loading history...
      </div>

      <div
        v-else-if="error && !isRefreshing"
        class="text-sm text-destructive text-center py-8"
      >
        {{ error }}
      </div>

      <div
        v-else-if="totalCount === 0 && activeExecutions.length === 0 && !hasActiveFilters && !isRefreshing"
        class="text-sm text-muted-foreground text-center py-8"
      >
        No executions yet.
      </div>

      <div
        v-else
        class="grid gap-4"
        :class="{ 'opacity-50 pointer-events-none': isRefreshing }"
      >
        <!-- Running executions -->
        <div
          v-if="activeExecutions.length > 0"
          class="space-y-1"
        >
          <div
            v-for="active in activeExecutions"
            :key="active.execution_id"
            class="flex items-center justify-between gap-3 p-2.5 rounded-md border border-blue-500/30 bg-blue-500/10"
          >
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <Loader2 class="w-4 h-4 text-blue-400 animate-spin shrink-0" />
                <span class="text-sm font-medium text-blue-400">Running</span>
                <span class="text-sm text-muted-foreground truncate">
                  {{ formatTime(active.started_at) }}
                </span>
              </div>
              <div class="text-xs text-muted-foreground mt-0.5 pl-6">
                {{ active.workflow_name }} · In progress...
              </div>
            </div>
            <Button
              variant="destructive"
              size="sm"
              class="h-6 px-2 shrink-0 text-xs"
              :disabled="isCancellingId === active.execution_id"
              @click="cancelActiveExecution(active)"
            >
              <Loader2
                v-if="isCancellingId === active.execution_id"
                class="w-3 h-3 animate-spin mr-1"
              />
              Cancel
            </Button>
          </div>
          <div
            v-if="totalCount > 0 || executionHistory.length > 0"
            class="border-t border-border/40 my-1"
          />
        </div>

        <div
          v-if="filteredExecutionHistory.length === 0 && hasActiveFilters"
          class="text-sm text-muted-foreground text-center py-4"
        >
          No runs match the current filters.
        </div>
        <div
          v-else-if="totalCount > 0"
          class="space-y-2 max-h-48 overflow-auto pr-2"
        >
          <button
            v-for="entry in filteredExecutionHistory"
            :key="entry.id"
            class="w-full text-left p-3 rounded-md border bg-muted/20 hover:bg-muted/40 transition-colors"
            :class="cn(selectedEntry?.id === entry.id && 'border-primary/60 bg-primary/10')"
            @click="selectEntry(entry.id)"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <Clock class="w-4 h-4 text-muted-foreground shrink-0" />
                <span class="text-sm font-medium truncate">{{ formatTime(entry.started_at) }}</span>
                <span
                  v-if="entry.trigger_source"
                  class="px-1.5 py-0.5 text-[10px] font-semibold rounded bg-violet-500/20 text-violet-400 uppercase shrink-0 hidden sm:inline"
                >
                  {{ entry.trigger_source }}
                </span>
              </div>
              <component
                :is="getStatusIcon(entry.status)"
                class="w-5 h-5 shrink-0"
                :class="entry.status === 'success' ? 'text-emerald-500' : entry.status === 'error' ? 'text-red-500' : 'text-amber-500'"
              />
            </div>
            <div class="text-xs text-muted-foreground mt-1">
              <template v-if="entry.status === 'pending'">
                {{ entry.workflow_name }} · Pending human review
              </template>
              <template v-else>
                {{ entry.workflow_name }} · {{ entry.execution_time_ms.toFixed(2) }}ms
              </template>
            </div>
          </button>
        </div>

        <div
          ref="detailContainerRef"
          class="border-t pt-4 flex flex-col"
          :style="capturedMinHeight ? { minHeight: `${capturedMinHeight}px` } : undefined"
        >
          <div
            v-if="detailLoading && selectedId"
            class="text-sm text-muted-foreground text-center py-8 flex-1 flex items-center justify-center"
          >
            Loading details...
          </div>
          <div
            v-else-if="selectedEntry"
            class="space-y-3"
          >
            <div class="text-sm font-semibold">
              Workflow
            </div>
            <div class="text-sm text-muted-foreground">
              {{ selectedEntry?.workflow_name }}
            </div>
            <div class="flex items-center justify-between">
              <div class="text-sm font-semibold">
                Inputs
              </div>
              <div class="flex items-center gap-1">
                <Button
                  v-if="pendingHitlUrl"
                  variant="ghost"
                  size="sm"
                  class="h-6 px-2 gap-1 text-amber-500 hover:text-amber-400"
                  @click="openExternal(pendingHitlUrl)"
                >
                  <ExternalLink class="w-3 h-3" />
                  <span class="text-xs">HITL Review</span>
                </Button>
                <Button
                  v-if="!isChatRun"
                  variant="ghost"
                  size="sm"
                  class="h-6 px-2 gap-1"
                  @click="bringToCanvas"
                >
                  <ArrowDownToLine class="w-3 h-3" />
                  <span class="text-xs">Bring to Canvas</span>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-6 px-2 gap-1"
                  @click="copyToClipboard(selectedEntry?.inputs ?? {}, 'inputs')"
                >
                  <component
                    :is="copiedField === 'inputs' ? Check : Copy"
                    class="w-3 h-3"
                  />
                  <span class="text-xs">{{ copiedField === 'inputs' ? 'Copied' : 'Copy' }}</span>
                </Button>
              </div>
            </div>
            <pre class="text-xs bg-muted/30 p-3 rounded-md max-h-32 overflow-auto whitespace-pre-wrap break-all">{{ JSON.stringify(selectedEntry?.inputs ?? {}, null, 2) }}</pre>
            <div class="flex items-center justify-between">
              <div class="text-sm font-semibold">
                Outputs
              </div>
              <Button
                variant="ghost"
                size="sm"
                class="h-6 px-2 gap-1"
                @click="copyToClipboard(selectedEntry?.outputs ?? {}, 'outputs')"
              >
                <component
                  :is="copiedField === 'outputs' ? Check : Copy"
                  class="w-3 h-3"
                />
                <span class="text-xs">{{ copiedField === 'outputs' ? 'Copied' : 'Copy' }}</span>
              </Button>
            </div>
            <pre class="text-xs bg-muted/30 p-3 rounded-md max-h-32 overflow-auto whitespace-pre-wrap break-all">{{ JSON.stringify(selectedEntry?.outputs ?? {}, null, 2) }}</pre>

            <div
              v-if="stepsForDisplay.length > 0"
              class="space-y-2"
            >
              <div class="flex items-center justify-between">
                <div class="text-sm font-semibold">
                  Steps
                </div>
                <div class="flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-xs h-6 px-2"
                    @click="expandAll"
                  >
                    Expand All
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-xs h-6 px-2"
                    @click="collapseAll"
                  >
                    Collapse All
                  </Button>
                </div>
              </div>

              <div class="space-y-1 max-h-64 overflow-auto pr-1">
                <div
                  v-for="node in displaySteps"
                  :key="node.displayKey"
                  :data-node-key="node.displayKey"
                  class="border rounded-md overflow-hidden"
                >
                  <button
                    class="w-full flex items-center gap-2 p-2 text-left hover:bg-muted/30 transition-colors"
                    @click="toggleNode(node.displayKey)"
                  >
                    <component
                      :is="isNodeExpanded(node.displayKey) ? ChevronDown : ChevronRight"
                      class="w-4 h-4 text-muted-foreground shrink-0"
                    />
                    <component
                      :is="getStatusIcon(node.status)"
                      class="w-4 h-4 shrink-0"
                      :class="getStatusColor(node.status)"
                    />
                    <span class="text-sm font-medium truncate flex-1">
                      {{ node.node_label }}
                    </span>
                    <span
                      v-if="node.isRetryAttempt && node.retryAttempt && node.retryMaxAttempts"
                      class="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 shrink-0"
                    >
                      attempt {{ node.retryAttempt }}/{{ node.retryMaxAttempts }} failed
                    </span>
                    <span class="text-xs text-muted-foreground shrink-0">
                      {{ node.node_type }}
                    </span>
                    <span class="text-xs text-muted-foreground shrink-0">
                      {{ node.execution_time_ms.toFixed(2) }}ms
                    </span>
                  </button>

                  <div
                    v-if="isNodeExpanded(node.displayKey)"
                    class="border-t bg-muted/10 p-3 space-y-2"
                  >
                    <div
                      v-if="node.error"
                      class="space-y-1"
                    >
                      <div class="text-xs font-medium text-red-500">
                        Error
                      </div>
                      <div
                        v-if="Array.isArray((node.output as Record<string, unknown>)?.guardrail_violated_categories) && ((node.output as Record<string, unknown>).guardrail_violated_categories as string[]).length > 0"
                        class="text-xs font-medium mb-1"
                      >
                        Blocked by: {{ ((node.output as Record<string, unknown>).guardrail_violated_categories as string[]).join(", ") }}
                      </div>
                      <pre
                        class="text-xs bg-red-500/10 text-red-400 p-2 rounded-md whitespace-pre-wrap break-all"
                      >{{ node.error }}</pre>
                    </div>

                    <!-- Chat run steps: request + response summary -->
                    <template v-if="isChatStepOutput(node.output)">
                      <div
                        v-if="Object.keys(getStepRequest(node.output)).length > 0"
                        class="space-y-1"
                      >
                        <div class="text-xs font-medium text-muted-foreground">
                          Request
                        </div>
                        <pre
                          class="text-xs bg-muted/30 p-2 rounded-md max-h-24 overflow-auto whitespace-pre-wrap break-all"
                        >{{ formatOutput(getStepRequest(node.output)) }}</pre>
                      </div>
                      <div class="space-y-1">
                        <div class="text-xs font-medium text-muted-foreground">
                          Response
                        </div>
                        <pre
                          class="text-xs bg-muted/30 p-2 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all"
                        >{{ getStepResponseSummary(node.output) }}</pre>
                      </div>
                    </template>
                    <!-- Workflow node output (raw) -->
                    <div
                      v-else
                      class="space-y-2"
                    >
                      <div
                        v-if="getSkillsUsed(node.output)?.length"
                        class="space-y-1"
                      >
                        <div class="text-xs font-medium text-muted-foreground">
                          Skills Used
                        </div>
                        <div class="flex flex-wrap gap-1">
                          <span
                            v-for="(s, i) in getSkillsUsed(node.output)"
                            :key="i"
                            class="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary"
                          >
                            {{ s }}
                          </span>
                        </div>
                      </div>
                      <div
                        v-if="getToolCalls(node.output)?.length"
                        class="space-y-1"
                      >
                        <div class="text-xs font-medium text-muted-foreground">
                          Tool Calls
                        </div>
                        <div class="space-y-1.5">
                          <div
                            v-for="(tc, i) in getToolCalls(node.output)!"
                            :key="i"
                            class="rounded border border-border/50 bg-muted/20 p-2 text-xs"
                          >
                            <div class="font-medium text-primary">
                              {{ tc.name }}({{ JSON.stringify(tc.arguments) }})
                            </div>
                            <div class="mt-1 text-muted-foreground break-all">
                              → {{ typeof tc.result === 'object' ? JSON.stringify(tc.result) : tc.result }}
                            </div>
                          </div>
                        </div>
                      </div>
                      <div
                        v-if="getHitlHistory(node.output).length"
                        class="rounded border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs"
                      >
                        <div class="font-medium text-emerald-600 dark:text-emerald-300">
                          Human review history
                        </div>
                        <div class="mt-2 space-y-2">
                          <div
                            v-for="(entry, entryIndex) in getHitlHistory(node.output)"
                            :key="entry.requestId || `${node.node_id}-hitl-${entryIndex}`"
                            class="rounded border border-emerald-500/20 bg-background/60 p-2"
                          >
                            <div class="font-medium text-emerald-600 dark:text-emerald-300">
                              {{ getHitlDecisionLabel(entry.decision) }}
                            </div>
                            <div
                              v-if="entry.summary"
                              class="mt-1 whitespace-pre-wrap text-muted-foreground"
                            >
                              {{ entry.summary }}
                            </div>
                            <div
                              v-if="getHitlDecisionText(entry)"
                              class="mt-1 whitespace-pre-wrap text-muted-foreground"
                            >
                              {{ getHitlDecisionText(entry) }}
                            </div>
                          </div>
                        </div>
                      </div>
                      <div class="space-y-1">
                        <div class="flex items-center justify-between gap-2">
                          <div class="text-xs font-medium text-muted-foreground">
                            Output
                          </div>
                          <div
                            v-if="getHitlReviewUrl(node.output)"
                            class="flex gap-1"
                          >
                            <Button
                              v-if="getHitlShareMarkdown(node.output)"
                              variant="ghost"
                              size="sm"
                              class="h-6 px-2 gap-1"
                              @click="copyToClipboard(getHitlShareMarkdown(node.output), `share-${node.node_id}`)"
                            >
                              <Copy class="w-3 h-3" />
                              <span class="text-xs">Copy Share Text</span>
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              class="h-6 px-2 gap-1"
                              @click="copyToClipboard(getHitlReviewUrl(node.output), `review-${node.node_id}`)"
                            >
                              <Copy class="w-3 h-3" />
                              <span class="text-xs">Copy Review Link</span>
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              class="h-6 px-2 gap-1"
                              @click="openExternal(getHitlReviewUrl(node.output)!)"
                            >
                              <ExternalLink class="w-3 h-3" />
                              <span class="text-xs">Open</span>
                            </Button>
                          </div>
                        </div>
                        <pre
                          class="text-xs bg-muted/30 p-2 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all"
                        >{{ formatOutput(node.output) }}</pre>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Dialog>
</template>
