<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
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
  RefreshCw,
  Search,
  X,
} from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Select from "@/components/ui/Select.vue";
import { buildDisplayNodeResults, type DisplayNodeResult } from "@/lib/executionLog";
import { cn } from "@/lib/utils";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";
import type { ActiveExecutionItem, ExecutionHistoryEntry, NodeResult } from "@/types/workflow";

interface Props {
  open: boolean;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "close"): void;
}>();

const workflowStore = useWorkflowStore();
const selectedId = ref<string | null>(null);
const expandedNodes = ref<Set<string>>(new Set());
const activeExecutions = ref<ActiveExecutionItem[]>([]);
const isCancellingId = ref<string | null>(null);
const selectedTriggerSource = ref<string | undefined>(undefined);
const searchActive = ref(false);
const searchQuery = ref("");
const searchInputRef = ref<HTMLInputElement | null>(null);
let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;

const executionHistoryList = computed(
  () => workflowStore.executionHistoryList,
);
const executionHistoryTotal = computed(
  () => workflowStore.executionHistoryTotal,
);
const isHistoryLoading = computed(() => workflowStore.isHistoryLoading);
const isHistoryDetailLoading = computed(
  () => workflowStore.isHistoryDetailLoading,
);
const selectedEntry = computed<ExecutionHistoryEntry | null>(() => {
  if (!selectedId.value) return null;
  return workflowStore.executionHistoryDetails.get(selectedId.value) ?? null;
});

const nodeResults = computed<NodeResult[]>(() => {
  if (!selectedEntry.value?.result?.node_results) return [];
  return selectedEntry.value.result.node_results.filter(
    (node) => node.status !== "skipped"
  );
});

const displayNodeResults = computed<DisplayNodeResult[]>(() =>
  buildDisplayNodeResults(nodeResults.value),
);

const triggerSourceOptions = computed<Array<{ value: string | undefined; label: string }>>(() => {
  const sourceSet = new Set<string>();

  for (const entry of executionHistoryList.value) {
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

const filteredExecutionHistoryList = computed(() => executionHistoryList.value);
const hasActiveFilters = computed<boolean>(
  () => Boolean(searchQuery.value.trim()) || Boolean(selectedTriggerSource.value),
);

function isTypingTarget(target: EventTarget | null): boolean {
  if (!target) return false;
  const element = target as HTMLElement;
  return (
    element.tagName === "INPUT" ||
    element.tagName === "TEXTAREA" ||
    element.tagName === "SELECT" ||
    element.isContentEditable ||
    element.closest("input, textarea, select, [contenteditable]") !== null
  );
}

function getSearchValue(): string | undefined {
  const query = searchQuery.value.trim();
  return query.length > 0 ? query : undefined;
}

async function loadHistory(keepDetails = false): Promise<void> {
  activeExecutions.value = [];
  const currentId = workflowStore.currentWorkflow?.id ?? null;
  const [, allActive] = await Promise.allSettled([
    workflowStore.fetchExecutionHistory(selectedTriggerSource.value, {
      keepDetails,
      search: getSearchValue(),
    }),
    workflowApi.getActiveExecutions(),
  ]);
  if (allActive.status === "fulfilled") {
    activeExecutions.value = currentId
      ? allActive.value.filter((entry) => entry.workflow_id === currentId)
      : [];
  }
}

async function resetSelectionToFirstEntry(): Promise<void> {
  const firstId = executionHistoryList.value[0]?.id ?? null;
  selectedId.value = firstId;
  expandedNodes.value = new Set();
  if (firstId) {
    await workflowStore.fetchExecutionHistoryEntry(firstId);
  }
}

async function reloadHistoryWithFilters(): Promise<void> {
  await loadHistory();
  await resetSelectionToFirstEntry();
}

function handleKeyDown(event: KeyboardEvent): void {
  if (!props.open || isTypingTarget(event.target)) return;
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
      searchActive.value = false;
      searchQuery.value = "";
      await loadHistory();
      await resetSelectionToFirstEntry();
    } else {
      document.removeEventListener("keydown", handleKeyDown);
      selectedTriggerSource.value = undefined;
      searchActive.value = false;
      searchQuery.value = "";
      if (searchDebounceTimer) {
        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = null;
      }
      delete document.body.dataset.heymOverlayEscapeTrap;
    }
  }
);

watch(selectedTriggerSource, async () => {
  if (!props.open) return;
  await reloadHistoryWithFilters();
});

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

onUnmounted(() => {
  document.removeEventListener("keydown", handleKeyDown);
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
  }
  delete document.body.dataset.heymOverlayEscapeTrap;
});

