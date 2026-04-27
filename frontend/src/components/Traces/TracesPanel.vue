<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Check, ChevronLeft, ChevronRight, Clock, Copy, ExternalLink, RefreshCcw, Search, Trash2, X } from "lucide-vue-next";

import type { CredentialListItem } from "@/types/credential";
import type { LLMTraceDetail, LLMTraceListItem } from "@/types/trace";
import type { WorkflowListItem } from "@/types/workflow";

import TraceDurationChart, { type TraceSpan } from "@/components/Traces/TraceDurationChart.vue";
import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { cn, formatDate } from "@/lib/utils";
import { credentialsApi, traceApi, workflowApi } from "@/services/api";

interface SelectOption {
  value: string;
  label: string;
}

const traces = ref<LLMTraceListItem[]>([]);
const total = ref(0);
const limit = ref(25);
const offset = ref(0);
const loading = ref(false);
const error = ref("");

const credentials = ref<CredentialListItem[]>([]);
const workflows = ref<WorkflowListItem[]>([]);
const sourceFilter = ref("all");
const credentialFilter = ref("all");
const workflowFilter = ref("all");
const searchActive = ref(false);
const searchQuery = ref("");
const searchInputRef = ref<HTMLInputElement | null>(null);
let searchDebounceTimer: ReturnType<typeof setTimeout> | null = null;

const route = useRoute();
const router = useRouter();

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
const selectedTrace = ref<LLMTraceDetail | null>(null);
const selectedTraceIndex = ref(-1);
const clearing = ref(false);
const copiedRequest = ref(false);
const copiedResponse = ref(false);

const hasPreviousTrace = computed(() => selectedTraceIndex.value > 0);
const hasNextTrace = computed(
  () => selectedTraceIndex.value >= 0 && selectedTraceIndex.value < traces.value.length - 1,
);
const tracePositionLabel = computed(() =>
  selectedTraceIndex.value >= 0
    ? `${selectedTraceIndex.value + 1} / ${traces.value.length}`
    : "Direct trace",
);

interface ToolCallEntry {
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  elapsed_ms?: number;
  source?: string;
  mcp_server?: string;
}

function getToolCallsFromResponse(response: Record<string, unknown> | null): ToolCallEntry[] | undefined {
  const arr = response?.tool_calls;
  return Array.isArray(arr) ? (arr as ToolCallEntry[]) : undefined;
}

function getSkillsFromRequest(request: Record<string, unknown> | null): string[] | undefined {
  const arr = request?.skills_included;
  return Array.isArray(arr) ? (arr as string[]) : undefined;
}

function computeInvocationTotalMs(children: TraceSpan[]): number {
  if (children.length === 0) return 0;
  const llmSpan = children.find((s) => s.id === "call_llm" || s.label === "call_llm");
  const subAgentSpans = children.filter((s) => s.label === "call_sub_agent");
  const otherSpans = children.filter(
    (s) =>
      s.id !== "call_llm" &&
      s.label !== "call_llm" &&
      s.label !== "call_sub_agent"
  );
  let total = 0;
  if (llmSpan) total += llmSpan.durationMs;
  if (subAgentSpans.length > 0) {
    total += Math.max(...subAgentSpans.map((s) => s.durationMs));
  }
  total += otherSpans.reduce((acc, s) => acc + s.durationMs, 0);
  return total > 0 ? total : 0;
}

