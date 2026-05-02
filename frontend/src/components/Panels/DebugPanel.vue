<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useVueFlow } from "@vue-flow/core";
import axios from "axios";
import DOMPurify from "dompurify";
import { jsonrepair } from "jsonrepair";
import { marked } from "marked";
import { AlertCircle, Bot, CheckCircle2, ChevronDown, ChevronUp, ChevronsUp, Clock, Copy, Download, ExternalLink, FileText, GripHorizontal, LayoutGrid, Loader2, Maximize2, Mic, MicOff, Minimize2, Pencil, RefreshCcw, Send, Sparkles, Square, Terminal, Timer, Trash2, X } from "lucide-vue-next";

import type { CredentialListItem, LLMModel } from "@/types/credential";
import type {
  AgentSkill,
  AgentSkillFile,
  NodeResult,
  PlaywrightStep,
  WorkflowEdge,
  WorkflowNode,
} from "@/types/workflow";
import type { WorkflowWithInputs } from "@/services/api";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import JsonTree from "@/components/ui/JsonTree.vue";
import Textarea from "@/components/ui/Textarea.vue";
import ExecutionTimeline from "@/components/Panels/ExecutionTimeline.vue";
import type { TimelineEntry, TimelineSelectPayload } from "@/components/Panels/executionTimeline";
import { isRetryAttemptNodeResult } from "@/lib/executionLog";
import { cn, formatFileSize } from "@/lib/utils";
import { buildMeasuredNodeSizeMap, getWorkflowNodeLayoutSize } from "@/lib/workflowLayout";
import { normalizeWorkflowEdges } from "@/lib/workflowEdges";
import { aiApi, credentialsApi, hitlApi, workflowApi } from "@/services/api";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { useWorkflowStore } from "@/stores/workflow";
import { playSuccessSound } from "@/utils/audio";

const { fitView, getNodes, updateNodeInternals } = useVueFlow();

const workflowStore = useWorkflowStore();

const panelHeight = ref(212);
const isResizing = ref(false);
const isCollapsed = ref(false);
const minHeight = 104;
const maxHeight = 500;
const collapsedHeight = 104;
const scrollContainer = ref<HTMLDivElement | null>(null);

const executionResult = computed(() => workflowStore.executionResult);
const nodeResults = computed(() => workflowStore.nodeResults);
const isExecuting = computed(() => workflowStore.isExecuting);
const runningNodeId = computed(() => workflowStore.runningNodeId);
const agentProgressLogs = computed(() => workflowStore.agentProgressLogs);
const selectedNode = computed(() => workflowStore.selectedNode);
const logsCopied = ref(false);
const showTimeline = ref(false);
const showMarkdownInExecutionLog = ref(true);

const runningAgentNode = computed(() => {
  const id = runningNodeId.value;
  if (!id) return null;
  const node = workflowStore.nodes.find((n) => n.id === id);
  return node?.type === "agent" ? node : null;
});

const liveAgentEntries = computed(() => {
  const id = runningNodeId.value;
  if (!id) return [];
  return agentProgressLogs.value.get(id) ?? [];
});

async function copyLogsAsJson(): Promise<void> {
  const jsonData = getLogsAsJsonData();

  try {
    await navigator.clipboard.writeText(JSON.stringify(jsonData, null, 2));
    logsCopied.value = true;
    setTimeout(() => {
      logsCopied.value = false;
    }, 2000);
  } catch {
    // Clipboard write failed
  }
}

function openInJsonEditor(): void {
  const jsonData = getLogsAsJsonData();
  const jsonString = JSON.stringify(jsonData, null, 2);
  const blob = new Blob([jsonString], { type: "application/json" });
  const file = new File([blob], "execution-logs.json", { type: "application/json" });

  const formData = new FormData();
  formData.append("file", file);

  fetch("https://jsonhero.io/api/create.json", {
    method: "POST",
    body: formData,
  })
    .then(res => res.json())
    .then((data: { docId: string }) => {
      window.open(`https://jsonhero.io/j/${data.docId}`, "_blank");
    })
    .catch(() => {
      const encodedJson = encodeURIComponent(jsonString);
      window.open(`https://jsoneditoronline.org/?json=${encodedJson}`, "_blank");
    });
}

function scrollToBottom(): void {
  nextTick(() => {
    if (scrollContainer.value) {
      scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight;
    }
  });
}

watch(
  () => nodeResults.value.length,
  () => {
    if (isExecuting.value) {
      scrollToBottom();
    }
  }
);

watch(
  () => isExecuting.value,
  (newValue) => {
    if (newValue && panelHeight.value < 300) {
      panelHeight.value = 500;
      isCollapsed.value = false;
    }
    if (newValue) {
      workflowStore.setDebugPanelHeight(panelHeight.value);
    }
  }
);

watch(
  () => executionResult.value,
  () => {
    if (isExecuting.value) {
      scrollToBottom();
    }
  }
);

watch(
  () => liveAgentEntries.value.length,
  () => {
    if (isExecuting.value) {
      scrollToBottom();
    }
  }
);

/** When a run finishes, the store sets nodeResults/executionResult then isExecuting=false in one tick.
 *  Watchers that require isExecuting===true never fire for that final paint — scroll here instead. */
watch(
  () => isExecuting.value,
  (executing, wasExecuting) => {
    if (wasExecuting === true && executing === false) {
      nextTick(() => {
        scrollToBottom();
        requestAnimationFrame(() => {
          if (scrollContainer.value) {
            scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight;
          }
        });
      });
    }
  },
  { flush: "post" },
);

const delegatedSubAgentLabelSet = computed(() => {
  const s = new Set<string>();
  for (const n of workflowStore.nodes) {
    if (n.type !== "agent") continue;
    const labels = n.data?.subAgentLabels;
    if (!Array.isArray(labels)) continue;
    for (const l of labels) {
      if (typeof l === "string") s.add(l);
    }
  }
  return s;
});

function isHiddenFromDefaultExecutionLog(r: NodeResult): boolean {
  if (r.metadata?.invocation === "sub_agent_tool") return true;
  if (r.node_type !== "agent" || !delegatedSubAgentLabelSet.value.has(r.node_label)) {
    return false;
  }
  if (r.status === "skipped") return true;
  // Older history without metadata: any row for an orchestrator-listed sub-agent label
  // is a delegated run (graph-scheduled sub-agents are skipped, not success).
  return r.status === "success" || r.status === "error" || r.status === "pending";
}

const extendedExecutionRows = computed((): NodeResult[] => {
  if (
    executionResult.value?.node_results &&
    executionResult.value.node_results.length > 0 &&
    !isExecuting.value
  ) {
    return executionResult.value.node_results;
  }
  return nodeResults.value;
});

const graphOnlyExecutionRows = computed((): NodeResult[] =>
  extendedExecutionRows.value.filter((r) => !isHiddenFromDefaultExecutionLog(r)),
);

const rawRowsForExecutionPanel = computed((): NodeResult[] => {
  const node = selectedNode.value;
  if (!node || node.type !== "agent" || node.data?.isOrchestrator) {
    return graphOnlyExecutionRows.value;
  }
  const label =
    typeof node.data?.label === "string" && node.data.label.trim() !== ""
      ? node.data.label.trim()
      : "";
  return extendedExecutionRows.value.filter(
    (r) => r.node_id === node.id || (label !== "" && r.node_label === label),
  );
});

const displayResults = computed(() => {
  const results = rawRowsForExecutionPanel.value;
  const seenCounts = new Map<string, number>();
  return results
    .filter(r => r.node_type !== "condition" && r.node_type !== "sticky" && r.status !== "skipped")
    .map((r, index) => {
      const occurrence = (seenCounts.get(r.node_id) || 0) + 1;
      seenCounts.set(r.node_id, occurrence);
      const rawOutput = r.output;
      const pendingPayload = getHitlPendingPayload(rawOutput);
      const resolvedPayload = getHitlResolvedPayload(rawOutput);
      const requestId =
        pendingPayload?.requestId ||
        (typeof (rawOutput as Record<string, unknown> | undefined)?.requestId === "string"
          ? String((rawOutput as Record<string, unknown>).requestId)
          : undefined);
      return {
        ...r,
        output: sanitizeForDisplay(r.output),
        rawOutput,
        occurrence,
        displayKey:
          requestId ||
          `${r.node_id}-${r.status}-${r.execution_time_ms}-${resolvedPayload?.decision || "none"}-${index}`,
      };
    });
});

// Sub-agent label → parent orchestrator node_id (for timeline hierarchy)
const subAgentLabelToParentId = computed((): Map<string, string> => {
  const map = new Map<string, string>();
  for (const n of workflowStore.nodes) {
    if (n.type !== "agent") continue;
    const labels = n.data?.subAgentLabels;
    if (!Array.isArray(labels)) continue;
    for (const l of labels) {
      if (typeof l === "string") map.set(l, n.id);
    }
  }
  return map;
});

const timelineResults = computed((): TimelineEntry[] =>
  extendedExecutionRows.value
    .map((r, rowIndex, allRows) => ({ r, rowIndex, allRows }))
    .filter(
      ({ r }) =>
        r.node_type !== "condition" &&
        r.node_type !== "sticky" &&
        !isRetryAttemptNodeResult(r) &&
        r.status !== "skipped" &&
        r.execution_time_ms > 0,
    )
    .map(({ r, rowIndex, allRows }) => {
      let retryFailedAttempts = 0;
      let retryFinalAttempt: number | null = null;
      let retryMaxAttempts: number | null = null;
      let highestRetryAttempt = 0;

      for (let previousIndex = rowIndex - 1; previousIndex >= 0; previousIndex -= 1) {
        const previousRow = allRows[previousIndex];
        if (previousRow.node_id !== r.node_id) {
          continue;
        }
        if (!isRetryAttemptNodeResult(previousRow)) {
          break;
        }

        retryFailedAttempts += 1;
        const attempt = previousRow.metadata?.retry_attempt;
        if (typeof attempt === "number" && Number.isInteger(attempt)) {
          highestRetryAttempt = Math.max(highestRetryAttempt, attempt);
        }
        const maxAttempts = previousRow.metadata?.retry_max_attempts;
        if (typeof maxAttempts === "number" && Number.isInteger(maxAttempts)) {
          retryMaxAttempts = maxAttempts;
        }
      }

      if (retryFailedAttempts > 0) {
        retryFinalAttempt = highestRetryAttempt > 0 ? highestRetryAttempt + 1 : retryFailedAttempts + 1;
        if (retryMaxAttempts === null) {
          retryMaxAttempts = retryFinalAttempt;
        }
      }

      return {
        ...r,
        isSubAgent: isHiddenFromDefaultExecutionLog(r),
        sourceNodeResultsIndex: rowIndex,
        retryFailedAttempts,
        retryFinalAttempt,
        retryMaxAttempts,
      };
    }),
);

function toggleTimeline(): void {
  showTimeline.value = !showTimeline.value;
}

function selectCanvasNodeFromTimeline(payload: TimelineSelectPayload): void {
  if (!workflowStore.nodes.some((n) => n.id === payload.nodeId)) {
    return;
  }
  workflowStore.selectNode(payload.nodeId);
  if (payload.resultListIndex !== null) {
    workflowStore.setTimelinePickedNodeResultIndex(payload.resultListIndex);
  }
  workflowStore.openPropertiesPanel(undefined, { skipPrimaryExpand: true });
}

function getLogsAsJsonData(): object {
  const logs = displayResults.value.map((result) => ({
    node_id: result.node_id,
    node_label: result.node_label,
    node_type: result.node_type,
    status: result.status,
    execution_time_ms: result.execution_time_ms,
    output: result.output,
    error: result.error,
    metadata: result.metadata,
  }));

  return {
    execution_status: executionResult.value?.status || "running",
    execution_time_ms: executionResult.value?.execution_time_ms || null,
    final_outputs: executionResult.value?.outputs || null,
    node_results: logs,
  };
}

const sanitizedFinalOutputs = computed(() => {
  if (!executionResult.value?.outputs) return null;
  return sanitizeForDisplay(executionResult.value.outputs);
});

const isFinalOutputExpanded = ref(false);
const finalOutputJsonTreeKey = ref(0);
const finalOutputJsonAutoDepth = ref(1);
const finalOutputExpandedPanelRef = ref<HTMLElement | null>(null);
const finalOutputCopied = ref(false);

function resetFinalOutputJsonTreeState(): void {
  finalOutputJsonAutoDepth.value = 1;
  finalOutputJsonTreeKey.value += 1;
}

function expandAllFinalOutputJson(): void {
  finalOutputJsonAutoDepth.value = 512;
  finalOutputJsonTreeKey.value += 1;
}

function collapseAllFinalOutputJson(): void {
  finalOutputJsonAutoDepth.value = 0;
  finalOutputJsonTreeKey.value += 1;
}