function formatTime(value: string): string {
  return new Date(value).toLocaleString();
}

async function selectEntry(entryId: string): Promise<void> {
  selectedId.value = entryId;
  expandedNodes.value = new Set();
  await workflowStore.fetchExecutionHistoryEntry(entryId);
}

async function cancelActiveExecution(item: ActiveExecutionItem): Promise<void> {
  isCancellingId.value = item.execution_id;
  try {
    await workflowApi.cancelExecution(item.workflow_id, item.execution_id);
  } catch {
    // 404 = already finished, treat as success
  } finally {
    isCancellingId.value = null;
    // If the cancelled execution belongs to the currently open workflow,
    // also abort the live SSE stream so the canvas stops mid-run.
    if (workflowStore.isExecuting && workflowStore.currentWorkflow?.id === item.workflow_id) {
      await workflowStore.stopExecution();
    }
    await refreshHistory();
  }
}

async function refreshHistory(): Promise<void> {
  const previousSelectedId = selectedId.value;
  await loadHistory(true);
  const newList = executionHistoryList.value;
  const stillExists =
    previousSelectedId !== null && newList.some((e) => e.id === previousSelectedId);
  if (!stillExists) {
    const firstId = newList[0]?.id ?? null;
    selectedId.value = firstId;
    expandedNodes.value = new Set();
    if (firstId && !workflowStore.executionHistoryDetails.has(firstId)) {
      await workflowStore.fetchExecutionHistoryEntry(firstId);
    }
  } else if (!workflowStore.executionHistoryDetails.has(previousSelectedId!)) {
    await workflowStore.fetchExecutionHistoryEntry(previousSelectedId!);
  }
}

function clearHistory(): void {
  void workflowStore.clearExecutionHistory();
  selectedId.value = null;
  selectedTriggerSource.value = undefined;
  searchActive.value = false;
  searchQuery.value = "";
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
  }
}

function toggleSearch(): void {
  searchActive.value = !searchActive.value;
  if (searchActive.value) {
    nextTick(() => searchInputRef.value?.focus());
  } else if (searchQuery.value) {
    searchQuery.value = "";
    void reloadHistoryWithFilters();
  }
}

function onSearchInput(event: Event): void {
  searchQuery.value = (event.target as HTMLInputElement).value;
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
  }
  searchDebounceTimer = setTimeout(() => {
    void reloadHistoryWithFilters();
  }, 300);
}

