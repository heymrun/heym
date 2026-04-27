<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  watch,
  type Component,
} from "vue";
import { AxiosError } from "axios";
import {
  AlertCircle,
  Braces,
  Check,
  ChevronLeft,
  ChevronRight,
  Code2,
  Copy,
  Hash,
  List,
  Loader2,
  Maximize2,
  Play,
  Type,
  Variable,
  X,
} from "lucide-vue-next";

import type { CompletionSuggestion, PropertyType } from "@/types/expression";
import type {
  ExpressionEvaluateResponse,
  NodeResult,
  WorkflowEdge,
  WorkflowNode,
} from "@/types/workflow";
import ExpressionOutputPathPicker from "@/components/ui/ExpressionOutputPathPicker.vue";
import { useExpressionCompletion } from "@/composables/useExpressionCompletion";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import {
  incomingEvaluateGraphNeighborNodes,
  outgoingEvaluateGraphNeighborNodes,
} from "@/lib/expressionEvaluateGraphNeighbors";
import { isRetryAttemptNodeResult } from "@/lib/executionLog";
import {
  findEnclosingLoopIdForListSize,
  findNodeResultIndexForLoopIteration,
  loopIterationIndexFromOutput,
  loopListSizeForEvaluateTitle,
  mapNodeResultsToEnclosingLoopIterations,
  selectedLoopIterationIndexForNode,
} from "@/lib/loopNodeDisplay";
import { extendDollarExpression, isSingleDollarReferenceExpression } from "@/lib/expressionPathPicker";
import { parseWebhookJson } from "@/lib/webhookBody";
import { cn } from "@/lib/utils";
import { nodeIconColorClass, nodeIcons } from "@/lib/nodeIcons";
import { expressionApi, workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";

interface Props {
  modelValue?: string;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
  singleLine?: boolean;
  nodes?: WorkflowNode[];
  nodeResults?: NodeResult[];
  edges?: WorkflowEdge[];
  currentNodeId?: string | null;
  expandable?: boolean;
  dialogTitle?: string;
  navigationEnabled?: boolean;
  navigationIndex?: number;
  navigationTotal?: number;
  dialogKeyLabel?: string;
  /** Shown in the expand dialog title between dialogTitle and dialogKeyLabel (e.g. node display name). */
  dialogNodeLabel?: string;
}

interface ExpressionMatch {
  start: number;
  end: number;
  expr: string;
}

interface InspectedTarget extends ExpressionMatch {
  kind: "selection" | "line" | "expression";
}

interface EvaluatedNodeResultInput {
  node_id: string;
  label: string;
  output: unknown;
}

interface DialogHistoryEntry {
  value: string;
  selectionStart: number;
  selectionEnd: number;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "",
  placeholder: "",
  disabled: false,
  rows: 3,
  singleLine: false,
  nodes: () => [],
  nodeResults: () => [],
  edges: () => [],
  currentNodeId: null,
  expandable: true,
  dialogTitle: "Evaluate",
  navigationEnabled: false,
  navigationIndex: 0,
  navigationTotal: 0,
  dialogKeyLabel: "",
  dialogNodeLabel: "",
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "navigate", direction: "prev" | "next"): void;
  (e: "navigateNode", payload: { targetNodeId: string }): void;
  (e: "registerFieldIndex", index: number): void;
}>();

const workflowStore = useWorkflowStore();

const textareaRef = ref<HTMLTextAreaElement | null>(null);
const inputRef = ref<HTMLInputElement | null>(null);
const dropdownRef = ref<HTMLDivElement | null>(null);
const dialogTextareaRef = ref<HTMLTextAreaElement | null>(null);
const dialogDropdownRef = ref<HTMLDivElement | null>(null);
const outputScrollRef = ref<HTMLDivElement | null>(null);
const evaluateDialogBodyRef = ref<HTMLDivElement | null>(null);
const showDropdown = ref(false);
const showDialogDropdown = ref(false);
const showExpandDialog = ref(false);
const dialogValue = ref("");
const suggestions = ref<CompletionSuggestion[]>([]);
const dialogSuggestions = ref<CompletionSuggestion[]>([]);
const selectedIndex = ref(0);
const dialogSelectedIndex = ref(0);
const dropdownPosition = ref({ top: 0, left: 0 });
const dialogDropdownPosition = ref({ top: 0, left: 0 });
const runResult = ref<ExpressionEvaluateResponse | null>(null);
const inspectedRunResult = ref<ExpressionEvaluateResponse | null>(null);
const runRequestError = ref<string | null>(null);
const runLoading = ref(false);
const lastRunDurationMs = ref<number | null>(null);
const outputPathPickerKey = ref(0);
const dialogSelectionStart = ref(0);
const dialogSelectionEnd = ref(0);
const dialogHistory = ref<DialogHistoryEntry[]>([]);
const dialogHistoryIndex = ref(-1);
const applyingDialogHistory = ref(false);
const lastRunRequestNodeResults = ref<EvaluatedNodeResultInput[] | null>(null);
const lastRunDialogSnapshot = ref<string | null>(null);
const lastInspectedSignature = ref<string | null>(null);
const lastSuccessfulEvaluateRequestSignature = ref<string | null>(null);
const lastRunNodeId = ref<string | null>(null);
const finalResultCopied = ref(false);
const forceOutputScrollTopOnNextUpdate = ref(false);
const AUTO_EVALUATE_THROTTLE_MS = 250;
/** True while openExpandDialog is applying dialogValue/showExpandDialog so batched watchers do not also schedule auto-eval. */
const openingExpandDialog = ref(false);
const hintWorkflowRunLoading = ref(false);
const suppressNextLoopSelectionAutoEvaluate = ref(false);
const lastAutoEvaluateStartedAtMs = ref<number | null>(null);
/** Cleared when opening the inline dropdown so a stale blur timeout cannot hide it (e.g. after Run hint). */
let inlineBlurHideTimer: ReturnType<typeof setTimeout> | null = null;
let pendingOutputBottomStickTimer: ReturnType<typeof setTimeout> | null = null;
let autoEvaluateTimer: ReturnType<typeof setTimeout> | null = null;
let pendingAutoEvaluateShouldResetOutputPathPicker = false;
let queuedEvaluateAfterCurrentRun = false;
let queuedEvaluateShouldResetOutputPathPicker = false;

const inputElement = computed((): HTMLInputElement | HTMLTextAreaElement | null =>
  props.singleLine ? inputRef.value : textareaRef.value,
);

const textareaClasses = computed((): string =>
  cn(
    "flex min-h-[80px] w-full rounded-md border-2 border-input bg-background px-3 py-2 text-sm font-mono placeholder:text-muted-foreground transition-colors focus-visible:border-primary focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 resize-none",
  ),
);

const inputClasses = computed((): string =>
  cn(
    "flex h-10 w-full rounded-md border-2 border-input bg-background px-3 py-2 text-sm font-mono placeholder:text-muted-foreground transition-colors focus-visible:border-primary focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
  ),
);

const upstreamNodeIds = computed((): Set<string> => {
  if (!props.currentNodeId) {
    return new Set<string>();
  }

  const upstream = new Set<string>();
  const visited = new Set<string>();
  const queue: string[] = [props.currentNodeId];

  while (queue.length > 0) {
    const nodeId = queue.shift();
    if (!nodeId || visited.has(nodeId)) {
      continue;
    }
    visited.add(nodeId);

    for (const edge of props.edges) {
      if (edge.target === nodeId && !visited.has(edge.source)) {
        upstream.add(edge.source);
        queue.push(edge.source);
      }
    }
  }

  return upstream;
});

const incomingNeighborNodes = computed((): WorkflowNode[] => {
  if (!props.currentNodeId || !props.edges?.length || !props.nodes?.length) {
    return [];
  }
  return incomingEvaluateGraphNeighborNodes(props.currentNodeId, props.edges, props.nodes);
});

const outgoingNeighborNodes = computed((): WorkflowNode[] => {
  if (!props.currentNodeId || !props.edges?.length || !props.nodes?.length) {
    return [];
  }
  return outgoingEvaluateGraphNeighborNodes(props.currentNodeId, props.edges, props.nodes);
});

/** True when this field participates in workflow graph edge navigation in the evaluate dialog. */
const evaluateGraphNavigationEnabled = computed((): boolean => {
  return (
    props.navigationEnabled ||
    (Boolean(props.currentNodeId) &&
      (props.nodes?.length ?? 0) > 0 &&
      (props.edges?.length ?? 0) > 0)
  );
});

const showEvaluateGraphToolbar = computed((): boolean => {
  return (
    evaluateGraphNavigationEnabled.value &&
    (incomingNeighborNodes.value.length > 0 || outgoingNeighborNodes.value.length > 0)
  );
});

const availableNodeResults = computed((): NodeResult[] => {
  return workflowStore.nodeResults.length > 0 ? workflowStore.nodeResults : props.nodeResults;
});

interface EvaluateLoopItemNavigationState {
  loopNodeId: string;
  currentIterationIndex: number;
  currentDisplayIndex: number;
  totalDisplayCount: number;
  canNavigatePrev: boolean;
  canNavigateNext: boolean;
}

const loopTitlePreviewListSize = ref<number | null>(null);

const evaluateLoopNodeId = computed((): string | null => {
  return findEnclosingLoopIdForListSize(
    props.currentNodeId,
    props.nodes,
    props.edges,
  );
});

const storedSelectedLoopIterationIndex = computed((): number | null => {
  const loopNodeId = evaluateLoopNodeId.value;
  const selection = workflowStore.evaluateLoopSelection;
  if (!loopNodeId || !selection || selection.loopNodeId !== loopNodeId) {
    return null;
  }
  return selection.iterationIndex;
});

const hasInputPreviewContext = computed((): boolean => {
  if (upstreamNodeIds.value.size === 0) {
    return false;
  }
  const hasUpstreamTextInput = props.nodes.some(
    (node) => upstreamNodeIds.value.has(node.id) && node.type === "textInput",
  );
  if (!hasUpstreamTextInput) {
    return false;
  }
  if (workflowStore.webhookBodyMode === "generic") {
    return parseWebhookJson(workflowStore.runInputJson).error === null;
  }
  return true;
});

function clampLoopIterationIndex(iterationIndex: number, totalDisplayCount: number): number {
  const normalized = Math.max(0, Math.floor(iterationIndex));
  if (totalDisplayCount <= 0) {
    return normalized;
  }
  return Math.min(normalized, totalDisplayCount - 1);
}