function buildTraceSpans(trace: LLMTraceDetail): TraceSpan[] {
  const response = trace.response as Record<string, unknown> | null | undefined;
  const timingBreakdown = response?.timing_breakdown as
    | { llm_ms?: number; tools_ms?: number; mcp_list_ms?: number }
    | undefined;

  const children: TraceSpan[] = [];

  if (timingBreakdown && typeof timingBreakdown === "object") {
    if (timingBreakdown.llm_ms != null && timingBreakdown.llm_ms > 0) {
      children.push({
        id: "call_llm",
        label: "call_llm",
        durationMs: timingBreakdown.llm_ms,
        depth: 1,
        icon: "llm",
      });
    }
    if (timingBreakdown.tools_ms != null && timingBreakdown.tools_ms > 0) {
      children.push({
        id: "tools",
        label: "tools",
        durationMs: timingBreakdown.tools_ms,
        depth: 1,
        icon: "tool",
      });
    }
    if (timingBreakdown.mcp_list_ms != null && timingBreakdown.mcp_list_ms > 0) {
      children.push({
        id: "mcp_list",
        label: "mcp_list",
        durationMs: timingBreakdown.mcp_list_ms,
        depth: 1,
        icon: "agent",
      });
    }
  } else {
    const responseElapsed = response?.elapsed_ms;
    if (
      typeof responseElapsed === "number" &&
      !Number.isNaN(responseElapsed) &&
      responseElapsed > 0
    ) {
      children.push({
        id: "call_llm",
        label: "call_llm",
        durationMs: responseElapsed,
        depth: 1,
        icon: "llm",
      });
    }

    const toolCalls = getToolCallsFromResponse(response ?? null);
    if (toolCalls?.length) {
      for (let i = 0; i < toolCalls.length; i++) {
        const tc = toolCalls[i];
        const ms = tc.elapsed_ms;
        if (typeof ms === "number" && !Number.isNaN(ms) && ms > 0) {
          children.push({
            id: `tool_${i}`,
            label: tc.name,
            durationMs: ms,
            depth: 1,
            icon: "tool",
          });
        }
      }
    }
  }

  const totalMs = computeInvocationTotalMs(children) || (trace.elapsed_ms ?? 0);

  if (totalMs <= 0 || Number.isNaN(totalMs)) {
    return [];
  }

  return [
    {
      id: "invocation",
      label: "invocation",
      durationMs: totalMs,
      depth: 0,
      icon: "invocation",
    },
    ...children,
  ];
}

const spans = computed(() =>
  selectedTrace.value ? buildTraceSpans(selectedTrace.value) : []
);

async function copyToClipboard(text: string, type: "request" | "response"): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    if (type === "request") {
      copiedRequest.value = true;
      setTimeout(() => { copiedRequest.value = false; }, 1500);
    } else {
      copiedResponse.value = true;
      setTimeout(() => { copiedResponse.value = false; }, 1500);
    }
  } catch {
    // Silently fail
  }
}

function goToWorkflow(): void {
  const workflowId = selectedTrace.value?.workflow_id;
  if (workflowId) {
    closeDetail();
    router.push(`/workflows/${workflowId}`);
  }
}

const sourceOptions = computed<SelectOption[]>(() => [
  { value: "all", label: "All Sources" },
  { value: "workflow", label: "Workflow LLM" },
  { value: "assistant", label: "AI Assistant" },
  { value: "dashboard_chat", label: "Dashboard Chat / Docs" },
  { value: "skill_builder", label: "Skill Builder" },
  { value: "evals", label: "Evals" },
]);

const credentialOptions = computed<SelectOption[]>(() => {
  const options = credentials.value.map((credential) => ({
    value: credential.id,
    label: credential.name,
  }));
  return [{ value: "all", label: "All Credentials" }, ...options];
});

const workflowOptions = computed<SelectOption[]>(() => {
  const options = workflows.value.map((workflow) => ({
    value: workflow.id,
    label: workflow.name,
  }));
  return [{ value: "all", label: "All Workflows" }, ...options];
});

const isWorkflowSource = computed(() => sourceFilter.value === "workflow");

const hasPrevious = computed(() => offset.value > 0);
const hasNext = computed(() => offset.value + limit.value < total.value);

const rangeStart = computed(() => {
  if (total.value === 0) return 0;
  return offset.value + 1;
});

const rangeEnd = computed(() => Math.min(offset.value + limit.value, total.value));

async function loadCredentials(): Promise<void> {
  try {
    credentials.value = await credentialsApi.listLLM();
  } catch {
    credentials.value = [];
  }
}

async function loadWorkflows(): Promise<void> {
  try {
    workflows.value = await workflowApi.list();
  } catch {
    workflows.value = [];
  }
}