function formatFinalOutputForPre(value: unknown): string {
  if (value === null || value === undefined) {
    return String(value);
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "object") {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

async function copyFinalOutputToClipboard(): Promise<void> {
  if (sanitizedFinalOutputs.value === null || sanitizedFinalOutputs.value === undefined) {
    return;
  }
  const text = JSON.stringify(sanitizedFinalOutputs.value, null, 2);
  try {
    await navigator.clipboard.writeText(text);
    finalOutputCopied.value = true;
    setTimeout(() => {
      finalOutputCopied.value = false;
    }, 2000);
  } catch {
    // Clipboard unavailable
  }
}

watch(isFinalOutputExpanded, async (open) => {
  if (open) {
    resetFinalOutputJsonTreeState();
    await nextTick();
    finalOutputExpandedPanelRef.value?.focus({ preventScroll: true });
  }
});

watch(
  () => executionResult.value?.status,
  (status) => {
    if (status !== "success") {
      isFinalOutputExpanded.value = false;
    }
  },
);

function stopExecution(): void {
  workflowStore.stopExecution();
}

const statusColors = {
  success: "text-green-500",
  error: "text-red-500",
  pending: "text-amber-500",
  running: "text-yellow-500",
  skipped: "text-gray-400",
};

const statusIcons = {
  success: CheckCircle2,
  error: AlertCircle,
  pending: Clock,
  running: Loader2,
  skipped: Clock,
};

function startResize(e: MouseEvent): void {
  isResizing.value = true;
  const startY = e.clientY;
  const startHeight = panelHeight.value;

  function onMouseMove(e: MouseEvent): void {
    const delta = startY - e.clientY;
    const newHeight = startHeight + delta;
    panelHeight.value = Math.min(maxHeight, Math.max(minHeight, newHeight));
    isCollapsed.value = panelHeight.value <= collapsedHeight;
  }

  function onMouseUp(): void {
    isResizing.value = false;
    if (panelHeight.value <= collapsedHeight + 20) {
      panelHeight.value = collapsedHeight;
      isCollapsed.value = true;
    }
    workflowStore.setDebugPanelHeight(panelHeight.value);
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", onMouseUp);
  }

  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
}

function toggleCollapse(): void {
  if (isCollapsed.value) {
    panelHeight.value = maxHeight;
    isCollapsed.value = false;
  } else {
    panelHeight.value = collapsedHeight;
    isCollapsed.value = true;
  }
  workflowStore.setDebugPanelHeight(panelHeight.value);
  setTimeout(() => fitView({ padding: 0.1 }), 300);
}

function clearExecutionLog(): void {
  workflowStore.clearExecution();
}

interface ToolCallEntry {
  name: string;
  arguments: Record<string, unknown>;
  result: unknown;
  elapsed_ms?: number;
  source?: string;
  mcp_server?: string;
  workflow_name?: string;
}

function formatToolCallTitle(tc: ToolCallEntry): string {
  if (tc.name === "_context_compression") {
    const compressed = tc.arguments?.messages_compressed;
    return typeof compressed === "number"
      ? `Context compressed (${compressed} messages → summary)`
      : "Context compressed";
  }
  if (tc.name === "call_sub_workflow") {
    const wn = tc.workflow_name;
    const wid =
      typeof tc.arguments?.workflow_id === "string" ? tc.arguments.workflow_id : "";
    if (wn && wid) {
      return `call_sub_workflow(${wn}, ${wid})`;
    }
    if (wn) {
      return `call_sub_workflow(${wn})`;
    }
  }
  return `${tc.name}(${JSON.stringify(tc.arguments)})`;
}

function callSubWorkflowInputsPayload(tc: ToolCallEntry): unknown {
  if (tc.name !== "call_sub_workflow") return undefined;
  if (!tc.arguments || !Object.prototype.hasOwnProperty.call(tc.arguments, "inputs")) {
    return undefined;
  }
  return tc.arguments.inputs;
}

function formatCallSubWorkflowInputs(tc: ToolCallEntry): string {
  const inp = callSubWorkflowInputsPayload(tc);
  if (inp === undefined) return "";
  if (typeof inp === "string") return inp;
  try {
    return JSON.stringify(inp, null, 2);
  } catch {
    return String(inp);
  }
}

function hasCallSubWorkflowInputs(tc: ToolCallEntry): boolean {
  const inp = callSubWorkflowInputsPayload(tc);
  return inp !== undefined;
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

function getOutputText(output: unknown): string | null {
  const o = output as Record<string, unknown> | undefined;
  const t = o?.text;
  return typeof t === "string" ? t : null;
}

function getMarkdownDisplayText(output: unknown): string | null {
  if (typeof output === "string") {
    return output;
  }
  return getOutputText(output);
}

function getGenericResultOutputText(output: unknown): string {
  const text = getOutputText(output);
  if (getToolCalls(output)?.length && text !== null) {
    return text;
  }
  return JSON.stringify(output);
}

function renderExecutionMarkdown(content: string): string {
  if (!content) return "";
  const html = marked(content, {
    breaks: true,
    gfm: true,
  }) as string;
  return DOMPurify.sanitize(html);
}

interface HITLPendingPayload {
  summary: string;
  draftText: string;
  reviewUrl: string;
  requestId: string;
  shareText?: string;
  shareMarkdown?: string;
  hitlHistory?: HITLResolvedPayload[];
}

function getHitlPendingPayload(output: unknown): HITLPendingPayload | null {
  const o = output as Record<string, unknown> | undefined;
  if (!o || o.decision !== null) return null;
  if (
    typeof o.summary !== "string" ||
    typeof o.draftText !== "string" ||
    typeof o.reviewUrl !== "string" ||
    typeof o.requestId !== "string"
  ) {
    return null;
  }
  return {
    summary: o.summary,
    draftText: o.draftText,
    reviewUrl: o.reviewUrl,
    requestId: o.requestId,
    shareText: typeof o.shareText === "string" ? o.shareText : undefined,
    shareMarkdown: typeof o.shareMarkdown === "string" ? o.shareMarkdown : undefined,
    hitlHistory: getHitlHistory(o),
  };
}

function trimDuplicatedPrefix(value: string, prefix: string): string {
  let text = value.trimStart();
  const duplicatePrefix = prefix.trim();
  if (!text || !duplicatePrefix) return text;

  while (text.startsWith(duplicatePrefix)) {
    text = text.slice(duplicatePrefix.length).replace(/^[\s:.-]+/, "").trimStart();
  }

  return text;
}

function normalizeDuplicateLineKey(value: string): string {
  return value
    .trim()
    .replace(/[.!?。！？]+$/g, "")
    .replace(/\s+/g, " ")
    .toLocaleLowerCase();
}

function removeConsecutiveDuplicateLines(value: string): string {
  const lines = value.split(/\r?\n/);
  const dedupedLines: string[] = [];
  let previousNonEmptyKey = "";

  for (const line of lines) {
    const key = normalizeDuplicateLineKey(line);
    if (key && key === previousNonEmptyKey) {
      continue;
    }
    dedupedLines.push(line);
    if (key) {
      previousNonEmptyKey = key;
    }
  }

  return dedupedLines.join("\n").trim();
}

function getDedupedReviewText(value: string, summary?: string): string {
  return removeConsecutiveDuplicateLines(trimDuplicatedPrefix(value, summary || ""));
}

function getHitlDisplayDraftText(payload: HITLPendingPayload): string {
  return getDedupedReviewText(payload.draftText, payload.summary);
}

function shouldShowGenericResultOutput(rawOutput: unknown): boolean {
  return !getHitlPendingPayload(rawOutput) && getHitlHistory(rawOutput).length === 0;
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

function getHitlResolvedPayload(output: unknown): HITLResolvedPayload | null {
  return normalizeHitlResolvedPayload(output);
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
  let text: string | null = null;
  if (payload.decision === "edited") {
    text = payload.editedText || payload.reviewText || payload.approvedMarkdown || null;
  } else if (payload.decision === "accepted") {
    text = payload.reviewText || payload.approvedMarkdown || payload.originalDraft || null;
  } else {
    text = payload.refusalReason || payload.reviewText || null;
  }

  const dedupedText = getDedupedReviewText(text || "", payload.summary);
  return dedupedText || null;
}

const hitlSubmittingRequestId = ref<string | null>(null);
const hitlSubmittingAction = ref<"accept" | "edit" | "refuse" | null>(null);
const hitlSubmittedRequestIds = ref<Set<string>>(new Set());
const hitlEditRequestId = ref<string | null>(null);
const hitlEditTextByRequestId = ref<Record<string, string>>({});
const hitlErrorByRequestId = ref<Record<string, string>>({});

function getHitlReviewToken(reviewUrl: string): string | null {
  try {
    const url = new URL(reviewUrl, window.location.origin);
    const parts = url.pathname.split("/").filter(Boolean);
    const reviewIndex = parts.indexOf("review");
    if (reviewIndex < 0 || reviewIndex + 1 >= parts.length) {
      return null;
    }
    return parts[reviewIndex + 1] || null;
  } catch {
    return null;
  }
}

function setHitlError(requestId: string, message: string | null): void {
  const next = { ...hitlErrorByRequestId.value };
  if (message) {
    next[requestId] = message;
  } else {
    delete next[requestId];
  }
  hitlErrorByRequestId.value = next;
}

function getHitlError(requestId: string): string | null {
  return hitlErrorByRequestId.value[requestId] || null;
}

function isHitlSubmitting(requestId: string): boolean {
  return hitlSubmittingRequestId.value === requestId;
}

function isHitlSubmittingAction(
  requestId: string,
  action: "accept" | "edit" | "refuse",
): boolean {
  return hitlSubmittingRequestId.value === requestId && hitlSubmittingAction.value === action;
}

function isHitlSubmitted(requestId: string): boolean {
  return hitlSubmittedRequestIds.value.has(requestId);
}

function openHitlEdit(payload: HITLPendingPayload): void {
  setHitlError(payload.requestId, null);
  hitlEditTextByRequestId.value = {
    ...hitlEditTextByRequestId.value,
    [payload.requestId]:
      hitlEditTextByRequestId.value[payload.requestId] ?? payload.draftText,
  };
  hitlEditRequestId.value = payload.requestId;
}

function cancelHitlEdit(requestId: string): void {
  if (hitlEditRequestId.value === requestId) {
    hitlEditRequestId.value = null;
  }
}

function getHitlEditText(requestId: string, fallback: string): string {
  return hitlEditTextByRequestId.value[requestId] ?? fallback;
}

function setHitlEditText(requestId: string, value: string): void {
  hitlEditTextByRequestId.value = {
    ...hitlEditTextByRequestId.value,
    [requestId]: value,
  };
}

function addSubmittedHitlRequest(requestId: string): void {
  const next = new Set(hitlSubmittedRequestIds.value);
  next.add(requestId);
  hitlSubmittedRequestIds.value = next;
}

async function refreshCurrentExecutionHistory(): Promise<void> {
  const historyId = executionResult.value?.execution_history_id;
  if (!historyId) return;

  const entry = await workflowStore.fetchExecutionHistoryEntry(historyId, true);
  if (entry) {
    workflowStore.applyExecutionHistoryEntry(entry);
  }
}

function getHitlSubmitError(error: unknown): string {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail || "Failed to submit human review decision.";
  }
  return "Failed to submit human review decision.";
}

async function submitHitlDecision(
  payload: HITLPendingPayload,
  action: "accept" | "edit" | "refuse",
): Promise<void> {
  if (hitlSubmittingRequestId.value || isHitlSubmitted(payload.requestId)) return;

  const token = getHitlReviewToken(payload.reviewUrl);
  if (!token) {
    setHitlError(payload.requestId, "Review link is not available yet.");
    return;
  }

  const editedText = getHitlEditText(payload.requestId, payload.draftText).trim();
  if (action === "edit" && !editedText) {
    setHitlError(payload.requestId, "Edited text is required.");
    return;
  }

  hitlSubmittingRequestId.value = payload.requestId;
  hitlSubmittingAction.value = action;
  setHitlError(payload.requestId, null);

  try {
    await hitlApi.decide(token, {
      action,
      edited_text: action === "edit" ? editedText : undefined,
    });
    addSubmittedHitlRequest(payload.requestId);
    if (hitlEditRequestId.value === payload.requestId) {
      hitlEditRequestId.value = null;
    }
    localStorage.setItem(
      "heym-hitl-resolution",
      JSON.stringify({
        requestId: payload.requestId,
        at: Date.now(),
      }),
    );
    await refreshCurrentExecutionHistory();
  } catch (error: unknown) {
    setHitlError(payload.requestId, getHitlSubmitError(error));
  } finally {
    hitlSubmittingRequestId.value = null;
    hitlSubmittingAction.value = null;
  }
}

async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    // Clipboard write failed
  }
}

function openExternal(url: string): void {
  window.open(url, "_blank", "noopener");
}

interface TimingBreakdown {
  llm_ms: number;
  tools_ms: number;
  mcp_list_ms: number;
}

function getTimingBreakdown(output: unknown): TimingBreakdown | undefined {
  const o = output as Record<string, unknown> | undefined;
  const tb = o?.timing_breakdown;
  if (tb && typeof tb === "object" && "llm_ms" in tb) {
    return tb as TimingBreakdown;
  }
  return undefined;
}

/** All image srcs from output: image gen (output.image) or Playwright screenshots (output.results, output.screenshot). */
function getOutputImageSrcs(output: unknown): string[] {
  const out = output as Record<string, unknown> | undefined;
  if (!out) return [];
  const srcs: string[] = [];
  const img = out.image;
  if (typeof img === "string" && (img.startsWith("data:image/") || img.startsWith("http"))) {
    srcs.push(img);
  }
  const base64 = out.file_base64;
  const mimeType = out.mime_type;
  if (
    typeof base64 === "string" &&
    base64.length > 0 &&
    typeof mimeType === "string" &&
    mimeType.startsWith("image/")
  ) {
    const dataUrl = `data:${mimeType};base64,${base64}`;
    if (!srcs.includes(dataUrl)) srcs.push(dataUrl);
  }
  const shot = out.screenshot;
  if (typeof shot === "string" && shot.length > 100) {
    const dataUrl = `data:image/png;base64,${shot}`;
    if (!srcs.includes(dataUrl)) srcs.push(dataUrl);
  }
  const results = out.results as Record<string, unknown> | undefined;
  if (results && typeof results === "object") {
    for (const v of Object.values(results)) {
      if (typeof v === "string" && v.length > 100 && /^[A-Za-z0-9+/=]+$/.test(v)) {
        const dataUrl = `data:image/png;base64,${v}`;
        if (!srcs.includes(dataUrl)) srcs.push(dataUrl);
      }
    }
  }
  return srcs;
}

const imageLightboxSrc = ref<string | null>(null);

function handleDebugPanelWindowKeyDown(e: KeyboardEvent): void {
  if (e.key === "Escape" && isFinalOutputExpanded.value) {
    e.preventDefault();
    e.stopImmediatePropagation();
    isFinalOutputExpanded.value = false;
    return;
  }
  if (e.key === "Escape" && imageLightboxSrc.value) {
    e.stopPropagation();
    imageLightboxSrc.value = null;
  }
}

/** All screenshots from the run, in execution order. */
const allScreenshotsFromRun = computed(() => {
  const results = executionResult.value ? executionResult.value.node_results : nodeResults.value;
  const srcs: string[] = [];
  for (const r of results) {
    if (r.node_type === "condition" || r.node_type === "sticky" || r.status === "skipped") continue;
    srcs.push(...getOutputImageSrcs(r.output));
  }
  return srcs;
});

interface SkillGeneratedFile {
  filename: string;
  mime_type: string;
  size_bytes: number;
  download_url: string;
}

function extractGeneratedFiles(output: unknown): SkillGeneratedFile[] {
  const files: SkillGeneratedFile[] = [];
  const visited = new WeakSet<object>();

  function tryPushGeneratedFilesArray(raw: unknown): void {
    if (!Array.isArray(raw)) return;
    for (const item of raw) {
      if (!item || typeof item !== "object") continue;
      const f = item as Record<string, unknown>;
      if (
        typeof f.filename === "string" &&
        typeof f.mime_type === "string" &&
        typeof f.size_bytes === "number" &&
        typeof f.download_url === "string"
      ) {
        files.push({
          filename: f.filename,
          mime_type: f.mime_type,
          size_bytes: f.size_bytes,
          download_url: f.download_url,
        });
      }
    }
  }

  function walk(value: unknown, depth: number): void {
    if (depth > 6) return;

    if (Array.isArray(value)) {
      for (const item of value) {
        walk(item, depth + 1);
      }
      return;
    }

    if (!value || typeof value !== "object") return;

    const obj = value as Record<string, unknown>;
    if (visited.has(obj)) return;
    visited.add(obj);

    // Skill output sometimes places `_generated_files` at the root, but sometimes
    // it's nested under e.g. `tool_calls[].result._generated_files`.
    if (Object.prototype.hasOwnProperty.call(obj, "_generated_files")) {
      tryPushGeneratedFilesArray(obj._generated_files);
    }

    for (const v of Object.values(obj)) {
      walk(v, depth + 1);
    }
  }

  walk(output, 0);
  return files;
}

const skillGeneratedFiles = computed(() => {
  const results = executionResult.value ? executionResult.value.node_results : nodeResults.value;
  const files: SkillGeneratedFile[] = [];
  for (const r of results) {
    if (r.status === "skipped") continue;
    files.push(...extractGeneratedFiles(r.output));
  }

  const seen = new Set<string>();
  return files.filter((f) => {
    if (seen.has(f.download_url)) return false;
    seen.add(f.download_url);
    return true;
  });
});

const downloadDialogOpen = ref(false);

function handleDownloadDialogKeyDown(e: KeyboardEvent): void {
  if (e.key === "Escape" && downloadDialogOpen.value) {
    e.stopPropagation();
    downloadDialogOpen.value = false;
  }
}

function onDownloadGeneratedFiles(): void {
  const files = skillGeneratedFiles.value;
  if (files.length === 1) {
    window.open(files[0].download_url, "_blank", "noopener");
    return;
  }
  if (files.length > 1) {
    downloadDialogOpen.value = true;
  }
}

function downloadGeneratedFile(file: SkillGeneratedFile): void {
  window.open(file.download_url, "_blank", "noopener");
  downloadDialogOpen.value = false;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  workflowJson?: {
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
  };
  hasParseError?: boolean;
}

interface SpeechRecognitionResultAlternative {
  transcript: string;
}

interface SpeechRecognitionResultItem {
  isFinal: boolean;
  0: SpeechRecognitionResultAlternative;
}

interface SpeechRecognitionResultList {
  length: number;
  [index: number]: SpeechRecognitionResultItem;
}

interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

interface SpeechRecognitionWindow extends Window {
  webkitSpeechRecognition?: new () => SpeechRecognition;
  SpeechRecognition?: new () => SpeechRecognition;
}

const aiPanelOpen = ref(false);
const aiLoading = ref(false);
const aiStreaming = ref(false);
const aiAbortController = ref<AbortController | null>(null);
const canvasMode = ref<"agent" | "ask">("agent");

const aiCredentials = ref<CredentialListItem[]>([]);
/** Full credential list (owned + shared) for stripping shared IDs when applying AI-generated workflows */
const allCredentialsForSanitize = ref<CredentialListItem[]>([]);
const aiModels = ref<LLMModel[]>([]);
const selectedCredentialId = ref("");
const selectedModel = ref("");
const loadingModels = ref(false);

const aiMessages = ref<ChatMessage[]>([]);
const aiInputMessage = ref("");
const aiMessagesContainer = ref<HTMLDivElement | null>(null);
const aiTextareaRef = ref<HTMLTextAreaElement | null>(null);
const availableWorkflows = ref<WorkflowWithInputs[]>([]);
const speechRecognition = ref<SpeechRecognition | null>(null);
const isSpeechSupported = ref(false);
const isListening = ref(false);
const isFixingTranscription = ref(false);

const lastWorkflowJson = computed(() => {
  if (aiMessages.value.length === 0) return null;
  const lastMessage = aiMessages.value[aiMessages.value.length - 1];
  return lastMessage.workflowJson || null;
});

const currentWorkflowContext = computed(() => {
  if (workflowStore.nodes.length === 0 && workflowStore.edges.length === 0) {
    return undefined;
  }

  const filteredNodes = workflowStore.nodes.map((node) => {
    if (node.type !== "agent") return node;
    const filteredSkills = (node.data.skills ?? []).map((skill: AgentSkill) => ({
      ...skill,
      files: (skill.files ?? []).filter((file: AgentSkillFile) => file.path.endsWith(".md")),
    }));
    return {
      ...node,
      data: {
        ...node.data,
        skills: filteredSkills,
      },
    };
  });

  return {
    id: workflowStore.currentWorkflow?.id,
    name: workflowStore.currentWorkflow?.name,
    nodes: filteredNodes,
    edges: workflowStore.edges,
  };
});

const conversationHistory = computed(() => {
  return aiMessages.value
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      role: m.role,
      content: m.content,
    }));
});