function inferEvaluateLoopTotalDisplayCount(): number | null {
  if (loopTitlePreviewListSize.value !== null) {
    return loopTitlePreviewListSize.value;
  }

  const localListSize = loopListSizeForEvaluateTitle(
    props.currentNodeId,
    props.nodes,
    props.edges,
    availableNodeResults.value,
  );
  if (localListSize !== null) {
    return localListSize;
  }

  const currentNodeId = props.currentNodeId;
  if (!currentNodeId) {
    return null;
  }

  const currentNode = props.nodes.find((node) => node.id === currentNodeId);
  if (!currentNode) {
    return null;
  }

  const iterationIndexes: number[] = [];
  if (currentNode.type === "loop") {
    availableNodeResults.value.forEach((row) => {
      if (row.node_id !== currentNodeId || isRetryAttemptNodeResult(row)) {
        return;
      }
      const iterationIndex = loopIterationIndexFromOutput(row.output);
      if (iterationIndex !== null) {
        iterationIndexes.push(iterationIndex);
      }
    });
  } else {
    const mapped = mapNodeResultsToEnclosingLoopIterations(
      currentNodeId,
      props.nodes,
      props.edges,
      availableNodeResults.value,
    );
    mapped?.iterationIndexes.forEach((iterationIndex, index) => {
      const resultIndex = mapped.resultIndexes[index];
      const row = typeof resultIndex === "number" ? availableNodeResults.value[resultIndex] : null;
      if (
        !row ||
        isRetryAttemptNodeResult(row) ||
        iterationIndex === null ||
        iterationIndex < 0
      ) {
        return;
      }
      iterationIndexes.push(iterationIndex);
    });
  }

  if (iterationIndexes.length === 0) {
    return null;
  }

  return Math.max(...iterationIndexes) + 1;
}

const evaluateLoopTotalDisplayCount = computed((): number | null => {
  return inferEvaluateLoopTotalDisplayCount();
});

const timelineSelectedLoopIterationIndex = computed((): number | null => {
  return selectedLoopIterationIndexForNode(
    props.currentNodeId,
    workflowStore.timelinePickedNodeResultIndex,
    props.nodes,
    props.edges,
    availableNodeResults.value,
  );
});

const evaluateLoopItemNavigation = computed((): EvaluateLoopItemNavigationState | null => {
  const loopNodeId = evaluateLoopNodeId.value;
  const totalDisplayCount = evaluateLoopTotalDisplayCount.value;
  if (!loopNodeId || totalDisplayCount === null || totalDisplayCount <= 1) {
    return null;
  }

  const baseIterationIndex =
    timelineSelectedLoopIterationIndex.value ?? storedSelectedLoopIterationIndex.value ?? 0;
  const currentIterationIndex = clampLoopIterationIndex(baseIterationIndex, totalDisplayCount);

  return {
    loopNodeId,
    currentIterationIndex,
    currentDisplayIndex: currentIterationIndex + 1,
    totalDisplayCount,
    canNavigatePrev: currentIterationIndex > 0,
    canNavigateNext: currentIterationIndex < totalDisplayCount - 1,
  };
});

const selectedLoopIterationIndex = computed((): number | null => {
  if (!evaluateLoopNodeId.value) {
    return null;
  }
  if (timelineSelectedLoopIterationIndex.value !== null) {
    return timelineSelectedLoopIterationIndex.value;
  }
  if (storedSelectedLoopIterationIndex.value === null) {
    return null;
  }
  const totalDisplayCount = evaluateLoopTotalDisplayCount.value;
  if (totalDisplayCount === null || totalDisplayCount <= 0) {
    return storedSelectedLoopIterationIndex.value;
  }
  return clampLoopIterationIndex(storedSelectedLoopIterationIndex.value, totalDisplayCount);
});

const effectiveDialogNodeLabel = computed((): string => {
  const fromProp = props.dialogNodeLabel?.trim();
  if (fromProp) {
    return fromProp;
  }
  const sel = workflowStore.selectedNode;
  if (sel && props.currentNodeId === sel.id) {
    const raw = sel.data.label;
    const trimmed = typeof raw === "string" ? raw.trim() : "";
    return trimmed.length > 0 ? trimmed : sel.type;
  }
  return "";
});

function truncateDialogFieldHint(text: string, maxLen: number): string {
  const t = text.trim();
  if (t.length <= maxLen) {
    return t;
  }
  const sliceLen = Math.max(0, maxLen - 3);
  return `${t.slice(0, sliceLen)}...`;
}

const expandDialogHeading = computed((): string => {
  const nodePart = effectiveDialogNodeLabel.value;
  const keyFromProp = props.dialogKeyLabel?.trim();
  const rawPh = props.placeholder?.trim();
  const keyFromPlaceholder =
    !keyFromProp && rawPh ? truncateDialogFieldHint(rawPh, 48) : "";
  const keyPart = keyFromProp || keyFromPlaceholder;
  const title = props.dialogTitle.trim().length > 0 ? props.dialogTitle.trim() : "Evaluate";
  let base: string;
  if (nodePart && keyPart) {
    base = `${nodePart} – ${keyPart}`;
  } else if (nodePart) {
    base = `${nodePart} – ${title}`;
  } else if (keyPart) {
    base = `${keyPart} – ${title}`;
  } else {
    base = title;
  }
  const listSize = loopTitlePreviewListSize.value ?? loopListSizeForEvaluateTitle(
    props.currentNodeId,
    props.nodes,
    props.edges,
    availableNodeResults.value,
  );
  if (listSize !== null) {
    const suffix = listSize === 1 ? "1 item" : `${listSize} items`;
    return `${base} (${suffix})`;
  }
  return base;
});

const hasContext = computed((): boolean => {
  if (upstreamNodeIds.value.size === 0) {
    return true;
  }

  const hasPinned = props.nodes.some(
    (node) =>
      upstreamNodeIds.value.has(node.id) &&
      node.data.pinnedData !== undefined &&
      node.data.pinnedData !== null,
  );
  const hasResults = availableNodeResults.value.some((result) =>
    upstreamNodeIds.value.has(result.node_id),
  );
  return hasPinned || hasResults || hasInputPreviewContext.value;
});

const canRun = computed((): boolean => Boolean(props.currentNodeId) && Boolean(workflowStore.currentWorkflow?.id));

const runIdleHint = computed((): string => {
  if (!canRun.value) {
    return "Load a workflow to preview the result.";
  }
  if (hasContext.value) {
    return "Output updates immediately, then throttles while you type.";
  }
  return "Output updates immediately, then throttles while you type. If upstream data is missing, the workflow runs once first.";
});

const runDurationLabel = computed((): string | null => {
  if (runLoading.value) {
    return "Updating preview...";
  }
  if (lastRunDurationMs.value === null) {
    return null;
  }
  return `Updated in ${lastRunDurationMs.value} ms`;
});

const canCopyFinalResult = computed((): boolean =>
  Boolean(runResult.value && !runResult.value.error),
);

const dialogExpressions = computed((): ExpressionMatch[] => findDollarExpressions(dialogValue.value));

const activeDialogDollarExpression = computed((): ExpressionMatch | null => {
  const start = dialogSelectionStart.value;
  const end = dialogSelectionEnd.value;
  if (dialogExpressions.value.length === 0) {
    return null;
  }

  if (start === end) {
    return (
      dialogExpressions.value.find((match) => start >= match.start && start <= match.end) ?? null
    );
  }

  return (
    dialogExpressions.value.find((match) => start < match.end && end > match.start) ?? null
  );
});

function findSelectedTextExpression(
  text: string,
  selectionStart: number,
  selectionEnd: number,
): ExpressionMatch | null {
  if (selectionStart === selectionEnd) {
    return null;
  }

  const raw = text.slice(selectionStart, selectionEnd);
  const leadingWhitespace = raw.match(/^\s*/)?.[0].length ?? 0;
  const trailingWhitespace = raw.match(/\s*$/)?.[0].length ?? 0;
  const start = selectionStart + leadingWhitespace;
  const end = selectionEnd - trailingWhitespace;

  if (start >= end) {
    return null;
  }

  return {
    start,
    end,
    expr: text.slice(start, end),
  };
}

function findSelectedLineExpression(
  text: string,
  selectionStart: number,
  selectionEnd: number,
): ExpressionMatch | null {
  const anchor = Math.max(0, Math.min(selectionStart, text.length));
  const lineStart = text.lastIndexOf("\n", Math.max(0, anchor - 1)) + 1;
  let lineEnd = text.indexOf("\n", Math.max(selectionEnd, anchor));
  if (lineEnd === -1) {
    lineEnd = text.length;
  }

  const line = text.slice(lineStart, lineEnd);
  const trimmedStartOffset = line.search(/\S/);
  if (trimmedStartOffset === -1) {
    return null;
  }

  const trimmedLine = line.trim();
  if (!trimmedLine.startsWith("$")) {
    return null;
  }

  const trailingWhitespaceLength = line.match(/\s*$/)?.[0].length ?? 0;
  return {
    start: lineStart + trimmedStartOffset,
    end: lineEnd - trailingWhitespaceLength,
    expr: trimmedLine,
  };
}

const inspectedTarget = computed((): InspectedTarget | null => {
  const selectedTextExpression = findSelectedTextExpression(
    dialogValue.value,
    dialogSelectionStart.value,
    dialogSelectionEnd.value,
  );
  if (selectedTextExpression) {
    return {
      ...selectedTextExpression,
      kind: "selection",
    };
  }

  const lineExpression = findSelectedLineExpression(
    dialogValue.value,
    dialogSelectionStart.value,
    dialogSelectionEnd.value,
  );
  if (lineExpression) {
    if (dialogExpressions.value.length === 1 && lineExpression.expr === dialogValue.value.trim()) {
      return null;
    }
    return {
      ...lineExpression,
      kind: "line",
    };
  }

  const match = activeDialogDollarExpression.value;
  if (!match) {
    return null;
  }

  const trimmed = match.expr.trim();
  if (dialogExpressions.value.length === 1 && trimmed === dialogValue.value.trim()) {
    return null;
  }

  return {
    ...match,
    expr: trimmed,
    kind: "expression",
  };
});

const inspectedExpression = computed((): string | null => {
  return inspectedTarget.value?.expr ?? null;
});

const canExtendInspectedExpressionPath = computed((): boolean => {
  if (!inspectedExpression.value) {
    return false;
  }
  return isSingleDollarReferenceExpression(inspectedExpression.value);
});

const inspectedResultLabel = computed((): string => {
  if (canExtendInspectedExpressionPath.value) {
    return "Selected Field";
  }
  if (inspectedTarget.value?.kind === "selection") {
    return "Selected Text";
  }
  return "Selected Expression";
});

/** Value to feed ExpressionOutputPathPicker (objects/arrays, or JSON-in-string payloads). */
function tryJsonTreeValue(value: unknown, resultType: string): unknown | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (resultType === "object" || resultType === "array") {
    return typeof value === "object" ? value : null;
  }
  if (resultType === "string" && typeof value === "string") {
    const s = value.trim();
    if (
      (s.startsWith("{") && s.endsWith("}")) ||
      (s.startsWith("[") && s.endsWith("]"))
    ) {
      try {
        const parsed = JSON.parse(s) as unknown;
        if (parsed !== null && typeof parsed === "object") {
          return parsed;
        }
      } catch {
        return null;
      }
    }
  }
  return null;
}

const finalResultTreeValue = computed((): unknown | null => {
  const r = runResult.value;
  if (!r || r.error) {
    return null;
  }
  return tryJsonTreeValue(r.result, r.result_type);
});