function clearSearch(): void {
  searchQuery.value = "";
  if (searchDebounceTimer) {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = null;
  }
  void reloadHistoryWithFilters();
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
  void reloadHistoryWithFilters();
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
  source?: string;
  mcp_server?: string;
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

function getHitlReviewUrl(output: unknown): string | null {
  const o = output as Record<string, unknown> | undefined;
  const reviewUrl = o?.reviewUrl;
  return typeof reviewUrl === "string" ? reviewUrl : null;
}

function getHitlShareMarkdown(output: unknown): string | null {
  const o = output as Record<string, unknown> | undefined;
  const shareMarkdown = o?.shareMarkdown;
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
  for (const node of displayNodeResults.value) {
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
  if (!selectedEntry.value) return;
  const nodeResultsFromHistory = selectedEntry.value.result?.node_results || [];
  const executionResultFromHistory = selectedEntry.value.result || undefined;
  workflowStore.loadHistoryInputs(selectedEntry.value.inputs, nodeResultsFromHistory, executionResultFromHistory);
  emit("close");
}
</script>

<template>
  <Dialog
    :open="open"
    title="Execution History"
    size="4xl"
    :close-on-escape="!searchActive || !searchQuery"
    @close="emit('close')"
    @escape="handleDialogEscape"
  >
    <!-- Top bar: count, filter, actions -->
    <div class="flex items-start justify-between gap-3 mb-4 shrink-0">
      <div class="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center">
        <p class="text-sm text-muted-foreground flex items-center gap-2 shrink-0">
          <template v-if="isHistoryLoading">
            <Loader2 class="w-3 h-3 animate-spin" />
            Loading...
          </template>
          <template v-else>
            {{ executionHistoryTotal }} run(s)
          </template>
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
      <div class="flex items-center gap-1 shrink-0">
        <Button
          variant="ghost"
          size="sm"
          :disabled="isHistoryLoading"
          @click="refreshHistory"
        >
          <RefreshCw
            class="w-4 h-4"
            :class="{ 'animate-spin': isHistoryLoading }"
          />
        </Button>
        <Button
          v-if="executionHistoryTotal > 0 || selectedTriggerSource || searchQuery"
          variant="outline"
          size="sm"
          :class="searchActive ? 'border-primary/60 bg-primary/10' : ''"
          @click="toggleSearch"
        >
          <Search class="w-4 h-4" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          class="gap-2"
          :disabled="executionHistoryTotal === 0 && !hasActiveFilters"
          @click="clearHistory"
        >
          <Trash2 class="w-4 h-4" />
          Clear history
        </Button>
      </div>
    </div>

    <div
      v-if="searchActive"
      class="flex flex-col gap-3 mb-4 sm:flex-row sm:items-center"
    >
      <div class="relative flex-1">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        <input
          ref="searchInputRef"
          :value="searchQuery"
          type="text"
          placeholder="Search by status, tag, inputs, outputs..."
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

    <!-- Empty state -->
    <div
      v-if="executionHistoryTotal === 0 && activeExecutions.length === 0 && !hasActiveFilters"
      class="text-sm text-muted-foreground text-center py-16"
    >
      No executions yet.
    </div>

    <!-- Two-column layout -->
    <div
      v-else
      class="flex gap-4 min-h-0 h-[60vh]"
    >
      <!-- LEFT: run list -->
      <div class="w-64 shrink-0 flex flex-col overflow-hidden border-r border-border/40 pr-3">
        <!-- Active executions -->
        <div
          v-if="activeExecutions.length > 0"
          class="space-y-1 mb-2 shrink-0"
        >
          <div
            v-for="active in activeExecutions"
            :key="active.execution_id"
            class="flex items-center justify-between gap-2 p-2 rounded-md border border-blue-500/30 bg-blue-500/10"
          >
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <Loader2 class="w-3 h-3 text-blue-400 animate-spin shrink-0" />
                <span class="text-xs font-medium text-blue-400">Running</span>
              </div>
              <div class="text-[10px] text-muted-foreground mt-0.5 pl-4 truncate">
                {{ formatTime(active.started_at) }}
              </div>
            </div>
            <Button
              variant="destructive"
              size="sm"
              class="h-5 px-1.5 shrink-0 text-[10px]"
              :disabled="isCancellingId === active.execution_id"
              @click="cancelActiveExecution(active)"
            >
              <Loader2
                v-if="isCancellingId === active.execution_id"
                class="w-3 h-3 animate-spin mr-0.5"
              />
              Cancel
            </Button>
          </div>
          <div
            v-if="executionHistoryTotal > 0"
            class="border-t border-border/40 my-1"
          />
        </div>

        <!-- No filter matches -->
        <div
          v-if="filteredExecutionHistoryList.length === 0 && hasActiveFilters"
          class="text-xs text-muted-foreground text-center py-6"
        >
          No runs match the current filters.
        </div>

        <!-- Run list -->
        <div
          v-else
          class="overflow-y-auto flex-1 space-y-1 pr-1"
        >
          <button
            v-for="entry in filteredExecutionHistoryList"
            :key="entry.id"
            class="w-full text-left p-2.5 rounded-md border bg-muted/20 hover:bg-muted/40 transition-colors"
            :class="cn(selectedEntry?.id === entry.id && 'border-primary/60 bg-primary/10')"
            @click="selectEntry(entry.id)"
          >
            <div class="flex items-center gap-1.5 min-w-0">
              <component
                :is="getStatusIcon(entry.status)"
                class="w-3.5 h-3.5 shrink-0"
                :class="entry.status === 'success' ? 'text-emerald-500' : entry.status === 'error' ? 'text-red-500' : 'text-amber-500'"
              />
              <span class="text-xs font-medium truncate flex-1">{{ formatTime(entry.started_at) }}</span>
            </div>
            <div class="flex items-center gap-1.5 mt-0.5 pl-5">
              <span class="text-[10px] text-muted-foreground">
                <template v-if="entry.status === 'pending'">Pending review</template>
                <template v-else>{{ entry.execution_time_ms.toFixed(2) }}ms</template>
              </span>
              <span
                v-if="entry.trigger_source"
                class="px-1 py-0 text-[9px] font-semibold rounded bg-violet-500/20 text-violet-400 uppercase"
              >
                {{ entry.trigger_source }}
              </span>
            </div>
          </button>
        </div>
      </div>

      <!-- RIGHT: execution detail -->
      <div class="flex-1 min-w-0 overflow-y-auto">
        <div
          v-if="isHistoryDetailLoading && !selectedEntry"
          class="flex items-center justify-center h-full text-sm text-muted-foreground gap-2"
        >
          <Loader2 class="w-4 h-4 animate-spin" />
          Loading details...
        </div>
        <div
          v-else-if="!selectedEntry"
          class="flex items-center justify-center h-full text-sm text-muted-foreground"
        >
          Select an execution to view details.
        </div>
        <div
          v-else
          class="space-y-3 pr-1"
          :class="{ 'opacity-50 pointer-events-none': isHistoryDetailLoading }"
        >
          <!-- Inputs -->
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
          <pre class="text-xs bg-muted/30 p-3 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all">{{ JSON.stringify(selectedEntry?.inputs ?? {}, null, 2) }}</pre>

          <!-- Outputs -->
          <div class="flex items-center justify-between">
            <div class="text-sm font-semibold">
              Outputs
            </div>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 px-2 gap-1"
              @click="copyToClipboard(selectedEntry?.result?.outputs ?? {}, 'outputs')"
            >
              <component
                :is="copiedField === 'outputs' ? Check : Copy"
                class="w-3 h-3"
              />
              <span class="text-xs">{{ copiedField === 'outputs' ? 'Copied' : 'Copy' }}</span>
            </Button>
          </div>
          <pre class="text-xs bg-muted/30 p-3 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all">{{ JSON.stringify(selectedEntry?.result?.outputs ?? {}, null, 2) }}</pre>

          <!-- Node Execution Logs -->
          <div
            v-if="nodeResults.length > 0"
            class="space-y-2"
          >
            <div class="flex items-center justify-between">
              <div class="text-sm font-semibold">
                Node Execution Logs
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

            <div class="space-y-1">
              <div
                v-for="node in displayNodeResults"
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
                    <pre class="text-xs bg-red-500/10 text-red-400 p-2 rounded-md whitespace-pre-wrap break-all">{{ node.error }}</pre>
                  </div>

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
                        <div class="flex items-center gap-2 flex-wrap">
                          <span class="font-medium text-primary">
                            {{ tc.name }}({{ JSON.stringify(tc.arguments) }})
                          </span>
                          <span
                            v-if="tc.source === 'mcp'"
                            class="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary"
                          >
                            MCP{{ tc.mcp_server ? `: ${tc.mcp_server}` : '' }}
                          </span>
                          <span
                            v-else-if="tc.source === 'skill'"
                            class="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary"
                          >
                            Skill
                          </span>
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
                    <pre class="text-xs bg-muted/30 p-2 rounded-md max-h-40 overflow-auto whitespace-pre-wrap break-all">{{ formatOutput(node.output) }}</pre>
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