function scrollAiToBottom(): void {
  nextTick(() => {
    if (aiMessagesContainer.value) {
      aiMessagesContainer.value.scrollTop = aiMessagesContainer.value.scrollHeight;
    }
  });
}

watch(aiMessages, scrollAiToBottom, { deep: true });

function setupSpeechRecognition(): void {
  const recognitionWindow = window as SpeechRecognitionWindow;
  const SpeechRecognitionConstructor = recognitionWindow.SpeechRecognition || recognitionWindow.webkitSpeechRecognition;
  if (!SpeechRecognitionConstructor) {
    isSpeechSupported.value = false;
    return;
  }
  isSpeechSupported.value = true;
  const recognition = new SpeechRecognitionConstructor();
  recognition.lang = "tr-TR";
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.onresult = (event: SpeechRecognitionEvent) => {
    const transcripts = Array.from(event.results).map(result => result[0]?.transcript ?? "");
    const transcript = transcripts.join("").trim();
    if (transcript) {
      aiInputMessage.value = transcript;
    }
  };
  recognition.onerror = () => {
    isListening.value = false;
  };
  recognition.onend = () => {
    if (isListening.value && speechRecognition.value) {
      speechRecognition.value.start();
    } else {
      isListening.value = false;
    }
  };
  speechRecognition.value = recognition;
}

async function fixTranscriptionIfNeeded(): Promise<void> {
  const text = aiInputMessage.value.trim();
  if (!text || !selectedCredentialId.value || !selectedModel.value) return;

  isFixingTranscription.value = true;
  try {
    const response = await aiApi.fixTranscription({
      credentialId: selectedCredentialId.value,
      model: selectedModel.value,
      text: text,
    });
    aiInputMessage.value = response.fixed_text;
  } catch {
    // keep original text
  } finally {
    isFixingTranscription.value = false;
  }
}

function toggleSpeechInput(): void {
  if (!speechRecognition.value) return;
  if (isListening.value) {
    isListening.value = false;
    speechRecognition.value.stop();
    fixTranscriptionIfNeeded();
    return;
  }
  aiInputMessage.value = "";
  isListening.value = true;
  speechRecognition.value.start();
}

async function loadAiCredentials(): Promise<void> {
  try {
    aiCredentials.value = await credentialsApi.listLLM();
    if (aiCredentials.value.length > 0 && !selectedCredentialId.value) {
      const firstOwned = aiCredentials.value.find((c) => !c.is_shared);
      selectedCredentialId.value = (firstOwned ?? aiCredentials.value[0]).id;
    }
  } catch {
    aiCredentials.value = [];
  }
}

async function loadAllCredentialsForSanitize(): Promise<void> {
  try {
    allCredentialsForSanitize.value = await credentialsApi.list();
  } catch {
    allCredentialsForSanitize.value = [];
  }
}

async function loadAiModels(): Promise<void> {
  if (!selectedCredentialId.value) {
    aiModels.value = [];
    selectedModel.value = "";
    return;
  }

  loadingModels.value = true;
  try {
    aiModels.value = await credentialsApi.getModels(selectedCredentialId.value);
    if (aiModels.value.length > 0) {
      selectedModel.value = aiModels.value[aiModels.value.length - 1].id;
    }
  } catch {
    aiModels.value = [];
    selectedModel.value = "";
  } finally {
    loadingModels.value = false;
  }
}

watch(selectedCredentialId, loadAiModels);

async function loadAvailableWorkflows(): Promise<void> {
  try {
    const workflows = await workflowApi.listWithInputs();
    const currentId = workflowStore.currentWorkflow?.id;
    availableWorkflows.value = workflows.filter((wf) => wf.id !== currentId);
  } catch {
    availableWorkflows.value = [];
  }
}

let unsubDismissOverlays: (() => void) | null = null;

onMounted(() => {
  unsubDismissOverlays = onDismissOverlays(() => {
    isFinalOutputExpanded.value = false;
  });
  workflowStore.setDebugPanelHeight(panelHeight.value);
  setupSpeechRecognition();
  void loadAiCredentials();
  void loadAllCredentialsForSanitize();
  loadAvailableWorkflows();
  window.addEventListener("keydown", handleDebugPanelWindowKeyDown, true);
  window.addEventListener("keydown", handleDownloadDialogKeyDown, true);
});

onUnmounted(() => {
  unsubDismissOverlays?.();
  unsubDismissOverlays = null;
  window.removeEventListener("keydown", handleDebugPanelWindowKeyDown, true);
  window.removeEventListener("keydown", handleDownloadDialogKeyDown, true);
});

function toggleAiPanel(): void {
  aiPanelOpen.value = !aiPanelOpen.value;
  if (aiPanelOpen.value && aiCredentials.value.length === 0) {
    void loadAiCredentials();
  }
  if (aiPanelOpen.value) {
    void loadAllCredentialsForSanitize();
    nextTick(() => {
      aiTextareaRef.value?.focus();
    });
  }
}

function askAiAboutError(result: {
  node_label: string;
  node_type: string;
  error: string | null;
}): void {
  aiPanelOpen.value = true;
  canvasMode.value = "ask";
  if (aiCredentials.value.length === 0) {
    void loadAiCredentials();
  }
  void loadAllCredentialsForSanitize();
  aiInputMessage.value = `Help me fix this error:\n\nNode: ${result.node_label} (${result.node_type})\nError: ${result.error}`;
  nextTick(() => {
    void sendAiMessage();
  });
}

function normalizeAgentToolParameters(nodes: WorkflowNode[]): void {
  for (const node of nodes) {
    const tools = node.data?.tools;
    if (!Array.isArray(tools)) continue;
    for (const tool of tools) {
      const params = tool.parameters;
      if (params != null && typeof params === "object") {
        try {
          (tool as { parameters: string }).parameters = JSON.stringify(params);
        } catch {
          (tool as { parameters: string }).parameters = '{"type":"object","properties":{},"required":[]}';
        }
      }
    }
  }
}