const showOutputPathPicker = computed((): boolean => finalResultTreeValue.value !== null);

const showInspectedOutputPathPicker = computed((): boolean => {
  if (!inspectedRunResult.value || inspectedRunResult.value.error) {
    return false;
  }
  if (!canExtendInspectedExpressionPath.value) {
    return false;
  }
  return (
    inspectedRunResult.value.result_type === "array" || inspectedRunResult.value.result_type === "object"
  );
});

const showSelectedInspectPanel = computed((): boolean =>
  Boolean(inspectedExpression.value && inspectedRunResult.value),
);

const selectedInspectContentKey = computed((): string => {
  if (!showSelectedInspectPanel.value || !inspectedExpression.value || !inspectedRunResult.value) {
    return "empty";
  }

  return [
    inspectedExpression.value,
    inspectedRunResult.value.result_type,
    inspectedRunResult.value.error ?? "",
    showInspectedOutputPathPicker.value ? "picker" : "text",
  ].join("|");
});

const showNavigation = computed((): boolean => props.navigationEnabled && props.navigationTotal > 1);
const canNavigatePrev = computed((): boolean => props.navigationIndex > 0);
const canNavigateNext = computed((): boolean => props.navigationIndex < props.navigationTotal - 1);

const { getSuggestions, applyCompletion } = useExpressionCompletion({
  get nodes() {
    return props.nodes;
  },
  get nodeResults() {
    return availableNodeResults.value;
  },
  get edges() {
    return props.edges;
  },
  get currentNodeId() {
    return props.currentNodeId ?? null;
  },
});

watch(
  () => [
    props.nodes,
    props.nodeResults,
    workflowStore.nodeResults,
    props.edges,
    props.currentNodeId,
  ],
  () => {
    if (showDropdown.value && inputElement.value) {
      updateSuggestions();
    }
    if (showDialogDropdown.value && dialogTextareaRef.value) {
      updateDialogSuggestions();
    }
  },
  { deep: true },
);

watch(
  () => props.modelValue,
  (next): void => {
    if (!showExpandDialog.value) {
      return;
    }
    const incoming = next ?? "";
    if (incoming === dialogValue.value) {
      return;
    }
    dialogValue.value = incoming;
    resetDialogHistory(dialogValue.value);
  },
);

watch(dialogValue, (): void => {
  inspectedRunResult.value = null;
  runRequestError.value = null;
  lastRunRequestNodeResults.value = null;
  lastRunDialogSnapshot.value = null;
  lastInspectedSignature.value = null;
  finalResultCopied.value = false;
  clearFinalResultCopyResetTimer();

  if (!showExpandDialog.value) {
    runResult.value = null;
    lastRunDurationMs.value = null;
    clearAutoEvaluateTimer();
    return;
  }

  if (!dialogValue.value.trim()) {
    runResult.value = null;
    lastRunDurationMs.value = null;
    clearAutoEvaluateTimer();
    return;
  }

  if (openingExpandDialog.value) {
    clearAutoEvaluateTimer();
    return;
  }

  scheduleExpressionEvaluation({ resetOutputPathPicker: true });
});

watch(showExpandDialog, (isOpen): void => {
  if (!isOpen) {
    clearAutoEvaluateTimer();
    pendingAutoEvaluateShouldResetOutputPathPicker = false;
    queuedEvaluateAfterCurrentRun = false;
    queuedEvaluateShouldResetOutputPathPicker = false;
    loopTitlePreviewListSize.value = null;
    lastAutoEvaluateStartedAtMs.value = null;
    lastSuccessfulEvaluateRequestSignature.value = null;
    return;
  }

  void refreshLoopTitlePreviewListSize();
  if (dialogValue.value.trim()) {
    scheduleExpressionEvaluation({ resetOutputPathPicker: true });
  }
});

watch(
  () => [
    props.currentNodeId,
    props.nodes,
    props.edges,
    props.nodeResults,
    workflowStore.nodeResults,
    workflowStore.runInputJson,
    workflowStore.runInputValues,
  ],
  (): void => {
    if (!showExpandDialog.value) {
      return;
    }
    void refreshLoopTitlePreviewListSize();
  },
  { deep: true },
);

watch(
  () => workflowStore.timelinePickedNodeResultIndex,
  (): void => {
    if (!showExpandDialog.value) {
      return;
    }
    void refreshLoopTitlePreviewListSize();
    if (!dialogValue.value.trim()) {
      return;
    }
    scheduleExpressionEvaluation({ resetOutputPathPicker: true });
  },
);

watch(
  (): [boolean, string | null, number | null, number | null, number | null] => [
    showExpandDialog.value,
    evaluateLoopNodeId.value,
    evaluateLoopTotalDisplayCount.value,
    timelineSelectedLoopIterationIndex.value,
    storedSelectedLoopIterationIndex.value,
  ],
  ([isOpen, loopNodeId, totalDisplayCount, timelineIterationIndex, storedIterationIndex]): void => {
    if (!isOpen || !loopNodeId) {
      return;
    }

    const nextIterationIndex =
      timelineIterationIndex !== null
        ? timelineIterationIndex
        : totalDisplayCount !== null && totalDisplayCount > 0
          ? (storedIterationIndex ?? 0)
          : null;
    if (nextIterationIndex === null) {
      return;
    }

    const normalizedIterationIndex =
      totalDisplayCount !== null && totalDisplayCount > 0
        ? clampLoopIterationIndex(nextIterationIndex, totalDisplayCount)
        : Math.max(0, Math.floor(nextIterationIndex));
    const currentSelection = workflowStore.evaluateLoopSelection;
    if (
      currentSelection?.loopNodeId === loopNodeId &&
      currentSelection.iterationIndex === normalizedIterationIndex
    ) {
      return;
    }

    suppressNextLoopSelectionAutoEvaluate.value = true;
    workflowStore.setEvaluateLoopSelection({
      loopNodeId,
      iterationIndex: normalizedIterationIndex,
    });
  },
);

watch(
  () => [
    workflowStore.evaluateLoopSelection?.loopNodeId ?? null,
    workflowStore.evaluateLoopSelection?.iterationIndex ?? null,
  ],
  (): void => {
    if (!showExpandDialog.value || openingExpandDialog.value) {
      return;
    }
    if (suppressNextLoopSelectionAutoEvaluate.value) {
      suppressNextLoopSelectionAutoEvaluate.value = false;
      return;
    }
    void refreshLoopTitlePreviewListSize();
    if (!dialogValue.value.trim()) {
      return;
    }
    scheduleExpressionEvaluation({ resetOutputPathPicker: true });
  },
);

watch(
  [inspectedExpression, dialogValue, showExpandDialog],
  ([nextExpression, nextDialogValue, isDialogOpen]): void => {
    if (!isDialogOpen) {
      return;
    }

    if (!nextExpression) {
      inspectedRunResult.value = null;
      lastInspectedSignature.value = null;
      return;
    }

    if (
      !lastRunRequestNodeResults.value ||
      !lastRunDialogSnapshot.value ||
      lastRunDialogSnapshot.value !== nextDialogValue
    ) {
      inspectedRunResult.value = null;
      lastInspectedSignature.value = null;
      return;
    }

    const signature = `${nextDialogValue}\n---\n${nextExpression}`;
    if (signature === lastInspectedSignature.value && inspectedRunResult.value) {
      return;
    }

    void refreshInspectedSelection(nextExpression, lastRunRequestNodeResults.value, signature);
  },
);

function resetDialogHistory(value: string): void {
  const cursor = value.length;
  dialogHistory.value = [{ value, selectionStart: cursor, selectionEnd: cursor }];
  dialogHistoryIndex.value = 0;
}

function pushDialogHistoryEntry(
  value: string,
  selectionStart: number,
  selectionEnd: number,
): void {
  if (applyingDialogHistory.value) {
    return;
  }

  const lastEntry = dialogHistory.value[dialogHistoryIndex.value];
  if (
    lastEntry &&
    lastEntry.value === value &&
    lastEntry.selectionStart === selectionStart &&
    lastEntry.selectionEnd === selectionEnd
  ) {
    return;
  }

  const nextHistory = dialogHistory.value.slice(0, dialogHistoryIndex.value + 1);
  nextHistory.push({ value, selectionStart, selectionEnd });
  dialogHistory.value = nextHistory.slice(-250);
  dialogHistoryIndex.value = dialogHistory.value.length - 1;
}

function restoreDialogHistoryEntry(index: number): void {
  const entry = dialogHistory.value[index];
  if (!entry) {
    return;
  }

  dialogHistoryIndex.value = index;
  applyingDialogHistory.value = true;
  dialogValue.value = entry.value;

  nextTick((): void => {
    const element = dialogTextareaRef.value;
    if (element) {
      const nextStart = Math.min(entry.selectionStart, entry.value.length);
      const nextEnd = Math.min(entry.selectionEnd, entry.value.length);
      element.focus();
      element.setSelectionRange(nextStart, nextEnd);
      updateDialogSelection(element);
    }
    updateDialogSuggestions();
    applyingDialogHistory.value = false;
  });
}

function undoDialogHistory(): void {
  if (dialogHistoryIndex.value <= 0) {
    return;
  }
  restoreDialogHistoryEntry(dialogHistoryIndex.value - 1);
}

function redoDialogHistory(): void {
  if (dialogHistoryIndex.value >= dialogHistory.value.length - 1) {
    return;
  }
  restoreDialogHistoryEntry(dialogHistoryIndex.value + 1);
}

function isOutputScrollNearBottom(threshold = 20): boolean {
  const element = outputScrollRef.value;
  if (!element) {
    return false;
  }
  return element.scrollHeight - element.scrollTop - element.clientHeight <= threshold;
}

function scrollOutputToBottom(): void {
  const element = outputScrollRef.value;
  if (!element) {
    return;
  }
  element.scrollTop = element.scrollHeight;
}

function scrollOutputToTop(): void {
  const element = outputScrollRef.value;
  if (!element) {
    return;
  }
  element.scrollTop = 0;
}

function clearPendingOutputBottomStickTimer(): void {
  if (pendingOutputBottomStickTimer !== null) {
    clearTimeout(pendingOutputBottomStickTimer);
    pendingOutputBottomStickTimer = null;
  }
}

function clearAutoEvaluateTimer(): void {
  if (autoEvaluateTimer !== null) {
    clearTimeout(autoEvaluateTimer);
    autoEvaluateTimer = null;
  }
}

function queueExpressionEvaluation(options?: { resetOutputPathPicker?: boolean }): void {
  if (!showExpandDialog.value || !dialogValue.value.trim() || !canRun.value) {
    return;
  }

  if (runLoading.value) {
    queuedEvaluateAfterCurrentRun = true;
    queuedEvaluateShouldResetOutputPathPicker =
      queuedEvaluateShouldResetOutputPathPicker || Boolean(options?.resetOutputPathPicker);
    return;
  }

  void runExpression(options);
}