async function loadTraces(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const response = await traceApi.list({
      limit: limit.value,
      offset: offset.value,
      source: sourceFilter.value === "all" ? undefined : sourceFilter.value,
      credentialId: credentialFilter.value === "all" ? undefined : credentialFilter.value,
      workflowId:
        isWorkflowSource.value && workflowFilter.value !== "all"
          ? workflowFilter.value
          : undefined,
      search: searchQuery.value || undefined,
      order: "desc",
    });
    traces.value = response.items;
    total.value = response.total;
  } catch {
    error.value = "Failed to load traces";
    traces.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

function resetPagination(): void {
  offset.value = 0;
}

function goPrevious(): void {
  if (!hasPrevious.value) return;
  offset.value = Math.max(0, offset.value - limit.value);
  loadTraces();
}

function goNext(): void {
  if (!hasNext.value) return;
  offset.value = offset.value + limit.value;
  loadTraces();
}

function getStatusClass(status: string): string {
  if (status === "error") return "text-destructive bg-destructive/10";
  return "text-emerald-600 bg-emerald-500/10";
}

function formatMillis(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "-";
  return `${Math.round(value)} ms`;
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? "");
  }
}

async function openTrace(
  traceId: string,
  index?: number,
  options: { pushOverlay?: boolean } = {},
): Promise<void> {
  const isNavigation = detailOpen.value;
  detailOpen.value = true;
  detailError.value = "";
  const pushOverlay = options.pushOverlay ?? true;

  if (pushOverlay && !isNavigation) {
    pushOverlayState();
  }

  if (index !== undefined) {
    selectedTraceIndex.value = index;
  } else {
    selectedTraceIndex.value = traces.value.findIndex(t => t.id === traceId);
  }

  if (!isNavigation) {
    detailLoading.value = true;
    selectedTrace.value = null;
  }

  try {
    selectedTrace.value = await traceApi.get(traceId);
  } catch {
    detailError.value = "Failed to load trace details";
  } finally {
    detailLoading.value = false;
  }
}

async function goToPreviousTrace(): Promise<void> {
  if (!hasPreviousTrace.value || detailLoading.value) return;
  const prevIndex = selectedTraceIndex.value - 1;
  const prevTrace = traces.value[prevIndex];
  if (prevTrace) {
    await openTrace(prevTrace.id, prevIndex);
  }
}

async function goToNextTrace(): Promise<void> {
  if (!hasNextTrace.value || detailLoading.value) return;
  const nextIndex = selectedTraceIndex.value + 1;
  const nextTrace = traces.value[nextIndex];
  if (nextTrace) {
    await openTrace(nextTrace.id, nextIndex);
  }
}

function closeDetail(): void {
  detailOpen.value = false;
  detailLoading.value = false;
  detailError.value = "";
  selectedTrace.value = null;
  selectedTraceIndex.value = -1;
  copiedRequest.value = false;
  copiedResponse.value = false;
  if (route.query.traceId !== undefined) {
    const nextQuery = { ...route.query };
    delete nextQuery.traceId;
    router.replace({ query: nextQuery });
  }
}

async function openTraceFromRoute(): Promise<void> {
  const rawTraceId = route.query.traceId;
  const traceId = Array.isArray(rawTraceId) ? rawTraceId[0] : rawTraceId;
  if (!traceId) {
    return;
  }
  await openTrace(traceId, undefined, { pushOverlay: false });
}

async function clearTraces(): Promise<void> {
  if (!confirm("Are you sure you want to delete all traces? This action cannot be undone.")) {
    return;
  }
  clearing.value = true;
  try {
    await traceApi.clear();
    traces.value = [];
    total.value = 0;
    offset.value = 0;
  } catch {
    error.value = "Failed to clear traces";
  } finally {
    clearing.value = false;
  }
}

function toggleSearch(): void {
  searchActive.value = !searchActive.value;
  if (searchActive.value) {
    nextTick(() => searchInputRef.value?.focus());
  } else if (searchQuery.value) {
    searchQuery.value = "";
    resetPagination();
    loadTraces();
  }
}

function onSearchInput(event: Event): void {
  searchQuery.value = (event.target as HTMLInputElement).value;
  if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    resetPagination();
    loadTraces();
  }, 300);
}

function clearSearch(): void {
  searchQuery.value = "";
  resetPagination();
  loadTraces();
  searchInputRef.value?.focus();
}

watch(sourceFilter, (next, prev) => {
  if (prev === "workflow" && next !== "workflow") {
    workflowFilter.value = "all";
  }
});