function tryParseWorkflowJson(raw: string): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } | null {
  function validate(parsed: unknown): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } | null {
    if (parsed && typeof parsed === "object" && "nodes" in parsed && Array.isArray((parsed as { nodes: unknown }).nodes)) {
      const p = parsed as { nodes: WorkflowNode[]; edges?: WorkflowEdge[] };
      const nodes = p.nodes;
      const edges = p.edges || [];
      normalizeAgentToolParameters(nodes);
      return { nodes, edges };
    }
    return null;
  }

  try {
    const parsed = JSON.parse(raw);
    return validate(parsed);
  } catch {
    // Try fixing common LLM JSON errors (trailing commas)
    const fixed = raw.replace(/,(\s*[}\]])/g, "$1");
    try {
      const parsed = JSON.parse(fixed);
      return validate(parsed);
    } catch {
      // Use jsonrepair for malformed JSON (unescaped quotes, bad escapes, etc.)
      try {
        const repaired = jsonrepair(raw);
        const parsed = JSON.parse(repaired);
        return validate(parsed);
      } catch {
        // ignore
      }
    }
  }
  return null;
}

function extractWorkflowJson(content: string): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } | null {
  const jsonStart = content.indexOf("```json");
  if (jsonStart === -1) return null;

  const afterJson = content.slice(jsonStart + 7);
  const firstNewline = afterJson.search(/\n/);
  const bodyStart = firstNewline >= 0 ? firstNewline + 1 : 0;
  const body = afterJson.slice(bodyStart);

  const backtickPositions: number[] = [];
  let pos = 0;
  while ((pos = body.indexOf("```", pos)) >= 0) {
    backtickPositions.push(pos);
    pos += 3;
  }

  let best: { result: { nodes: WorkflowNode[]; edges: WorkflowEdge[] }; totalTools: number } | null = null;
  for (let i = 0; i < backtickPositions.length; i++) {
    const raw = body.slice(0, backtickPositions[i]).trim();
    const result = tryParseWorkflowJson(raw);
    if (result) {
      const totalTools = result.nodes
        .filter((n) => n.type === "agent")
        .reduce((sum, n) => sum + ((n.data?.tools as unknown[] | undefined)?.length ?? 0), 0);
      if (!best || totalTools >= best.totalTools) {
        best = { result, totalTools };
      }
    }
  }

  if (!best) {
    const raw = body.trim();
    const result = tryParseWorkflowJson(raw);
    if (result) best = { result, totalTools: 0 };
  }

  if (best) return best.result;
  return null;
}

async function sendAiMessage(): Promise<void> {
  const message = aiInputMessage.value.trim();
  if (!message || !selectedCredentialId.value || !selectedModel.value) return;
  if (aiStreaming.value) return;

  const userMessage: ChatMessage = {
    id: `msg_${Date.now()}`,
    role: "user",
    content: message,
  };
  aiMessages.value.push(userMessage);
  aiInputMessage.value = "";

  const assistantMessage: ChatMessage = {
    id: `msg_${Date.now()}_assistant`,
    role: "assistant",
    content: "",
  };
  aiMessages.value.push(assistantMessage);

  aiStreaming.value = true;
  aiLoading.value = true;
  aiAbortController.value = new AbortController();

  const historyForRequest = conversationHistory.value.slice(0, -2);

  const isAskMode = canvasMode.value === "ask";

  aiApi.assistantStream(
    {
      credentialId: selectedCredentialId.value,
      model: selectedModel.value,
      message: message,
      currentWorkflow: currentWorkflowContext.value,
      conversationHistory: historyForRequest,
      availableWorkflows: availableWorkflows.value.map((wf) => ({
        id: wf.id,
        name: wf.name,
        description: wf.description,
        input_fields: wf.input_fields,
        output_node: wf.output_node,
      })),
      askMode: isAskMode,
    },
    (text) => {
      aiLoading.value = false;
      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        lastMsg.content += text;
      }
    },
    () => {
      aiStreaming.value = false;
      aiLoading.value = false;
      aiAbortController.value = null;

      if (isAskMode) return;

      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        const workflowJson = extractWorkflowJson(lastMsg.content);
        if (workflowJson) {
          lastMsg.workflowJson = workflowJson;
          lastMsg.hasParseError = false;
          playSuccessSound();
          setTimeout(() => {
            applyWorkflowChanges(true);
          }, 300);
        } else if (lastMsg.content.trim().length > 0) {
          lastMsg.hasParseError = true;
        }
      }
    },
    (error) => {
      aiStreaming.value = false;
      aiLoading.value = false;
      aiAbortController.value = null;

      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        lastMsg.content = `Error: ${error.message}`;
      }
    },
    aiAbortController.value.signal,
  );
}

function stopAiStreaming(): void {
  if (aiAbortController.value) {
    aiAbortController.value.abort();
    aiAbortController.value = null;
  }
  aiStreaming.value = false;
  aiLoading.value = false;
}

function retryMessage(failedMessageId: string): void {
  if (aiStreaming.value) return;

  const failedMsgIndex = aiMessages.value.findIndex((m) => m.id === failedMessageId);
  if (failedMsgIndex === -1) return;

  let userMessageIndex = failedMsgIndex - 1;
  while (userMessageIndex >= 0 && aiMessages.value[userMessageIndex].role !== "user") {
    userMessageIndex--;
  }

  if (userMessageIndex < 0) return;

  const userMessage = aiMessages.value[userMessageIndex].content;

  const assistantMessage: ChatMessage = {
    id: `msg_${Date.now()}_assistant_retry`,
    role: "assistant",
    content: "",
  };
  aiMessages.value.push(assistantMessage);

  aiStreaming.value = true;
  aiLoading.value = true;
  aiAbortController.value = new AbortController();

  const historyForRequest = conversationHistory.value.slice(0, -2);

  aiApi.assistantStream(
    {
      credentialId: selectedCredentialId.value,
      model: selectedModel.value,
      message: userMessage,
      currentWorkflow: currentWorkflowContext.value,
      conversationHistory: historyForRequest,
      availableWorkflows: availableWorkflows.value.map((wf) => ({
        id: wf.id,
        name: wf.name,
        description: wf.description,
        input_fields: wf.input_fields,
        output_node: wf.output_node,
      })),
    },
    (text) => {
      aiLoading.value = false;
      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        lastMsg.content += text;
      }
    },
    () => {
      aiStreaming.value = false;
      aiLoading.value = false;
      aiAbortController.value = null;

      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        const workflowJson = extractWorkflowJson(lastMsg.content);
        if (workflowJson) {
          lastMsg.workflowJson = workflowJson;
          lastMsg.hasParseError = false;
          playSuccessSound();
          setTimeout(() => {
            applyWorkflowChanges(true);
          }, 300);
        } else if (lastMsg.content.trim().length > 0) {
          lastMsg.hasParseError = true;
        }
      }
    },
    (error) => {
      aiStreaming.value = false;
      aiLoading.value = false;
      aiAbortController.value = null;

      const lastMsg = aiMessages.value[aiMessages.value.length - 1];
      if (lastMsg && lastMsg.role === "assistant") {
        lastMsg.content = `Error: ${error.message}`;
      }
    },
    aiAbortController.value.signal,
  );
}


function tidyUpNodes(): void {
  const nodes = workflowStore.nodes;
  const edges = workflowStore.edges;

  if (nodes.length === 0) return;

  const stickyNodeIds = new Set(nodes.filter((n) => n.type === "sticky").map((n) => n.id));
  const layoutNodes = nodes.filter((n) => !stickyNodeIds.has(n.id));
  const layoutEdges = edges.filter(
    (e) => !stickyNodeIds.has(e.source) && !stickyNodeIds.has(e.target),
  );

  if (layoutNodes.length === 0) return;

  const subAgentNodeIds = new Set<string>();
  const orchestratorToSubAgents = new Map<string, string[]>();
  layoutNodes.forEach((n) => {
    if (
      n.type === "agent" &&
      n.data?.isOrchestrator &&
      (n.data?.subAgentLabels as string[] | undefined)?.length
    ) {
      const labels = n.data.subAgentLabels as string[];
      const subIds: string[] = [];
      labels.forEach((label) => {
        const subNode = layoutNodes.find(
          (n2) => n2.type === "agent" && n2.data?.label === label
        );
        if (subNode) {
          subAgentNodeIds.add(subNode.id);
          subIds.push(subNode.id);
        }
      });
      orchestratorToSubAgents.set(n.id, subIds);
    }
  });

  const inDegree = new Map<string, number>();
  const outEdges = new Map<string, { target: string; sourceHandle?: string }[]>();

  layoutNodes.forEach(n => {
    inDegree.set(n.id, 0);
    outEdges.set(n.id, []);
  });

  const forwardEdges = layoutEdges.filter(e => e.targetHandle !== "loop");

  forwardEdges.forEach(e => {
    inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
    outEdges.get(e.source)?.push({ target: e.target, sourceHandle: e.sourceHandle });
  });

  const levels: string[][] = [];
  const visited = new Set<string>();
  const nodeSourceHandle = new Map<string, string | undefined>();

  let currentLevel = layoutNodes.filter(n => inDegree.get(n.id) === 0).map(n => n.id);

  while (currentLevel.length > 0) {
    levels.push(currentLevel);
    currentLevel.forEach(id => visited.add(id));

    const nextLevel: string[] = [];
    currentLevel.forEach(nodeId => {
      outEdges.get(nodeId)?.forEach(({ target: targetId, sourceHandle }) => {
        if (!visited.has(targetId) && !nextLevel.includes(targetId)) {
          const allInputsVisited = forwardEdges
            .filter(e => e.target === targetId)
            .every(e => visited.has(e.source));
          if (allInputsVisited) {
            nextLevel.push(targetId);
            nodeSourceHandle.set(targetId, sourceHandle);
          }
        }
      });
    });

    nextLevel.sort((a, b) => {
      const handleA = nodeSourceHandle.get(a);
      const handleB = nodeSourceHandle.get(b);

      const getOrder = (handle: string | undefined): number => {
        if (!handle) return 0;
        if (handle === "output") return 0;
        if (handle === "batchStatus") return 1;
        if (handle === "true") return 0;
        if (handle === "false") return 1;
        if (handle === "hitl") return 1;
        if (handle === "error") return 2;
        if (handle === "loop") return 0;
        if (handle === "done") return 1;
        if (handle === "default") return 999;
        if (handle.startsWith("case-")) {
          const index = parseInt(handle.split("-")[1] || "", 10);
          if (!Number.isNaN(index)) return index;
        }
        return 100;
      };

      return getOrder(handleA) - getOrder(handleB);
    });

    currentLevel = nextLevel;
  }

  layoutNodes.filter(n => !visited.has(n.id)).forEach(n => {
    levels.push([n.id]);
    visited.add(n.id);
  });

  const NODE_WIDTH = 200;
  const NODE_HEIGHT = 80;
  const HORIZONTAL_GAP = 100;
  const VERTICAL_GAP = 60;
  const LOOP_BRANCH_OFFSET = 200;
  const DONE_BRANCH_OFFSET = 50;
  const BATCH_LLM_INTER_COLUMN_EXTRA = 80;
  const START_X = 50;
  const START_Y = 200;
  const STRIDE = NODE_HEIGHT + VERTICAL_GAP;
  const measuredNodeSizes = buildMeasuredNodeSizeMap(getNodes.value);
  const layoutNodeById = new Map(layoutNodes.map((node) => [node.id, node]));
  const getNodeWidth = (nodeId: string): number => {
    const node = layoutNodeById.get(nodeId);
    if (node === undefined) return NODE_WIDTH;
    return getWorkflowNodeLayoutSize(node, measuredNodeSizes, {
      isSubAgent: subAgentNodeIds.has(nodeId),
    }).width;
  };
  const getLevelWidth = (level: string[]): number => {
    const placedNodeIds = level.filter((nodeId) => !subAgentNodeIds.has(nodeId));
    if (placedNodeIds.length === 0) return NODE_WIDTH;
    return Math.max(...placedNodeIds.map((nodeId) => getNodeWidth(nodeId)));
  };

  const loopBranchNodes = new Set<string>();
  const doneBranchNodes = new Set<string>();
  const loopNodeIds = layoutNodes.filter(n => n.type === "loop").map(n => n.id);

  loopNodeIds.forEach(loopId => {
    const loopOutEdges = forwardEdges.filter(e => e.source === loopId && e.sourceHandle === "loop");
    const toVisit = loopOutEdges.map(e => e.target);

    while (toVisit.length > 0) {
      const nodeId = toVisit.shift()!;
      if (loopBranchNodes.has(nodeId) || nodeId === loopId) continue;
      loopBranchNodes.add(nodeId);

      const childEdges = forwardEdges.filter(e => e.source === nodeId);
      childEdges.forEach(e => {
        if (!loopBranchNodes.has(e.target) && e.target !== loopId) {
          toVisit.push(e.target);
        }
      });
    }

    const doneOutEdges = forwardEdges.filter(e => e.source === loopId && e.sourceHandle === "done");
    const doneToVisit = doneOutEdges.map(e => e.target);

    while (doneToVisit.length > 0) {
      const nodeId = doneToVisit.shift()!;
      if (doneBranchNodes.has(nodeId) || loopBranchNodes.has(nodeId)) continue;
      doneBranchNodes.add(nodeId);

      const childEdges = forwardEdges.filter(e => e.source === nodeId);
      childEdges.forEach(e => {
        if (!doneBranchNodes.has(e.target) && !loopBranchNodes.has(e.target)) {
          doneToVisit.push(e.target);
        }
      });
    }
  });

  const nodePositions = new Map<string, { x: number; y: number }>();

  const columnX: number[] = [START_X];
  for (let k = 1; k < levels.length; k++) {
    const prevHasBatchLlm = levels[k - 1].some((id) => {
      const n = layoutNodes.find((nn) => nn.id === id);
      return n?.type === "llm" && n.data?.batchModeEnabled === true;
    });
    const extra = prevHasBatchLlm ? BATCH_LLM_INTER_COLUMN_EXTRA : 0;
    columnX.push(columnX[k - 1] + getLevelWidth(levels[k - 1]) + HORIZONTAL_GAP + extra);
  }

  levels.forEach((level, levelIndex) => {
    const mainNodes = level.filter(
      id => !loopBranchNodes.has(id) && !doneBranchNodes.has(id) && !subAgentNodeIds.has(id)
    );
    const loopNodes = level.filter(id => loopBranchNodes.has(id) && !subAgentNodeIds.has(id));
    const doneNodes = level.filter(id => doneBranchNodes.has(id) && !subAgentNodeIds.has(id));

    const x = columnX[levelIndex] ?? START_X;
    const firstMainY = START_Y;

    loopNodes.forEach((nodeId, nodeIndex) => {
      const y = START_Y - LOOP_BRANCH_OFFSET + nodeIndex * STRIDE;
      nodePositions.set(nodeId, { x, y });
      workflowStore.updateNodePosition(nodeId, { x, y });
    });

    mainNodes.forEach((nodeId, nodeIndex) => {
      const y = firstMainY + nodeIndex * STRIDE;
      nodePositions.set(nodeId, { x, y });
      workflowStore.updateNodePosition(nodeId, { x, y });
    });

    doneNodes.forEach((nodeId, nodeIndex) => {
      const y = START_Y + DONE_BRANCH_OFFSET + nodeIndex * STRIDE;
      nodePositions.set(nodeId, { x, y });
      workflowStore.updateNodePosition(nodeId, { x, y });
    });
  });

  layoutNodes.forEach((node) => {
    const nodeId = node.id;
    if (subAgentNodeIds.has(nodeId)) return;
    if (node.type !== "llm" || !node.data?.batchModeEnabled) return;

    const childTargets = [
      ...new Set(forwardEdges.filter((e) => e.source === nodeId).map((e) => e.target)),
    ];
    if (childTargets.length < 1) return;

    const ys: number[] = [];
    for (const cid of childTargets) {
      const p = nodePositions.get(cid);
      if (p !== undefined) ys.push(p.y);
    }
    if (childTargets.length === 1 && ys.length === 1) {
      ys.push(ys[0] + STRIDE);
    }
    if (ys.length < 2) return;

    const newY = (Math.min(...ys) + Math.max(...ys)) / 2;
    const pos = nodePositions.get(nodeId);
    if (pos === undefined) return;
    pos.y = newY;
    workflowStore.updateNodePosition(nodeId, { x: pos.x, y: newY });
  });

  orchestratorToSubAgents.forEach((subIds, orchId) => {
    const pos = nodePositions.get(orchId);
    if (!pos) return;
    const subY = pos.y + STRIDE;
    const orchCenterX = pos.x + getNodeWidth(orchId) / 2;
    const subWidths = subIds.map((subId) => getNodeWidth(subId));
    const totalSubWidth = subWidths.reduce((sum, width) => sum + width, 0)
      + (subIds.length - 1) * HORIZONTAL_GAP;
    const startX = orchCenterX - totalSubWidth / 2;
    let nextX = startX;
    subIds.forEach((subId, index) => {
      const x = nextX;
      nextX += (subWidths[index] ?? NODE_WIDTH) + HORIZONTAL_GAP;
      workflowStore.updateNodePosition(subId, { x, y: subY });
    });
  });

  void nextTick(() => {
    updateNodeInternals(nodes.map((n) => n.id));
    setTimeout(() => fitView({ padding: 0.2 }), 100);
  });
}