function scheduleExpressionEvaluation(options?: { resetOutputPathPicker?: boolean }): void {
  if (!showExpandDialog.value || !dialogValue.value.trim() || !canRun.value) {
    clearAutoEvaluateTimer();
    pendingAutoEvaluateShouldResetOutputPathPicker = false;
    return;
  }

  const now = performance.now();
  const lastStartedAtMs = lastAutoEvaluateStartedAtMs.value;
  const msSinceLastStart =
    lastStartedAtMs === null ? Number.POSITIVE_INFINITY : now - lastStartedAtMs;

  if (!runLoading.value && msSinceLastStart >= AUTO_EVALUATE_THROTTLE_MS) {
    clearAutoEvaluateTimer();
    pendingAutoEvaluateShouldResetOutputPathPicker = false;
    lastAutoEvaluateStartedAtMs.value = now;
    queueExpressionEvaluation(options);
    return;
  }

  pendingAutoEvaluateShouldResetOutputPathPicker =
    pendingAutoEvaluateShouldResetOutputPathPicker || Boolean(options?.resetOutputPathPicker);
  const delayMs = Math.max(0, AUTO_EVALUATE_THROTTLE_MS - msSinceLastStart);
  clearAutoEvaluateTimer();
  autoEvaluateTimer = setTimeout((): void => {
    autoEvaluateTimer = null;
    const shouldResetOutputPathPicker = pendingAutoEvaluateShouldResetOutputPathPicker;
    pendingAutoEvaluateShouldResetOutputPathPicker = false;
    lastAutoEvaluateStartedAtMs.value = performance.now();
    queueExpressionEvaluation({ resetOutputPathPicker: shouldResetOutputPathPicker });
  }, delayMs);
}

function scheduleOutputBottomStick(): void {
  clearPendingOutputBottomStickTimer();
  pendingOutputBottomStickTimer = setTimeout((): void => {
    scrollOutputToBottom();
    pendingOutputBottomStickTimer = null;
  }, 260);
}

watch(
  [() => runResult.value, showSelectedInspectPanel, selectedInspectContentKey],
  async (): Promise<void> => {
    const shouldScrollTop = forceOutputScrollTopOnNextUpdate.value;
    const shouldStickToBottom = !shouldScrollTop && isOutputScrollNearBottom();
    await nextTick();
    if (shouldScrollTop) {
      clearPendingOutputBottomStickTimer();
      scrollOutputToTop();
      forceOutputScrollTopOnNextUpdate.value = false;
      return;
    }
    if (shouldStickToBottom) {
      scrollOutputToBottom();
      scheduleOutputBottomStick();
    }
  },
  { flush: "pre" },
);

watch(
  inspectedExpression,
  (): void => {
    if (!showExpandDialog.value || !runResult.value) {
      return;
    }
    forceOutputScrollTopOnNextUpdate.value = true;
  },
  { flush: "sync" },
);

function getTypeIcon(suggestion: CompletionSuggestion): Component {
  if (suggestion.type === "hint") return AlertCircle;
  if (suggestion.type === "node") return Variable;
  if (suggestion.type === "function") return Code2;
  if (suggestion.type === "keyword") return Variable;

  const propertyType = suggestion.propertyType as PropertyType;
  switch (propertyType) {
    case "string":
      return Type;
    case "number":
      return Hash;
    case "array":
      return List;
    case "object":
      return Braces;
    default:
      return Variable;
  }
}

function getTypeColor(suggestion: CompletionSuggestion): string {
  if (suggestion.type === "hint") return "text-amber-500";
  if (suggestion.type === "node") return "text-blue-400";
  if (suggestion.type === "function") return "text-purple-400";
  if (suggestion.type === "keyword") return "text-emerald-400";

  const propertyType = suggestion.propertyType as PropertyType;
  switch (propertyType) {
    case "string":
      return "text-green-400";
    case "number":
      return "text-yellow-400";
    case "array":
      return "text-orange-400";
    case "object":
      return "text-cyan-400";
    case "boolean":
      return "text-pink-400";
    default:
      return "text-muted-foreground";
  }
}

function clearInlineBlurHideTimer(): void {
  if (inlineBlurHideTimer !== null) {
    clearTimeout(inlineBlurHideTimer);
    inlineBlurHideTimer = null;
  }
}

function updateSuggestions(): void {
  const element = inputElement.value;
  if (!element) {
    return;
  }

  const cursorPos = element.selectionStart || 0;
  const text = props.modelValue || "";
  suggestions.value = getSuggestions(text, cursorPos);
  selectedIndex.value = 0;
  showDropdown.value = suggestions.value.length > 0;
  if (showDropdown.value) {
    clearInlineBlurHideTimer();
    updateDropdownPosition();
  }
}

function updateDialogSuggestions(): void {
  const element = dialogTextareaRef.value;
  if (!element) {
    return;
  }

  const cursorPos = element.selectionStart || 0;
  dialogSuggestions.value = getSuggestions(dialogValue.value, cursorPos);
  dialogSelectedIndex.value = 0;
  showDialogDropdown.value = dialogSuggestions.value.length > 0;
  if (showDialogDropdown.value) {
    updateDialogDropdownPosition();
  }
}

function updateDropdownPosition(): void {
  const element = inputElement.value;
  if (!element) {
    return;
  }

  const rect = element.getBoundingClientRect();
  dropdownPosition.value = { top: rect.height + 4, left: 0 };
}

function updateDialogDropdownPosition(): void {
  const element = dialogTextareaRef.value;
  if (!element) {
    return;
  }

  const rect = element.getBoundingClientRect();
  const bodyEl = evaluateDialogBodyRef.value;
  const containerRect = bodyEl?.getBoundingClientRect() ?? element.parentElement?.getBoundingClientRect();
  dialogDropdownPosition.value = {
    top: containerRect ? rect.bottom - containerRect.top + 4 : rect.height + 4,
    left: 0,
  };
}

function handleInput(event: Event): void {
  const target = event.target as HTMLTextAreaElement;
  emit("update:modelValue", target.value);
  nextTick((): void => {
    updateSuggestions();
  });
}

function handleDialogInput(event: Event): void {
  const target = event.target as HTMLTextAreaElement;
  dialogValue.value = target.value;
  updateDialogSelection(target);
  pushDialogHistoryEntry(target.value, target.selectionStart || 0, target.selectionEnd || 0);
  nextTick((): void => {
    updateDialogSuggestions();
  });
}

function updateDialogSelection(target?: HTMLTextAreaElement): void {
  const element = target ?? dialogTextareaRef.value;
  if (!element) {
    return;
  }

  dialogSelectionStart.value = element.selectionStart || 0;
  dialogSelectionEnd.value = element.selectionEnd || 0;
}

function scrollToSelected(): void {
  if (!dropdownRef.value) {
    return;
  }

  const selectedElement = dropdownRef.value.querySelector(
    `[data-index="${selectedIndex.value}"]`,
  );
  if (selectedElement instanceof HTMLElement) {
    selectedElement.scrollIntoView({ block: "nearest" });
  }
}

function scrollDialogToSelected(): void {
  if (!dialogDropdownRef.value) {
    return;
  }

  const selectedElement = dialogDropdownRef.value.querySelector(
    `[data-index="${dialogSelectedIndex.value}"]`,
  );
  if (selectedElement instanceof HTMLElement) {
    selectedElement.scrollIntoView({ block: "nearest" });
  }
}

function selectSuggestion(suggestion: CompletionSuggestion): void {
  if (suggestion.type === "hint" && suggestion.hintAction === "run-workflow") {
    void runWorkflowForCompletionHint();
    return;
  }

  const element = inputElement.value;
  if (!element) {
    return;
  }

  const cursorPos = element.selectionStart || 0;
  const { newText, newCursorPos } = applyCompletion(props.modelValue || "", cursorPos, suggestion);
  emit("update:modelValue", newText);
  showDropdown.value = false;

  nextTick((): void => {
    const nextElement = inputElement.value;
    if (nextElement) {
      nextElement.focus();
      nextElement.setSelectionRange(newCursorPos, newCursorPos);
    }
  });
}

function selectDialogSuggestion(suggestion: CompletionSuggestion): void {
  if (suggestion.type === "hint" && suggestion.hintAction === "run-workflow") {
    void runWorkflowForCompletionHint();
    return;
  }

  const element = dialogTextareaRef.value;
  if (!element) {
    return;
  }

  const cursorPos = element.selectionStart || 0;
  const { newText, newCursorPos } = applyCompletion(dialogValue.value, cursorPos, suggestion);
  dialogValue.value = newText;
  pushDialogHistoryEntry(newText, newCursorPos, newCursorPos);
  showDialogDropdown.value = false;

  nextTick((): void => {
    if (dialogTextareaRef.value) {
      dialogTextareaRef.value.focus();
      dialogTextareaRef.value.setSelectionRange(newCursorPos, newCursorPos);
      updateDialogSelection(dialogTextareaRef.value);
    }
  });
}

function handleKeyDown(event: KeyboardEvent): void {
  if (!showDropdown.value || suggestions.value.length === 0) {
    return;
  }

  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      selectedIndex.value = (selectedIndex.value + 1) % suggestions.value.length;
      scrollToSelected();
      break;
    case "ArrowUp":
      event.preventDefault();
      selectedIndex.value = selectedIndex.value === 0
        ? suggestions.value.length - 1
        : selectedIndex.value - 1;
      scrollToSelected();
      break;
    case "Tab":
    case "Enter":
      event.preventDefault();
      selectSuggestion(suggestions.value[selectedIndex.value]);
      break;
    case "Escape":
      event.preventDefault();
      showDropdown.value = false;
      break;
  }
}

function handleDialogKeyDown(event: KeyboardEvent): void {
  if (!showDialogDropdown.value || dialogSuggestions.value.length === 0) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeExpandDialog();
    }
    return;
  }

  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      dialogSelectedIndex.value = (dialogSelectedIndex.value + 1) % dialogSuggestions.value.length;
      scrollDialogToSelected();
      break;
    case "ArrowUp":
      event.preventDefault();
      dialogSelectedIndex.value = dialogSelectedIndex.value === 0
        ? dialogSuggestions.value.length - 1
        : dialogSelectedIndex.value - 1;
      scrollDialogToSelected();
      break;
    case "Tab":
    case "Enter":
      event.preventDefault();
      selectDialogSuggestion(dialogSuggestions.value[dialogSelectedIndex.value]);
      break;
    case "Escape":
      event.preventDefault();
      showDialogDropdown.value = false;
      break;
  }
}

function handleDialogShortcutKeyDown(event: KeyboardEvent): void {
  if (!showExpandDialog.value || !(event.ctrlKey || event.metaKey)) {
    return;
  }

  const key = event.key.toLowerCase();
  if (key === "enter") {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    applyDialogChanges({ closeDialog: false });
    return;
  }

  if (key === "z" && !event.shiftKey) {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    undoDialogHistory();
    return;
  }

  if ((key === "z" && event.shiftKey) || key === "y") {
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    redoDialogHistory();
  }
}

