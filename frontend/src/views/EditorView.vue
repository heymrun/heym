<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useMediaQuery } from "@vueuse/core";
import { useRoute, useRouter } from "vue-router";
import { AlertTriangle, ChevronLeft, ChevronRight, Compass, Copy, Download, Globe, GitBranch, History, LayoutTemplate, Moon, Pencil, RefreshCw, Save, Search, Share2, Sparkles, Sun, TerminalSquare, Trash2, Users, X, XCircle } from "lucide-vue-next";
import axios from "axios";

import type {
  ExecutionToken,
  SseNodeConfig,
  WebhookBodyMode,
  WorkflowAuthType,
  WorkflowListItem,
  WorkflowShare,
} from "@/types/workflow";
import type { Team, TeamShare } from "@/types/team";

import WorkflowCanvas from "@/components/Canvas/WorkflowCanvas.vue";
import ContextualShowcase from "@/features/showcase/components/ContextualShowcase.vue";
import ShareTemplateModal from "@/features/templates/components/ShareTemplateModal.vue";
import { useRunbookPlayer } from "@/features/runbook/useRunbookPlayer";
import RunbookCursor from "@/features/runbook/components/RunbookCursor.vue";
import { RUNBOOK_QUERY_FLAG, RUNBOOK_QUERY_VALUE } from "@/features/runbook/runbookScript";
import WorkflowCommandPalette from "@/components/Dialogs/WorkflowCommandPalette.vue";
import WebPortalSettingsDialog from "@/components/Dialogs/WebPortalSettingsDialog.vue";
import WorkflowEditHistoryDialog from "@/components/Dialogs/WorkflowEditHistoryDialog.vue";
import { resolveShowcaseContext } from "@/features/showcase/showcaseResolver";
import ExpressionEvaluateFallbackDialog from "@/components/ui/ExpressionEvaluateFallbackDialog.vue";
import AnalysisPanel from "@/components/Panels/AnalysisPanel.vue";
import DebugPanel from "@/components/Panels/DebugPanel.vue";
import ExecutionHistoryDialog from "@/components/Panels/ExecutionHistoryDialog.vue";
import NodePanel from "@/components/Panels/NodePanel.vue";
import PropertiesPanel from "@/components/Panels/PropertiesPanel.vue";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import Tooltip from "@/components/ui/Tooltip.vue";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { getDocPath } from "@/docs/manifest";
import { joinOriginAndPath } from "@/lib/appUrl";
import { buildExecutionLogForAssistant } from "@/lib/executionLog";
import { isPaletteOpenInNewTab } from "@/lib/paletteNavigate";
import { parseWebhookJson, stringifyWebhookJson } from "@/lib/webhookBody";
import { useRecentWorkflows } from "@/composables/useRecentWorkflows";
import { useToast } from "@/composables/useToast";
import { templatesApi, teamsApi, workflowApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { useShowcaseStore } from "@/stores/showcase";
import { useThemeStore } from "@/stores/theme";
import { useWorkflowStore, type ValidationError } from "@/stores/workflow";

const route = useRoute();
const router = useRouter();
const { startRunbookNewWorkflow, playRunbookInPlace } = useRunbookPlayer();
const authStore = useAuthStore();
const showcaseStore = useShowcaseStore();
const themeStore = useThemeStore();
const workflowStore = useWorkflowStore();
const { addRecent } = useRecentWorkflows();
const { showToast } = useToast();
const { activeContext, isDesktopPanelOpen, isMobileSheetOpen } = storeToRefs(showcaseStore);
const HITL_RESOLUTION_STORAGE_KEY = "heym-hitl-resolution";
const isMobile = useMediaQuery("(max-width: 767px)");

const loading = ref(true);
// On mobile, start with both side panels collapsed so only the canvas is visible.
const leftPanelOpen = ref(!isMobile.value);
const rightPanelOpen = ref(!isMobile.value);
const historyOpen = ref(false);
const editHistoryOpen = ref(false);
const shareOpen = ref(false);
const shareTemplateOpen = ref(false);
const curlOpen = ref(false);
const curlInput = ref("{}");
const webhookBodyMode = ref<WebhookBodyMode>("legacy");
const authType = ref<WorkflowAuthType>("jwt");
const authHeaderKey = ref("");
const authHeaderValue = ref("");
const curlCopied = ref(false);
const executionTokens = ref<ExecutionToken[]>([]);
const selectedTokenId = ref<string | null>(null);
const tokenTtlSeconds = ref<number>(900);
const tokenMode = ref<"short" | "long">("long");
const tokenVisibility = ref<Record<string, boolean>>({});
const tokenCreating = ref(false);
const tokenRevoking = ref<string | null>(null);
const sseEnabled = ref(false);
const simpleResponse = ref(true);
const sseNodeConfig = ref<Record<string, SseNodeConfig>>({});
const editingNodeId = ref<string | null>(null);
const editingNodeMessage = ref("");
const cacheTtlMinutes = ref(0);
const cacheEvicting = ref(false);
const rateLimitRequests = ref(0);
const rateLimitWindowSeconds = ref(60);
const shareEmail = ref("");
const shareError = ref("");
const shareLoading = ref(false);
const shareSubmitting = ref(false);
const shareRemoving = ref<string | null>(null);
const workflowShares = ref<WorkflowShare[]>([]);
const workflowTeamShares = ref<TeamShare[]>([]);
const shareTeamId = ref("");
const teams = ref<Team[]>([]);
const validationErrors = ref<ValidationError[]>([]);
const showValidationDialog = ref(false);
const portalDialogRef = ref<InstanceType<typeof WebPortalSettingsDialog> | null>(null);
const showCommandPalette = ref(false);
const paletteWorkflows = ref<WorkflowListItem[]>([]);
let pendingExecutionStreamAbortController: AbortController | null = null;
let pendingExecutionReconnectId: number | null = null;
let pendingExecutionStreamHistoryId: string | null = null;

const workflowId = computed(() => route.params.id as string);
const workflowName = computed(() => workflowStore.currentWorkflow?.name || "Workflow");
const workflowDescription = computed(() => workflowStore.currentWorkflow?.description || "");
const isDashboardWidget = computed(
  () => workflowStore.currentWorkflow?.kind === "dashboard_widget",
);
const isStandardWorkflow = computed(
  () => Boolean(workflowStore.currentWorkflow) && !isDashboardWidget.value,
);
const hasUnsavedChanges = computed(() => workflowStore.hasUnsavedChanges);
const isSaving = computed(() => workflowStore.isSaving);
const isEditing = computed(() => isTitleEditing.value || isDescriptionEditing.value);

const isTitleEditing = ref(false);
const isDescriptionEditing = ref(false);
const editingTitleValue = ref("");
const editingDescriptionValue = ref("");
const titleInputRef = ref<HTMLInputElement | null>(null);
const descriptionInputRef = ref<HTMLInputElement | null>(null);
let skipNextTitleCommit = false;

function returnToDashboard(event?: MouseEvent): void {
  const target = { name: "dashboard", query: { tab: "dashboard" } };
  if (event?.ctrlKey || event?.metaKey) {
    const routeTarget = router.resolve(target);
    window.open(routeTarget.href, "_blank", "noopener,noreferrer");
    return;
  }

  void router.push(target);
}
let skipNextDescriptionCommit = false;

function startTitleEdit(): void {
  if (isDescriptionEditing.value) {
    const trimmed = editingDescriptionValue.value.trim();
    const newValue = trimmed || null;
    if (newValue !== (workflowStore.currentWorkflow?.description ?? null)) {
      void workflowStore.updateMetadata(workflowStore.currentWorkflow?.name ?? "", newValue);
    }
    isDescriptionEditing.value = false;
  }
  editingTitleValue.value = workflowStore.currentWorkflow?.name ?? "";
  isTitleEditing.value = true;
  void nextTick(() => {
    titleInputRef.value?.select();
  });
}

function commitTitleEdit(): void {
  if (skipNextTitleCommit) {
    skipNextTitleCommit = false;
    isTitleEditing.value = false;
    return;
  }
  const trimmed = editingTitleValue.value.trim();
  if (trimmed && trimmed !== workflowStore.currentWorkflow?.name) {
    void workflowStore.updateMetadata(trimmed, workflowStore.currentWorkflow?.description ?? null);
  }
  isTitleEditing.value = false;
}

function cancelTitleEdit(): void {
  skipNextTitleCommit = true;
  isTitleEditing.value = false;
}

function startDescriptionEdit(): void {
  if (workflowStore.hasUnsavedChanges && !isTitleEditing.value) return;
  if (isTitleEditing.value) {
    const trimmed = editingTitleValue.value.trim();
    if (trimmed && trimmed !== workflowStore.currentWorkflow?.name) {
      void workflowStore.updateMetadata(trimmed, workflowStore.currentWorkflow?.description ?? null);
    }
    isTitleEditing.value = false;
  }
  editingDescriptionValue.value = workflowStore.currentWorkflow?.description ?? "";
  isDescriptionEditing.value = true;
  void nextTick(() => {
    descriptionInputRef.value?.focus();
  });
}

function commitDescriptionEdit(): void {
  if (skipNextDescriptionCommit) {
    skipNextDescriptionCommit = false;
    isDescriptionEditing.value = false;
    return;
  }
  const trimmed = editingDescriptionValue.value.trim();
  const newValue = trimmed || null;
  if (newValue !== (workflowStore.currentWorkflow?.description ?? null)) {
    void workflowStore.updateMetadata(
      workflowStore.currentWorkflow?.name ?? "",
      newValue,
    );
  }
  isDescriptionEditing.value = false;
}

function cancelDescriptionEdit(): void {
  skipNextDescriptionCommit = true;
  isDescriptionEditing.value = false;
}

const isGenericWebhookBodyMode = computed(() => webhookBodyMode.value === "generic");
const showcaseContext = computed(() => {
  return resolveShowcaseContext({ routePath: route.path });
});
const sseConfigurableNodes = computed(() => {
  return workflowStore.nodes
    .filter((node) => node.type !== "sticky")
    .slice()
    .sort((leftNode, rightNode) => {
      const xDiff = leftNode.position.x - rightNode.position.x;
      if (xDiff !== 0) return xDiff;

      const yDiff = leftNode.position.y - rightNode.position.y;
      if (yDiff !== 0) return yDiff;

      return (leftNode.data?.label || leftNode.id).localeCompare(
        rightNode.data?.label || rightNode.id,
      );
    });
});
const isShowcaseOpenForEditor = computed(() => {
  return activeContext.value === showcaseContext.value &&
    (isDesktopPanelOpen.value || isMobileSheetOpen.value);
});
const curlBodyError = computed(() => parseWebhookJson(curlInput.value).error);
let removeOverlayDismiss: (() => void) | null = null;

watch(
  () => workflowStore.propertiesPanelOpen,
  (open) => {
    if (open && !rightPanelOpen.value) {
      rightPanelOpen.value = true;
    }
  },
);

// Collapse both side panels when the viewport becomes mobile so the canvas
// (standard workflow or dashboard widget) is shown on its own.
watch(isMobile, (mobile) => {
  if (mobile) {
    leftPanelOpen.value = false;
    rightPanelOpen.value = false;
  }
});

function toggleRightPanel(): void {
  rightPanelOpen.value = !rightPanelOpen.value;
}

const { analysisPanelOpen } = storeToRefs(workflowStore);

const analysisWorkflowId = computed(() => workflowStore.currentWorkflow?.id ?? "");
const analysisWorkflowPayload = computed(() => ({
  id: workflowStore.currentWorkflow?.id,
  name: workflowStore.currentWorkflow?.name,
  description: workflowStore.currentWorkflow?.description ?? null,
  nodes: workflowStore.nodes,
  edges: workflowStore.edges,
  error_workflow_id: workflowStore.currentWorkflow?.error_workflow_id ?? null,
  minutes_saved_per_run: workflowStore.currentWorkflow?.minutes_saved_per_run ?? null,
}));

function toggleAnalysisPanel(): void {
  analysisPanelOpen.value = !analysisPanelOpen.value;
  if (analysisPanelOpen.value) {
    leftPanelOpen.value = false;
  }
}

// Runs the workflow (best-effort) and returns its execution log so the analysis
// prompt can include real run results. Returns undefined if it can't run.
async function runWorkflowForAnalysis(): Promise<
  Record<string, unknown> | undefined
> {
  if (workflowStore.isExecuting || workflowStore.nodes.length === 0) {
    return undefined;
  }
  if (!workflowStore.validateWorkflow().isValid) return undefined;
  const targets = await workflowStore.validateExecuteTargetsExist();
  if (!targets.isValid) return undefined;
  try {
    await workflowStore.executeWorkflow(workflowStore.buildExecutionRequestBody());
  } catch (err) {
    if (err instanceof Error && err.message === "Execution cancelled") {
      throw err;
    }
    // Other errors surface via execution state; analysis still proceeds.
  }
  const log = buildExecutionLogForAssistant(
    workflowStore.nodeResults,
    workflowStore.executionResult,
  );
  return (log as Record<string, unknown> | null) ?? undefined;
}

// The analysis panel and NodePanel share the left slot; opening one hides the other.
watch(leftPanelOpen, (open) => {
  if (open && analysisPanelOpen.value) {
    analysisPanelOpen.value = false;
  }
});

function toggleShowcaseGuide(): void {
  if (!showcaseContext.value) return;

  if (isShowcaseOpenForEditor.value) {
    showcaseStore.closeAll();
    return;
  }

  showcaseStore.setCurrentContext(showcaseContext.value);
  if (isMobile.value) {
    showcaseStore.openMobileSheet();
  } else {
    showcaseStore.openDesktopPanel();
  }
  pushOverlayState();
}

function clearPendingExecutionReconnect(): void {
  if (pendingExecutionReconnectId !== null) {
    window.clearTimeout(pendingExecutionReconnectId);
    pendingExecutionReconnectId = null;
  }
}

function stopPendingExecutionStream(): void {
  clearPendingExecutionReconnect();
  pendingExecutionStreamHistoryId = null;
  if (pendingExecutionStreamAbortController) {
    pendingExecutionStreamAbortController.abort();
    pendingExecutionStreamAbortController = null;
  }
}

function isRunbookAutoPlayRequested(): boolean {
  return route.query[RUNBOOK_QUERY_FLAG] === RUNBOOK_QUERY_VALUE;
}

async function playRunbookFromQueryIfReady(): Promise<void> {
  if (!isRunbookAutoPlayRequested()) return;

  const runbookQuery = { ...route.query };
  delete runbookQuery[RUNBOOK_QUERY_FLAG];
  await router.replace({
    name: "editor",
    params: { id: workflowId.value },
    query: runbookQuery,
  });

  if (workflowStore.nodes.length !== 0) return;
  await nextTick();
  await nextTick();
  void playRunbookInPlace();
}

async function refreshPendingExecutionOnce(): Promise<void> {
  const result = workflowStore.executionResult;
  const historyId = result?.execution_history_id;
  if (!historyId || result?.status !== "pending") return;

  const entry = await workflowStore.fetchExecutionHistoryEntry(historyId, true);
  if (!entry || !entry.result) return;

  workflowStore.applyExecutionHistoryEntry(entry);
  if (entry.status !== "pending" && historyId === pendingExecutionStreamHistoryId) {
    stopPendingExecutionStream();
  }
}

function schedulePendingExecutionReconnect(historyId: string): void {
  clearPendingExecutionReconnect();
  pendingExecutionReconnectId = window.setTimeout(() => {
    pendingExecutionReconnectId = null;
    const currentResult = workflowStore.executionResult;
    if (
      currentResult?.status === "pending" &&
      currentResult.execution_history_id === historyId
    ) {
      ensurePendingExecutionStream();
    }
  }, 1500);
}

function ensurePendingExecutionStream(): void {
  const result = workflowStore.executionResult;
  const historyId = result?.execution_history_id;
  if (!historyId || result?.status !== "pending") return;
  if (
    pendingExecutionStreamAbortController &&
    pendingExecutionStreamHistoryId === historyId
  ) {
    return;
  }

  stopPendingExecutionStream();
  pendingExecutionStreamHistoryId = historyId;
  pendingExecutionStreamAbortController = new AbortController();

  workflowApi.streamWorkflowHistoryEntry(
    workflowId.value,
    historyId,
    (serverHistory) => {
      const entry = workflowStore.executionHistoryDetails.get(serverHistory.id) ?? {
        id: serverHistory.id,
        started_at: serverHistory.started_at,
        inputs: serverHistory.inputs,
        status: serverHistory.status as "running" | "success" | "error" | "pending",
        result: {
          workflow_id: serverHistory.workflow_id,
          status: serverHistory.status as "success" | "error" | "pending",
          outputs: serverHistory.outputs,
          execution_time_ms: serverHistory.execution_time_ms,
          node_results: serverHistory.node_results || [],
          execution_history_id: serverHistory.id,
          highlight: serverHistory.highlight ?? null,
        },
        trigger_source: serverHistory.trigger_source ?? null,
      };

      const nextEntry = {
        ...entry,
        started_at: serverHistory.started_at,
        inputs: serverHistory.inputs,
        status: serverHistory.status as "running" | "success" | "error" | "pending",
        result: {
          workflow_id: serverHistory.workflow_id,
          status: serverHistory.status as "success" | "error" | "pending",
          outputs: serverHistory.outputs,
          execution_time_ms: serverHistory.execution_time_ms,
          node_results: serverHistory.node_results || [],
          execution_history_id: serverHistory.id,
          highlight: serverHistory.highlight ?? null,
        },
        trigger_source: serverHistory.trigger_source ?? null,
      };
      workflowStore.applyExecutionHistoryEntry(nextEntry);
    },
    () => {
      stopPendingExecutionStream();
    },
    () => {
      if (pendingExecutionStreamHistoryId !== historyId) return;
      pendingExecutionStreamAbortController = null;
      schedulePendingExecutionReconnect(historyId);
    },
    pendingExecutionStreamAbortController.signal,
  );
}

function handleHitlResolutionStorage(event: StorageEvent): void {
  if (event.key !== HITL_RESOLUTION_STORAGE_KEY) return;
  void refreshPendingExecutionOnce();
}


function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

async function handleKeyDown(event: KeyboardEvent): Promise<void> {
  const isMeta = event.metaKey || event.ctrlKey;

  // Run Workflow: Ctrl+Enter — works even when an input/textarea is focused
  if (isMeta && event.key === "Enter") {
    if (showCommandPalette.value) {
      return;
    }
    event.preventDefault();
    if (!workflowStore.isExecuting && workflowStore.nodes.length > 0) {
      const validation = workflowStore.validateWorkflow();
      if (!validation.isValid) {
        validationErrors.value = validation.errors;
        showValidationDialog.value = true;
        pushOverlayState();
        return;
      }
      const executeTargetValidation = await workflowStore.validateExecuteTargetsExist();
      if (!executeTargetValidation.isValid) {
        validationErrors.value = executeTargetValidation.errors;
        showValidationDialog.value = true;
        pushOverlayState();
        return;
      }

      workflowStore.propertiesPanelTab = "config";
      rightPanelOpen.value = true;
      if (
        workflowStore.currentWorkflow?.webhook_body_mode === "generic" &&
        parseWebhookJson(workflowStore.runInputJson).error
      ) {
        return;
      }
      const body = workflowStore.buildExecutionRequestBody();
      void workflowStore.executeWorkflow(body).catch(() => {
        // Errors are reflected via execution state / debug UI.
      });
    }
    return;
  }

  if (isTypingTarget(event.target)) return;

  // Command palette: Cmd/Ctrl + K
  if (isMeta && event.key === "k") {
    event.preventDefault();
    showCommandPalette.value = true;
    pushOverlayState();
    return;
  }

  // Save: Cmd/Ctrl + S
  if (isMeta && event.key === "s") {
    event.preventDefault();
    if (hasUnsavedChanges.value && !isSaving.value) {
      handleSave();
    }
  }

  // Undo: Cmd/Ctrl + Z (skip while agent memory graph dialog is open — graph has its own undo)
  if (isMeta && event.key === "z" && !event.shiftKey) {
    if (workflowStore.agentMemoryGraphDialogOpen) {
      return;
    }
    event.preventDefault();
    workflowStore.undo();
  }

  // Redo: Cmd/Ctrl + Shift + Z or Cmd/Ctrl + Y
  if (isMeta && ((event.key === "z" && event.shiftKey) || event.key === "y")) {
    if (workflowStore.agentMemoryGraphDialogOpen) {
      return;
    }
    event.preventDefault();
    workflowStore.redo();
  }
}

function downloadWorkflow(): void {
  const data = {
    nodes: workflowStore.nodes,
    edges: workflowStore.edges,
  };
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const safeName = workflowName.value.trim().replace(/\s+/g, "-").toLowerCase() || "workflow";
  link.href = url;
  link.download = `${safeName}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

async function bringExecutionFromRoute(): Promise<void> {
  const execId = route.params.executionId as string | undefined;
  if (!execId) return;
  // Use the same store path as the Execution History dialog's "Bring to Canvas" so
  // highlights and node/output mapping populate identically (pass the full execution
  // result, not just node_results). fetchExecutionHistoryEntry returns null when the
  // execution is missing/inaccessible -> fall back to the plain workflow.
  const entry = await workflowStore.fetchExecutionHistoryEntry(execId);
  if (!entry) return;
  workflowStore.loadHistoryInputs(
    entry.inputs,
    entry.result?.node_results || [],
    entry.result || undefined,
  );
}

onMounted(async () => {
  window.addEventListener("keydown", handleKeyDown);
  window.addEventListener("storage", handleHitlResolutionStorage);
  removeOverlayDismiss = onDismissOverlays(() => {
    historyOpen.value = false;
    editHistoryOpen.value = false;
    shareOpen.value = false;
    curlOpen.value = false;
    showValidationDialog.value = false;
    showCommandPalette.value = false;
    shareTemplateOpen.value = false;
    portalDialogRef.value?.closeDialog();
  });
  await authStore.fetchUser();
  const [loadResult, listResult] = await Promise.allSettled([
    workflowStore.loadWorkflow(workflowId.value),
    workflowApi.list(),
  ]);
  paletteWorkflows.value = listResult.status === "fulfilled" ? listResult.value : [];
  if (loadResult.status === "rejected") {
    router.push({ name: "dashboard" });
    loading.value = false;
    return;
  }
  try {
    if (workflowStore.currentWorkflow) {
      addRecent(workflowId.value, workflowStore.currentWorkflow.name);
    }
    authType.value = workflowStore.currentWorkflow?.auth_type || "jwt";
    authHeaderKey.value = workflowStore.currentWorkflow?.auth_header_key || "";
    authHeaderValue.value = workflowStore.currentWorkflow?.auth_header_value || "";
    webhookBodyMode.value = workflowStore.currentWorkflow?.webhook_body_mode || "legacy";
    if (workflowStore.pendingHistoryInputs) {
      workflowStore.loadHistoryInputs(
        workflowStore.pendingHistoryInputs,
        workflowStore.pendingHistoryNodeResults || undefined,
        workflowStore.pendingHistoryExecutionResult || undefined,
      );
    }
    await bringExecutionFromRoute();
    // Handle node template injection via query param
    const nodeTemplateId = route.query.addNodeTemplate as string | undefined;
    if (nodeTemplateId) {
      try {
        const nodeTemplate = await templatesApi.getNode(nodeTemplateId);
        const nodeId = `node_${Date.now()}`;
        workflowStore.addNode({
          id: nodeId,
          type: nodeTemplate.node_type as import("@/types/workflow").NodeType,
          position: { x: 300, y: 200 },
          data: {
            label: String(nodeTemplate.node_data?.label ?? nodeTemplate.name),
            ...nodeTemplate.node_data,
          } as import("@/types/workflow").NodeData,
        });
        await workflowStore.saveWorkflow();
      } catch {
        // silently ignore if template not found
      }
      // Clean up query param from URL
      const nextQuery = { ...route.query };
      delete nextQuery.addNodeTemplate;
      router.replace({
        name: "editor",
        params: { id: workflowId.value },
        query: nextQuery,
      });
    }

  } finally {
    loading.value = false;
  }
  await playRunbookFromQueryIfReady();
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeyDown);
  window.removeEventListener("storage", handleHitlResolutionStorage);
  stopPendingExecutionStream();
  removeOverlayDismiss?.();
  removeOverlayDismiss = null;
});

watch(workflowName, (name) => {
  document.title = `Heym - ${name}`;
}, { immediate: true });

watch(
  () => ({
    status: workflowStore.executionResult?.status,
    historyId: workflowStore.executionResult?.execution_history_id,
  }),
  ({ status, historyId }) => {
    if (status === "pending" && historyId) {
      ensurePendingExecutionStream();
      return;
    }
    stopPendingExecutionStream();
  },
  { immediate: true, deep: true },
);

watch(
  () => route.params.id as string,
  async (newId, oldId) => {
    const id = typeof newId === "string" ? newId : newId?.[0];
    const prevId = typeof oldId === "string" ? oldId : oldId?.[0];
    if (id && prevId && id !== prevId) {
      loading.value = true;
      let loadedWorkflow = false;
      try {
        await workflowStore.loadWorkflow(id);
        if (workflowStore.currentWorkflow) {
          addRecent(id, workflowStore.currentWorkflow.name);
        }
        authType.value = workflowStore.currentWorkflow?.auth_type || "jwt";
        authHeaderKey.value = workflowStore.currentWorkflow?.auth_header_key || "";
        authHeaderValue.value = workflowStore.currentWorkflow?.auth_header_value || "";
        webhookBodyMode.value = workflowStore.currentWorkflow?.webhook_body_mode || "legacy";
        loadedWorkflow = true;
      } catch {
        router.push({ name: "dashboard" });
      } finally {
        loading.value = false;
      }
      if (loadedWorkflow) {
        await playRunbookFromQueryIfReady();
      }
    }
  },
);

watch(
  () => route.params.executionId as string | undefined,
  async (execId, prevExecId) => {
    if (execId && execId !== prevExecId) {
      await bringExecutionFromRoute();
    }
  },
);

watch(authType, async (value) => {
  if (!workflowStore.currentWorkflow) return;
  if (workflowStore.currentWorkflow.auth_type === value) return;
  await workflowApi.update(workflowId.value, { auth_type: value });
  workflowStore.currentWorkflow.auth_type = value;
});

watch(authHeaderKey, async (value) => {
  if (!workflowStore.currentWorkflow) return;
  if (workflowStore.currentWorkflow.auth_header_key === value) return;
  await workflowApi.update(workflowId.value, { auth_header_key: value });
  workflowStore.currentWorkflow.auth_header_key = value;
});

watch(authHeaderValue, async (value) => {
  if (!workflowStore.currentWorkflow) return;
  if (workflowStore.currentWorkflow.auth_header_value === value) return;
  await workflowApi.update(workflowId.value, { auth_header_value: value });
  workflowStore.currentWorkflow.auth_header_value = value;
});

watch(webhookBodyMode, async (value) => {
  if (!workflowStore.currentWorkflow) return;
  if (workflowStore.currentWorkflow.webhook_body_mode === value) return;
  await workflowApi.update(workflowId.value, { webhook_body_mode: value });
  workflowStore.currentWorkflow.webhook_body_mode = value;
  if (value === "legacy") {
    workflowStore.resetRunInputJsonFromMode();
  }
  if (curlOpen.value) {
    syncCurlInputFromWorkflow();
  }
});

watch(shareOpen, async (open) => {
  if (!open) return;
  if (!isStandardWorkflow.value) {
    shareOpen.value = false;
    return;
  }
  shareError.value = "";
  await loadShares();
});

watch(curlOpen, async (open) => {
  if (!open) return;
  syncCurlInputFromWorkflow();
  const workflow = workflowStore.currentWorkflow;
  if (!workflow) {
    sseEnabled.value = false;
    sseNodeConfig.value = {};
    editingNodeId.value = null;
    editingNodeMessage.value = "";
    return;
  }
  if (workflow) {
    cacheTtlMinutes.value = workflow.cache_ttl_seconds
      ? Math.round(workflow.cache_ttl_seconds / 60)
      : 0;
    rateLimitRequests.value = workflow.rate_limit_requests || 0;
    rateLimitWindowSeconds.value = workflow.rate_limit_window_seconds || 60;
    sseEnabled.value = workflow.sse_enabled ?? false;
    sseNodeConfig.value = { ...(workflow.sse_node_config ?? {}) };
    editingNodeId.value = null;
    editingNodeMessage.value = "";
    if (authType.value === "jwt") {
      executionTokens.value = await workflowApi.executionTokens.list(workflowId.value);
      const firstActive = executionTokens.value.find(
        (t) => !t.revoked && new Date(t.expires_at) > new Date(),
      );
      selectedTokenId.value = firstActive?.id ?? null;
    }
  }
});

watch(curlInput, (value) => {
  if (isGenericWebhookBodyMode.value) {
    workflowStore.runInputJson = value;
  }
});

watch(
  () => workflowStore.runInputJson,
  (value) => {
    if (!curlOpen.value) return;
    if (!isGenericWebhookBodyMode.value) return;
    if (curlInput.value === value) return;
    curlInput.value = value;
  },
);

function syncCurlInputFromWorkflow(): void {
  if (isGenericWebhookBodyMode.value) {
    curlInput.value = workflowStore.runInputJson.trim()
      ? workflowStore.runInputJson
      : "{}";
    return;
  }

  curlInput.value = stringifyWebhookJson(workflowStore.buildLegacyExecutionBody());
}

async function saveCacheSettings(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  const ttlSeconds = cacheTtlMinutes.value > 0 ? cacheTtlMinutes.value * 60 : 0;
  await workflowApi.update(workflowId.value, { cache_ttl_seconds: ttlSeconds });
  workflowStore.currentWorkflow.cache_ttl_seconds = ttlSeconds > 0 ? ttlSeconds : null;
}

async function evictResponseCache(): Promise<void> {
  if (cacheTtlMinutes.value <= 0 || cacheEvicting.value) return;
  cacheEvicting.value = true;
  try {
    await workflowApi.clearResponseCache(workflowId.value);
    showToast("Response cache cleared", "success", 2500);
  } catch (error: unknown) {
    const message = axios.isAxiosError(error)
      ? error.response?.data?.detail || "Failed to clear response cache"
      : "Failed to clear response cache";
    showToast(message, "error");
  } finally {
    cacheEvicting.value = false;
  }
}

async function saveRateLimitSettings(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  await workflowApi.update(workflowId.value, {
    rate_limit_requests: rateLimitRequests.value > 0 ? rateLimitRequests.value : 0,
    rate_limit_window_seconds: rateLimitWindowSeconds.value > 0 ? rateLimitWindowSeconds.value : 0,
  });
  workflowStore.currentWorkflow.rate_limit_requests = rateLimitRequests.value > 0 ? rateLimitRequests.value : null;
  workflowStore.currentWorkflow.rate_limit_window_seconds = rateLimitWindowSeconds.value > 0 ? rateLimitWindowSeconds.value : null;
}

async function saveSseEnabled(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  await workflowApi.update(workflowId.value, { sse_enabled: sseEnabled.value });
  workflowStore.currentWorkflow.sse_enabled = sseEnabled.value;
}

async function saveSseNodeConfig(): Promise<void> {
  if (!workflowStore.currentWorkflow) return;
  await workflowApi.update(workflowId.value, { sse_node_config: sseNodeConfig.value });
  workflowStore.currentWorkflow.sse_node_config = { ...sseNodeConfig.value };
}

function getNodeSseConfig(nodeId: string): SseNodeConfig {
  return sseNodeConfig.value[nodeId] ?? { send_start: true, start_message: null };
}

function getNodeStartMessagePlaceholder(nodeLabel: string): string {
  return `[START] ${nodeLabel}`;
}

async function toggleNodeSendStart(nodeId: string): Promise<void> {
  const current = getNodeSseConfig(nodeId);
  sseNodeConfig.value = {
    ...sseNodeConfig.value,
    [nodeId]: { ...current, send_start: !current.send_start },
  };
  if (editingNodeId.value === nodeId && current.send_start) {
    editingNodeId.value = null;
  }
  await saveSseNodeConfig();
}

function startEditingNodeMessage(nodeId: string): void {
  const current = getNodeSseConfig(nodeId);
  editingNodeId.value = nodeId;
  editingNodeMessage.value = current.start_message ?? "";
}

function cancelEditingNodeMessage(): void {
  editingNodeId.value = null;
  editingNodeMessage.value = "";
}

async function commitNodeMessage(nodeId: string): Promise<void> {
  if (editingNodeId.value !== nodeId) return;
  const current = getNodeSseConfig(nodeId);
  const trimmed = editingNodeMessage.value.trim();
  sseNodeConfig.value = {
    ...sseNodeConfig.value,
    [nodeId]: { ...current, start_message: trimmed || null },
  };
  editingNodeId.value = null;
  editingNodeMessage.value = "";
  await saveSseNodeConfig();
}

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeyDown);
  workflowStore.clearWorkflow();
  document.title = "Heym - AI Workflow Automation";
});

async function handleSave(): Promise<void> {
  await workflowStore.saveWorkflow();
}

function handleLogoClick(event: Event): void {
  if (hasUnsavedChanges.value) {
    if (!confirm("You have unsaved changes. Are you sure you want to leave?")) {
      event.preventDefault();
    }
  }
}


const curlPayload = computed(() => {
  return parseWebhookJson(curlInput.value).value;
});

const curlCommand = computed(() => {
  if (curlBodyError.value) {
    return "Fix JSON body to generate the cURL command.";
  }

  const basePath = sseEnabled.value
    ? `/api/workflows/${workflowId.value}/execute/stream`
    : `/api/workflows/${workflowId.value}/execute`;
  const url = joinOriginAndPath(window.location.origin, basePath);
  const payload = stringifyWebhookJson(curlPayload.value);
  const escapedPayload = payload.replace(/'/g, "'\\''");
  const indentedPayload = escapedPayload
    .split("\n")
    .map((line, index) => (index === 0 ? line : `  ${line}`))
    .join("\n");

  const headerLines = [
    '  -H "Content-Type: application/json" \\',
    '  -H "X-Trigger-Source: API" \\',
  ];
  if (!simpleResponse.value) {
    headerLines.push('  -H "X-Simple-Response: false" \\');
  }
  if (sseEnabled.value) {
    headerLines.push('  -H "Accept: text/event-stream" \\');
  }
  if (authType.value === "jwt") {
    const activeToken = executionTokens.value.find((t) => t.id === selectedTokenId.value);
    const bearer = activeToken ? activeToken.token : "<your-execution-token>";
    headerLines.push(`  -H "Authorization: Bearer ${bearer}" \\`);
  } else if (authType.value === "header_auth") {
    const key = authHeaderKey.value || "X-API-Key";
    const value = authHeaderValue.value || "your-secret-value";
    headerLines.push(`  -H "${key}: ${value}" \\`);
  }

  const commandLines = [
    `curl -X POST${sseEnabled.value ? " --no-buffer" : ""} \\`,
    ...headerLines,
    `  "${url}" \\`,
    `  -d '${indentedPayload}'`,
  ];
  return commandLines.join("\n");
});

async function copyCurlCommand(): Promise<void> {
  if (curlBodyError.value) return;
  await navigator.clipboard.writeText(curlCommand.value);
  curlCopied.value = true;
  setTimeout(() => {
    curlCopied.value = false;
  }, 2000);
}

function formatCurlJson(): void {
  if (curlBodyError.value) return;
  curlInput.value = stringifyWebhookJson(curlPayload.value);
}

async function createExecutionToken(): Promise<void> {
  tokenCreating.value = true;
  try {
    const ttl = tokenMode.value === "long" ? 315360000 : Math.max(60, Math.floor(Number(tokenTtlSeconds.value)));
    const token = await workflowApi.executionTokens.create(workflowId.value, ttl);
    executionTokens.value.unshift(token);
    selectedTokenId.value = token.id;
  } finally {
    tokenCreating.value = false;
  }
}

async function revokeExecutionToken(tokenId: string): Promise<void> {
  tokenRevoking.value = tokenId;
  try {
    await workflowApi.executionTokens.revoke(workflowId.value, tokenId);
    const token = executionTokens.value.find((t) => t.id === tokenId);
    if (token) token.revoked = true;
    if (selectedTokenId.value === tokenId) {
      const nextActive = executionTokens.value.find(
        (t) => !t.revoked && new Date(t.expires_at) > new Date(),
      );
      selectedTokenId.value = nextActive?.id ?? null;
    }
  } finally {
    tokenRevoking.value = null;
  }
}

function formatTokenDate(isoString: string): string {
  return new Date(isoString).toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isTokenExpired(isoString: string): boolean {
  return new Date(isoString) < new Date();
}

async function loadShares(): Promise<void> {
  shareLoading.value = true;
  shareError.value = "";
  try {
    const [userShares, teamShares, teamList] = await Promise.all([
      workflowApi.listShares(workflowId.value),
      workflowApi.listTeamShares(workflowId.value),
      teamsApi.list(),
    ]);
    workflowShares.value = userShares;
    workflowTeamShares.value = teamShares;
    teams.value = teamList;
  } catch (error: unknown) {
    if (axios.isAxiosError(error)) {
      shareError.value = error.response?.data?.detail || "Failed to load shares";
    } else {
      shareError.value = "Failed to load shares";
    }
  } finally {
    shareLoading.value = false;
  }
}

async function addShare(): Promise<void> {
  const email = shareEmail.value.trim();
  if (!email) return;
  shareSubmitting.value = true;
  shareError.value = "";
  try {
    const share = await workflowApi.addShare(workflowId.value, email);
    const existingIndex = workflowShares.value.findIndex((entry) => entry.user_id === share.user_id);
    if (existingIndex >= 0) {
      workflowShares.value.splice(existingIndex, 1, share);
    } else {
      workflowShares.value.push(share);
    }
    workflowShares.value.sort((a, b) => a.email.localeCompare(b.email));
    shareEmail.value = "";
  } catch (error: unknown) {
    if (axios.isAxiosError(error)) {
      shareError.value = error.response?.data?.detail || "Failed to share workflow";
    } else {
      shareError.value = "Failed to share workflow";
    }
  } finally {
    shareSubmitting.value = false;
  }
}

async function removeShare(userId: string): Promise<void> {
  shareRemoving.value = userId;
  shareError.value = "";
  try {
    await workflowApi.removeShare(workflowId.value, userId);
    workflowShares.value = workflowShares.value.filter((share) => share.user_id !== userId);
  } catch (error: unknown) {
    if (axios.isAxiosError(error)) {
      shareError.value = error.response?.data?.detail || "Failed to remove share";
    } else {
      shareError.value = "Failed to remove share";
    }
  } finally {
    shareRemoving.value = null;
  }
}

const workflowTeamOptions = computed(() => {
  const shared = new Set(workflowTeamShares.value.map((s) => s.team_id));
  return [
    { value: "", label: "Select a team" },
    ...teams.value
      .filter((t) => !shared.has(t.id))
      .map((t) => ({ value: t.id, label: t.name })),
  ];
});

async function addWorkflowTeamShare(): Promise<void> {
  if (!shareTeamId.value) return;
  shareSubmitting.value = true;
  shareError.value = "";
  try {
    const share = await workflowApi.addTeamShare(workflowId.value, shareTeamId.value);
    workflowTeamShares.value = [...workflowTeamShares.value, share];
    shareTeamId.value = "";
  } catch (error: unknown) {
    if (axios.isAxiosError(error)) {
      shareError.value = error.response?.data?.detail || "Failed to share with team";
    } else {
      shareError.value = "Failed to share with team";
    }
  } finally {
    shareSubmitting.value = false;
  }
}

async function removeWorkflowTeamShare(teamId: string): Promise<void> {
  shareError.value = "";
  try {
    await workflowApi.removeTeamShare(workflowId.value, teamId);
    workflowTeamShares.value = workflowTeamShares.value.filter((s) => s.team_id !== teamId);
  } catch (error: unknown) {
    if (axios.isAxiosError(error)) {
      shareError.value = error.response?.data?.detail || "Failed to remove team share";
    } else {
      shareError.value = "Failed to remove team share";
    }
  }
}

function closeValidationDialog(): void {
  showValidationDialog.value = false;
  validationErrors.value = [];
}

function selectNodeFromError(nodeId: string): void {
  workflowStore.selectNode(nodeId);
  rightPanelOpen.value = true;
  closeValidationDialog();
}

function openWorkflowFromPalette(workflowId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const workflow = paletteWorkflows.value.find((w) => w.id === workflowId);
  if (workflow) {
    addRecent(workflowId, workflow.name);
  }
  if (isPaletteOpenInNewTab(event)) {
    const resolved = router.resolve({ name: "editor", params: { id: workflowId } });
    window.open(resolved.href, "_blank", "noopener,noreferrer");
  } else {
    router.push({ name: "editor", params: { id: workflowId } });
  }
}

async function handleRunbookFromPalette(): Promise<void> {
  showCommandPalette.value = false;
  await startRunbookNewWorkflow();
}

function handleTabSelectFromPalette(tabId: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const openInNewTab = isPaletteOpenInNewTab(event);
  if (tabId === "evals") {
    if (openInNewTab) {
      window.open(joinOriginAndPath(window.location.origin, "/evals"), "_blank", "noopener,noreferrer");
    } else {
      router.push("/evals");
    }
  } else if (tabId === "chat") {
    if (openInNewTab) {
      window.open(joinOriginAndPath(window.location.origin, "/chats"), "_blank", "noopener,noreferrer");
    } else {
      router.push("/chats");
    }
  } else {
    if (openInNewTab) {
      const path = tabId === "workflows" ? "/" : `/?tab=${tabId}`;
      window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
    } else {
      router.push({ path: "/", query: tabId === "workflows" ? {} : { tab: tabId } });
    }
  }
}

function onDocSelectFromPalette(categoryId: string, slug: string, event?: MouseEvent | KeyboardEvent): void {
  showCommandPalette.value = false;
  const path = getDocPath(categoryId, slug);
  if (isPaletteOpenInNewTab(event)) {
    window.open(joinOriginAndPath(window.location.origin, path), "_blank", "noopener,noreferrer");
  } else {
    router.push(path);
  }
}
</script>

<template>
  <div
    class="h-screen flex flex-col bg-background overflow-x-hidden"
    :style="{ '--showcase-width': '40vw' }"
  >
    <header class="editor-header h-16 border-b border-border/30 flex items-center justify-between px-2 sm:px-4 shrink-0 overflow-x-hidden">
      <div class="flex items-center gap-1 sm:gap-2 md:gap-4 min-w-0 flex-1">
        <router-link
          to="/"
          class="flex items-center gap-2 md:gap-3 font-semibold cursor-pointer group shrink-0"
          @click="handleLogoClick"
        >
          <div class="flex items-center justify-center w-9 h-9">
            <img
              src="/fav.svg"
              alt="Heym"
              class="w-9 h-9"
            >
          </div>
          <span
            class="text-lg font-bold tracking-tight hidden md:block group-hover:text-primary transition-colors"
          >Heym</span>
        </router-link>
        <div class="hidden sm:block w-px h-6 bg-border/50 shrink-0" />
        <div
          class="min-w-0 flex-1"
          data-heym-inline-edit
        >
          <input
            v-if="isTitleEditing"
            ref="titleInputRef"
            v-model="editingTitleValue"
            class="w-full max-w-full min-w-0 font-semibold text-sm md:text-base bg-transparent border-b border-primary outline-none"
            maxlength="100"
            @blur="commitTitleEdit"
            @keydown.enter.prevent="commitTitleEdit"
            @keydown.escape="cancelTitleEdit"
          >
          <h1
            v-else
            data-testid="workflow-title"
            class="block w-full font-semibold text-sm md:text-base truncate cursor-text hover:bg-muted/50 rounded px-0.5 -mx-0.5"
            :title="workflowName"
            @mousedown.prevent="startTitleEdit"
          >
            {{ workflowName }}
          </h1>
          <input
            v-if="isDescriptionEditing"
            ref="descriptionInputRef"
            v-model="editingDescriptionValue"
            class="hidden sm:block w-full max-w-full min-w-0 text-xs text-muted-foreground bg-transparent border-b border-primary outline-none"
            maxlength="300"
            placeholder="Add description..."
            @blur="commitDescriptionEdit"
            @keydown.enter.prevent="commitDescriptionEdit"
            @keydown.escape="cancelDescriptionEdit"
          >
          <p
            v-else-if="hasUnsavedChanges"
            class="hidden sm:block text-xs text-amber-500"
          >
            Unsaved changes
          </p>
          <p
            v-else-if="workflowDescription"
            class="hidden sm:block w-full text-xs text-muted-foreground truncate cursor-text hover:bg-muted/50 rounded px-0.5 -mx-0.5"
            @mousedown.prevent="startDescriptionEdit"
          >
            {{ workflowDescription }}
          </p>
          <p
            v-else
            class="hidden sm:block w-full text-xs text-muted-foreground/40 truncate cursor-text hover:bg-muted/50 rounded px-0.5 -mx-0.5"
            @mousedown.prevent="startDescriptionEdit"
          >
            Add description...
          </p>
        </div>
      </div>

      <p
        v-show="isEditing"
        class="hidden sm:block text-xs text-muted-foreground/85 shrink-0 select-none"
      >
        ↵ save · Esc cancel
      </p>
      <div
        v-show="!isEditing"
        class="flex items-center gap-1 md:gap-2 flex-wrap shrink-0"
      >
        <Button
          v-if="!isDashboardWidget"
          variant="ghost"
          size="icon"
          class="md:hidden text-destructive hover:text-destructive h-11 w-11 min-h-[44px] min-w-[44px]"
          aria-label="Clear"
          :disabled="workflowStore.nodes.length === 0"
          @click="workflowStore.clearCanvas()"
        >
          <Trash2 class="w-4 h-4" />
        </Button>
        <Tooltip
          v-if="!isDashboardWidget"
          label="Clear"
        >
          <Button
            variant="ghost"
            size="sm"
            class="hidden md:inline-flex gap-2 text-destructive hover:text-destructive"
            aria-label="Clear"
            :disabled="workflowStore.nodes.length === 0"
            @click="workflowStore.clearCanvas()"
          >
            <Trash2 class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Clear</span>
          </Button>
        </Tooltip>
        <Button
          v-if="isDashboardWidget"
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:hidden text-foreground"
          aria-label="Back to Dashboard"
          title="Back to Dashboard"
          @click="returnToDashboard"
        >
          <ChevronLeft class="w-4 h-4" />
        </Button>
        <Tooltip
          v-if="isDashboardWidget"
          label="Back to Dashboard"
        >
          <Button
            variant="ghost"
            size="sm"
            class="hidden md:inline-flex gap-2 text-foreground"
            aria-label="Back to Dashboard"
            @click="returnToDashboard"
          >
            <ChevronLeft class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Dashboard</span>
          </Button>
        </Tooltip>
        <Button
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] md:hidden text-foreground"
          aria-label="History"
          @click="historyOpen = true; pushOverlayState()"
        >
          <History class="w-4 h-4" />
        </Button>
        <Tooltip label="History">
          <Button
            variant="ghost"
            size="sm"
            class="hidden md:inline-flex gap-2 text-foreground"
            aria-label="History"
            @click="historyOpen = true; pushOverlayState()"
          >
            <History class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">History</span>
          </Button>
        </Tooltip>
        <Button
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] hidden sm:flex md:hidden text-foreground"
          aria-label="Edit History"
          @click="editHistoryOpen = true; pushOverlayState()"
        >
          <GitBranch class="w-4 h-4" />
        </Button>
        <Tooltip label="Edit History">
          <Button
            variant="ghost"
            size="sm"
            class="hidden md:inline-flex gap-2 text-foreground"
            aria-label="Edit History"
            @click="editHistoryOpen = true; pushOverlayState()"
          >
            <GitBranch class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Edit History</span>
          </Button>
        </Tooltip>
        <Tooltip label="Download">
          <Button
            variant="ghost"
            size="sm"
            class="hidden lg:inline-flex gap-2 text-foreground"
            aria-label="Download"
            @click="downloadWorkflow"
          >
            <Download class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Download</span>
          </Button>
        </Tooltip>
        <Tooltip
          v-if="isStandardWorkflow"
          label="Portal"
        >
          <Button
            variant="ghost"
            size="sm"
            class="hidden lg:inline-flex gap-2 text-foreground"
            aria-label="Portal"
            @click="portalDialogRef?.openDialog(); pushOverlayState()"
          >
            <Globe class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Portal</span>
          </Button>
        </Tooltip>
        <Tooltip
          v-if="isStandardWorkflow"
          label="Share"
        >
          <Button
            variant="ghost"
            size="sm"
            class="hidden lg:inline-flex gap-2 text-foreground"
            aria-label="Share"
            @click="shareOpen = true; pushOverlayState()"
          >
            <Share2 class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Share</span>
          </Button>
        </Tooltip>
        <Tooltip
          v-if="isStandardWorkflow"
          label="Save as reusable template"
        >
          <Button
            variant="ghost"
            size="sm"
            class="hidden xl:inline-flex gap-2 text-foreground"
            aria-label="Template"
            @click="shareTemplateOpen = true"
          >
            <LayoutTemplate class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Template</span>
          </Button>
        </Tooltip>
        <Tooltip
          v-if="isStandardWorkflow"
          label="cURL"
        >
          <Button
            variant="ghost"
            size="sm"
            class="hidden xl:inline-flex gap-2 text-foreground"
            aria-label="cURL"
            @click="curlOpen = true; pushOverlayState()"
          >
            <TerminalSquare class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">cURL</span>
          </Button>
        </Tooltip>
        <Tooltip
          v-if="isStandardWorkflow"
          label="Analyze my workflow"
        >
          <Button
            variant="ghost"
            size="sm"
            class="hidden xl:inline-flex gap-2 text-foreground"
            :class="{ 'text-primary': analysisPanelOpen }"
            aria-label="Analyze"
            @click="toggleAnalysisPanel"
          >
            <Sparkles class="w-4 h-4" />
            <span class="hidden min-[1600px]:inline">Analyze</span>
          </Button>
        </Tooltip>
        <Button
          variant="ghost"
          size="icon"
          class="h-11 w-11 min-h-[44px] min-w-[44px] hidden sm:flex md:hidden text-foreground"
          aria-label="Page Guide"
          title="Page Guide"
          @click="toggleShowcaseGuide"
        >
          <Compass class="w-4 h-4 text-foreground" />
        </Button>
        <Tooltip label="Page Guide">
          <Button
            variant="ghost"
            size="sm"
            class="hidden xl:inline-flex gap-2 text-foreground"
            aria-label="Page Guide"
            @click="toggleShowcaseGuide"
          >
            <Compass class="w-4 h-4 text-foreground" />
            <span class="hidden min-[1600px]:inline">Page Guide</span>
          </Button>
        </Tooltip>
        <Tooltip label="Search (Ctrl+K)">
          <Button
            variant="ghost"
            size="icon"
            class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-9 md:w-9 text-foreground"
            aria-label="Search (Ctrl+K)"
            @click="showCommandPalette = true; pushOverlayState()"
          >
            <Search class="w-4 h-4" />
          </Button>
        </Tooltip>
        <Tooltip :label="themeStore.isDark ? 'Switch to light mode' : 'Switch to dark mode'">
          <Button
            variant="ghost"
            size="icon"
            class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-9 md:w-9 text-foreground"
            :aria-label="themeStore.isDark ? 'Switch to light mode' : 'Switch to dark mode'"
            @click="themeStore.toggle"
          >
            <Sun
              v-if="themeStore.isDark"
              class="w-4 h-4"
            />
            <Moon
              v-else
              class="w-4 h-4"
            />
          </Button>
        </Tooltip>
        <Button
          variant="gradient"
          size="sm"
          data-testid="save-workflow-button"
          :disabled="!hasUnsavedChanges"
          :loading="isSaving"
          class="hidden sm:inline-flex"
          aria-label="Save"
          @click="handleSave"
        >
          <Save class="w-4 h-4" />
          <span class="hidden md:inline">Save</span>
        </Button>
        <Button
          variant="gradient"
          size="icon"
          :disabled="!hasUnsavedChanges"
          :loading="isSaving"
          class="sm:hidden h-11 w-11 min-h-[44px] min-w-[44px]"
          aria-label="Save"
          @click="handleSave"
        >
          <Save class="w-4 h-4" />
        </Button>
      </div>
    </header>

    <ExecutionHistoryDialog
      :open="historyOpen"
      @close="historyOpen = false"
    />

    <WorkflowEditHistoryDialog
      :open="editHistoryOpen"
      :workflow-id="workflowId"
      @close="editHistoryOpen = false"
      @reverted="editHistoryOpen = false"
    />

    <WebPortalSettingsDialog ref="portalDialogRef" />

    <Dialog
      :open="shareOpen"
      title="Share workflow"
      @close="shareOpen = false"
    >
      <div class="space-y-6">
        <p class="text-sm text-muted-foreground">
          Sharing this workflow lets collaborators view, edit, and run it. Credentials and
          sub-workflows used by this workflow are not shared automatically. Share each credential
          and sub-workflow with the same users or teams so recipients can run the workflow.
        </p>
        <div class="space-y-3">
          <div class="space-y-2">
            <Label>Invite by email</Label>
            <div class="flex gap-2">
              <Input
                v-model="shareEmail"
                placeholder="name@example.com"
                type="email"
              />
              <Button
                :loading="shareSubmitting"
                @click="addShare"
              >
                Add
              </Button>
            </div>
          </div>
          <div class="space-y-2">
            <Label>Share with team</Label>
            <div class="flex gap-2">
              <Select
                v-model="shareTeamId"
                :options="workflowTeamOptions"
                class="flex-1"
              />
              <Button
                :loading="shareSubmitting"
                :disabled="!shareTeamId"
                @click="addWorkflowTeamShare"
              >
                <Users class="w-4 h-4" />
                Add
              </Button>
            </div>
          </div>
          <p
            v-if="shareError"
            class="text-xs text-destructive"
          >
            {{ shareError }}
          </p>
        </div>
        <div class="space-y-2">
          <Label>Shared with users</Label>
          <div
            v-if="shareLoading"
            class="text-sm text-muted-foreground"
          >
            Loading...
          </div>
          <div
            v-else-if="workflowShares.length === 0"
            class="text-sm text-muted-foreground"
          >
            No users
          </div>
          <div
            v-else
            class="space-y-2"
          >
            <div
              v-for="share in workflowShares"
              :key="share.user_id"
              class="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <div>
                <div class="text-sm font-medium">
                  {{ share.name }}
                </div>
                <div class="text-xs text-muted-foreground">
                  {{ share.email }}
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                class="text-destructive"
                :loading="shareRemoving === share.user_id"
                @click="removeShare(share.user_id)"
              >
                Remove
              </Button>
            </div>
          </div>
        </div>
        <div class="space-y-2">
          <Label>Shared with teams</Label>
          <div
            v-if="shareLoading"
            class="text-sm text-muted-foreground"
          >
            Loading...
          </div>
          <div
            v-else-if="workflowTeamShares.length === 0"
            class="text-sm text-muted-foreground"
          >
            No teams
          </div>
          <div
            v-else
            class="space-y-2"
          >
            <div
              v-for="share in workflowTeamShares"
              :key="share.id"
              class="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <div class="text-sm font-medium">
                {{ share.team_name }}
              </div>
              <Button
                variant="ghost"
                size="sm"
                class="text-destructive"
                @click="removeWorkflowTeamShare(share.team_id)"
              >
                Remove
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Dialog>

    <Dialog
      :open="curlOpen"
      title="Run with cURL"
      size="2xl"
      @close="curlOpen = false"
    >
      <div class="space-y-4">
        <div class="grid grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-x-4 gap-y-3">
          <Label class="whitespace-nowrap text-sm">Request Body</Label>
          <div class="min-w-0">
            <Select
              v-model="webhookBodyMode"
              :options="[
                { value: 'legacy', label: 'Defined' },
                { value: 'generic', label: 'Generic' }
              ]"
              class="min-w-0"
            />
          </div>
          <Label class="whitespace-nowrap text-sm">Authentication</Label>
          <div class="min-w-0">
            <Select
              v-model="authType"
              :options="[
                { value: 'anonymous', label: 'Anonymous' },
                { value: 'jwt', label: 'JWT Token' },
                { value: 'header_auth', label: 'Header Auth' }
              ]"
              class="min-w-0"
            />
          </div>
        </div>
        <div
          v-if="isGenericWebhookBodyMode"
          class="text-xs text-muted-foreground bg-muted/50 p-2 rounded"
        >
          Generic mode keeps the request body as raw JSON. Input fields stay available in the canvas, but they do not reshape the webhook payload.
        </div>
        <div
          v-else
          class="text-xs text-muted-foreground bg-muted/50 p-2 rounded"
        >
          Defined mode pre-fills the request body from Input fields and keeps empty keys in the JSON payload.
        </div>
        <div
          v-if="authType === 'header_auth'"
          class="grid grid-cols-2 gap-3"
        >
          <div class="space-y-2">
            <Label>Header Key</Label>
            <Input
              v-model="authHeaderKey"
              placeholder="X-API-Key"
            />
          </div>
          <div class="space-y-2">
            <Label>Header Value</Label>
            <Input
              v-model="authHeaderValue"
              placeholder="your-secret-value"
            />
          </div>
        </div>
        <div
          v-if="authType === 'jwt'"
          class="space-y-3"
        >
          <div class="flex items-center gap-3">
            <div class="flex rounded-md border overflow-hidden text-xs">
              <button
                :class="[
                  'px-3 py-1.5 transition-colors',
                  tokenMode === 'short'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-transparent text-muted-foreground hover:bg-muted',
                ]"
                @click="tokenMode = 'short'"
              >
                Short-lived
              </button>
              <button
                :class="[
                  'px-3 py-1.5 transition-colors',
                  tokenMode === 'long'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-transparent text-muted-foreground hover:bg-muted',
                ]"
                @click="tokenMode = 'long'"
              >
                Long-lived
              </button>
            </div>
            <div
              v-if="tokenMode === 'short'"
              class="flex items-center gap-1.5 text-xs"
            >
              <Input
                v-model.number="tokenTtlSeconds"
                type="number"
                min="60"
                class="h-7 w-24 text-xs"
              />
              <span class="text-muted-foreground">seconds</span>
            </div>
            <Button
              size="sm"
              variant="outline"
              class="ml-auto text-xs h-7"
              :disabled="tokenCreating"
              @click="createExecutionToken"
            >
              {{ tokenCreating ? "Creating…" : "+ New Token" }}
            </Button>
          </div>

          <div
            v-if="executionTokens.length > 0"
            class="divide-y rounded border text-xs"
          >
            <div
              v-for="token in executionTokens"
              :key="token.id"
              :class="[
                'flex flex-col gap-1 px-3 py-2 cursor-pointer transition-colors',
                token.revoked || isTokenExpired(token.expires_at)
                  ? 'opacity-50'
                  : selectedTokenId === token.id
                    ? 'bg-muted'
                    : 'hover:bg-muted/50',
              ]"
              @click="
                !token.revoked &&
                  !isTokenExpired(token.expires_at) &&
                  (selectedTokenId = token.id)
              "
            >
              <div class="flex items-center justify-between gap-2">
                <span class="text-muted-foreground">
                  Created: {{ formatTokenDate(token.created_at) }} ·
                  <span
                    :class="
                      token.revoked
                        ? 'text-destructive'
                        : isTokenExpired(token.expires_at)
                          ? 'text-amber-500'
                          : ''
                    "
                  >
                    {{
                      token.revoked
                        ? "Revoked"
                        : isTokenExpired(token.expires_at)
                          ? "Expired"
                          : "Expires: " + formatTokenDate(token.expires_at)
                    }}
                  </span>
                </span>
                <div class="flex items-center gap-1 shrink-0">
                  <button
                    class="p-0.5 hover:text-foreground text-muted-foreground"
                    :title="tokenVisibility[token.id] ? 'Hide token' : 'Show token'"
                    @click.stop="
                      tokenVisibility[token.id] = !(tokenVisibility[token.id] ?? false)
                    "
                  >
                    <svg
                      v-if="!tokenVisibility[token.id]"
                      xmlns="http://www.w3.org/2000/svg"
                      class="h-3.5 w-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                      />
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                      />
                    </svg>
                    <svg
                      v-else
                      xmlns="http://www.w3.org/2000/svg"
                      class="h-3.5 w-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21"
                      />
                    </svg>
                  </button>
                  <button
                    v-if="!token.revoked"
                    class="p-0.5 hover:text-destructive text-muted-foreground"
                    :disabled="tokenRevoking === token.id"
                    title="Revoke token"
                    @click.stop="revokeExecutionToken(token.id)"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      class="h-3.5 w-3.5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
                      />
                    </svg>
                  </button>
                </div>
              </div>
              <div
                v-if="tokenVisibility[token.id]"
                class="font-mono text-[10px] break-all text-muted-foreground select-all"
              >
                {{ token.token }}
              </div>
            </div>
          </div>
          <p
            v-else
            class="text-xs text-muted-foreground"
          >
            No tokens yet. Create one to use in the curl command.
          </p>
        </div>
        <div
          v-if="authType === 'anonymous'"
          class="text-xs text-amber-600 bg-amber-50 dark:bg-amber-950/30 dark:text-amber-400 p-2 rounded"
        >
          Warning: This workflow can be executed by anyone without authentication.
        </div>

        <div class="border-t pt-4 space-y-3">
          <div class="space-y-2">
            <Label class="text-sm font-medium">Response Cache</Label>
            <div class="flex flex-wrap items-center gap-2">
              <Input
                v-model.number="cacheTtlMinutes"
                type="number"
                min="0"
                class="w-24"
                placeholder="0"
                @change="saveCacheSettings"
              />
              <span class="text-sm text-muted-foreground">minutes (0 = disabled)</span>
              <Button
                v-if="cacheTtlMinutes > 0"
                variant="outline"
                size="sm"
                :loading="cacheEvicting"
                @click="evictResponseCache"
              >
                <RefreshCw
                  v-if="!cacheEvicting"
                  class="w-3.5 h-3.5"
                />
                Clear cache
              </Button>
            </div>
            <p class="text-xs text-muted-foreground">
              Cache response for identical requests (same body + query params).
            </p>
            <p
              v-if="sseEnabled && cacheTtlMinutes > 0"
              class="text-xs text-amber-600 bg-amber-50 dark:bg-amber-950/30 dark:text-amber-400 p-2 rounded"
            >
              Cache is not available when SSE streaming is enabled.
            </p>
          </div>

          <div class="space-y-2">
            <Label class="text-sm font-medium">Rate Limit (429)</Label>
            <div class="flex items-center gap-2">
              <Input
                v-model.number="rateLimitRequests"
                type="number"
                min="0"
                class="w-20"
                placeholder="0"
                @change="saveRateLimitSettings"
              />
              <span class="text-sm text-muted-foreground">requests per</span>
              <Input
                v-model.number="rateLimitWindowSeconds"
                type="number"
                min="1"
                class="w-20"
                placeholder="60"
                @change="saveRateLimitSettings"
              />
              <span class="text-sm text-muted-foreground">seconds</span>
            </div>
            <p class="text-xs text-muted-foreground">
              Limit requests per IP address. Set requests to 0 to disable.
            </p>
          </div>
        </div>

        <div class="border-t pt-4 space-y-3">
          <div class="flex items-center justify-between gap-3 pr-4">
            <div>
              <Label class="text-sm font-medium">SSE Streaming</Label>
              <p class="mt-0.5 text-xs text-muted-foreground">
                Stream node events with Server-Sent Events and switch the command to
                <code class="rounded bg-muted px-1 text-xs">/execute/stream</code>.
              </p>
            </div>
            <input
              id="sse-enabled"
              type="checkbox"
              class="h-4 w-4 cursor-pointer rounded border-input bg-background"
              :checked="sseEnabled"
              @change="sseEnabled = ($event.target as HTMLInputElement).checked; saveSseEnabled()"
            >
          </div>

          <div
            v-if="sseEnabled && sseConfigurableNodes.length > 0"
            class="space-y-2"
          >
            <Label class="text-xs uppercase tracking-wide text-muted-foreground">
              Node Start Messages
            </Label>
            <div class="divide-y rounded border">
              <div
                v-for="node in sseConfigurableNodes"
                :key="node.id"
                class="flex items-center gap-2 px-3 py-2"
              >
                <input
                  type="checkbox"
                  class="h-3.5 w-3.5 shrink-0 cursor-pointer rounded border-input bg-background"
                  :checked="getNodeSseConfig(node.id).send_start"
                  @change="toggleNodeSendStart(node.id)"
                >
                <span class="min-w-[96px] truncate text-sm font-medium">
                  {{ node.data?.label || node.type }}
                </span>
                <template v-if="editingNodeId === node.id">
                  <input
                    v-model="editingNodeMessage"
                    class="flex-1 rounded border bg-background px-2 py-0.5 font-mono text-xs"
                    :placeholder="getNodeStartMessagePlaceholder(node.data?.label || node.type)"
                    @keydown.enter.prevent="commitNodeMessage(node.id)"
                    @keydown.escape.prevent="cancelEditingNodeMessage()"
                    @blur="commitNodeMessage(node.id)"
                  >
                </template>
                <template v-else>
                  <span class="flex-1 truncate font-mono text-xs text-muted-foreground">
                    {{
                      getNodeSseConfig(node.id).start_message ||
                        getNodeStartMessagePlaceholder(node.data?.label || node.type)
                    }}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-6 w-6 shrink-0"
                    :disabled="!getNodeSseConfig(node.id).send_start"
                    @click="startEditingNodeMessage(node.id)"
                  >
                    <Pencil class="h-3 w-3" />
                  </Button>
                </template>
              </div>
            </div>
          </div>
        </div>

        <div class="border-t pt-4">
          <div class="flex items-center justify-between gap-3 pr-4">
            <div>
              <Label class="text-sm font-medium">Simple Response</Label>
              <p class="mt-0.5 text-xs text-muted-foreground">
                Return only the final <code class="rounded bg-muted px-1 text-xs">outputs</code> object. Uncheck for the full response with status, node results, and metadata.
              </p>
            </div>
            <input
              id="simple-response"
              type="checkbox"
              class="h-4 w-4 cursor-pointer rounded border-input bg-background"
              :checked="simpleResponse"
              @change="simpleResponse = ($event.target as HTMLInputElement).checked"
            >
          </div>
        </div>

        <div class="space-y-2">
          <div class="flex items-center justify-between gap-3">
            <Label>{{ isGenericWebhookBodyMode ? "Raw JSON Body" : "Defined Request Body" }}</Label>
            <Button
              variant="ghost"
              size="sm"
              :disabled="!!curlBodyError"
              @click="formatCurlJson"
            >
              Format JSON
            </Button>
          </div>
          <Textarea
            v-model="curlInput"
            class="font-mono text-sm"
            :rows="6"
          />
          <p
            v-if="curlBodyError"
            class="text-xs text-red-500"
          >
            {{ curlBodyError }}
          </p>
        </div>
        <div class="space-y-2">
          <div class="flex items-center justify-between gap-3">
            <Label>Command</Label>
            <Button
              variant="outline"
              size="sm"
              class="gap-2"
              :disabled="!!curlBodyError"
              @click="copyCurlCommand"
            >
              <Copy class="w-4 h-4" />
              {{ curlCopied ? "Copied!" : "Copy cURL" }}
            </Button>
          </div>
          <Textarea
            :model-value="curlCommand"
            class="font-mono text-xs"
            :rows="6"
            readonly
          />
        </div>
      </div>
    </Dialog>

    <div
      v-if="loading"
      class="flex-1 flex items-center justify-center"
    >
      <div class="animate-pulse text-muted-foreground">
        Loading workflow...
      </div>
    </div>

    <div
      v-else
      class="flex-1 flex overflow-hidden overflow-x-hidden"
    >
      <NodePanel v-show="leftPanelOpen && !analysisPanelOpen" />
      <AnalysisPanel
        v-if="analysisPanelOpen"
        :workflow-id="analysisWorkflowId"
        :current-workflow="analysisWorkflowPayload"
        :run-workflow="runWorkflowForAnalysis"
      />

      <div class="flex-1 flex flex-col min-h-0 min-w-0">
        <div class="flex-1 relative min-h-0 min-w-0">
          <button
            class="panel-toggle panel-toggle-left absolute top-1/2 -translate-y-1/2 z-30 w-5 h-12 rounded-r-lg flex items-center justify-center transition-all left-0"
            @click.stop="leftPanelOpen = !leftPanelOpen"
          >
            <ChevronLeft
              v-if="leftPanelOpen"
              class="w-4 h-4"
            />
            <ChevronRight
              v-else
              class="w-4 h-4"
            />
          </button>

          <WorkflowCanvas />

          <button
            class="panel-toggle panel-toggle-right absolute top-1/2 -translate-y-1/2 z-30 w-5 h-12 rounded-l-lg flex items-center justify-center transition-all pointer-events-auto right-0"
            @click.stop.prevent="toggleRightPanel"
          >
            <ChevronRight
              v-if="rightPanelOpen"
              class="w-4 h-4"
            />
            <ChevronLeft
              v-else
              class="w-4 h-4"
            />
          </button>
        </div>
        <DebugPanel />
      </div>

      <PropertiesPanel v-if="rightPanelOpen" />
    </div>

    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showValidationDialog"
          class="fixed inset-0 z-50 flex items-center justify-center"
        >
          <div
            class="absolute inset-0 bg-black/50 backdrop-blur-sm"
            @click="closeValidationDialog"
          />
          <div class="relative bg-card border rounded-lg shadow-xl w-[90vw] max-w-[400px] max-h-[80vh] overflow-hidden overflow-x-hidden">
            <div class="flex items-center justify-between p-4 border-b bg-destructive/10">
              <div class="flex items-center gap-2">
                <AlertTriangle class="w-5 h-5 text-destructive" />
                <h3 class="font-semibold text-destructive">
                  Configuration Required
                </h3>
              </div>
              <button
                class="p-1 rounded hover:bg-muted transition-colors"
                @click="closeValidationDialog"
              >
                <X class="w-4 h-4" />
              </button>
            </div>
            <div class="p-4">
              <p class="text-sm text-muted-foreground mb-4">
                Please fix the following issues before running the workflow:
              </p>
              <div class="space-y-2 max-h-[300px] overflow-y-auto">
                <div
                  v-for="error in validationErrors"
                  :key="`${error.nodeId}-${error.message}`"
                  class="flex items-start gap-3 p-3 rounded-md bg-muted/50 hover:bg-muted cursor-pointer transition-colors"
                  @click="selectNodeFromError(error.nodeId)"
                >
                  <XCircle class="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="font-medium text-sm">{{ error.nodeLabel }}</span>
                      <span class="text-xs px-1.5 py-0.5 rounded bg-muted-foreground/20 text-muted-foreground">
                        {{ error.nodeType }}
                      </span>
                    </div>
                    <p class="text-xs text-muted-foreground mt-0.5">
                      {{ error.message }}
                    </p>
                  </div>
                </div>
              </div>
            </div>
            <div class="p-4 border-t bg-muted/30">
              <Button
                variant="outline"
                class="w-full"
                @click="closeValidationDialog"
              >
                Close
              </Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <ExpressionEvaluateFallbackDialog />

    <WorkflowCommandPalette
      :open="showCommandPalette"
      :workflows="paletteWorkflows"
      context="editor"
      :hide-templates="isDashboardWidget"
      :hide-runbook="isDashboardWidget"
      @select="openWorkflowFromPalette"
      @tab-select="handleTabSelectFromPalette"
      @doc-select="onDocSelectFromPalette"
      @runbook="handleRunbookFromPalette"
      @close="showCommandPalette = false"
    />

    <!-- Share as Template modal -->
    <ShareTemplateModal
      v-if="shareTemplateOpen && isStandardWorkflow"
      kind="workflow"
      :nodes="(workflowStore.currentWorkflow?.nodes ?? []) as Record<string, unknown>[]"
      :edges="(workflowStore.currentWorkflow?.edges ?? []) as Record<string, unknown>[]"
      @close="shareTemplateOpen = false"
      @shared="shareTemplateOpen = false"
    />

    <ContextualShowcase
      :context="showcaseContext"
      :show-desktop-trigger="false"
      :show-mobile-trigger="false"
    />

    <RunbookCursor />
  </div>
</template>

<style scoped>
.editor-header {
  background: hsl(var(--background) / 0.9);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.editor-header::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg,
      transparent 0%,
      hsl(var(--border) / 0.6) 30%,
      hsl(var(--border) / 0.6) 70%,
      transparent 100%);
}

.panel-toggle {
  background: hsl(var(--card) / 0.95);
  backdrop-filter: blur(12px);
  border: 1px solid hsl(var(--border) / 0.4);
  color: hsl(var(--muted-foreground));
  transition: all 0.2s cubic-bezier(0.22, 1, 0.36, 1);
  transform-origin: center;
}

.panel-toggle:hover {
  background: hsl(var(--primary) / 0.08);
  border-color: hsl(var(--primary) / 0.25);
  color: hsl(var(--primary));
}

.panel-toggle-left {
  border-left: none;
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
  box-shadow: 2px 0 8px hsl(0 0% 0% / 0.06);
}

.panel-toggle-right {
  border-right: none;
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
  box-shadow: -2px 0 8px hsl(0 0% 0% / 0.06);
  pointer-events: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