const PLACEHOLDER_CREDENTIAL_PATTERNS = [
  "YOUR_CREDENTIAL_ID",
  "credential-uuid",
  "llm-credential-uuid",
  "slack-credential-uuid",
  "telegram-credential-uuid",
  "imap-credential-uuid",
  "smtp-credential-uuid",
  "redis-credential-uuid",
  "grist-credential-uuid",
  "rabbitmq-credential-uuid",
  "flaresolverr-cred-id",
  "openai-cred-id",
];

function isPlaceholderOrInvalidCredential(credentialId: string | undefined): boolean {
  if (!credentialId || credentialId.trim() === "") return true;
  const lower = credentialId.toLowerCase();
  if (PLACEHOLDER_CREDENTIAL_PATTERNS.some((p) => lower.includes(p.toLowerCase()))) return true;
  const match = aiCredentials.value.find((c) => c.id === credentialId);
  if (!match) return true;
  return false;
}

/**
 * Clear AI-generated credentialId when unknown, placeholder, or shared (only owned credentials are kept).
 */
function shouldClearIntegrationCredentialId(credentialId: string | undefined): boolean {
  if (!credentialId || credentialId.trim() === "") return false;
  const lower = credentialId.toLowerCase();
  if (PLACEHOLDER_CREDENTIAL_PATTERNS.some((p) => lower.includes(p.toLowerCase()))) return true;
  const match = allCredentialsForSanitize.value.find((c) => c.id === credentialId);
  if (!match) return true;
  if (match.is_shared) return true;
  return false;
}

function sanitizeIntegrationCredentialFields(node: WorkflowNode): WorkflowNode {
  const t = node.type;
  const integrationTypes = new Set([
    "slack",
    "telegram",
    "imapTrigger",
    "telegramTrigger",
    "sendEmail",
    "redis",
    "grist",
    "rabbitmq",
    "crawler",
    "googleSheets",
    "slackTrigger",
    "bigquery",
  ]);
  if (!integrationTypes.has(t) && t !== "playwright") {
    return node;
  }
  const data = { ...node.data };
  const credId = data.credentialId as string | undefined;
  if (credId && shouldClearIntegrationCredentialId(credId)) {
    data.credentialId = "";
  }
  if (t === "playwright") {
    const sanitizePlaywrightSteps = (
      steps: PlaywrightStep[] | undefined,
    ): PlaywrightStep[] | undefined => {
      if (!Array.isArray(steps)) return steps;
      return steps.map((step) => {
        const s = step as { action?: string; credentialId?: string; model?: string };
        if (
          s.action === "aiStep" &&
          s.credentialId &&
          shouldClearIntegrationCredentialId(s.credentialId)
        ) {
          return { ...step, credentialId: "", model: "" };
        }
        return step;
      });
    };
    data.playwrightSteps = sanitizePlaywrightSteps(data.playwrightSteps);
    data.playwrightAuthFallbackSteps = sanitizePlaywrightSteps(data.playwrightAuthFallbackSteps);
  }
  return { ...node, data };
}

function isPlaceholderOrInvalidModel(modelId: string | undefined): boolean {
  if (!modelId || modelId.trim() === "") return true;
  return !aiModels.value.some((m) => m.id === modelId);
}

function isMarkdownSkillFile(file: AgentSkillFile): boolean {
  return file.path.toLowerCase().endsWith(".md");
}

function findMatchingExistingAgentNode(node: WorkflowNode): WorkflowNode | undefined {
  const byId = workflowStore.nodes.find((existingNode) => existingNode.type === "agent" && existingNode.id === node.id);
  if (byId) {
    return byId;
  }

  const label = node.data?.label;
  if (!label || typeof label !== "string") {
    return undefined;
  }

  return workflowStore.nodes.find(
    (existingNode) => existingNode.type === "agent" && existingNode.data?.label === label,
  );
}

function findMatchingExistingSkill(
  skill: AgentSkill,
  existingSkills: AgentSkill[],
): AgentSkill | undefined {
  if (skill.id) {
    const byId = existingSkills.find((existingSkill) => existingSkill.id === skill.id);
    if (byId) {
      return byId;
    }
  }

  if (skill.name) {
    return existingSkills.find((existingSkill) => existingSkill.name === skill.name);
  }

  return undefined;
}

function preserveAgentSkillFiles(node: WorkflowNode): WorkflowNode {
  if (node.type !== "agent") {
    return node;
  }

  const existingNode = findMatchingExistingAgentNode(node);
  if (!existingNode || existingNode.type !== "agent") {
    return node;
  }

  const existingSkills = existingNode.data?.skills;
  if (!existingSkills || existingSkills.length === 0) {
    return node;
  }

  const data = { ...node.data };
  if (data.skills === undefined) {
    data.skills = existingSkills;
    return { ...node, data };
  }

  const mergedSkills = data.skills.map((skill: AgentSkill) => {
    const existingSkill = findMatchingExistingSkill(skill, existingSkills);
    if (!existingSkill?.files || existingSkill.files.length === 0) {
      return skill;
    }

    const preservedFiles = existingSkill.files.filter((file) => !isMarkdownSkillFile(file));
    if (preservedFiles.length === 0) {
      return skill;
    }

    const nextFiles = [...(skill.files ?? [])];
    const seenPaths = new Set(nextFiles.map((file) => file.path));
    preservedFiles.forEach((file) => {
      if (!seenPaths.has(file.path)) {
        nextFiles.push(file);
      }
    });

    return {
      ...skill,
      files: nextFiles,
    };
  });

  data.skills = mergedSkills;
  return { ...node, data };
}

function applyWorkflowChanges(showMessage = true): void {
  if (!lastWorkflowJson.value) return;

  const { nodes: newNodes, edges: newEdges } = lastWorkflowJson.value;
  const newNodeIds = new Set(newNodes.map((n) => n.id));

  const effectiveCredentialId = selectedCredentialId.value;
  const effectiveModel = selectedModel.value;

  const sanitizedNodes = newNodes.map((node): WorkflowNode => {
    const mergedNode = preserveAgentSkillFiles(node);
    if (mergedNode.type !== "llm" && mergedNode.type !== "agent") {
      return sanitizeIntegrationCredentialFields(mergedNode);
    }

    const data = { ...mergedNode.data };
    const credId = data.credentialId as string | undefined;
    const model = data.model as string | undefined;

    if (isPlaceholderOrInvalidCredential(credId)) {
      data.credentialId = effectiveCredentialId || "";
      if (!effectiveCredentialId) {
        data.model = "";
      }
    }
    if (isPlaceholderOrInvalidModel(model)) {
      data.model = effectiveModel || "";
    }

    const fb = data.fallbackCredentialId as string | undefined;
    if (fb && shouldClearIntegrationCredentialId(fb)) {
      data.fallbackCredentialId = "";
      data.fallbackModel = "";
    }
    const gr = data.guardrailCredentialId as string | undefined;
    if (gr && shouldClearIntegrationCredentialId(gr)) {
      data.guardrailCredentialId = "";
      data.guardrailModel = "";
    }

    return sanitizeIntegrationCredentialFields({ ...mergedNode, data });
  });

  let edgesToApply = newEdges;
  if (newEdges.length === 0 && workflowStore.edges.length > 0) {
    edgesToApply = workflowStore.edges.filter(
      (e) => newNodeIds.has(e.source) && newNodeIds.has(e.target)
    );
  }

  workflowStore.nodes.splice(0, workflowStore.nodes.length, ...sanitizedNodes);
  workflowStore.edges.splice(
    0,
    workflowStore.edges.length,
    ...normalizeWorkflowEdges(edgesToApply, sanitizedNodes),
  );
  workflowStore.hasUnsavedChanges = true;
  workflowStore.clearExecution();

  if (showMessage) {
    aiMessages.value.push({
      id: `msg_${Date.now()}_system`,
      role: "assistant",
      content: "Workflow applied and tidied up!",
    });
  }

  setTimeout(() => {
    tidyUpNodes();
  }, 100);
}

function clearAiChat(): void {
  aiMessages.value = [];
}

function handleAiKeydown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendAiMessage();
  }
}

function sanitizeForDisplay(data: unknown): unknown {
  if (typeof data === "string") {
    if (data.startsWith("data:image")) {
      return data.slice(0, 150) + "...";
    }
    if (data.length > 100 && /^[A-Za-z0-9+/=]+$/.test(data)) {
      return "[Base64 data]";
    }
  }
  if (typeof data === "object" && data !== null) {
    if (Array.isArray(data)) {
      return data.map(sanitizeForDisplay);
    }
    const result: Record<string, unknown> = {};
    for (const key in data) {
      if (Object.prototype.hasOwnProperty.call(data, key)) {
        result[key] = sanitizeForDisplay((data as Record<string, unknown>)[key]);
      }
    }
    return result;
  }
  return data;
}