function handleBlur(event: FocusEvent): void {
  const relatedTarget = event.relatedTarget as HTMLElement | null;
  if (relatedTarget && dropdownRef.value?.contains(relatedTarget)) {
    return;
  }

  clearInlineBlurHideTimer();
  inlineBlurHideTimer = setTimeout((): void => {
    inlineBlurHideTimer = null;
    showDropdown.value = false;
  }, 150);
}

function handleDialogBlur(event: FocusEvent): void {
  const relatedTarget = event.relatedTarget as HTMLElement | null;
  if (relatedTarget && dialogDropdownRef.value?.contains(relatedTarget)) {
    return;
  }

  setTimeout((): void => {
    showDialogDropdown.value = false;
  }, 150);
}

function handleDropdownMouseDown(event: MouseEvent): void {
  event.preventDefault();
}

function handleDialogDropdownMouseDown(event: MouseEvent): void {
  event.preventDefault();
}

function handleClickOutside(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  const element = inputElement.value;
  if (!element?.contains(target) && !dropdownRef.value?.contains(target)) {
    showDropdown.value = false;
  }
}

function openExpandDialog(): void {
  openingExpandDialog.value = true;
  dialogValue.value = props.modelValue || "";
  runResult.value = null;
  inspectedRunResult.value = null;
  runRequestError.value = null;
  lastRunRequestNodeResults.value = null;
  lastRunDialogSnapshot.value = null;
  lastInspectedSignature.value = null;
  lastSuccessfulEvaluateRequestSignature.value = null;
  lastRunNodeId.value = null;
  lastAutoEvaluateStartedAtMs.value = null;
  resetDialogHistory(dialogValue.value);
  showExpandDialog.value = true;
  showDialogDropdown.value = false;
  pushOverlayState();
  if (props.navigationEnabled && props.navigationTotal > 1) {
    emit("registerFieldIndex", props.navigationIndex);
  }
  nextTick((): void => {
    openingExpandDialog.value = false;
    const element = dialogTextareaRef.value;
    element?.focus();
    updateDialogSelection(element ?? undefined);
  });
}

function closeExpandDialog(): void {
  showExpandDialog.value = false;
  showDialogDropdown.value = false;
}

function applyDialogChanges(options?: { closeDialog?: boolean }): void {
  emit("update:modelValue", dialogValue.value);
  if (options?.closeDialog ?? true) {
    closeExpandDialog();
  }
}

function handleNavigateToNode(targetNodeId: string): void {
  emit("update:modelValue", dialogValue.value);
  const desiredIterationIndex = selectedLoopIterationIndex.value;
  if (evaluateLoopNodeId.value && desiredIterationIndex !== null) {
    workflowStore.setEvaluateLoopSelection({
      loopNodeId: evaluateLoopNodeId.value,
      iterationIndex: desiredIterationIndex,
    });
  }
  if (desiredIterationIndex !== null) {
    const targetResultIndex = findNodeResultIndexForLoopIteration(
      targetNodeId,
      desiredIterationIndex,
      props.nodes,
      props.edges,
      availableNodeResults.value,
    );
    workflowStore.setTimelinePickedNodeResultIndex(targetResultIndex);
  } else {
    workflowStore.setTimelinePickedNodeResultIndex(null);
  }
  const payload = { targetNodeId };
  emit("navigateNode", payload);
  workflowStore.runExpressionGraphNavigate(payload);
}

function handleNavigate(direction: "prev" | "next"): void {
  emit("update:modelValue", dialogValue.value);
  emit("navigate", direction);
}

function handleFooterNavigatePrev(): void {
  if (!canNavigatePrev.value) {
    return;
  }
  handleNavigate("prev");
}

function handleFooterNavigateNext(): void {
  if (!canNavigateNext.value) {
    return;
  }
  handleNavigate("next");
}

function navigateLoopItem(direction: "prev" | "next"): void {
  const state = evaluateLoopItemNavigation.value;
  if (!state) {
    return;
  }
  const nextIterationIndex =
    direction === "prev"
      ? state.currentIterationIndex - 1
      : state.currentIterationIndex + 1;
  if (nextIterationIndex < 0 || nextIterationIndex >= state.totalDisplayCount) {
    return;
  }
  workflowStore.setEvaluateLoopSelection({
    loopNodeId: state.loopNodeId,
    iterationIndex: nextIterationIndex,
  });
  workflowStore.setTimelinePickedNodeResultIndex(
    findNodeResultIndexForLoopIteration(
      props.currentNodeId,
      nextIterationIndex,
      props.nodes,
      props.edges,
      availableNodeResults.value,
    ),
  );
}

function handleLoopItemNavigatePrev(): void {
  navigateLoopItem("prev");
}

function handleLoopItemNavigateNext(): void {
  navigateLoopItem("next");
}

function replaceTrimmedExpression(raw: string, nextExpression: string): string {
  const leading = raw.match(/^\s*/)?.[0] ?? "";
  const trailing = raw.match(/\s*$/)?.[0] ?? "";
  return `${leading}${nextExpression}${trailing}`;
}

function replaceExpressionMatch(
  raw: string,
  match: ExpressionMatch,
  nextExpression: string,
): string {
  return `${raw.slice(0, match.start)}${nextExpression}${raw.slice(match.end)}`;
}

function focusDialogRange(start: number, end: number): void {
  nextTick((): void => {
    const element = dialogTextareaRef.value;
    if (!element) {
      return;
    }
    element.focus();
    element.setSelectionRange(start, end);
    updateDialogSelection(element);
  });
}

function handleDialogPathPick(segments: (string | number)[]): void {
  const inspectedMatch = inspectedTarget.value;
  if (
    inspectedMatch &&
    inspectedExpression.value &&
    showInspectedOutputPathPicker.value
  ) {
    const nextExpression = extendDollarExpression(inspectedExpression.value, segments);
    dialogValue.value = replaceExpressionMatch(dialogValue.value, inspectedMatch, nextExpression);
    pushDialogHistoryEntry(
      dialogValue.value,
      inspectedMatch.start,
      inspectedMatch.start + nextExpression.length,
    );
    focusDialogRange(inspectedMatch.start, inspectedMatch.start + nextExpression.length);
    return;
  }

  const trimmed = dialogValue.value.trim();
  if (!isSingleDollarReferenceExpression(trimmed)) {
    return;
  }

  const nextExpression = extendDollarExpression(trimmed, segments);
  dialogValue.value = replaceTrimmedExpression(dialogValue.value, nextExpression);
  pushDialogHistoryEntry(dialogValue.value, 0, dialogValue.value.length);
  focusDialogRange(0, dialogValue.value.length);
}

function findDollarExpressions(text: string): ExpressionMatch[] {
  const expressions: ExpressionMatch[] = [];
  let index = 0;

  while (index < text.length) {
    if (text[index] === "$" && index + 1 < text.length && /[a-zA-Z]/.test(text[index + 1])) {
      const start = index;
      index += 1;

      while (index < text.length && /[a-zA-Z0-9_.]/.test(text[index])) {
        index += 1;
      }

      while (index < text.length && (text[index] === "(" || text[index] === "[")) {
        const bracket = text[index];
        const closeBracket = bracket === "(" ? ")" : "]";
        let depth = 1;
        index += 1;

        while (index < text.length && depth > 0) {
          if (text[index] === bracket) {
            depth += 1;
          } else if (text[index] === closeBracket) {
            depth -= 1;
          } else if (text[index] === '"' || text[index] === "'") {
            const quote = text[index];
            index += 1;
            while (index < text.length && text[index] !== quote) {
              if (text[index] === "\\") {
                index += 1;
              }
              index += 1;
            }
          }
          index += 1;
        }

        while (index < text.length && text[index] === ".") {
          index += 1;
          while (index < text.length && /[a-zA-Z0-9_]/.test(text[index])) {
            index += 1;
          }
        }
      }

      expressions.push({ start, end: index, expr: text.slice(start, index) });
    } else {
      index += 1;
    }
  }

  return expressions;
}

function truncateString(str: string, maxLength: number): string {
  if (!str || str.length <= maxLength) {
    return str || "";
  }
  return `${str.slice(0, maxLength - 3)}...`;
}

