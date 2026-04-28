<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  watch,
  type ComponentPublicInstance,
} from "vue";
import { useRouter } from "vue-router";
import { AlertTriangle, Ban, BookOpen, Bot, Braces, Brain, Bug, CalendarClock, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, Clock, Copy, Database, Download, ExternalLink, FileArchive, FileJson, GitBranch, GitMerge, Globe, HardDrive, Inbox, Loader2, Mail, Maximize2, MessageSquare, Minus, Minimize2, MonitorPlay, MousePointerClick, Play, Plus, Power, Rabbit, Radio, Repeat, Search, Send, Server, Settings, Settings2, Sheet, ShieldAlert, Shuffle, Sparkles, StickyNote, Table2, Terminal, Trash2, Type, Variable, X, XCircle, Zap } from "lucide-vue-next";

import type { CredentialListItem, LLMModel } from "@/types/credential";
import type {
  AgentMCPConnection,
  AgentSkill,
  AgentSkillFile,
  ExecuteInputMapping,
  GuardrailCategory,
  InputField,
  MappingField,
  MCPTransportType,
  OutputSchemaField,
  PlaywrightStep,
  PlaywrightStepAction,
  ReasoningEffort,
} from "@/types/workflow";
import { createAgentSkillZipBlob, getSkillZipFileName, parseSkillZip } from "@/lib/skillZipParser";

import SelectorPickerDialog from "@/components/Dialogs/SelectorPickerDialog.vue";
import SkillBuilderModal from "@/components/Panels/SkillBuilderModal.vue";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import JsonTree from "@/components/ui/JsonTree.vue";
import GoogleSheetsValuesInputPanel from "@/components/ui/GoogleSheetsValuesInputPanel.vue";
import JsonInputPanel from "@/components/ui/JsonInputPanel.vue";
import { isRetryAttemptNodeResult } from "@/lib/executionLog";
import {
  findEnclosingLoopIdForListSize,
  findNodeResultIndexForLoopIteration,
  mapNodeResultsToEnclosingLoopIterations,
  selectedLoopIterationIndexForNode,
} from "@/lib/loopNodeDisplay";
import { parseWebhookJson, stringifyWebhookJson } from "@/lib/webhookBody";
import { cn } from "@/lib/utils";
import { configApi, credentialsApi, dataTablesApi, filesApi, gristApi, mcpApi, workflowApi } from "@/services/api";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { useToast } from "@/composables/useToast";
import type { DataTableListItem } from "@/types/dataTable";
import type { GeneratedFile } from "@/types/file";
import { useAuthStore } from "@/stores/auth";
import { useWorkflowStore, type ValidationError } from "@/stores/workflow";

import type { NodeType } from "@/types/workflow";
import type { WebSocketTriggerEventName } from "@/types/workflow";

const nodeIcons: Record<NodeType, ReturnType<typeof Type>> = {
  textInput: Type,
  cron: CalendarClock,
  websocketTrigger: Radio,
  llm: Brain,
  agent: Bot,
  condition: GitBranch,
  switch: Shuffle,
  execute: Play,
  output: FileJson,
  wait: Clock,
  http: Globe,
  websocketSend: Send,
  sticky: StickyNote,
  merge: GitMerge,
  set: Settings2,
  jsonOutputMapper: Braces,
  telegramTrigger: MessageSquare,
  telegram: MessageSquare,
  slack: MessageSquare,
  slackTrigger: MessageSquare,
  imapTrigger: Inbox,
  sendEmail: Mail,
  errorHandler: AlertTriangle,
  variable: Variable,
  loop: Repeat,
  disableNode: Ban,
  redis: Database,
  rag: Search,
  grist: Table2,
  googleSheets: Sheet,
  bigquery: Database,
  throwError: XCircle,
  rabbitmq: Rabbit,
  crawler: Bug,
  consoleLog: Terminal,
  playwright: MonitorPlay,
  dataTable: Table2,
  drive: HardDrive,
};

const nodeColorMap: Record<NodeType, string> = {
  textInput: "node-input",
  cron: "node-cron",
  websocketTrigger: "node-websocket",
  llm: "node-llm",
  agent: "node-agent",
  condition: "node-condition",
  switch: "node-switch",
  execute: "node-execute",
  output: "node-output",
  wait: "node-wait",
  http: "node-http",
  websocketSend: "node-websocket",
  sticky: "node-sticky",
  merge: "node-merge",
  set: "node-set",
  jsonOutputMapper: "node-output",
  telegramTrigger: "node-telegram",
  telegram: "node-telegram",
  slack: "node-slack",
  slackTrigger: "node-slack",
  imapTrigger: "node-email",
  sendEmail: "node-email",
  errorHandler: "node-error",
  variable: "node-variable",
  loop: "node-loop",
  disableNode: "node-disable",
  redis: "node-redis",
  rag: "node-rag",
  grist: "node-grist",
  googleSheets: "node-google-sheets",
  bigquery: "node-google-sheets",
  throwError: "node-throw-error",
  rabbitmq: "node-rabbitmq",
  crawler: "node-crawler",
  consoleLog: "node-console-log",
  playwright: "node-playwright",
  dataTable: "node-datatable",
  drive: "node-drive",
};

const nodeDocSlugMap: Record<NodeType, string> = {
  textInput: "input-node",
  cron: "cron-node",
  websocketTrigger: "websocket-trigger-node",
  llm: "llm-node",
  agent: "agent-node",
  condition: "condition-node",
  switch: "switch-node",
  execute: "execute-node",
  output: "output-node",
  wait: "wait-node",
  http: "http-node",
  websocketSend: "websocket-send-node",
  sticky: "sticky-note-node",
  merge: "merge-node",
  set: "set-node",
  jsonOutputMapper: "json-output-mapper-node",
  telegramTrigger: "telegram-trigger-node",
  telegram: "telegram-node",
  slack: "slack-node",
  slackTrigger: "slack-trigger-node",
  imapTrigger: "imap-trigger-node",
  sendEmail: "send-email-node",
  errorHandler: "error-handler-node",
  variable: "variable-node",
  loop: "loop-node",
  disableNode: "disable-node",
  redis: "redis-node",
  rag: "rag-node",
  grist: "grist-node",
  googleSheets: "google-sheets-node",
  bigquery: "bigquery-node",
  throwError: "throw-error-node",
  rabbitmq: "rabbitmq-node",
  crawler: "crawler-node",
  consoleLog: "console-log-node",
  playwright: "playwright-node",
  dataTable: "datatable-node",
  drive: "drive-node",
};

const workflowStore = useWorkflowStore();
const router = useRouter();
const authStore = useAuthStore();
const { showToast } = useToast();

/** False when viewing another user's shared workflow (not owner). Used for model suffix labels. */
const isWorkflowOwner = computed(
  () =>
    !workflowStore.currentWorkflow ||
    workflowStore.currentWorkflow.owner_id === authStore.user?.id,
);

const activeTab = computed({
  get: () => workflowStore.propertiesPanelTab,
  set: (value: "properties" | "config") => { workflowStore.propertiesPanelTab = value; }
});
const runInputValues = computed(() => workflowStore.runInputValues);
const runInputJson = computed(() => workflowStore.runInputJson);
const allInputFields = computed(() => workflowStore.allInputFields);
const isGenericWebhookBodyMode = computed(() => workflowStore.webhookBodyMode === "generic");

const slackTriggerWebhookUrl = computed((): string => {
  if (!selectedNode.value || selectedNode.value.type !== "slackTrigger") return "";
  return `${window.location.origin}/api/slack/webhook/${selectedNode.value.id}`;
});

const telegramTriggerWebhookUrl = computed((): string => {
  if (!selectedNode.value || selectedNode.value.type !== "telegramTrigger") return "";
  return `${window.location.origin}/api/telegram/webhook/${selectedNode.value.id}`;
});

function copySlackWebhookUrl(): void {
  navigator.clipboard.writeText(slackTriggerWebhookUrl.value);
}

function copyTelegramWebhookUrl(): void {
  navigator.clipboard.writeText(telegramTriggerWebhookUrl.value);
}
const runBodyError = computed(() => {
  if (!isGenericWebhookBodyMode.value) return null;
  return parseWebhookJson(workflowStore.runInputJson).error;
});
const genericBodyPlaceholder = `{
  "event": {
    "user": {
      "id": "123"
    }
  }
}`;

function updateRunInputJson(value: string): void {
  workflowStore.runInputJson = value;
}

function updateInputValue(key: string, value: string): void {
  workflowStore.runInputValues[key] = value;
}

function formatRunInputJson(): void {
  if (runBodyError.value) return;
  workflowStore.runInputJson = stringifyWebhookJson(
    workflowStore.buildExecutionRequestBody(),
  );
}
const labelError = ref("");
const copied = ref(false);
const copiedOutput = ref(false);
/** Full-screen expand for Config tab run / "Last Executed Node" output. */
const isOutputExpanded = ref(false);
const runOutputJsonTreeKey = ref(0);
const runOutputJsonAutoDepth = ref(1);
const runOutputExpandedPanelRef = ref<HTMLElement | null>(null);

function resetRunOutputJsonTreeState(): void {
  runOutputJsonAutoDepth.value = 1;
  runOutputJsonTreeKey.value += 1;
}

function expandAllRunOutputJson(): void {
  runOutputJsonAutoDepth.value = 512;
  runOutputJsonTreeKey.value += 1;
}

function collapseAllRunOutputJson(): void {
  runOutputJsonAutoDepth.value = 0;
  runOutputJsonTreeKey.value += 1;
}

/** Full-screen expand for Properties tab "Last Output" JSON block. */
const isLastOutputExpanded = ref(false);
const lastOutputJsonTreeKey = ref(0);
const lastOutputJsonAutoDepth = ref(1);

function resetLastOutputJsonTreeState(): void {
  lastOutputJsonAutoDepth.value = 1;
  lastOutputJsonTreeKey.value += 1;
}

function expandAllLastOutputJson(): void {
  lastOutputJsonAutoDepth.value = 512;
  lastOutputJsonTreeKey.value += 1;
}

function collapseAllLastOutputJson(): void {
  lastOutputJsonAutoDepth.value = 0;
  lastOutputJsonTreeKey.value += 1;
}
const workflowOptions = ref<{ value: string; label: string }[]>([]);
const subWorkflowSearch = ref("");
const filteredWorkflowOptionsForSubWorkflows = computed(() => {
  const q = subWorkflowSearch.value.trim().toLowerCase();
  const filtered = q
    ? workflowOptions.value.filter(
      (opt) => opt.label.toLowerCase().includes(q) || opt.value.toLowerCase().includes(q)
    )
    : workflowOptions.value;
  const selectedIds = selectedNode.value?.data?.subWorkflowIds || [];
  if (selectedIds.length === 0) return filtered;
  const byId = new Map(filtered.map((o) => [o.value, o]));
  const selected = selectedIds.map((id) => byId.get(id)).filter(Boolean) as { value: string; label: string }[];
  const unselected = filtered.filter((o) => !selectedIds.includes(o.value));
  return [...selected, ...unselected];
});
const isEditingPinnedData = ref(false);
const editedPinnedData = ref("");
const outputMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const outputSchemaValueInputRefs = ref<Map<number, InstanceType<typeof ExpressionInput>>>(new Map());
const currentOutputExpressionFieldIndex = ref(0);
const httpCurlInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const websocketSendUrlInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const websocketSendHeadersInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const websocketSendMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const userMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const telegramChatIdInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const telegramMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const slackMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const sendEmailBodyInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const conditionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const redisKeyInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const setMappingInputRefs = ref<Map<number, InstanceType<typeof ExpressionInput>>>(new Map());
const currentSetMappingIndex = ref(0);
const executeMappingInputRefs = ref<Map<number, InstanceType<typeof ExpressionInput>>>(new Map());
const currentExecuteMappingIndex = ref(0);

/** When set to the newly selected node id, skip closing evaluate dialogs (graph Prev/Next reopens immediately). */
const suppressCloseExpandDialogsForNavigationId = ref<string | null>(null);
const llmSystemInstructionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const llmImageExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentLlmExpressionFieldIndex = ref(0);
const agentSystemInstructionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const agentImageExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentAgentExpressionFieldIndex = ref(0);
const variableValueInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const throwErrorMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);

const llmCredentials = ref<CredentialListItem[]>([]);
const llmModels = ref<LLMModel[]>([]);
const guardrailModels = ref<LLMModel[]>([]);
const fallbackModels = ref<LLMModel[]>([]);
const loadingModels = ref(false);
const loadingGuardrailModels = ref(false);
const loadingFallbackModels = ref(false);
const jsonFormatError = ref(false);
const telegramCredentials = ref<CredentialListItem[]>([]);
const slackCredentials = ref<CredentialListItem[]>([]);
const slackTriggerCredentials = ref<CredentialListItem[]>([]);
const imapTriggerCredentials = ref<CredentialListItem[]>([]);
const smtpCredentials = ref<CredentialListItem[]>([]);
const redisCredentials = ref<CredentialListItem[]>([]);
const gristCredentials = ref<CredentialListItem[]>([]);
const googleSheetsCredentials = ref<CredentialListItem[]>([]);
const bigqueryCredentials = ref<CredentialListItem[]>([]);
const rabbitmqCredentials = ref<CredentialListItem[]>([]);
const cohereCredentials = ref<CredentialListItem[]>([]);
const crawlerCredentials = ref<CredentialListItem[]>([]);
const dataTables = ref<DataTableListItem[]>([]);
const driveFiles = ref<GeneratedFile[]>([]);

const driveFileOptions = computed(() => {
  const options: { value: string; label: string }[] = [{ value: "", label: "Select file..." }];
  for (const f of driveFiles.value) {
    options.push({ value: f.id, label: f.filename });
  }
  return options;
});
const dataTableColumns = ref<import("@/types/dataTable").DataTableColumn[]>([]);
const dataTableSelectiveValues = ref<Record<string, string>>({});
const dataTableSelectiveExpressionInputRefs = ref<
  Map<string, InstanceType<typeof ExpressionInput>>
>(new Map());
const gristColumns = ref<{ id: string; name: string; type: string }[]>([]);
const vectorStores = ref<{ id: string; name: string }[]>([]);
const ragQueryInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const ragDocumentInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const rabbitmqExchangeInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const rabbitmqRoutingKeyInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const rabbitmqQueueNameInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const rabbitmqMessageBodyInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentRabbitmqSendExpressionFieldIndex = ref(0);
const websocketTriggerEventOptions: Array<{
  value: WebSocketTriggerEventName;
  label: string;
  description: string;
}> = [
  {
    value: "onMessage",
    label: "onMessage",
    description: "Fire when a text or binary frame arrives from the remote socket.",
  },
  {
    value: "onConnected",
    label: "onConnected",
    description: "Fire after the socket opens and report whether it is a reconnect.",
  },
  {
    value: "onClosed",
    label: "onClosed",
    description: "Fire when an established connection closes and include close metadata.",
  },
];
const crawlerUrlInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const consoleLogMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const switchExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const loopArrayExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const executeTemplateExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gristDocIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gristTableIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gristRecordIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gristRecordIdsExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gristRecordsDataExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gristSortExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const gristRecordDataJsonInputRef = ref<InstanceType<typeof JsonInputPanel> | null>(null);
const gristFilterJsonInputRef = ref<InstanceType<typeof JsonInputPanel> | null>(null);
const currentGristExpressionFieldIndex = ref(0);
const googleSheetsSpreadsheetIdExpressionInputRef = ref<InstanceType<
  typeof ExpressionInput
> | null>(null);
const googleSheetsSheetNameExpressionInputRef = ref<InstanceType<
  typeof ExpressionInput
> | null>(null);
const googleSheetsValuesInputRef = ref<InstanceType<
  typeof GoogleSheetsValuesInputPanel
> | null>(null);
const currentGoogleSheetsExpressionFieldIndex = ref(0);
const bqProjectIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const bqQueryExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const bqDatasetIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const bqTableIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const bqRowsExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const bqMappingInputRefs = ref<Map<number, InstanceType<typeof ExpressionInput>>>(new Map());
const currentBigQueryExpressionFieldIndex = ref(0);
const dataTableRowIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const dataTableDataExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const dataTableFilterExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const dataTableSortExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentDataTableExpressionFieldIndex = ref(0);
const driveFileIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const drivePasswordExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentDriveExpressionFieldIndex = ref(0);
const currentPlaywrightExpressionFieldIndex = ref(0);
/** ExpressionInput instances keyed by stable slot id (survives action changes / unmount). */
const playwrightExprRefsBySlotKey = ref<Record<string, InstanceType<typeof ExpressionInput> | null>>({});
const validationErrors = ref<ValidationError[]>([]);
const showValidationDialog = ref(false);

type PlaywrightStepListKey = "playwrightSteps" | "playwrightAuthFallbackSteps";

type PlaywrightExprNavSlotField = "url" | "selector" | "typeFill" | "instructions";

interface PlaywrightExprNavSlot {
  kind: "authState" | "authSelector" | "stepField";
  stepListKey?: PlaywrightStepListKey;
  stepIndex?: number;
  field?: PlaywrightExprNavSlotField;
}

const selectorPickerOpen = ref(false);
const expandedSavedStepKey = ref<string | null>(null);
const selectorPickerTarget = ref<
  | { type: "playwright"; stepIndex: number; stepListKey: PlaywrightStepListKey }
  | { type: "crawler"; selectorIndex: number }
  | null
>(null);

const selectorPickerInitialUrl = computed((): string => {
  const node = workflowStore.selectedNode;
  if (!node) return "";
  const target = selectorPickerTarget.value;
  if (!target) return "";
  if (target.type === "playwright") {
    const steps = ((node.data[target.stepListKey] || []) as PlaywrightStep[]);
    const nav = steps.find((s) => s.action === "navigate");
    if (nav?.url) return String(nav.url);
    const mainSteps = (node.data.playwrightSteps || []) as PlaywrightStep[];
    const mainNav = mainSteps.find((s) => s.action === "navigate");
    return String(mainNav?.url ?? "");
  }
  if (target.type === "crawler") {
    return String(node.data.crawlerUrl ?? "");
  }
  return "";
});

function openSelectorPickerPlaywright(
  stepIndex: number,
  stepListKey: PlaywrightStepListKey = "playwrightSteps",
): void {
  selectorPickerTarget.value = { type: "playwright", stepIndex, stepListKey };
  selectorPickerOpen.value = true;
}

function openSelectorPickerCrawler(selectorIndex: number): void {
  selectorPickerTarget.value = { type: "crawler", selectorIndex };
  selectorPickerOpen.value = true;
}

function onSelectorPicked(selector: string): void {
  const target = selectorPickerTarget.value;
  if (!target) return;
  if (target.type === "playwright") {
    updatePlaywrightStep(target.stepListKey, target.stepIndex, "selector", selector);
  } else if (target.type === "crawler") {
    updateCrawlerSelector(target.selectorIndex, "selector", selector);
  }
  selectorPickerTarget.value = null;
}

async function loadWorkflowOptions(): Promise<void> {
  try {
    const workflows = await workflowApi.list();
    const currentId = workflowStore.currentWorkflow?.id;
    workflowOptions.value = workflows
      .filter((workflow) => workflow.id !== currentId)
      .map((workflow) => ({
        value: workflow.id,
        label: workflow.name,
      }));
    const selectedNode = workflowStore.selectedNode;
    if (
      selectedNode?.type === "execute" &&
      selectedNode.data.executeWorkflowId &&
      !workflowOptions.value.some((option) => option.value === selectedNode.data.executeWorkflowId)
    ) {
      updateNodeData("executeWorkflowId", "");
      updateNodeData("targetWorkflowInputFields", []);
      updateNodeData("targetWorkflowName", "");
      updateNodeData("executeInputMappings", []);
    }
    // Sync subWorkflowNames for agent nodes that have IDs but no names (e.g. from migrated DB)
    const node = workflowStore.selectedNode;
    if (node?.type === "agent" && node.data.subWorkflowIds?.length) {
      const ids = node.data.subWorkflowIds;
      const names = node.data.subWorkflowNames || {};
      const opts = new Map(workflowOptions.value.map((o) => [o.value, o.label]));
      const filteredIds = ids.filter((id) => opts.has(id));
      if (filteredIds.length !== ids.length) {
        const nextNames = Object.fromEntries(
          filteredIds.map((id) => [id, names[id] || opts.get(id) || ""]),
        );
        updateNodeData("subWorkflowIds", filteredIds);
        updateNodeData("subWorkflowNames", nextNames);
        return;
      }
      let needsSync = false;
      const next: Record<string, string> = { ...names };
      for (const id of ids) {
        if (!next[id] && opts.has(id)) {
          next[id] = opts.get(id)!;
          needsSync = true;
        }
      }
      if (needsSync) {
        updateNodeData("subWorkflowNames", next);
      }
    }
  } catch {
    workflowOptions.value = [];
  }
}

watch(
  () => workflowStore.selectedNode?.type,
  async (type) => {
    if (type !== "agent") subWorkflowSearch.value = "";
    if (type === "execute" || type === "agent") {
      await loadWorkflowOptions();
    }

    if (type === "llm" || type === "agent" || type === "playwright") {
      try {
        llmCredentials.value = await credentialsApi.listLLM();
      } catch {
        llmCredentials.value = [];
      }
      if (type === "playwright") {
        const steps = workflowStore.selectedNode?.data?.playwrightSteps || [];
        for (const step of steps) {
          if (step.action === "aiStep" && step.credentialId) {
            loadPlaywrightAiStepModels(step.credentialId);
          }
        }
      }
    }

    if (type === "slack") {
      try {
        slackCredentials.value = await credentialsApi.listByType("slack");
      } catch {
        slackCredentials.value = [];
      }
    }

    if (type === "telegram" || type === "telegramTrigger") {
      try {
        telegramCredentials.value = await credentialsApi.listByType("telegram");
      } catch {
        telegramCredentials.value = [];
      }
    }

    if (type === "drive") {
      if (!workflowStore.selectedNode?.data.driveOperation) {
        updateNodeData("driveOperation", "get");
      }
      try {
        const res = await filesApi.list({ limit: 200 });
        driveFiles.value = res.files;
      } catch {
        driveFiles.value = [];
      }
    }

    if (type === "sendEmail") {
      try {
        smtpCredentials.value = await credentialsApi.listByType("smtp");
      } catch {
        smtpCredentials.value = [];
      }
    }

    if (type === "redis") {
      try {
        redisCredentials.value = await credentialsApi.listByType("redis");
      } catch {
        redisCredentials.value = [];
      }
    }

    if (type === "rag") {
      try {
        const { vectorStoresApi } = await import("@/services/api");
        const stores = await vectorStoresApi.list();
        vectorStores.value = stores.map((s) => ({ id: s.id, name: s.name }));
      } catch {
        vectorStores.value = [];
      }
      try {
        cohereCredentials.value = await credentialsApi.listByType("cohere");
      } catch {
        cohereCredentials.value = [];
      }
    }

    if (type === "grist") {
      try {
        gristCredentials.value = await credentialsApi.listByType("grist");
      } catch {
        gristCredentials.value = [];
      }
    }

    if (type === "googleSheets") {
      try {
        googleSheetsCredentials.value = await credentialsApi.listByType("google_sheets");
      } catch {
        googleSheetsCredentials.value = [];
      }
    }

    if (type === "bigquery") {
      try {
        bigqueryCredentials.value = await credentialsApi.listByType("bigquery");
      } catch {
        bigqueryCredentials.value = [];
      }
    }

    if (type === "rabbitmq") {
      try {
        rabbitmqCredentials.value = await credentialsApi.listByType("rabbitmq");
      } catch {
        rabbitmqCredentials.value = [];
      }
    }

    if (type === "crawler") {
      try {
        crawlerCredentials.value = await credentialsApi.listByType("flaresolverr");
      } catch {
        crawlerCredentials.value = [];
      }
    }

    if (type === "slackTrigger") {
      try {
        slackTriggerCredentials.value = await credentialsApi.listByType("slack_trigger");
      } catch {
        slackTriggerCredentials.value = [];
      }
    }

    if (type === "imapTrigger") {
      try {
        imapTriggerCredentials.value = await credentialsApi.listByType("imap");
      } catch {
        imapTriggerCredentials.value = [];
      }
    }

    if (type === "dataTable") {
      try {
        dataTables.value = await dataTablesApi.list();
      } catch {
        dataTables.value = [];
      }
      await loadDataTableColumnsForSelectedNode();
      syncDataTableSelectiveUiFromNodeMode();
    }
  },
  { immediate: true }
);

watch(
  () => workflowStore.selectedNode?.id,
  async () => {
    if (workflowStore.selectedNode?.type !== "dataTable") {
      return;
    }
    await loadDataTableColumnsForSelectedNode();
    syncDataTableSelectiveUiFromNodeMode();
  },
);

watch(
  () => workflowStore.selectedNode?.id,
  async () => {
    if (
      workflowStore.selectedNode?.type === "execute" ||
      workflowStore.selectedNode?.type === "agent"
    ) {
      if (workflowOptions.value.length === 0) await loadWorkflowOptions();
    }
  }
);

watch(
  () => workflowStore.nodes.length,
  async () => {
    if (
      workflowStore.selectedNode?.type === "execute" ||
      workflowStore.selectedNode?.type === "agent"
    ) {
      await loadWorkflowOptions();
    }
  }
);

async function fetchGristColumns(): Promise<void> {
  const node = workflowStore.selectedNode;
  if (!node || node.type !== "grist") return;

  const docId = node.data.gristDocId;
  const tableId = node.data.gristTableId;

  if (!docId || !tableId) {
    gristColumns.value = [];
    return;
  }

  try {
    const columns = await gristApi.getColumns(docId, tableId);
    gristColumns.value = columns;
  } catch {
    gristColumns.value = [];
  }
}

watch(
  () => [
    workflowStore.selectedNode?.data.gristDocId,
    workflowStore.selectedNode?.data.gristTableId,
  ],
  () => {
    fetchGristColumns();
  },
  { immediate: true },
);

const targetWorkflowInputFields = ref<{ key: string; defaultValue?: string }[]>([]);
const loadingTargetInputs = ref(false);

function areInputFieldsEqual(left: InputField[] | undefined, right: InputField[]): boolean {
  if (!left || left.length !== right.length) return false;

  return left.every((field, index) => {
    const other = right[index];
    return field.key === other?.key && field.defaultValue === other?.defaultValue;
  });
}

function areExecuteInputMappingsEqual(
  left: ExecuteInputMapping[] | undefined,
  right: ExecuteInputMapping[],
): boolean {
  if (!left || left.length !== right.length) return false;

  return left.every((mapping, index) => {
    const other = right[index];
    return mapping.key === other?.key && mapping.value === other?.value;
  });
}

const executeWorkflowId = computed(() => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "execute") return null;
  return node.data.executeWorkflowId || null;
});

watch(
  executeWorkflowId,
  async (workflowId) => {
    const selectedNode = workflowStore.selectedNode;

    if (!workflowId) {
      targetWorkflowInputFields.value = [];
      return;
    }

    if (selectedNode?.type === "execute") {
      targetWorkflowInputFields.value = selectedNode.data.targetWorkflowInputFields || [];
    }

    const selectedNodeId = selectedNode?.id;
    loadingTargetInputs.value = true;
    try {
      const result = await workflowApi.getInputFields(workflowId);
      targetWorkflowInputFields.value = result.inputFields;
      const currentNode = workflowStore.selectedNode;
      if (
        !currentNode ||
        currentNode.id !== selectedNodeId ||
        currentNode.type !== "execute" ||
        currentNode.data.executeWorkflowId !== workflowId
      ) {
        return;
      }

      if (!areInputFieldsEqual(currentNode.data.targetWorkflowInputFields, result.inputFields)) {
        updateNodeData("targetWorkflowInputFields", result.inputFields);
      }

      if (currentNode.data.targetWorkflowName !== result.name) {
        updateNodeData("targetWorkflowName", result.name);
      }

      const existingMappings = currentNode.data.executeInputMappings || [];
      const existingByKey = new Map(existingMappings.map((mapping) => [mapping.key, mapping.value]));
      const syncedMappings = result.inputFields.map((field) => ({
        key: field.key,
        value: existingByKey.get(field.key) || `$input.${field.key}`,
      }));

      if (!areExecuteInputMappingsEqual(currentNode.data.executeInputMappings, syncedMappings)) {
        updateNodeData("executeInputMappings", syncedMappings);
      }
    } catch {
      const currentNode = workflowStore.selectedNode;
      if (
        currentNode?.type === "execute" &&
        currentNode.data.executeWorkflowId === workflowId
      ) {
        targetWorkflowInputFields.value = currentNode.data.targetWorkflowInputFields || [];
      } else {
        targetWorkflowInputFields.value = [];
      }
    } finally {
      loadingTargetInputs.value = false;
    }
  },
  { immediate: true }
);

const llmCredentialId = computed(() => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "llm" && node?.type !== "agent") return null;
  return node.data.credentialId || null;
});

watch(
  llmCredentialId,
  async (credentialId) => {
    if (!credentialId) {
      llmModels.value = [];
      return;
    }
    loadingModels.value = true;
    try {
      llmModels.value = await credentialsApi.getModels(credentialId);
    } catch {
      llmModels.value = [];
    } finally {
      loadingModels.value = false;
    }
  },
  { immediate: true }
);

const guardrailCredentialId = computed(() => {
  const node = workflowStore.selectedNode;
  if (!node || (node.type !== "llm" && node.type !== "agent")) return null;
  if (!node.data.guardrailsEnabled) return null;
  return (node.data.guardrailCredentialId as string | undefined) || null;
});

watch(
  guardrailCredentialId,
  async (credentialId) => {
    if (!credentialId) {
      guardrailModels.value = [];
      return;
    }
    loadingGuardrailModels.value = true;
    try {
      guardrailModels.value = await credentialsApi.getModels(credentialId);
    } catch {
      guardrailModels.value = [];
    } finally {
      loadingGuardrailModels.value = false;
    }
  },
  { immediate: true }
);

const guardrailCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && (node.type === "llm" || node.type === "agent")
      ? (node.data.guardrailCredentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    llmCredentials.value,
    selectedCredentialId,
    "Select credential...",
    "Credential not available (re-select)",
  );
});

const guardrailModelOptions = computed(() => {
  const node = selectedNode.value;
  const selectedModelId =
    node && (node.type === "llm" || node.type === "agent")
      ? (node.data.guardrailModel as string | undefined)
      : undefined;
  const credentialId = guardrailCredentialId.value;
  const showSharedByOwner =
    !isWorkflowOwner.value && credentialId;
  const suffix = showSharedByOwner ? " (shared by owner)" : "";

  if (guardrailModels.value.length === 0) {
    if (selectedModelId) {
      return [
        { value: "", label: "Select model..." },
        { value: selectedModelId, label: `${selectedModelId}${suffix}` },
      ];
    }
    return [{ value: "", label: "Select credential first" }];
  }

  const options = guardrailModels.value.map((m) => ({
    value: m.id,
    label: `${m.is_reasoning ? `${m.name} (Reasoning)` : m.name}${suffix}`,
  }));

  if (
    selectedModelId &&
    !guardrailModels.value.some((m) => m.id === selectedModelId) &&
    !options.some((opt) => opt.value === selectedModelId)
  ) {
    options.push({ value: selectedModelId, label: `${selectedModelId}${suffix}` });
  }

  return options;
});

function handleGuardrailCredentialChange(credentialId: string | undefined): void {
  updateNodeData("guardrailCredentialId", credentialId || "");
  updateNodeData("guardrailModel", "");
}

function handleGuardrailModelChange(model: string | undefined): void {
  updateNodeData("guardrailModel", model || "");
}

const fallbackCredentialId = computed(() => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "llm" && node?.type !== "agent") return null;
  return (node.data.fallbackCredentialId as string | undefined) || null;
});

watch(
  fallbackCredentialId,
  async (credentialId) => {
    if (!credentialId) {
      fallbackModels.value = [];
      return;
    }
    loadingFallbackModels.value = true;
    try {
      fallbackModels.value = await credentialsApi.getModels(credentialId);
    } catch {
      fallbackModels.value = [];
    } finally {
      loadingFallbackModels.value = false;
    }
  },
  { immediate: true }
);

const fallbackCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && (node.type === "llm" || node.type === "agent")
      ? (node.data.fallbackCredentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    llmCredentials.value,
    selectedCredentialId,
    "None (no fallback)",
    "Credential not available (re-select)",
  );
});

const fallbackModelOptions = computed(() => {
  const node = selectedNode.value;
  const selectedModelId =
    node && (node.type === "llm" || node.type === "agent")
      ? (node.data.fallbackModel as string | undefined)
      : undefined;
  const credentialId = fallbackCredentialId.value;
  const showSharedByOwner = !isWorkflowOwner.value && credentialId;
  const suffix = showSharedByOwner ? " (shared by owner)" : "";

  if (fallbackModels.value.length === 0) {
    if (selectedModelId) {
      return [
        { value: "", label: "Select model..." },
        { value: selectedModelId, label: `${selectedModelId}${suffix}` },
      ];
    }
    return [{ value: "", label: "Select fallback credential first" }];
  }

  const options: { value: string; label: string }[] = [
    { value: "", label: "Select model..." },
    ...fallbackModels.value.map((m) => ({
      value: m.id,
      label: `${m.is_reasoning ? `${m.name} (Reasoning)` : m.name}${suffix}`,
    })),
  ];

  if (
    selectedModelId &&
    !fallbackModels.value.some((m) => m.id === selectedModelId) &&
    !options.some((opt) => opt.value === selectedModelId)
  ) {
    options.push({ value: selectedModelId, label: `${selectedModelId}${suffix}` });
  }

  return options;
});

function handleFallbackCredentialChange(credentialId: string | undefined): void {
  updateNodeData("fallbackCredentialId", credentialId || "");
  updateNodeData("fallbackModel", "");
}

function handleFallbackModelChange(model: string | undefined): void {
  updateNodeData("fallbackModel", model || "");
}

const selectedNode = computed(() => workflowStore.selectedNode);

const selectedNodeEvaluateDialogLabel = computed((): string => {
  const node = selectedNode.value;
  if (!node) {
    return "";
  }
  const raw = node.data.label;
  const trimmed = typeof raw === "string" ? raw.trim() : "";
  return trimmed.length > 0 ? trimmed : node.type;
});

const isExecuting = computed(() => workflowStore.isExecuting);
const hasNodes = computed(() => workflowStore.nodes.length > 0);

const lastExecutedNode = computed(() => {
  const results = workflowStore.nodeResults;
  if (!results || results.length === 0) return null;
  return results[results.length - 1];
});

const previousNode = computed(() => {
  if (!selectedNode.value) return null;
  const incomingEdge = workflowStore.edges.find(
    (e) => e.target === selectedNode.value?.id
  );
  if (!incomingEdge) return null;
  return workflowStore.nodes.find((n) => n.id === incomingEdge.source) || null;
});

const previousNodeLabel = computed(() => {
  return previousNode.value?.data.label || "input";
});

const exampleRef = computed(() => {
  const isTextInput = !previousNode.value || previousNode.value.type === "textInput";
  const bodyPart = isTextInput ? ".body" : "";
  return `$${previousNodeLabel.value}${bodyPart}.text`;
});

const nodeOutput = computed(() => {
  if (!selectedNode.value) return null;
  const id = selectedNode.value.id;
  const all = workflowStore.nodeResults;
  const pick = workflowStore.timelinePickedNodeResultIndex;
  if (
    pick !== null &&
    pick >= 0 &&
    pick < all.length &&
    all[pick].node_id === id
  ) {
    return all[pick];
  }
  const streamed = all.filter((r) => r.node_id === id);
  if (streamed.length > 0) {
    return streamed[streamed.length - 1] ?? null;
  }
  const snapshot = workflowStore.executionResult?.node_results;
  if (!snapshot?.length) return null;
  const fromSnapshot = snapshot.filter((r) => r.node_id === id);
  return fromSnapshot.length > 0 ? (fromSnapshot[fromSnapshot.length - 1] ?? null) : null;
});

interface SelectedNodeLoopItemNavigationState {
  currentDisplayIndex: number;
  totalDisplayCount: number;
  currentResultPosition: number;
  resultIndexes: number[];
  canNavigatePrev: boolean;
  canNavigateNext: boolean;
}

const selectedNodeLoopItemNavigation = computed(
  (): SelectedNodeLoopItemNavigationState | null => {
    const node = selectedNode.value;
    const nodeResults = workflowStore.nodeResults;
    if (!node || nodeResults.length === 0) {
      return null;
    }

    const mapped = mapNodeResultsToEnclosingLoopIterations(
      node.id,
      workflowStore.nodes,
      workflowStore.edges,
      nodeResults,
    );
    if (!mapped) {
      return null;
    }

    const resultIndexes: number[] = [];
    const iterationIndexes: Array<number | null> = [];
    mapped.resultIndexes.forEach((resultIndex, index) => {
      const row = nodeResults[resultIndex];
      if (!row || isRetryAttemptNodeResult(row)) {
        return;
      }
      resultIndexes.push(resultIndex);
      iterationIndexes.push(mapped.iterationIndexes[index] ?? null);
    });

    if (resultIndexes.length <= 1) {
      return null;
    }

    const pickedResultIndex = workflowStore.timelinePickedNodeResultIndex;
    let currentResultPosition = resultIndexes.length - 1;
    if (pickedResultIndex !== null) {
      const matchedPosition = resultIndexes.indexOf(pickedResultIndex);
      if (matchedPosition >= 0) {
        currentResultPosition = matchedPosition;
      }
    }

    const totalDisplayCount =
      mapped.total !== null && mapped.total > 0 ? mapped.total : resultIndexes.length;
    const currentIterationIndex = iterationIndexes[currentResultPosition];
    const currentDisplayIndex =
      currentIterationIndex !== null && currentIterationIndex >= 0
        ? currentIterationIndex + 1
        : currentResultPosition + 1;

    return {
      currentDisplayIndex,
      totalDisplayCount,
      currentResultPosition,
      resultIndexes,
      canNavigatePrev: currentResultPosition > 0,
      canNavigateNext: currentResultPosition < resultIndexes.length - 1,
    };
  },
);

function navigateSelectedNodeLoopItem(direction: "prev" | "next"): void {
  const state = selectedNodeLoopItemNavigation.value;
  if (!state) {
    return;
  }

  const nextPosition =
    direction === "prev"
      ? state.currentResultPosition - 1
      : state.currentResultPosition + 1;
  if (nextPosition < 0 || nextPosition >= state.resultIndexes.length) {
    return;
  }

  workflowStore.setTimelinePickedNodeResultIndex(state.resultIndexes[nextPosition]);
}

function navigateToPreviousSelectedNodeLoopItem(): void {
  navigateSelectedNodeLoopItem("prev");
}

function navigateToNextSelectedNodeLoopItem(): void {
  navigateSelectedNodeLoopItem("next");
}

watch(nodeOutput, (v) => {
  if (!v) {
    isLastOutputExpanded.value = false;
  }
});

watch(
  () => workflowStore.selectedNodeId,
  () => {
    isLastOutputExpanded.value = false;
  },
);

const lastOutputExpandedPanelRef = ref<HTMLElement | null>(null);

watch(isLastOutputExpanded, async (open) => {
  if (open) {
    resetLastOutputJsonTreeState();
    await nextTick();
    lastOutputExpandedPanelRef.value?.focus({ preventScroll: true });
  }
});

watch(isOutputExpanded, async (open) => {
  if (open) {
    resetRunOutputJsonTreeState();
    await nextTick();
    runOutputExpandedPanelRef.value?.focus({ preventScroll: true });
  }
});

watch(isExecuting, (executing) => {
  if (executing) {
    isOutputExpanded.value = false;
  }
});

const httpLastRequest = computed(() => {
  if (!selectedNode.value || selectedNode.value.type !== "http") return null;
  if (!nodeOutput.value || nodeOutput.value.status !== "success") return null;
  const output = nodeOutput.value.output as {
    status?: number;
    headers?: Record<string, string>;
    body?: unknown;
    request?: {
      method?: string;
      url?: string;
      headers?: Record<string, string>;
    };
  };
  if (!output || typeof output.status !== "number") return null;
  const requestInfo = output.request || {};
  return {
    status: output.status,
    method: requestInfo.method || "GET",
    url: requestInfo.url || "",
    requestHeaders: requestInfo.headers || {},
  };
});

const pinnedData = computed(() => {
  if (!selectedNode.value) return null;
  return selectedNode.value.data.pinnedData || null;
});

const isNodeActive = computed(() => {
  if (!selectedNode.value) return true;
  return selectedNode.value.data.active !== false;
});

const availableTargetNodes = computed(() => {
  if (!selectedNode.value) return [];
  return workflowStore.nodes
    .filter((node) => node.id !== selectedNode.value?.id && node.type !== "sticky")
    .map((node) => ({
      value: node.data.label,
      label: `${node.data.label} (${node.type})`,
    }));
});

function toggleActive(): void {
  if (!selectedNode.value) return;
  workflowStore.toggleNodeActive(selectedNode.value.id);
}

function closeAllExpressionExpandDialogs(): void {
  workflowStore.closeExpressionEvaluateFallbackDialog();
  for (const input of setMappingInputRefs.value.values()) {
    input.closeExpandDialog();
  }
  for (const input of executeMappingInputRefs.value.values()) {
    input.closeExpandDialog();
  }
  outputMessageInputRef.value?.closeExpandDialog();
  for (const input of outputSchemaValueInputRefs.value.values()) {
    input.closeExpandDialog();
  }
  httpCurlInputRef.value?.closeExpandDialog();
  websocketSendUrlInputRef.value?.closeExpandDialog();
  websocketSendHeadersInputRef.value?.closeExpandDialog();
  websocketSendMessageInputRef.value?.closeExpandDialog();
  userMessageInputRef.value?.closeExpandDialog();
  telegramChatIdInputRef.value?.closeExpandDialog();
  telegramMessageInputRef.value?.closeExpandDialog();
  slackMessageInputRef.value?.closeExpandDialog();
  sendEmailBodyInputRef.value?.closeExpandDialog();
  conditionInputRef.value?.closeExpandDialog();
  redisKeyInputRef.value?.closeExpandDialog();
  variableValueInputRef.value?.closeExpandDialog();
  throwErrorMessageInputRef.value?.closeExpandDialog();
  ragQueryInputRef.value?.closeExpandDialog();
  ragDocumentInputRef.value?.closeExpandDialog();
  rabbitmqExchangeInputRef.value?.closeExpandDialog();
  rabbitmqRoutingKeyInputRef.value?.closeExpandDialog();
  rabbitmqQueueNameInputRef.value?.closeExpandDialog();
  rabbitmqMessageBodyInputRef.value?.closeExpandDialog();
  crawlerUrlInputRef.value?.closeExpandDialog();
  consoleLogMessageInputRef.value?.closeExpandDialog();
  switchExpressionInputRef.value?.closeExpandDialog();
  loopArrayExpressionInputRef.value?.closeExpandDialog();
  executeTemplateExpressionInputRef.value?.closeExpandDialog();
  gristDocIdExpressionInputRef.value?.closeExpandDialog();
  gristTableIdExpressionInputRef.value?.closeExpandDialog();
  gristRecordIdExpressionInputRef.value?.closeExpandDialog();
  gristRecordIdsExpressionInputRef.value?.closeExpandDialog();
  gristRecordsDataExpressionInputRef.value?.closeExpandDialog();
  gristSortExpressionInputRef.value?.closeExpandDialog();
  gristRecordDataJsonInputRef.value?.closeExpandDialog();
  gristFilterJsonInputRef.value?.closeExpandDialog();
  dataTableRowIdExpressionInputRef.value?.closeExpandDialog();
  dataTableDataExpressionInputRef.value?.closeExpandDialog();
  dataTableFilterExpressionInputRef.value?.closeExpandDialog();
  dataTableSortExpressionInputRef.value?.closeExpandDialog();
  for (const inst of dataTableSelectiveExpressionInputRefs.value.values()) {
    inst.closeExpandDialog();
  }
  driveFileIdExpressionInputRef.value?.closeExpandDialog();
  drivePasswordExpressionInputRef.value?.closeExpandDialog();
  closeAllPlaywrightExpressionDialogs();
  llmSystemInstructionInputRef.value?.closeExpandDialog();
  llmImageExpressionInputRef.value?.closeExpandDialog();
  agentSystemInstructionInputRef.value?.closeExpandDialog();
  agentImageExpressionInputRef.value?.closeExpandDialog();
  googleSheetsSpreadsheetIdExpressionInputRef.value?.closeExpandDialog();
  googleSheetsSheetNameExpressionInputRef.value?.closeExpandDialog();
  googleSheetsValuesInputRef.value?.closeExpandDialog();
  closeBigQueryExpressionDialogs();
}

/** Opens the primary expression evaluate dialog for whichever node is currently selected. */
function openPrimaryExpandDialogForSelectedNode(): void {
  workflowStore.closeExpressionEvaluateFallbackDialog();
  const nodeType = workflowStore.selectedNode?.type;
  if (nodeType === "output") {
    currentOutputExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) {
        return;
      }
      const n = workflowStore.selectedNode;
      if (!n || n.type !== "output") {
        return;
      }
      const schemaLen = (n.data.outputSchema || []).length;
      if (schemaLen > 0) {
        if (outputSchemaValueInputRefs.value.get(0)) {
          nextTick(() => openOutputExpressionFieldAtIndex(0));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      } else if (outputMessageInputRef.value) {
        nextTick(() => openOutputExpressionFieldAtIndex(0));
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "http") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (httpCurlInputRef.value) {
        nextTick(() => httpCurlInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "websocketSend") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (websocketSendMessageInputRef.value) {
        nextTick(() => websocketSendMessageInputRef.value?.openExpandDialog());
      } else if (websocketSendUrlInputRef.value) {
        nextTick(() => websocketSendUrlInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "llm") {
    currentLlmExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      const n = workflowStore.selectedNode;
      if (!n || n.type !== "llm") {
        return;
      }
      const imageMode = n.data.outputType === "image";
      const ready = imageMode
        ? !!userMessageInputRef.value
        : !!llmSystemInstructionInputRef.value;
      if (ready) {
        nextTick(() => openLlmExpressionFieldAtIndex(0));
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "agent") {
    currentAgentExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (agentSystemInstructionInputRef.value) {
        nextTick(() => openAgentExpressionFieldAtIndex(0));
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "telegram") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (telegramMessageInputRef.value) {
        nextTick(() => telegramMessageInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "slack") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (slackMessageInputRef.value) {
        nextTick(() => slackMessageInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "sendEmail") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (sendEmailBodyInputRef.value) {
        nextTick(() => sendEmailBodyInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "condition") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (conditionInputRef.value) {
        nextTick(() => conditionInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "set" || nodeType === "jsonOutputMapper") {
    currentSetMappingIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      const inputRef = setMappingInputRefs.value.get(0);
      if (inputRef) {
        nextTick(() => inputRef.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "execute") {
    currentExecuteMappingIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      const inputRef = executeMappingInputRefs.value.get(0);
      if (inputRef) {
        nextTick(() => inputRef.openExpandDialog());
      } else if (executeTemplateExpressionInputRef.value) {
        nextTick(() => executeTemplateExpressionInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "variable") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (variableValueInputRef.value) {
        nextTick(() => variableValueInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "redis") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (redisKeyInputRef.value) {
        nextTick(() => redisKeyInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "rag") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      const n = workflowStore.selectedNode;
      if (!n || n.type !== "rag") {
        return;
      }
      const op = (n.data.ragOperation as string | undefined) || "";
      const focusField = workflowStore.focusField;
      if (focusField === "documentContent" && ragDocumentInputRef.value) {
        nextTick(() => ragDocumentInputRef.value?.openExpandDialog());
      } else if (focusField === "queryText" && ragQueryInputRef.value) {
        nextTick(() => ragQueryInputRef.value?.openExpandDialog());
      } else if (op === "insert" && ragDocumentInputRef.value) {
        nextTick(() => ragDocumentInputRef.value?.openExpandDialog());
      } else if (op === "search" && ragQueryInputRef.value) {
        nextTick(() => ragQueryInputRef.value?.openExpandDialog());
      } else if (ragQueryInputRef.value) {
        nextTick(() => ragQueryInputRef.value?.openExpandDialog());
      } else if (ragDocumentInputRef.value) {
        nextTick(() => ragDocumentInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "throwError") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (throwErrorMessageInputRef.value) {
        nextTick(() => throwErrorMessageInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "crawler") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (crawlerUrlInputRef.value) {
        nextTick(() => crawlerUrlInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "consoleLog") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (consoleLogMessageInputRef.value) {
        nextTick(() => consoleLogMessageInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "switch") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (switchExpressionInputRef.value) {
        nextTick(() => switchExpressionInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "loop") {
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (loopArrayExpressionInputRef.value) {
        nextTick(() => loopArrayExpressionInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "rabbitmq") {
    currentRabbitmqSendExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      const n = workflowStore.selectedNode;
      if (!n || n.type !== "rabbitmq") {
        return;
      }
      const op = (n.data.rabbitmqOperation as string | undefined) || "";
      if (op === "send") {
        if (rabbitmqExchangeInputRef.value) {
          nextTick(() => rabbitmqExchangeInputRef.value?.openExpandDialog());
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      } else if (op === "receive") {
        if (rabbitmqQueueNameInputRef.value) {
          nextTick(() => rabbitmqQueueNameInputRef.value?.openExpandDialog());
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      } else if (rabbitmqExchangeInputRef.value) {
        nextTick(() => rabbitmqExchangeInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "grist") {
    currentGristExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (gristDocIdExpressionInputRef.value) {
        nextTick(() => gristDocIdExpressionInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "dataTable") {
    currentDataTableExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      const n = workflowStore.selectedNode;
      if (!n || n.type !== "dataTable") {
        return;
      }
      const op = (n.data.dataTableOperation as string | undefined) || "";
      const rawData = (n.data.dataTableInputMode || "raw") === "raw";
      const rowDataOps = ["insert", "update", "upsert"];
      const firstCol = dataTableColumns.value[0];
      const firstSelectiveRef = firstCol
        ? dataTableSelectiveExpressionInputRefs.value.get(firstCol.name)
        : undefined;

      if (["getById", "update", "remove"].includes(op) && dataTableRowIdExpressionInputRef.value) {
        nextTick(() => openDataTableExpressionFieldAtIndex(0));
        return;
      }
      if (rowDataOps.includes(op) && !rawData && dataTableColumns.value.length > 0) {
        if (firstSelectiveRef) {
          nextTick(() => openDataTableExpressionFieldAtIndex(0));
          return;
        }
      } else if (rowDataOps.includes(op) && rawData && dataTableDataExpressionInputRef.value) {
        nextTick(() => openDataTableExpressionFieldAtIndex(0));
        return;
      } else if (op === "find" && dataTableFilterExpressionInputRef.value) {
        nextTick(() => openDataTableExpressionFieldAtIndex(0));
        return;
      } else if (op === "getAll" && dataTableSortExpressionInputRef.value) {
        nextTick(() => openDataTableExpressionFieldAtIndex(0));
        return;
      }

      if (dataTableDataExpressionInputRef.value) {
        nextTick(() => openDataTableExpressionFieldAtIndex(0));
      } else if (dataTableRowIdExpressionInputRef.value) {
        nextTick(() => openDataTableExpressionFieldAtIndex(0));
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "googleSheets") {
    currentGoogleSheetsExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) {
        return;
      }
      if (googleSheetsSpreadsheetIdExpressionInputRef.value) {
        nextTick(() => openGoogleSheetsExpressionFieldAtIndex(0));
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "bigquery") {
    currentBigQueryExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (bqProjectIdExpressionInputRef.value) {
        nextTick(() => openBigQueryExpressionFieldAtIndex(0));
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "drive") {
    currentDriveExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) return;
      if (driveFileIdExpressionInputRef.value) {
        nextTick(() => driveFileIdExpressionInputRef.value?.openExpandDialog());
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  } else if (nodeType === "playwright") {
    currentPlaywrightExpressionFieldIndex.value = 0;
    const tryOpenDialog = (attempts = 0): void => {
      if (attempts > 20) {
        return;
      }
      const n = workflowStore.selectedNode;
      if (!n || n.type !== "playwright") {
        return;
      }
      const total = playwrightExpressionNavPlan.value.total;
      if (total === 0) {
        return;
      }
      const firstSlot = playwrightExpressionNavPlan.value.slots[0];
      const firstKey = firstSlot ? playwrightExprSlotKeyFromSlot(firstSlot) : "";
      if (firstKey && playwrightExprRefsBySlotKey.value[firstKey]) {
        nextTick(() => openPlaywrightExpressionFieldAtIndex(0));
      } else {
        setTimeout(() => tryOpenDialog(attempts + 1), 100);
      }
    };
    nextTick(() => tryOpenDialog());
  }
}

/** True when the properties panel can open an ExpressionInput evaluate dialog for the current node. */
function selectedNodeHasPrimaryEvaluateExpandTarget(): boolean {
  const n = workflowStore.selectedNode;
  if (!n) {
    return false;
  }
  switch (n.type) {
    case "set":
    case "jsonOutputMapper":
      return true;
    case "output":
    case "http":
    case "websocketSend":
    case "llm":
    case "agent":
    case "slack":
    case "sendEmail":
    case "condition":
    case "execute": {
      const wfId =
        typeof n.data.executeWorkflowId === "string" ? n.data.executeWorkflowId.trim() : "";
      if (!wfId) {
        return true;
      }
      const persistedFieldCount = (n.data.targetWorkflowInputFields || []).length;
      const persistedMappingCount = (n.data.executeInputMappings || []).length;
      if (persistedFieldCount > 0 || persistedMappingCount > 0) {
        return true;
      }
      if (loadingTargetInputs.value) {
        return false;
      }
      return targetWorkflowInputFields.value.length > 0;
    }
    case "variable":
    case "redis":
    case "rag":
    case "throwError":
    case "crawler":
    case "consoleLog":
    case "switch":
    case "loop":
    case "grist":
    case "googleSheets":
    case "bigquery":
    case "dataTable":
    case "drive":
    case "rabbitmq":
      return true;
    case "playwright":
      return playwrightExpressionNavPlan.value.total > 0;
    default:
      return false;
  }
}

function handleExpressionWorkflowNodeNavigate(payload: { targetNodeId: string }): void {
  const id = payload.targetNodeId.trim();
  if (!id) {
    return;
  }
  const loopNodeIdForNode = (nodeId: string | null): string | null => {
    if (!nodeId) {
      return null;
    }
    const node = workflowStore.nodes.find((item) => item.id === nodeId);
    if (!node) {
      return null;
    }
    if (node.type === "loop") {
      return nodeId;
    }
    return findEnclosingLoopIdForListSize(
      nodeId,
      workflowStore.nodes,
      workflowStore.edges,
    );
  };
  const currentSelectedNodeId = workflowStore.selectedNode?.id ?? null;
  const currentLoopNodeId = loopNodeIdForNode(currentSelectedNodeId);
  const targetLoopNodeId = loopNodeIdForNode(id);
  const desiredIterationIndexFromTimeline = selectedLoopIterationIndexForNode(
    currentSelectedNodeId,
    workflowStore.timelinePickedNodeResultIndex,
    workflowStore.nodes,
    workflowStore.edges,
    workflowStore.nodeResults,
  );
  const storedLoopSelection = workflowStore.evaluateLoopSelection;
  const desiredIterationIndex =
    desiredIterationIndexFromTimeline ??
    (storedLoopSelection &&
    currentLoopNodeId &&
    targetLoopNodeId === currentLoopNodeId &&
    storedLoopSelection.loopNodeId === currentLoopNodeId
      ? storedLoopSelection.iterationIndex
      : null);
  suppressCloseExpandDialogsForNavigationId.value = id;
  activeTab.value = "properties";
  workflowStore.setSuppressVueFlowSelectionEcho(true);
  workflowStore.selectNode(id);
  if (desiredIterationIndex !== null) {
    if (targetLoopNodeId) {
      workflowStore.setEvaluateLoopSelection({
        loopNodeId: targetLoopNodeId,
        iterationIndex: desiredIterationIndex,
      });
    }
    workflowStore.setTimelinePickedNodeResultIndex(
      findNodeResultIndexForLoopIteration(
        id,
        desiredIterationIndex,
        workflowStore.nodes,
        workflowStore.edges,
        workflowStore.nodeResults,
      ),
    );
  } else {
    workflowStore.setTimelinePickedNodeResultIndex(null);
  }
  nextTick(() => {
    requestAnimationFrame(() => {
      const n = workflowStore.selectedNode;
      if (n && selectedNodeHasPrimaryEvaluateExpandTarget()) {
        openPrimaryExpandDialogForSelectedNode();
      } else if (n) {
        workflowStore.openExpressionEvaluateFallbackDialog(n.id);
      } else {
        workflowStore.closeExpressionEvaluateFallbackDialog();
      }
      suppressCloseExpandDialogsForNavigationId.value = null;
      nextTick(() => {
        workflowStore.setSuppressVueFlowSelectionEcho(false);
      });
    });
  });
}

workflowStore.setExpressionGraphNavigateHandler(handleExpressionWorkflowNodeNavigate);

function openLlmExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "llm") {
    return;
  }
  currentLlmExpressionFieldIndex.value = index;
  if (isImageOutputMode.value) {
    if (index === 0) {
      userMessageInputRef.value?.openExpandDialog();
    } else if (index === 1 && n.data.imageInputEnabled) {
      llmImageExpressionInputRef.value?.openExpandDialog();
    }
    return;
  }
  if (index === 0) {
    llmSystemInstructionInputRef.value?.openExpandDialog();
  } else if (index === 1) {
    userMessageInputRef.value?.openExpandDialog();
  } else if (index === 2 && n.data.imageInputEnabled) {
    llmImageExpressionInputRef.value?.openExpandDialog();
  }
}

function handleLlmExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "llm") {
    return;
  }
  const total = llmExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentLlmExpressionFieldIndex.value - 1
      : currentLlmExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  llmSystemInstructionInputRef.value?.closeExpandDialog();
  userMessageInputRef.value?.closeExpandDialog();
  llmImageExpressionInputRef.value?.closeExpandDialog();
  currentLlmExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openLlmExpressionFieldAtIndex(newIndex);
  });
}

function openAgentExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "agent") {
    return;
  }
  currentAgentExpressionFieldIndex.value = index;
  if (index === 0) {
    agentSystemInstructionInputRef.value?.openExpandDialog();
  } else if (index === 1) {
    userMessageInputRef.value?.openExpandDialog();
  } else if (index === 2 && n.data.imageInputEnabled) {
    agentImageExpressionInputRef.value?.openExpandDialog();
  }
}

function handleAgentExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "agent") {
    return;
  }
  const total = agentExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentAgentExpressionFieldIndex.value - 1
      : currentAgentExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  agentSystemInstructionInputRef.value?.closeExpandDialog();
  userMessageInputRef.value?.closeExpandDialog();
  agentImageExpressionInputRef.value?.closeExpandDialog();
  currentAgentExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openAgentExpressionFieldAtIndex(newIndex);
  });
}

watch(
  () => workflowStore.selectedNode?.id,
  (newId) => {
    if (!(newId && suppressCloseExpandDialogsForNavigationId.value === newId)) {
      closeAllExpressionExpandDialogs();
    }
    cancelEditingPinnedData();
    currentLlmExpressionFieldIndex.value = 0;
    currentAgentExpressionFieldIndex.value = 0;
    currentSetMappingIndex.value = 0;
    currentExecuteMappingIndex.value = 0;
    currentGristExpressionFieldIndex.value = 0;
    currentGoogleSheetsExpressionFieldIndex.value = 0;
    currentBigQueryExpressionFieldIndex.value = 0;
    currentRabbitmqSendExpressionFieldIndex.value = 0;
    currentDataTableExpressionFieldIndex.value = 0;
    currentDriveExpressionFieldIndex.value = 0;
    currentPlaywrightExpressionFieldIndex.value = 0;
    playwrightExprRefsBySlotKey.value = {};
    currentOutputExpressionFieldIndex.value = 0;
  },
);

function onLlmRegisterExpressionFieldIndex(index: number): void {
  currentLlmExpressionFieldIndex.value = index;
}

function onAgentRegisterExpressionFieldIndex(index: number): void {
  currentAgentExpressionFieldIndex.value = index;
}

const gristExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "grist") {
    return 1;
  }
  const op = (n.data.gristOperation as string | undefined) || "";
  const recordRaw = (n.data.gristRecordDataInputMode || "raw") === "raw";
  const filterRaw = (n.data.gristFilterInputMode || "raw") === "raw";
  const ncol = gristColumns.value.length;
  const selectiveRecordSlots = 1 + ncol;
  const selectiveFilterSlots = 1 + ncol;

  if (!op || op === "listTables") {
    return 1;
  }
  if (op === "listColumns") {
    return 2;
  }
  if (op === "getRecord") {
    return 3;
  }
  if (op === "updateRecord") {
    return recordRaw ? 4 : 3 + selectiveRecordSlots;
  }
  if (op === "createRecord") {
    return recordRaw ? 3 : 2 + selectiveRecordSlots;
  }
  if (op === "createRecords" || op === "updateRecords") {
    return 3;
  }
  if (op === "deleteRecord") {
    return 4;
  }
  if (op === "getRecords") {
    return filterRaw ? 4 : 2 + selectiveFilterSlots + 1;
  }
  return 1;
});

function openGristExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "grist") {
    return;
  }
  currentGristExpressionFieldIndex.value = index;
  const op = (n.data.gristOperation as string | undefined) || "";

  if (!op || op === "listTables") {
    gristDocIdExpressionInputRef.value?.openExpandDialog();
    return;
  }
  if (op === "listColumns") {
    if (index === 0) {
      gristDocIdExpressionInputRef.value?.openExpandDialog();
    } else {
      gristTableIdExpressionInputRef.value?.openExpandDialog();
    }
    return;
  }
  if (op === "getRecord") {
    if (index === 0) {
      gristDocIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 1) {
      gristTableIdExpressionInputRef.value?.openExpandDialog();
    } else {
      gristRecordIdExpressionInputRef.value?.openExpandDialog();
    }
    return;
  }
  if (op === "updateRecord") {
    const rawRec = (n.data.gristRecordDataInputMode || "raw") === "raw";
    if (index === 0) {
      gristDocIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 1) {
      gristTableIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 2) {
      gristRecordIdExpressionInputRef.value?.openExpandDialog();
    } else if (rawRec && index === 3) {
      gristRecordDataJsonInputRef.value?.openExpandDialog();
    } else if (!rawRec && index >= 3) {
      gristRecordDataJsonInputRef.value?.openExpandDialog(index - 3);
    }
    return;
  }
  if (op === "createRecord") {
    const rawRec = (n.data.gristRecordDataInputMode || "raw") === "raw";
    if (index === 0) {
      gristDocIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 1) {
      gristTableIdExpressionInputRef.value?.openExpandDialog();
    } else if (rawRec && index === 2) {
      gristRecordDataJsonInputRef.value?.openExpandDialog();
    } else if (!rawRec && index >= 2) {
      gristRecordDataJsonInputRef.value?.openExpandDialog(index - 2);
    }
    return;
  }
  if (op === "createRecords" || op === "updateRecords") {
    if (index === 0) {
      gristDocIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 1) {
      gristTableIdExpressionInputRef.value?.openExpandDialog();
    } else {
      gristRecordsDataExpressionInputRef.value?.openExpandDialog();
    }
    return;
  }
  if (op === "deleteRecord") {
    if (index === 0) {
      gristDocIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 1) {
      gristTableIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 2) {
      gristRecordIdExpressionInputRef.value?.openExpandDialog();
    } else {
      gristRecordIdsExpressionInputRef.value?.openExpandDialog();
    }
    return;
  }
  if (op === "getRecords") {
    const rawFilter = (n.data.gristFilterInputMode || "raw") === "raw";
    const ncol = gristColumns.value.length;
    if (index === 0) {
      gristDocIdExpressionInputRef.value?.openExpandDialog();
    } else if (index === 1) {
      gristTableIdExpressionInputRef.value?.openExpandDialog();
    } else if (rawFilter) {
      if (index === 2) {
        gristFilterJsonInputRef.value?.openExpandDialog();
      } else if (index === 3) {
        gristSortExpressionInputRef.value?.openExpandDialog();
      }
    } else {
      const filterEnd = 2 + (1 + ncol);
      if (index >= 2 && index < filterEnd) {
        gristFilterJsonInputRef.value?.openExpandDialog(index - 2);
      } else if (index === filterEnd) {
        gristSortExpressionInputRef.value?.openExpandDialog();
      }
    }
    return;
  }
  gristDocIdExpressionInputRef.value?.openExpandDialog();
}

function handleGristExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "grist") {
    return;
  }
  const total = gristExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentGristExpressionFieldIndex.value - 1
      : currentGristExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  gristDocIdExpressionInputRef.value?.closeExpandDialog();
  gristTableIdExpressionInputRef.value?.closeExpandDialog();
  gristRecordIdExpressionInputRef.value?.closeExpandDialog();
  gristRecordIdsExpressionInputRef.value?.closeExpandDialog();
  gristRecordsDataExpressionInputRef.value?.closeExpandDialog();
  gristSortExpressionInputRef.value?.closeExpandDialog();
  gristRecordDataJsonInputRef.value?.closeExpandDialog();
  gristFilterJsonInputRef.value?.closeExpandDialog();
  currentGristExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openGristExpressionFieldAtIndex(newIndex);
  });
}

function onGristRegisterExpressionFieldIndex(index: number): void {
  currentGristExpressionFieldIndex.value = index;
}

const googleSheetsExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "googleSheets") {
    return 1;
  }
  const op = (n.data.gsOperation as string | undefined) || "";
  if (!op) {
    return 1;
  }
  if (op === "getSheetInfo") {
    return 1;
  }
  if (op === "readRange" || op === "clearRange") {
    return 2;
  }
  if (op === "appendRows" || op === "updateRange") {
    const raw = (n.data.gsValuesInputMode || "raw") === "raw";
    if (raw) {
      return 3;
    }
    const cols = parseInt(n.data.gsValuesSelectiveCols || "1", 10) || 1;
    return 2 + cols;
  }
  return 2;
});

function openGoogleSheetsExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "googleSheets") {
    return;
  }
  currentGoogleSheetsExpressionFieldIndex.value = index;
  const op = (n.data.gsOperation as string | undefined) || "";
  if (index === 0) {
    googleSheetsSpreadsheetIdExpressionInputRef.value?.openExpandDialog();
    return;
  }
  if (index === 1 && op !== "getSheetInfo") {
    googleSheetsSheetNameExpressionInputRef.value?.openExpandDialog();
    return;
  }
  if (index >= 2 && (op === "appendRows" || op === "updateRange")) {
    googleSheetsValuesInputRef.value?.openExpandDialog(index - 2);
  }
}

function handleGoogleSheetsExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "googleSheets") {
    return;
  }
  const total = googleSheetsExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentGoogleSheetsExpressionFieldIndex.value - 1
      : currentGoogleSheetsExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  googleSheetsSpreadsheetIdExpressionInputRef.value?.closeExpandDialog();
  googleSheetsSheetNameExpressionInputRef.value?.closeExpandDialog();
  googleSheetsValuesInputRef.value?.closeExpandDialog();
  currentGoogleSheetsExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openGoogleSheetsExpressionFieldAtIndex(newIndex);
  });
}

function onGoogleSheetsRegisterExpressionFieldIndex(index: number): void {
  currentGoogleSheetsExpressionFieldIndex.value = index;
}

const bigQueryExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "bigquery") return 1;
  const op = (n.data.bqOperation as string | undefined) || "";
  if (!op) return 1;
  if (op === "query") return 2; // projectId + query
  // insertRows: projectId + datasetId + tableId + rows/mappings
  const mode = (n.data.bqRowsInputMode as string | undefined) || "raw";
  if (mode === "selective") {
    return 3 + ((n.data.bqMappings as unknown[]) || []).length;
  }
  return 4; // projectId + datasetId + tableId + rows JSON
});

function openBigQueryExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "bigquery") return;
  currentBigQueryExpressionFieldIndex.value = index;
  const op = (n.data.bqOperation as string | undefined) || "";
  const mode = (n.data.bqRowsInputMode as string | undefined) || "raw";
  if (index === 0) { bqProjectIdExpressionInputRef.value?.openExpandDialog(); return; }
  if (op === "query") {
    if (index === 1) bqQueryExpressionInputRef.value?.openExpandDialog();
    return;
  }
  // insertRows
  if (index === 1) { bqDatasetIdExpressionInputRef.value?.openExpandDialog(); return; }
  if (index === 2) { bqTableIdExpressionInputRef.value?.openExpandDialog(); return; }
  if (mode === "selective") {
    bqMappingInputRefs.value.get(index - 3)?.openExpandDialog();
  } else {
    bqRowsExpressionInputRef.value?.openExpandDialog();
  }
}

function closeBigQueryExpressionDialogs(): void {
  bqProjectIdExpressionInputRef.value?.closeExpandDialog();
  bqQueryExpressionInputRef.value?.closeExpandDialog();
  bqDatasetIdExpressionInputRef.value?.closeExpandDialog();
  bqTableIdExpressionInputRef.value?.closeExpandDialog();
  bqRowsExpressionInputRef.value?.closeExpandDialog();
  for (const inst of bqMappingInputRefs.value.values()) inst.closeExpandDialog();
}

function handleBigQueryExpressionFieldNavigate(direction: "prev" | "next"): void {
  const total = bigQueryExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentBigQueryExpressionFieldIndex.value - 1
      : currentBigQueryExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) return;
  closeBigQueryExpressionDialogs();
  currentBigQueryExpressionFieldIndex.value = newIndex;
  nextTick(() => { openBigQueryExpressionFieldAtIndex(newIndex); });
}

function onBigQueryRegisterExpressionFieldIndex(index: number): void {
  currentBigQueryExpressionFieldIndex.value = index;
}

function bqMappingInputRef(index: number, el: InstanceType<typeof ExpressionInput> | null): void {
  if (el) {
    bqMappingInputRefs.value.set(index, el);
  } else {
    bqMappingInputRefs.value.delete(index);
  }
}

const rabbitmqSendExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "rabbitmq") {
    return 1;
  }
  return n.data.rabbitmqOperation === "send" ? 4 : 1;
});

function openRabbitmqSendExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "rabbitmq" || n.data.rabbitmqOperation !== "send") {
    return;
  }
  currentRabbitmqSendExpressionFieldIndex.value = index;
  if (index === 0) {
    rabbitmqExchangeInputRef.value?.openExpandDialog();
  } else if (index === 1) {
    rabbitmqRoutingKeyInputRef.value?.openExpandDialog();
  } else if (index === 2) {
    rabbitmqQueueNameInputRef.value?.openExpandDialog();
  } else {
    rabbitmqMessageBodyInputRef.value?.openExpandDialog();
  }
}

function handleRabbitmqSendExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "rabbitmq" || n.data.rabbitmqOperation !== "send") {
    return;
  }
  const total = rabbitmqSendExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentRabbitmqSendExpressionFieldIndex.value - 1
      : currentRabbitmqSendExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  rabbitmqExchangeInputRef.value?.closeExpandDialog();
  rabbitmqRoutingKeyInputRef.value?.closeExpandDialog();
  rabbitmqQueueNameInputRef.value?.closeExpandDialog();
  rabbitmqMessageBodyInputRef.value?.closeExpandDialog();
  currentRabbitmqSendExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openRabbitmqSendExpressionFieldAtIndex(newIndex);
  });
}

function onRabbitmqSendRegisterExpressionFieldIndex(index: number): void {
  currentRabbitmqSendExpressionFieldIndex.value = index;
}

function setDataTableSelectiveExpressionInputRef(
  colName: string,
  el: Element | ComponentPublicInstance | null,
): void {
  const inst = el as InstanceType<typeof ExpressionInput> | null;
  if (inst && typeof inst.openExpandDialog === "function") {
    dataTableSelectiveExpressionInputRefs.value.set(colName, inst);
  } else {
    dataTableSelectiveExpressionInputRefs.value.delete(colName);
  }
}

function hydrateDataTableSelectiveValuesFromStoredJson(): void {
  const n = selectedNode.value;
  if (!n || n.type !== "dataTable") {
    return;
  }
  try {
    const parsed = JSON.parse(n.data.dataTableData || "{}") as Record<string, unknown>;
    dataTableSelectiveValues.value = Object.fromEntries(
      dataTableColumns.value.map((c) => [
        c.name,
        parsed[c.name] != null ? String(parsed[c.name]) : "",
      ]),
    );
  } catch {
    dataTableSelectiveValues.value = Object.fromEntries(
      dataTableColumns.value.map((c) => [c.name, ""]),
    );
  }
}

async function loadDataTableColumnsForSelectedNode(): Promise<void> {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "dataTable") {
    return;
  }
  const tableId = n.data.dataTableId;
  if (tableId) {
    try {
      const dt = await dataTablesApi.get(tableId);
      dataTableColumns.value = dt.columns || [];
    } catch {
      dataTableColumns.value = [];
    }
  } else {
    dataTableColumns.value = [];
  }
}

function syncDataTableSelectiveUiFromNodeMode(): void {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "dataTable") {
    return;
  }
  if ((n.data.dataTableInputMode || "raw") === "selective") {
    hydrateDataTableSelectiveValuesFromStoredJson();
  } else {
    dataTableSelectiveValues.value = {};
  }
}

function switchDataTableRowDataToSelectiveMode(): void {
  updateNodeData("dataTableInputMode", "selective");
  hydrateDataTableSelectiveValuesFromStoredJson();
}

function handleDataTableIdChangedForSelect(v: string | undefined): void {
  void (async (): Promise<void> => {
    updateNodeData("dataTableId", v || "");
    dataTableSelectiveValues.value = {};
    if (v) {
      try {
        const dt = await dataTablesApi.get(v);
        dataTableColumns.value = dt.columns || [];
      } catch {
        dataTableColumns.value = [];
      }
    } else {
      dataTableColumns.value = [];
    }
    syncDataTableSelectiveUiFromNodeMode();
  })();
}

function handleDataTableSelectiveColumnInput(colName: string, v: string): void {
  const next = { ...dataTableSelectiveValues.value, [colName]: v };
  dataTableSelectiveValues.value = next;
  const obj: Record<string, string> = {};
  for (const c of dataTableColumns.value) {
    if (next[c.name]) {
      obj[c.name] = next[c.name];
    }
  }
  if (selectedNode.value?.type === "dataTable") {
    updateNodeData("dataTableData", JSON.stringify(obj, null, 2));
  }
}

const dataTableExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "dataTable") {
    return 1;
  }
  const op = (n.data.dataTableOperation as string | undefined) || "";
  const rawData = (n.data.dataTableInputMode || "raw") === "raw";
  const colCount = dataTableColumns.value.length;

  if (op === "find") {
    return 2;
  }
  if (op === "getAll") {
    return 1;
  }
  if (op === "getById" || op === "remove") {
    return 1;
  }
  if (op === "insert") {
    if (!rawData && colCount > 0) {
      return colCount;
    }
    return 1;
  }
  if (op === "update") {
    if (rawData) {
      return 2;
    }
    return colCount > 0 ? 1 + colCount : 1;
  }
  if (op === "upsert") {
    if (rawData) {
      return 2;
    }
    return colCount > 0 ? colCount + 1 : 1;
  }
  return 1;
});

function openDataTableExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "dataTable") {
    return;
  }
  currentDataTableExpressionFieldIndex.value = index;
  const op = (n.data.dataTableOperation as string | undefined) || "";
  const rawData = (n.data.dataTableInputMode || "raw") === "raw";

  if (op === "find") {
    if (index === 0) {
      dataTableFilterExpressionInputRef.value?.openExpandDialog();
    } else {
      dataTableSortExpressionInputRef.value?.openExpandDialog();
    }
    return;
  }
  if (op === "getAll") {
    dataTableSortExpressionInputRef.value?.openExpandDialog();
    return;
  }
  if (op === "getById" || op === "remove") {
    dataTableRowIdExpressionInputRef.value?.openExpandDialog();
    return;
  }
  if (op === "insert") {
    if (rawData) {
      dataTableDataExpressionInputRef.value?.openExpandDialog();
    } else {
      const col = dataTableColumns.value[index];
      if (col) {
        dataTableSelectiveExpressionInputRefs.value.get(col.name)?.openExpandDialog();
      }
    }
    return;
  }
  if (op === "update") {
    if (index === 0) {
      dataTableRowIdExpressionInputRef.value?.openExpandDialog();
    } else if (rawData) {
      dataTableDataExpressionInputRef.value?.openExpandDialog();
    } else {
      const col = dataTableColumns.value[index - 1];
      if (col) {
        dataTableSelectiveExpressionInputRefs.value.get(col.name)?.openExpandDialog();
      }
    }
    return;
  }
  if (op === "upsert") {
    if (rawData) {
      if (index === 0) {
        dataTableDataExpressionInputRef.value?.openExpandDialog();
      } else {
        dataTableFilterExpressionInputRef.value?.openExpandDialog();
      }
    } else {
      const nCols = dataTableColumns.value.length;
      if (index < nCols) {
        const col = dataTableColumns.value[index];
        if (col) {
          dataTableSelectiveExpressionInputRefs.value.get(col.name)?.openExpandDialog();
        }
      } else if (index === nCols) {
        dataTableFilterExpressionInputRef.value?.openExpandDialog();
      }
    }
    return;
  }
}

function handleDataTableExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "dataTable") {
    return;
  }
  const total = dataTableExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentDataTableExpressionFieldIndex.value - 1
      : currentDataTableExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  dataTableRowIdExpressionInputRef.value?.closeExpandDialog();
  dataTableDataExpressionInputRef.value?.closeExpandDialog();
  dataTableFilterExpressionInputRef.value?.closeExpandDialog();
  dataTableSortExpressionInputRef.value?.closeExpandDialog();
  for (const inst of dataTableSelectiveExpressionInputRefs.value.values()) {
    inst.closeExpandDialog();
  }
  currentDataTableExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openDataTableExpressionFieldAtIndex(newIndex);
  });
}

function onDataTableRegisterExpressionFieldIndex(index: number): void {
  currentDataTableExpressionFieldIndex.value = index;
}

const driveExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "drive") {
    return 1;
  }
  return n.data.driveOperation === "setPassword" ? 2 : 1;
});

function openDriveExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "drive") {
    return;
  }
  currentDriveExpressionFieldIndex.value = index;
  if (n.data.driveOperation === "setPassword") {
    if (index === 0) {
      driveFileIdExpressionInputRef.value?.openExpandDialog();
    } else {
      drivePasswordExpressionInputRef.value?.openExpandDialog();
    }
    return;
  }
  driveFileIdExpressionInputRef.value?.openExpandDialog();
}

function handleDriveExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "drive" || n.data.driveOperation !== "setPassword") {
    return;
  }
  const total = driveExpressionFieldCount.value;
  const newIndex =
    direction === "prev"
      ? currentDriveExpressionFieldIndex.value - 1
      : currentDriveExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  driveFileIdExpressionInputRef.value?.closeExpandDialog();
  drivePasswordExpressionInputRef.value?.closeExpandDialog();
  currentDriveExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openDriveExpressionFieldAtIndex(newIndex);
  });
}

function onDriveRegisterExpressionFieldIndex(index: number): void {
  currentDriveExpressionFieldIndex.value = index;
}

function onSetMappingRegisterFieldIndex(index: number): void {
  currentSetMappingIndex.value = index;
}

function onExecuteMappingRegisterFieldIndex(index: number): void {
  currentExecuteMappingIndex.value = index;
}

watch(
  () => workflowStore.propertiesPanelOpen,
  (open) => {
    if (open) {
      if (activeTab.value === "properties") {
        if (!workflowStore.skipPrimaryExpandOnNextPropertiesOpen) {
          openPrimaryExpandDialogForSelectedNode();
        }
      } else {
        activeTab.value = "properties";
      }
      workflowStore.clearSkipPrimaryExpandOnNextPropertiesOpen();
      workflowStore.propertiesPanelOpen = false;
    }
  }
);

function buildCredentialOptions(
  credentials: CredentialListItem[],
  selectedCredentialId: string | undefined,
  placeholderLabel: string,
  sharedFallbackLabel: string,
): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = [
    { value: "", label: placeholderLabel },
    ...credentials.map((c) => ({
      value: c.id,
      label: c.is_shared ? `${c.name} (${c.type}) - shared` : `${c.name} (${c.type})`,
    })),
  ];

  if (
    selectedCredentialId &&
    !credentials.some((c) => c.id === selectedCredentialId) &&
    !options.some((opt) => opt.value === selectedCredentialId)
  ) {
    options.push({
      value: selectedCredentialId,
      label: sharedFallbackLabel,
    });
  }

  return options;
}

const credentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && (node.type === "llm" || node.type === "agent")
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    llmCredentials.value,
    selectedCredentialId,
    "Select credential...",
    "Credential not available (re-select)",
  );
});

/** On import: clear credential ids that the current user cannot use (unknown / not in owned + shared list). */
watch(
  () => [
    workflowStore.selectedNode?.id,
    workflowStore.selectedNode?.type,
    workflowStore.selectedNode?.data?.credentialId,
    workflowStore.selectedNode?.data?.fallbackCredentialId,
    workflowStore.selectedNode?.data?.guardrailCredentialId,
    llmCredentials.value,
    isWorkflowOwner.value,
  ] as const,
  () => {
    const node = workflowStore.selectedNode;
    if (!node || (node.type !== "llm" && node.type !== "agent") || !isWorkflowOwner.value) return;
    const validIds = new Set(llmCredentials.value.map((c) => c.id));
    // Skip when credentials not loaded yet (e.g. after refresh) so we don't clear valid ids
    if (validIds.size === 0 && llmCredentials.value.length === 0) return;
    const patch: Record<string, string> = {};
    const cid = (node.data.credentialId as string | undefined)?.trim();
    if (cid && !validIds.has(cid)) {
      patch.credentialId = "";
      patch.model = "";
    }
    const fcid = (node.data.fallbackCredentialId as string | undefined)?.trim();
    if (fcid && !validIds.has(fcid)) {
      patch.fallbackCredentialId = "";
      patch.fallbackModel = "";
    }
    const gcid = (node.data.guardrailCredentialId as string | undefined)?.trim();
    if (gcid && !validIds.has(gcid)) {
      patch.guardrailCredentialId = "";
      patch.guardrailModel = "";
    }
    if (Object.keys(patch).length > 0) {
      workflowStore.updateNode(node.id, { ...node.data, ...patch });
      workflowStore.hasUnsavedChanges = true;
    }
  },
  { immediate: true }
);

const slackCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "slack"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    slackCredentials.value,
    selectedCredentialId,
    "Select Slack credential...",
    "Shared Slack credential (from owner)",
  );
});

const telegramCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "telegram"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    telegramCredentials.value,
    selectedCredentialId,
    "Select Telegram credential...",
    "Shared Telegram credential (from owner)",
  );
});

const telegramTriggerCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "telegramTrigger"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    telegramCredentials.value,
    selectedCredentialId,
    "Select Telegram credential...",
    "Shared Telegram credential (from owner)",
  );
});

const smtpCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "sendEmail"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    smtpCredentials.value,
    selectedCredentialId,
    "Select SMTP credential...",
    "Shared SMTP credential (from owner)",
  );
});

const imapTriggerCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "imapTrigger"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    imapTriggerCredentials.value,
    selectedCredentialId,
    "Select IMAP credential...",
    "Shared IMAP credential (from owner)",
  );
});

const redisCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "redis"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    redisCredentials.value,
    selectedCredentialId,
    "Select Redis credential...",
    "Shared Redis credential (from owner)",
  );
});

const vectorStoreOptions = computed(() => {
  return [
    { value: "", label: "Select a vector store" },
    ...vectorStores.value.map((s) => ({
      value: s.id,
      label: s.name,
    })),
  ];
});

const ragOperationOptions = [
  { value: "", label: "Select operation" },
  { value: "insert", label: "Insert" },
  { value: "search", label: "Search" },
];

const redisOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "set", label: "Set Variable" },
  { value: "get", label: "Get Variable" },
  { value: "hasKey", label: "Has Key" },
  { value: "deleteKey", label: "Delete Key" },
];

const gristCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "grist"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    gristCredentials.value,
    selectedCredentialId,
    "Select Grist credential...",
    "Shared Grist credential (from owner)",
  );
});

const googleSheetsCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "googleSheets"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    googleSheetsCredentials.value,
    selectedCredentialId,
    "Select Google Sheets credential...",
    "Shared Google Sheets credential (from owner)",
  );
});

const cohereCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "rag"
      ? (node.data.rerankerCredentialId as string | undefined)
      : undefined;

  const options: { value: string; label: string }[] = [
    { value: "", label: "Select Cohere credential..." },
    ...cohereCredentials.value.map((c) => ({
      value: c.id,
      label: c.is_shared ? `${c.name} - shared` : c.name,
    })),
  ];

  if (
    selectedCredentialId &&
    !cohereCredentials.value.some((c) => c.id === selectedCredentialId) &&
    !options.some((opt) => opt.value === selectedCredentialId)
  ) {
    options.push({
      value: selectedCredentialId,
      label: "Shared Cohere credential (from owner)",
    });
  }

  return options;
});

const gristOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "getRecord", label: "Get Record" },
  { value: "getRecords", label: "Get Records" },
  { value: "createRecord", label: "Create Record" },
  { value: "createRecords", label: "Create Records (Batch)" },
  { value: "updateRecord", label: "Update Record" },
  { value: "updateRecords", label: "Update Records (Batch)" },
  { value: "deleteRecord", label: "Delete Record(s)" },
  { value: "listTables", label: "List Tables" },
  { value: "listColumns", label: "List Columns" },
];

const googleSheetsOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "readRange", label: "Read" },
  { value: "appendRows", label: "Append Rows" },
  { value: "updateRange", label: "Update Rows" },
  { value: "clearRange", label: "Clear Rows" },
  { value: "getSheetInfo", label: "Get Sheet Info" },
];

const googleSheetsAppendPlacementOptions = [
  { value: "append", label: "Bottom (after last row)" },
  { value: "prepend", label: "Top (below row 1)" },
];

const bigQueryCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "bigquery"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    bigqueryCredentials.value,
    selectedCredentialId,
    "Select BigQuery credential...",
    "Shared BigQuery credential (from owner)",
  );
});

const bigQueryOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "query", label: "Run Query" },
  { value: "insertRows", label: "Insert Rows" },
];

const dataTableOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "find", label: "Find Rows" },
  { value: "getAll", label: "Get All Rows" },
  { value: "getById", label: "Get Row by ID" },
  { value: "insert", label: "Insert Row" },
  { value: "update", label: "Update Row" },
  { value: "remove", label: "Remove Row" },
  { value: "upsert", label: "Upsert Row" },
];

const driveOperationOptions = [
  { value: "get", label: "Get File" },
  { value: "downloadUrl", label: "Download from URL" },
  { value: "delete", label: "Delete File" },
  { value: "setPassword", label: "Set Password" },
  { value: "setTtl", label: "Set TTL (Expiry)" },
  { value: "setMaxDownloads", label: "Set Max Downloads" },
];

const dataTableOptions = computed(() => {
  const options = [{ value: "", label: "Select table..." }];
  for (const dt of dataTables.value) {
    options.push({ value: dt.id, label: dt.name });
  }
  return options;
});

const rabbitmqCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "rabbitmq"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  return buildCredentialOptions(
    rabbitmqCredentials.value,
    selectedCredentialId,
    "Select RabbitMQ credential...",
    "Shared RabbitMQ credential (from owner)",
  );
});

const rabbitmqOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "send", label: "Send Message" },
  { value: "receive", label: "Receive Message (Trigger)" },
];

const crawlerCredentialOptions = computed(() => {
  const node = selectedNode.value;
  const selectedCredentialId =
    node && node.type === "crawler"
      ? (node.data.credentialId as string | undefined)
      : undefined;

  const options: { value: string; label: string }[] = [
    { value: "", label: "Select FlareSolverr credential..." },
    ...crawlerCredentials.value.map((c) => ({
      value: c.id,
      label: c.is_shared ? `${c.name} - shared` : c.name,
    })),
  ];

  if (
    selectedCredentialId &&
    !crawlerCredentials.value.some((c) => c.id === selectedCredentialId) &&
    !options.some((opt) => opt.value === selectedCredentialId)
  ) {
    options.push({
      value: selectedCredentialId,
      label: "Shared FlareSolverr credential (from owner)",
    });
  }

  return options;
});

const crawlerModeOptions = [
  { value: "basic", label: "Basic (Raw HTML)" },
  { value: "extract", label: "Extract (CSS Selectors)" },
];

function addCrawlerSelector(): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const selectors = [...(node.data.crawlerSelectors || [])];
  selectors.push({ name: "", selector: "", attributes: [] });
  updateNodeData("crawlerSelectors", selectors);
}

function removeCrawlerSelector(index: number): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const selectors = [...(node.data.crawlerSelectors || [])];
  selectors.splice(index, 1);
  updateNodeData("crawlerSelectors", selectors);
}

function updateCrawlerSelector(index: number, field: string, value: string): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const selectors = [...(node.data.crawlerSelectors || [])];
  if (selectors[index]) {
    selectors[index] = { ...selectors[index], [field]: value };
    updateNodeData("crawlerSelectors", selectors);
  }
}

function updateCrawlerSelectorAttributes(index: number, value: string): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const selectors = [...(node.data.crawlerSelectors || [])];
  if (selectors[index]) {
    const attributes = value.split(",").map((attr) => attr.trim()).filter((attr) => attr);
    selectors[index] = { ...selectors[index], attributes };
    updateNodeData("crawlerSelectors", selectors);
  }
}

const playwrightStepActionOptions: { value: PlaywrightStepAction; label: string }[] = [
  { value: "navigate", label: "Navigate" },
  { value: "click", label: "Click" },
  { value: "type", label: "Type" },
  { value: "fill", label: "Fill" },
  { value: "wait", label: "Wait" },
  { value: "screenshot", label: "Screenshot" },
  { value: "getText", label: "Get Text" },
  { value: "getAttribute", label: "Get Attribute" },
  { value: "getHTML", label: "Get HTML" },
  { value: "getVisibleTextOnPage", label: "Get visible page text" },
  { value: "hover", label: "Hover" },
  { value: "selectOption", label: "Select Option" },
  { value: "scrollDown", label: "Scroll Down" },
  { value: "scrollUp", label: "Scroll Up" },
  { value: "aiStep", label: "AI Step" },
];

const playwrightAiStepModelsCache = ref<Record<string, { value: string; label: string }[]>>({});

async function loadPlaywrightAiStepModels(credentialId: string): Promise<void> {
  if (!credentialId || playwrightAiStepModelsCache.value[credentialId]) return;
  try {
    const models = await credentialsApi.getModels(credentialId);
    playwrightAiStepModelsCache.value = {
      ...playwrightAiStepModelsCache.value,
      [credentialId]: models.map((m) => ({ value: m.id, label: m.id })),
    };
  } catch {
    playwrightAiStepModelsCache.value = {
      ...playwrightAiStepModelsCache.value,
      [credentialId]: [],
    };
  }
}

function playwrightAiStepModelOptions(
  credentialId: string | undefined,
  currentModel?: string,
): { value: string; label: string }[] {
  if (!credentialId) return [{ value: "", label: "Select credential first..." }];
  const cached = playwrightAiStepModelsCache.value[credentialId];
  if (cached) {
    const options: { value: string; label: string }[] = [
      { value: "", label: "Select model..." },
      ...cached,
    ];

    if (
      currentModel &&
      !cached.some((m) => m.value === currentModel) &&
      !options.some((opt) => opt.value === currentModel)
    ) {
      options.push({
        value: currentModel,
        label: "Shared model (from owner)",
      });
    }

    return options;
  }
  // While loading: keep current model in options so save preserves it
  return currentModel
    ? [{ value: currentModel, label: `${currentModel} (loading...)` }]
    : [{ value: "", label: "Loading..." }];
}

interface PlaywrightStepSection {
  emptyText: string;
  helpText?: string;
  key: PlaywrightStepListKey;
  label: string;
}

const playwrightStepSections = computed((): PlaywrightStepSection[] => {
  const sections: PlaywrightStepSection[] = [
    {
      key: "playwrightSteps",
      label: "Steps",
      emptyText: "Add steps to define browser automation. Steps are executed in order at runtime.",
    },
  ];
  if (workflowStore.selectedNode?.data?.playwrightAuthEnabled) {
    sections.push({
      key: "playwrightAuthFallbackSteps",
      label: "Fallback login steps",
      emptyText: "These steps run only if the authenticated selector is missing after cookie restore.",
      helpText: "Fallback steps should leave the browser on the authenticated page expected by the main flow.",
    });
  }
  return sections;
});

function getPlaywrightSteps(stepListKey: PlaywrightStepListKey): PlaywrightStep[] {
  const node = workflowStore.selectedNode;
  if (!node) return [];
  return [...((node.data[stepListKey] || []) as PlaywrightStep[])];
}

function savedStepKey(
  stepListKey: PlaywrightStepListKey,
  stepIndex: number,
  savedStepIndex: number,
): string {
  return `${stepListKey}-${stepIndex}-${savedStepIndex}`;
}

function addPlaywrightStep(stepListKey: PlaywrightStepListKey = "playwrightSteps"): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const steps = getPlaywrightSteps(stepListKey);
  steps.push({ action: "navigate", url: "https://example.com" });
  updateNodeData(stepListKey, steps);
  nextTick(() => {
    const els = document.querySelectorAll(`[data-playwright-step="${stepListKey}"]`);
    const last = els[els.length - 1];
    if (last) last.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

function removePlaywrightStep(
  stepListKey: PlaywrightStepListKey,
  index: number,
): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const steps = getPlaywrightSteps(stepListKey);
  steps.splice(index, 1);
  updateNodeData(stepListKey, steps);
}

function movePlaywrightStepUp(
  stepListKey: PlaywrightStepListKey,
  index: number,
): void {
  const node = workflowStore.selectedNode;
  if (!node || index <= 0) return;

  const steps = getPlaywrightSteps(stepListKey);
  [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]];
  updateNodeData(stepListKey, steps);
}

function movePlaywrightStepDown(
  stepListKey: PlaywrightStepListKey,
  index: number,
): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const steps = getPlaywrightSteps(stepListKey);
  if (index >= steps.length - 1) return;

  [steps[index], steps[index + 1]] = [steps[index + 1], steps[index]];
  updateNodeData(stepListKey, steps);
}

type PlaywrightStepValue =
  | string
  | number
  | boolean
  | PlaywrightStep["savedSteps"]
  | undefined;

/** Short label for evaluate dialog title (section + action + step + field). */
function playwrightStepDialogKey(
  sectionLabel: string,
  stepIndex: number,
  actionLabel: string,
  part: string,
): string {
  return `${sectionLabel} · ${actionLabel} · step ${stepIndex + 1} · ${part}`;
}

function playwrightStepActionLabel(action: PlaywrightStepAction | string): string {
  const found = playwrightStepActionOptions.find((o) => o.value === action);
  return found?.label ?? String(action);
}

/** Expression fields per step, in the same DOM order as PropertiesPanel. */
function playwrightStepExpressionFields(step: PlaywrightStep): PlaywrightExprNavSlotField[] {
  const a = step.action;
  if (a === "navigate") {
    return ["url"];
  }
  if (a === "aiStep") {
    return ["instructions"];
  }
  const withSelector: PlaywrightStepAction[] = [
    "click",
    "type",
    "fill",
    "getText",
    "getAttribute",
    "getHTML",
    "hover",
    "selectOption",
  ];
  if (!withSelector.includes(a)) {
    return [];
  }
  const fields: PlaywrightExprNavSlotField[] = ["selector"];
  if (a === "type" || a === "fill") {
    fields.push("typeFill");
  }
  return fields;
}

const playwrightExpressionNavPlan = computed((): { slots: PlaywrightExprNavSlot[]; total: number } => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "playwright") {
    return { slots: [], total: 0 };
  }
  const slots: PlaywrightExprNavSlot[] = [];
  if (n.data.playwrightAuthEnabled === true) {
    slots.push({ kind: "authState" });
    slots.push({ kind: "authSelector" });
  }
  const appendSteps = (stepListKey: PlaywrightStepListKey): void => {
    const steps = (n.data[stepListKey] || []) as PlaywrightStep[];
    for (let stepIndex = 0; stepIndex < steps.length; stepIndex++) {
      for (const field of playwrightStepExpressionFields(steps[stepIndex])) {
        slots.push({ kind: "stepField", stepListKey, stepIndex, field });
      }
    }
  };
  appendSteps("playwrightSteps");
  if (n.data.playwrightAuthEnabled === true) {
    appendSteps("playwrightAuthFallbackSteps");
  }
  return { slots, total: slots.length };
});

function playwrightExprSlotKeyFromSlot(slot: PlaywrightExprNavSlot): string {
  if (slot.kind === "authState") {
    return "authState";
  }
  if (slot.kind === "authSelector") {
    return "authSelector";
  }
  return `${String(slot.stepListKey)}-${String(slot.stepIndex)}-${String(slot.field)}`;
}

function playwrightExprNavGlobalIndexForAuthState(): number {
  return playwrightExpressionNavPlan.value.slots.findIndex((s) => s.kind === "authState");
}

function playwrightExprNavGlobalIndexForAuthSelector(): number {
  return playwrightExpressionNavPlan.value.slots.findIndex((s) => s.kind === "authSelector");
}

function playwrightExprNavGlobalIndexForStep(
  stepListKey: PlaywrightStepListKey,
  stepIndex: number,
  field: PlaywrightExprNavSlotField,
): number {
  return playwrightExpressionNavPlan.value.slots.findIndex(
    (s) =>
      s.kind === "stepField" &&
      s.stepListKey === stepListKey &&
      s.stepIndex === stepIndex &&
      s.field === field,
  );
}

function bindPlaywrightExprSlotRef(slotKey: string, el: unknown): void {
  if (el === null || el === undefined) {
    playwrightExprRefsBySlotKey.value[slotKey] = null;
    return;
  }
  playwrightExprRefsBySlotKey.value[slotKey] = el as InstanceType<typeof ExpressionInput>;
}

function closeAllPlaywrightExpressionDialogs(): void {
  for (const comp of Object.values(playwrightExprRefsBySlotKey.value)) {
    comp?.closeExpandDialog();
  }
}

function openPlaywrightExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "playwright") {
    return;
  }
  currentPlaywrightExpressionFieldIndex.value = index;
  const slot = playwrightExpressionNavPlan.value.slots[index];
  if (!slot) {
    return;
  }
  const slotKey = playwrightExprSlotKeyFromSlot(slot);
  nextTick(() => {
    playwrightExprRefsBySlotKey.value[slotKey]?.openExpandDialog();
  });
}

function handlePlaywrightExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "playwright") {
    return;
  }
  const total = playwrightExpressionNavPlan.value.total;
  if (total <= 1) {
    return;
  }
  const newIndex =
    direction === "prev"
      ? currentPlaywrightExpressionFieldIndex.value - 1
      : currentPlaywrightExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  closeAllPlaywrightExpressionDialogs();
  currentPlaywrightExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openPlaywrightExpressionFieldAtIndex(newIndex);
  });
}

function onPlaywrightRegisterExpressionFieldIndex(index: number): void {
  currentPlaywrightExpressionFieldIndex.value = index;
}

function updatePlaywrightStep(
  stepListKey: PlaywrightStepListKey,
  index: number,
  field: keyof PlaywrightStep,
  value: PlaywrightStepValue,
): void {
  const node = workflowStore.selectedNode;
  if (!node) return;

  const steps = getPlaywrightSteps(stepListKey);
  if (steps[index]) {
    const next = { ...steps[index], [field]: value };
    if (field === "saveStepsForFuture" && value === false) {
      delete next.savedSteps;
    }
    steps[index] = next;
    updateNodeData(stepListKey, steps);
  }
}

type SavedStepField = keyof NonNullable<PlaywrightStep["savedSteps"]>[number];

function updatePlaywrightStepSavedStep(
  stepListKey: PlaywrightStepListKey,
  stepIndex: number,
  savedStepIndex: number,
  field: SavedStepField,
  value: string | number | undefined,
): void {
  const node = workflowStore.selectedNode;
  if (!node) return;
  const steps = getPlaywrightSteps(stepListKey);
  const step = steps[stepIndex];
  if (!step?.savedSteps?.[savedStepIndex]) return;
  const saved = step.savedSteps.map((s, i) =>
    i === savedStepIndex ? { ...s, [field]: value } : s,
  );
  steps[stepIndex] = { ...step, savedSteps: saved };
  updateNodeData(stepListKey, steps);
}

function removePlaywrightStepSavedStep(
  stepListKey: PlaywrightStepListKey,
  stepIndex: number,
  savedStepIndex: number,
): void {
  const node = workflowStore.selectedNode;
  if (!node) return;
  const steps = getPlaywrightSteps(stepListKey);
  const step = steps[stepIndex];
  if (!step?.savedSteps) return;
  const saved = step.savedSteps.filter((_, i) => i !== savedStepIndex);
  steps[stepIndex] = { ...step, savedSteps: saved.length ? saved : undefined };
  updateNodeData(stepListKey, steps);
  if (expandedSavedStepKey.value?.startsWith(`${stepListKey}-${stepIndex}-`)) {
    expandedSavedStepKey.value = null;
  }
}

function formatSavedStep(s: { action: string; selector?: string; text?: string; value?: string; timeout?: number; amount?: number }): string {
  const a = s.action;
  const sel = s.selector ? ` "${s.selector}"` : "";
  if (a === "click") return `click${sel}`;
  if (a === "fill") return `fill${sel} → ${s.value ?? ""}`;
  if (a === "type") return `type${sel} → ${s.text ?? ""}`;
  if (a === "wait") return `wait ${s.timeout ?? 2000}ms`;
  if (a === "hover") return `hover${sel}`;
  if (a === "selectOption") return `selectOption${sel} → ${s.value ?? ""}`;
  if (a === "scrollDown") return `scrollDown ${s.amount ?? 300}px`;
  if (a === "scrollUp") return `scrollUp ${s.amount ?? 300}px`;
  return a;
}

const modelOptions = computed(() => {
  const node = selectedNode.value;
  const selectedModelId =
    node && (node.type === "llm" || node.type === "agent")
      ? (node.data.model as string | undefined)
      : undefined;
  const credentialId = llmCredentialId.value;
  const showSharedByOwner = !isWorkflowOwner.value && credentialId;
  const suffix = showSharedByOwner ? " (shared by owner)" : "";

  if (llmModels.value.length === 0) {
    if (selectedModelId) {
      return [
        { value: "", label: "Select credential first..." },
        {
          value: selectedModelId,
          label: `${selectedModelId}${suffix}`,
        },
      ];
    }
    return [{ value: "", label: "Select credential first..." }];
  }

  const options = llmModels.value.map((m) => ({
    value: m.id,
    label: `${m.is_reasoning ? `${m.name} (Reasoning)` : m.name}${suffix}`,
  }));

  if (
    selectedModelId &&
    !llmModels.value.some((m) => m.id === selectedModelId) &&
    !options.some((opt) => opt.value === selectedModelId)
  ) {
    options.push({
      value: selectedModelId,
      label: `${selectedModelId}${suffix}`,
    });
  }

  return options;
});

const reasoningEffortOptions = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

const outputTypeOptions = [
  { value: "text", label: "Text" },
  { value: "image", label: "Image" },
];

const GUARDRAIL_CATEGORIES: { value: GuardrailCategory; label: string }[] = [
  { value: "violence", label: "Violence" },
  { value: "hate_speech", label: "Hate Speech" },
  { value: "sexual_content", label: "Sexual Content" },
  { value: "nsfw", label: "NSFW / Profanity" },
  { value: "self_harm", label: "Self-Harm" },
  { value: "harassment", label: "Harassment" },
  { value: "illegal_activity", label: "Illegal Activity" },
  { value: "political_extremism", label: "Political Extremism" },
  { value: "spam_phishing", label: "Spam / Phishing" },
  { value: "personal_data", label: "Personal Data Request" },
  { value: "prompt_injection", label: "Prompt Injection" },
];

const GUARDRAIL_SEVERITY_OPTIONS = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];

function toggleGuardrailCategory(checked: boolean, category: GuardrailCategory): void {
  const current: GuardrailCategory[] = (selectedNode.value?.data.guardrailsCategories as GuardrailCategory[]) || [];
  let updated: GuardrailCategory[];
  if (checked) {
    updated = current.includes(category) ? current : [...current, category];
  } else {
    updated = current.filter((c) => c !== category);
  }
  updateNodeData("guardrailsCategories", updated);
}

const variableTypeOptions = [
  { value: "auto", label: "Auto (detect type)" },
  { value: "string", label: "String" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Boolean" },
  { value: "array", label: "Array" },
  { value: "object", label: "Object" },
];

const httpStatusCodeOptions = [
  { value: "", label: "Select status code..." },
  { value: "400", label: "400 Bad Request" },
  { value: "401", label: "401 Unauthorized" },
  { value: "403", label: "403 Forbidden" },
  { value: "404", label: "404 Not Found" },
  { value: "409", label: "409 Conflict" },
  { value: "422", label: "422 Unprocessable Entity" },
  { value: "429", label: "429 Too Many Requests" },
  { value: "500", label: "500 Internal Server Error" },
  { value: "502", label: "502 Bad Gateway" },
  { value: "503", label: "503 Service Unavailable" },
];

const reservedVariableNames = ref<Set<string>>(new Set());

const RESERVED_LABEL_NAMES = new Set([
  "headers",
  "query",
  "value",
  "list",
  "array",
  "vars",
  "items",
  "first",
  "last",
  "random",
  "name",
  "type",
  "length",
  "tostring",
  "touppercase",
  "tolowercase",
  "substring",
  "indexof",
  "contains",
  "startswith",
  "endswith",
  "replace",
  "replaceall",
  "regexreplace",
  "reverse",
  "distinct",
  "notnull",
  "filter",
  "map",
  "sort",
  "join",
  "status",
  "body",
  "outputs",
  "result",
  "item",
  "index",
  "total",
  "isfirst",
  "islast",
  "branch",
  "results",
  "merged",
  "error",
  "errornode",
  "errornodetype",
  "timestamp",
  "input",
  "now",
  "date",
]);

async function loadReservedVariableNames(): Promise<void> {
  try {
    const names = await configApi.getReservedVariableNames();
    reservedVariableNames.value = new Set(names);
  } catch {
    reservedVariableNames.value = new Set();
  }
}

const reservedLabelError = computed(() => {
  const node = workflowStore.selectedNode;
  if (!node) return "";
  const label = (node.data.label || "").trim().toLowerCase();
  if (!label) return "";
  if (RESERVED_LABEL_NAMES.has(label)) {
    return `"${node.data.label}" is a reserved name and cannot be used as a node label`;
  }
  return "";
});

const variableNameError = computed(() => {
  const node = workflowStore.selectedNode;
  if (!node || node.type !== "variable") return "";
  const varName = (node.data.variableName || "").trim().toLowerCase();
  if (!varName) return "";
  if (reservedVariableNames.value.has(varName)) {
    return `"${varName}" is a reserved name and cannot be used`;
  }
  return "";
});

function getInputFieldError(key: string): string {
  const normalizedKey = (key || "").trim().toLowerCase();
  if (!normalizedKey) return "";
  if (reservedVariableNames.value.has(normalizedKey)) {
    return `"${key}" is reserved`;
  }
  return "";
}

function getMappingKeyError(key: string): string {
  const normalizedKey = (key || "").trim().toLowerCase();
  if (!normalizedKey) return "";
  if (reservedVariableNames.value.has(normalizedKey)) {
    return `"${key}" is reserved`;
  }
  return "";
}

function getExpressionWarning(value: string): string {
  void value;
  return "";
}

const isImageOutputMode = computed(() => {
  return workflowStore.selectedNode?.data.outputType === "image";
});

const llmExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "llm") {
    return 1;
  }
  if (isImageOutputMode.value) {
    return n.data.imageInputEnabled ? 2 : 1;
  }
  return n.data.imageInputEnabled ? 3 : 2;
});

const agentExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "agent") {
    return 1;
  }
  return n.data.imageInputEnabled ? 3 : 2;
});

const selectedModelIsReasoning = computed(() => {
  const modelId = workflowStore.selectedNode?.data.model;
  if (!modelId) return false;
  const model = llmModels.value.find((m) => m.id === modelId);
  return model?.is_reasoning ?? false;
});

const selectedLlmBatchModel = computed(() => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "llm") return null;
  const modelId = node.data.model;
  if (!modelId) return null;
  return llmModels.value.find((model) => model.id === modelId) || null;
});

const selectedLlmCredentialType = computed((): string | null => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "llm" || !node.data.credentialId) {
    return null;
  }
  return llmCredentials.value.find((c) => c.id === node.data.credentialId)?.type ?? null;
});

const llmBatchCapabilityMessage = computed(() => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "llm") return null;
  if (!node.data.credentialId) {
    return "Select a credential to check batch support.";
  }
  if (loadingModels.value) {
    return "Checking provider batch support...";
  }
  if (isImageOutputMode.value) {
    return "Batch mode works only with text output.";
  }
  if (node.data.imageInputEnabled) {
    return "Batch mode does not support image input.";
  }
  if (selectedLlmCredentialType.value && selectedLlmCredentialType.value !== "openai") {
    return "Batch mode is only available for OpenAI credentials.";
  }

  const selectedModel = selectedLlmBatchModel.value;
  if (selectedModel) {
    return selectedModel.batch_support_reason || (
      selectedModel.supports_batch
        ? "Batch mode is available for this model."
        : "Batch mode is not available for this model."
    );
  }

  if (llmModels.value.length === 0) {
    return "Select a model to see batch support.";
  }

  const supportedModels = llmModels.value.filter((model) => model.supports_batch);
  if (supportedModels.length === 0) {
    return llmModels.value[0]?.batch_support_reason || "Batch mode is not available for this credential.";
  }
  if (supportedModels.length === llmModels.value.length) {
    return supportedModels[0]?.batch_support_reason || "Batch mode is available for this credential.";
  }
  return `${supportedModels.length}/${llmModels.value.length} models support batch mode. Select one to continue.`;
});

const llmBatchCapabilityTone = computed(() => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "llm") return "muted";
  if (isImageOutputMode.value || node.data.imageInputEnabled) return "warning";
  if (selectedLlmCredentialType.value && selectedLlmCredentialType.value !== "openai") {
    return "warning";
  }
  const selectedModel = selectedLlmBatchModel.value;
  if (selectedModel) {
    return selectedModel.supports_batch ? "positive" : "warning";
  }
  const supportedCount = llmModels.value.filter((model) => model.supports_batch).length;
  if (supportedCount === 0 && llmModels.value.length > 0) return "warning";
  if (supportedCount > 0 && supportedCount === llmModels.value.length) return "positive";
  return "muted";
});

const llmBatchModeAvailable = computed(() => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "llm") return false;
  if (isImageOutputMode.value || node.data.imageInputEnabled) return false;
  if (selectedLlmCredentialType.value !== "openai") return false;
  return selectedLlmBatchModel.value?.supports_batch === true;
});

const _AGENT_CONTEXT_LIMITS: Record<string, number> = {
  // OpenAI
  "gpt-4.1": 1_047_576,
  "gpt-4o-mini": 128_000,
  "gpt-4o": 128_000,
  "gpt-4-turbo": 128_000,
  "gpt-4.5": 128_000,
  "gpt-4": 8_192,
  "gpt-3.5-turbo": 16_385,
  // OpenAI reasoning
  "o4-mini": 200_000,
  "o3-mini": 200_000,
  "o1-mini": 128_000,
  "o3": 200_000,
  "o1": 200_000,
  // Anthropic Claude
  "claude-opus-4": 200_000,
  "claude-sonnet-4": 200_000,
  "claude-3-7-sonnet": 200_000,
  "claude-3-5-sonnet": 200_000,
  "claude-3-5-haiku": 200_000,
  "claude-3-opus": 200_000,
  "claude-3-haiku": 200_000,
  "claude-haiku": 200_000,
  // Google Gemini
  "gemini-2.5-pro": 1_048_576,
  "gemini-2.5-flash": 1_048_576,
  "gemini-2.0-flash": 1_048_576,
  "gemini-1.5-pro": 2_000_000,
  "gemini-1.5-flash": 1_000_000,
};

function _formatContextTokens(tokens: number): string {
  if (tokens >= 1_000_000) {
    const m = tokens / 1_000_000;
    return `${Number.isInteger(m) ? m : m.toFixed(1)}M`;
  }
  return `${Math.round(tokens / 1_000)}K`;
}

const agentModelContextLimit = computed((): string | null => {
  const node = workflowStore.selectedNode;
  if (node?.type !== "agent") return null;
  const modelId = node.data.model as string | undefined;
  if (!modelId) return null;
  const lower = modelId.toLowerCase();
  for (const [key, limit] of Object.entries(_AGENT_CONTEXT_LIMITS)) {
    if (lower.includes(key)) return _formatContextTokens(limit);
  }
  return null;
});

function handleModelChange(modelId: string | undefined): void {
  if (!modelId) return;
  const model = llmModels.value.find((m) => m.id === modelId);
  updateNodeData("model", modelId);
  if (model?.is_reasoning) {
    updateNodeData("isReasoningModel", true);
    if (!workflowStore.selectedNode?.data.reasoningEffort) {
      updateNodeData("reasoningEffort", "medium");
    }
  } else {
    updateNodeData("isReasoningModel", false);
  }
  if (selectedNode.value?.type === "llm" && model?.supports_batch !== true) {
    updateNodeData("batchModeEnabled", false);
  }
}

function handleCredentialChange(credentialId: string | undefined): void {
  if (!credentialId) return;
  updateNodeData("credentialId", credentialId);
  updateNodeData("model", "");
  if (selectedNode.value?.type === "llm") {
    updateNodeData("batchModeEnabled", false);
  }
}

function handleLlmOutputTypeChange(outputType: string | undefined): void {
  updateNodeData("outputType", outputType || "text");
  if (outputType === "image" && selectedNode.value?.type === "llm") {
    updateNodeData("batchModeEnabled", false);
  }
}

function handleLlmImageInputChange(enabled: boolean): void {
  updateNodeData("imageInputEnabled", enabled);
  if (enabled && selectedNode.value?.type === "llm") {
    updateNodeData("batchModeEnabled", false);
  }
}

function handleLlmBatchModeChange(enabled: boolean): void {
  updateNodeData("batchModeEnabled", enabled);
  if (enabled) {
    updateNodeData("outputType", "text");
    if (selectedNode.value?.type === "llm" && selectedNode.value.data.imageInputEnabled) {
      updateNodeData("imageInputEnabled", false);
    }
  }
}

watch(
  () => ({
    nodeType: selectedNode.value?.type,
    batchModeEnabled: selectedNode.value?.data.batchModeEnabled,
    batchModeAvailable: llmBatchModeAvailable.value,
    loadingModels: loadingModels.value,
    isImageOutput: isImageOutputMode.value,
    imageInputEnabled:
      selectedNode.value?.type === "llm" ? !!selectedNode.value.data.imageInputEnabled : false,
    modelId:
      selectedNode.value?.type === "llm"
        ? (selectedNode.value.data.model as string | undefined)
        : undefined,
    modelsCount: llmModels.value.length,
  }),
  (state) => {
    if (state.nodeType !== "llm" || !state.batchModeEnabled) return;
    if (state.loadingModels) return;
    if (state.batchModeAvailable) return;

    if (state.isImageOutput || state.imageInputEnabled) {
      updateNodeData("batchModeEnabled", false);
      return;
    }

    if (!state.modelId || state.modelsCount === 0) return;

    const resolved = llmModels.value.find((m) => m.id === state.modelId);
    if (!resolved) return;

    if (resolved.supports_batch !== true) {
      updateNodeData("batchModeEnabled", false);
    }
  },
);

const availableSubAgentLabels = computed(() => {
  const node = selectedNode.value;
  if (!node) return [];
  return workflowStore.nodes
    .filter((n) => n.type === "agent" && n.id !== node.id)
    .map((n) => n.data?.label || n.id)
    .filter((label): label is string => !!label);
});

function toggleSubAgentLabel(label: string, checked: boolean): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.subAgentLabels || [];
  if (checked) {
    if (!current.includes(label)) updateNodeData("subAgentLabels", [...current, label]);
  } else {
    updateNodeData("subAgentLabels", current.filter((l) => l !== label));
  }
}

function toggleSubWorkflowId(workflowId: string, workflowName: string, checked: boolean): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.subWorkflowIds || [];
  const names = { ...(selectedNode.value.data.subWorkflowNames || {}) };
  if (checked) {
    if (!current.includes(workflowId)) {
      updateNodeData("subWorkflowIds", [...current, workflowId]);
      names[workflowId] = workflowName;
      updateNodeData("subWorkflowNames", names);
    }
  } else {
    updateNodeData("subWorkflowIds", current.filter((id) => id !== workflowId));
    delete names[workflowId];
    updateNodeData("subWorkflowNames", names);
  }
}

function openSubWorkflowEditor(workflowId: string): void {
  const href = router.resolve({ name: "editor", params: { id: workflowId } }).href;
  window.open(href, "_blank", "noopener,noreferrer");
}

function openDataTableInNewTab(tableId: string): void {
  const id = tableId.trim();
  if (!id) return;
  const href = router.resolve({
    name: "dashboard",
    query: { tab: `datatable/${id}` },
  }).href;
  window.open(href, "_blank", "noopener,noreferrer");
}

function addAgentTool(): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.tools || [];
  updateNodeData("tools", [
    ...current,
    {
      name: "",
      description: "",
      parameters: '{"type":"object","properties":{},"required":[]}',
      code: "",
    },
  ]);
}

function removeAgentTool(index: number): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.tools || [])];
  current.splice(index, 1);
  updateNodeData("tools", current);
}

function updateAgentTool(
  index: number,
  field: "name" | "description" | "parameters" | "code",
  value: string
): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.tools || [])];
  if (current[index]) {
    current[index] = { ...current[index], [field]: value };
    updateNodeData("tools", current);
  }
}

function addAgentMCPConnection(): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.mcpConnections || [];
  const id = crypto.randomUUID();
  updateNodeData("mcpConnections", [
    ...current,
    {
      id,
      transport: "stdio" as MCPTransportType,
      label: "",
      timeoutSeconds: 30,
      command: "",
      args: [],
    },
  ]);
}

function removeAgentMCPConnection(index: number): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.mcpConnections || [])];
  current.splice(index, 1);
  updateNodeData("mcpConnections", current);
}

function updateAgentMCPConnection(
  index: number,
  field: keyof AgentMCPConnection,
  value: string | number | string[] | Record<string, string> | undefined
): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.mcpConnections || [])];
  if (current[index]) {
    current[index] = { ...current[index], [field]: value };
    updateNodeData("mcpConnections", current);
  }
}

function addAgentSkill(): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.skills || [];
  updateNodeData("skills", [
    ...current,
    {
      id: crypto.randomUUID(),
      name: "",
      content: "",
      files: [],
      timeoutSeconds: 30,
    },
  ]);
}

function removeAgentSkill(index: number): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.skills || [])];
  current.splice(index, 1);
  updateNodeData("skills", current);
}

function updateAgentSkill(
  index: number,
  field: keyof AgentSkill,
  value: string | number | AgentSkillFile[] | undefined
): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.skills || [])];
  if (current[index]) {
    current[index] = { ...current[index], [field]: value };
    updateNodeData("skills", current);
  }
}

function updateAgentSkillFile(
  skillIndex: number,
  fileIndex: number,
  field: keyof AgentSkillFile,
  value: string
): void {
  if (!selectedNode.value) return;
  const skills = [...(selectedNode.value.data.skills || [])];
  const skill = skills[skillIndex];
  if (!skill?.files) return;
  const files = [...skill.files];
  if (files[fileIndex]) {
    files[fileIndex] = { ...files[fileIndex], [field]: value };
    updateAgentSkill(skillIndex, "files", files);
  }
}

function removeAgentSkillFile(skillIndex: number, fileIndex: number): void {
  if (!selectedNode.value) return;
  const skills = [...(selectedNode.value.data.skills || [])];
  const skill = skills[skillIndex];
  if (!skill?.files) return;

  updateAgentSkill(
    skillIndex,
    "files",
    skill.files.filter((_, index) => index !== fileIndex),
  );
}

const skillZipLoading = ref(false);
const skillZipError = ref("");
const skillDownloadLoadingId = ref<string | null>(null);
const skillBuilderOpen = ref(false);
const skillBuilderTargetSkill = ref<AgentSkill | null>(null);

function upsertAgentSkills(parsedSkills: AgentSkill[], replaceSkillId?: string): void {
  if (!selectedNode.value) return;

  const currentSkills = selectedNode.value.data.skills || [];
  if (!replaceSkillId) {
    updateNodeData("skills", [...currentSkills, ...parsedSkills]);
    return;
  }

  const replaceIndex = currentSkills.findIndex((skill) => skill.id === replaceSkillId);
  if (replaceIndex >= 0) {
    const originalSkill = currentSkills[replaceIndex];
    const replacementSkills = parsedSkills.map((skill, index) =>
      index === 0
        ? {
            ...skill,
            id: originalSkill.id,
            timeoutSeconds: skill.timeoutSeconds ?? originalSkill.timeoutSeconds ?? 30,
          }
        : skill,
    );
    const nextSkills = [...currentSkills];
    nextSkills.splice(replaceIndex, 1, ...replacementSkills);
    updateNodeData("skills", nextSkills);
    return;
  }

  const replacementNames = new Set(parsedSkills.map((skill) => skill.name));
  updateNodeData(
    "skills",
    [
      ...currentSkills.filter((skill) => !replacementNames.has(skill.name)),
      ...parsedSkills,
    ],
  );
}

async function applySkillFile(file: File, replaceSkillId?: string): Promise<void> {
  if (!selectedNode.value) return;

  const name = file.name.toLowerCase();
  if (name.endsWith(".zip")) {
    const parsed = await parseSkillZip(file);
    if (parsed.length === 0) {
      throw new Error("Invalid skill zip: missing SKILL.md");
    }
    upsertAgentSkills(parsed, replaceSkillId);
    return;
  }

  if (name.endsWith(".md")) {
    const skillName = name.replace(/\.md$/i, "") || "skill";
    upsertAgentSkills(
      [
        {
          id: crypto.randomUUID(),
          name: skillName,
          content: await file.text(),
          files: [],
          timeoutSeconds: 30,
        },
      ],
      replaceSkillId,
    );
    return;
  }

  throw new Error("Only .zip or .md files are supported");
}

async function handleSkillZipDrop(file: File): Promise<void> {
  skillZipLoading.value = true;
  skillZipError.value = "";
  try {
    await applySkillFile(file);
  } catch (e) {
    skillZipError.value = e instanceof Error ? e.message : "Failed to parse file";
    showToast(skillZipError.value, "error");
  } finally {
    skillZipLoading.value = false;
  }
}

function triggerSkillZipDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

async function downloadAgentSkill(skill: AgentSkill): Promise<void> {
  if (skillDownloadLoadingId.value) {
    return;
  }

  skillDownloadLoadingId.value = skill.id;
  skillZipError.value = "";

  try {
    const blob = await createAgentSkillZipBlob(skill);
    triggerSkillZipDownload(blob, getSkillZipFileName(skill.name || "skill"));
    showToast("Skill downloaded", "success");
  } catch (e) {
    skillZipError.value = e instanceof Error ? e.message : "Failed to download skill";
    showToast(skillZipError.value, "error");
  } finally {
    skillDownloadLoadingId.value = null;
  }
}

function isTextSkillFile(file: AgentSkillFile): boolean {
  return (file.encoding ?? "text") === "text";
}

function isImageSkillFile(file: AgentSkillFile): boolean {
  return (file.mimeType || "").startsWith("image/");
}

function getSkillFilePreviewSrc(file: AgentSkillFile): string {
  if (!isImageSkillFile(file) || (file.encoding ?? "text") !== "base64") {
    return "";
  }
  return `data:${file.mimeType};base64,${file.content}`;
}

const expandedSkillIds = ref<Set<string>>(new Set());

function toggleSkillExpanded(id: string): void {
  const next = new Set(expandedSkillIds.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedSkillIds.value = next;
}

function openSkillBuilderNew(): void {
  skillBuilderTargetSkill.value = null;
  skillBuilderOpen.value = true;
}

function openSkillBuilderEdit(skill: AgentSkill): void {
  skillBuilderTargetSkill.value = skill;
  skillBuilderOpen.value = true;
}

async function handleSkillBuilderSave(file: File): Promise<void> {
  const replaceSkillId = skillBuilderTargetSkill.value?.id;
  const successMessage = replaceSkillId ? "Skill updated" : "Skill added";

  skillZipLoading.value = true;
  skillZipError.value = "";
  try {
    await applySkillFile(file, replaceSkillId);
    showToast(successMessage, "success");
    skillBuilderOpen.value = false;
    skillBuilderTargetSkill.value = null;
  } catch (e) {
    skillZipError.value = e instanceof Error ? e.message : "Failed to save generated skill";
    showToast(skillZipError.value, "error");
  } finally {
    skillZipLoading.value = false;
  }
}

watch(skillBuilderOpen, (isOpen: boolean) => {
  if (!isOpen) {
    skillBuilderTargetSkill.value = null;
  }
});

interface MCPFetchState {
  loading: boolean;
  error: string | null;
  tools: { name: string; description: string }[];
}
const mcpFetchState = ref<Record<string, MCPFetchState>>({});

function getMCPFetchState(connId: string): MCPFetchState {
  return (
    mcpFetchState.value[connId] ?? {
      loading: false,
      error: null,
      tools: [],
    }
  );
}

async function fetchMCPTools(conn: AgentMCPConnection, _index: number): Promise<void> {
  const id = conn.id;
  mcpFetchState.value = {
    ...mcpFetchState.value,
    [id]: { loading: true, error: null, tools: [] },
  };

  const connection = {
    id: conn.id,
    transport: conn.transport,
    label: conn.label,
    timeoutSeconds: conn.timeoutSeconds ?? 30,
    command: conn.command,
    args: conn.args,
    env: conn.env,
    url: conn.url,
    headers: conn.headers,
  };

  try {
    const res = await mcpApi.fetchTools(connection);
    mcpFetchState.value = {
      ...mcpFetchState.value,
      [id]: { loading: false, error: null, tools: res.tools },
    };
  } catch (e: unknown) {
    const msg = e && typeof e === "object" && "response" in e
      ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
      : String(e);
    mcpFetchState.value = {
      ...mcpFetchState.value,
      [id]: { loading: false, error: msg || "Failed to connect", tools: [] },
    };
  }
}

function formatJsonSchema(): void {
  if (!selectedNode.value) return;
  const schema = selectedNode.value.data.jsonOutputSchema;
  if (!schema || typeof schema !== "string") return;

  try {
    const parsed = JSON.parse(schema);
    const formatted = JSON.stringify(parsed, null, 2);
    updateNodeData("jsonOutputSchema", formatted);
    jsonFormatError.value = false;
  } catch {
    jsonFormatError.value = true;
    setTimeout(() => {
      jsonFormatError.value = false;
    }, 2000);
  }
}

function updateNodeData(key: string, value: unknown): void {
  if (!selectedNode.value) return;
  workflowStore.updateNode(selectedNode.value.id, { [key]: value });
}

function toggleWebSocketTriggerEvent(
  eventName: WebSocketTriggerEventName,
  enabled: boolean,
): void {
  const node = selectedNode.value;
  if (!node || node.type !== "websocketTrigger") return;

  const currentEvents = node.data.websocketTriggerEvents || [];
  const nextEvents = enabled
    ? Array.from(new Set([...currentEvents, eventName]))
    : currentEvents.filter((value) => value !== eventName);
  updateNodeData("websocketTriggerEvents", nextEvents);
}

function isValidCamelCase(str: string): boolean {
  return /^[a-z][a-zA-Z0-9]*$/.test(str);
}

function handleLabelChange(value: string): void {
  if (!selectedNode.value) return;

  const sanitized = value.replace(/[^a-zA-Z0-9]/g, "");

  if (sanitized.length === 0) {
    labelError.value = "Label cannot be empty";
    return;
  }

  const camelCase = sanitized.charAt(0).toLowerCase() + sanitized.slice(1);

  if (!isValidCamelCase(camelCase)) {
    labelError.value = "Must start with lowercase letter";
    return;
  }

  labelError.value = "";
  workflowStore.updateNode(selectedNode.value.id, { label: camelCase });
}

function handleDurationChange(value: string | number): void {
  const numValue = typeof value === "string" ? parseInt(value, 10) : value;
  const validValue = isNaN(numValue) || numValue < 1 ? 1 : Math.min(numValue, 60000);
  updateNodeData("duration", validValue);
}

function handleCasesChange(value: string): void {
  const cases = value
    .split("\n")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
  updateNodeData("cases", cases);
}

const outputSchema = computed<OutputSchemaField[]>(() => {
  if (!selectedNode.value) return [];
  return selectedNode.value.data.outputSchema || [];
});

function addOutputSchemaField(): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.outputSchema || [];
  updateNodeData("outputSchema", [...current, { key: "", value: "" }]);
}

function updateOutputSchemaField(index: number, field: "key" | "value", value: string): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.outputSchema || [])];
  current[index] = { ...current[index], [field]: value };
  updateNodeData("outputSchema", current);
}

function removeOutputSchemaField(index: number): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.outputSchema || [])];
  current.splice(index, 1);
  updateNodeData("outputSchema", current);
}

const outputExpressionFieldCount = computed((): number => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "output") {
    return 1;
  }
  const schemaLen = (n.data.outputSchema || []).length;
  if (schemaLen > 0) {
    return schemaLen;
  }
  return 1;
});

function setOutputSchemaValueInputRef(index: number, el: unknown): void {
  if (el) {
    outputSchemaValueInputRefs.value.set(index, el as InstanceType<typeof ExpressionInput>);
  } else {
    outputSchemaValueInputRefs.value.delete(index);
  }
}

function openOutputExpressionFieldAtIndex(index: number): void {
  const n = selectedNode.value;
  if (!n || n.type !== "output") {
    return;
  }
  currentOutputExpressionFieldIndex.value = index;
  const schemaLen = (n.data.outputSchema || []).length;
  if (schemaLen > 0) {
    outputSchemaValueInputRefs.value.get(index)?.openExpandDialog();
  } else {
    outputMessageInputRef.value?.openExpandDialog();
  }
}

function handleOutputExpressionFieldNavigate(direction: "prev" | "next"): void {
  const n = selectedNode.value;
  if (!n || n.type !== "output") {
    return;
  }
  const total = outputExpressionFieldCount.value;
  if (total <= 1) {
    return;
  }
  const newIndex =
    direction === "prev"
      ? currentOutputExpressionFieldIndex.value - 1
      : currentOutputExpressionFieldIndex.value + 1;
  if (newIndex < 0 || newIndex >= total) {
    return;
  }
  outputMessageInputRef.value?.closeExpandDialog();
  for (const input of outputSchemaValueInputRefs.value.values()) {
    input.closeExpandDialog();
  }
  currentOutputExpressionFieldIndex.value = newIndex;
  nextTick(() => {
    openOutputExpressionFieldAtIndex(newIndex);
  });
}

function onOutputRegisterExpressionFieldIndex(index: number): void {
  currentOutputExpressionFieldIndex.value = index;
}

const mappings = computed<MappingField[]>(() => {
  if (!selectedNode.value) return [];
  return selectedNode.value.data.mappings || [];
});

function addMappingField(): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.mappings || [];
  updateNodeData("mappings", [...current, { key: "", value: "" }]);
}

function updateMappingField(index: number, field: "key" | "value", value: string): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.mappings || [])];
  current[index] = { ...current[index], [field]: value };
  updateNodeData("mappings", current);
}

function removeMappingField(index: number): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.mappings || [])];
  current.splice(index, 1);
  updateNodeData("mappings", current);
}

function handleSetMappingNavigate(direction: "prev" | "next"): void {
  const newIndex = direction === "prev"
    ? currentSetMappingIndex.value - 1
    : currentSetMappingIndex.value + 1;

  if (newIndex < 0 || newIndex >= mappings.value.length) return;

  const currentRef = setMappingInputRefs.value.get(currentSetMappingIndex.value);
  if (currentRef) {
    currentRef.closeExpandDialog();
  }

  currentSetMappingIndex.value = newIndex;
  nextTick(() => {
    const inputRef = setMappingInputRefs.value.get(newIndex);
    if (inputRef) {
      inputRef.openExpandDialog();
    }
  });
}

function setMappingInputRef(index: number, el: InstanceType<typeof ExpressionInput> | null): void {
  if (el) {
    setMappingInputRefs.value.set(index, el);
  } else {
    setMappingInputRefs.value.delete(index);
  }
}

const bqMappings = computed<Array<{ key: string; value: string }>>(() => {
  if (!selectedNode.value) return [];
  return (selectedNode.value.data.bqMappings as Array<{ key: string; value: string }> | undefined) || [];
});

function addBqMapping(): void {
  if (!selectedNode.value) return;
  const current = bqMappings.value;
  updateNodeData("bqMappings", [...current, { key: "", value: "" }]);
}

function updateBqMapping(index: number, field: "key" | "value", value: string): void {
  if (!selectedNode.value) return;
  const current = [...bqMappings.value];
  current[index] = { ...current[index], [field]: value };
  updateNodeData("bqMappings", current);
}

function removeBqMapping(index: number): void {
  if (!selectedNode.value) return;
  const current = [...bqMappings.value];
  current.splice(index, 1);
  updateNodeData("bqMappings", current);
}

function switchBqToRaw(): void {
  const mappings = bqMappings.value;
  if (mappings.length > 0) {
    const row: Record<string, string> = {};
    for (const m of mappings) {
      if (m.key) row[m.key] = m.value;
    }
    updateNodeData("bqRows", JSON.stringify([row], null, 2));
  }
  updateNodeData("bqRowsInputMode", "raw");
}

const executeMappings = computed(() => {
  if (!selectedNode.value) return [];
  return selectedNode.value.data.executeInputMappings || [];
});

function handleExecuteMappingNavigate(direction: "prev" | "next"): void {
  const newIndex = direction === "prev"
    ? currentExecuteMappingIndex.value - 1
    : currentExecuteMappingIndex.value + 1;

  if (newIndex < 0 || newIndex >= executeMappings.value.length) return;

  const currentRef = executeMappingInputRefs.value.get(currentExecuteMappingIndex.value);
  if (currentRef) {
    currentRef.closeExpandDialog();
  }

  currentExecuteMappingIndex.value = newIndex;
  nextTick(() => {
    const inputRef = executeMappingInputRefs.value.get(newIndex);
    if (inputRef) {
      inputRef.openExpandDialog();
    }
  });
}

function setExecuteMappingInputRef(index: number, el: InstanceType<typeof ExpressionInput> | null): void {
  if (el) {
    executeMappingInputRefs.value.set(index, el);
  } else {
    executeMappingInputRefs.value.delete(index);
  }
}

const inputFields = computed<InputField[]>(() => {
  if (!selectedNode.value) return [];
  return selectedNode.value.data.inputFields || [];
});

function addInputField(): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.inputFields || [];
  const newKey = current.length === 0 ? "text" : `field${current.length + 1}`;
  updateNodeData("inputFields", [...current, { key: newKey }]);
}

function updateInputField(index: number, field: keyof InputField, value: string): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.inputFields || [])];
  current[index] = { ...current[index], [field]: value };
  updateNodeData("inputFields", current);
}

function removeInputField(index: number): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.inputFields || [])];
  current.splice(index, 1);
  updateNodeData("inputFields", current);
}

function pinNodeOutput(): void {
  if (!selectedNode.value) return;

  if (isEditingPinnedData.value) {
    try {
      const parsed = JSON.parse(editedPinnedData.value);
      updateNodeData("pinnedData", parsed);
      isEditingPinnedData.value = false;
    } catch {
      return;
    }
    return;
  }

  if (!nodeOutput.value) return;
  updateNodeData("pinnedData", nodeOutput.value.output);
}

function clearPinnedData(): void {
  if (!selectedNode.value) return;
  updateNodeData("pinnedData", null);
  isEditingPinnedData.value = false;
}

function startEditingPinnedData(): void {
  if (!pinnedData.value) return;
  editedPinnedData.value = JSON.stringify(pinnedData.value, null, 2);
  isEditingPinnedData.value = true;
}

function cancelEditingPinnedData(): void {
  isEditingPinnedData.value = false;
  editedPinnedData.value = "";
}

function updateInputCount(delta: number): void {
  if (!selectedNode.value) return;
  const current = selectedNode.value.data.inputCount || 2;
  const newValue = Math.max(2, Math.min(10, current + delta));
  updateNodeData("inputCount", newValue);
}


function deleteNode(): void {
  if (!selectedNode.value) return;
  if (!confirm("Are you sure you want to delete this node?")) return;
  workflowStore.removeNode(selectedNode.value.id);
}

async function handleExecute(): Promise<void> {
  const validation = workflowStore.validateWorkflow();
  if (!validation.isValid) {
    validationErrors.value = validation.errors;
    showValidationDialog.value = true;
    return;
  }

  const executeTargetValidation = await workflowStore.validateExecuteTargetsExist();
  if (!executeTargetValidation.isValid) {
    validationErrors.value = executeTargetValidation.errors;
    showValidationDialog.value = true;
    return;
  }

  if (runBodyError.value) {
    return;
  }

  const body = workflowStore.buildExecutionRequestBody();
  await workflowStore.executeWorkflow(body);
}

function closeValidationDialog(): void {
  showValidationDialog.value = false;
  validationErrors.value = [];
}

function selectNodeFromError(nodeId: string): void {
  workflowStore.selectNode(nodeId);
  activeTab.value = "properties";
  closeValidationDialog();
}

function sanitizeForDisplay(data: unknown): unknown {
  if (data === null || data === undefined) return data;
  if (typeof data === "string") {
    if (data.startsWith("data:image/") && data.length > 100) {
      return "[Image Data - base64]";
    }
    if (data.length > 100 && /^[A-Za-z0-9+/=]+$/.test(data)) {
      return "[Base64 data]";
    }
    return data;
  }
  if (Array.isArray(data)) {
    return data.map(sanitizeForDisplay);
  }
  if (typeof data === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(data)) {
      result[key] = sanitizeForDisplay(value);
    }
    return result;
  }
  return data;
}

function formatOutput(output: unknown): string {
  if (output === null || output === undefined) {
    return "null";
  }
  if (typeof output === "string") {
    if (output.startsWith("data:image/") && output.length > 100) {
      return "[Image Data - base64]";
    }
    return output;
  }
  try {
    return JSON.stringify(output, null, 2);
  } catch {
    return String(output);
  }
}

async function copyLastNodeOutput(): Promise<void> {
  if (!lastExecutedNode.value) return;
  const text = formatOutput(lastExecutedNode.value.output);
  await navigator.clipboard.writeText(text);
  copiedOutput.value = true;
  setTimeout(() => {
    copiedOutput.value = false;
  }, 2000);
}

const displayPinnedData = computed(() => {
  if (!pinnedData.value) return null;
  return sanitizeForDisplay(pinnedData.value);
});

const displayNodeOutput = computed(() => {
  if (!nodeOutput.value?.output) return null;
  return sanitizeForDisplay(nodeOutput.value.output);
});

/** All image srcs for display: image gen (output.image) or Playwright screenshots (output.results, output.screenshot). */
const nodeOutputImageSrcs = computed((): string[] => {
  const out = nodeOutput.value?.output as Record<string, unknown> | undefined;
  if (!out) return [];
  const srcs: string[] = [];
  const img = out.image;
  if (typeof img === "string" && (img.startsWith("data:image/") || img.startsWith("http"))) {
    srcs.push(img);
  }
  const shot = out.screenshot;
  if (typeof shot === "string" && shot.length > 100) {
    srcs.push(`data:image/png;base64,${shot}`);
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
});

const imageLightboxSrc = ref<string | null>(null);


async function copyOutput(): Promise<void> {
  if (!nodeOutput.value) return;
  const text = JSON.stringify(nodeOutput.value.output, null, 2);
  await navigator.clipboard.writeText(text);
  copied.value = true;
  setTimeout(() => {
    copied.value = false;
  }, 2000);
}

const canVisitWorkflow = computed(() => {
  if (!selectedNode.value) return false;
  if (selectedNode.value.type !== "execute") return false;
  return !!selectedNode.value.data.executeWorkflowId;
});

function visitWorkflow(): void {
  if (!canVisitWorkflow.value || !selectedNode.value) return;
  const workflowId = selectedNode.value.data.executeWorkflowId;
  if (workflowId) {
    const href = router.resolve({ name: "editor", params: { id: workflowId } }).href;
    window.open(href, "_blank", "noopener,noreferrer");
  }
}

function updateExecuteMapping(index: number, value: string): void {
  if (!selectedNode.value) return;
  const current = [...(selectedNode.value.data.executeInputMappings || [])];
  if (current[index]) {
    current[index] = { ...current[index], value };
    updateNodeData("executeInputMappings", current);
  }
}

function handleKeyDown(e: KeyboardEvent): void {
  if (e.key === "Escape" && isLastOutputExpanded.value) {
    e.preventDefault();
    e.stopImmediatePropagation();
    isLastOutputExpanded.value = false;
    return;
  }
  if (e.key === "Escape" && isOutputExpanded.value) {
    e.preventDefault();
    e.stopImmediatePropagation();
    isOutputExpanded.value = false;
    return;
  }
  if (e.key === "Escape" && imageLightboxSrc.value) {
    e.stopPropagation();
    imageLightboxSrc.value = null;
    return;
  }
  if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
    if (canVisitWorkflow.value) {
      e.preventDefault();
      visitWorkflow();
    }
  }
}

let unsubDismissOverlays: (() => void) | null = null;

onMounted(() => {
  unsubDismissOverlays = onDismissOverlays(() => {
    isLastOutputExpanded.value = false;
    isOutputExpanded.value = false;
  });
  window.addEventListener("keydown", handleKeyDown, true);
  loadReservedVariableNames();
});

onUnmounted(() => {
  unsubDismissOverlays?.();
  unsubDismissOverlays = null;
  window.removeEventListener("keydown", handleKeyDown, true);
  workflowStore.setExpressionGraphNavigateHandler(null);
});
</script>

<template>
  <div
    class="properties-panel w-80 sm:w-72 md:w-80 border-l border-border/30 flex flex-col max-w-full overflow-x-hidden"
  >
    <div class="flex border-b border-border/30 p-1 gap-1 bg-muted/20">
      <button
        :class="cn(
          'flex-1 px-3 py-2 min-h-[44px] text-sm font-medium transition-all flex items-center justify-center gap-2 rounded-lg',
          activeTab === 'properties'
            ? 'text-primary bg-primary/10 shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
        )"
        @click="activeTab = 'properties'"
      >
        <Settings class="w-4 h-4" />
        <span class="hidden md:inline">Properties</span>
      </button>
      <button
        :class="cn(
          'flex-1 px-3 py-2 min-h-[44px] text-sm font-medium transition-all flex items-center justify-center gap-2 rounded-lg',
          activeTab === 'config'
            ? 'text-primary bg-primary/10 shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
        )"
        @click="activeTab = 'config'"
      >
        <Zap class="w-4 h-4" />
        <span class="hidden md:inline">Run</span>
      </button>
    </div>

    <div
      v-if="activeTab === 'properties'"
      class="flex-1 flex flex-col overflow-hidden overflow-x-hidden"
    >
      <div
        v-if="!selectedNode"
        class="flex-1 flex items-center justify-center p-8 text-center"
      >
        <div class="text-muted-foreground">
          <Settings class="w-10 h-10 mx-auto mb-3 opacity-50" />
          <p class="text-sm">
            Select a node to view its properties
          </p>
        </div>
      </div>

      <div
        v-else
        class="flex flex-col h-full overflow-hidden overflow-x-hidden"
      >
        <div
          class="p-4 border-b flex items-center justify-between shrink-0"
          :style="{
            backgroundColor: `hsl(var(--${nodeColorMap[selectedNode.type]}) / 0.15)`,
          }"
        >
          <div class="flex items-center gap-3 min-w-0">
            <div
              class="flex items-center justify-center w-9 h-9 rounded-lg shrink-0"
              :style="{
                backgroundColor: `hsl(var(--${nodeColorMap[selectedNode.type]}) / 0.2)`,
                color: `hsl(var(--${nodeColorMap[selectedNode.type]}))`,
              }"
            >
              <component
                :is="nodeIcons[selectedNode.type]"
                class="w-5 h-5"
              />
            </div>
            <div class="flex flex-col min-w-0">
              <h2 class="font-semibold text-sm truncate">
                {{ selectedNode.data.label }}
              </h2>
              <div class="flex items-center gap-1.5">
                <span
                  class="text-xs text-muted-foreground"
                  :style="{ color: `hsl(var(--${nodeColorMap[selectedNode.type]}) / 0.8)` }"
                >{{ selectedNode.type
                }}</span>
                <span
                  v-if="!isNodeActive"
                  class="text-[10px] text-gray-500 bg-gray-800 px-1 py-0.5 rounded"
                >disabled</span>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-0.5 shrink-0 -mr-2">
            <Button
              variant="ghost"
              size="icon"
              class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8 text-muted-foreground hover:text-foreground"
              title="View documentation"
              @click.prevent="$router.push(`/docs/nodes/${nodeDocSlugMap[selectedNode.type]}`)"
            >
              <BookOpen class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
              :class="isNodeActive ? 'text-green-500 hover:text-green-600' : 'text-gray-500 hover:text-gray-400'"
              :title="isNodeActive ? 'Disable node (D)' : 'Enable node (D)'"
              @click="toggleActive"
            >
              <Power class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="text-destructive h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
              @click="deleteNode"
            >
              <Trash2 class="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div class="flex-1 overflow-auto overflow-x-hidden p-4 space-y-4">
          <div class="space-y-2">
            <Label>Label</Label>
            <Input
              :model-value="selectedNode.data.label"
              placeholder="camelCaseOnly"
              :class="{ 'border-red-500 focus:ring-red-500': reservedLabelError }"
              @update:model-value="handleLabelChange($event)"
            />
            <p
              v-if="reservedLabelError"
              class="text-xs text-red-500 flex items-center gap-1"
            >
              <AlertTriangle class="h-3 w-3" />
              {{ reservedLabelError }}
            </p>
            <p
              v-else-if="labelError"
              class="text-xs text-red-500"
            >
              {{ labelError }}
            </p>
            <p
              v-else
              class="text-xs text-muted-foreground"
            >
              camelCase only (no spaces/special chars)
            </p>
          </div>

          <template v-if="selectedNode.type === 'textInput'">
            <div class="space-y-3">
              <template v-if="!isGenericWebhookBodyMode">
                <div class="flex items-center justify-between">
                  <Label>Input Fields</Label>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-11 min-h-[44px] md:h-7 px-2"
                    @click="addInputField"
                  >
                    <Plus class="w-3 h-3 mr-1" />
                    Add
                  </Button>
                </div>
                <div
                  v-for="(field, index) in inputFields"
                  :key="index"
                  class="space-y-1"
                >
                  <div class="flex gap-1.5 items-center">
                    <Input
                      :model-value="field.key"
                      placeholder="key"
                      :class="[
                        'w-24 shrink-0 font-mono text-xs',
                        getInputFieldError(field.key) ? 'border-red-500 focus:ring-red-500' : ''
                      ]"
                      @update:model-value="updateInputField(index, 'key', $event)"
                    />
                    <Input
                      :model-value="field.defaultValue || ''"
                      placeholder="default (optional)"
                      class="flex-1 text-xs"
                      @update:model-value="updateInputField(index, 'defaultValue', $event)"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8 text-destructive shrink-0"
                      @click="removeInputField(index)"
                    >
                      <Minus class="w-3 h-3" />
                    </Button>
                  </div>
                  <p
                    v-if="getInputFieldError(field.key)"
                    class="text-xs text-red-500 flex items-center gap-1 ml-1"
                  >
                    <AlertTriangle class="h-3 w-3" />
                    {{ getInputFieldError(field.key) }}
                  </p>
                </div>
                <p class="text-xs text-muted-foreground">
                  Access via ${{ selectedNode.data.label }}.body.key
                </p>
              </template>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Generic webhook mode keeps the incoming request body as raw JSON, so input field add/remove controls are hidden here. Access request data through ${{ selectedNode.data.label }}.body.*
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'cron'">
            <div class="space-y-2">
              <Label>Cron Expression</Label>
              <Input
                :model-value="selectedNode.data.cronExpression || ''"
                placeholder="0 * * * *"
                @update:model-value="updateNodeData('cronExpression', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use standard cron format to define the schedule.
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'telegramTrigger'">
            <div class="space-y-4">
              <div class="space-y-2">
                <Label>Telegram Credential</Label>
                <Select
                  :model-value="selectedNode.data.credentialId || ''"
                  :options="telegramTriggerCredentialOptions"
                  placeholder="Select Telegram credential"
                  @update:model-value="updateNodeData('credentialId', $event)"
                />
                <p
                  v-if="!selectedNode.data.credentialId"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  No Telegram credential set — bot-specific verification is disabled
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Uses the selected bot token for downstream sends and optionally verifies the Telegram secret token header on incoming webhooks.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Webhook URL</Label>
                <div class="flex gap-2">
                  <Input
                    :model-value="telegramTriggerWebhookUrl"
                    readonly
                    class="font-mono text-xs"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    @click="copyTelegramWebhookUrl"
                  >
                    Copy
                  </Button>
                </div>
                <p class="text-xs text-muted-foreground">
                  Register this URL with Telegram's <code>setWebhook</code> API for your bot. Reuse the same credential if you also send messages downstream.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-xs text-muted-foreground">Available output fields</Label>
                <div class="text-xs text-muted-foreground space-y-1 font-mono">
                  <div>${{ selectedNode.data.label }}.update — full Telegram update payload</div>
                  <div>${{ selectedNode.data.label }}.message — primary message-like object</div>
                  <div>${{ selectedNode.data.label }}.message.text — incoming message text</div>
                  <div>${{ selectedNode.data.label }}.message.chat.id — destination chat ID</div>
                  <div>${{ selectedNode.data.label }}.callback_query — callback query payload when present</div>
                  <div>${{ selectedNode.data.label }}.headers — sanitized webhook headers</div>
                  <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'slackTrigger'">
            <div class="space-y-4">
              <div class="space-y-2">
                <Label>Signing Secret Credential</Label>
                <Select
                  :model-value="selectedNode.data.credentialId || ''"
                  :options="slackTriggerCredentials.map((c) => ({ value: c.id, label: c.name }))"
                  placeholder="Select Slack Trigger credential"
                  @update:model-value="updateNodeData('credentialId', $event)"
                />
                <p
                  v-if="!selectedNode.data.credentialId"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  No credential set — requests will not be verified
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Used to verify incoming Slack request signatures
                </p>
              </div>

              <div class="space-y-2">
                <Label>Webhook URL</Label>
                <div class="flex gap-2">
                  <Input
                    :model-value="slackTriggerWebhookUrl"
                    readonly
                    class="font-mono text-xs"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    @click="copySlackWebhookUrl"
                  >
                    Copy
                  </Button>
                </div>
                <p class="text-xs text-muted-foreground">
                  Paste this URL into your Slack App → Event Subscriptions → Request URL.
                  The challenge is verified automatically.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-xs text-muted-foreground">Available output fields</Label>
                <div class="text-xs text-muted-foreground space-y-1 font-mono">
                  <div>${{ selectedNode.data.label }}.event — full Slack event object</div>
                  <div>${{ selectedNode.data.label }}.event.type — event type</div>
                  <div>${{ selectedNode.data.label }}.event.text — message text</div>
                  <div>${{ selectedNode.data.label }}.event.user — Slack user ID</div>
                  <div>${{ selectedNode.data.label }}.headers — HTTP headers</div>
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'imapTrigger'">
            <div class="space-y-4">
              <div class="space-y-2">
                <Label>IMAP Credential</Label>
                <Select
                  :model-value="selectedNode.data.credentialId || ''"
                  :options="imapTriggerCredentialOptions"
                  placeholder="Select IMAP credential"
                  @update:model-value="updateNodeData('credentialId', $event)"
                />
                <p
                  v-if="!selectedNode.data.credentialId"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  No IMAP credential set — inbox polling is disabled
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Heym logs in to this mailbox and checks for new email on the interval below.
                </p>
              </div>

              <div class="space-y-2">
                <Label for="imap-poll-interval">Poll Interval (Minutes)</Label>
                <Input
                  id="imap-poll-interval"
                  :model-value="String(selectedNode.data.pollIntervalMinutes ?? 5)"
                  type="number"
                  min="1"
                  step="1"
                  @update:model-value="updateNodeData('pollIntervalMinutes', Number.parseInt($event, 10) || 1)"
                />
                <p class="text-xs text-muted-foreground">
                  Minimum 1 minute. First poll baselines the current inbox, then only newer emails trigger runs.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-xs text-muted-foreground">Available output fields</Label>
                <div class="text-xs text-muted-foreground space-y-1 font-mono">
                  <div>${{ selectedNode.data.label }}.email.subject — decoded email subject</div>
                  <div>${{ selectedNode.data.label }}.email.from — raw from header</div>
                  <div>${{ selectedNode.data.label }}.email.text — plain-text body</div>
                  <div>${{ selectedNode.data.label }}.email.html — HTML body</div>
                  <div>${{ selectedNode.data.label }}.email.attachments — attachment metadata array</div>
                  <div>${{ selectedNode.data.label }}.email.headers — decoded header map</div>
                  <div>${{ selectedNode.data.label }}.email.uid — IMAP UID for deduping</div>
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'websocketTrigger'">
            <div class="space-y-4">
              <div class="space-y-2">
                <Label>WebSocket URL</Label>
                <Input
                  :model-value="selectedNode.data.websocketUrl || ''"
                  placeholder="wss://example.com/socket"
                  @update:model-value="updateNodeData('websocketUrl', $event)"
                />
                <p
                  v-if="!selectedNode.data.websocketUrl || selectedNode.data.websocketUrl.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  URL is required
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Heym opens an outbound client connection to this remote socket. This node does not expose a Heym webhook or server socket.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Headers (JSON object)</Label>
                <Textarea
                  :model-value="selectedNode.data.websocketHeaders || ''"
                  placeholder="{&quot;Authorization&quot;: &quot;Bearer token&quot;}"
                  :rows="4"
                  class="font-mono text-xs"
                  @update:model-value="updateNodeData('websocketHeaders', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Optional handshake headers as a JSON object. Leave empty if the socket does not require custom headers.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Subprotocols</Label>
                <Input
                  :model-value="selectedNode.data.websocketSubprotocols || ''"
                  placeholder="json, graphql-ws"
                  @update:model-value="updateNodeData('websocketSubprotocols', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Optional comma-separated subprotocol list sent during the WebSocket handshake.
                </p>
              </div>

              <div class="space-y-3 pt-2 border-t">
                <Label>Emitted Events</Label>
                <div class="space-y-3">
                  <div
                    v-for="option in websocketTriggerEventOptions"
                    :key="option.value"
                    class="rounded-lg border border-border/60 p-3 space-y-1"
                  >
                    <div class="flex items-center gap-2">
                      <input
                        :id="`websocket-trigger-event-${option.value}`"
                        type="checkbox"
                        class="h-4 w-4 rounded border-input bg-background"
                        :checked="(selectedNode.data.websocketTriggerEvents || []).includes(option.value)"
                        @change="toggleWebSocketTriggerEvent(option.value, ($event.target as HTMLInputElement).checked)"
                      >
                      <Label
                        :for="`websocket-trigger-event-${option.value}`"
                        class="text-sm font-medium"
                      >
                        {{ option.label }}
                      </Label>
                    </div>
                    <p class="text-xs text-muted-foreground pl-6">
                      {{ option.description }}
                    </p>
                  </div>
                </div>
                <p
                  v-if="(selectedNode.data.websocketTriggerEvents || []).length === 0"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Select at least one emitted event
                </p>
              </div>

              <div class="space-y-3 pt-2 border-t">
                <Label>Reconnect After Drop</Label>
                <div class="flex items-center gap-2">
                  <input
                    id="websocket-trigger-retry-enabled"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="selectedNode.data.retryEnabled !== false"
                    @change="updateNodeData('retryEnabled', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="websocket-trigger-retry-enabled"
                    class="text-sm font-normal"
                  >
                    Retry when the remote socket closes
                  </Label>
                </div>

                <div
                  v-if="selectedNode.data.retryEnabled !== false"
                  class="space-y-2 pl-6"
                >
                  <Label>Retry Wait (Seconds)</Label>
                  <Input
                    type="number"
                    :model-value="selectedNode.data.retryWaitSeconds || 5"
                    min="1"
                    max="3600"
                    class="w-28"
                    @update:model-value="updateNodeData('retryWaitSeconds', $event ? parseInt($event as string) : 5)"
                  />
                  <p class="text-xs text-muted-foreground">
                    After a drop, Heym waits this many seconds before opening the connection again.
                  </p>
                </div>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Disable this to stop the trigger after the first disconnect.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-xs text-muted-foreground">Available output fields</Label>
                <div class="text-xs text-muted-foreground space-y-1 font-mono">
                  <div>${{ selectedNode.data.label }}.eventName — onMessage / onConnected / onClosed</div>
                  <div>${{ selectedNode.data.label }}.url — connected socket URL</div>
                  <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
                  <div>${{ selectedNode.data.label }}.message.data — parsed JSON or raw message body</div>
                  <div>${{ selectedNode.data.label }}.message.text — decoded text payload when available</div>
                  <div>${{ selectedNode.data.label }}.message.base64 — binary payload as base64</div>
                  <div>${{ selectedNode.data.label }}.connection.reconnected — true after a reconnect</div>
                  <div>${{ selectedNode.data.label }}.connection.subprotocol — negotiated subprotocol</div>
                  <div>${{ selectedNode.data.label }}.close.initiatedBy — server / client / unknown</div>
                  <div>${{ selectedNode.data.label }}.close.code — close code</div>
                  <div>${{ selectedNode.data.label }}.close.reason — close reason text</div>
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'llm'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="credentialOptions"
                @update:model-value="handleCredentialChange($event)"
              />
              <p
                v-if="!selectedNode.data.credentialId"
                class="text-xs text-muted-foreground"
              >
                <a
                  href="/?tab=credentials"
                  class="text-primary hover:underline"
                  @click.prevent="$router.push('/?tab=credentials')"
                >Add credentials</a> in Dashboard
              </p>
            </div>

            <div class="space-y-2">
              <Label>Model</Label>
              <Select
                :model-value="selectedNode.data.model || ''"
                :options="modelOptions"
                :disabled="!selectedNode.data.credentialId || loadingModels"
                @update:model-value="handleModelChange($event)"
              />
              <p
                v-if="loadingModels"
                class="text-xs text-muted-foreground"
              >
                Loading models...
              </p>
            </div>

            <div class="space-y-2 pt-2 border-t">
              <Label>Fallback (optional)</Label>
              <p class="text-xs text-muted-foreground">
                If primary credential/model fails, retry with fallback.
              </p>
              <Select
                :model-value="selectedNode.data.fallbackCredentialId || ''"
                :options="fallbackCredentialOptions"
                @update:model-value="handleFallbackCredentialChange($event)"
              />
              <Select
                :model-value="selectedNode.data.fallbackModel || ''"
                :options="fallbackModelOptions"
                :disabled="!selectedNode.data.fallbackCredentialId || loadingFallbackModels"
                @update:model-value="handleFallbackModelChange($event)"
              />
            </div>

            <div class="space-y-2">
              <Label>Output Type</Label>
              <Select
                :model-value="selectedNode.data.outputType || 'text'"
                :options="outputTypeOptions"
                @update:model-value="handleLlmOutputTypeChange($event)"
              />
              <p class="text-xs text-muted-foreground">
                Choose between text generation or image generation
              </p>
            </div>

            <template v-if="isImageOutputMode">
              <div class="space-y-2">
                <Label>Prompt</Label>
                <ExpressionInput
                  ref="userMessageInputRef"
                  :model-value="selectedNode.data.userMessage || ''"
                  placeholder="A beautiful sunset over mountains..."
                  :rows="4"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  navigation-enabled
                  :navigation-index="0"
                  :navigation-total="llmExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Prompt"
                  @update:model-value="updateNodeData('userMessage', $event)"
                  @navigate="handleLlmExpressionFieldNavigate"
                  @register-field-index="onLlmRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  Describe the image you want to generate
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label>Image Input</Label>
                <div class="flex items-center gap-2">
                  <input
                    id="llm-image-input"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="!!selectedNode.data.imageInputEnabled"
                    :disabled="!!selectedNode.data.batchModeEnabled"
                    @change="handleLlmImageInputChange(($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="llm-image-input"
                    class="text-sm font-normal"
                  >
                    Include image input
                  </Label>
                </div>
                <ExpressionInput
                  v-if="selectedNode.data.imageInputEnabled"
                  ref="llmImageExpressionInputRef"
                  :model-value="selectedNode.data.imageInput || ''"
                  placeholder="$input.imageUrl"
                  :rows="2"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  navigation-enabled
                  :navigation-index="1"
                  :navigation-total="llmExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Image input"
                  @update:model-value="updateNodeData('imageInput', $event)"
                  @navigate="handleLlmExpressionFieldNavigate"
                  @register-field-index="onLlmRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  Supports image URLs or base64 data URLs.
                </p>
              </div>
            </template>

            <template v-else>
              <div class="space-y-2 pt-2 border-t">
                <Label>System Instruction</Label>
                <ExpressionInput
                  ref="llmSystemInstructionInputRef"
                  :model-value="selectedNode.data.systemInstruction || ''"
                  placeholder="You are a helpful assistant..."
                  :rows="4"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  navigation-enabled
                  :navigation-index="0"
                  :navigation-total="llmExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="System instruction"
                  @update:model-value="updateNodeData('systemInstruction', $event)"
                  @navigate="handleLlmExpressionFieldNavigate"
                  @register-field-index="onLlmRegisterExpressionFieldIndex"
                />
              </div>

              <div class="space-y-2">
                <Label>User Message</Label>
                <ExpressionInput
                  ref="userMessageInputRef"
                  :model-value="selectedNode.data.userMessage || ''"
                  :placeholder="exampleRef"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  navigation-enabled
                  :navigation-index="1"
                  :navigation-total="llmExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="User message"
                  @update:model-value="updateNodeData('userMessage', $event)"
                  @navigate="handleLlmExpressionFieldNavigate"
                  @register-field-index="onLlmRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  <template v-if="selectedNode.data.batchModeEnabled">
                    Batch mode expects an array here. Example:
                    <span class="font-mono">$input.items.map("item.text")</span>
                  </template>
                  <template v-else>
                    Use $ expressions like {{ exampleRef }}
                  </template>
                </p>
              </div>

              <div class="space-y-3 pt-2 border-t">
                <div class="flex items-center gap-2">
                  <input
                    id="llm-batch-mode"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="!!selectedNode.data.batchModeEnabled"
                    :disabled="!llmBatchModeAvailable"
                    @change="handleLlmBatchModeChange(($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="llm-batch-mode"
                    class="text-sm font-normal"
                  >
                    Use Batch API mode
                  </Label>
                </div>
                <p
                  v-if="llmBatchCapabilityMessage"
                  :class="[
                    'text-xs',
                    llmBatchCapabilityTone === 'positive'
                      ? 'text-success'
                      : llmBatchCapabilityTone === 'warning'
                        ? 'text-amber-600'
                        : 'text-muted-foreground',
                  ]"
                >
                  {{ llmBatchCapabilityMessage }}
                </p>
                <p
                  v-if="selectedNode.data.batchModeEnabled"
                  class="text-xs text-muted-foreground"
                >
                  User Message must resolve to an array. Batch status updates stream live and
                  can trigger the <span class="font-semibold text-node-llm">STATUS</span> output
                  branch.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label>Image Input</Label>
                <div class="flex items-center gap-2">
                  <input
                    id="llm-image-input"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="!!selectedNode.data.imageInputEnabled"
                    :disabled="!!selectedNode.data.batchModeEnabled"
                    @change="handleLlmImageInputChange(($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="llm-image-input"
                    class="text-sm font-normal"
                  >
                    Include image input
                  </Label>
                </div>
                <ExpressionInput
                  v-if="selectedNode.data.imageInputEnabled"
                  ref="llmImageExpressionInputRef"
                  :model-value="selectedNode.data.imageInput || ''"
                  placeholder="$input.imageUrl"
                  :rows="2"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  navigation-enabled
                  :navigation-index="2"
                  :navigation-total="llmExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Image input"
                  @update:model-value="updateNodeData('imageInput', $event)"
                  @navigate="handleLlmExpressionFieldNavigate"
                  @register-field-index="onLlmRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  Supports image URLs or base64 data URLs.
                </p>
              </div>

              <div class="space-y-3 pt-2 border-t">
                <div
                  v-if="selectedModelIsReasoning"
                  class="space-y-2"
                >
                  <div class="flex items-center gap-2">
                    <Brain class="w-4 h-4 text-purple-500" />
                    <Label class="text-purple-500">Reasoning Model</Label>
                  </div>
                  <Select
                    :model-value="(selectedNode.data.reasoningEffort as ReasoningEffort) || 'medium'"
                    :options="reasoningEffortOptions"
                    @update:model-value="updateNodeData('reasoningEffort', $event)"
                  />
                  <p class="text-xs text-muted-foreground">
                    Reasoning effort level (replaces temperature)
                  </p>
                </div>

                <div
                  v-else
                  class="space-y-2"
                >
                  <Label>Temperature</Label>
                  <Input
                    type="number"
                    :model-value="selectedNode.data.temperature || 0.7"
                    min="0"
                    max="2"
                    step="0.1"
                    @update:model-value="updateNodeData('temperature', parseFloat($event as string))"
                  />
                </div>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label>JSON Output Parser</Label>
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <input
                      id="llm-json-output"
                      type="checkbox"
                      class="h-4 w-4 rounded border-input bg-background"
                      :checked="!!selectedNode.data.jsonOutputEnabled"
                      @change="updateNodeData('jsonOutputEnabled', ($event.target as HTMLInputElement).checked)"
                    >
                    <Label
                      for="llm-json-output"
                      class="text-sm font-normal"
                    >
                      Enable JSON output
                    </Label>
                  </div>
                  <Button
                    v-if="selectedNode.data.jsonOutputEnabled"
                    variant="ghost"
                    size="sm"
                    :class="['h-11 min-h-[44px] md:h-7 px-2 gap-1.5', jsonFormatError ? 'text-red-500' : '']"
                    :title="jsonFormatError ? 'Invalid JSON' : 'Format JSON'"
                    @click="formatJsonSchema"
                  >
                    <Braces class="w-3.5 h-3.5" />
                    <span class="text-xs">{{ jsonFormatError ? 'Invalid' : 'Format' }}</span>
                  </Button>
                </div>
                <Textarea
                  v-if="selectedNode.data.jsonOutputEnabled"
                  :model-value="selectedNode.data.jsonOutputSchema || ''"
                  placeholder="{ &quot;type&quot;: &quot;object&quot;, &quot;properties&quot;: { &quot;answer&quot;: { &quot;type&quot;: &quot;string&quot; } }, &quot;required&quot;: [&quot;answer&quot;] }"
                  :rows="6"
                  class="font-mono text-xs"
                  @update:model-value="updateNodeData('jsonOutputSchema', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Provide a JSON schema to shape the response.
                </p>
              </div>
            </template>

            <div class="space-y-4 pt-4 border-t">
              <div class="flex items-center gap-2">
                <input
                  id="llm-guardrails-enabled"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.guardrailsEnabled"
                  @change="updateNodeData('guardrailsEnabled', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="llm-guardrails-enabled"
                  class="text-sm font-normal flex items-center gap-1.5"
                >
                  <ShieldAlert class="w-3.5 h-3.5 text-amber-500" />
                  Enable Guardrails
                </Label>
              </div>

              <template v-if="selectedNode.data.guardrailsEnabled">
                <div class="space-y-3 pl-6">
                  <div
                    v-if="!selectedNode.data.guardrailCredentialId || !selectedNode.data.guardrailModel"
                    class="flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-2 text-amber-600 dark:text-amber-400"
                  >
                    <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
                    <p class="text-xs">
                      Guardrail credential and model are required. The workflow cannot run until both are selected.
                    </p>
                  </div>
                  <div class="space-y-2">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Credential</Label>
                    <Select
                      :model-value="selectedNode.data.guardrailCredentialId || ''"
                      :options="guardrailCredentialOptions"
                      @update:model-value="handleGuardrailCredentialChange($event)"
                    />
                    <p class="text-xs text-muted-foreground">
                      Select a credential (e.g. OpenAI) for content safety. Required when guardrails are enabled.
                    </p>
                  </div>
                  <div class="space-y-2">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Model</Label>
                    <Select
                      :model-value="selectedNode.data.guardrailModel || ''"
                      :options="guardrailModelOptions"
                      :disabled="loadingGuardrailModels"
                      @update:model-value="handleGuardrailModelChange($event)"
                    />
                  </div>
                  <div class="space-y-2">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Blocked Categories</Label>
                    <div class="grid grid-cols-1 gap-1.5">
                      <div
                        v-for="cat in GUARDRAIL_CATEGORIES"
                        :key="cat.value"
                        class="flex items-center gap-2"
                      >
                        <input
                          :id="`llm-guardrail-${cat.value}`"
                          type="checkbox"
                          class="h-4 w-4 rounded border-input bg-background"
                          :checked="(selectedNode.data.guardrailsCategories || []).includes(cat.value as GuardrailCategory)"
                          @change="toggleGuardrailCategory(($event.target as HTMLInputElement).checked, cat.value as GuardrailCategory)"
                        >
                        <Label
                          :for="`llm-guardrail-${cat.value}`"
                          class="text-xs font-normal"
                        >
                          {{ cat.label }}
                        </Label>
                      </div>
                    </div>
                  </div>

                  <div class="space-y-2 pt-1">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Sensitivity</Label>
                    <Select
                      :model-value="selectedNode.data.guardrailsSeverity || 'medium'"
                      :options="GUARDRAIL_SEVERITY_OPTIONS"
                      @update:model-value="updateNodeData('guardrailsSeverity', $event)"
                    />
                    <p class="text-xs text-muted-foreground">
                      <span v-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'low'">
                        Low — flag even borderline cases
                      </span>
                      <span v-else-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'medium'">
                        Medium — flag clear violations
                      </span>
                      <span v-else>
                        High — only flag extreme violations
                      </span>
                    </p>
                  </div>
                </div>
                <p class="text-xs text-muted-foreground">
                  If the user message matches a blocked category, the node will throw an error instead of running.
                </p>
              </template>
            </div>
          </template>

          <template v-if="selectedNode.type === 'agent'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="credentialOptions"
                @update:model-value="handleCredentialChange($event)"
              />
              <p
                v-if="!selectedNode.data.credentialId"
                class="text-xs text-muted-foreground"
              >
                <a
                  href="/?tab=credentials"
                  class="text-primary hover:underline"
                  @click.prevent="$router.push('/?tab=credentials')"
                >Add credentials</a> in Dashboard
              </p>
            </div>
            <div class="space-y-2">
              <Label>Model</Label>
              <Select
                :model-value="selectedNode.data.model || ''"
                :options="modelOptions"
                :disabled="!selectedNode.data.credentialId || loadingModels"
                @update:model-value="handleModelChange($event)"
              />
              <p
                v-if="agentModelContextLimit"
                class="text-xs text-muted-foreground"
              >
                {{ agentModelContextLimit }} context window
              </p>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <div class="flex items-center gap-2">
                <input
                  id="agent-persistent-memory"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.persistentMemoryEnabled"
                  @change="updateNodeData('persistentMemoryEnabled', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="agent-persistent-memory"
                  class="text-sm font-normal"
                >
                  Persistent memory (graph)
                </Label>
              </div>
              <p class="text-xs text-muted-foreground">
                Each run loads this graph into the system prompt when non-empty; after the run, new facts merge in the background. Sub-agents use their own graph. Use the pink brain on the node to view or edit.
              </p>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <Label>Fallback (optional)</Label>
              <p class="text-xs text-muted-foreground">
                If primary credential/model fails, retry with fallback.
              </p>
              <Select
                :model-value="selectedNode.data.fallbackCredentialId || ''"
                :options="fallbackCredentialOptions"
                @update:model-value="handleFallbackCredentialChange($event)"
              />
              <Select
                :model-value="selectedNode.data.fallbackModel || ''"
                :options="fallbackModelOptions"
                :disabled="!selectedNode.data.fallbackCredentialId || loadingFallbackModels"
                @update:model-value="handleFallbackModelChange($event)"
              />
            </div>
            <div class="space-y-2 pt-2 border-t">
              <Label>System Instruction</Label>
              <ExpressionInput
                ref="agentSystemInstructionInputRef"
                :model-value="selectedNode.data.systemInstruction || ''"
                placeholder="You are a helpful assistant..."
                :rows="4"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                navigation-enabled
                :navigation-index="0"
                :navigation-total="agentExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="System instruction"
                @update:model-value="updateNodeData('systemInstruction', $event)"
                @navigate="handleAgentExpressionFieldNavigate"
                @register-field-index="onAgentRegisterExpressionFieldIndex"
              />
            </div>
            <div class="space-y-2">
              <Label>User Message</Label>
              <ExpressionInput
                ref="userMessageInputRef"
                :model-value="selectedNode.data.userMessage || ''"
                :placeholder="exampleRef"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                navigation-enabled
                :navigation-index="1"
                :navigation-total="agentExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="User message"
                @update:model-value="updateNodeData('userMessage', $event)"
                @navigate="handleAgentExpressionFieldNavigate"
                @register-field-index="onAgentRegisterExpressionFieldIndex"
              />
            </div>
            <div class="space-y-2 pt-2 border-t">
              <Label>Image Input</Label>
              <div class="flex items-center gap-2">
                <input
                  id="agent-image-input"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.imageInputEnabled"
                  @change="updateNodeData('imageInputEnabled', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="agent-image-input"
                  class="text-sm font-normal"
                >
                  Include image input
                </Label>
              </div>
              <ExpressionInput
                v-if="selectedNode.data.imageInputEnabled"
                ref="agentImageExpressionInputRef"
                :model-value="selectedNode.data.imageInput || ''"
                placeholder="$input.imageUrl"
                :rows="2"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                navigation-enabled
                :navigation-index="2"
                :navigation-total="agentExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Image input"
                @update:model-value="updateNodeData('imageInput', $event)"
                @navigate="handleAgentExpressionFieldNavigate"
                @register-field-index="onAgentRegisterExpressionFieldIndex"
              />
              <p class="text-xs text-muted-foreground">
                Supports image URLs or base64 data URLs.
              </p>
            </div>
            <div class="space-y-3 pt-2 border-t">
              <div
                v-if="selectedModelIsReasoning"
                class="space-y-2"
              >
                <div class="flex items-center gap-2">
                  <Brain class="w-4 h-4 text-purple-500" />
                  <Label class="text-purple-500">Reasoning Model</Label>
                </div>
                <Select
                  :model-value="(selectedNode.data.reasoningEffort as ReasoningEffort) || 'medium'"
                  :options="reasoningEffortOptions"
                  @update:model-value="updateNodeData('reasoningEffort', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Reasoning effort level (replaces temperature)
                </p>
              </div>
              <div
                v-else
                class="space-y-2"
              >
                <Label>Temperature</Label>
                <Input
                  type="number"
                  :model-value="selectedNode.data.temperature || 0.7"
                  min="0"
                  max="2"
                  step="0.1"
                  @update:model-value="updateNodeData('temperature', parseFloat($event as string))"
                />
              </div>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <div class="flex items-center gap-2">
                <input
                  id="agent-orchestrator"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.isOrchestrator"
                  @change="updateNodeData('isOrchestrator', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="agent-orchestrator"
                  class="text-sm font-normal"
                >
                  Orchestrator mode (can call sub-agents)
                </Label>
              </div>
              <p class="text-xs text-muted-foreground">
                When enabled, this agent can delegate tasks to other agent nodes in the workflow.
              </p>
              <div
                v-if="selectedNode.data.isOrchestrator"
                class="space-y-2 pt-2"
              >
                <Label class="text-xs">Sub-Agents</Label>
                <div
                  v-if="availableSubAgentLabels.length === 0"
                  class="text-xs text-muted-foreground"
                >
                  Add more agent nodes to the workflow to select them as sub-agents.
                </div>
                <div
                  v-else
                  class="flex flex-col gap-2"
                >
                  <div
                    v-for="label in availableSubAgentLabels"
                    :key="label"
                    class="flex items-center gap-2"
                  >
                    <input
                      :id="`sub-agent-${label}`"
                      type="checkbox"
                      class="h-4 w-4 rounded border-input bg-background"
                      :checked="(selectedNode.data.subAgentLabels || []).includes(label)"
                      @change="toggleSubAgentLabel(label, ($event.target as HTMLInputElement).checked)"
                    >
                    <Label
                      :for="`sub-agent-${label}`"
                      class="text-sm font-normal"
                    >
                      {{ label }}
                    </Label>
                  </div>
                </div>
              </div>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <Label class="text-sm font-medium">Sub-Workflows</Label>
              <p class="text-xs text-muted-foreground">
                Workflows this agent can call as tools. The agent will receive a
                call_sub_workflow tool.
              </p>
              <div
                v-if="workflowOptions.length === 0"
                class="text-xs text-muted-foreground"
              >
                No other workflows available.
              </div>
              <template v-else>
                <Input
                  v-model="subWorkflowSearch"
                  placeholder="Search workflows..."
                  class="h-8 text-sm"
                />
                <div class="max-h-48 overflow-y-auto overflow-x-hidden rounded-md border border-input bg-background">
                  <div
                    v-for="opt in filteredWorkflowOptionsForSubWorkflows"
                    :key="opt.value"
                    class="group flex items-center gap-2 px-3 py-2 hover:bg-muted/50 cursor-pointer"
                    @click="toggleSubWorkflowId(opt.value, opt.label, !(selectedNode.data.subWorkflowIds || []).includes(opt.value))"
                  >
                    <input
                      :id="`sub-workflow-${opt.value}`"
                      type="checkbox"
                      class="h-4 w-4 shrink-0 rounded border-input bg-background pointer-events-none"
                      :checked="(selectedNode.data.subWorkflowIds || []).includes(opt.value)"
                    >
                    <Label
                      class="text-sm font-normal flex-1 min-w-0 break-words select-none"
                      :title="opt.label"
                    >
                      {{ opt.label }}
                    </Label>
                    <button
                      type="button"
                      class="p-1.5 h-7 w-7 rounded hover:bg-muted text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity duration-200 shrink-0"
                      title="Open in new tab"
                      @click.stop="openSubWorkflowEditor(opt.value)"
                    >
                      <ExternalLink :size="14" />
                    </button>
                  </div>
                </div>
                <p class="text-xs text-muted-foreground">
                  {{ (selectedNode.data.subWorkflowIds || []).length }} selected
                </p>
              </template>
            </div>
            <div
              v-if="(selectedNode.data.tools || []).length > 0"
              class="space-y-2 pt-2 border-t"
            >
              <Label>Tool Timeout (seconds)</Label>
              <Input
                type="number"
                :model-value="String(selectedNode.data.toolTimeoutSeconds ?? 30)"
                min="1"
                max="300"
                placeholder="30"
                @update:model-value="updateNodeData('toolTimeoutSeconds', parseInt($event, 10) || 30)"
              />
              <p class="text-xs text-muted-foreground">
                Max seconds per tool execution
              </p>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <div class="flex items-center justify-between">
                <Label>Tools</Label>
                <Button
                  variant="outline"
                  size="sm"
                  class="gap-1"
                  @click="addAgentTool"
                >
                  <Plus class="w-3.5 h-3.5" />
                  Add Tool
                </Button>
              </div>
              <div
                v-for="(tool, idx) in (selectedNode.data.tools || [])"
                :key="idx"
                class="rounded border p-3 space-y-2"
              >
                <div class="flex justify-between items-center">
                  <span class="text-sm font-medium">Tool {{ idx + 1 }}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="gap-1 text-destructive hover:text-destructive hover:bg-destructive/10"
                    @click="removeAgentTool(idx)"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                    Remove
                  </Button>
                </div>
                <div class="space-y-2">
                  <Label class="text-xs">Name</Label>
                  <Input
                    :model-value="tool.name"
                    placeholder="count_characters"
                    @update:model-value="updateAgentTool(idx, 'name', $event)"
                  />
                  <Label class="text-xs">Description</Label>
                  <Textarea
                    :model-value="tool.description"
                    placeholder="Counts characters in the given text"
                    :rows="2"
                    @update:model-value="updateAgentTool(idx, 'description', $event)"
                  />
                  <Label class="text-xs">Parameters (JSON Schema)</Label>
                  <Textarea
                    :model-value="tool.parameters"
                    placeholder="{ &quot;type&quot;: &quot;object&quot;, &quot;properties&quot;: { &quot;text&quot;: { &quot;type&quot;: &quot;string&quot; } }, &quot;required&quot;: [&quot;text&quot;] }"
                    :rows="4"
                    class="font-mono text-xs"
                    @update:model-value="updateAgentTool(idx, 'parameters', $event)"
                  />
                  <Label class="text-xs">Python Code</Label>
                  <Textarea
                    :model-value="tool.code"
                    placeholder="def count_characters(text: str) -> int:&#10;    return len(text)"
                    :rows="4"
                    class="font-mono text-xs"
                    @update:model-value="updateAgentTool(idx, 'code', $event)"
                  />
                </div>
              </div>
              <p class="text-xs text-muted-foreground">
                Python tools the agent can call. Optional.
              </p>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <div class="flex items-center justify-between">
                <Label class="flex items-center gap-1">
                  <Server class="w-3.5 h-3.5" />
                  MCP Connections
                </Label>
                <Button
                  variant="outline"
                  size="sm"
                  class="gap-1"
                  @click="addAgentMCPConnection"
                >
                  <Plus class="w-3.5 h-3.5" />
                  Add MCP
                </Button>
              </div>
              <div
                v-for="(conn, idx) in (selectedNode.data.mcpConnections || [])"
                :key="conn.id"
                class="rounded border p-3 space-y-2"
              >
                <div class="flex justify-between items-center">
                  <span class="text-sm font-medium">MCP {{ idx + 1 }}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="gap-1 text-destructive hover:text-destructive hover:bg-destructive/10"
                    @click="removeAgentMCPConnection(idx)"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                    Remove
                  </Button>
                </div>
                <div class="space-y-2">
                  <div class="flex gap-2">
                    <div class="flex-1">
                      <Label class="text-xs">Transport</Label>
                      <Select
                        :model-value="conn.transport"
                        :options="[
                          { value: 'stdio', label: 'stdio' },
                          { value: 'sse', label: 'SSE' },
                        ]"
                        @update:model-value="updateAgentMCPConnection(idx, 'transport', $event)"
                      />
                    </div>
                    <div class="w-24">
                      <Label class="text-xs">Timeout (s)</Label>
                      <Input
                        type="number"
                        :model-value="String(conn.timeoutSeconds ?? 30)"
                        min="1"
                        max="300"
                        placeholder="30"
                        @update:model-value="updateAgentMCPConnection(idx, 'timeoutSeconds', parseInt($event, 10) || 30)"
                      />
                    </div>
                  </div>
                  <div>
                    <Label class="text-xs">Label (optional)</Label>
                    <Input
                      :model-value="conn.label ?? ''"
                      placeholder="filesystem"
                      @update:model-value="updateAgentMCPConnection(idx, 'label', $event)"
                    />
                  </div>
                  <template v-if="conn.transport === 'stdio'">
                    <div>
                      <Label class="text-xs">Command</Label>
                      <Input
                        :model-value="conn.command ?? ''"
                        placeholder="npx"
                        @update:model-value="updateAgentMCPConnection(idx, 'command', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Args (JSON array)</Label>
                      <Textarea
                        :model-value="typeof conn.args === 'string' ? conn.args : JSON.stringify(conn.args ?? [], null, 2)"
                        placeholder="[&quot;-y&quot;, &quot;@modelcontextprotocol/server-filesystem&quot;, &quot;--path&quot;, &quot;/tmp&quot;]"
                        :rows="2"
                        class="font-mono text-xs"
                        @update:model-value="updateAgentMCPConnection(idx, 'args', $event)"
                      />
                    </div>
                  </template>
                  <template v-else>
                    <div>
                      <Label class="text-xs">URL</Label>
                      <Input
                        :model-value="conn.url ?? ''"
                        placeholder="https://example.com/mcp/sse"
                        @update:model-value="updateAgentMCPConnection(idx, 'url', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Headers (JSON object)</Label>
                      <Textarea
                        :model-value="typeof conn.headers === 'string' ? conn.headers : JSON.stringify(conn.headers ?? {}, null, 2)"
                        placeholder="{&quot;Authorization&quot;: &quot;Bearer ...&quot;, &quot;X-Custom&quot;: &quot;value&quot;}"
                        :rows="2"
                        class="font-mono text-xs"
                        @update:model-value="updateAgentMCPConnection(idx, 'headers', $event)"
                      />
                    </div>
                  </template>
                  <div class="pt-2 flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      class="gap-1"
                      :disabled="(conn.transport === 'stdio' && !conn.command) ||
                        (conn.transport === 'sse' && !conn.url) ||
                        getMCPFetchState(conn.id).loading
                      "
                      @click="fetchMCPTools(conn, idx)"
                    >
                      <Loader2
                        v-if="getMCPFetchState(conn.id).loading"
                        class="w-3.5 h-3.5 animate-spin"
                      />
                      <Server
                        v-else
                        class="w-3.5 h-3.5"
                      />
                      {{ getMCPFetchState(conn.id).loading ? "Connecting…" : "Fetch tools" }}
                    </Button>
                    <span
                      v-if="getMCPFetchState(conn.id).error"
                      class="text-xs text-destructive truncate min-w-0 flex-1"
                      :title="getMCPFetchState(conn.id).error ?? undefined"
                    >
                      {{ getMCPFetchState(conn.id).error }}
                    </span>
                    <span
                      v-else-if="getMCPFetchState(conn.id).tools.length > 0"
                      class="text-xs text-muted-foreground"
                    >
                      {{ getMCPFetchState(conn.id).tools.length }} tool(s)
                    </span>
                  </div>
                  <div
                    v-if="getMCPFetchState(conn.id).tools.length > 0"
                    class="rounded border bg-muted/30 p-2 space-y-1.5 max-h-32 overflow-y-auto"
                  >
                    <div
                      v-for="t in getMCPFetchState(conn.id).tools"
                      :key="t.name"
                      class="text-xs"
                    >
                      <span class="font-medium text-foreground">{{ t.name }}</span>
                      <span
                        v-if="t.description"
                        class="text-muted-foreground"
                      >
                        — {{ t.description }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              <p class="text-xs text-muted-foreground">
                MCP servers the agent can call. Optional. stdio: command + args. SSE: url + headers.
              </p>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <div class="flex items-center justify-between">
                <Label class="flex items-center gap-1">
                  <BookOpen class="w-3.5 h-3.5" />
                  Skills
                </Label>
                <div class="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    class="gap-1"
                    @click="addAgentSkill"
                  >
                    <Plus class="w-3.5 h-3.5" />
                    Add Skill
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="gap-1 border-primary/30 text-primary hover:bg-primary/10 hover:text-primary"
                    :disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
                    @click="openSkillBuilderNew"
                  >
                    <Sparkles class="w-3.5 h-3.5" />
                    AI Build
                  </Button>
                </div>
              </div>
              <div
                class="rounded border border-dashed p-4 text-center text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:bg-muted/30"
                :class="{ 'opacity-50 pointer-events-none': skillZipLoading }"
                @dragenter.stop.prevent
                @dragover.stop.prevent
                @drop.prevent="(e: DragEvent) => {
                  e.stopPropagation();
                  const f = e.dataTransfer?.files?.[0];
                  if (f) handleSkillZipDrop(f);
                }"
              >
                <FileArchive class="w-8 h-8 mx-auto mb-2 opacity-60" />
                Drop .zip or .md file here
              </div>
              <p
                v-if="skillZipError"
                class="text-xs text-destructive"
              >
                {{ skillZipError }}
              </p>
              <div
                v-for="(skill, idx) in (selectedNode.data.skills || [])"
                :key="skill.id"
                class="rounded border p-3 space-y-2"
              >
                <div class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                  <button
                    type="button"
                    class="flex min-w-0 flex-1 items-center gap-1.5 self-center text-left text-sm font-medium hover:text-primary"
                    :title="`Skill ${idx + 1}: ${skill.name || '(unnamed)'}`"
                    @click="toggleSkillExpanded(skill.id)"
                  >
                    <ChevronRight
                      v-if="!expandedSkillIds.has(skill.id)"
                      class="w-3.5 h-3.5"
                    />
                    <ChevronDown
                      v-else
                      class="w-3.5 h-3.5"
                    />
                    <span class="break-words leading-tight">
                      Skill {{ idx + 1 }}: {{ skill.name || '(unnamed)' }}
                    </span>
                  </button>
                  <div class="flex shrink-0 items-center gap-1 rounded-lg border border-border/60 bg-muted/10 p-1">
                    <button
                      type="button"
                      class="flex h-7 w-7 items-center justify-center rounded-md text-primary transition-colors hover:bg-primary/10 hover:text-primary disabled:pointer-events-none disabled:opacity-50"
                      :disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
                      :title="'Edit with AI'"
                      :aria-label="'Edit with AI'"
                      @click="openSkillBuilderEdit(skill)"
                    >
                      <Sparkles class="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      class="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
                      :disabled="skillDownloadLoadingId !== null"
                      :title="'Download skill ZIP'"
                      :aria-label="'Download skill ZIP'"
                      @click="downloadAgentSkill(skill)"
                    >
                      <Loader2
                        v-if="skillDownloadLoadingId === skill.id"
                        class="w-3.5 h-3.5 animate-spin"
                      />
                      <Download
                        v-else
                        class="w-3.5 h-3.5"
                      />
                    </button>
                    <button
                      type="button"
                      class="flex h-7 w-7 items-center justify-center rounded-md text-destructive transition-colors hover:bg-destructive/10 hover:text-destructive"
                      :title="'Remove skill'"
                      :aria-label="'Remove skill'"
                      @click="removeAgentSkill(idx)"
                    >
                      <Trash2 class="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
                <div
                  v-if="expandedSkillIds.has(skill.id)"
                  class="space-y-2 pt-2 border-t"
                >
                  <div>
                    <Label class="text-xs">Name</Label>
                    <Input
                      :model-value="skill.name"
                      placeholder="skill-name"
                      @update:model-value="updateAgentSkill(idx, 'name', $event)"
                    />
                  </div>
                  <div>
                    <Label class="text-xs">Timeout (seconds)</Label>
                    <Input
                      type="number"
                      :model-value="String(skill.timeoutSeconds ?? 30)"
                      min="1"
                      max="300"
                      placeholder="30"
                      @update:model-value="updateAgentSkill(idx, 'timeoutSeconds', parseInt($event, 10) || 30)"
                    />
                  </div>
                  <div>
                    <Label class="text-xs">SKILL.md Content</Label>
                    <Textarea
                      :model-value="skill.content"
                      placeholder="---&#10;name: my-skill&#10;---&#10;&#10;Instructions..."
                      :rows="6"
                      class="font-mono text-xs"
                      @update:model-value="updateAgentSkill(idx, 'content', $event)"
                    />
                  </div>
                  <div
                    v-if="skill.files?.length"
                    class="space-y-1"
                  >
                    <Label class="text-xs">Files ({{ skill.files.length }})</Label>
                    <div
                      v-for="(f, fi) in skill.files"
                      :key="fi"
                      class="rounded border bg-muted/20 p-2"
                    >
                      <div class="flex justify-between items-center mb-1">
                        <span class="text-xs font-mono">{{ f.path }}</span>
                        <Button
                          variant="ghost"
                          size="sm"
                          class="gap-1 text-destructive hover:text-destructive hover:bg-destructive/10"
                          @click="removeAgentSkillFile(idx, fi)"
                        >
                          <Trash2 class="w-3.5 h-3.5" />
                          Remove
                        </Button>
                      </div>
                      <div
                        v-if="isImageSkillFile(f)"
                        class="space-y-2"
                      >
                        <img
                          v-if="getSkillFilePreviewSrc(f)"
                          :src="getSkillFilePreviewSrc(f)"
                          :alt="f.path"
                          class="max-h-56 w-auto max-w-full rounded border bg-background object-contain"
                        >
                        <p class="text-xs text-muted-foreground">
                          Image preview stored as base64 to keep workflow saves UTF-8 safe.
                        </p>
                      </div>
                      <Textarea
                        v-else-if="isTextSkillFile(f)"
                        :model-value="f.content"
                        :rows="4"
                        class="font-mono text-xs"
                        @update:model-value="updateAgentSkillFile(idx, fi, 'content', $event)"
                      />
                      <p
                        v-else
                        class="text-xs text-muted-foreground"
                      >
                        Binary file stored as base64. Editing is disabled in the workflow editor.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
              <p class="text-xs text-muted-foreground">
                SKILL.md instructions and optional Python files. Optional. Drop zip or add manually.
              </p>
            </div>

            <div class="space-y-2 pt-2 border-t">
              <Label>Human Review</Label>
              <div class="flex items-center gap-2">
                <input
                  id="agent-hitl-enabled"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.hitlEnabled"
                  @change="updateNodeData('hitlEnabled', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="agent-hitl-enabled"
                  class="text-sm font-normal"
                >
                  Pause for human review
                </Label>
              </div>
              <Label
                v-if="selectedNode.data.hitlEnabled"
                class="text-xs uppercase tracking-[0.24em] text-muted-foreground"
              >
                Approval Guidelines
              </Label>
              <ExpressionInput
                v-if="selectedNode.data.hitlEnabled"
                :model-value="selectedNode.data.hitlSummary || ''"
                placeholder="Describe when this agent should ask for approval..."
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Approval guidelines"
                @update:model-value="updateNodeData('hitlSummary', $event)"
              />
              <p class="text-xs text-muted-foreground">
                HITL adds a human-review tool to this agent. Use the system prompt plus this field
                to describe when approval is needed. Heym asks the model to interpret MCP approval
                scope from these instructions as `always`, `once`, or `never`. The reviewer-facing
                summary is generated from the agent's review request, not from this field. Use the
                extra review output on the canvas to notify Slack, email, or other nodes while the
                run is waiting. Review links expire after 168 hours.
              </p>
              <p
                v-if="selectedNode.data.hitlEnabled && selectedNode.data.jsonOutputEnabled"
                class="text-xs text-amber-500"
              >
                HITL works only with text-mode agent outputs in v1.
              </p>
            </div>

            <div class="space-y-2 pt-2 border-t">
              <Label>JSON Output Parser</Label>
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-2">
                  <input
                    id="agent-json-output"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="!!selectedNode.data.jsonOutputEnabled"
                    @change="updateNodeData('jsonOutputEnabled', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="agent-json-output"
                    class="text-sm font-normal"
                  >
                    Enable JSON output
                  </Label>
                </div>
                <Button
                  v-if="selectedNode.data.jsonOutputEnabled"
                  variant="ghost"
                  size="sm"
                  :class="['h-11 min-h-[44px] md:h-7 px-2 gap-1.5', jsonFormatError ? 'text-red-500' : '']"
                  :title="jsonFormatError ? 'Invalid JSON' : 'Format JSON'"
                  @click="formatJsonSchema"
                >
                  <Braces class="w-3.5 h-3.5" />
                  <span class="text-xs">{{ jsonFormatError ? 'Invalid' : 'Format' }}</span>
                </Button>
              </div>
              <Textarea
                v-if="selectedNode.data.jsonOutputEnabled"
                :model-value="selectedNode.data.jsonOutputSchema || ''"
                placeholder="{ &quot;type&quot;: &quot;object&quot;, &quot;properties&quot;: { &quot;answer&quot;: { &quot;type&quot;: &quot;string&quot; } }, &quot;required&quot;: [&quot;answer&quot;] }"
                :rows="6"
                class="font-mono text-xs"
                @update:model-value="updateNodeData('jsonOutputSchema', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Provide a JSON schema to shape the agent's final response.
              </p>
            </div>

            <div class="space-y-4 pt-4 border-t">
              <div class="flex items-center gap-2">
                <input
                  id="agent-guardrails-enabled"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.guardrailsEnabled"
                  @change="updateNodeData('guardrailsEnabled', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="agent-guardrails-enabled"
                  class="text-sm font-normal flex items-center gap-1.5"
                >
                  <ShieldAlert class="w-3.5 h-3.5 text-amber-500" />
                  Enable Guardrails
                </Label>
              </div>

              <template v-if="selectedNode.data.guardrailsEnabled">
                <div class="space-y-3 pl-6">
                  <div
                    v-if="!selectedNode.data.guardrailCredentialId || !selectedNode.data.guardrailModel"
                    class="flex items-start gap-2 rounded-md border border-amber-500/50 bg-amber-500/10 p-2 text-amber-600 dark:text-amber-400"
                  >
                    <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
                    <p class="text-xs">
                      Guardrail credential and model are required. The workflow cannot run until both are selected.
                    </p>
                  </div>
                  <div class="space-y-2">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Credential</Label>
                    <Select
                      :model-value="selectedNode.data.guardrailCredentialId || ''"
                      :options="guardrailCredentialOptions"
                      @update:model-value="handleGuardrailCredentialChange($event)"
                    />
                    <p class="text-xs text-muted-foreground">
                      Select a credential (e.g. OpenAI) for content safety. Required when guardrails are enabled.
                    </p>
                  </div>
                  <div class="space-y-2">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Guardrail Model</Label>
                    <Select
                      :model-value="selectedNode.data.guardrailModel || ''"
                      :options="guardrailModelOptions"
                      :disabled="loadingGuardrailModels"
                      @update:model-value="handleGuardrailModelChange($event)"
                    />
                  </div>
                  <div class="space-y-2">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Blocked Categories</Label>
                    <div class="grid grid-cols-1 gap-1.5">
                      <div
                        v-for="cat in GUARDRAIL_CATEGORIES"
                        :key="cat.value"
                        class="flex items-center gap-2"
                      >
                        <input
                          :id="`agent-guardrail-${cat.value}`"
                          type="checkbox"
                          class="h-4 w-4 rounded border-input bg-background"
                          :checked="(selectedNode.data.guardrailsCategories || []).includes(cat.value as GuardrailCategory)"
                          @change="toggleGuardrailCategory(($event.target as HTMLInputElement).checked, cat.value as GuardrailCategory)"
                        >
                        <Label
                          :for="`agent-guardrail-${cat.value}`"
                          class="text-xs font-normal"
                        >
                          {{ cat.label }}
                        </Label>
                      </div>
                    </div>
                  </div>

                  <div class="space-y-2 pt-1">
                    <Label class="text-xs text-muted-foreground uppercase tracking-wide">Sensitivity</Label>
                    <Select
                      :model-value="selectedNode.data.guardrailsSeverity || 'medium'"
                      :options="GUARDRAIL_SEVERITY_OPTIONS"
                      @update:model-value="updateNodeData('guardrailsSeverity', $event)"
                    />
                    <p class="text-xs text-muted-foreground">
                      <span v-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'low'">
                        Low — flag even borderline cases
                      </span>
                      <span v-else-if="(selectedNode.data.guardrailsSeverity || 'medium') === 'medium'">
                        Medium — flag clear violations
                      </span>
                      <span v-else>
                        High — only flag extreme violations
                      </span>
                    </p>
                  </div>
                </div>
                <p class="text-xs text-muted-foreground">
                  If the user message matches a blocked category, the agent will throw an error instead of running.
                </p>
              </template>
            </div>
          </template>

          <template v-if="selectedNode.type === 'condition'">
            <div class="space-y-2">
              <Label>Condition</Label>
              <ExpressionInput
                ref="conditionInputRef"
                :model-value="selectedNode.data.condition || ''"
                :placeholder="`${exampleRef}.length > 0`"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Condition"
                @update:model-value="updateNodeData('condition', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $ prefix: {{ exampleRef }}, $nodeName.field
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'switch'">
            <div class="space-y-2">
              <Label>Expression</Label>
              <ExpressionInput
                ref="switchExpressionInputRef"
                :model-value="selectedNode.data.expression || ''"
                :placeholder="exampleRef"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Expression"
                @update:model-value="updateNodeData('expression', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $ prefix: {{ exampleRef }}, $nodeName.field
              </p>
            </div>
            <div class="space-y-2">
              <Label>Cases</Label>
              <Textarea
                :model-value="(selectedNode.data.cases || []).join('\n')"
                placeholder="case1&#10;case2"
                :rows="4"
                class="font-mono text-sm"
                @update:model-value="handleCasesChange($event)"
              />
              <p class="text-xs text-muted-foreground">
                One case per line, matched by value
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'execute'">
            <div class="space-y-2">
              <Label>Target Workflow</Label>
              <Select
                :model-value="selectedNode.data.executeWorkflowId || ''"
                :options="[{ value: '', label: 'Select a workflow...' }, ...workflowOptions]"
                @update:model-value="updateNodeData('executeWorkflowId', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Select which workflow to execute
              </p>
            </div>
            <Button
              v-if="canVisitWorkflow"
              variant="outline"
              size="sm"
              class="w-full gap-2"
              @click="visitWorkflow"
            >
              <ExternalLink class="w-4 h-4" />
              Visit Workflow
              <span class="text-xs text-muted-foreground ml-auto">⌘⇧O</span>
            </Button>

            <div
              v-if="loadingTargetInputs"
              class="flex items-center gap-2 text-sm text-muted-foreground py-2"
            >
              <div class="animate-spin w-4 h-4 border-2 border-primary border-t-transparent rounded-full" />
              Loading workflow inputs...
            </div>

            <div
              v-else-if="targetWorkflowInputFields.length > 0"
              class="space-y-3"
            >
              <div class="flex items-center justify-between">
                <Label>Input Mappings</Label>
                <span class="text-xs text-muted-foreground">
                  {{ targetWorkflowInputFields.length }} field{{ targetWorkflowInputFields.length > 1 ? 's' : '' }}
                </span>
              </div>
              <div class="space-y-2 border rounded-md p-3 bg-muted/30">
                <div
                  v-for="(mapping, index) in (selectedNode.data.executeInputMappings || [])"
                  :key="mapping.key"
                  class="space-y-1.5"
                >
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-medium text-foreground bg-muted px-2 py-0.5 rounded">
                      {{ mapping.key }}
                    </span>
                    <span
                      v-if="targetWorkflowInputFields[index]?.defaultValue"
                      class="text-xs text-muted-foreground"
                    >
                      (default: {{ targetWorkflowInputFields[index].defaultValue }})
                    </span>
                  </div>
                  <ExpressionInput
                    :ref="(el: any) => setExecuteMappingInputRef(index, el)"
                    :model-value="mapping.value"
                    :placeholder="`$input.${mapping.key}`"
                    :rows="1"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    navigation-enabled
                    :navigation-index="index"
                    :navigation-total="executeMappings.length"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    :dialog-key-label="mapping.key"
                    @update:model-value="updateExecuteMapping(index, $event)"
                    @navigate="handleExecuteMappingNavigate"
                    @register-field-index="onExecuteMappingRegisterFieldIndex"
                  />
                  <p
                    v-if="getExpressionWarning(mapping.value)"
                    class="text-xs text-amber-500 flex items-center gap-1 mt-1"
                  >
                    <AlertTriangle class="h-3 w-3" />
                    {{ getExpressionWarning(mapping.value) }}
                  </p>
                </div>
              </div>
              <p class="text-xs text-muted-foreground">
                Map values to the target workflow's input fields. Use $ expressions.
              </p>
            </div>

            <div
              v-else-if="selectedNode.data.executeWorkflowId"
              class="text-xs text-muted-foreground py-2"
            >
              Target workflow has no input fields defined.
            </div>

            <div
              v-if="!selectedNode.data.executeWorkflowId"
              class="space-y-2"
            >
              <Label>Input Template</Label>
              <ExpressionInput
                ref="executeTemplateExpressionInputRef"
                :model-value="selectedNode.data.executeInput || ''"
                :placeholder="exampleRef"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Input template"
                @update:model-value="updateNodeData('executeInput', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Transform the input before passing downstream. Use $ prefix: {{ exampleRef }}
              </p>
            </div>
            <div class="flex items-center gap-2 pt-1">
              <input
                id="execute-do-not-wait"
                type="checkbox"
                class="h-4 w-4 rounded border-input bg-background"
                :checked="!!selectedNode.data.executeDoNotWait"
                @change="updateNodeData('executeDoNotWait', ($event.target as HTMLInputElement).checked)"
              >
              <Label
                for="execute-do-not-wait"
                class="text-sm font-normal"
              >
                Do not wait
              </Label>
            </div>
          </template>

          <template v-if="selectedNode.type === 'http'">
            <div class="space-y-2">
              <Label>cURL Command</Label>
              <ExpressionInput
                ref="httpCurlInputRef"
                :model-value="selectedNode.data.curl || ''"
                placeholder="curl -X GET https://api.example.com"
                :rows="4"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="cURL command"
                dialog-title="Edit cURL Command"
                @update:model-value="updateNodeData('curl', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Double-click to expand. Use $ expressions like {{ exampleRef }}
              </p>
            </div>

            <div
              v-if="httpLastRequest"
              class="space-y-2 pt-3 border-t"
            >
              <Label class="flex items-center gap-2">
                <ExternalLink class="w-3.5 h-3.5" />
                Last Request
              </Label>
              <div class="bg-muted/50 rounded-md p-3 space-y-3 text-xs font-mono max-h-80 overflow-y-auto">
                <div class="flex items-center gap-2">
                  <span
                    :class="[
                      'px-1.5 py-0.5 rounded text-[10px] font-semibold shrink-0',
                      httpLastRequest.status >= 200 && httpLastRequest.status < 300
                        ? 'bg-green-500/20 text-green-600'
                        : httpLastRequest.status >= 400
                          ? 'bg-red-500/20 text-red-600'
                          : 'bg-yellow-500/20 text-yellow-600'
                    ]"
                  >
                    {{ httpLastRequest.status }}
                  </span>
                  <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-600 text-[10px] font-semibold shrink-0">
                    {{ httpLastRequest.method }}
                  </span>
                </div>
                <div class="break-all text-foreground text-[11px]">
                  {{ httpLastRequest.url || 'N/A' }}
                </div>
                <div
                  v-if="httpLastRequest.requestHeaders && Object.keys(httpLastRequest.requestHeaders).length > 0"
                  class="space-y-1.5"
                >
                  <span class="text-muted-foreground text-[10px] uppercase font-semibold">Request Headers:</span>
                  <div class="text-[11px] space-y-1 pl-2 border-l-2 border-primary/20">
                    <div
                      v-for="(value, key) in httpLastRequest.requestHeaders"
                      :key="key"
                      class="break-all"
                    >
                      <span class="text-primary font-medium">{{ key }}:</span>
                      <span class="text-muted-foreground ml-1">{{ value }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'websocketSend'">
            <div class="space-y-4">
              <div class="space-y-2">
                <Label>WebSocket URL</Label>
                <ExpressionInput
                  ref="websocketSendUrlInputRef"
                  :model-value="selectedNode.data.websocketUrl || ''"
                  placeholder="wss://example.com/socket"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="WebSocket URL"
                  @update:model-value="updateNodeData('websocketUrl', $event)"
                />
                <p
                  v-if="!selectedNode.data.websocketUrl || selectedNode.data.websocketUrl.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  URL is required
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Supports expressions, so you can choose the destination socket from upstream data or variables.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Headers (JSON object)</Label>
                <ExpressionInput
                  ref="websocketSendHeadersInputRef"
                  :model-value="selectedNode.data.websocketHeaders || ''"
                  placeholder="{&quot;Authorization&quot;: &quot;Bearer $vars.socketToken&quot;}"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="WebSocket headers"
                  @update:model-value="updateNodeData('websocketHeaders', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Optional headers for the outbound handshake. Use a JSON object string or a full-expression object.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Subprotocols</Label>
                <Input
                  :model-value="selectedNode.data.websocketSubprotocols || ''"
                  placeholder="json, graphql-ws"
                  @update:model-value="updateNodeData('websocketSubprotocols', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Optional comma-separated subprotocol list.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Message</Label>
                <ExpressionInput
                  ref="websocketSendMessageInputRef"
                  :model-value="selectedNode.data.websocketMessage || ''"
                  placeholder="$input"
                  :rows="4"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="WebSocket message"
                  @update:model-value="updateNodeData('websocketMessage', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Full expressions keep objects and arrays as JSON before sending. Plain strings are sent as text frames.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-muted-foreground">Output</Label>
                <div class="text-xs font-mono space-y-1 text-muted-foreground">
                  <div>${{ selectedNode.data.label }}.status - "sent" on success</div>
                  <div>${{ selectedNode.data.label }}.url - resolved socket URL</div>
                  <div>${{ selectedNode.data.label }}.message_type - text / json / binary</div>
                  <div>${{ selectedNode.data.label }}.size_bytes - payload size in bytes</div>
                  <div>${{ selectedNode.data.label }}.subprotocol - negotiated subprotocol</div>
                  <div>${{ selectedNode.data.label }}.sent_at - ISO timestamp</div>
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'output'">
            <div class="space-y-2">
              <div class="flex items-center gap-2">
                <input
                  id="output-downstream"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.allowDownstream"
                  @change="updateNodeData('allowDownstream', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="output-downstream"
                  class="text-sm font-normal"
                >
                  Run downstream after output
                </Label>
              </div>
              <p class="text-xs text-muted-foreground">
                Enable this to allow nodes to run after the output finishes.
              </p>
            </div>

            <div
              v-if="outputSchema.length === 0"
              class="space-y-2"
            >
              <Label>Message Template (simple/string)</Label>
              <ExpressionInput
                ref="outputMessageInputRef"
                :model-value="selectedNode.data.message || ''"
                :placeholder="exampleRef"
                :rows="2"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Message template"
                :navigation-enabled="outputExpressionFieldCount > 1"
                :navigation-index="0"
                :navigation-total="outputExpressionFieldCount"
                @navigate="handleOutputExpressionFieldNavigate"
                @register-field-index="onOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('message', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Simple template. Use $ prefix: {{ exampleRef }}. When JSON schema rows exist, the template is not
                used; remove all schema rows to edit the message again.
              </p>
            </div>

            <div class="space-y-3 pt-2 border-t">
              <div class="flex items-center justify-between">
                <Label>JSON Schema (key=value)</Label>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-11 min-h-[44px] md:h-7 px-2"
                  @click="addOutputSchemaField"
                >
                  <Plus class="w-3 h-3 mr-1" />
                  Add
                </Button>
              </div>
              <div
                v-for="(field, index) in outputSchema"
                :key="index"
                class="space-y-1"
              >
                <div class="flex gap-1.5 items-center">
                  <Input
                    :model-value="field.key"
                    placeholder="key"
                    class="w-20 shrink-0 font-mono text-xs"
                    @update:model-value="updateOutputSchemaField(index, 'key', $event)"
                  />
                  <span class="text-muted-foreground text-xs">=</span>
                  <ExpressionInput
                    :ref="(el: unknown) => setOutputSchemaValueInputRef(index, el)"
                    :model-value="field.value"
                    placeholder="$node.field"
                    single-line
                    class="flex-1 text-xs"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    :dialog-key-label="field.key ? `Output field: ${field.key}` : 'Output schema value'"
                    :navigation-enabled="outputExpressionFieldCount > 1"
                    :navigation-index="index"
                    :navigation-total="outputExpressionFieldCount"
                    @navigate="handleOutputExpressionFieldNavigate"
                    @register-field-index="onOutputRegisterExpressionFieldIndex"
                    @update:model-value="updateOutputSchemaField(index, 'value', $event)"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-10 w-7 text-destructive shrink-0"
                    @click="removeOutputSchemaField(index)"
                  >
                    <Minus class="w-3 h-3" />
                  </Button>
                </div>
                <p
                  v-if="getExpressionWarning(field.value)"
                  class="text-xs text-amber-500 flex items-center gap-1 ml-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  {{ getExpressionWarning(field.value) }}
                </p>
              </div>
              <p class="text-xs text-muted-foreground">
                Build custom JSON output. Values support $ expressions.
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'consoleLog'">
            <div class="space-y-2">
              <Label>Log message</Label>
              <ExpressionInput
                ref="consoleLogMessageInputRef"
                :model-value="selectedNode.data.logMessage || ''"
                :placeholder="exampleRef"
                :rows="2"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Log message"
                @update:model-value="updateNodeData('logMessage', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Written to backend (server) console only; not visible in the browser.
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'slack'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="slackCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <p
                v-if="!selectedNode.data.credentialId"
                class="text-xs text-muted-foreground"
              >
                <a
                  href="/?tab=credentials"
                  class="text-primary hover:underline"
                  @click.prevent="$router.push('/?tab=credentials')"
                >Add credentials</a> in Dashboard
              </p>
            </div>

            <div class="space-y-2">
              <Label>Message</Label>
              <ExpressionInput
                ref="slackMessageInputRef"
                :model-value="selectedNode.data.message || ''"
                :placeholder="exampleRef"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Message"
                @update:model-value="updateNodeData('message', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $ expressions like {{ exampleRef }} or $error.message
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'telegram'">
            <div class="space-y-2">
              <Label>Telegram Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="telegramCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <p
                v-if="!selectedNode.data.credentialId"
                class="text-xs text-muted-foreground"
              >
                <a
                  href="/?tab=credentials"
                  class="text-primary hover:underline"
                  @click.prevent="$router.push('/?tab=credentials')"
                >Add credentials</a> in Dashboard
              </p>
            </div>

            <div class="space-y-2">
              <Label>Chat ID</Label>
              <ExpressionInput
                ref="telegramChatIdInputRef"
                :model-value="selectedNode.data.chatId || ''"
                placeholder="$telegramTrigger.message.chat.id"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Chat ID"
                @update:model-value="updateNodeData('chatId', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Usually comes from the trigger: $telegramTrigger.message.chat.id
              </p>
            </div>

            <div class="space-y-2">
              <Label>Message</Label>
              <ExpressionInput
                ref="telegramMessageInputRef"
                :model-value="selectedNode.data.message || ''"
                :placeholder="exampleRef"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Message"
                @update:model-value="updateNodeData('message', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $ expressions like {{ exampleRef }} or $telegramTrigger.message.text
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'sendEmail'">
            <div class="space-y-2">
              <Label>SMTP Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="smtpCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <p
                v-if="!selectedNode.data.credentialId"
                class="text-xs text-muted-foreground"
              >
                <a
                  href="/?tab=credentials"
                  class="text-primary hover:underline"
                  @click.prevent="$router.push('/?tab=credentials')"
                >Add credentials</a> in Dashboard
              </p>
            </div>

            <div class="space-y-2">
              <Label>To</Label>
              <ExpressionInput
                :model-value="selectedNode.data.to || ''"
                placeholder="recipient@example.com"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="To"
                @update:model-value="updateNodeData('to', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Recipient email (comma-separated for multiple)
              </p>
            </div>

            <div class="space-y-2">
              <Label>Subject</Label>
              <ExpressionInput
                :model-value="selectedNode.data.subject || ''"
                placeholder="Email Subject"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Subject"
                @update:model-value="updateNodeData('subject', $event)"
              />
            </div>

            <div class="space-y-2">
              <Label>Body</Label>
              <ExpressionInput
                ref="sendEmailBodyInputRef"
                :model-value="selectedNode.data.emailBody || ''"
                :placeholder="exampleRef"
                :rows="4"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                dialog-title="Edit Email Body"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Body"
                @update:model-value="updateNodeData('emailBody', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $ expressions like {{ exampleRef }}
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'errorHandler'">
            <div class="space-y-2">
              <Label>Message</Label>
              <ExpressionInput
                :model-value="selectedNode.data.message || ''"
                placeholder="$error.message"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Message"
                @update:model-value="updateNodeData('message', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $error.message, $error.node_id, $error.node_label.
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'merge'">
            <div class="space-y-2">
              <Label>Number of Inputs</Label>
              <div class="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
                  :disabled="(selectedNode.data.inputCount || 2) <= 2"
                  @click="updateInputCount(-1)"
                >
                  <Minus class="w-4 h-4" />
                </Button>
                <span class="text-sm font-medium w-8 text-center">
                  {{ selectedNode.data.inputCount || 2 }}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-8 md:w-8"
                  :disabled="(selectedNode.data.inputCount || 2) >= 10"
                  @click="updateInputCount(1)"
                >
                  <Plus class="w-4 h-4" />
                </Button>
              </div>
              <p class="text-xs text-muted-foreground">
                Waits for all inputs before merging data.
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'set' || selectedNode.type === 'jsonOutputMapper'">
            <div class="space-y-3">
              <div class="flex items-center justify-between">
                <Label>Mappings (key = value)</Label>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-11 min-h-[44px] md:h-7 px-2"
                  @click="addMappingField"
                >
                  <Plus class="w-3 h-3 mr-1" />
                  Add
                </Button>
              </div>
              <div
                v-for="(mapping, index) in mappings"
                :key="index"
                class="space-y-1"
              >
                <div class="flex gap-1 items-center">
                  <Input
                    :model-value="mapping.key"
                    placeholder="key"
                    :class="[
                      'w-20 shrink-0 font-mono text-xs',
                      getMappingKeyError(mapping.key) ? 'border-red-500 focus:ring-red-500' : ''
                    ]"
                    @update:model-value="updateMappingField(index, 'key', $event)"
                  />
                  <span class="text-muted-foreground text-xs">=</span>
                  <ExpressionInput
                    :ref="(el: any) => setMappingInputRef(index, el)"
                    :model-value="mapping.value"
                    :placeholder="exampleRef"
                    single-line
                    class="flex-1 text-xs"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    navigation-enabled
                    :navigation-index="index"
                    :navigation-total="mappings.length"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    :dialog-key-label="mapping.key || `mapping ${index + 1}`"
                    @update:model-value="updateMappingField(index, 'value', $event)"
                    @navigate="handleSetMappingNavigate"
                    @register-field-index="onSetMappingRegisterFieldIndex"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-10 w-7 text-destructive shrink-0"
                    @click="removeMappingField(index)"
                  >
                    <Minus class="w-3 h-3" />
                  </Button>
                </div>
                <p
                  v-if="getMappingKeyError(mapping.key)"
                  class="text-xs text-red-500 flex items-center gap-1 ml-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  {{ getMappingKeyError(mapping.key) }}
                </p>
                <p
                  v-if="getExpressionWarning(mapping.value)"
                  class="text-xs text-amber-500 flex items-center gap-1 ml-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  {{ getExpressionWarning(mapping.value) }}
                </p>
              </div>
              <p
                v-if="selectedNode.type === 'set'"
                class="text-xs text-muted-foreground"
              >
                Transform input data to custom output. Values support $ expressions like {{ exampleRef }}
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Builds the JSON object returned to webhook and run callers when this node is the only terminal
                (no <code class="text-[10px]">result</code> wrapper or outer node label). Values support
                $ expressions like {{ exampleRef }}
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'wait'">
            <div class="space-y-2">
              <Label>Duration (ms)</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.duration || 1000"
                min="1"
                max="60000"
                step="100"
                @update:model-value="handleDurationChange($event)"
              />
              <p class="text-xs text-muted-foreground">
                Wait time in milliseconds (1ms - 60 seconds)
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'variable'">
            <div class="space-y-2">
              <Label>Variable Name</Label>
              <Input
                :model-value="selectedNode.data.variableName || ''"
                placeholder="myVariable"
                :class="{ 'border-red-500 focus:ring-red-500': variableNameError }"
                @update:model-value="updateNodeData('variableName', $event)"
              />
              <p
                v-if="variableNameError"
                class="text-xs text-red-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                {{ variableNameError }}
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Access via: {{ selectedNode.data.isGlobal ? '$global' : '$vars' }}.{{ selectedNode.data.variableName ||
                  'variableName' }}
              </p>
            </div>
            <div class="space-y-2">
              <Label>Value</Label>
              <ExpressionInput
                ref="variableValueInputRef"
                :model-value="selectedNode.data.variableValue || ''"
                :placeholder="`${exampleRef} or literal value`"
                :rows="2"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Value"
                @update:model-value="updateNodeData('variableValue', $event)"
              />
              <p
                v-if="getExpressionWarning(selectedNode.data.variableValue || '')"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                {{ getExpressionWarning(selectedNode.data.variableValue || '') }}
              </p>
              <p class="text-xs text-muted-foreground">
                Use $ expressions or enter a literal value
              </p>
            </div>
            <div class="space-y-2">
              <Label>Type</Label>
              <Select
                :model-value="selectedNode.data.variableType || 'auto'"
                :options="variableTypeOptions"
                @update:model-value="updateNodeData('variableType', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Auto-detect or force a specific type
              </p>
            </div>
            <div class="flex items-center gap-2 pt-2">
              <input
                :id="`variable-isGlobal-${selectedNode.id}`"
                type="checkbox"
                :checked="!!selectedNode.data.isGlobal"
                class="rounded border-border"
                @change="updateNodeData('isGlobal', ($event.target as HTMLInputElement).checked)"
              >
              <Label
                :for="`variable-isGlobal-${selectedNode.id}`"
                class="cursor-pointer text-sm font-normal"
              >
                Store in Global Variable Store
              </Label>
            </div>
          </template>

          <template v-if="selectedNode.type === 'loop'">
            <div class="space-y-2">
              <Label>Array Expression</Label>
              <ExpressionInput
                ref="loopArrayExpressionInputRef"
                :model-value="selectedNode.data.arrayExpression || ''"
                placeholder="$input.items"
                :rows="2"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Array expression"
                @update:model-value="updateNodeData('arrayExpression', $event)"
              />
              <p
                v-if="getExpressionWarning(selectedNode.data.arrayExpression || '')"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                {{ getExpressionWarning(selectedNode.data.arrayExpression || '') }}
              </p>
              <p class="text-xs text-muted-foreground">
                Expression that resolves to an array to iterate over
              </p>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Outputs</Label>
              <div class="text-xs space-y-1">
                <div class="flex items-center gap-2">
                  <span class="px-1.5 py-0.5 rounded bg-node-loop/20 text-node-loop font-medium">loop</span>
                  <span class="text-muted-foreground">Runs for each item in array</span>
                </div>
                <div class="flex items-center gap-2">
                  <span class="px-1.5 py-0.5 rounded bg-green-500/20 text-green-500 font-medium">done</span>
                  <span class="text-muted-foreground">Runs after all iterations complete</span>
                </div>
              </div>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Available Fields</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <div>${{ selectedNode.data.label }}.item - Current item</div>
                <div>${{ selectedNode.data.label }}.index - Current index (0-based)</div>
                <div>${{ selectedNode.data.label }}.total - Total items count</div>
                <div>${{ selectedNode.data.label }}.isFirst - Boolean</div>
                <div>${{ selectedNode.data.label }}.isLast - Boolean</div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'disableNode'">
            <div class="space-y-2">
              <Label>Target Node</Label>
              <Select
                :model-value="selectedNode.data.targetNodeLabel || ''"
                :options="availableTargetNodes"
                placeholder="Select node to disable"
                @update:model-value="updateNodeData('targetNodeLabel', $event)"
              />
              <p class="text-xs text-muted-foreground">
                The selected node will be permanently disabled when this node executes
              </p>
            </div>
            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Output</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <div>${{ selectedNode.data.label }}.targetNode - Disabled node label</div>
                <div>${{ selectedNode.data.label }}.disabled - Always true on success</div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'redis'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="redisCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <div v-if="!selectedNode.data.credentialId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Credential is required.
                </p>
                <p class="text-xs text-muted-foreground mt-1">
                  <a
                    href="/?tab=credentials"
                    class="text-primary hover:underline"
                    @click.prevent="$router.push('/?tab=credentials')"
                  >Add credentials</a> in Dashboard
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.redisOperation || ''"
                :options="redisOperationOptions"
                @update:model-value="updateNodeData('redisOperation', $event)"
              />
              <p
                v-if="!selectedNode.data.redisOperation"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Operation is required
              </p>
            </div>

            <div class="space-y-2">
              <Label>Key <span class="text-destructive">*</span></Label>
              <ExpressionInput
                ref="redisKeyInputRef"
                :model-value="selectedNode.data.redisKey || ''"
                placeholder="cache:$userInput.body.userId"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Key"
                @update:model-value="updateNodeData('redisKey', $event)"
              />
              <p
                v-if="!selectedNode.data.redisKey || selectedNode.data.redisKey.trim() === ''"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Key is required
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Redis key (supports expressions)
              </p>
            </div>

            <template v-if="selectedNode.data.redisOperation === 'set'">
              <div class="space-y-2">
                <Label>Value</Label>
                <ExpressionInput
                  :model-value="selectedNode.data.redisValue || ''"
                  placeholder="$previousNode.data"
                  :rows="2"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Value"
                  @update:model-value="updateNodeData('redisValue', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Value to store (supports expressions)
                </p>
              </div>

              <div class="space-y-2">
                <Label>TTL (seconds)</Label>
                <Input
                  type="number"
                  :model-value="selectedNode.data.redisTtl || ''"
                  placeholder="3600 (optional)"
                  min="0"
                  @update:model-value="updateNodeData('redisTtl', $event ? parseInt($event as string) : undefined)"
                />
                <p class="text-xs text-muted-foreground">
                  Time-to-live in seconds (leave empty for no expiration)
                </p>
              </div>
            </template>

            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Output</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <template v-if="selectedNode.data.redisOperation === 'set'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.key - The key that was set</div>
                  <div>${{ selectedNode.data.label }}.ttl - TTL value (or null)</div>
                </template>
                <template v-else-if="selectedNode.data.redisOperation === 'get'">
                  <div>${{ selectedNode.data.label }}.value - Retrieved value</div>
                  <div>${{ selectedNode.data.label }}.exists - Boolean</div>
                  <div>${{ selectedNode.data.label }}.key - The key queried</div>
                </template>
                <template v-else-if="selectedNode.data.redisOperation === 'hasKey'">
                  <div>${{ selectedNode.data.label }}.exists - Boolean</div>
                  <div>${{ selectedNode.data.label }}.key - The key checked</div>
                </template>
                <template v-else-if="selectedNode.data.redisOperation === 'deleteKey'">
                  <div>${{ selectedNode.data.label }}.deleted - Boolean</div>
                  <div>${{ selectedNode.data.label }}.key - The key deleted</div>
                </template>
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'rag'">
            <div class="space-y-2">
              <Label>Vector Store</Label>
              <Select
                :model-value="selectedNode.data.vectorStoreId || ''"
                :options="vectorStoreOptions"
                @update:model-value="updateNodeData('vectorStoreId', $event)"
              />
              <div v-if="!selectedNode.data.vectorStoreId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Vector Store is required.
                </p>
                <p class="text-xs text-muted-foreground mt-1">
                  <a
                    href="/?tab=vectorstores"
                    class="text-primary hover:underline"
                    @click.prevent="$router.push('/?tab=vectorstores')"
                  >Create a vector store</a> in Dashboard
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.ragOperation || ''"
                :options="ragOperationOptions"
                @update:model-value="updateNodeData('ragOperation', $event)"
              />
              <p
                v-if="!selectedNode.data.ragOperation"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Operation is required
              </p>
            </div>

            <template v-if="selectedNode.data.ragOperation === 'insert'">
              <div class="space-y-2">
                <Label>Document Content <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="ragDocumentInputRef"
                  :model-value="selectedNode.data.documentContent || ''"
                  placeholder="$input.text"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Document content"
                  @update:model-value="updateNodeData('documentContent', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Text content to embed and store (supports expressions)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Document Metadata (JSON)</Label>
                <Textarea
                  :model-value="selectedNode.data.documentMetadata || '{}'"
                  placeholder="{&quot;source&quot;: &quot;manual&quot;, &quot;category&quot;: &quot;faq&quot;}"
                  :rows="3"
                  @update:model-value="updateNodeData('documentMetadata', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  JSON metadata to associate with the document
                </p>
              </div>
            </template>

            <template v-if="selectedNode.data.ragOperation === 'search'">
              <div class="space-y-2">
                <Label>Query Text <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="ragQueryInputRef"
                  :model-value="selectedNode.data.queryText || ''"
                  placeholder="$input.text"
                  :rows="2"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Query text"
                  @update:model-value="updateNodeData('queryText', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Query text to embed and search (supports expressions)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Search Limit</Label>
                <Input
                  type="number"
                  :model-value="selectedNode.data.searchLimit || 5"
                  placeholder="5"
                  min="1"
                  max="100"
                  @update:model-value="updateNodeData('searchLimit', $event ? parseInt($event as string) : 5)"
                />
                <p class="text-xs text-muted-foreground">
                  Number of results to return (default: 5)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Metadata Filters (JSON)</Label>
                <Textarea
                  :model-value="selectedNode.data.metadataFilters || '{}'"
                  placeholder="{&quot;category&quot;: &quot;faq&quot;}"
                  :rows="3"
                  @update:model-value="updateNodeData('metadataFilters', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Filter results by metadata (exact match)
                </p>
              </div>

              <div class="space-y-3 pt-3 border-t">
                <div class="flex items-center justify-between">
                  <Label>Enable Reranker</Label>
                  <label class="relative inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      :checked="selectedNode.data.enableReranker || false"
                      class="sr-only peer"
                      @change="updateNodeData('enableReranker', ($event.target as HTMLInputElement).checked)"
                    >
                    <div
                      class="w-9 h-5 bg-muted rounded-full peer peer-checked:bg-primary transition-colors after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-4"
                    />
                  </label>
                </div>
                <p class="text-xs text-muted-foreground">
                  Use Cohere to rerank results for better relevance
                </p>

                <template v-if="selectedNode.data.enableReranker">
                  <div class="space-y-2">
                    <Label>Cohere Credential</Label>
                    <Select
                      :model-value="selectedNode.data.rerankerCredentialId || ''"
                      :options="cohereCredentialOptions"
                      @update:model-value="updateNodeData('rerankerCredentialId', $event)"
                    />
                    <div v-if="!selectedNode.data.rerankerCredentialId">
                      <p class="text-xs text-amber-500 flex items-center gap-1">
                        <AlertTriangle class="h-3 w-3" />
                        Cohere credential required for reranking
                      </p>
                      <p class="text-xs text-muted-foreground mt-1">
                        <a
                          href="/?tab=credentials"
                          class="text-primary hover:underline"
                          @click.prevent="$router.push('/?tab=credentials')"
                        >Add Cohere credential</a> in Dashboard
                      </p>
                    </div>
                  </div>

                  <div class="space-y-2">
                    <Label>Reranker Top N</Label>
                    <Input
                      type="number"
                      :model-value="selectedNode.data.rerankerTopN || selectedNode.data.searchLimit || 5"
                      placeholder="5"
                      min="1"
                      max="50"
                      @update:model-value="updateNodeData('rerankerTopN', $event ? parseInt($event as string) : 5)"
                    />
                    <p class="text-xs text-muted-foreground">
                      Number of top results to return after reranking
                    </p>
                  </div>
                </template>
              </div>
            </template>

            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Output</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <template v-if="selectedNode.data.ragOperation === 'insert'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.operation - "insert"</div>
                  <div>${{ selectedNode.data.label }}.point_id - Vector ID</div>
                </template>
                <template v-else-if="selectedNode.data.ragOperation === 'search'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.operation - "search"</div>
                  <div>${{ selectedNode.data.label }}.reranked - Boolean</div>
                  <div>${{ selectedNode.data.label }}.results - Array of results</div>
                  <div>${{ selectedNode.data.label }}.results[0].text - Document text</div>
                  <div>${{ selectedNode.data.label }}.results[0].score - Similarity score</div>
                  <div v-if="selectedNode.data.enableReranker">
                    ${{ selectedNode.data.label }}.results[0].relevance_score - Reranker score
                  </div>
                  <div>${{ selectedNode.data.label }}.results[0].metadata - Metadata</div>
                  <div>${{ selectedNode.data.label }}.count - Number of results</div>
                </template>
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'grist'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="gristCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <div v-if="!selectedNode.data.credentialId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Credential is required.
                </p>
                <p class="text-xs text-muted-foreground mt-1">
                  <a
                    href="/?tab=credentials"
                    class="text-primary hover:underline"
                    @click.prevent="$router.push('/?tab=credentials')"
                  >Add credentials</a> in Dashboard
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.gristOperation || ''"
                :options="gristOperationOptions"
                @update:model-value="updateNodeData('gristOperation', $event)"
              />
              <p
                v-if="!selectedNode.data.gristOperation"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Operation is required
              </p>
            </div>

            <div class="space-y-2">
              <Label>Document ID <span class="text-destructive">*</span></Label>
              <ExpressionInput
                ref="gristDocIdExpressionInputRef"
                :model-value="selectedNode.data.gristDocId || ''"
                placeholder="your-document-id"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :navigation-enabled="gristExpressionFieldCount > 1"
                :navigation-index="0"
                :navigation-total="gristExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Document ID"
                @navigate="handleGristExpressionFieldNavigate"
                @register-field-index="onGristRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('gristDocId', $event)"
              />
              <p
                v-if="!selectedNode.data.gristDocId || selectedNode.data.gristDocId.trim() === ''"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Document ID is required
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Grist document ID (found in document URL)
              </p>
            </div>

            <template v-if="selectedNode.data.gristOperation && selectedNode.data.gristOperation !== 'listTables'">
              <div class="space-y-2">
                <Label>Table ID <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="gristTableIdExpressionInputRef"
                  :model-value="selectedNode.data.gristTableId || ''"
                  placeholder="Table1"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="gristExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="gristExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Table ID"
                  @navigate="handleGristExpressionFieldNavigate"
                  @register-field-index="onGristRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gristTableId', $event)"
                />
                <p
                  v-if="!selectedNode.data.gristTableId || selectedNode.data.gristTableId.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Table ID is required
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Use listTables operation to discover table IDs
                </p>
              </div>
            </template>

            <template
              v-if="selectedNode.data.gristOperation === 'getRecord' || selectedNode.data.gristOperation === 'updateRecord'"
            >
              <div class="space-y-2">
                <Label>Record ID <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="gristRecordIdExpressionInputRef"
                  :model-value="selectedNode.data.gristRecordId || ''"
                  placeholder="$input.recordId"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="gristExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="gristExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Record ID"
                  @navigate="handleGristExpressionFieldNavigate"
                  @register-field-index="onGristRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gristRecordId', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Numeric record ID (supports expressions)
                </p>
              </div>
            </template>

            <template
              v-if="selectedNode.data.gristOperation === 'createRecord' || selectedNode.data.gristOperation === 'updateRecord'"
            >
              <JsonInputPanel
                ref="gristRecordDataJsonInputRef"
                :model-value="selectedNode.data.gristRecordData || '{}'"
                :columns="gristColumns"
                :input-mode="selectedNode.data.gristRecordDataInputMode || 'raw'"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                placeholder="{
  &quot;Name&quot;: &quot;John&quot;,
  &quot;Email&quot;: &quot;john@example.com&quot;
}"
                :rows="4"
                label="Record Data (JSON)"
                :navigation-enabled="gristExpressionFieldCount > 1"
                :navigation-index="selectedNode.data.gristOperation === 'updateRecord' ? 3 : 2"
                :selective-navigation-base-index="selectedNode.data.gristOperation === 'updateRecord' ? 3 : 2"
                :navigation-total="gristExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Record data (JSON)"
                @update:model-value="updateNodeData('gristRecordData', $event)"
                @update:input-mode="updateNodeData('gristRecordDataInputMode', $event)"
                @navigate="handleGristExpressionFieldNavigate"
                @register-field-index="onGristRegisterExpressionFieldIndex"
              />
            </template>

            <template
              v-if="selectedNode.data.gristOperation === 'createRecords' || selectedNode.data.gristOperation === 'updateRecords'"
            >
              <div class="space-y-2">
                <Label>Records Data (JSON Array)</Label>
                <ExpressionInput
                  ref="gristRecordsDataExpressionInputRef"
                  :model-value="selectedNode.data.gristRecordsData || '[]'"
                  placeholder="[{&quot;Name&quot;: &quot;John&quot;}, {&quot;Name&quot;: &quot;Jane&quot;}]"
                  :rows="5"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="gristExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="gristExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Records data"
                  @navigate="handleGristExpressionFieldNavigate"
                  @register-field-index="onGristRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gristRecordsData', $event)"
                />
                <div class="flex items-center justify-between">
                  <p class="text-xs text-muted-foreground">
                    <template v-if="selectedNode.data.gristOperation === 'updateRecords'">
                      Array of objects with "id" and "fields" properties
                    </template>
                    <template v-else>
                      Array of record objects (batch create)
                    </template>
                  </p>
                  <button
                    class="text-xs text-primary hover:underline"
                    @click="() => { try { const parsed = JSON.parse(selectedNode?.data.gristRecordsData || '[]'); updateNodeData('gristRecordsData', JSON.stringify(parsed, null, 2)); } catch {} }"
                  >
                    Format
                  </button>
                </div>
              </div>
            </template>

            <template v-if="selectedNode.data.gristOperation === 'deleteRecord'">
              <div class="space-y-2">
                <Label>Record ID (single)</Label>
                <ExpressionInput
                  ref="gristRecordIdExpressionInputRef"
                  :model-value="selectedNode.data.gristRecordId || ''"
                  placeholder="$input.recordId"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="gristExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="gristExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Record ID (single)"
                  @navigate="handleGristExpressionFieldNavigate"
                  @register-field-index="onGristRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gristRecordId', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Single record ID to delete
                </p>
              </div>
              <div class="space-y-2">
                <Label>Record IDs (batch)</Label>
                <ExpressionInput
                  ref="gristRecordIdsExpressionInputRef"
                  :model-value="selectedNode.data.gristRecordIds || ''"
                  placeholder="[1, 2, 3]"
                  :rows="2"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="gristExpressionFieldCount > 1"
                  :navigation-index="3"
                  :navigation-total="gristExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Record IDs (batch)"
                  @navigate="handleGristExpressionFieldNavigate"
                  @register-field-index="onGristRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gristRecordIds', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  JSON array of record IDs for batch delete (overrides single ID)
                </p>
              </div>
            </template>

            <template v-if="selectedNode.data.gristOperation === 'getRecords'">
              <JsonInputPanel
                ref="gristFilterJsonInputRef"
                :model-value="selectedNode.data.gristFilter || '{}'"
                :columns="gristColumns"
                :input-mode="selectedNode.data.gristFilterInputMode || 'raw'"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                placeholder="{
  &quot;Status&quot;: [&quot;Active&quot;, &quot;Pending&quot;]
}"
                :rows="3"
                label="Filter (JSON)"
                :navigation-enabled="gristExpressionFieldCount > 1"
                :navigation-index="2"
                :selective-navigation-base-index="2"
                :navigation-total="gristExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Filter (JSON)"
                @update:model-value="updateNodeData('gristFilter', $event)"
                @update:input-mode="updateNodeData('gristFilterInputMode', $event)"
                @navigate="handleGristExpressionFieldNavigate"
                @register-field-index="onGristRegisterExpressionFieldIndex"
              />

              <div class="space-y-2">
                <Label>Sort</Label>
                <ExpressionInput
                  ref="gristSortExpressionInputRef"
                  :model-value="selectedNode.data.gristSort || ''"
                  placeholder="Name,-CreatedAt"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="gristExpressionFieldCount > 1"
                  :navigation-index="(selectedNode.data.gristFilterInputMode || 'raw') === 'raw' ? 3 : 3 + gristColumns.length"
                  :navigation-total="gristExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Sort"
                  @navigate="handleGristExpressionFieldNavigate"
                  @register-field-index="onGristRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gristSort', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Column names to sort by (prefix with - for descending)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Limit (optional)</Label>
                <Input
                  type="number"
                  :model-value="selectedNode.data.gristLimit || ''"
                  placeholder="Leave empty for all records"
                  min="1"
                  @update:model-value="updateNodeData('gristLimit', $event ? parseInt($event as string) : '')"
                />
                <p class="text-xs text-muted-foreground">
                  Maximum number of records to return (leave empty for all)
                </p>
              </div>
            </template>

            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Output</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <template v-if="selectedNode.data.gristOperation === 'listTables'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.tables - Array of table info</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'listColumns'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.columns - Array of column info</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'getRecord'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.record - Record object</div>
                  <div>${{ selectedNode.data.label }}.found - Boolean</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'getRecords'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.records - Array of records</div>
                  <div>${{ selectedNode.data.label }}.count - Number of records</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'createRecord'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.record - Created record</div>
                  <div>${{ selectedNode.data.label }}.id - New record ID</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'createRecords'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.records - Created records</div>
                  <div>${{ selectedNode.data.label }}.count - Number created</div>
                  <div>${{ selectedNode.data.label }}.ids - Array of new IDs</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'updateRecord'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.id - Updated record ID</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'updateRecords'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.count - Number updated</div>
                </template>
                <template v-else-if="selectedNode.data.gristOperation === 'deleteRecord'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.deleted - Array of deleted IDs</div>
                  <div>${{ selectedNode.data.label }}.count - Number deleted</div>
                </template>
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'googleSheets'">
            <div class="space-y-2">
              <Label>Google Sheets Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="googleSheetsCredentialOptions"
                :disabled="!isWorkflowOwner"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <div v-if="!selectedNode.data.credentialId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Credential is required.
                </p>
                <p class="text-xs text-muted-foreground mt-1">
                  <a
                    href="/?tab=credentials"
                    class="text-primary hover:underline"
                    @click.prevent="$router.push('/?tab=credentials')"
                  >Add credentials</a> in Dashboard
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.gsOperation || ''"
                :options="googleSheetsOperationOptions"
                @update:model-value="updateNodeData('gsOperation', $event)"
              />
            </div>

            <template v-if="selectedNode.data.gsOperation">
              <div class="space-y-2">
                <Label>Spreadsheet ID or URL</Label>
                <ExpressionInput
                  ref="googleSheetsSpreadsheetIdExpressionInputRef"
                  :model-value="selectedNode.data.gsSpreadsheetId || ''"
                  placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms or full URL"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="googleSheetsExpressionFieldCount > 1"
                  :navigation-index="0"
                  :navigation-total="googleSheetsExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Spreadsheet ID or URL"
                  @navigate="handleGoogleSheetsExpressionFieldNavigate"
                  @register-field-index="onGoogleSheetsRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gsSpreadsheetId', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Accepts a full Google Sheets URL or bare spreadsheet ID
                </p>
              </div>

              <div
                v-if="selectedNode.data.gsOperation !== 'getSheetInfo'"
                class="space-y-2"
              >
                <Label>Sheet Name</Label>
                <ExpressionInput
                  ref="googleSheetsSheetNameExpressionInputRef"
                  :model-value="selectedNode.data.gsSheetName || 'Sheet1'"
                  placeholder="Sheet1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="googleSheetsExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="googleSheetsExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Sheet name"
                  @navigate="handleGoogleSheetsExpressionFieldNavigate"
                  @register-field-index="onGoogleSheetsRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('gsSheetName', $event)"
                />
              </div>

              <!-- Read: declarative row/header controls -->
              <template v-if="selectedNode.data.gsOperation === 'readRange'">
                <div class="grid grid-cols-2 gap-2">
                  <div class="space-y-1">
                    <Label class="text-xs">Start row</Label>
                    <input
                      type="number"
                      min="1"
                      :value="selectedNode.data.gsStartRow ?? '1'"
                      placeholder="1"
                      class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      @input="updateNodeData('gsStartRow', String(($event.target as HTMLInputElement).value))"
                    >
                  </div>
                  <div class="space-y-1">
                    <Label class="text-xs">Max rows (0 = all)</Label>
                    <input
                      type="number"
                      min="0"
                      :value="selectedNode.data.gsMaxRows ?? '0'"
                      placeholder="0"
                      class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                      @input="updateNodeData('gsMaxRows', String(($event.target as HTMLInputElement).value))"
                    >
                  </div>
                </div>
                <div class="flex items-center gap-2 pt-1">
                  <input
                    id="gs-has-header"
                    type="checkbox"
                    :checked="selectedNode.data.gsHasHeader !== false"
                    class="rounded border-border"
                    @change="updateNodeData('gsHasHeader', ($event.target as HTMLInputElement).checked)"
                  >
                  <label
                    for="gs-has-header"
                    class="text-xs cursor-pointer select-none"
                  >First row is header (returns objects with column names as keys)</label>
                </div>
              </template>

              <!-- Update: target sheet row + values (single values PUT, not batchUpdate) -->
              <template v-if="selectedNode.data.gsOperation === 'updateRange'">
                <div class="space-y-1">
                  <Label class="text-xs">Row number</Label>
                  <input
                    type="number"
                    min="1"
                    :value="selectedNode.data.gsUpdateRow ?? selectedNode.data.gsStartRow ?? '1'"
                    placeholder="1"
                    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    @input="updateNodeData('gsUpdateRow', String(($event.target as HTMLInputElement).value))"
                  >
                  <p class="text-xs text-muted-foreground">
                    Sheet row number to update (1-based).
                  </p>
                </div>
              </template>

              <!-- Clear: full sheet (columns A–Z); optional first row preserved -->
              <template v-if="selectedNode.data.gsOperation === 'clearRange'">
                <p class="text-xs text-muted-foreground">
                  Clears all values in columns A through Z for this tab (same width as read/update).
                </p>
                <div class="flex items-center gap-2 pt-1">
                  <input
                    id="gs-keep-header-clear"
                    type="checkbox"
                    :checked="selectedNode.data.gsKeepHeader === true"
                    class="rounded border-border"
                    @change="updateNodeData('gsKeepHeader', ($event.target as HTMLInputElement).checked)"
                  >
                  <label
                    for="gs-keep-header-clear"
                    class="text-xs cursor-pointer select-none"
                  >Keep header row (preserve row 1, clear rows below)</label>
                </div>
              </template>

              <template v-if="selectedNode.data.gsOperation === 'appendRows'">
                <div class="space-y-2">
                  <Label class="text-xs">Insert rows</Label>
                  <Select
                    :model-value="selectedNode.data.gsAppendPlacement || 'append'"
                    :options="googleSheetsAppendPlacementOptions"
                    @update:model-value="updateNodeData('gsAppendPlacement', $event)"
                  />
                  <p class="text-xs text-muted-foreground">
                    Bottom appends after the last row with data. Top inserts directly under row 1 and shifts existing rows down.
                  </p>
                </div>
              </template>

              <!-- Values: append + update -->
              <div
                v-if="selectedNode.data.gsOperation === 'appendRows' || selectedNode.data.gsOperation === 'updateRange'"
                class="space-y-2"
              >
                <Label>Values (JSON array of rows)</Label>
                <GoogleSheetsValuesInputPanel
                  ref="googleSheetsValuesInputRef"
                  :model-value="selectedNode.data.gsValues || '[]'"
                  :input-mode="selectedNode.data.gsValuesInputMode === 'selective' ? 'selective' : 'raw'"
                  :selective-cols="selectedNode.data.gsValuesSelectiveCols || '3'"
                  :selective-single-row="true"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="googleSheetsExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="googleSheetsExpressionFieldCount"
                  :selective-navigation-base-index="2"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  @update:model-value="updateNodeData('gsValues', $event)"
                  @update:input-mode="updateNodeData('gsValuesInputMode', $event)"
                  @update:selective-cols="updateNodeData('gsValuesSelectiveCols', $event)"
                  @navigate="handleGoogleSheetsExpressionFieldNavigate"
                  @register-field-index="onGoogleSheetsRegisterExpressionFieldIndex"
                />
              </div>
            </template>

            <div class="rounded-md bg-muted/40 border p-3 space-y-1">
              <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Output
              </p>
              <div class="text-xs font-mono space-y-0.5">
                <template v-if="selectedNode.data.gsOperation === 'readRange'">
                  <div>${{ selectedNode.data.label }}.rows - Array of row objects</div>
                  <div>${{ selectedNode.data.label }}.total - Number of rows returned</div>
                </template>
                <template v-else-if="selectedNode.data.gsOperation === 'appendRows'">
                  <div>${{ selectedNode.data.label }}.updatedRange - Range that was updated</div>
                  <div>${{ selectedNode.data.label }}.updatedRows - Number of rows appended</div>
                </template>
                <template v-else-if="selectedNode.data.gsOperation === 'updateRange'">
                  <div>${{ selectedNode.data.label }}.updatedRange - Range that was updated</div>
                  <div>${{ selectedNode.data.label }}.updatedCells - Number of cells updated</div>
                </template>
                <template v-else-if="selectedNode.data.gsOperation === 'clearRange'">
                  <div>${{ selectedNode.data.label }}.clearedRange - Range that was cleared</div>
                </template>
                <template v-else-if="selectedNode.data.gsOperation === 'getSheetInfo'">
                  <div>${{ selectedNode.data.label }}.sheets - Array of {title, sheetId, index}</div>
                </template>
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'bigquery'">
            <div class="space-y-2">
              <Label>BigQuery Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="bigQueryCredentialOptions"
                :disabled="!isWorkflowOwner"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <div v-if="!selectedNode.data.credentialId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Credential is required.
                </p>
                <p class="text-xs text-muted-foreground mt-1">
                  <a
                    href="/?tab=credentials"
                    class="text-primary hover:underline"
                    @click.prevent="$router.push('/?tab=credentials')"
                  >Add credentials</a> in Dashboard
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.bqOperation || ''"
                :options="bigQueryOperationOptions"
                @update:model-value="updateNodeData('bqOperation', $event)"
              />
            </div>

            <template v-if="selectedNode.data.bqOperation">
              <div class="space-y-2">
                <Label>Project ID</Label>
                <ExpressionInput
                  ref="bqProjectIdExpressionInputRef"
                  :model-value="selectedNode.data.bqProjectId || ''"
                  placeholder="my-gcp-project"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="bigQueryExpressionFieldCount > 1"
                  :navigation-index="0"
                  :navigation-total="bigQueryExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Project ID"
                  @update:model-value="updateNodeData('bqProjectId', $event)"
                  @navigate="handleBigQueryExpressionFieldNavigate"
                  @register-field-index="onBigQueryRegisterExpressionFieldIndex"
                />
              </div>

              <!-- query operation fields -->
              <template v-if="selectedNode.data.bqOperation === 'query'">
                <div class="space-y-2">
                  <Label>SQL Query</Label>
                  <ExpressionInput
                    ref="bqQueryExpressionInputRef"
                    :model-value="selectedNode.data.bqQuery || ''"
                    placeholder="SELECT * FROM `dataset.table` LIMIT 10"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :navigation-enabled="bigQueryExpressionFieldCount > 1"
                    :navigation-index="1"
                    :navigation-total="bigQueryExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="SQL Query"
                    @update:model-value="updateNodeData('bqQuery', $event)"
                    @navigate="handleBigQueryExpressionFieldNavigate"
                    @register-field-index="onBigQueryRegisterExpressionFieldIndex"
                  />
                </div>
                <div class="space-y-2">
                  <Label>Max Results <span class="text-muted-foreground font-normal">(0 = unlimited)</span></Label>
                  <input
                    type="number"
                    min="0"
                    :value="selectedNode.data.bqMaxResults ?? '1000'"
                    placeholder="1000"
                    class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    @input="updateNodeData('bqMaxResults', String(($event.target as HTMLInputElement).value))"
                  >
                </div>
              </template>

              <!-- insertRows operation fields -->
              <template v-if="selectedNode.data.bqOperation === 'insertRows'">
                <div class="space-y-2">
                  <Label>Dataset ID</Label>
                  <ExpressionInput
                    ref="bqDatasetIdExpressionInputRef"
                    :model-value="selectedNode.data.bqDatasetId || ''"
                    placeholder="my_dataset"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :navigation-enabled="bigQueryExpressionFieldCount > 1"
                    :navigation-index="1"
                    :navigation-total="bigQueryExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Dataset ID"
                    @update:model-value="updateNodeData('bqDatasetId', $event)"
                    @navigate="handleBigQueryExpressionFieldNavigate"
                    @register-field-index="onBigQueryRegisterExpressionFieldIndex"
                  />
                </div>
                <div class="space-y-2">
                  <Label>Table ID</Label>
                  <ExpressionInput
                    ref="bqTableIdExpressionInputRef"
                    :model-value="selectedNode.data.bqTableId || ''"
                    placeholder="my_table"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :navigation-enabled="bigQueryExpressionFieldCount > 1"
                    :navigation-index="2"
                    :navigation-total="bigQueryExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Table ID"
                    @update:model-value="updateNodeData('bqTableId', $event)"
                    @navigate="handleBigQueryExpressionFieldNavigate"
                    @register-field-index="onBigQueryRegisterExpressionFieldIndex"
                  />
                </div>

                <!-- Row input mode toggle -->
                <div class="flex items-center gap-2 rounded-md border border-input p-1">
                  <button
                    :class="[
                      'flex-1 rounded text-xs py-1 transition-colors',
                      (selectedNode.data.bqRowsInputMode || 'raw') === 'raw'
                        ? 'bg-primary text-primary-foreground font-medium'
                        : 'text-muted-foreground hover:text-foreground'
                    ]"
                    @click="switchBqToRaw()"
                  >
                    JSON array
                  </button>
                  <button
                    :class="[
                      'flex-1 rounded text-xs py-1 transition-colors',
                      selectedNode.data.bqRowsInputMode === 'selective'
                        ? 'bg-primary text-primary-foreground font-medium'
                        : 'text-muted-foreground hover:text-foreground'
                    ]"
                    @click="updateNodeData('bqRowsInputMode', 'selective')"
                  >
                    Key-value
                  </button>
                </div>

                <!-- Raw JSON array mode -->
                <div
                  v-if="(selectedNode.data.bqRowsInputMode || 'raw') === 'raw'"
                  class="space-y-2"
                >
                  <Label>Rows (JSON array)</Label>
                  <ExpressionInput
                    ref="bqRowsExpressionInputRef"
                    :model-value="selectedNode.data.bqRows || '[]'"
                    placeholder="[{&quot;col&quot;: &quot;$input.value&quot;}]"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    :navigation-enabled="bigQueryExpressionFieldCount > 1"
                    :navigation-index="3"
                    :navigation-total="bigQueryExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Rows"
                    @update:model-value="updateNodeData('bqRows', $event)"
                    @navigate="handleBigQueryExpressionFieldNavigate"
                    @register-field-index="onBigQueryRegisterExpressionFieldIndex"
                  />
                  <p class="text-xs text-muted-foreground">
                    JSON array of row objects; each key must match a column name in the table.
                  </p>
                </div>

                <!-- Selective key-value mode -->
                <div
                  v-else
                  class="space-y-3"
                >
                  <div class="flex items-center justify-between">
                    <Label>Row fields</Label>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-11 min-h-[44px] md:h-7 px-2"
                      @click="addBqMapping"
                    >
                      <Plus class="w-3 h-3 mr-1" />
                      Add
                    </Button>
                  </div>
                  <div
                    v-for="(mapping, index) in bqMappings"
                    :key="index"
                    class="flex gap-1 items-center"
                  >
                    <Input
                      :model-value="mapping.key"
                      placeholder="column"
                      class="w-24 shrink-0 font-mono text-xs"
                      @update:model-value="updateBqMapping(index, 'key', $event)"
                    />
                    <span class="text-muted-foreground text-xs">=</span>
                    <ExpressionInput
                      :ref="(el: any) => bqMappingInputRef(index, el)"
                      :model-value="mapping.value"
                      :placeholder="exampleRef"
                      single-line
                      class="flex-1 text-xs"
                      :nodes="workflowStore.nodes"
                      :node-results="workflowStore.nodeResults"
                      :edges="workflowStore.edges"
                      :current-node-id="selectedNode.id"
                      :navigation-enabled="bigQueryExpressionFieldCount > 1"
                      :navigation-index="index + 3"
                      :navigation-total="bigQueryExpressionFieldCount"
                      :dialog-node-label="selectedNodeEvaluateDialogLabel"
                      :dialog-key-label="mapping.key || `field ${index + 1}`"
                      @update:model-value="updateBqMapping(index, 'value', $event)"
                      @navigate="handleBigQueryExpressionFieldNavigate"
                      @register-field-index="onBigQueryRegisterExpressionFieldIndex"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      class="h-10 w-7 text-destructive shrink-0"
                      @click="removeBqMapping(index)"
                    >
                      <Minus class="w-3 h-3" />
                    </Button>
                  </div>
                  <p class="text-xs text-muted-foreground">
                    One row is inserted per execution. Add a field for each column.
                  </p>
                </div>
              </template>
            </template>

            <div class="rounded-md bg-muted/40 border p-3 space-y-1">
              <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Output
              </p>
              <div class="text-xs font-mono space-y-0.5">
                <template v-if="selectedNode.data.bqOperation === 'query'">
                  <div>${{ selectedNode.data.label }}.rows - Array of row objects</div>
                  <div>${{ selectedNode.data.label }}.total - Number of rows returned</div>
                  <div>${{ selectedNode.data.label }}.schema - Table schema fields</div>
                </template>
                <template v-else-if="selectedNode.data.bqOperation === 'insertRows'">
                  <div>${{ selectedNode.data.label }}.insertedCount - Number of rows inserted</div>
                  <div>${{ selectedNode.data.label }}.errors - Array of insertion errors (empty on success)</div>
                </template>
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'dataTable'">
            <div class="space-y-2">
              <Label>DataTable</Label>
              <div class="group relative">
                <Select
                  :model-value="selectedNode.data.dataTableId || ''"
                  :options="dataTableOptions"
                  :select-class="selectedNode.data.dataTableId ? 'pr-16' : undefined"
                  @update:model-value="handleDataTableIdChangedForSelect"
                />
                <button
                  v-if="selectedNode.data.dataTableId"
                  type="button"
                  class="absolute inset-y-0 right-9 z-10 flex items-center justify-center w-7 opacity-0 group-hover:opacity-100 transition-opacity duration-200 text-muted-foreground hover:text-foreground"
                  title="Open in new tab"
                  @click.stop="openDataTableInNewTab(selectedNode.data.dataTableId || '')"
                >
                  <ExternalLink :size="14" />
                </button>
              </div>
              <p
                v-if="!selectedNode.data.dataTableId"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                DataTable is required.
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                <a
                  href="/?tab=datatable"
                  class="text-primary hover:underline"
                  @click.prevent="$router.push('/?tab=datatable')"
                >Manage DataTables</a> in Dashboard
              </p>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.dataTableOperation || ''"
                :options="dataTableOperationOptions"
                @update:model-value="updateNodeData('dataTableOperation', $event)"
              />
              <p
                v-if="!selectedNode.data.dataTableOperation"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Operation is required
              </p>
            </div>

            <!-- Row ID — for getById, update, remove -->
            <div
              v-if="['getById', 'update', 'remove'].includes(selectedNode.data.dataTableOperation || '')"
              class="space-y-2"
            >
              <Label>Row ID <span class="text-destructive">*</span></Label>
              <ExpressionInput
                ref="dataTableRowIdExpressionInputRef"
                :model-value="selectedNode.data.dataTableRowId || ''"
                placeholder="row-uuid"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :navigation-enabled="dataTableExpressionFieldCount > 1"
                :navigation-index="0"
                :navigation-total="dataTableExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Row ID"
                @navigate="handleDataTableExpressionFieldNavigate"
                @register-field-index="onDataTableRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('dataTableRowId', $event)"
              />
            </div>

            <!-- Row Data — for insert, update, upsert -->
            <div
              v-if="['insert', 'update', 'upsert'].includes(selectedNode.data.dataTableOperation || '')"
              class="space-y-2"
            >
              <div class="flex items-center justify-between">
                <Label>Row Data <span class="text-destructive">*</span></Label>
                <div
                  v-if="dataTableColumns.length > 0"
                  class="flex rounded border text-xs overflow-hidden"
                >
                  <button
                    class="px-2 py-0.5 transition-colors"
                    :class="(selectedNode.data.dataTableInputMode || 'raw') === 'raw' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'"
                    @click="updateNodeData('dataTableInputMode', 'raw')"
                  >
                    Raw
                  </button>
                  <button
                    class="px-2 py-0.5 transition-colors"
                    :class="selectedNode.data.dataTableInputMode === 'selective' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'"
                    @click="switchDataTableRowDataToSelectiveMode"
                  >
                    Selective
                  </button>
                </div>
              </div>

              <!-- Raw mode -->
              <template v-if="(selectedNode.data.dataTableInputMode || 'raw') === 'raw'">
                <ExpressionInput
                  ref="dataTableDataExpressionInputRef"
                  :model-value="selectedNode.data.dataTableData || '{}'"
                  placeholder="{&#10;  &quot;column_name&quot;: &quot;value&quot;&#10;}"
                  :rows="4"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  class="font-mono text-xs"
                  :navigation-enabled="dataTableExpressionFieldCount > 1 && (selectedNode.data.dataTableInputMode || 'raw') === 'raw'"
                  :navigation-index="selectedNode.data.dataTableOperation === 'upsert' ? 0 : 1"
                  :navigation-total="dataTableExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Row data"
                  @navigate="handleDataTableExpressionFieldNavigate"
                  @register-field-index="onDataTableRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('dataTableData', $event)"
                />
                <div class="flex items-center justify-between">
                  <p class="text-xs text-muted-foreground">
                    JSON object mapping column names to values
                  </p>
                  <button
                    class="text-xs text-primary hover:underline"
                    @click="() => { try { const parsed = JSON.parse(selectedNode?.data.dataTableData || '{}'); updateNodeData('dataTableData', JSON.stringify(parsed, null, 2)); } catch {} }"
                  >
                    Format
                  </button>
                </div>
              </template>

              <!-- Selective mode -->
              <template v-else>
                <div class="space-y-2">
                  <div
                    v-for="(col, colIdx) in dataTableColumns"
                    :key="col.id"
                    class="space-y-1"
                  >
                    <label class="text-xs text-muted-foreground flex items-center gap-1">
                      {{ col.name }}
                      <span class="text-[10px] text-muted-foreground/60">({{ col.type }})</span>
                      <span
                        v-if="col.required"
                        class="text-destructive"
                      >*</span>
                    </label>
                    <ExpressionInput
                      :ref="(el) => setDataTableSelectiveExpressionInputRef(col.name, el)"
                      :model-value="dataTableSelectiveValues[col.name] || ''"
                      :placeholder="col.type === 'boolean' ? 'true / false' : col.type === 'number' ? '0' : col.type === 'json' ? '{}' : ''"
                      :rows="col.type === 'json' ? 2 : 1"
                      :nodes="workflowStore.nodes"
                      :node-results="workflowStore.nodeResults"
                      :edges="workflowStore.edges"
                      :current-node-id="selectedNode.id"
                      :navigation-enabled="dataTableExpressionFieldCount > 1"
                      :navigation-index="
                        selectedNode.data.dataTableOperation === 'update'
                          ? 1 + colIdx
                          : colIdx
                      "
                      :navigation-total="dataTableExpressionFieldCount"
                      :dialog-node-label="selectedNodeEvaluateDialogLabel"
                      :dialog-key-label="`Row data: ${col.name}`"
                      @navigate="handleDataTableExpressionFieldNavigate"
                      @register-field-index="onDataTableRegisterExpressionFieldIndex"
                      @update:model-value="handleDataTableSelectiveColumnInput(col.name, $event)"
                    />
                  </div>
                </div>
              </template>
            </div>

            <!-- Filter — for find, upsert -->
            <div
              v-if="['find', 'upsert'].includes(selectedNode.data.dataTableOperation || '')"
              class="space-y-2"
            >
              <Label>Filter (JSON)</Label>
              <ExpressionInput
                ref="dataTableFilterExpressionInputRef"
                :model-value="selectedNode.data.dataTableFilter || '{}'"
                placeholder="{&#10;  &quot;column_name&quot;: &quot;value&quot;&#10;}"
                :rows="3"
                class="font-mono text-xs"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :navigation-enabled="dataTableExpressionFieldCount > 1"
                :navigation-index="
                  selectedNode.data.dataTableOperation === 'find'
                    ? 0
                    : (selectedNode.data.dataTableInputMode || 'raw') === 'raw'
                      ? 1
                      : dataTableColumns.length
                "
                :navigation-total="dataTableExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Filter"
                @navigate="handleDataTableExpressionFieldNavigate"
                @register-field-index="onDataTableRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('dataTableFilter', $event)"
              />
              <div class="flex items-center justify-between">
                <p class="text-xs text-muted-foreground">
                  Exact-match filter: {"column": "value"}
                </p>
                <button
                  class="text-xs text-primary hover:underline"
                  @click="() => { try { const parsed = JSON.parse(selectedNode?.data.dataTableFilter || '{}'); updateNodeData('dataTableFilter', JSON.stringify(parsed, null, 2)); } catch {} }"
                >
                  Format
                </button>
              </div>
            </div>

            <!-- Sort — for find, getAll -->
            <div
              v-if="['find', 'getAll'].includes(selectedNode.data.dataTableOperation || '')"
              class="space-y-2"
            >
              <Label>Sort</Label>
              <ExpressionInput
                ref="dataTableSortExpressionInputRef"
                :model-value="selectedNode.data.dataTableSort || ''"
                placeholder="column_name or -column_name"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :navigation-enabled="dataTableExpressionFieldCount > 1"
                :navigation-index="selectedNode.data.dataTableOperation === 'find' ? 1 : 0"
                :navigation-total="dataTableExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Sort"
                @navigate="handleDataTableExpressionFieldNavigate"
                @register-field-index="onDataTableRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('dataTableSort', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Prefix with - for descending (e.g. -created_at)
              </p>
            </div>

            <!-- Limit — for find, getAll -->
            <div
              v-if="['find', 'getAll'].includes(selectedNode.data.dataTableOperation || '')"
              class="space-y-2"
            >
              <Label>Limit</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.dataTableLimit ?? ''"
                placeholder="No limit"
                min="0"
                @update:model-value="updateNodeData('dataTableLimit', $event ? parseInt(String($event)) : null)"
              />
              <p class="text-xs text-muted-foreground">
                Leave empty for no limit
              </p>
            </div>

            <!-- Output schema -->
            <div class="space-y-2 mt-3">
              <Label class="text-xs font-medium text-muted-foreground">Output Schema</Label>
              <div class="text-xs font-mono text-muted-foreground space-y-0.5 bg-muted/30 p-2 rounded">
                <template v-if="selectedNode.data.dataTableOperation === 'find'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.rows - Array of rows</div>
                  <div>${{ selectedNode.data.label }}.count - Number of rows</div>
                </template>
                <template v-else-if="selectedNode.data.dataTableOperation === 'getAll'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.rows - Array of rows</div>
                  <div>${{ selectedNode.data.label }}.count - Number of rows</div>
                </template>
                <template v-else-if="selectedNode.data.dataTableOperation === 'getById'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.row - Row object</div>
                  <div>${{ selectedNode.data.label }}.found - Boolean</div>
                </template>
                <template v-else-if="selectedNode.data.dataTableOperation === 'insert'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.row - Created row</div>
                  <div>${{ selectedNode.data.label }}.id - New row ID</div>
                </template>
                <template v-else-if="selectedNode.data.dataTableOperation === 'update'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.row - Updated row</div>
                  <div>${{ selectedNode.data.label }}.id - Row ID</div>
                </template>
                <template v-else-if="selectedNode.data.dataTableOperation === 'remove'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.id - Deleted row ID</div>
                </template>
                <template v-else-if="selectedNode.data.dataTableOperation === 'upsert'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.row - Row object</div>
                  <div>${{ selectedNode.data.label }}.operation - "insert" or "update"</div>
                </template>
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'drive'">
            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.driveOperation || ''"
                :options="driveOperationOptions"
                @update:model-value="updateNodeData('driveOperation', $event || undefined)"
              />
              <p class="text-xs text-muted-foreground">
                File operation to perform
              </p>
            </div>

            <div
              v-if="selectedNode.data.driveOperation === 'downloadUrl'"
              class="space-y-2"
            >
              <Label>Source URL</Label>
              <ExpressionInput
                :model-value="selectedNode.data.driveSourceUrl || ''"
                placeholder="https://example.com/file.pdf"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Source URL"
                @update:model-value="updateNodeData('driveSourceUrl', $event)"
              />
              <p class="text-xs text-muted-foreground">
                URL of the file to download and store in Drive
              </p>
            </div>

            <div
              v-if="selectedNode.data.driveOperation && selectedNode.data.driveOperation !== 'downloadUrl'"
              class="space-y-2"
            >
              <Label>File ID</Label>
              <template v-if="selectedNode.data.driveOperation === 'get'">
                <Select
                  :model-value="selectedNode.data.driveFileId || ''"
                  :options="driveFileOptions"
                  @update:model-value="updateNodeData('driveFileId', $event || undefined)"
                />
                <ExpressionInput
                  ref="driveFileIdExpressionInputRef"
                  :model-value="selectedNode.data.driveFileId || ''"
                  placeholder="$skill._generated_files[0].id"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="File ID"
                  @update:model-value="updateNodeData('driveFileId', $event)"
                />
              </template>
              <template v-else>
                <ExpressionInput
                  ref="driveFileIdExpressionInputRef"
                  :model-value="selectedNode.data.driveFileId || ''"
                  placeholder="$skill._generated_files[0].id"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  :dialog-key-label="
                    selectedNode.data.driveOperation === 'setPassword'
                      ? 'Drive set password · File ID'
                      : 'File ID'
                  "
                  :navigation-enabled="selectedNode.data.driveOperation === 'setPassword'"
                  :navigation-index="0"
                  :navigation-total="driveExpressionFieldCount"
                  @navigate="handleDriveExpressionFieldNavigate"
                  @register-field-index="onDriveRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('driveFileId', $event)"
                />
              </template>
              <p class="text-xs text-muted-foreground">
                ID of the file to manage
              </p>
            </div>

            <div
              v-if="selectedNode.data.driveOperation === 'get'"
              class="space-y-2"
            >
              <Label>Options</Label>
              <div class="flex items-center gap-2">
                <input
                  id="drive-include-binary"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.driveIncludeBinary"
                  @change="updateNodeData('driveIncludeBinary', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="drive-include-binary"
                  class="font-normal text-sm"
                >
                  Include binary content
                </Label>
              </div>
              <p class="text-xs text-muted-foreground">
                When enabled, the file content is returned as base64 in <code>file_base64</code>
              </p>
            </div>

            <div
              v-if="selectedNode.data.driveOperation === 'setPassword'"
              class="space-y-2"
            >
              <Label>Password</Label>
              <ExpressionInput
                ref="drivePasswordExpressionInputRef"
                :model-value="selectedNode.data.drivePassword || ''"
                placeholder="Enter password or expression"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Drive set password · Password"
                navigation-enabled
                :navigation-index="1"
                :navigation-total="driveExpressionFieldCount"
                @navigate="handleDriveExpressionFieldNavigate"
                @register-field-index="onDriveRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('drivePassword', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Password to protect the file download link
              </p>
            </div>

            <div
              v-if="selectedNode.data.driveOperation === 'setTtl'"
              class="space-y-2"
            >
              <Label>TTL (Hours)</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.driveTtlHours ?? ''"
                min="1"
                placeholder="e.g. 24"
                @update:model-value="updateNodeData('driveTtlHours', $event !== '' ? Number($event) : undefined)"
              />
              <p class="text-xs text-muted-foreground">
                Hours until the file download link expires
              </p>
            </div>

            <div
              v-if="selectedNode.data.driveOperation === 'setMaxDownloads'"
              class="space-y-2"
            >
              <Label>Max Downloads</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.driveMaxDownloads ?? ''"
                min="1"
                placeholder="e.g. 5"
                @update:model-value="updateNodeData('driveMaxDownloads', $event !== '' ? Number($event) : undefined)"
              />
              <p class="text-xs text-muted-foreground">
                Maximum number of times the file can be downloaded
              </p>
            </div>

            <div class="rounded-lg bg-muted/50 p-3 space-y-1">
              <p class="text-xs font-medium text-foreground">
                Output
              </p>
              <div class="text-xs text-muted-foreground space-y-0.5 font-mono">
                <template v-if="selectedNode.data.driveOperation === 'get'">
                  <div>${{ selectedNode.data.label }}.id - file UUID</div>
                  <div>${{ selectedNode.data.label }}.filename - file name</div>
                  <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
                  <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
                  <div>${{ selectedNode.data.label }}.download_url - public download URL</div>
                  <div>${{ selectedNode.data.label }}.file_base64 - base64 content (if enabled)</div>
                </template>
                <template v-else-if="selectedNode.data.driveOperation === 'downloadUrl'">
                  <div>${{ selectedNode.data.label }}.id - new file UUID</div>
                  <div>${{ selectedNode.data.label }}.filename - file name</div>
                  <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
                  <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
                  <div>${{ selectedNode.data.label }}.download_url - Drive download URL</div>
                </template>
                <template v-else-if="selectedNode.data.driveOperation === 'delete'">
                  <div>${{ selectedNode.data.label }}.status - "deleted"</div>
                  <div>${{ selectedNode.data.label }}.file_id - deleted file ID</div>
                </template>
                <template v-else-if="selectedNode.data.driveOperation === 'setPassword' || selectedNode.data.driveOperation === 'setTtl' || selectedNode.data.driveOperation === 'setMaxDownloads'">
                  <div>${{ selectedNode.data.label }}.status - "updated"</div>
                  <div>${{ selectedNode.data.label }}.file_id - file ID</div>
                  <div>${{ selectedNode.data.label }}.download_url - new access URL</div>
                </template>
                <template v-else>
                  <div>Select an operation to see output fields</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'throwError'">
            <div class="space-y-2">
              <Label>HTTP Status Code</Label>
              <Select
                :model-value="selectedNode.data.httpStatusCode?.toString() || ''"
                :options="httpStatusCodeOptions"
                @update:model-value="updateNodeData('httpStatusCode', $event ? parseInt($event) : undefined)"
              />
              <p class="text-xs text-muted-foreground">
                HTTP status code to return when this error is thrown
              </p>
            </div>

            <div class="space-y-2">
              <Label>Error Message</Label>
              <ExpressionInput
                ref="throwErrorMessageInputRef"
                :model-value="selectedNode.data.errorMessage || ''"
                :placeholder="`${exampleRef} or error message`"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Error message"
                @update:model-value="updateNodeData('errorMessage', $event)"
              />
              <p
                v-if="getExpressionWarning(selectedNode.data.errorMessage || '')"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                {{ getExpressionWarning(selectedNode.data.errorMessage || '') }}
              </p>
              <p
                v-if="!selectedNode.data.errorMessage && !selectedNode.data.httpStatusCode"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Error message or HTTP status code is required
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Message to include in the error response
              </p>
            </div>

            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Behavior</Label>
              <p class="text-xs text-muted-foreground">
                When this node executes, workflow execution will stop and return an error response with the specified
                HTTP status code and message.
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'rabbitmq'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="rabbitmqCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <div v-if="!selectedNode.data.credentialId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Credential is required.
                </p>
                <p class="text-xs text-muted-foreground mt-1">
                  <a
                    href="/?tab=credentials"
                    class="text-primary hover:underline"
                    @click.prevent="$router.push('/?tab=credentials')"
                  >Add credentials</a> in Dashboard
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.rabbitmqOperation || ''"
                :options="rabbitmqOperationOptions"
                @update:model-value="updateNodeData('rabbitmqOperation', $event)"
              />
              <p
                v-if="!selectedNode.data.rabbitmqOperation"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Operation is required
              </p>
            </div>

            <template v-if="selectedNode.data.rabbitmqOperation === 'send'">
              <div class="space-y-2">
                <Label>Exchange Name</Label>
                <ExpressionInput
                  ref="rabbitmqExchangeInputRef"
                  :model-value="selectedNode.data.rabbitmqExchange || ''"
                  placeholder="my-exchange (optional)"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
                  :navigation-index="0"
                  :navigation-total="rabbitmqSendExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Exchange name"
                  @navigate="handleRabbitmqSendExpressionFieldNavigate"
                  @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('rabbitmqExchange', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Exchange name (leave empty for default exchange)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Routing Key</Label>
                <ExpressionInput
                  ref="rabbitmqRoutingKeyInputRef"
                  :model-value="selectedNode.data.rabbitmqRoutingKey || ''"
                  placeholder="my-routing-key"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="rabbitmqSendExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Routing key"
                  @navigate="handleRabbitmqSendExpressionFieldNavigate"
                  @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('rabbitmqRoutingKey', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Routing key for message delivery
                </p>
              </div>

              <div class="space-y-2">
                <Label>Queue Name</Label>
                <ExpressionInput
                  ref="rabbitmqQueueNameInputRef"
                  :model-value="selectedNode.data.rabbitmqQueueName || ''"
                  placeholder="my-queue (used as routing key if empty)"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="rabbitmqSendExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Queue name"
                  @navigate="handleRabbitmqSendExpressionFieldNavigate"
                  @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('rabbitmqQueueName', $event)"
                />
                <p
                  v-if="!selectedNode.data.rabbitmqRoutingKey && !selectedNode.data.rabbitmqQueueName"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Routing key or queue name is required
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Queue name (optional, used as routing key if routing key is empty)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Message Body</Label>
                <ExpressionInput
                  ref="rabbitmqMessageBodyInputRef"
                  :model-value="selectedNode.data.rabbitmqMessageBody || ''"
                  placeholder="$input or {&quot;key&quot;: &quot;value&quot;}"
                  :rows="4"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
                  :navigation-index="3"
                  :navigation-total="rabbitmqSendExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Message body"
                  @navigate="handleRabbitmqSendExpressionFieldNavigate"
                  @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('rabbitmqMessageBody', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  JSON message body to send (supports expressions)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Delay (ms)</Label>
                <Input
                  type="number"
                  :model-value="selectedNode.data.rabbitmqDelayMs || ''"
                  placeholder="0 (optional)"
                  min="0"
                  @update:model-value="updateNodeData('rabbitmqDelayMs', $event ? parseInt($event as string) : undefined)"
                />
                <p class="text-xs text-muted-foreground">
                  x-delay header in milliseconds for delayed message exchange plugin
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-muted-foreground">Output</Label>
                <div class="text-xs font-mono space-y-1 text-muted-foreground">
                  <div>${{ selectedNode.data.label }}.status - "published" on success</div>
                  <div>${{ selectedNode.data.label }}.message_id - Unique message ID</div>
                  <div>${{ selectedNode.data.label }}.exchange - Exchange name used</div>
                  <div>${{ selectedNode.data.label }}.routing_key - Routing key used</div>
                  <div>${{ selectedNode.data.label }}.delay_ms - Delay value (if set)</div>
                </div>
              </div>
            </template>

            <template v-if="selectedNode.data.rabbitmqOperation === 'receive'">
              <div class="space-y-2">
                <Label>Queue Name <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="rabbitmqQueueNameInputRef"
                  :model-value="selectedNode.data.rabbitmqQueueName || ''"
                  placeholder="my-queue"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Queue name"
                  @update:model-value="updateNodeData('rabbitmqQueueName', $event)"
                />
                <p
                  v-if="!selectedNode.data.rabbitmqQueueName || selectedNode.data.rabbitmqQueueName.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Queue name is required
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Queue to consume messages from
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-muted-foreground">Trigger Behavior</Label>
                <p class="text-xs text-muted-foreground">
                  This node acts as a trigger. When a message arrives in the specified queue, the workflow will be
                  executed automatically.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-muted-foreground">Output</Label>
                <div class="text-xs font-mono space-y-1 text-muted-foreground">
                  <div>${{ selectedNode.data.label }}.body - Message body (parsed JSON)</div>
                  <div>${{ selectedNode.data.label }}.headers - Message headers</div>
                  <div>${{ selectedNode.data.label }}.message_id - Message ID</div>
                  <div>${{ selectedNode.data.label }}.routing_key - Routing key</div>
                  <div>${{ selectedNode.data.label }}.exchange - Exchange name</div>
                  <div>${{ selectedNode.data.label }}.timestamp - Message timestamp</div>
                </div>
              </div>
            </template>
          </template>

          <template v-if="selectedNode.type === 'crawler'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="crawlerCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <div v-if="!selectedNode.data.credentialId">
                <p class="text-xs text-amber-500 flex items-center gap-1">
                  <AlertTriangle class="h-3 w-3" />
                  Select a FlareSolverr credential
                </p>
              </div>
            </div>

            <div class="space-y-2">
              <Label>URL to Crawl <span class="text-destructive">*</span></Label>
              <ExpressionInput
                ref="crawlerUrlInputRef"
                :model-value="selectedNode.data.crawlerUrl || ''"
                placeholder="https://example.com or $input.text"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="URL to crawl"
                @update:model-value="updateNodeData('crawlerUrl', $event)"
              />
              <p class="text-xs text-muted-foreground">
                URL to scrape (supports expressions)
              </p>
            </div>

            <div class="space-y-2">
              <Label>Wait (seconds)</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.crawlerWaitSeconds || 0"
                placeholder="0"
                min="0"
                max="60"
                @update:model-value="updateNodeData('crawlerWaitSeconds', $event ? parseInt($event as string) : 0)"
              />
              <p class="text-xs text-muted-foreground">
                Wait time before extracting content (for dynamic pages)
              </p>
            </div>

            <div class="space-y-2">
              <Label>Max Timeout (ms)</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.crawlerMaxTimeout || 60000"
                placeholder="60000"
                min="1000"
                max="300000"
                @update:model-value="updateNodeData('crawlerMaxTimeout', $event ? parseInt($event as string) : 60000)"
              />
              <p class="text-xs text-muted-foreground">
                Maximum timeout for the request in milliseconds
              </p>
            </div>

            <div class="space-y-2">
              <Label>Mode</Label>
              <Select
                :model-value="selectedNode.data.crawlerMode || 'basic'"
                :options="crawlerModeOptions"
                @update:model-value="updateNodeData('crawlerMode', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Basic returns raw HTML, Extract parses with CSS selectors
              </p>
            </div>

            <template v-if="selectedNode.data.crawlerMode === 'extract'">
              <div class="space-y-2 pt-2 border-t">
                <div class="flex items-center justify-between">
                  <Label>CSS Selectors</Label>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-7 text-xs"
                    @click="addCrawlerSelector"
                  >
                    <Plus class="h-3 w-3 mr-1" />
                    Add Selector
                  </Button>
                </div>

                <div
                  v-for="(selector, index) in (selectedNode.data.crawlerSelectors || [])"
                  :key="index"
                  class="space-y-2 p-3 border rounded-md bg-muted/30"
                >
                  <div class="flex items-center justify-between">
                    <span class="text-xs font-medium">Selector {{ index + 1 }}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="h-6 w-6 p-0 text-destructive hover:text-destructive"
                      @click="removeCrawlerSelector(index)"
                    >
                      <Trash2 class="h-3 w-3" />
                    </Button>
                  </div>

                  <div class="space-y-1">
                    <Label class="text-xs">Name</Label>
                    <Input
                      :model-value="selector.name"
                      placeholder="items"
                      @update:model-value="updateCrawlerSelector(index, 'name', $event as string)"
                    />
                  </div>

                  <div class="space-y-1">
                    <div class="flex items-center justify-between gap-2">
                      <Label class="text-xs">CSS Selector</Label>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-6 gap-1 text-xs"
                        @click="openSelectorPickerCrawler(index)"
                      >
                        <MousePointerClick class="h-3 w-3" />
                        Pick from page
                      </Button>
                    </div>
                    <Input
                      :model-value="selector.selector"
                      placeholder="ul#timeline > li"
                      @update:model-value="updateCrawlerSelector(index, 'selector', $event as string)"
                    />
                  </div>

                  <div class="space-y-1">
                    <Label class="text-xs">Attributes (comma-separated)</Label>
                    <Input
                      :model-value="(selector.attributes || []).join(', ')"
                      placeholder="data-post-id, href, class"
                      @update:model-value="updateCrawlerSelectorAttributes(index, $event as string)"
                    />
                    <p class="text-xs text-muted-foreground">
                      HTML attributes to extract from each element
                    </p>
                  </div>
                </div>

                <p
                  v-if="!selectedNode.data.crawlerSelectors?.length"
                  class="text-xs text-muted-foreground"
                >
                  Add CSS selectors to extract specific elements from the page
                </p>
              </div>
            </template>

            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Output</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <div>${{ selectedNode.data.label }}.html - Raw HTML content</div>
                <div>${{ selectedNode.data.label }}.url - Crawled URL</div>
                <div>${{ selectedNode.data.label }}.status - Response status</div>
                <template v-if="selectedNode.data.crawlerMode === 'extract'">
                  <div>${{ selectedNode.data.label }}.extracted - Extracted data by selector name</div>
                </template>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'playwright'">
            <div class="space-y-4">
              <div class="space-y-2">
                <Label class="text-muted-foreground">Auth & Session</Label>
                <div class="flex items-center gap-2">
                  <input
                    id="playwright-auth-enabled"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="selectedNode.data.playwrightAuthEnabled === true"
                    @change="updateNodeData('playwrightAuthEnabled', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="playwright-auth-enabled"
                    class="text-sm font-normal"
                  >
                    Restore session from cookies/storageState
                  </Label>
                </div>
                <p class="text-xs text-muted-foreground">
                  Load session data from an expression like <code class="font-mono">$global.authState</code>, verify
                  login with a selector, and run fallback login steps only when needed.
                </p>

                <div
                  v-if="selectedNode.data.playwrightAuthEnabled"
                  class="space-y-3 rounded-md border border-border/60 bg-muted/20 p-3"
                >
                  <div class="space-y-1">
                    <Label class="text-xs">Auth state expression</Label>
                    <ExpressionInput
                      :ref="(el) => bindPlaywrightExprSlotRef('authState', el)"
                      :model-value="selectedNode.data.playwrightAuthStateExpression || ''"
                      placeholder="$global.authState or [{&quot;name&quot;:&quot;session&quot;,...}]"
                      :rows="2"
                      :nodes="workflowStore.nodes"
                      :node-results="workflowStore.nodeResults"
                      :edges="workflowStore.edges"
                      :current-node-id="selectedNode.id"
                      :dialog-node-label="selectedNodeEvaluateDialogLabel"
                      dialog-key-label="Playwright auth · state expression"
                      :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                      :navigation-index="playwrightExprNavGlobalIndexForAuthState()"
                      :navigation-total="playwrightExpressionNavPlan.total"
                      @navigate="handlePlaywrightExpressionFieldNavigate"
                      @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                      @update:model-value="updateNodeData('playwrightAuthStateExpression', $event)"
                    />
                    <p class="text-xs text-muted-foreground">
                      Accepts a Playwright <code class="font-mono">storageState</code> object or a raw
                      <code class="font-mono">cookies[]</code> array, including JSON strings of either.
                    </p>
                  </div>

                  <div class="space-y-1">
                    <Label class="text-xs">Authenticated selector</Label>
                    <ExpressionInput
                      :ref="(el) => bindPlaywrightExprSlotRef('authSelector', el)"
                      :model-value="selectedNode.data.playwrightAuthCheckSelector || ''"
                      placeholder="nav [data-user-menu] or text=Dashboard"
                      :rows="1"
                      :nodes="workflowStore.nodes"
                      :node-results="workflowStore.nodeResults"
                      :edges="workflowStore.edges"
                      :current-node-id="selectedNode.id"
                      :dialog-node-label="selectedNodeEvaluateDialogLabel"
                      dialog-key-label="Playwright auth · check selector"
                      :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                      :navigation-index="playwrightExprNavGlobalIndexForAuthSelector()"
                      :navigation-total="playwrightExpressionNavPlan.total"
                      @navigate="handlePlaywrightExpressionFieldNavigate"
                      @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                      @update:model-value="updateNodeData('playwrightAuthCheckSelector', $event)"
                    />
                    <p class="text-xs text-muted-foreground">
                      The selector must be visible after the first navigate step. If not, fallback login steps run.
                    </p>
                  </div>

                  <div class="space-y-1">
                    <Label class="text-xs">Auth check timeout (ms)</Label>
                    <Input
                      type="number"
                      :model-value="selectedNode.data.playwrightAuthCheckTimeout || 5000"
                      placeholder="5000"
                      min="1"
                      @update:model-value="updateNodeData('playwrightAuthCheckTimeout', $event ? parseInt($event as string) : 5000)"
                    />
                  </div>
                </div>
              </div>

              <div
                v-for="section in playwrightStepSections"
                :key="section.key"
                class="space-y-2"
              >
                <div class="flex items-center justify-between gap-3">
                  <div class="space-y-0.5">
                    <Label>{{ section.label }}</Label>
                    <p
                      v-if="section.helpText"
                      class="text-xs text-muted-foreground"
                    >
                      {{ section.helpText }}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-7 text-xs"
                    @click="addPlaywrightStep(section.key)"
                  >
                    <Plus class="h-3 w-3 mr-1" />
                    Add Step
                  </Button>
                </div>

                <div
                  v-for="(step, index) in getPlaywrightSteps(section.key)"
                  :key="`${section.key}-${index}`"
                  :data-playwright-step="section.key"
                  class="space-y-2 p-3 border rounded-md bg-muted/30"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-xs font-medium">Step {{ index + 1 }}</span>
                    <div class="flex items-center gap-1">
                      <Button
                        variant="outline"
                        size="sm"
                        class="h-7 w-7 p-0 shrink-0 text-base font-semibold leading-none text-muted-foreground hover:text-foreground"
                        aria-label="Move step up"
                        :disabled="index === 0"
                        @click="movePlaywrightStepUp(section.key, index)"
                      >
                        ↑
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        class="h-7 w-7 p-0 shrink-0 text-base font-semibold leading-none text-muted-foreground hover:text-foreground"
                        aria-label="Move step down"
                        :disabled="index >= getPlaywrightSteps(section.key).length - 1"
                        @click="movePlaywrightStepDown(section.key, index)"
                      >
                        ↓
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-7 gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        aria-label="Remove step"
                        @click="removePlaywrightStep(section.key, index)"
                      >
                        <Trash2 class="h-3.5 w-3.5" />
                        Remove
                      </Button>
                    </div>
                  </div>

                  <div class="space-y-1">
                    <Label class="text-xs">Action</Label>
                    <Select
                      :model-value="step.action"
                      :options="playwrightStepActionOptions"
                      @update:model-value="updatePlaywrightStep(section.key, index, 'action', $event as PlaywrightStepAction)"
                    />
                  </div>

                  <template v-if="step.action === 'navigate'">
                    <div class="space-y-1">
                      <Label class="text-xs">URL</Label>
                      <ExpressionInput
                        :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-url`, el)"
                        :model-value="step.url || ''"
                        placeholder="https://example.com or $nodeLabel.body.text"
                        :rows="1"
                        :nodes="workflowStore.nodes"
                        :node-results="workflowStore.nodeResults"
                        :edges="workflowStore.edges"
                        :current-node-id="selectedNode.id"
                        :dialog-node-label="selectedNodeEvaluateDialogLabel"
                        :dialog-key-label="
                          playwrightStepDialogKey(
                            section.label,
                            index,
                            playwrightStepActionLabel(step.action),
                            'URL',
                          )
                        "
                        :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                        :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'url')"
                        :navigation-total="playwrightExpressionNavPlan.total"
                        @navigate="handlePlaywrightExpressionFieldNavigate"
                        @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                        @update:model-value="updatePlaywrightStep(section.key, index, 'url', $event)"
                      />
                      <p class="text-xs text-muted-foreground">
                        For textInput: <code class="font-mono">$nodeLabel.body.fieldKey</code> (e.g. $start.body.text)
                      </p>
                    </div>
                  </template>

                  <template
                    v-if="['click', 'type', 'fill', 'getText', 'getAttribute', 'getHTML', 'hover', 'selectOption'].includes(step.action)"
                  >
                    <div class="space-y-1">
                      <div class="flex items-center justify-between gap-2">
                        <Label class="text-xs">Selector</Label>
                        <Button
                          variant="ghost"
                          size="sm"
                          class="h-6 gap-1 text-xs"
                          @click="openSelectorPickerPlaywright(index, section.key)"
                        >
                          <MousePointerClick class="h-3 w-3" />
                          Pick from page
                        </Button>
                      </div>
                      <ExpressionInput
                        :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-selector`, el)"
                        :model-value="step.selector || ''"
                        placeholder="button#submit or #search"
                        :rows="1"
                        :nodes="workflowStore.nodes"
                        :node-results="workflowStore.nodeResults"
                        :edges="workflowStore.edges"
                        :current-node-id="selectedNode.id"
                        :dialog-node-label="selectedNodeEvaluateDialogLabel"
                        :dialog-key-label="
                          playwrightStepDialogKey(
                            section.label,
                            index,
                            playwrightStepActionLabel(step.action),
                            'Selector',
                          )
                        "
                        :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                        :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'selector')"
                        :navigation-total="playwrightExpressionNavPlan.total"
                        @navigate="handlePlaywrightExpressionFieldNavigate"
                        @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                        @update:model-value="updatePlaywrightStep(section.key, index, 'selector', $event)"
                      />
                    </div>
                  </template>

                  <template v-if="['type', 'fill'].includes(step.action)">
                    <div class="space-y-1">
                      <Label class="text-xs">{{ step.action === 'type' ? 'Text' : 'Value' }}</Label>
                      <ExpressionInput
                        :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-typeFill`, el)"
                        :model-value="step.action === 'type' ? (step.text || '') : (step.value || '')"
                        :placeholder="step.action === 'type' ? 'Text to type' : 'Value to fill'"
                        :rows="1"
                        :nodes="workflowStore.nodes"
                        :node-results="workflowStore.nodeResults"
                        :edges="workflowStore.edges"
                        :current-node-id="selectedNode.id"
                        :dialog-node-label="selectedNodeEvaluateDialogLabel"
                        :dialog-key-label="
                          playwrightStepDialogKey(
                            section.label,
                            index,
                            playwrightStepActionLabel(step.action),
                            step.action === 'type' ? 'Text' : 'Value',
                          )
                        "
                        :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                        :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'typeFill')"
                        :navigation-total="playwrightExpressionNavPlan.total"
                        @navigate="handlePlaywrightExpressionFieldNavigate"
                        @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                        @update:model-value="updatePlaywrightStep(section.key, index, step.action === 'type' ? 'text' : 'value', $event)"
                      />
                    </div>
                  </template>

                  <template v-if="step.action === 'getAttribute'">
                    <div class="space-y-1">
                      <Label class="text-xs">Attribute</Label>
                      <Input
                        :model-value="step.attribute || ''"
                        placeholder="href, data-id, etc."
                        @update:model-value="updatePlaywrightStep(section.key, index, 'attribute', $event as string)"
                      />
                    </div>
                  </template>

                  <template
                    v-if="['getText', 'getAttribute', 'getHTML', 'getVisibleTextOnPage', 'screenshot'].includes(step.action)"
                  >
                    <div class="space-y-1">
                      <Label class="text-xs">Output Key</Label>
                      <Input
                        :model-value="step.outputKey || ''"
                        placeholder="e.g. pageTitle, screenshot"
                        @update:model-value="updatePlaywrightStep(section.key, index, 'outputKey', $event as string)"
                      />
                      <p class="text-xs text-muted-foreground">
                        Store result in ${{ selectedNode.data.label }}.results.key
                      </p>
                    </div>
                  </template>

                  <template v-if="step.action === 'wait'">
                    <div class="space-y-1">
                      <Label class="text-xs">Timeout (ms)</Label>
                      <Input
                        type="number"
                        :model-value="step.timeout || 4000"
                        placeholder="4000"
                        min="0"
                        @update:model-value="updatePlaywrightStep(section.key, index, 'timeout', $event ? parseInt($event as string) : 4000)"
                      />
                    </div>
                  </template>

                  <template v-if="['scrollDown', 'scrollUp'].includes(step.action)">
                    <div class="space-y-1">
                      <Label class="text-xs">Amount (pixels)</Label>
                      <Input
                        type="number"
                        :model-value="step.amount ?? 300"
                        placeholder="300"
                        min="1"
                        @update:model-value="updatePlaywrightStep(section.key, index, 'amount', $event ? parseInt($event as string) : 300)"
                      />
                      <p class="text-xs text-muted-foreground">
                        Pixels to scroll (default 300)
                      </p>
                    </div>
                  </template>

                  <template v-if="step.action === 'aiStep'">
                    <div class="space-y-2 p-2 rounded-md bg-muted/50 border border-border/50">
                      <p class="text-xs text-muted-foreground">
                        AI analyzes page HTML (+ optional screenshot) and returns Playwright actions. Useful for dynamic
                        sites.
                      </p>
                      <div class="space-y-1">
                        <Label class="text-xs">Instructions</Label>
                        <ExpressionInput
                          :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-instructions`, el)"
                          :model-value="step.instructions || ''"
                          placeholder="e.g. Click the login button, fill email field with test@example.com"
                          :rows="3"
                          :nodes="workflowStore.nodes"
                          :node-results="workflowStore.nodeResults"
                          :edges="workflowStore.edges"
                          :current-node-id="selectedNode.id"
                          :dialog-node-label="selectedNodeEvaluateDialogLabel"
                          :dialog-key-label="
                            playwrightStepDialogKey(
                              section.label,
                              index,
                              playwrightStepActionLabel(step.action),
                              'Instructions',
                            )
                          "
                          :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                          :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'instructions')"
                          :navigation-total="playwrightExpressionNavPlan.total"
                          @navigate="handlePlaywrightExpressionFieldNavigate"
                          @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                          @update:model-value="updatePlaywrightStep(section.key, index, 'instructions', $event)"
                        />
                      </div>
                      <div class="space-y-1">
                        <Label class="text-xs">Credential</Label>
                        <Select
                          :model-value="step.credentialId || ''"
                          :options="credentialOptions"
                          @update:model-value="(v) => { updatePlaywrightStep(section.key, index, 'credentialId', v); loadPlaywrightAiStepModels(v as string); }"
                        />
                      </div>
                      <div class="space-y-1">
                        <Label class="text-xs">Model</Label>
                        <Select
                          :model-value="step.model || ''"
                          :options="playwrightAiStepModelOptions(step.credentialId, step.model)"
                          :disabled="!step.credentialId"
                          @update:model-value="updatePlaywrightStep(section.key, index, 'model', $event)"
                        />
                      </div>
                      <div class="flex flex-col gap-2 pt-1">
                        <div class="flex items-center gap-2">
                          <input
                            :id="`ai-step-log-${section.key}-${index}`"
                            type="checkbox"
                            class="h-4 w-4 rounded border-input bg-background"
                            :checked="step.logStepsToConsole === true"
                            @change="updatePlaywrightStep(section.key, index, 'logStepsToConsole', ($event.target as HTMLInputElement).checked)"
                          >
                          <Label
                            :for="`ai-step-log-${section.key}-${index}`"
                            class="text-xs font-normal"
                          >
                            Log steps to console
                          </Label>
                        </div>
                        <div class="flex items-center gap-2">
                          <input
                            :id="`ai-step-save-${section.key}-${index}`"
                            type="checkbox"
                            class="h-4 w-4 rounded border-input bg-background"
                            :checked="step.saveStepsForFuture === true"
                            @change="updatePlaywrightStep(section.key, index, 'saveStepsForFuture', ($event.target as HTMLInputElement).checked)"
                          >
                          <Label
                            :for="`ai-step-save-${section.key}-${index}`"
                            class="text-xs font-normal"
                          >
                            Save steps for future usages
                          </Label>
                        </div>
                        <div class="flex items-center gap-2">
                          <input
                            :id="`ai-step-screenshot-${section.key}-${index}`"
                            type="checkbox"
                            class="h-4 w-4 rounded border-input bg-background"
                            :checked="step.sendScreenshot === true"
                            @change="updatePlaywrightStep(section.key, index, 'sendScreenshot', ($event.target as HTMLInputElement).checked)"
                          >
                          <Label
                            :for="`ai-step-screenshot-${section.key}-${index}`"
                            class="text-xs font-normal"
                          >
                            Send screenshot to LLM
                          </Label>
                        </div>
                        <div class="flex flex-col gap-0.5">
                          <div class="flex items-center gap-2">
                            <input
                              :id="`ai-step-auto-heal-${section.key}-${index}`"
                              type="checkbox"
                              class="h-4 w-4 rounded border-input bg-background"
                              :checked="step.autoHealMode === true"
                              @change="updatePlaywrightStep(section.key, index, 'autoHealMode', ($event.target as HTMLInputElement).checked)"
                            >
                            <Label
                              :for="`ai-step-auto-heal-${section.key}-${index}`"
                              class="text-xs font-normal"
                            >
                              Auto heal mode
                            </Label>
                          </div>
                          <p class="text-xs text-muted-foreground pl-6">
                            If selector fails 2x, ask LLM for text/role-based alternative and retry
                          </p>
                        </div>
                      </div>
                      <div class="space-y-1 pt-1">
                        <Label class="text-xs">Timeout (ms) <span
                          class="text-muted-foreground font-normal"
                        >(optional)</span></Label>
                        <Input
                          type="number"
                          :model-value="step.aiStepTimeout ?? 30000"
                          placeholder="30000"
                          min="5000"
                          max="300000"
                          @update:model-value="updatePlaywrightStep(section.key, index, 'aiStepTimeout', parseInt(String($event), 10) || 30000)"
                        />
                        <p class="text-xs text-muted-foreground">
                          Timeout for LLM API call (default 30000 ms = 30 s)
                        </p>
                      </div>
                      <div
                        v-if="step.savedSteps?.length"
                        class="mt-2 pt-2 border-t border-border/50 space-y-1"
                      >
                        <Label class="text-xs text-muted-foreground">
                          Saved steps ({{ step.savedSteps.length }}) — will be reused without LLM call
                        </Label>
                        <div class="space-y-1">
                          <div
                            v-for="(s, i) in step.savedSteps"
                            :key="`${section.key}-${index}-${i}`"
                            class="rounded border border-border/50 bg-background/50 overflow-hidden"
                          >
                            <div class="flex items-center gap-1 px-2 py-1.5 min-h-0">
                              <button
                                type="button"
                                class="flex-1 min-w-0 flex items-center gap-2 text-left text-xs font-mono text-muted-foreground hover:bg-muted/50 transition-colors rounded py-0.5 -mx-1 px-1"
                                @click="expandedSavedStepKey = expandedSavedStepKey === savedStepKey(section.key, index, i) ? null : savedStepKey(section.key, index, i)"
                              >
                                <span class="truncate">{{ formatSavedStep(s) }}</span>
                                <ChevronDown
                                  v-if="expandedSavedStepKey === savedStepKey(section.key, index, i)"
                                  class="h-3 w-3 shrink-0"
                                />
                                <ChevronRight
                                  v-else
                                  class="h-3 w-3 shrink-0"
                                />
                              </button>
                              <button
                                type="button"
                                class="shrink-0 flex items-center justify-center w-8 h-8 rounded-md text-red-500 hover:bg-red-500/10 transition-colors"
                                aria-label="Remove saved step"
                                @click="removePlaywrightStepSavedStep(section.key, index, i)"
                              >
                                <Trash2 class="h-4 w-4" />
                              </button>
                            </div>
                            <div
                              v-if="expandedSavedStepKey === savedStepKey(section.key, index, i)"
                              class="px-2 pb-2 pt-1 space-y-1.5 border-t border-border/50"
                            >
                              <div class="space-y-1">
                                <Label class="text-xs">Action</Label>
                                <div
                                  class="font-mono text-xs h-7 px-2 py-1.5 rounded-md bg-muted/50 text-muted-foreground border border-transparent"
                                >
                                  {{ s.action }}
                                </div>
                              </div>
                              <div
                                v-if="['click', 'fill', 'type', 'hover', 'selectOption'].includes(s.action)"
                                class="space-y-1"
                              >
                                <Label class="text-xs">Selector</Label>
                                <Input
                                  :model-value="s.selector ?? ''"
                                  placeholder="e.g. button[type=submit]"
                                  class="font-mono text-xs h-7"
                                  @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'selector', $event || undefined)"
                                />
                              </div>
                              <div
                                v-if="s.action === 'type'"
                                class="space-y-1"
                              >
                                <Label class="text-xs">Text</Label>
                                <Input
                                  :model-value="s.text ?? ''"
                                  placeholder="Text to type"
                                  class="font-mono text-xs h-7"
                                  @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'text', $event)"
                                />
                              </div>
                              <div
                                v-if="['fill', 'selectOption'].includes(s.action)"
                                class="space-y-1"
                              >
                                <Label class="text-xs">Value</Label>
                                <Input
                                  :model-value="s.value ?? ''"
                                  placeholder="Value"
                                  class="font-mono text-xs h-7"
                                  @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'value', $event)"
                                />
                              </div>
                              <div
                                v-if="s.action === 'wait'"
                                class="space-y-1"
                              >
                                <Label class="text-xs">Timeout (ms)</Label>
                                <Input
                                  type="number"
                                  :model-value="s.timeout ?? 2000"
                                  placeholder="2000"
                                  min="0"
                                  class="font-mono text-xs h-7"
                                  @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'timeout', $event ? parseInt(String($event), 10) : undefined)"
                                />
                              </div>
                              <div
                                v-if="['scrollDown', 'scrollUp'].includes(s.action)"
                                class="space-y-1"
                              >
                                <Label class="text-xs">Amount (px)</Label>
                                <Input
                                  type="number"
                                  :model-value="s.amount ?? 300"
                                  placeholder="300"
                                  min="0"
                                  class="font-mono text-xs h-7"
                                  @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'amount', $event ? parseInt(String($event), 10) : undefined)"
                                />
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </template>

                  <div
                    v-if="
                      !['navigate', 'wait', 'scrollDown', 'scrollUp'].includes(step.action)
                        && (step.selector || step.action === 'getVisibleTextOnPage')
                    "
                    class="space-y-1"
                  >
                    <Label class="text-xs">Step Timeout (ms, optional)</Label>
                    <Input
                      type="number"
                      :model-value="step.timeout || ''"
                      placeholder="30000"
                      min="0"
                      @update:model-value="updatePlaywrightStep(section.key, index, 'timeout', $event ? parseInt($event as string) : undefined)"
                    />
                  </div>
                </div>

                <p
                  v-if="!getPlaywrightSteps(section.key).length"
                  class="text-xs text-muted-foreground"
                >
                  {{ section.emptyText }}
                </p>
              </div>
            </div>

            <div class="space-y-2 pt-2 border-t">
              <div class="flex flex-col gap-1">
                <div class="flex items-center gap-2">
                  <input
                    id="playwright-headless"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="selectedNode.data.playwrightHeadless !== false"
                    @change="updateNodeData('playwrightHeadless', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="playwright-headless"
                    class="text-sm font-normal"
                  >
                    Headless mode
                  </Label>
                </div>
                <p class="text-xs text-muted-foreground">
                  Only applies in local development. Docker always runs headless (no display).
                </p>
              </div>
              <div class="flex flex-col gap-1">
                <div class="flex items-center gap-2">
                  <input
                    id="playwright-capture-network"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="selectedNode.data.playwrightCaptureNetwork === true"
                    @change="updateNodeData('playwrightCaptureNetwork', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    for="playwright-capture-network"
                    class="text-sm font-normal"
                  >
                    Capture network requests
                  </Label>
                </div>
                <p class="text-xs text-muted-foreground">
                  Capture JSON API responses, headers, and cookies during execution.
                </p>
              </div>
              <div class="space-y-1">
                <Label class="text-xs">Timeout (ms)</Label>
                <Input
                  type="number"
                  :model-value="selectedNode.data.playwrightTimeout || 30000"
                  placeholder="30000"
                  min="5000"
                  max="120000"
                  @update:model-value="updateNodeData('playwrightTimeout', $event ? parseInt($event as string) : 30000)"
                />
              </div>
            </div>

            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Output</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <div>${{ selectedNode.data.label }}.status - "ok" on success</div>
                <div>${{ selectedNode.data.label }}.results - Output from getText/getAttribute/getHTML/getVisibleTextOnPage/screenshot</div>
                <div>${{ selectedNode.data.label }}.screenshot - Base64 screenshot if step has outputKey</div>
                <div v-if="selectedNode.data.playwrightCaptureNetwork || selectedNode.data.playwrightAuthEnabled">
                  ${{ selectedNode.data.label }}.cookies - HTTP cookies
                </div>
                <template v-if="selectedNode.data.playwrightCaptureNetwork">
                  <div>${{ selectedNode.data.label }}.networkRequests - Captured JSON responses (max 200)</div>
                  <div>${{ selectedNode.data.label }}.localStorage - Browser localStorage key-value pairs</div>
                  <div>${{ selectedNode.data.label }}.sessionStorage - Browser sessionStorage key-value pairs</div>
                </template>
              </div>
            </div>
          </template>

          <div
            v-if="!['textInput', 'cron', 'sticky', 'errorHandler', 'output', 'throwError', 'telegramTrigger', 'websocketTrigger', 'slackTrigger', 'imapTrigger'].includes(selectedNode.type) && !(selectedNode.type === 'rabbitmq' && selectedNode.data.rabbitmqOperation === 'receive')"
            class="space-y-4 pt-4 border-t"
          >
            <Label class="text-muted-foreground">Error Handling</Label>

            <div class="space-y-3">
              <div class="flex items-center gap-2">
                <input
                  id="retry-enabled"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.retryEnabled"
                  @change="updateNodeData('retryEnabled', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="retry-enabled"
                  class="text-sm font-normal"
                >
                  Retry on failure
                </Label>
              </div>

              <template v-if="selectedNode.data.retryEnabled">
                <div class="space-y-2 pl-6">
                  <div class="flex items-center gap-3">
                    <Label class="text-sm font-normal min-w-[100px]">Max attempts</Label>
                    <Input
                      type="number"
                      :model-value="selectedNode.data.retryMaxAttempts || 3"
                      min="1"
                      max="10"
                      class="w-20 h-8"
                      @update:model-value="updateNodeData('retryMaxAttempts', $event ? parseInt($event as string) : 3)"
                    />
                  </div>
                  <div class="flex items-center gap-3">
                    <Label class="text-sm font-normal min-w-[100px]">Wait (seconds)</Label>
                    <Input
                      type="number"
                      :model-value="selectedNode.data.retryWaitSeconds || 5"
                      min="1"
                      max="60"
                      class="w-20 h-8"
                      @update:model-value="updateNodeData('retryWaitSeconds', $event ? parseInt($event as string) : 5)"
                    />
                  </div>
                </div>
                <p class="text-xs text-muted-foreground">
                  If node fails, retry up to {{ selectedNode.data.retryMaxAttempts || 3 }} times with {{
                    selectedNode.data.retryWaitSeconds || 5 }}s wait between attempts
                </p>
              </template>
            </div>

            <div class="space-y-3 pt-2">
              <div class="flex items-center gap-2">
                <input
                  id="on-error-enabled"
                  type="checkbox"
                  class="h-4 w-4 rounded border-input bg-background"
                  :checked="!!selectedNode.data.onErrorEnabled"
                  @change="updateNodeData('onErrorEnabled', ($event.target as HTMLInputElement).checked)"
                >
                <Label
                  for="on-error-enabled"
                  class="text-sm font-normal"
                >
                  Continue on error
                </Label>
              </div>

              <template v-if="selectedNode.data.onErrorEnabled">
                <p class="text-xs text-muted-foreground pl-6">
                  When enabled, if this node fails, the workflow will continue via the <span
                    class="text-red-400 font-medium"
                  >error</span> output handle instead of stopping.
                </p>
                <div class="text-xs font-mono space-y-1 text-muted-foreground pl-6">
                  <div>${{ selectedNode.data.label }}.error - Error message</div>
                </div>
              </template>
            </div>
          </div>

          <div class="space-y-2 pt-4 border-t">
            <div class="flex items-center justify-between">
              <Label>Pinned Data</Label>
              <div class="flex items-center gap-2">
                <template v-if="isEditingPinnedData">
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-11 min-h-[44px] md:h-7 px-2"
                    @click="cancelEditingPinnedData"
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-11 min-h-[44px] md:h-7 px-2"
                    @click="pinNodeOutput"
                  >
                    Save
                  </Button>
                </template>
                <template v-else>
                  <Button
                    v-if="!pinnedData"
                    variant="outline"
                    size="sm"
                    class="h-7 px-2"
                    :disabled="!nodeOutput"
                    @click="pinNodeOutput"
                  >
                    Pin
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="h-7 px-2"
                    :disabled="!pinnedData"
                    @click="clearPinnedData"
                  >
                    Clear
                  </Button>
                </template>
              </div>
            </div>
            <div v-if="isEditingPinnedData">
              <Textarea
                v-model="editedPinnedData"
                class="font-mono text-xs"
                :rows="8"
                placeholder="{}"
              />
              <p class="text-xs text-muted-foreground mt-1">
                Edit JSON directly. Click Save to apply.
              </p>
            </div>
            <div
              v-else-if="pinnedData"
              class="p-2 rounded-md bg-amber-500/10 text-xs font-mono overflow-auto max-h-40 cursor-pointer hover:bg-amber-500/20 transition-colors"
              title="Double-click to edit"
              @dblclick="startEditingPinnedData"
            >
              <pre>{{ JSON.stringify(displayPinnedData, null, 2) }}</pre>
            </div>
            <p
              v-else
              class="text-xs text-muted-foreground"
            >
              No pinned data for this node.
            </p>
          </div>

          <div
            v-if="nodeOutput"
            class="space-y-2 pt-4 border-t rounded-lg border border-border/40 bg-muted/20 p-3"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2 min-w-0">
                <Label>Last Output</Label>
                <CheckCircle2
                  v-if="nodeOutput.status === 'success'"
                  class="w-4 h-4 shrink-0 text-green-500"
                />
                <XCircle
                  v-else-if="nodeOutput.status === 'error'"
                  class="w-4 h-4 shrink-0 text-red-500"
                />
              </div>
              <div
                v-if="!nodeOutput.error"
                class="flex items-center gap-1.5 shrink-0"
              >
                <div
                  v-if="selectedNodeLoopItemNavigation"
                  class="flex items-center gap-0.5 rounded-md border border-border/50 bg-background/70 px-1 py-1"
                >
                  <span class="px-1 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                    Loop
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-7 w-7"
                    :disabled="!selectedNodeLoopItemNavigation.canNavigatePrev"
                    title="Previous loop item"
                    @click.stop="navigateToPreviousSelectedNodeLoopItem"
                  >
                    <ChevronLeft class="w-3.5 h-3.5" />
                  </Button>
                  <span class="min-w-[3.5rem] text-center text-xs text-muted-foreground">
                    {{ selectedNodeLoopItemNavigation.currentDisplayIndex }} /
                    {{ selectedNodeLoopItemNavigation.totalDisplayCount }}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    class="h-7 w-7"
                    :disabled="!selectedNodeLoopItemNavigation.canNavigateNext"
                    title="Next loop item"
                    @click.stop="navigateToNextSelectedNodeLoopItem"
                  >
                    <ChevronRight class="w-3.5 h-3.5" />
                  </Button>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-7 px-2 gap-1.5"
                  @click="isLastOutputExpanded = !isLastOutputExpanded"
                >
                  <Maximize2
                    v-if="!isLastOutputExpanded"
                    class="w-3.5 h-3.5"
                  />
                  <Minimize2
                    v-else
                    class="w-3.5 h-3.5"
                  />
                  <span class="text-xs">{{ isLastOutputExpanded ? 'Minimize' : 'Expand' }}</span>
                </Button>
                <button
                  class="flex items-center gap-1 px-2 py-1 rounded hover:bg-muted transition-colors text-xs shrink-0"
                  :title="copied ? 'Copied!' : 'Copy to clipboard'"
                  @click="copyOutput"
                >
                  <Check
                    v-if="copied"
                    class="w-3 h-3 text-green-500"
                  />
                  <Copy
                    v-else
                    class="w-3 h-3 text-muted-foreground"
                  />
                  <span
                    v-if="copied"
                    class="text-green-500"
                  >Copied</span>
                </button>
              </div>
            </div>
            <div
              v-if="nodeOutput.error"
              class="p-2 rounded-md bg-red-500/10 text-red-400 text-xs font-mono break-all whitespace-pre-wrap"
            >
              {{ nodeOutput.error }}
            </div>
            <template v-else>
              <div
                v-if="nodeOutputImageSrcs.length > 0 && !isLastOutputExpanded"
                class="space-y-2"
              >
                <div class="flex flex-wrap gap-2">
                  <img
                    v-for="(src, idx) in nodeOutputImageSrcs"
                    :key="idx"
                    :src="src"
                    :alt="`Screenshot ${idx + 1}`"
                    class="w-24 h-24 sm:w-28 sm:h-28 rounded-md border object-cover cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all"
                    @click="imageLightboxSrc = src"
                  >
                </div>
                <div
                  v-if="(nodeOutput.output as Record<string, unknown>)?.revised_prompt"
                  class="p-2 rounded-md bg-muted text-xs"
                >
                  <span class="text-muted-foreground">Revised prompt:</span>
                  <p class="mt-1">
                    {{ (nodeOutput.output as Record<string, unknown>).revised_prompt }}
                  </p>
                </div>
              </div>
              <div
                v-else-if="!isLastOutputExpanded"
                class="p-2 rounded-md bg-muted text-xs font-mono overflow-auto max-h-48"
              >
                <pre>{{ JSON.stringify(displayNodeOutput, null, 2) }}</pre>
              </div>
            </template>
            <div class="text-xs text-muted-foreground">
              Execution time: {{ nodeOutput.execution_time_ms.toFixed(2) }}ms
            </div>

            <Teleport to="body">
              <Transition name="fade">
                <div
                  v-if="isLastOutputExpanded && nodeOutput && !nodeOutput.error"
                  class="fixed inset-0 z-50 flex items-center justify-center"
                >
                  <div
                    class="absolute inset-0 bg-black/50 backdrop-blur-sm"
                    @click="isLastOutputExpanded = false"
                  />
                  <div
                    ref="lastOutputExpandedPanelRef"
                    class="relative w-[90vw] max-w-full h-[90vh] rounded-lg border border-border bg-card shadow-md flex flex-col overflow-x-hidden outline-none"
                    tabindex="-1"
                    role="dialog"
                    aria-modal="true"
                    @keydown.escape.stop.prevent="isLastOutputExpanded = false"
                  >
                    <div class="flex items-center justify-between gap-2 sm:gap-3 p-3 sm:p-4 border-b">
                      <div class="flex items-center gap-2 min-w-0 flex-1">
                        <CheckCircle2 class="w-4 h-4 text-primary shrink-0" />
                        <Label class="text-sm font-medium truncate">
                          Last Output — {{ selectedNodeEvaluateDialogLabel }}
                        </Label>
                      </div>
                      <div class="flex items-center justify-end gap-1 shrink-0 flex-wrap">
                        <div
                          v-if="selectedNodeLoopItemNavigation"
                          class="flex items-center gap-0.5 rounded-md border border-border/50 bg-background/70 px-1 py-1"
                        >
                          <span class="px-1 text-[10px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                            Loop
                          </span>
                          <Button
                            variant="ghost"
                            size="icon"
                            class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                            :disabled="!selectedNodeLoopItemNavigation.canNavigatePrev"
                            title="Previous loop item"
                            @click.stop="navigateToPreviousSelectedNodeLoopItem"
                          >
                            <ChevronLeft class="w-3.5 h-3.5" />
                          </Button>
                          <span class="min-w-[3.75rem] text-center text-xs text-muted-foreground">
                            {{ selectedNodeLoopItemNavigation.currentDisplayIndex }} /
                            {{ selectedNodeLoopItemNavigation.totalDisplayCount }}
                          </span>
                          <Button
                            variant="ghost"
                            size="icon"
                            class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                            :disabled="!selectedNodeLoopItemNavigation.canNavigateNext"
                            title="Next loop item"
                            @click.stop="navigateToNextSelectedNodeLoopItem"
                          >
                            <ChevronRight class="w-3.5 h-3.5" />
                          </Button>
                        </div>
                        <template
                          v-if="displayNodeOutput !== null && typeof displayNodeOutput === 'object'"
                        >
                          <Button
                            variant="ghost"
                            size="sm"
                            class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                            @click="expandAllLastOutputJson"
                          >
                            Expand all
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                            @click="collapseAllLastOutputJson"
                          >
                            Collapse all
                          </Button>
                        </template>
                        <Button
                          variant="ghost"
                          size="sm"
                          class="h-11 min-h-[44px] md:h-7 px-2 gap-1.5"
                          @click="copyOutput"
                        >
                          <Copy class="w-3.5 h-3.5" />
                          <span class="text-xs">{{ copied ? 'Copied!' : 'Copy' }}</span>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                          @click="isLastOutputExpanded = false"
                        >
                          <X class="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                    <div class="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
                      <div
                        v-if="nodeOutputImageSrcs.length > 0"
                        class="flex flex-wrap gap-2"
                      >
                        <img
                          v-for="(src, idx) in nodeOutputImageSrcs"
                          :key="`modal-${idx}`"
                          :src="src"
                          :alt="`Screenshot ${idx + 1}`"
                          class="w-24 h-24 sm:w-28 sm:h-28 rounded-md border object-cover cursor-pointer hover:ring-2 hover:ring-primary/50 transition-all"
                          @click="imageLightboxSrc = src"
                        >
                      </div>
                      <div
                        v-if="displayNodeOutput !== null && typeof displayNodeOutput === 'object'"
                        class="text-xs font-mono"
                      >
                        <JsonTree
                          :key="lastOutputJsonTreeKey"
                          :data="displayNodeOutput"
                          :root-expanded="true"
                          :auto-expand-depth="lastOutputJsonAutoDepth"
                        />
                      </div>
                      <pre
                        v-else
                        class="text-xs font-mono whitespace-pre-wrap break-words text-foreground"
                      >{{ formatOutput(displayNodeOutput) }}</pre>
                    </div>
                  </div>
                </div>
              </Transition>
            </Teleport>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="activeTab === 'config'"
      class="flex-1 flex flex-col overflow-hidden overflow-x-hidden min-h-0"
    >
      <div class="flex-1 flex flex-col overflow-hidden min-h-0">
        <div
          :class="[
            'overflow-y-auto overflow-x-hidden p-3 sm:p-4 space-y-4 min-w-0',
            !lastExecutedNode || isExecuting ? 'flex-1' : 'flex-shrink-0'
          ]"
        >
          <template v-if="isGenericWebhookBodyMode">
            <div class="space-y-2 min-w-0">
              <div class="flex items-center justify-between gap-3">
                <Label>Raw JSON Body</Label>
                <Button
                  variant="ghost"
                  size="sm"
                  :disabled="!!runBodyError"
                  @click="formatRunInputJson"
                >
                  Format JSON
                </Button>
              </div>
              <Textarea
                :model-value="runInputJson"
                :rows="8"
                :disabled="isExecuting"
                class="min-w-0 w-full font-mono text-sm"
                :placeholder="genericBodyPlaceholder"
                @update:model-value="updateRunInputJson"
              />
              <p class="text-xs text-muted-foreground">
                Generic mode sends the request body exactly as written here. Access nested values through $inputLabel.body.*
              </p>
              <p
                v-if="runBodyError"
                class="text-xs text-red-500"
              >
                {{ runBodyError }}
              </p>
            </div>
          </template>

          <template v-else-if="allInputFields.length > 0">
            <div
              v-for="field in allInputFields"
              :key="field.key"
              class="space-y-2 min-w-0"
            >
              <Label class="truncate">{{ field.key }}</Label>
              <Textarea
                :model-value="runInputValues[field.key] ?? ''"
                :placeholder="field.defaultValue || `Enter ${field.key}...`"
                :rows="3"
                :disabled="isExecuting"
                class="min-w-0 w-full"
                @update:model-value="updateInputValue(field.key, $event)"
              />
            </div>
          </template>

          <Button
            class="w-full min-w-0"
            :loading="isExecuting"
            :disabled="!hasNodes || !!runBodyError"
            @click="handleExecute"
          >
            <Play class="w-4 h-4 shrink-0" />
            <span class="hidden sm:inline truncate">{{ isExecuting ? 'Executing...' : 'Run Workflow' }}</span>
          </Button>

          <p
            v-if="hasNodes"
            class="hidden sm:block text-xs text-muted-foreground text-center break-words"
          >
            Press <kbd class="px-1.5 py-0.5 rounded bg-muted font-mono">Ctrl+Enter</kbd> to run
          </p>

          <p
            v-if="!hasNodes"
            class="text-xs text-muted-foreground text-center"
          >
            Add nodes to your workflow to run it
          </p>
        </div>

        <div
          v-if="lastExecutedNode && !isExecuting"
          :class="[
            'flex-1 flex flex-col overflow-hidden pt-4 px-4 pb-4 min-h-0',
            allInputFields.length > 0 || isGenericWebhookBodyMode ? 'border-t border-border/30' : ''
          ]"
        >
          <div class="space-y-2">
            <div class="flex items-center gap-2">
              <CheckCircle2 class="w-4 h-4 text-primary" />
              <Label class="text-sm font-medium">Last Executed Node</Label>
            </div>
            <div class="rounded-md bg-muted/50 p-2">
              <p class="text-sm font-medium text-foreground">
                {{ lastExecutedNode.node_label }}
              </p>
              <p class="text-xs text-muted-foreground mt-1">
                Status: <span
                  :class="lastExecutedNode.status === 'success' ? 'text-green-500' : lastExecutedNode.status === 'error' ? 'text-red-500' : 'text-yellow-500'"
                >{{
                  lastExecutedNode.status }}</span>
              </p>
            </div>
          </div>

          <div class="flex-1 flex flex-col space-y-2 min-h-0">
            <div class="flex items-center justify-between flex-shrink-0">
              <Label class="text-sm font-medium">Output</Label>
              <div class="flex items-center gap-1.5">
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-7 px-2 gap-1.5"
                  @click="isOutputExpanded = !isOutputExpanded"
                >
                  <Maximize2
                    v-if="!isOutputExpanded"
                    class="w-3.5 h-3.5"
                  />
                  <Minimize2
                    v-else
                    class="w-3.5 h-3.5"
                  />
                  <span class="text-xs">{{ isOutputExpanded ? 'Minimize' : 'Expand' }}</span>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-7 px-2 gap-1.5"
                  @click="copyLastNodeOutput"
                >
                  <Copy class="w-3.5 h-3.5" />
                  <span class="text-xs">{{ copiedOutput ? 'Copied!' : 'Copy' }}</span>
                </Button>
              </div>
            </div>
            <div
              v-if="!isOutputExpanded"
              class="flex-1 rounded-md border border-border/30 bg-muted/30 p-3 overflow-y-auto min-h-0"
            >
              <pre class="text-xs font-mono whitespace-pre-wrap break-words text-foreground">{{
              formatOutput(lastExecutedNode.output) }}</pre>
            </div>
          </div>

          <Teleport to="body">
            <Transition name="fade">
              <div
                v-if="isOutputExpanded"
                class="fixed inset-0 z-50 flex items-center justify-center"
              >
                <div
                  class="absolute inset-0 bg-black/50 backdrop-blur-sm"
                  @click="isOutputExpanded = false"
                />
                <div
                  ref="runOutputExpandedPanelRef"
                  class="relative w-[90vw] max-w-full h-[90vh] rounded-lg border border-border bg-card shadow-md flex flex-col overflow-x-hidden outline-none"
                  tabindex="-1"
                  role="dialog"
                  aria-modal="true"
                  @keydown.escape.stop.prevent="isOutputExpanded = false"
                >
                  <div class="flex items-center justify-between gap-2 sm:gap-3 p-3 sm:p-4 border-b">
                    <div class="flex items-center gap-2 min-w-0 flex-1">
                      <CheckCircle2 class="w-4 h-4 text-primary shrink-0" />
                      <Label class="text-sm font-medium truncate">
                        Output — {{ lastExecutedNode.node_label }}
                      </Label>
                    </div>
                    <div class="flex items-center justify-end gap-1 shrink-0 flex-wrap">
                      <template
                        v-if="lastExecutedNode.output && typeof lastExecutedNode.output === 'object'"
                      >
                        <Button
                          variant="ghost"
                          size="sm"
                          class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                          @click="expandAllRunOutputJson"
                        >
                          Expand all
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          class="h-11 min-h-[44px] md:h-7 px-2 text-[11px] font-medium"
                          @click="collapseAllRunOutputJson"
                        >
                          Collapse all
                        </Button>
                      </template>
                      <Button
                        variant="ghost"
                        size="sm"
                        class="h-11 min-h-[44px] md:h-7 px-2 gap-1.5"
                        @click="copyLastNodeOutput"
                      >
                        <Copy class="w-3.5 h-3.5" />
                        <span class="text-xs">{{ copiedOutput ? 'Copied!' : 'Copy' }}</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        class="h-11 w-11 min-h-[44px] min-w-[44px] md:h-7 md:w-7"
                        @click="isOutputExpanded = false"
                      >
                        <X class="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                  <div class="flex-1 overflow-y-auto p-4 min-h-0">
                    <div
                      v-if="lastExecutedNode.output && typeof lastExecutedNode.output === 'object'"
                      class="text-xs font-mono"
                    >
                      <JsonTree
                        :key="runOutputJsonTreeKey"
                        :data="lastExecutedNode.output"
                        :root-expanded="true"
                        :auto-expand-depth="runOutputJsonAutoDepth"
                      />
                    </div>
                    <pre
                      v-else
                      class="text-xs font-mono whitespace-pre-wrap break-words text-foreground"
                    >{{
                    formatOutput(lastExecutedNode.output) }}</pre>
                  </div>
                </div>
              </div>
            </Transition>
          </Teleport>
        </div>
      </div>
    </div>
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
        <div
          class="relative bg-card border rounded-lg shadow-md w-[90vw] max-w-[400px] max-h-[80vh] overflow-hidden overflow-x-hidden"
        >
          <div class="flex items-center justify-between p-4 border-b bg-destructive/10">
            <div class="flex items-center gap-2">
              <AlertTriangle class="w-5 h-5 text-destructive" />
              <h3 class="font-semibold text-destructive">
                Configuration Required
              </h3>
            </div>
            <button
              class="p-2 rounded hover:bg-muted transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
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

  <SelectorPickerDialog
    :open="selectorPickerOpen"
    :initial-url="selectorPickerInitialUrl"
    @close="selectorPickerOpen = false"
    @select="onSelectorPicked"
  />

  <SkillBuilderModal
    :open="skillBuilderOpen"
    :credential-id="selectedNode?.data?.credentialId || ''"
    :existing-skill="skillBuilderTargetSkill"
    :model="selectedNode?.data?.model || ''"
    @save="handleSkillBuilderSave"
    @update:open="skillBuilderOpen = $event"
  />
</template>

<style scoped>
.properties-panel {
  background: linear-gradient(180deg,
      hsl(var(--card) / 0.95) 0%,
      hsl(var(--card) / 0.85) 100%);
  backdrop-filter: blur(8px);
  position: relative;
  z-index: 10;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