function renderContent(content: string): string {
  const codeBlocks: string[] = [];
  let result = content.replace(/```(\w+)?\n?([\s\S]*?)```/g, (_match, lang, code) => {
    const language = lang || "json";
    const escapedCode = code.trim()
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    const placeholder = `\x00CODEBLOCK${codeBlocks.length}\x00`;
    codeBlocks.push(`<div class="code-block"><div class="code-header">${language}</div><pre><code>${escapedCode}</code></pre></div>`);
    return placeholder;
  });

  result = result
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  result = result.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  result = result.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");
  result = result.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>');
  result = result.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>');
  result = result.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>');
  result = result.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>');
  result = result.replace(/^- (.+)$/gm, '<li class="md-li">$1</li>');

  codeBlocks.forEach((block, i) => {
    result = result.replace(`\x00CODEBLOCK${i}\x00`, block);
  });

  result = result.replace(/\n/g, "<br>");
  return result;
}
</script>

<template>
  <div
    class="border-t bg-card/50 flex flex-col relative overflow-x-hidden"
    :class="{ 'transition-[height] duration-200': !isResizing }"
    :style="{ height: `${panelHeight}px` }"
  >
    <div
      class="h-3 min-h-[44px] cursor-ns-resize hover:bg-primary/20 transition-colors flex items-center justify-center group md:h-1.5"
      :class="isResizing && 'bg-primary/30'"
      @mousedown="startResize"
    >
      <GripHorizontal class="w-8 h-3 text-muted-foreground/50 group-hover:text-muted-foreground" />
    </div>

    <div
      class="px-4 py-2 border-b flex items-center justify-between bg-muted/30 cursor-pointer"
      @click="toggleCollapse"
    >
      <div class="flex items-center gap-2">
        <Terminal class="w-4 h-4 text-muted-foreground" />
        <span class="font-medium text-sm">Execution Log</span>
        <component
          :is="isCollapsed ? ChevronUp : ChevronDown"
          class="w-4 h-4 text-muted-foreground"
        />
      </div>
      <div class="flex items-center gap-2">
        <div
          v-if="executionResult"
          class="flex items-center gap-2 text-xs mr-2"
        >
          <span :class="cn(statusColors[executionResult.status])">
            {{ executionResult.status.toUpperCase() }}
          </span>
          <span class="text-muted-foreground">
            {{ executionResult.execution_time_ms.toFixed(2) }}ms
          </span>
        </div>
        <Button
          v-if="isExecuting"
          variant="destructive"
          size="sm"
          class="h-11 min-h-[44px] md:h-7 px-2 gap-1"
          title="Stop execution"
          @click.stop="stopExecution"
        >
          <Square class="w-3 h-3 fill-current" />
          Stop
        </Button>
        <Button
          v-if="(executionResult || nodeResults.length > 0) && !isExecuting && !isCollapsed"
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
          title="Scroll to top"
          @click.stop="scrollContainer?.scrollTo({ top: 0, behavior: 'smooth' })"
        >
          <ChevronsUp class="w-3.5 h-3.5" />
        </Button>
        <Button
          v-if="(executionResult || nodeResults.length > 0) && !isCollapsed"
          :variant="showMarkdownInExecutionLog ? 'secondary' : 'ghost'"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
          :title="showMarkdownInExecutionLog ? 'Show plain text' : 'Show markdown'"
          @click.stop="showMarkdownInExecutionLog = !showMarkdownInExecutionLog"
        >
          <FileText class="w-3.5 h-3.5" />
        </Button>
        <Button
          v-if="(executionResult || nodeResults.length > 0) && !isExecuting"
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
          :title="logsCopied ? 'Copied!' : 'Copy logs as JSON'"
          @click.stop="copyLogsAsJson"
        >
          <CheckCircle2
            v-if="logsCopied"
            class="w-3.5 h-3.5 text-green-500"
          />
          <Copy
            v-else
            class="w-3.5 h-3.5"
          />
        </Button>
        <Button
          v-if="(executionResult || nodeResults.length > 0) && !isExecuting"
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
          title="Open in JSON Editor"
          @click.stop="openInJsonEditor"
        >
          <ExternalLink class="w-3.5 h-3.5" />
        </Button>
        <Button
          v-if="(executionResult || nodeResults.length > 0) && !isExecuting"
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
          title="Clear execution log"
          @click.stop="clearExecutionLog"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </Button>
        <Button
          v-if="skillGeneratedFiles.length > 0 && !isExecuting"
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
          title="Download generated files"
          @click.stop="onDownloadGeneratedFiles"
        >
          <Download class="w-3.5 h-3.5" />
        </Button>
        <Button
          v-if="(executionResult || nodeResults.length > 0) && !isExecuting"
          :variant="showTimeline ? 'secondary' : 'ghost'"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
          title="Execution timeline"
          @click.stop="toggleTimeline"
        >
          <Timer class="w-3.5 h-3.5" />
        </Button>
        <div class="w-px h-5 bg-border mx-1" />
        <Button
          :variant="aiPanelOpen ? 'default' : 'ghost'"
          size="sm"
          class="h-7 px-2 gap-1"
          title="AI Assistant"
          @click.stop="toggleAiPanel"
        >
          <Sparkles class="w-3.5 h-3.5" />
          AI
        </Button>
      </div>
    </div>

    <div
      v-if="!isCollapsed"
      ref="scrollContainer"
      class="flex-1 overflow-auto p-4 min-h-0"
    >
      <div
        v-if="displayResults.length === 0 && !isExecuting"
        class="flex items-center justify-center h-full"
      >
        <p class="text-muted-foreground text-sm">
          Run the workflow to see execution results
        </p>
      </div>

      <div
        v-else
        class="space-y-2 text-sm font-mono"
      >
        <div
          v-for="result in displayResults"
          :key="result.displayKey"
          class="flex items-start gap-3 p-2 rounded-md bg-muted/30"
        >
          <component
            :is="statusIcons[result.status as keyof typeof statusIcons]"
            :class="cn('w-4 h-4 shrink-0 mt-0.5', statusColors[result.status as keyof typeof statusColors], result.status === 'running' && 'animate-spin')"
          />
          <div class="flex-1 min-w-0">
            <div class="flex items-baseline justify-between gap-1">
              <span class="font-small truncate">
                {{ result.node_label || result.node_id }}
                <span
                  v-if="result.occurrence > 1"
                  class="ml-2 text-xs font-normal text-muted-foreground"
                >
                  #{{ result.occurrence }}
                </span>
              </span>
              <span class="text-xs text-muted-foreground shrink-0">
                {{ result.status === 'skipped' ? 'skipped' : `${result.execution_time_ms.toFixed(2)}ms` }}
              </span>
            </div>
            <div
              v-if="result.error"
            >
              <div class="text-red-400 text-xs break-all whitespace-pre-wrap">
                <div
                  v-if="Array.isArray((result.output as Record<string, unknown>)?.guardrail_violated_categories) && ((result.output as Record<string, unknown>).guardrail_violated_categories as string[]).length > 0"
                  class="font-medium mb-1"
                >
                  Blocked by: {{ ((result.output as Record<string, unknown>).guardrail_violated_categories as string[]).join(", ") }}
                </div>
                {{ result.error }}
              </div>
              <div class="flex justify-end mt-3">
                <Button
                  variant="default"
                  size="sm"
                  class="min-h-[12px]"
                  @click="askAiAboutError(result)"
                >
                  <Sparkles class="w-3 h-3" />
                  Ask AI
                </Button>
              </div>
            </div>
            <template v-else>
              <div
                v-if="getHitlPendingPayload(result.rawOutput)"
                class="mt-2 rounded border border-amber-500/30 bg-amber-500/10 p-3 text-xs"
              >
                <div class="font-medium text-amber-600 dark:text-amber-300">
                  Waiting for human review
                </div>
                <div class="mt-1 whitespace-pre-wrap text-muted-foreground">
                  {{ getHitlPendingPayload(result.rawOutput)!.summary }}
                </div>
                <div
                  v-if="getHitlDisplayDraftText(getHitlPendingPayload(result.rawOutput)!)"
                  class="mt-2 line-clamp-4 whitespace-pre-wrap text-muted-foreground"
                >
                  {{ getHitlDisplayDraftText(getHitlPendingPayload(result.rawOutput)!) }}
                </div>
                <div class="mt-3 flex flex-wrap gap-2">
                  <Button
                    v-if="getHitlPendingPayload(result.rawOutput)!.shareMarkdown"
                    variant="outline"
                    size="sm"
                    class="gap-1"
                    @click="copyText(getHitlPendingPayload(result.rawOutput)!.shareMarkdown!)"
                  >
                    <Copy class="h-3.5 w-3.5" />
                    Copy Share Text
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="gap-1"
                    @click="copyText(getHitlPendingPayload(result.rawOutput)!.reviewUrl)"
                  >
                    <Copy class="h-3.5 w-3.5" />
                    Copy Review Link
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    class="gap-1"
                    @click="openExternal(getHitlPendingPayload(result.rawOutput)!.reviewUrl)"
                  >
                    <ExternalLink class="h-3.5 w-3.5" />
                    Open Review Page
                  </Button>
                </div>
                <div class="mt-3 flex flex-wrap gap-2 border-t border-amber-500/20 pt-3">
                  <Button
                    variant="success"
                    size="sm"
                    class="gap-1 border border-emerald-600 bg-emerald-600 text-white shadow-sm hover:bg-emerald-700 hover:text-white"
                    :loading="isHitlSubmittingAction(getHitlPendingPayload(result.rawOutput)!.requestId, 'accept')"
                    :disabled="isHitlSubmitting(getHitlPendingPayload(result.rawOutput)!.requestId) || isHitlSubmitted(getHitlPendingPayload(result.rawOutput)!.requestId)"
                    @click="submitHitlDecision(getHitlPendingPayload(result.rawOutput)!, 'accept')"
                  >
                    <CheckCircle2 class="h-3.5 w-3.5" />
                    Accept
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="gap-1"
                    :disabled="isHitlSubmitting(getHitlPendingPayload(result.rawOutput)!.requestId) || isHitlSubmitted(getHitlPendingPayload(result.rawOutput)!.requestId)"
                    @click="openHitlEdit(getHitlPendingPayload(result.rawOutput)!)"
                  >
                    <Pencil class="h-3.5 w-3.5" />
                    Edit & Continue
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    class="gap-1"
                    :loading="isHitlSubmittingAction(getHitlPendingPayload(result.rawOutput)!.requestId, 'refuse')"
                    :disabled="isHitlSubmitting(getHitlPendingPayload(result.rawOutput)!.requestId) || isHitlSubmitted(getHitlPendingPayload(result.rawOutput)!.requestId)"
                    @click="submitHitlDecision(getHitlPendingPayload(result.rawOutput)!, 'refuse')"
                  >
                    <X class="h-3.5 w-3.5" />
                    Refuse
                  </Button>
                </div>
                <div
                  v-if="hitlEditRequestId === getHitlPendingPayload(result.rawOutput)!.requestId && !isHitlSubmitted(getHitlPendingPayload(result.rawOutput)!.requestId)"
                  class="mt-3 space-y-2"
                >
                  <Textarea
                    :model-value="getHitlEditText(getHitlPendingPayload(result.rawOutput)!.requestId, getHitlPendingPayload(result.rawOutput)!.draftText)"
                    :disabled="isHitlSubmitting(getHitlPendingPayload(result.rawOutput)!.requestId)"
                    :rows="5"
                    @update:model-value="setHitlEditText(getHitlPendingPayload(result.rawOutput)!.requestId, $event)"
                  />
                  <div class="flex flex-wrap justify-end gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      :disabled="isHitlSubmitting(getHitlPendingPayload(result.rawOutput)!.requestId)"
                      @click="cancelHitlEdit(getHitlPendingPayload(result.rawOutput)!.requestId)"
                    >
                      Cancel
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      class="gap-1"
                      :loading="isHitlSubmittingAction(getHitlPendingPayload(result.rawOutput)!.requestId, 'edit')"
                      :disabled="isHitlSubmitting(getHitlPendingPayload(result.rawOutput)!.requestId)"
                      @click="submitHitlDecision(getHitlPendingPayload(result.rawOutput)!, 'edit')"
                    >
                      <Send class="h-3.5 w-3.5" />
                      Continue
                    </Button>
                  </div>
                </div>
                <div
                  v-if="isHitlSubmitted(getHitlPendingPayload(result.rawOutput)!.requestId)"
                  class="mt-3 rounded border border-amber-500/20 bg-background/60 px-3 py-2 text-muted-foreground"
                >
                  Decision submitted. Waiting for the workflow to resume...
                </div>
                <div
                  v-if="getHitlError(getHitlPendingPayload(result.rawOutput)!.requestId)"
                  class="mt-2 text-destructive"
                >
                  {{ getHitlError(getHitlPendingPayload(result.rawOutput)!.requestId) }}
                </div>
                <div
                  v-if="getHitlPendingPayload(result.rawOutput)!.hitlHistory?.length"
                  class="mt-3 space-y-2 border-t border-amber-500/20 pt-3"
                >
                  <div class="text-[11px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-200">
                    Previous Human Review Decisions
                  </div>
                  <div
                    v-for="(entry, entryIndex) in getHitlPendingPayload(result.rawOutput)!.hitlHistory"
                    :key="entry.requestId || `${result.displayKey}-history-${entryIndex}`"
                    class="rounded border border-amber-500/20 bg-background/60 p-2"
                  >
                    <div class="font-medium text-amber-700 dark:text-amber-200">
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
              <div
                v-else-if="getHitlHistory(result.rawOutput).length"
                class="mt-2 rounded border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs"
              >
                <div class="flex items-center gap-2 font-medium text-emerald-600 dark:text-emerald-300">
                  <CheckCircle2 class="h-3.5 w-3.5" />
                  Human review history
                </div>
                <div class="mt-2 space-y-2">
                  <div
                    v-for="(entry, entryIndex) in getHitlHistory(result.rawOutput)"
                    :key="entry.requestId || `${result.displayKey}-resolved-${entryIndex}`"
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
              <div
                v-if="getSkillsUsed(result.output)?.length"
                class="mt-2 space-y-1.5"
              >
                <div class="text-xs font-medium text-muted-foreground">
                  Skills Used:
                </div>
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="(s, i) in getSkillsUsed(result.output)"
                    :key="i"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary"
                  >
                    {{ s }}
                  </span>
                </div>
              </div>
              <div
                v-if="getToolCalls(result.output)?.length"
                class="mt-2 space-y-1.5"
              >
                <div class="text-xs font-medium text-muted-foreground">
                  Tool Calls:
                </div>
                <div
                  v-for="(tc, i) in getToolCalls(result.output)"
                  :key="i"
                  class="rounded border border-border/50 bg-muted/20 p-2 text-xs"
                >
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="font-medium text-primary">
                      {{ formatToolCallTitle(tc) }}
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
                    <span
                      v-if="tc.elapsed_ms != null"
                      class="text-[10px] text-muted-foreground"
                    >
                      {{ tc.elapsed_ms.toFixed(0) }}ms
                    </span>
                  </div>
                  <div
                    v-if="hasCallSubWorkflowInputs(tc)"
                    class="mt-1.5 rounded bg-background/50 px-2 py-1 border border-border/40"
                  >
                    <div class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-0.5">
                      inputs
                    </div>
                    <pre class="text-[11px] whitespace-pre-wrap break-all text-muted-foreground font-mono max-h-40 overflow-y-auto">{{ formatCallSubWorkflowInputs(tc) }}</pre>
                  </div>
                  <div class="mt-1 text-muted-foreground break-all">
                    → {{ typeof tc.result === 'object' ? JSON.stringify(tc.result) : tc.result }}
                  </div>
                </div>
              </div>
              <div
                v-if="getTimingBreakdown(result.output)"
                class="mt-2 text-xs text-muted-foreground"
              >
                <span class="font-medium">Timing:</span>
                LLM {{ getTimingBreakdown(result.output)!.llm_ms.toFixed(0) }}ms
                + tools {{ getTimingBreakdown(result.output)!.tools_ms.toFixed(0) }}ms
                <template v-if="(getTimingBreakdown(result.output)!.mcp_list_ms ?? 0) > 0">
                  + MCP list {{ getTimingBreakdown(result.output)!.mcp_list_ms!.toFixed(0) }}ms
                </template>
              </div>
              <div
                v-if="getOutputImageSrcs(result.rawOutput).length > 0"
                class="mt-2 flex flex-wrap gap-1.5"
              >
                <img
                  v-for="(src, idx) in getOutputImageSrcs(result.rawOutput)"
                  :key="idx"
                  :src="src"
                  :alt="`Screenshot ${idx + 1}`"
                  class="w-16 h-16 rounded border object-cover cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all"
                  @click="imageLightboxSrc = src"
                >
              </div>
              <div
                v-if="shouldShowGenericResultOutput(result.rawOutput)"
                class="text-muted-foreground text-xs mt-1"
              >
                <div
                  v-if="showMarkdownInExecutionLog && getMarkdownDisplayText(result.output) !== null"
                  class="execution-markdown-output break-words font-sans"
                >
                  <!-- eslint-disable vue/no-v-html -->
                  <div v-html="renderExecutionMarkdown(getMarkdownDisplayText(result.output)!)" />
                  <!-- eslint-enable vue/no-v-html -->
                </div>
                <div
                  v-else
                  class="break-all whitespace-pre-wrap"
                >
                  {{ getGenericResultOutputText(result.output) }}
                </div>
              </div>
            </template>
          </div>
        </div>

        <div
          v-if="runningAgentNode && isExecuting"
          class="flex items-start gap-3 p-2 rounded-md bg-muted/30"
        >
          <Loader2 class="w-4 h-4 mt-0.5 shrink-0 animate-spin text-yellow-500" />
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between">
              <span class="font-medium">{{ runningAgentNode.data?.label || runningAgentNode.id }}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary">
                Live
              </span>
            </div>
            <div
              v-if="liveAgentEntries.length > 0"
              class="mt-2 space-y-1.5"
            >
              <div class="text-xs font-medium text-muted-foreground">
                Tool Calls (streaming):
              </div>
              <div
                v-for="(tc, i) in liveAgentEntries"
                :key="i"
                class="rounded border border-border/50 bg-muted/20 p-2 text-xs"
              >
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="font-medium text-primary">
                    {{ formatToolCallTitle(tc) }}
                  </span>
                  <span
                    v-if="tc.phase"
                    class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
                  >
                    {{ tc.phase }}
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
                  <span
                    v-if="tc.elapsed_ms != null"
                    class="text-[10px] text-muted-foreground"
                  >
                    {{ tc.elapsed_ms.toFixed(0) }}ms
                  </span>
                </div>
                <div
                  v-if="hasCallSubWorkflowInputs(tc)"
                  class="mt-1.5 rounded bg-background/50 px-2 py-1 border border-border/40"
                >
                  <div class="text-[10px] font-medium uppercase tracking-wide text-muted-foreground mb-0.5">
                    inputs
                  </div>
                  <pre class="text-[11px] whitespace-pre-wrap break-all text-muted-foreground font-mono max-h-40 overflow-y-auto">{{ formatCallSubWorkflowInputs(tc) }}</pre>
                </div>
                <div
                  v-if="tc.result != null"
                  class="mt-1 text-muted-foreground break-all"
                >
                  → {{ typeof tc.result === 'object' ? JSON.stringify(tc.result) : tc.result }}
                </div>
                <div
                  v-else
                  class="mt-1 text-muted-foreground"
                >
                  → pending...
                </div>
              </div>
            </div>
            <div
              v-else
              class="text-xs text-muted-foreground mt-1"
            >
              Running agent...
            </div>
          </div>
        </div>

        <div
          v-else-if="isExecuting"
          class="flex items-center gap-2 text-muted-foreground p-2"
        >
          <Loader2 class="w-4 h-4 animate-spin" />
          <span class="text-xs">Executing...</span>
        </div>

        <div
          v-if="allScreenshotsFromRun.length > 0 && !isExecuting"
          class="mt-3 pt-3 border-t border-border/50"
        >
          <div class="text-xs font-medium text-muted-foreground mb-2">
            Screenshots ({{ allScreenshotsFromRun.length }})
          </div>
          <div class="flex flex-wrap gap-2">
            <img
              v-for="(src, idx) in allScreenshotsFromRun"
              :key="idx"
              :src="src"
              :alt="`Screenshot ${idx + 1}`"
              class="w-20 h-20 rounded-md border object-cover cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all"
              @click="imageLightboxSrc = src"
            >
          </div>
        </div>

        <div
          v-if="executionResult?.status === 'success' && sanitizedFinalOutputs !== null"
          class="p-3 rounded-md bg-green-500/10 border border-green-500/20"
        >
          <div class="flex items-center justify-between gap-2 mb-1">
            <div class="text-xs text-green-400">
              Final Output:
            </div>
            <div class="flex items-center justify-end gap-1 shrink-0 flex-wrap">
              <Button
                variant="ghost"
                size="sm"
                class="h-7 px-2 gap-1.5"
                @click="isFinalOutputExpanded = !isFinalOutputExpanded"
              >
                <Maximize2
                  v-if="!isFinalOutputExpanded"
                  class="w-3.5 h-3.5"
                />
                <Minimize2
                  v-else
                  class="w-3.5 h-3.5"
                />
                <span class="text-xs">{{ isFinalOutputExpanded ? 'Minimize' : 'Expand' }}</span>
              </Button>
              <button
                type="button"
                class="flex items-center gap-1 px-2 py-1 rounded hover:bg-green-500/20 transition-colors text-xs shrink-0"
                :title="finalOutputCopied ? 'Copied!' : 'Copy to clipboard'"
                @click="copyFinalOutputToClipboard"
              >
                <CheckCircle2
                  v-if="finalOutputCopied"
                  class="w-3 h-3 text-green-400"
                />
                <Copy
                  v-else
                  class="w-3 h-3 text-green-400/80"
                />
                <span
                  v-if="finalOutputCopied"
                  class="text-green-400"
                >Copied</span>
              </button>
            </div>
          </div>
          <pre
            v-if="!isFinalOutputExpanded"
            class="text-xs overflow-auto whitespace-pre-wrap break-all max-h-48"
          >{{ formatFinalOutputForPre(sanitizedFinalOutputs) }}</pre>

          <Teleport to="body">
            <Transition name="fade">
              <div
                v-if="isFinalOutputExpanded && sanitizedFinalOutputs !== null"
                class="fixed inset-0 z-50 flex items-center justify-center"
              >
                <div
                  class="absolute inset-0 bg-black/50 backdrop-blur-sm"
                  @click="isFinalOutputExpanded = false"
                />
                <div
                  ref="finalOutputExpandedPanelRef"
                  class="relative w-[90vw] max-w-full h-[90vh] rounded-lg border border-border bg-card shadow-md flex flex-col overflow-x-hidden outline-none"
                  tabindex="-1"
                  role="dialog"
                  aria-modal="true"
                  @keydown.escape.stop.prevent="isFinalOutputExpanded = false"
                >
                  <div class="flex items-center justify-between gap-2 sm:gap-3 p-3 sm:p-4 border-b">
                    <div class="flex items-center gap-2 min-w-0 flex-1">
                      <CheckCircle2 class="w-4 h-4 text-green-500 shrink-0" />
                      <span class="text-sm font-medium truncate text-foreground">Final Output</span>
                    </div>
                    <div class="flex items-center justify-end gap-1 shrink-0 flex-wrap">
                      <template
                        v-if="typeof sanitizedFinalOutputs === 'object' && sanitizedFinalOutputs !== null"
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                          @click="expandAllFinalOutputJson"
                        >
                          Expand all
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                          @click="collapseAllFinalOutputJson"
                        >
                          Collapse all
                        </Button>
                      </template>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-11 min-h-[44px] md:h-7 px-2 gap-1.5"
                        @click="copyFinalOutputToClipboard"
                      >
                        <Copy class="w-3.5 h-3.5" />
                        <span class="text-xs">{{ finalOutputCopied ? 'Copied!' : 'Copy' }}</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                        @click="isFinalOutputExpanded = false"
                      >
                        <X class="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                  <div class="flex-1 overflow-y-auto p-4 min-h-0">
                    <div
                      v-if="typeof sanitizedFinalOutputs === 'object' && sanitizedFinalOutputs !== null"
                      class="text-xs font-mono"
                    >
                      <JsonTree
                        :key="finalOutputJsonTreeKey"
                        :data="sanitizedFinalOutputs"
                        :root-expanded="true"
                        :auto-expand-depth="finalOutputJsonAutoDepth"
                      />
                    </div>
                    <pre
                      v-else
                      class="text-xs font-mono whitespace-pre-wrap break-words text-foreground"
                    >{{ formatFinalOutputForPre(sanitizedFinalOutputs) }}</pre>
                  </div>
                </div>
              </div>
            </Transition>
          </Teleport>
        </div>
      </div>
    </div>
    <ExecutionTimeline
      v-if="!isCollapsed && showTimeline && timelineResults.length > 0"
      :node-results="timelineResults"
      :total-time-ms="executionResult?.execution_time_ms ?? 0"
      :sub-agent-label-to-parent-id="subAgentLabelToParentId"
      @select-node="selectCanvasNodeFromTimeline"
    />

    <Transition name="ai-slide">
      <div
        v-if="aiPanelOpen"
        class="ai-panel"
      >
        <div class="ai-panel-header">
          <div class="flex items-center gap-2">
            <Sparkles class="w-4 h-4 text-primary" />
            <span class="font-medium text-sm">AI Assistant</span>
          </div>
          <div class="flex items-center gap-2">
            <div class="mode-toggle">
              <button
                :class="['mode-toggle-btn', canvasMode === 'agent' && 'active']"
                title="Agent mode: builds and modifies the canvas"
                @click="canvasMode = 'agent'"
              >
                Agent
              </button>
              <button
                :class="['mode-toggle-btn', canvasMode === 'ask' && 'active']"
                title="Ask mode: answers questions without touching the canvas"
                @click="canvasMode = 'ask'"
              >
                Ask
              </button>
            </div>
            <button
              class="p-1 rounded hover:bg-muted transition-colors"
              @click="aiPanelOpen = false"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
        </div>

        <div class="ai-panel-config">
          <div class="config-row">
            <label class="config-label">Credential</label>
            <select
              v-model="selectedCredentialId"
              class="config-select"
              :title="aiCredentials.find(c => c.id === selectedCredentialId)?.name || ''"
            >
              <option
                value=""
                disabled
              >
                Select...
              </option>
              <option
                v-for="cred in aiCredentials"
                :key="cred.id"
                :value="cred.id"
                :title="cred.is_shared ? `${cred.name} - shared` : cred.name"
              >
                {{ cred.is_shared ? `${cred.name} - shared` : cred.name }}
              </option>
            </select>
          </div>

          <div class="config-row">
            <label class="config-label">Model</label>
            <select
              v-model="selectedModel"
              :disabled="!selectedCredentialId || loadingModels"
              class="config-select"
              :title="aiModels.find(m => m.id === selectedModel)?.name || ''"
            >
              <option
                value=""
                disabled
              >
                {{ loadingModels ? "Loading..." : "Select..." }}
              </option>
              <option
                v-for="model in aiModels"
                :key="model.id"
                :value="model.id"
                :title="model.name"
              >
                {{ model.name }}
              </option>
            </select>
          </div>
        </div>

        <div
          ref="aiMessagesContainer"
          class="ai-messages"
        >
          <div
            v-if="aiMessages.length === 0"
            class="empty-state"
          >
            <Bot class="w-12 h-12 text-muted-foreground/50 mb-3" />
            <p class="text-sm text-muted-foreground text-center">
              {{ canvasMode === 'ask' ? 'Ask me anything about your workflow or Heym' : 'Ask me to create or modify your workflow' }}
            </p>
          </div>

          <div
            v-for="msg in aiMessages"
            :key="msg.id"
            :class="['ai-message', msg.role]"
          >
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="message-content"
              v-html="renderContent(msg.content)"
            />
            <!-- eslint-enable vue/no-v-html -->
            <div
              v-if="msg.workflowJson"
              class="workflow-detected"
            >
              <LayoutGrid class="w-3 h-3" />
              <span>Auto-applying workflow...</span>
            </div>
            <div
              v-if="msg.hasParseError && !aiStreaming && canvasMode === 'agent'"
              class="parse-error-action"
            >
              <div class="parse-error-message">
                <AlertCircle class="w-3 h-3" />
                <span>Could not extract workflow from response</span>
              </div>
              <button
                class="retry-btn"
                :disabled="aiStreaming"
                @click="retryMessage(msg.id)"
              >
                <RefreshCcw class="w-3 h-3" />
                Retry
              </button>
            </div>
          </div>

          <div
            v-if="aiLoading && !aiMessages[aiMessages.length - 1]?.content"
            class="loading-indicator"
          >
            <Loader2 class="w-3 h-3 animate-spin" />
            <span>Thinking...</span>
          </div>
        </div>


        <div class="ai-input">
          <textarea
            ref="aiTextareaRef"
            v-model="aiInputMessage"
            :disabled="aiStreaming || !selectedCredentialId || !selectedModel"
            :placeholder="canvasMode === 'ask' ? 'Ask a question...' : 'Describe your workflow...'"
            class="ai-textarea"
            rows="2"
            @keydown="handleAiKeydown"
          />
          <div class="ai-input-actions">
            <button
              v-if="isSpeechSupported"
              class="ai-btn-secondary"
              :disabled="aiStreaming || isFixingTranscription || !selectedCredentialId || !selectedModel"
              :title="isListening ? 'Stop voice input' : isFixingTranscription ? 'Fixing...' : 'Voice input'"
              @click="toggleSpeechInput"
            >
              <Loader2
                v-if="isFixingTranscription"
                class="w-3.5 h-3.5 animate-spin"
              />
              <component
                :is="isListening ? MicOff : Mic"
                v-else
                class="w-3.5 h-3.5"
              />
              {{ isFixingTranscription ? "Fixing..." : isListening ? "Stop" : "Voice" }}
            </button>
            <button
              v-if="aiMessages.length > 0"
              class="ai-btn-secondary"
              title="Clear chat"
              @click="clearAiChat"
            >
              <Trash2 class="w-3.5 h-3.5" />
              Clear
            </button>
            <button
              v-if="aiStreaming"
              class="ai-btn-primary stop"
              title="Stop"
              @click="stopAiStreaming"
            >
              <Square class="w-3.5 h-3.5" />
              Stop
            </button>
            <button
              v-else
              :disabled="!aiInputMessage.trim() || !selectedCredentialId || !selectedModel"
              class="ai-btn-primary"
              title="Send"
              @click="sendAiMessage"
            >
              <Send class="w-3.5 h-3.5" />
              Send
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <Dialog
      :open="downloadDialogOpen"
      title="Download generated files"
      size="md"
      @close="downloadDialogOpen = false"
    >
      <div class="space-y-3">
        <p class="text-sm text-muted-foreground">
          Select a file to download.
        </p>
        <div
          class="space-y-2 max-h-[50vh] overflow-auto pr-1"
        >
          <Button
            v-for="file in skillGeneratedFiles"
            :key="file.download_url"
            variant="secondary"
            size="default"
            class="w-full justify-start"
            @click="downloadGeneratedFile(file)"
          >
            <Download class="w-3.5 h-3.5" />
            <span class="truncate max-w-[240px]">
              {{ file.filename }}
            </span>
            <span class="text-xs text-muted-foreground ml-auto">
              {{ formatFileSize(file.size_bytes) }}
            </span>
          </Button>
        </div>
      </div>
    </Dialog>

    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="imageLightboxSrc"
          class="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          @click="imageLightboxSrc = null"
        >
          <img
            :src="imageLightboxSrc"
            alt="Enlarged"
            class="max-w-[95vw] max-h-[95vh] object-contain rounded-lg shadow-2xl"
            @click.stop
          >
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.ai-panel {
  position: fixed;
  right: 24px;
  bottom: 24px;
  width: 400px;
  height: calc(100vh - 100px);
  max-height: 700px;
  background: hsl(var(--card));
  border: 1px solid hsl(var(--border));
  border-radius: 12px;
  box-shadow: 0 8px 32px hsl(var(--foreground) / 0.15);
  display: flex;
  flex-direction: column;
  z-index: 101;
  overflow: hidden;
}