function formatRunResult(value: unknown): string {
  if (value === null || value === undefined) {
    return "null";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

let finalResultCopyResetTimer: ReturnType<typeof setTimeout> | null = null;

function clearFinalResultCopyResetTimer(): void {
  if (finalResultCopyResetTimer !== null) {
    clearTimeout(finalResultCopyResetTimer);
    finalResultCopyResetTimer = null;
  }
}

async function copyFinalResult(): Promise<void> {
  if (!runResult.value || runResult.value.error || typeof navigator === "undefined" || !navigator.clipboard) {
    return;
  }

  await navigator.clipboard.writeText(formatRunResult(runResult.value.result));
  finalResultCopied.value = true;
  clearFinalResultCopyResetTimer();
  finalResultCopyResetTimer = setTimeout((): void => {
    finalResultCopied.value = false;
    finalResultCopyResetTimer = null;
  }, 1400);
}

function parseRunError(error: unknown): string {
  if (error instanceof AxiosError) {
    const detail = error.response?.data as { detail?: string } | undefined;
    if (typeof detail?.detail === "string") {
      return detail.detail;
    }
    if (typeof error.message === "string" && error.message.length > 0) {
      return error.message;
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Expression evaluation failed.";
}

function loopNodeForEvaluateTitle(): WorkflowNode | null {
  const currentNodeId = props.currentNodeId;
  if (!currentNodeId) {
    return null;
  }

  const selfNode = props.nodes.find((node) => node.id === currentNodeId) ?? null;
  if (selfNode?.type === "loop") {
    return selfNode;
  }

  const enclosingLoopId = findEnclosingLoopIdForListSize(
    currentNodeId,
    props.nodes,
    props.edges,
  );
  if (!enclosingLoopId) {
    return null;
  }

  return props.nodes.find((node) => node.id === enclosingLoopId) ?? null;
}

async function refreshLoopTitlePreviewListSize(): Promise<void> {
  const currentNodeId = props.currentNodeId;
  const loopNode = loopNodeForEvaluateTitle();
  if (!currentNodeId || !loopNode) {
    loopTitlePreviewListSize.value = null;
    return;
  }

  const localListSize = loopListSizeForEvaluateTitle(
    currentNodeId,
    props.nodes,
    props.edges,
    availableNodeResults.value,
  );
  if (localListSize !== null) {
    loopTitlePreviewListSize.value = localListSize;
    return;
  }

  const selectedLoopTotal =
    lastRunNodeId.value === currentNodeId ? runResult.value?.selected_loop_total : null;
  loopTitlePreviewListSize.value =
    typeof selectedLoopTotal === "number" ? selectedLoopTotal : null;
}

let inspectedEvaluationRequestId = 0;

async function evaluateExpressionWithContext(
  expression: string,
  workflowId: string,
  requestNodeResults: EvaluatedNodeResultInput[],
  options?: { selectedLoopIterationIndex?: number | null },
): Promise<ExpressionEvaluateResponse> {
  return expressionApi.evaluate({
    expression,
    workflow_id: workflowId,
    current_node_id: props.currentNodeId!,
    field_name: props.dialogKeyLabel || undefined,
    input_body: workflowStore.buildExecutionRequestBody(),
    selected_loop_iteration_index:
      options?.selectedLoopIterationIndex ?? selectedLoopIterationIndex.value,
    node_results: requestNodeResults,
  });
}

async function refreshInspectedSelection(
  expression: string,
  requestNodeResults: EvaluatedNodeResultInput[],
  signature: string,
): Promise<void> {
  const workflowId = workflowStore.currentWorkflow?.id;
  if (!workflowId) {
    return;
  }

  const requestId = ++inspectedEvaluationRequestId;

  try {
    const nextResult = await evaluateExpressionWithContext(
      expression,
      workflowId,
      requestNodeResults,
    );
    if (requestId !== inspectedEvaluationRequestId) {
      return;
    }
    inspectedRunResult.value = nextResult;
    lastInspectedSignature.value = signature;
  } catch (error: unknown) {
    if (requestId !== inspectedEvaluationRequestId) {
      return;
    }
    inspectedRunResult.value = {
      result: null,
      result_type: "null",
      preserved_type: false,
      error: parseRunError(error),
    };
    lastInspectedSignature.value = signature;
  }
}

function getExecutionValidationMessage(message: string | undefined): string {
  return message || "Workflow validation failed before evaluation.";
}

async function ensureExecutionContext(workflowId: string): Promise<NodeResult[] | null> {
  if (hasContext.value) {
    return availableNodeResults.value;
  }

  const validation = workflowStore.validateWorkflow();
  if (!validation.isValid) {
    runRequestError.value = getExecutionValidationMessage(validation.errors[0]?.message);
    return null;
  }

  const executeTargetValidation = await workflowStore.validateExecuteTargetsExist();
  if (!executeTargetValidation.isValid) {
    runRequestError.value = getExecutionValidationMessage(
      executeTargetValidation.errors[0]?.message,
    );
    return null;
  }

  if (workflowStore.webhookBodyMode === "generic") {
    const parsedBody = parseWebhookJson(workflowStore.runInputJson);
    if (parsedBody.error) {
      runRequestError.value = parsedBody.error;
      return null;
    }
  }

  if (workflowStore.hasUnsavedChanges) {
    await workflowStore.saveWorkflow();
  }

  const executionResult = await workflowApi.execute(
    workflowId,
    workflowStore.buildExecutionRequestBody(),
    {
      bodyMode: workflowStore.currentWorkflow?.webhook_body_mode,
      testRun: true,
      triggerSource: "Canvas",
      simpleResponse: false,
    },
  );
  workflowStore.applyExecutionResultSnapshot(executionResult, { preserveSelection: true });
  return executionResult.node_results || [];
}

async function runWorkflowForCompletionHint(): Promise<void> {
  const workflowId = workflowStore.currentWorkflow?.id;
  if (!workflowId || hintWorkflowRunLoading.value || workflowStore.isExecuting) {
    return;
  }
  const expandWasOpen = showExpandDialog.value;
  const savedCursor =
    expandWasOpen
      ? Math.min(dialogSelectionStart.value, dialogValue.value.length)
      : null;

  hintWorkflowRunLoading.value = true;
  runRequestError.value = null;
  try {
    await workflowStore.executeWorkflow(workflowStore.buildExecutionRequestBody());
    await nextTick();
    await nextTick();

    if (expandWasOpen) {
      emit("update:modelValue", dialogValue.value);
      await nextTick();
      closeExpandDialog();
      await nextTick();
      await nextTick();
      const el = inputElement.value;
      if (el !== null && savedCursor !== null) {
        el.focus();
        el.setSelectionRange(savedCursor, savedCursor);
      }
    } else {
      inputElement.value?.focus();
    }

    clearInlineBlurHideTimer();
    updateSuggestions();
    if (!showDropdown.value || suggestions.value.length === 0) {
      await nextTick();
      updateSuggestions();
    }
  } catch {
    // Streaming / save failures are reflected on the canvas and debug UI.
  } finally {
    hintWorkflowRunLoading.value = false;
  }
}

function stringifyEvaluateSignatureValue(value: unknown): string {
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function buildEvaluateRequestSignature(
  expression: string,
  inspectedExpressionValue: string | null,
  requestNodeResults: EvaluatedNodeResultInput[],
): string {
  return JSON.stringify({
    workflowId: workflowStore.currentWorkflow?.id ?? null,
    currentNodeId: props.currentNodeId ?? null,
    expression,
    inspectedExpression: inspectedExpressionValue,
    selectedLoopIterationIndex: selectedLoopIterationIndex.value,
    inputBody: stringifyEvaluateSignatureValue(workflowStore.buildExecutionRequestBody()),
    nodeResults: requestNodeResults,
  });
}

async function runExpression(options?: { resetOutputPathPicker?: boolean }): Promise<void> {
  if (runLoading.value || !props.currentNodeId || !showExpandDialog.value) {
    return;
  }

  const requestCurrentNodeId = props.currentNodeId;
  const requestDialogSnapshot = dialogValue.value;
  if (!requestDialogSnapshot.trim()) {
    return;
  }
  const requestInspectedExpression = inspectedExpression.value;
  const runStartedAt = performance.now();
  let didEvaluate = false;
  const workflowId = workflowStore.currentWorkflow?.id;
  if (!workflowId) {
    runRequestError.value = "Workflow must be loaded before evaluation.";
    return;
  }

  if (options?.resetOutputPathPicker) {
    outputPathPickerKey.value += 1;
  }

  forceOutputScrollTopOnNextUpdate.value = true;
  runLoading.value = true;
  runRequestError.value = null;
  finalResultCopied.value = false;
  clearFinalResultCopyResetTimer();

  try {
    const evaluationNodeResults = await ensureExecutionContext(workflowId);
    if (!evaluationNodeResults) {
      return;
    }

    const requestNodeResults: EvaluatedNodeResultInput[] = evaluationNodeResults.map((result) => ({
      node_id: result.node_id,
      label: result.node_label,
      output: result.output,
    }));
    const requestSignature = buildEvaluateRequestSignature(
      requestDialogSnapshot,
      requestInspectedExpression,
      requestNodeResults,
    );
    if (
      requestSignature === lastSuccessfulEvaluateRequestSignature.value &&
      requestDialogSnapshot === lastRunDialogSnapshot.value &&
      runResult.value !== null &&
      !runResult.value.error
    ) {
      return;
    }

    const [nextRunResult, nextInspectedRunResult] = await Promise.all([
      evaluateExpressionWithContext(requestDialogSnapshot, workflowId, requestNodeResults),
      requestInspectedExpression
        ? evaluateExpressionWithContext(requestInspectedExpression, workflowId, requestNodeResults)
        : Promise.resolve(null),
    ]);

    if (
      !showExpandDialog.value ||
      requestDialogSnapshot !== dialogValue.value ||
      requestCurrentNodeId !== props.currentNodeId
    ) {
      return;
    }

    runResult.value = nextRunResult;
    lastRunNodeId.value = requestCurrentNodeId;
    if (typeof nextRunResult.selected_loop_total === "number") {
      loopTitlePreviewListSize.value = nextRunResult.selected_loop_total;
    } else if (loopNodeForEvaluateTitle()) {
      loopTitlePreviewListSize.value = null;
    }
    inspectedRunResult.value =
      requestInspectedExpression && requestInspectedExpression === inspectedExpression.value
        ? nextInspectedRunResult
        : null;
    lastRunRequestNodeResults.value = requestNodeResults;
    lastRunDialogSnapshot.value = requestDialogSnapshot;
    didEvaluate = true;
    if (!nextRunResult.error) {
      lastSuccessfulEvaluateRequestSignature.value = requestSignature;
    }
    lastInspectedSignature.value =
      requestInspectedExpression && requestInspectedExpression === inspectedExpression.value
        ? `${requestDialogSnapshot}\n---\n${requestInspectedExpression}`
        : null;
  } catch (error: unknown) {
    if (!showExpandDialog.value || requestDialogSnapshot !== dialogValue.value) {
      return;
    }
    runRequestError.value = parseRunError(error);
  } finally {
    if (didEvaluate) {
      lastRunDurationMs.value = Math.max(1, Math.round(performance.now() - runStartedAt));
      nextTick((): void => {
        clearPendingOutputBottomStickTimer();
        scrollOutputToTop();
      });
    }
    runLoading.value = false;
    if (queuedEvaluateAfterCurrentRun) {
      const shouldResetOutputPathPicker = queuedEvaluateShouldResetOutputPathPicker;
      queuedEvaluateAfterCurrentRun = false;
      queuedEvaluateShouldResetOutputPathPicker = false;
      queueExpressionEvaluation({ resetOutputPathPicker: shouldResetOutputPathPicker });
    }
  }
}

let unsubDismissOverlays: (() => void) | null = null;

onMounted((): void => {
  document.addEventListener("click", handleClickOutside);
  document.addEventListener("keydown", handleDialogShortcutKeyDown, true);
  unsubDismissOverlays = onDismissOverlays((): void => {
    if (!showExpandDialog.value) {
      return;
    }
    if (showDialogDropdown.value) {
      showDialogDropdown.value = false;
      return;
    }
    closeExpandDialog();
  });
});

onUnmounted((): void => {
  document.removeEventListener("click", handleClickOutside);
  document.removeEventListener("keydown", handleDialogShortcutKeyDown, true);
  unsubDismissOverlays?.();
  clearInlineBlurHideTimer();
  clearAutoEvaluateTimer();
  clearPendingOutputBottomStickTimer();
  clearFinalResultCopyResetTimer();
});

function handleExpressionDragStart(event: DragEvent): void {
  const text = inspectedExpression.value;
  if (!text || !event.dataTransfer) {
    return;
  }
  event.dataTransfer.setData("text/plain", text);
  event.dataTransfer.effectAllowed = "copy";
}

function handleDialogTextareaDrop(event: DragEvent): void {
  event.preventDefault();
  const text = event.dataTransfer?.getData("text/plain");
  if (!text || !dialogTextareaRef.value) {
    return;
  }

  const textarea = dialogTextareaRef.value;
  let insertPos = dialogSelectionStart.value;

  // Try to resolve the character offset at the drop coordinates.
  if ("caretPositionFromPoint" in document) {
    const pos = (document as Document & { caretPositionFromPoint(x: number, y: number): { offsetNode: Node; offset: number } | null }).caretPositionFromPoint(event.clientX, event.clientY);
    if (pos && pos.offsetNode === textarea) {
      insertPos = pos.offset;
    }
  } else if ("caretRangeFromPoint" in document) {
    const range = (document as Document & { caretRangeFromPoint(x: number, y: number): Range | null }).caretRangeFromPoint(event.clientX, event.clientY);
    if (range && range.startContainer === textarea) {
      insertPos = range.startOffset;
    }
  }

  const current = dialogValue.value;
  const before = current.slice(0, insertPos);
  const after = current.slice(insertPos);
  dialogValue.value = `${before}${text}${after}`;
  const newCursor = insertPos + text.length;
  pushDialogHistoryEntry(dialogValue.value, newCursor, newCursor);

  nextTick((): void => {
    textarea.focus();
    textarea.setSelectionRange(newCursor, newCursor);
    updateDialogSelection(textarea);
  });
}

defineExpose({
  openExpandDialog,
  closeExpandDialog,
});
</script>

<template>
  <div class="relative flex items-center gap-1">
    <div class="relative flex-1">
      <input
        v-if="singleLine"
        ref="inputRef"
        type="text"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :class="inputClasses"
        @input="handleInput"
        @keydown="handleKeyDown"
        @blur="handleBlur"
      >
      <textarea
        v-else
        ref="textareaRef"
        :value="modelValue"
        :placeholder="placeholder"
        :disabled="disabled"
        :rows="rows"
        :class="cn(textareaClasses, expandable && 'pr-10')"
        @input="handleInput"
        @keydown="handleKeyDown"
        @blur="handleBlur"
      />

      <button
        v-if="expandable && !disabled && !singleLine"
        type="button"
        class="absolute right-2 top-2 rounded p-1 text-muted-foreground transition-colors hover:bg-accent/80 hover:text-foreground"
        title="Expand editor"
        @click="openExpandDialog"
      >
        <Maximize2 class="h-4 w-4" />
      </button>

      <div
        v-if="showDropdown && suggestions.length > 0"
        ref="dropdownRef"
        class="absolute z-50 max-h-48 w-full overflow-auto rounded-md border bg-popover shadow-lg"
        :style="{ top: `${dropdownPosition.top}px`, left: `${dropdownPosition.left}px` }"
        @mousedown="handleDropdownMouseDown"
      >
        <div class="py-1">
          <template
            v-for="(suggestion, index) in suggestions"
            :key="suggestion.label"
          >
            <div
              v-if="suggestion.type === 'hint'"
              class="flex w-full items-center gap-2 px-3 py-2 text-sm text-muted-foreground"
            >
              <component
                :is="getTypeIcon(suggestion)"
                :class="cn('h-4 w-4 shrink-0', getTypeColor(suggestion))"
              />
              <span class="min-w-0 flex-1 text-amber-600 dark:text-amber-400">{{ suggestion.label }}</span>
              <button
                v-if="suggestion.hintAction === 'run-workflow'"
                type="button"
                class="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="hintWorkflowRunLoading || !canRun || workflowStore.isExecuting"
                @click.stop="runWorkflowForCompletionHint()"
              >
                <Loader2
                  v-if="hintWorkflowRunLoading"
                  class="h-3 w-3 animate-spin"
                />
                <Play
                  v-else
                  class="h-3 w-3 fill-current"
                />
                Run
              </button>
            </div>
            <button
              v-else
              :data-index="index"
              type="button"
              :class="cn(
                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent',
                index === selectedIndex && 'bg-accent',
              )"
              @click="selectSuggestion(suggestion)"
              @mouseenter="selectedIndex = index"
            >
              <component
                :is="getTypeIcon(suggestion)"
                :class="cn('h-4 w-4 shrink-0', getTypeColor(suggestion))"
              />
              <span class="flex-1 truncate font-mono">{{ suggestion.label }}</span>
              <span
                v-if="suggestion.detail"
                class="shrink-0 text-xs text-muted-foreground"
              >
                {{ suggestion.detail }}
              </span>
            </button>
          </template>
        </div>

        <div
          v-if="
            suggestions.length > 0 &&
              (!suggestions.every((suggestion) => suggestion.type === 'hint') ||
                suggestions.some((s) => s.hintAction === 'run-workflow'))
          "
          class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t px-3 py-1.5 text-xs text-muted-foreground"
        >
          <span v-if="suggestions.some((s) => s.type !== 'hint')">
            <kbd class="rounded bg-muted px-1 py-0.5 text-[10px]">Tab</kbd> to insert
          </span>
          <span v-if="suggestions.some((s) => s.hintAction === 'run-workflow')">
            <kbd class="rounded bg-muted px-1 py-0.5 text-[10px]">Enter</kbd> to run workflow
          </span>
          <span v-if="suggestions.some((s) => s.type !== 'hint')">
            <kbd class="rounded bg-muted px-1 py-0.5 text-[10px]">↑↓</kbd> to navigate
          </span>
        </div>
      </div>
    </div>

    <button
      v-if="expandable && !disabled && singleLine"
      type="button"
      class="flex h-10 w-8 shrink-0 items-center justify-center rounded-md border border-input bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      title="Expand editor"
      @click="openExpandDialog"
    >
      <Maximize2 class="h-3.5 w-3.5" />
    </button>

    <Teleport to="body">
      <div
        v-if="showExpandDialog"
        class="pointer-events-none fixed inset-0 z-[10000] flex items-center justify-center"
      >
        <div
          class="pointer-events-auto fixed inset-0 bg-black/50 backdrop-blur-sm"
          @click="closeExpandDialog"
        />

        <div
          class="pointer-events-auto relative z-10 mx-4 flex h-[80vh] w-[80vw] max-w-[1400px] flex-col overflow-hidden rounded-lg border bg-background shadow-2xl"
        >
          <div
            class="relative z-[60] flex min-w-0 shrink-0 items-center justify-between border-b bg-background px-4 py-3"
          >
            <h3 class="min-w-0 flex-1 truncate pr-2 text-lg font-semibold">
              {{ expandDialogHeading }}
            </h3>
            <div class="flex items-center gap-2 shrink-0">
              <div
                v-if="evaluateLoopItemNavigation"
                class="flex items-center gap-0.5 rounded-md border border-border/50 bg-background/70 px-1 py-1"
              >
                <span class="px-1 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                  Loop
                </span>
                <button
                  type="button"
                  class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 md:min-h-[28px] md:min-w-[28px] md:p-1.5"
                  :disabled="!evaluateLoopItemNavigation.canNavigatePrev"
                  title="Previous loop item"
                  @click.stop="handleLoopItemNavigatePrev"
                >
                  <ChevronLeft class="h-4 w-4" />
                </button>
                <span class="min-w-[3.75rem] text-center text-xs text-muted-foreground">
                  {{ evaluateLoopItemNavigation.currentDisplayIndex }} /
                  {{ evaluateLoopItemNavigation.totalDisplayCount }}
                </span>
                <button
                  type="button"
                  class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 md:min-h-[28px] md:min-w-[28px] md:p-1.5"
                  :disabled="!evaluateLoopItemNavigation.canNavigateNext"
                  title="Next loop item"
                  @click.stop="handleLoopItemNavigateNext"
                >
                  <ChevronRight class="h-4 w-4" />
                </button>
              </div>
              <button
                type="button"
                class="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                @click="closeExpandDialog"
              >
                <X class="h-5 w-5" />
              </button>
            </div>
          </div>

          <div
            v-if="showEvaluateGraphToolbar"
            class="relative z-[60] grid w-full min-w-0 shrink-0 gap-3 border-b border-border/40 bg-background px-6 py-3 md:grid-cols-2"
          >
            <div
              v-if="evaluateGraphNavigationEnabled && incomingNeighborNodes.length > 0"
              class="pointer-events-auto min-w-0"
            >
              <div class="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Upstream
              </div>
              <div class="flex flex-wrap gap-2">
                <button
                  v-for="node in incomingNeighborNodes"
                  :key="`incoming-${node.id}`"
                  type="button"
                  class="flex min-w-0 items-center gap-2 rounded-lg px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
                  @click.stop="handleNavigateToNode(node.id)"
                >
                  <ChevronLeft
                    :class="cn('h-4 w-4 shrink-0 opacity-80', nodeIconColorClass[node.type] ?? 'text-muted-foreground')"
                  />
                  <component
                    :is="nodeIcons[node.type] ?? Type"
                    :class="cn('h-5 w-5 shrink-0', nodeIconColorClass[node.type] ?? 'text-muted-foreground')"
                  />
                  <span class="min-w-0 max-w-[min(72ch,min(960px,45vw))] truncate text-sm font-medium text-foreground">
                    {{ truncateString(node.data.label || node.type, 120) }}
                  </span>
                </button>
              </div>
            </div>
            <div
              v-if="evaluateGraphNavigationEnabled && outgoingNeighborNodes.length > 0"
              :class="
                cn(
                  'pointer-events-auto min-w-0 md:text-right',
                  incomingNeighborNodes.length === 0 && 'w-full md:col-start-2',
                )
              "
            >
              <div
                :class="
                  cn(
                    'mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground',
                    incomingNeighborNodes.length === 0 && 'text-right',
                  )
                "
              >
                Downstream
              </div>
              <div
                :class="
                  cn(
                    'flex flex-wrap gap-2',
                    incomingNeighborNodes.length === 0 ? 'justify-end' : 'md:justify-end',
                  )
                "
              >
                <button
                  v-for="node in outgoingNeighborNodes"
                  :key="`outgoing-${node.id}`"
                  type="button"
                  class="flex min-w-0 items-center gap-2 rounded-lg px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
                  @click.stop="handleNavigateToNode(node.id)"
                >
                  <span class="min-w-0 max-w-[min(72ch,min(960px,45vw))] truncate text-sm font-medium text-foreground">
                    {{ truncateString(node.data.label || node.type, 120) }}
                  </span>
                  <component
                    :is="nodeIcons[node.type] ?? Type"
                    :class="cn('h-5 w-5 shrink-0', nodeIconColorClass[node.type] ?? 'text-muted-foreground')"
                  />
                  <ChevronRight
                    :class="cn('h-4 w-4 shrink-0 opacity-80', nodeIconColorClass[node.type] ?? 'text-muted-foreground')"
                  />
                </button>
              </div>
            </div>
          </div>

          <div
            ref="evaluateDialogBodyRef"
            class="relative z-0 flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            <div
              class="flex max-h-[min(34dvh,260px)] shrink-0 flex-col overflow-y-auto overscroll-y-contain px-4 pt-3 pb-0 [scrollbar-gutter:stable]"
            >
              <textarea
                ref="dialogTextareaRef"
                :value="dialogValue"
                :placeholder="placeholder"
                rows="6"
                class="box-border w-full min-h-[8.5rem] rounded-md border-2 border-input bg-background px-4 py-3 font-mono text-base leading-relaxed placeholder:text-muted-foreground transition-colors focus-visible:border-primary focus-visible:outline-none resize-none"
                @input="handleDialogInput"
                @keydown="handleDialogKeyDown"
                @keyup="updateDialogSelection()"
                @click="updateDialogSelection()"
                @mouseup="updateDialogSelection()"
                @select="updateDialogSelection()"
                @blur="handleDialogBlur"
                @dragover.prevent
                @drop="handleDialogTextareaDrop"
              />
            </div>

            <div
              class="mx-4 mb-3 mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-md border bg-muted/20"
            >
              <div class="flex items-center justify-between border-b bg-background px-4 py-2">
                <div class="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  <span>Output</span>
                  <span
                    v-if="showInspectedOutputPathPicker"
                    class="normal-case tracking-normal text-[10px] font-normal"
                    title="Double-click a row below to extend the selected expression."
                  >
                    Double-click a row below to extend the selected expression.
                  </span>
                  <span
                    v-else-if="showOutputPathPicker"
                    class="normal-case tracking-normal text-[10px] font-normal"
                    title="Double-click a row below to insert its path."
                  >
                    Double-click a row below to insert its path.
                  </span>
                </div>

                <div
                  v-if="runDurationLabel"
                  class="flex items-center gap-2 text-[11px] text-muted-foreground"
                >
                  <Loader2
                    v-if="runLoading"
                    class="h-3.5 w-3.5 animate-spin"
                  />
                  <span>{{ runDurationLabel }}</span>
                </div>
              </div>

              <div class="relative flex min-h-0 flex-1 flex-col">
                <div
                  ref="outputScrollRef"
                  class="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-3 [scrollbar-gutter:stable]"
                >
                  <div
                    v-if="runRequestError"
                    class="mb-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive"
                  >
                    {{ runRequestError }}
                  </div>
                  <div
                    v-else-if="runLoading && !runResult"
                    class="flex min-h-[8rem] items-center justify-center gap-2 text-xs text-muted-foreground"
                  >
                    <Loader2 class="h-3.5 w-3.5 animate-spin" />
                    <span>Updating preview...</span>
                  </div>

                  <template v-else-if="runResult">
                    <div
                      v-if="runResult.error"
                      class="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive"
                    >
                      {{ runResult.error }}
                    </div>
                    <template v-else>
                      <div :class="cn('flex flex-col', showSelectedInspectPanel && 'gap-3')">
                        <div
                          v-if="showSelectedInspectPanel"
                          class="min-h-0 overflow-hidden"
                        >
                          <Transition
                            mode="out-in"
                            enter-active-class="transition-all delay-50 duration-170 ease-out"
                            enter-from-class="translate-y-1 opacity-0"
                            enter-to-class="translate-y-0 opacity-100"
                            leave-active-class="transition-all duration-120 ease-in"
                            leave-from-class="translate-y-0 opacity-100"
                            leave-to-class="translate-y-0 opacity-0"
                          >
                            <div
                              :key="selectedInspectContentKey"
                              class="flex flex-col rounded-md border border-border/60 bg-background/60 px-3 py-3"
                            >
                              <div class="mb-2 flex shrink-0 items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                <span>{{ inspectedResultLabel }}</span>
                                <code
                                  draggable="true"
                                  class="normal-case rounded bg-muted px-1.5 py-0.5 text-[10px] text-foreground cursor-grab active:cursor-grabbing select-none"
                                  title="Drag to insert into the expression editor"
                                  @dragstart="handleExpressionDragStart"
                                >
                                  {{ inspectedExpression }}
                                </code>
                              </div>

                              <div
                                v-if="inspectedRunResult?.error"
                                class="shrink-0 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive"
                              >
                                {{ inspectedRunResult.error }}
                              </div>
                              <ExpressionOutputPathPicker
                                v-else-if="showInspectedOutputPathPicker && inspectedRunResult"
                                :key="`selected-${outputPathPickerKey}-${inspectedExpression}`"
                                :value="inspectedRunResult.result"
                                :default-collapsed="true"
                                :build-drag-text="inspectedExpression ? (segs) => extendDollarExpression(inspectedExpression!, segs) : null"
                                @pick="handleDialogPathPick"
                              />
                              <pre
                                v-else-if="inspectedRunResult"
                                class="whitespace-pre-wrap break-words text-xs font-mono text-foreground"
                              >{{ formatRunResult(inspectedRunResult.result) }}</pre>

                              <div
                                v-if="inspectedRunResult"
                                class="mt-3 shrink-0 border-t border-border/60 pt-3 text-xs leading-normal text-muted-foreground"
                              >
                                Type:
                                <span class="font-medium text-foreground">{{ inspectedRunResult.result_type }}</span>
                                <span
                                  v-if="inspectedRunResult.preserved_type"
                                  class="ml-2 text-emerald-600 dark:text-emerald-400"
                                >
                                  type preserved
                                </span>
                              </div>
                            </div>
                          </Transition>
                        </div>

                        <div class="shrink-0 transition-all duration-220 ease-[cubic-bezier(0.22,1,0.36,1)]">
                          <div class="rounded-md border border-border/60 bg-background/50 px-3 py-3">
                            <div class="mb-2 flex shrink-0 items-center justify-between gap-3">
                              <div class="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                                Final Result
                              </div>
                              <button
                                v-if="canCopyFinalResult"
                                type="button"
                                class="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-background/70 px-2 py-1 text-[10px] font-medium uppercase tracking-[0.06em] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                                @click="copyFinalResult()"
                              >
                                <Check
                                  v-if="finalResultCopied"
                                  class="h-3 w-3"
                                />
                                <Copy
                                  v-else
                                  class="h-3 w-3"
                                />
                                <span>{{ finalResultCopied ? "Copied" : "Copy Final Result" }}</span>
                              </button>
                            </div>

                            <ExpressionOutputPathPicker
                              v-if="showOutputPathPicker && finalResultTreeValue != null"
                              :key="`result-${outputPathPickerKey}`"
                              :value="finalResultTreeValue"
                              :build-drag-text="isSingleDollarReferenceExpression(dialogValue.trim()) ? (segs) => extendDollarExpression(dialogValue.trim(), segs) : null"
                              @pick="handleDialogPathPick"
                            />
                            <pre
                              v-else
                              class="whitespace-pre-wrap break-words text-xs font-mono text-foreground"
                            >{{ formatRunResult(runResult.result) }}</pre>

                            <div
                              class="mt-3 border-t border-border/60 pt-3 text-xs leading-relaxed text-muted-foreground"
                            >
                              Type:
                              <span class="font-medium text-foreground">{{ runResult.result_type }}</span>
                              <span
                                v-if="runResult.preserved_type"
                                class="ml-2 text-emerald-600 dark:text-emerald-400"
                              >
                                type preserved
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </template>
                  </template>

                  <p
                    v-else
                    class="m-0 text-xs italic text-muted-foreground"
                  >
                    {{ runIdleHint }}
                    <span v-if="dialogExpressions.length > 1">
                      Select a $field and run again to inspect its JSON structure.
                    </span>
                  </p>
                </div>
              </div>
            </div>

            <div
              v-if="showDialogDropdown && dialogSuggestions.length > 0"
              ref="dialogDropdownRef"
              class="absolute left-4 right-4 z-40 max-h-64 overflow-auto rounded-md border bg-popover shadow-lg"
              :style="{ top: `${dialogDropdownPosition.top}px` }"
              @mousedown="handleDialogDropdownMouseDown"
            >
              <div class="py-1">
                <template
                  v-for="(suggestion, index) in dialogSuggestions"
                  :key="suggestion.label"
                >
                  <div
                    v-if="suggestion.type === 'hint'"
                    class="flex w-full items-center gap-3 px-4 py-2 text-sm text-muted-foreground"
                  >
                    <component
                      :is="getTypeIcon(suggestion)"
                      :class="cn('h-4 w-4 shrink-0', getTypeColor(suggestion))"
                    />
                    <span class="min-w-0 flex-1 text-amber-600 dark:text-amber-400">{{ suggestion.label }}</span>
                    <button
                      v-if="suggestion.hintAction === 'run-workflow'"
                      type="button"
                      class="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                      :disabled="hintWorkflowRunLoading || !canRun || workflowStore.isExecuting"
                      @click.stop="runWorkflowForCompletionHint()"
                    >
                      <Loader2
                        v-if="hintWorkflowRunLoading"
                        class="h-3 w-3 animate-spin"
                      />
                      <Play
                        v-else
                        class="h-3 w-3 fill-current"
                      />
                      Run
                    </button>
                  </div>
                  <button
                    v-else
                    :data-index="index"
                    type="button"
                    :class="cn(
                      'flex w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors hover:bg-accent',
                      index === dialogSelectedIndex && 'bg-accent',
                    )"
                    @click="selectDialogSuggestion(suggestion)"
                    @mouseenter="dialogSelectedIndex = index"
                  >
                    <component
                      :is="getTypeIcon(suggestion)"
                      :class="cn('h-4 w-4 shrink-0', getTypeColor(suggestion))"
                    />
                    <span class="flex-1 font-mono">{{ suggestion.label }}</span>
                    <span
                      v-if="suggestion.detail"
                      class="text-xs text-muted-foreground"
                    >
                      {{ suggestion.detail }}
                    </span>
                  </button>
                </template>
              </div>

              <div
                v-if="
                  dialogSuggestions.length > 0 &&
                    (!dialogSuggestions.every((suggestion) => suggestion.type === 'hint') ||
                      dialogSuggestions.some((s) => s.hintAction === 'run-workflow'))
                "
                class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t px-4 py-2 text-xs text-muted-foreground"
              >
                <span v-if="dialogSuggestions.some((s) => s.type !== 'hint')">
                  <kbd class="rounded bg-muted px-1.5 py-0.5 text-[11px]">Tab</kbd> to insert
                </span>
                <span v-if="dialogSuggestions.some((s) => s.hintAction === 'run-workflow')">
                  <kbd class="rounded bg-muted px-1.5 py-0.5 text-[11px]">Enter</kbd> to run workflow
                </span>
                <span v-if="dialogSuggestions.some((s) => s.type !== 'hint')">
                  <kbd class="rounded bg-muted px-1.5 py-0.5 text-[11px]">↑↓</kbd> to navigate
                </span>
              </div>
            </div>
          </div>

          <div
            class="relative z-[60] flex shrink-0 items-center justify-between border-t bg-muted/30 px-4 py-3"
          >
            <div
              v-if="showNavigation"
              class="pointer-events-auto flex items-center gap-2"
            >
              <button
                type="button"
                :disabled="!canNavigatePrev"
                :class="cn(
                  'rounded-md p-2 transition-colors',
                  canNavigatePrev
                    ? 'text-foreground hover:bg-accent'
                    : 'cursor-not-allowed text-muted-foreground/40',
                )"
                @click.stop="handleFooterNavigatePrev"
              >
                <ChevronLeft class="h-4 w-4" />
              </button>
              <span class="min-w-[3rem] text-center text-sm text-muted-foreground">
                {{ navigationIndex + 1 }} / {{ navigationTotal }}
              </span>
              <button
                type="button"
                :disabled="!canNavigateNext"
                :class="cn(
                  'rounded-md p-2 transition-colors',
                  canNavigateNext
                    ? 'text-foreground hover:bg-accent'
                    : 'cursor-not-allowed text-muted-foreground/40',
                )"
                @click.stop="handleFooterNavigateNext"
              >
                <ChevronRight class="h-4 w-4" />
              </button>
            </div>
            <div
              v-else
              class="flex-1"
            />

            <div class="flex items-center gap-2">
              <button
                type="button"
                class="rounded-md px-4 py-2 text-sm font-medium transition-colors hover:bg-accent"
                @click="closeExpandDialog"
              >
                Cancel
              </button>
              <button
                type="button"
                class="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                @click="applyDialogChanges()"
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
</style>