watch([sourceFilter, credentialFilter, workflowFilter], () => {
  resetPagination();
  loadTraces();
});

watch(
  () => route.query.traceId,
  async (traceId) => {
    if (traceId !== undefined) {
      await openTraceFromRoute();
    }
  },
);

function handleKeyDown(event: KeyboardEvent): void {
  if (detailOpen.value) return;
  const tag = (event.target as HTMLElement)?.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (event.key === "s" || event.key === "S") {
    event.preventDefault();
    toggleSearch();
  }
}

onMounted(async () => {
  await loadCredentials();
  await loadWorkflows();
  await loadTraces();
  await openTraceFromRoute();
  const unsub = onDismissOverlays(closeDetail);
  document.addEventListener("keydown", handleKeyDown);
  onBeforeUnmount(() => {
    unsub();
    document.removeEventListener("keydown", handleKeyDown);
  });
});
</script>

<template>
  <div class="space-y-6 overflow-x-hidden">
    <div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div>
        <h2 class="text-2xl font-bold tracking-tight">
          Traces
        </h2>
        <p class="text-muted-foreground mt-1">
          Inspect AI assistant and workflow LLM calls in one place.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          :class="searchActive ? 'border-primary/60 bg-primary/10' : ''"
          @click="toggleSearch"
        >
          <Search class="w-4 h-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          :loading="loading"
          @click="loadTraces"
        >
          <RefreshCcw class="w-4 h-4 mr-1" />
          Refresh
        </Button>
        <Button
          variant="destructive"
          size="sm"
          :loading="clearing"
          :disabled="traces.length === 0"
          @click="clearTraces"
        >
          <Trash2 class="w-4 h-4 mr-1" />
          Clear All
        </Button>
      </div>
    </div>

    <div
      v-if="searchActive"
      class="relative w-full min-w-0 flex-1"
    >
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none z-[1]" />
      <input
        ref="searchInputRef"
        type="text"
        :value="searchQuery"
        placeholder="Search traces by model, workflow, credential, node..."
        class="w-full min-w-0 pl-9 pr-8 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-primary/30 focus:border-primary/50 transition-colors"
        @input="onSearchInput"
        @keydown.enter="onSearchInput"
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

    <div class="space-y-4">
      <div
        class="grid gap-4 grid-cols-1 sm:grid-cols-2"
        :class="isWorkflowSource ? 'md:grid-cols-3' : ''"
      >
        <div class="space-y-2">
          <Label>Source</Label>
          <Select
            v-model="sourceFilter"
            :options="sourceOptions"
          />
        </div>
        <div class="space-y-2">
          <Label>Credential</Label>
          <Select
            v-model="credentialFilter"
            :options="credentialOptions"
          />
        </div>
        <div
          v-if="isWorkflowSource"
          class="space-y-2 sm:col-span-2 md:col-span-1"
        >
          <Label>Workflow</Label>
          <Select
            v-model="workflowFilter"
            :options="workflowOptions"
          />
        </div>
      </div>
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-end">
        <div class="text-xs text-muted-foreground sm:mr-auto sm:text-right">
          {{ rangeStart }}-{{ rangeEnd }} of {{ total }}
        </div>
        <div class="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            class="h-9 md:h-9 text-xs"
            :disabled="!hasPrevious"
            @click="goPrevious"
          >
            <ChevronLeft class="w-3 h-3 md:w-4 md:h-4" />
            <span class="hidden sm:inline">Prev</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="h-9 md:h-9 text-xs"
            :disabled="!hasNext"
            @click="goNext"
          >
            <span class="hidden sm:inline">Next</span>
            <ChevronRight class="w-3 h-3 md:w-4 md:h-4" />
          </Button>
        </div>
      </div>
    </div>

    <div
      v-if="loading"
      class="text-sm text-muted-foreground text-center py-10"
    >
      Loading traces...
    </div>

    <div
      v-else-if="error"
      class="text-sm text-destructive text-center py-10"
    >
      {{ error }}
    </div>

    <div
      v-else-if="traces.length === 0"
      class="text-sm text-muted-foreground text-center py-10"
    >
      No traces yet.
    </div>

    <div
      v-else
      class="grid gap-3"
    >
      <Card
        v-for="(trace, index) in traces"
        :key="trace.id"
        class="p-4"
      >
        <button
          class="w-full text-left space-y-3"
          @click="openTrace(trace.id, index)"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-3 text-sm">
              <div class="flex items-center gap-1 text-muted-foreground">
                <Clock class="w-4 h-4" />
                <span>{{ formatDate(trace.created_at) }}</span>
              </div>
              <span class="text-xs uppercase tracking-wide text-muted-foreground">
                {{ trace.source }}
              </span>
              <span class="text-xs text-muted-foreground">
                {{ trace.model || "Unknown model" }}
              </span>
            </div>
            <span
              class="text-xs font-medium px-2 py-1 rounded-full"
              :class="getStatusClass(trace.status)"
            >
              {{ trace.status }}
            </span>
          </div>

          <div class="text-sm text-muted-foreground">
            <span>{{ trace.credential_name || "Unknown credential" }}</span>
            <span v-if="trace.workflow_name"> - {{ trace.workflow_name }}</span>
            <span v-if="trace.node_label"> - {{ trace.node_label }}</span>
          </div>

          <div class="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
            <span>{{ trace.request_type }}</span>
            <span v-if="trace.total_tokens !== null">{{ trace.total_tokens }} tokens</span>
            <span>{{ formatMillis(trace.elapsed_ms) }}</span>
          </div>
        </button>
      </Card>
    </div>

    <Dialog
      :open="detailOpen"
      title="Trace Details"
      size="3xl"
      allow-fullscreen
      default-fullscreen
      @close="closeDetail"
    >
      <template #header-actions>
        <div class="flex items-center gap-2 flex-wrap">
          <div class="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              class="h-9 px-2 md:h-7 text-xs"
              :disabled="!hasPreviousTrace || detailLoading"
              @click="goToPreviousTrace"
            >
              <ChevronLeft class="w-3 h-3 md:w-4 md:h-4" />
              <span class="hidden sm:inline">Prev</span>
            </Button>
            <span class="text-xs text-muted-foreground px-1 whitespace-nowrap">
              {{ tracePositionLabel }}
            </span>
            <Button
              variant="outline"
              size="sm"
              class="h-9 px-2 md:h-7 text-xs"
              :disabled="!hasNextTrace || detailLoading"
              @click="goToNextTrace"
            >
              <span class="hidden sm:inline">Next</span>
              <ChevronRight class="w-3 h-3 md:w-4 md:h-4" />
            </Button>
          </div>
          <Button
            v-if="selectedTrace?.workflow_id"
            variant="outline"
            size="sm"
            class="h-9 md:h-7 text-xs"
            @click="goToWorkflow"
          >
            <ExternalLink class="w-3 h-3 mr-1" />
            <span class="hidden sm:inline">Go to Workflow</span>
            <span class="sm:hidden">Workflow</span>
          </Button>
        </div>
      </template>
      <div
        v-if="detailLoading"
        class="text-sm text-muted-foreground text-center py-8"
      >
        Loading trace...
      </div>

      <div
        v-else-if="detailError"
        class="text-sm text-destructive text-center py-8"
      >
        {{ detailError }}
      </div>

      <div
        v-else-if="!selectedTrace"
        class="text-sm text-muted-foreground text-center py-8"
      >
        No trace selected.
      </div>

      <div
        v-else
        class="space-y-4"
      >
        <div class="grid gap-3 md:grid-cols-4">
          <Card
            variant="flat"
            :hover="false"
            class="p-3"
          >
            <div class="text-xs text-muted-foreground">
              Status
            </div>
            <div
              class="mt-1 text-sm font-medium"
              :class="cn(selectedTrace.status === 'error' ? 'text-destructive' : 'text-emerald-600')"
            >
              {{ selectedTrace.status }}
            </div>
          </Card>
          <Card
            variant="flat"
            :hover="false"
            class="p-3"
          >
            <div class="text-xs text-muted-foreground">
              Model
            </div>
            <div class="mt-1 text-sm font-medium">
              {{ selectedTrace.model || "Unknown" }}
            </div>
          </Card>
          <Card
            variant="flat"
            :hover="false"
            class="p-3"
          >
            <div class="text-xs text-muted-foreground">
              Time
            </div>
            <div class="mt-1 text-sm font-medium">
              {{ formatMillis(spans.length > 0 ? spans[0].durationMs : selectedTrace.elapsed_ms) }}
            </div>
          </Card>
          <Card
            variant="flat"
            :hover="false"
            class="p-3"
          >
            <div class="text-xs text-muted-foreground">
              Tokens
            </div>
            <div class="mt-1 text-sm font-medium">
              {{ selectedTrace.total_tokens ?? "-" }}
            </div>
          </Card>
        </div>

        <TraceDurationChart
          v-if="spans.length > 0"
          :spans="spans"
        />

        <div class="grid gap-3 md:grid-cols-3">
          <Card
            variant="flat"
            :hover="false"
            class="p-3"
          >
            <div class="text-xs text-muted-foreground">
              Created At
            </div>
            <div class="mt-1 text-sm font-medium">
              {{ formatDate(selectedTrace.created_at) }}
            </div>
          </Card>
          <Card
            variant="flat"
            :hover="false"
            class="p-3"
          >
            <div class="text-xs text-muted-foreground">
              Credential
            </div>
            <div class="mt-1 text-sm font-medium">
              {{ selectedTrace.credential_name || "Unknown" }}
            </div>
          </Card>
          <Card
            variant="flat"
            :hover="false"
            class="p-3"
          >
            <div class="text-xs text-muted-foreground">
              Workflow / Node
            </div>
            <div class="mt-1 text-sm font-medium">
              {{ selectedTrace.workflow_name || "-" }}
              <span v-if="selectedTrace.node_label">
                / {{ selectedTrace.node_label }}
              </span>
            </div>
          </Card>
        </div>

        <div
          v-if="selectedTrace.error"
          class="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
        >
          {{ selectedTrace.error }}
        </div>

        <div
          v-if="getSkillsFromRequest(selectedTrace.request)?.length"
          class="space-y-2"
        >
          <div class="text-sm font-medium">
            Skills Included
          </div>
          <div class="flex flex-wrap gap-1">
            <span
              v-for="(s, i) in getSkillsFromRequest(selectedTrace.request)"
              :key="i"
              class="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary"
            >
              {{ s }}
            </span>
          </div>
        </div>

        <div
          v-if="getToolCallsFromResponse(selectedTrace.response)?.length"
          class="space-y-2"
        >
          <div class="text-sm font-medium">
            Tool Calls
          </div>
          <div class="space-y-2">
            <div
              v-for="(tc, i) in getToolCallsFromResponse(selectedTrace.response)!"
              :key="i"
              class="rounded-md border border-border/50 bg-muted/20 p-3 text-sm"
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
              <div class="mt-2 text-xs text-muted-foreground break-all">
                → {{ typeof tc.result === 'object' ? JSON.stringify(tc.result) : tc.result }}
              </div>
            </div>
          </div>
        </div>

        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <div class="text-sm font-medium">
              Request
            </div>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 px-2"
              @click="copyToClipboard(formatJson(selectedTrace.request), 'request')"
            >
              <Check
                v-if="copiedRequest"
                class="w-3 h-3 mr-1 text-emerald-500"
              />
              <Copy
                v-else
                class="w-3 h-3 mr-1"
              />
              {{ copiedRequest ? "Copied" : "Copy" }}
            </Button>
          </div>
          <pre class="text-xs bg-muted/30 border rounded-md p-3 overflow-auto max-h-[40vh] whitespace-pre-wrap">{{ formatJson(selectedTrace.request) }}</pre>
        </div>

        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <div class="text-sm font-medium">
              Response
            </div>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 px-2"
              @click="copyToClipboard(formatJson(selectedTrace.response), 'response')"
            >
              <Check
                v-if="copiedResponse"
                class="w-3 h-3 mr-1 text-emerald-500"
              />
              <Copy
                v-else
                class="w-3 h-3 mr-1"
              />
              {{ copiedResponse ? "Copied" : "Copy" }}
            </Button>
          </div>
          <pre class="text-xs bg-muted/30 border rounded-md p-3 overflow-auto max-h-[40vh] whitespace-pre-wrap">{{ formatJson(selectedTrace.response) }}</pre>
        </div>
      </div>
    </Dialog>
  </div>
</template>