.execution-markdown-output :deep(p) {
  margin: 0.35rem 0;
}

.execution-markdown-output :deep(p:first-child) {
  margin-top: 0;
}

.execution-markdown-output :deep(p:last-child) {
  margin-bottom: 0;
}

.execution-markdown-output :deep(h1),
.execution-markdown-output :deep(h2),
.execution-markdown-output :deep(h3),
.execution-markdown-output :deep(h4),
.execution-markdown-output :deep(h5),
.execution-markdown-output :deep(h6) {
  color: hsl(var(--foreground));
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1.35;
  margin: 0.65rem 0 0.35rem;
}

.execution-markdown-output :deep(ul),
.execution-markdown-output :deep(ol) {
  margin: 0.35rem 0;
  padding-left: 1.25rem;
}

.execution-markdown-output :deep(li) {
  margin: 0.15rem 0;
}

.execution-markdown-output :deep(code) {
  background: hsl(var(--muted) / 0.65);
  border-radius: 0.25rem;
  color: hsl(var(--foreground));
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 0.85em;
  padding: 0.1rem 0.3rem;
}

.execution-markdown-output :deep(pre) {
  background: hsl(var(--background) / 0.7);
  border: 1px solid hsl(var(--border) / 0.7);
  border-radius: 0.375rem;
  margin: 0.45rem 0;
  overflow-x: auto;
  padding: 0.625rem;
}

.execution-markdown-output :deep(pre code) {
  background: transparent;
  border-radius: 0;
  padding: 0;
}

.execution-markdown-output :deep(blockquote) {
  border-left: 2px solid hsl(var(--border));
  margin: 0.5rem 0;
  padding-left: 0.75rem;
}

.execution-markdown-output :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
}

.execution-markdown-output :deep(table) {
  border-collapse: collapse;
  display: block;
  margin: 0.5rem 0;
  max-width: 100%;
  overflow-x: auto;
}

.execution-markdown-output :deep(th),
.execution-markdown-output :deep(td) {
  border: 1px solid hsl(var(--border));
  padding: 0.25rem 0.4rem;
}

.ai-panel-header {
  padding: 12px 16px;
  border-bottom: 1px solid hsl(var(--border));
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: hsl(var(--muted) / 0.5);
  border-radius: 12px 12px 0 0;
}

.ai-panel-config {
  padding: 10px 12px;
  border-bottom: 1px solid hsl(var(--border));
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.config-row .config-label {
  width: 70px;
  flex-shrink: 0;
}

.config-row .config-select {
  flex: 1;
  min-width: 0;
}

.config-label {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
  white-space: nowrap;
}

.config-select {
  height: 32px;
  padding: 0 10px;
  border: 1px solid hsl(var(--border));
  border-radius: 6px;
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  font-size: 13px;
  cursor: pointer;
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  padding-right: 28px;
  min-width: 0;
  text-overflow: ellipsis;
  overflow: hidden;
  white-space: nowrap;
}

.config-select:focus {
  outline: none;
  border-color: hsl(var(--primary));
  box-shadow: 0 0 0 2px hsl(var(--primary) / 0.15);
}

.config-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  min-height: 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 16px;
}

.ai-message {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: 10px;
  max-width: 90%;
  font-size: 14px;
}

.ai-message.user {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  margin-left: auto;
}

.ai-message.assistant {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
  margin-right: auto;
}

.message-content {
  line-height: 1.6;
  font-size: 14px;
  word-break: break-word;
}

.message-content :deep(.code-block) {
  margin: 8px 0;
  border-radius: 8px;
  overflow: hidden;
  background: hsl(var(--background));
  border: 1px solid hsl(var(--border));
}

.message-content :deep(.code-header) {
  padding: 6px 12px;
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
  border-bottom: 1px solid hsl(var(--border));
}

.message-content :deep(pre) {
  margin: 0;
  padding: 12px;
  overflow-x: auto;
  max-height: 300px;
}

.message-content :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
}

.message-content :deep(.inline-code) {
  background: hsl(var(--muted));
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.message-content :deep(strong) {
  font-weight: 600;
}

.message-content :deep(em) {
  font-style: italic;
}

.message-content :deep(.md-h2) {
  font-size: 16px;
  font-weight: 600;
  margin: 12px 0 8px 0;
}

.message-content :deep(.md-h3) {
  font-size: 15px;
  font-weight: 600;
  margin: 10px 0 6px 0;
}

.message-content :deep(.md-h4) {
  font-size: 14px;
  font-weight: 600;
  margin: 8px 0 4px 0;
}

.message-content :deep(.md-li) {
  display: block;
  padding-left: 16px;
  position: relative;
}

.message-content :deep(.md-li)::before {
  content: "•";
  position: absolute;
  left: 4px;
}

.workflow-detected {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 10px;
  background: hsl(var(--primary) / 0.15);
  border-radius: 6px;
  font-size: 12px;
  color: hsl(var(--primary));
}

.loading-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  font-size: 14px;
  color: hsl(var(--muted-foreground));
}

.ai-input {
  padding: 12px;
  border-top: 1px solid hsl(var(--border));
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ai-textarea {
  width: 100%;
  resize: none;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  line-height: 1.4;
}

.ai-textarea:focus {
  outline: none;
  border-color: hsl(var(--primary));
}

.ai-textarea:disabled {
  opacity: 0.5;
}

.ai-input-actions {
  display: flex;
  gap: 8px;
}

.ai-btn-primary {
  flex: 1;
  height: 36px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
}

.ai-btn-primary:hover {
  opacity: 0.9;
}

.ai-btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ai-btn-primary.stop {
  background: hsl(var(--destructive));
  color: hsl(var(--destructive-foreground));
}

.ai-btn-secondary {
  height: 36px;
  padding: 0 12px;
  border-radius: 8px;
  border: 1px solid hsl(var(--border));
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: hsl(var(--background));
  color: hsl(var(--muted-foreground));
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
}

.ai-btn-secondary:hover {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.ai-slide-enter-active,
.ai-slide-leave-active {
  transition: all 0.25s ease;
}

.ai-slide-enter-from,
.ai-slide-leave-to {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}

.parse-error-action {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  background: hsl(var(--destructive) / 0.1);
  border: 1px solid hsl(var(--destructive) / 0.3);
  border-radius: 8px;
}

.parse-error-message {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: hsl(var(--destructive));
}

.retry-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 32px;
  padding: 0 14px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  font-size: 13px;
  font-weight: 500;
  transition: all 0.15s;
}

.retry-btn:hover {
  opacity: 0.9;
}

.retry-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.mode-toggle {
  display: flex;
  border: 1px solid hsl(var(--border));
  border-radius: 6px;
  overflow: hidden;
  background: hsl(var(--background));
}

.mode-toggle-btn {
  padding: 2px 10px;
  font-size: 11px;
  font-weight: 500;
  color: hsl(var(--muted-foreground));
  background: transparent;
  border: none;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
  line-height: 20px;
}

.mode-toggle-btn:hover {
  background: hsl(var(--muted) / 0.6);
  color: hsl(var(--foreground));
}

.mode-toggle-btn.active {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}
</style>
