import {
  computed,
  inject,
  nextTick,
  onMounted,
  onUnmounted,
  provide,
  ref,
  watch,
  type ComponentPublicInstance,
  type InjectionKey,
} from "vue";
import { useRouter } from "vue-router";
import { AlertTriangle, Ban, BarChart3, Bot, Braces, Brain, Bug, CalendarClock, Clock, Database, FileJson, FileText, GitBranch, GitMerge, Github, Globe, HardDrive, Inbox, ListTodo, Mail, MessageSquare, MonitorPlay, Play, Plug, Puzzle, Rabbit, Radio, Repeat, Search, Send, Server, Settings2, Sheet, ShieldAlert, Shuffle, StickyNote, Table2, Terminal, Type, Upload, Variable, XCircle } from "lucide-vue-next";
import type { ClickHouseColumn, CredentialListItem, LLMModel, NotionDataSourceItem, NotionPageItem } from "@/types/credential";
import type { AgentMCPConnection, AgentSkill, AgentSkillFile, ExecuteInputMapping, GuardrailCategory, InputField, MappingField, MCPTransportType, OutputSchemaField, PlaywrightStep, PlaywrightStepAction, WorkflowListItem } from "@/types/workflow";
import { createAgentSkillZipBlob, getSkillZipFileName, parseSkillZip } from "@/lib/skillZipParser";
import { isRetryAttemptNodeResult } from "@/lib/executionLog";
import { findEnclosingLoopIdForListSize, findNodeResultIndexForLoopIteration, mapNodeResultsToEnclosingLoopIterations, selectedLoopIterationIndexForNode } from "@/lib/loopNodeDisplay";
import { getGitHubExpressionFields, type GitHubExpressionFieldKey } from "@/lib/githubExpressionFields";
import { getLinearExpressionFields, type LinearExpressionFieldKey } from "@/lib/linearExpressionFields";
import { getNotionExpressionFields, type NotionExpressionFieldKey } from "@/lib/notionExpressionFields";
import { getSentryExpressionFields, type SentryExpressionFieldKey } from "@/lib/sentryExpressionFields";
import { parseWebhookJson, stringifyWebhookJson } from "@/lib/webhookBody";
import { configApi, credentialsApi, dataTablesApi, filesApi, gristApi, mcpApi, workflowApi } from "@/services/api";
import type { MCPFetchToolItem } from "@/services/api";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { useToast } from "@/composables/useToast";
import { useRunPanelFileDrag } from "@/composables/useRunPanelFileDrag";
import type { DataTableListItem } from "@/types/dataTable";
import type { GeneratedFile } from "@/types/file";
import { useAuthStore } from "@/stores/auth";
import { useWorkflowStore, type ValidationError } from "@/stores/workflow";
import { useRunbookPlayer } from "@/features/runbook/useRunbookPlayer";
import type { NodeType } from "@/types/workflow";
import type { WebSocketTriggerEventName } from "@/types/workflow";
import { NODE_DEFINITIONS } from "@/types/node";
import {
  bigQueryOperationOptions,
  clickhouseOperationGroups,
  clickhouseOperationOptions,
  dataTableOperationOptions,
  driveOperationOptions,
  githubOperationGroups,
  githubOperationOptions,
  googleSheetsOperationOptions,
  gristOperationOptions,
  linearOperationGroups,
  linearOperationOptions,
  notionOperationGroups,
  notionOperationOptions,
  rabbitmqOperationOptions,
  ragOperationOptions,
  redisOperationOptions,
  s3OperationGroups,
  s3OperationOptions,
  supabaseOperationOptions,
} from "./operationOptions";

interface ExpandableFieldRef {
  openExpandDialog(localIndex?: number): void;
  closeExpandDialog(): void;
}

type CodexExpressionFieldKey =
  | "repositoryUrl"
  | "baseBranch"
  | "taskPrompt"
  | "branchName"
  | "setupCommand";

interface CodexExpressionField {
  key: CodexExpressionFieldKey;
  label: string;
}

export function usePropertiesPanelController() {
  const nodeIcons: Record<NodeType, ReturnType<typeof Type>> = {
    chartOutput: BarChart3,
    textInput: Type,
    cron: CalendarClock,
    websocketTrigger: Radio,
    fileUploadTrigger: Upload,
    llm: Brain,
    agent: Bot,
    codex: Terminal,
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
    discord: MessageSquare,
    discordTrigger: MessageSquare,
    imapTrigger: Inbox,
    sendEmail: Mail,
    errorHandler: AlertTriangle,
    variable: Variable,
    loop: Repeat,
    disableNode: Ban,
    redis: Database,
    rag: Search,
    grist: Table2,
    github: Github,
    linear: ListTodo,
    googleSheets: Sheet,
    bigquery: Database,
    supabase: Database,
    clickhouse: Database,
    notion: FileText,
    sentry: ShieldAlert,
    throwError: XCircle,
    rabbitmq: Rabbit,
    crawler: Bug,
    consoleLog: Terminal,
    playwright: MonitorPlay,
    dataTable: Table2,
    drive: HardDrive,
    s3: Server,
    mcpCall: Plug,
    plugin: Puzzle,
    pluginTrigger: Puzzle,
  };

  const nodeColorMap: Record<NodeType, string> = {
    chartOutput: "node-output",
    textInput: "node-input",
    cron: "node-cron",
    websocketTrigger: "node-websocket",
    fileUploadTrigger: "node-websocket",
    llm: "node-llm",
    agent: "node-agent",
    codex: "node-codex",
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
    discord: "node-discord",
    discordTrigger: "node-discord",
    imapTrigger: "node-email",
    sendEmail: "node-email",
    errorHandler: "node-error",
    variable: "node-variable",
    loop: "node-loop",
    disableNode: "node-disable",
    redis: "node-redis",
    rag: "node-rag",
    grist: "node-grist",
    github: "node-github",
    linear: "node-linear",
    googleSheets: "node-google-sheets",
    bigquery: "node-google-sheets",
    supabase: "node-datatable",
    clickhouse: "node-datatable",
    notion: "node-notion",
    sentry: "node-sentry",
    throwError: "node-throw-error",
    rabbitmq: "node-rabbitmq",
    crawler: "node-crawler",
    consoleLog: "node-console-log",
    playwright: "node-playwright",
    dataTable: "node-datatable",
    drive: "node-drive",
    s3: "node-drive",
    mcpCall: "node-agent",
    plugin: "node-action",
    pluginTrigger: "node-trigger",
  };

  const nodeDocSlugMap: Record<NodeType, string> = {
    chartOutput: "chart-output-node",
    textInput: "input-node",
    cron: "cron-node",
    websocketTrigger: "websocket-trigger-node",
    fileUploadTrigger: "file-upload-trigger-node",
    llm: "llm-node",
    agent: "agent-node",
    codex: "codex-node",
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
    discord: "discord-node",
    discordTrigger: "discord-trigger-node",
    imapTrigger: "imap-trigger-node",
    sendEmail: "send-email-node",
    errorHandler: "error-handler-node",
    variable: "variable-node",
    loop: "loop-node",
    disableNode: "disable-node",
    redis: "redis-node",
    rag: "rag-node",
    grist: "grist-node",
    github: "github-node",
    linear: "linear-node",
    googleSheets: "google-sheets-node",
    bigquery: "bigquery-node",
    supabase: "supabase-node",
    clickhouse: "clickhouse-node",
    notion: "notion-node",
    sentry: "sentry-node",
    throwError: "throw-error-node",
    rabbitmq: "rabbitmq-node",
    crawler: "crawler-node",
    consoleLog: "console-log-node",
    playwright: "playwright-node",
    dataTable: "datatable-node",
    drive: "drive-node",
    s3: "amazon-s3-node",
    mcpCall: "mcp-call-node",
    plugin: "plugin-node",
    pluginTrigger: "plugin-trigger-node",
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

  const autoRecoverRuns = computed(
    () => workflowStore.currentWorkflow?.auto_recover_runs ?? true,
  );

  async function onToggleAutoRecover(value: boolean): Promise<void> {
    const wf = workflowStore.currentWorkflow;
    if (!wf || !isWorkflowOwner.value) return;
    const previous = wf.auto_recover_runs;
    wf.auto_recover_runs = value;
    try {
      await workflowApi.update(wf.id, { auto_recover_runs: value });
    } catch {
      wf.auto_recover_runs = previous;
    }
  }

  const otherWorkflows = ref<WorkflowListItem[]>([]);

  async function loadOtherWorkflows(): Promise<void> {
    try {
      const all = await workflowApi.list();
      const currentId = workflowStore.currentWorkflow?.id;
      otherWorkflows.value = all.filter((w) => w.id !== currentId);
    } catch {
      otherWorkflows.value = [];
    }
  }

  onMounted(() => {
    void loadOtherWorkflows();
  });

  const errorWorkflowId = computed(
    () => workflowStore.currentWorkflow?.error_workflow_id ?? "",
  );

  const EMPTY_UUID = "00000000-0000-0000-0000-000000000000";

  async function onChangeErrorWorkflow(value: string): Promise<void> {
    const wf = workflowStore.currentWorkflow;
    if (!wf || !isWorkflowOwner.value) return;
    const previous = wf.error_workflow_id;
    const next = value === "" ? null : value;
    wf.error_workflow_id = next;
    try {
      await workflowApi.update(wf.id, {
        error_workflow_id: next === null ? EMPTY_UUID : next,
      });
    } catch {
      wf.error_workflow_id = previous;
    }
  }

  const minutesSavedPerRun = computed(
    () => workflowStore.currentWorkflow?.minutes_saved_per_run ?? null,
  );

  async function onChangeMinutesSaved(raw: string): Promise<void> {
    const wf = workflowStore.currentWorkflow;
    if (!wf || !isWorkflowOwner.value) return;
    const parsed = raw === "" ? null : Number(raw);
    const next = parsed !== null && Number.isFinite(parsed) && parsed > 0 ? parsed : null;
    const previous = wf.minutes_saved_per_run;
    wf.minutes_saved_per_run = next;
    try {
      await workflowApi.update(wf.id, { minutes_saved_per_run: next ?? 0 });
    } catch {
      wf.minutes_saved_per_run = previous;
    }
  }

  const workflowTimeoutSeconds = computed(
    () => workflowStore.currentWorkflow?.workflow_timeout_seconds ?? null,
  );

  async function onChangeWorkflowTimeout(raw: string): Promise<void> {
    const wf = workflowStore.currentWorkflow;
    if (!wf || !isWorkflowOwner.value) return;
    const parsed = raw === "" ? null : Number(raw);
    const next =
      parsed !== null && Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : null;
    const previous = wf.workflow_timeout_seconds;
    wf.workflow_timeout_seconds = next;
    try {
      await workflowApi.update(wf.id, { workflow_timeout_seconds: next ?? 0 });
    } catch {
      wf.workflow_timeout_seconds = previous;
    }
  }

  const showRunAnalyzer = computed(
    () =>
      workflowStore.nodes.length > 0 &&
      workflowStore.analysisNoteEmpty &&
      !workflowStore.analysisPanelOpen,
  );

  function openAnalyzer(): void {
    workflowStore.analysisPanelOpen = true;
  }

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

  const discordTriggerWebhookUrl = computed((): string => {
    if (!selectedNode.value || selectedNode.value.type !== "discordTrigger") return "";
    return `${window.location.origin}/api/discord/webhook/${selectedNode.value.id}`;
  });

  const telegramTriggerWebhookUrl = computed((): string => {
    if (!selectedNode.value || selectedNode.value.type !== "telegramTrigger") return "";
    return `${window.location.origin}/api/telegram/webhook/${selectedNode.value.id}`;
  });

  function copySlackWebhookUrl(): void {
    navigator.clipboard.writeText(slackTriggerWebhookUrl.value);
  }

  function copyDiscordWebhookUrl(): void {
    navigator.clipboard.writeText(discordTriggerWebhookUrl.value);
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
  const outputMessageInputRef = ref<ExpandableFieldRef | null>(null);
  const outputSchemaValueInputRefs = ref<Map<number, ExpandableFieldRef>>(new Map());
  const currentOutputExpressionFieldIndex = ref(0);
  const httpCurlInputRef = ref<ExpandableFieldRef | null>(null);
  const websocketSendUrlInputRef = ref<ExpandableFieldRef | null>(null);
  const websocketSendHeadersInputRef = ref<ExpandableFieldRef | null>(null);
  const websocketSendMessageInputRef = ref<ExpandableFieldRef | null>(null);
  const userMessageInputRef = ref<ExpandableFieldRef | null>(null);
  const telegramChatIdInputRef = ref<ExpandableFieldRef | null>(null);
  const telegramMessageInputRef = ref<ExpandableFieldRef | null>(null);
  const slackMessageInputRef = ref<ExpandableFieldRef | null>(null);
  const discordMessageInputRef = ref<ExpandableFieldRef | null>(null);
  const discordUsernameInputRef = ref<ExpandableFieldRef | null>(null);
  const discordAvatarUrlInputRef = ref<ExpandableFieldRef | null>(null);
  const sendEmailToInputRef = ref<ExpandableFieldRef | null>(null);
  const sendEmailCcInputRef = ref<ExpandableFieldRef | null>(null);
  const sendEmailBccInputRef = ref<ExpandableFieldRef | null>(null);
  const sendEmailSubjectInputRef = ref<ExpandableFieldRef | null>(null);
  const sendEmailBodyInputRef = ref<ExpandableFieldRef | null>(null);
  const sendEmailAttachmentsInputRef = ref<ExpandableFieldRef | null>(null);
  const currentSendEmailExpressionFieldIndex = ref(0);
  const conditionInputRef = ref<ExpandableFieldRef | null>(null);
  const redisKeyInputRef = ref<ExpandableFieldRef | null>(null);
  const setMappingInputRefs = ref<Map<number, ExpandableFieldRef>>(new Map());
  const currentSetMappingIndex = ref(0);
  const executeMappingInputRefs = ref<Map<number, ExpandableFieldRef>>(new Map());
  const currentExecuteMappingIndex = ref(0);

  /** When set to the newly selected node id, skip closing evaluate dialogs (graph Prev/Next reopens immediately). */
  const suppressCloseExpandDialogsForNavigationId = ref<string | null>(null);
  const llmSystemInstructionInputRef = ref<ExpandableFieldRef | null>(null);
  const llmImageExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentLlmExpressionFieldIndex = ref(0);
  const agentSystemInstructionInputRef = ref<ExpandableFieldRef | null>(null);
  const agentImageExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const agentMcpEnvInputRefs = ref<Map<string, ExpandableFieldRef>>(new Map());
  const currentAgentExpressionFieldIndex = ref(0);
  const codexRepositoryUrlExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const codexBaseBranchExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const codexTaskPromptExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const codexBranchNameExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const codexSetupCommandExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentCodexExpressionFieldIndex = ref(0);
  const variableValueInputRef = ref<ExpandableFieldRef | null>(null);
  const throwErrorMessageInputRef = ref<ExpandableFieldRef | null>(null);

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
  const discordCredentials = ref<CredentialListItem[]>([]);
  const discordTriggerCredentials = ref<CredentialListItem[]>([]);
  const imapTriggerCredentials = ref<CredentialListItem[]>([]);
  const smtpCredentials = ref<CredentialListItem[]>([]);
  const redisCredentials = ref<CredentialListItem[]>([]);
  const gristCredentials = ref<CredentialListItem[]>([]);
  const codexCredentials = ref<CredentialListItem[]>([]);
  const githubCredentials = ref<CredentialListItem[]>([]);
  const linearCredentials = ref<CredentialListItem[]>([]);
  const googleSheetsCredentials = ref<CredentialListItem[]>([]);
  const bigqueryCredentials = ref<CredentialListItem[]>([]);
  const supabaseCredentials = ref<CredentialListItem[]>([]);
  const clickhouseCredentials = ref<CredentialListItem[]>([]);
  const notionCredentials = ref<CredentialListItem[]>([]);
  const notionDiscoveredDataSources = ref<NotionDataSourceItem[]>([]);
  const loadingNotionDataSources = ref(false);
  const notionDataSourcesError = ref<string | null>(null);
  const notionDataSourceSearch = ref("");
  const notionDataSourcesNextCursor = ref<string | null>(null);
  const notionDataSourcesHasMore = ref(false);
  let notionDataSourcesRequestSequence = 0;
  let notionDataSourceSearchTimer: ReturnType<typeof setTimeout> | null = null;
  const notionDiscoveredPages = ref<NotionPageItem[]>([]);
  const loadingNotionPages = ref(false);
  const notionPagesError = ref<string | null>(null);
  const notionPageSearch = ref("");
  const notionPagesNextCursor = ref<string | null>(null);
  const notionPagesHasMore = ref(false);
  let notionPagesRequestSequence = 0;
  let notionPageSearchTimer: ReturnType<typeof setTimeout> | null = null;
  const supabaseDiscoveredTables = ref<string[]>([]);
  const supabaseDiscoveredColumns = ref<string[]>([]);
  const loadingSupabaseTables = ref(false);
  const loadingSupabaseColumns = ref(false);
  let supabaseTablesRequestSequence = 0;
  let supabaseColumnsRequestSequence = 0;
  const clickhouseDiscoveredColumns = ref<ClickHouseColumn[]>([]);
  const loadingClickhouseColumns = ref(false);
  let clickhouseColumnsRequestSequence = 0;
  const s3Credentials = ref<CredentialListItem[]>([]);
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
    Map<string, ExpandableFieldRef>
  >(new Map());
  const gristColumns = ref<{ id: string; name: string; type: string }[]>([]);
  const vectorStores = ref<{ id: string; name: string; backend: string }[]>([]);
  const ragQueryInputRef = ref<ExpandableFieldRef | null>(null);
  const ragDocumentInputRef = ref<ExpandableFieldRef | null>(null);
  const rabbitmqExchangeInputRef = ref<ExpandableFieldRef | null>(null);
  const rabbitmqRoutingKeyInputRef = ref<ExpandableFieldRef | null>(null);
  const rabbitmqQueueNameInputRef = ref<ExpandableFieldRef | null>(null);
  const rabbitmqMessageBodyInputRef = ref<ExpandableFieldRef | null>(null);
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
  const crawlerUrlInputRef = ref<ExpandableFieldRef | null>(null);
  const consoleLogMessageInputRef = ref<ExpandableFieldRef | null>(null);
  const switchExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const loopArrayExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const executeTemplateExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const gristDocIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const gristTableIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const gristRecordIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const gristRecordIdsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const gristRecordsDataExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const gristSortExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const gristRecordDataJsonInputRef = ref<ExpandableFieldRef | null>(null);
  const gristFilterJsonInputRef = ref<ExpandableFieldRef | null>(null);
  const currentGristExpressionFieldIndex = ref(0);
  const githubOwnerExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubRepoExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubOrganizationExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubInviteEmailExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubIssueNumberExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubAssigneeExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubCreatorExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubMentionedExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubLabelsFilterExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubSinceExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubTitleExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubBodyExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubCommentBodyExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubLabelsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubAssigneesExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubHeadExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubBaseExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubPullRequestNumberExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubReviewIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubReviewBodyExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubCommitIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubFilePathExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubFileContentExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubCommitMessageExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubBranchExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubTagNameExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubReleaseIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubWorkflowIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const githubWorkflowInputsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentGitHubExpressionFieldIndex = ref(0);
  const sentryOrganizationSlugExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryProjectSlugExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryTeamSlugExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryIssueIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryEventIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryReleaseVersionExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryNameExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentrySlugExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryPlatformExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryStatusExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryAssignedToExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryQueryExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryStatsPeriodExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryLimitExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryReleaseProjectsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryReleaseRefsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const sentryPayloadExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentSentryExpressionFieldIndex = ref(0);
  const linearLimitExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearAfterExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearTeamIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearProjectIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearIssueIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearTitleExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearDescriptionExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearStateIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearIssueLinkUrlExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearAssigneeIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearPriorityExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearCommentIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearCommentBodyExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const linearParentCommentIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentLinearExpressionFieldIndex = ref(0);
  const googleSheetsSpreadsheetIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const googleSheetsSheetNameExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const googleSheetsValuesInputRef = ref<ExpandableFieldRef | null>(null);
  const currentGoogleSheetsExpressionFieldIndex = ref(0);
  const bqProjectIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const bqQueryExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const bqDatasetIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const bqTableIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const bqRowsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const bqMappingInputRefs = ref<Map<number, ExpandableFieldRef>>(new Map());
  const currentBigQueryExpressionFieldIndex = ref(0);
  const clickhouseQueryExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const clickhouseTableExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const clickhouseFilterExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const clickhouseSortExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const clickhouseRowIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const clickhouseDataExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const clickhouseMappingInputRefs = ref<Map<string, ExpandableFieldRef>>(new Map());
  const currentClickhouseExpressionFieldIndex = ref(0);
  const supabaseSchemaExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const supabaseTableExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const supabaseSelectColumnsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const supabaseFilterExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const supabaseOrderByExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const supabaseRowsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const supabaseOnConflictExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const supabaseDataExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentSupabaseExpressionFieldIndex = ref(0);
  const notionQueryExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionPageIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionDatabaseIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionDatabaseExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionDataSourceIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionDataSourceExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionBlockIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionPropertiesExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionParentPageIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionBlockExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionIconExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionCoverExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionChildrenExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionFilterExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionSortExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionSortsExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionStartCursorExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const notionAfterBlockIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentNotionExpressionFieldIndex = ref(0);
  const dataTableRowIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const dataTableDataExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const dataTableFilterExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const dataTableSortExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentDataTableExpressionFieldIndex = ref(0);
  const driveFileIdExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const drivePasswordExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const driveFilenameExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const driveBase64ContentExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentDriveExpressionFieldIndex = ref(0);
  const s3BucketExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const s3KeyExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const s3SourceBucketExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const s3SourceKeyExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const s3PrefixExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const s3ContinuationTokenExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const s3BodyExpressionInputRef = ref<ExpandableFieldRef | null>(null);
  const currentS3ExpressionFieldIndex = ref(0);
  const currentPlaywrightExpressionFieldIndex = ref(0);
  /** ExpressionInput instances keyed by stable slot id (survives action changes / unmount). */
  const playwrightExprRefsBySlotKey = ref<Record<string, ExpandableFieldRef | null>>({});
  const mcpCallArgumentInputRefs = ref<Map<string, ExpandableFieldRef>>(new Map());
  const mcpCallConnectionEnvInputRef = ref<ExpandableFieldRef | null>(null);
  const currentMCPCallExpressionFieldIndex = ref(0);
  type ChartOutputExpressionFieldKey =
    | "text"
    | "valueField"
    | "dataPath"
    | "labelField"
    | "xField"
    | "yField"
    | "min"
    | "max"
    | "unit"
    | "title"
    | "url";

  interface ChartOutputExpressionField {
    key: ChartOutputExpressionFieldKey;
    label: string;
  }

  const chartOutputExpressionInputRefs = ref<
    Map<ChartOutputExpressionFieldKey, ExpandableFieldRef>
  >(new Map());
  const currentChartOutputExpressionFieldIndex = ref(0);
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
      if (type === "discord") {
        try {
          discordCredentials.value = await credentialsApi.listByType("discord");
        } catch {
          discordCredentials.value = [];
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
          vectorStores.value = stores.map((s) => ({
            id: s.id,
            name: s.name,
            backend: s.backend ?? "qdrant",
          }));
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

      if (type === "github") {
        try {
          githubCredentials.value = await credentialsApi.listByType("github");
        } catch {
          githubCredentials.value = [];
        }
      }

      if (type === "codex") {
        try {
          codexCredentials.value = await credentialsApi.listByType("codex");
        } catch {
          codexCredentials.value = [];
        }
        try {
          githubCredentials.value = await credentialsApi.listByType("github");
        } catch {
          githubCredentials.value = [];
        }
      }

      if (type === "linear") {
        try {
          linearCredentials.value = await credentialsApi.listByType("linear");
        } catch {
          linearCredentials.value = [];
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

      if (type === "supabase") {
        try {
          supabaseCredentials.value = await credentialsApi.listByType("supabase");
        } catch {
          supabaseCredentials.value = [];
        }
      }

      if (type === "clickhouse") {
        try {
          clickhouseCredentials.value = await credentialsApi.listByType("clickhouse");
        } catch {
          clickhouseCredentials.value = [];
        }
      }

      if (type === "notion") {
        try {
          notionCredentials.value = await credentialsApi.listByType("notion");
        } catch {
          notionCredentials.value = [];
        }
      }

      if (type === "s3") {
        try {
          s3Credentials.value = await credentialsApi.listByType("s3");
        } catch {
          s3Credentials.value = [];
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
      if (type === "discordTrigger") {
        try {
          discordTriggerCredentials.value = await credentialsApi.listByType("discord_trigger");
        } catch {
          discordTriggerCredentials.value = [];
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

  async function loadSupabaseTablesForSelectedNode(): Promise<void> {
    const node = workflowStore.selectedNode;
    if (!node || node.type !== "supabase") {
      supabaseDiscoveredTables.value = [];
      return;
    }

    const credentialId = String(node.data.credentialId || "").trim();
    if (!credentialId) {
      supabaseDiscoveredTables.value = [];
      return;
    }

    const requestId = ++supabaseTablesRequestSequence;
    const selectedNodeId = node.id;
    const selectedCredentialId = credentialId;
    const selectedSchema = String(node.data.supabaseSchema || "").trim() || undefined;
    loadingSupabaseTables.value = true;
    try {
      const result = await credentialsApi.listSupabaseTables(selectedCredentialId, selectedSchema);
      const currentNode = workflowStore.selectedNode;
      if (
        requestId !== supabaseTablesRequestSequence ||
        !currentNode ||
        currentNode.type !== "supabase" ||
        currentNode.id !== selectedNodeId ||
        String(currentNode.data.credentialId || "").trim() !== selectedCredentialId ||
        (String(currentNode.data.supabaseSchema || "").trim() || undefined) !== selectedSchema
      ) {
        return;
      }
      supabaseDiscoveredTables.value = result.tables || [];
    } catch {
      if (requestId === supabaseTablesRequestSequence) {
        supabaseDiscoveredTables.value = [];
      }
    } finally {
      if (requestId === supabaseTablesRequestSequence) {
        loadingSupabaseTables.value = false;
      }
    }
  }

  async function loadSupabaseColumnsForSelectedNode(): Promise<void> {
    const node = workflowStore.selectedNode;
    if (!node || node.type !== "supabase") {
      supabaseDiscoveredColumns.value = [];
      return;
    }

    const credentialId = String(node.data.credentialId || "").trim();
    const table = String(node.data.supabaseTable || "").trim();
    if (!credentialId || !table) {
      supabaseDiscoveredColumns.value = [];
      return;
    }

    const requestId = ++supabaseColumnsRequestSequence;
    const selectedNodeId = node.id;
    const selectedCredentialId = credentialId;
    const selectedTable = table;
    const selectedSchema = String(node.data.supabaseSchema || "").trim() || undefined;
    loadingSupabaseColumns.value = true;
    try {
      const result = await credentialsApi.listSupabaseColumns(
        selectedCredentialId,
        selectedTable,
        selectedSchema,
      );
      const currentNode = workflowStore.selectedNode;
      if (
        requestId !== supabaseColumnsRequestSequence ||
        !currentNode ||
        currentNode.type !== "supabase" ||
        currentNode.id !== selectedNodeId ||
        String(currentNode.data.credentialId || "").trim() !== selectedCredentialId ||
        String(currentNode.data.supabaseTable || "").trim() !== selectedTable ||
        (String(currentNode.data.supabaseSchema || "").trim() || undefined) !== selectedSchema
      ) {
        return;
      }
      supabaseDiscoveredColumns.value = result.columns || [];
    } catch {
      if (requestId === supabaseColumnsRequestSequence) {
        supabaseDiscoveredColumns.value = [];
      }
    } finally {
      if (requestId === supabaseColumnsRequestSequence) {
        loadingSupabaseColumns.value = false;
      }
    }
  }

  watch(
    () => workflowStore.selectedNode?.id,
    async () => {
      if (workflowStore.selectedNode?.type !== "supabase") {
        supabaseDiscoveredTables.value = [];
        supabaseDiscoveredColumns.value = [];
        return;
      }
      await loadSupabaseTablesForSelectedNode();
      await loadSupabaseColumnsForSelectedNode();
    },
  );

  watch(
    () => [
      workflowStore.selectedNode?.data.credentialId,
      workflowStore.selectedNode?.data.supabaseSchema,
    ],
    async () => {
      if (workflowStore.selectedNode?.type !== "supabase") {
        return;
      }
      await loadSupabaseTablesForSelectedNode();
      await loadSupabaseColumnsForSelectedNode();
    },
    { immediate: true },
  );

  watch(
    () => workflowStore.selectedNode?.data.supabaseTable,
    async () => {
      if (workflowStore.selectedNode?.type !== "supabase") {
        return;
      }
      await loadSupabaseColumnsForSelectedNode();
    },
  );

  function mergeNotionOptions<T extends { id: string }>(current: T[], incoming: T[]): T[] {
    const itemsById = new Map(current.map((item) => [item.id, item]));
    for (const item of incoming) {
      itemsById.set(item.id, item);
    }
    return [...itemsById.values()];
  }

  async function loadNotionDataSourcesForSelectedNode(
    append = false,
  ): Promise<void> {
    const node = workflowStore.selectedNode;
    if (!node || node.type !== "notion") {
      notionDiscoveredDataSources.value = [];
      notionDataSourcesError.value = null;
      notionDataSourcesNextCursor.value = null;
      notionDataSourcesHasMore.value = false;
      return;
    }
    const credentialId = String(node.data.credentialId || "").trim();
    if (!credentialId) {
      notionDiscoveredDataSources.value = [];
      notionDataSourcesError.value = null;
      notionDataSourcesNextCursor.value = null;
      notionDataSourcesHasMore.value = false;
      return;
    }

    const requestId = ++notionDataSourcesRequestSequence;
    loadingNotionDataSources.value = true;
    notionDataSourcesError.value = null;
    try {
      const result = await credentialsApi.listNotionDataSources(
        credentialId,
        notionDataSourceSearch.value.trim() || undefined,
        append ? notionDataSourcesNextCursor.value || undefined : undefined,
      );
      if (
        requestId !== notionDataSourcesRequestSequence ||
        workflowStore.selectedNode?.id !== node.id ||
        String(workflowStore.selectedNode?.data.credentialId || "").trim() !== credentialId
      ) {
        return;
      }
      notionDiscoveredDataSources.value = append
        ? mergeNotionOptions(notionDiscoveredDataSources.value, result.data_sources)
        : result.data_sources;
      notionDataSourcesNextCursor.value = result.next_cursor || null;
      notionDataSourcesHasMore.value = result.has_more;
    } catch (error: unknown) {
      if (requestId === notionDataSourcesRequestSequence) {
        if (!append) {
          notionDiscoveredDataSources.value = [];
        }
        notionDataSourcesError.value =
          (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          "Failed to load Notion data sources.";
      }
    } finally {
      if (requestId === notionDataSourcesRequestSequence) {
        loadingNotionDataSources.value = false;
      }
    }
  }

  async function loadNotionPagesForSelectedNode(append = false): Promise<void> {
    const node = workflowStore.selectedNode;
    if (!node || node.type !== "notion") {
      notionDiscoveredPages.value = [];
      notionPagesError.value = null;
      notionPagesNextCursor.value = null;
      notionPagesHasMore.value = false;
      return;
    }
    const credentialId = String(node.data.credentialId || "").trim();
    if (!credentialId) {
      notionDiscoveredPages.value = [];
      notionPagesError.value = null;
      notionPagesNextCursor.value = null;
      notionPagesHasMore.value = false;
      return;
    }
    const requestId = ++notionPagesRequestSequence;
    loadingNotionPages.value = true;
    notionPagesError.value = null;
    try {
      const result = await credentialsApi.listNotionPages(
        credentialId,
        notionPageSearch.value.trim() || undefined,
        append ? notionPagesNextCursor.value || undefined : undefined,
      );
      if (
        requestId !== notionPagesRequestSequence ||
        workflowStore.selectedNode?.id !== node.id ||
        String(workflowStore.selectedNode?.data.credentialId || "").trim() !== credentialId
      ) {
        return;
      }
      notionDiscoveredPages.value = append
        ? mergeNotionOptions(notionDiscoveredPages.value, result.pages)
        : result.pages;
      notionPagesNextCursor.value = result.next_cursor || null;
      notionPagesHasMore.value = result.has_more;
    } catch (error: unknown) {
      if (requestId === notionPagesRequestSequence) {
        if (!append) {
          notionDiscoveredPages.value = [];
        }
        notionPagesError.value =
          (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          "Failed to load Notion pages.";
      }
    } finally {
      if (requestId === notionPagesRequestSequence) {
        loadingNotionPages.value = false;
      }
    }
  }

  watch(
    () => [
      workflowStore.selectedNode?.id,
      workflowStore.selectedNode?.data.credentialId,
    ],
    async () => {
      if (workflowStore.selectedNode?.type !== "notion") {
        notionDiscoveredDataSources.value = [];
        notionDataSourcesError.value = null;
        notionDiscoveredPages.value = [];
        notionPagesError.value = null;
        return;
      }
      await Promise.all([
        loadNotionDataSourcesForSelectedNode(),
        loadNotionPagesForSelectedNode(),
      ]);
    },
    { immediate: true },
  );

  watch(notionDataSourceSearch, () => {
    if (notionDataSourceSearchTimer) {
      clearTimeout(notionDataSourceSearchTimer);
    }
    notionDataSourceSearchTimer = setTimeout(() => {
      void loadNotionDataSourcesForSelectedNode();
    }, 300);
  });

  watch(notionPageSearch, () => {
    if (notionPageSearchTimer) {
      clearTimeout(notionPageSearchTimer);
    }
    notionPageSearchTimer = setTimeout(() => {
      void loadNotionPagesForSelectedNode();
    }, 300);
  });

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

  function updateExecuteWorkflowId(value: string | undefined): void {
    const workflowId = value || "";
    updateNodeData("executeWorkflowId", workflowId);
    if (!workflowId) {
      updateNodeData("targetWorkflowInputFields", []);
      updateNodeData("targetWorkflowName", "");
      updateNodeData("executeInputMappings", []);
    }
  }

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

  const selectedNodeTypeLabel = computed((): string => {
    const node = selectedNode.value;
    if (!node) {
      return "";
    }
    return NODE_DEFINITIONS[node.type]?.label ?? node.type;
  });

  const isExecuting = computed(() => workflowStore.isExecuting);
  const {
    isActive: isRunPanelFileDragActive,
    reset: resetRunPanelFileDrag,
    onDragEnter: onRunPanelFileDragEnter,
    onDragLeave: onRunPanelFileDragLeave,
    onDragOver: onRunPanelFileDragOver,
    onDrop: onRunPanelFileDrop,
  } = useRunPanelFileDrag(
    computed(
      () =>
        isExecuting.value
        || isGenericWebhookBodyMode.value
        || allInputFields.value.length === 0,
    ),
  );
  const { isRunbookPlaying } = useRunbookPlayer();
  const hasNodes = computed(() => workflowStore.nodes.length > 0);

  function revealRunTabForRunbook(): void {
    if (!isRunbookPlaying.value) return;
    activeTab.value = "config";
  }

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
    discordMessageInputRef.value?.closeExpandDialog();
    discordUsernameInputRef.value?.closeExpandDialog();
    discordAvatarUrlInputRef.value?.closeExpandDialog();
    sendEmailToInputRef.value?.closeExpandDialog();
    sendEmailCcInputRef.value?.closeExpandDialog();
    sendEmailBccInputRef.value?.closeExpandDialog();
    sendEmailSubjectInputRef.value?.closeExpandDialog();
    sendEmailBodyInputRef.value?.closeExpandDialog();
    sendEmailAttachmentsInputRef.value?.closeExpandDialog();
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
    driveFilenameExpressionInputRef.value?.closeExpandDialog();
    driveBase64ContentExpressionInputRef.value?.closeExpandDialog();
    closeAllPlaywrightExpressionDialogs();
    llmSystemInstructionInputRef.value?.closeExpandDialog();
    llmImageExpressionInputRef.value?.closeExpandDialog();
    agentSystemInstructionInputRef.value?.closeExpandDialog();
    agentImageExpressionInputRef.value?.closeExpandDialog();
    for (const input of agentMcpEnvInputRefs.value.values()) {
      input.closeExpandDialog();
    }
    googleSheetsSpreadsheetIdExpressionInputRef.value?.closeExpandDialog();
    googleSheetsSheetNameExpressionInputRef.value?.closeExpandDialog();
    googleSheetsValuesInputRef.value?.closeExpandDialog();
    closeBigQueryExpressionDialogs();
    closeClickhouseExpressionDialogs();
    closeNotionExpressionDialogs();
    closeS3ExpressionDialogs();
    closeMCPCallExpressionDialogs();
    closeChartOutputExpressionDialogs();
    closeCodexExpressionDialogs();
    closeGitHubExpressionDialogs();
    closeSentryExpressionDialogs();
    closeLinearExpressionDialogs();
  }

  const notionExpressionFields = computed(() => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "notion") {
      return [];
    }
    const operation = (n.data.notionOperation as string | undefined) || "";
    return getNotionExpressionFields(operation, {
      dataSourceInputMode: n.data.notionDataSourceInputMode as string | undefined,
      parentPageInputMode: n.data.notionParentPageInputMode as string | undefined,
      appendPosition: n.data.notionAppendPosition as string | undefined,
      afterBlockId: n.data.notionAfterBlockId as string | undefined,
    });
  });

  const notionExpressionFieldCount = computed(
    (): number => notionExpressionFields.value.length,
  );

  function notionExpressionFieldIndex(key: NotionExpressionFieldKey): number {
    const index = notionExpressionFields.value.findIndex((field) => field.key === key);
    return index >= 0 ? index : -1;
  }

  function notionExpressionFieldLabel(key: NotionExpressionFieldKey): string {
    return notionExpressionFields.value.find((field) => field.key === key)?.label ?? "";
  }

  function notionExpressionNavBindings(key: NotionExpressionFieldKey): {
    navigationEnabled: boolean;
    navigationIndex: number;
    navigationTotal: number;
    dialogNodeLabel: string;
    dialogKeyLabel: string;
  } {
    const index = notionExpressionFieldIndex(key);
    return {
      navigationEnabled: notionExpressionFieldCount.value > 1 && index >= 0,
      navigationIndex: index >= 0 ? index : 0,
      navigationTotal: notionExpressionFieldCount.value,
      dialogNodeLabel: selectedNodeEvaluateDialogLabel.value,
      dialogKeyLabel: notionExpressionFieldLabel(key),
    };
  }

  /** Opens the primary expression evaluate dialog for whichever node is currently selected. */
  function notionExpressionInputRefForField(
    field: string | null,
  ): ExpandableFieldRef | null {
    switch (field) {
      case "notionQuery":
        return notionQueryExpressionInputRef.value;
      case "notionPageId":
        return notionPageIdExpressionInputRef.value;
      case "notionDatabaseId":
        return notionDatabaseIdExpressionInputRef.value;
      case "notionDatabase":
        return notionDatabaseExpressionInputRef.value;
      case "notionDataSourceId":
        return notionDataSourceIdExpressionInputRef.value;
      case "notionDataSource":
        return notionDataSourceExpressionInputRef.value;
      case "notionParentPageId":
        return notionParentPageIdExpressionInputRef.value;
      case "notionBlockId":
        return notionBlockIdExpressionInputRef.value;
      case "notionBlock":
        return notionBlockExpressionInputRef.value;
      case "notionProperties":
        return notionPropertiesExpressionInputRef.value;
      case "notionIcon":
        return notionIconExpressionInputRef.value;
      case "notionCover":
        return notionCoverExpressionInputRef.value;
      case "notionChildren":
        return notionChildrenExpressionInputRef.value;
      case "notionFilter":
        return notionFilterExpressionInputRef.value;
      case "notionSort":
        return notionSortExpressionInputRef.value;
      case "notionSorts":
        return notionSortsExpressionInputRef.value;
      case "notionStartCursor":
        return notionStartCursorExpressionInputRef.value;
      case "notionAfterBlockId":
        return notionAfterBlockIdExpressionInputRef.value;
      default:
        return null;
    }
  }

  function resolveNotionExpressionStartIndex(): number {
    const focusField = workflowStore.focusField;
    if (focusField) {
      const index = notionExpressionFieldIndex(focusField as NotionExpressionFieldKey);
      if (index >= 0) {
        return index;
      }
    }
    return 0;
  }

  function openNotionExpressionFieldAtIndex(index: number): boolean {
    const n = selectedNode.value;
    if (!n || n.type !== "notion") {
      return false;
    }
    const field = notionExpressionFields.value[index];
    if (!field) {
      return false;
    }
    currentNotionExpressionFieldIndex.value = index;
    const input = notionExpressionInputRefForField(field.key);
    if (!input) {
      return false;
    }
    input.openExpandDialog();
    return true;
  }

  function closeNotionExpressionDialogs(): void {
    notionQueryExpressionInputRef.value?.closeExpandDialog();
    notionPageIdExpressionInputRef.value?.closeExpandDialog();
    notionDatabaseIdExpressionInputRef.value?.closeExpandDialog();
    notionDatabaseExpressionInputRef.value?.closeExpandDialog();
    notionDataSourceIdExpressionInputRef.value?.closeExpandDialog();
    notionDataSourceExpressionInputRef.value?.closeExpandDialog();
    notionParentPageIdExpressionInputRef.value?.closeExpandDialog();
    notionBlockIdExpressionInputRef.value?.closeExpandDialog();
    notionBlockExpressionInputRef.value?.closeExpandDialog();
    notionPropertiesExpressionInputRef.value?.closeExpandDialog();
    notionIconExpressionInputRef.value?.closeExpandDialog();
    notionCoverExpressionInputRef.value?.closeExpandDialog();
    notionChildrenExpressionInputRef.value?.closeExpandDialog();
    notionFilterExpressionInputRef.value?.closeExpandDialog();
    notionSortExpressionInputRef.value?.closeExpandDialog();
    notionSortsExpressionInputRef.value?.closeExpandDialog();
    notionStartCursorExpressionInputRef.value?.closeExpandDialog();
    notionAfterBlockIdExpressionInputRef.value?.closeExpandDialog();
  }

  function handleNotionExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = notionExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentNotionExpressionFieldIndex.value - 1
        : currentNotionExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeNotionExpressionDialogs();
    currentNotionExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openNotionExpressionFieldAtIndex(newIndex);
    });
  }

  function onNotionRegisterExpressionFieldIndex(index: number): void {
    currentNotionExpressionFieldIndex.value = index;
  }

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
    } else if (nodeType === "chartOutput") {
      currentChartOutputExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        const firstField = chartOutputExpressionFields.value[0];
        if (firstField && chartOutputExpressionInputRefs.value.get(firstField.key)) {
          nextTick(() => openChartOutputExpressionFieldAtIndex(0));
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
    } else if (nodeType === "mcpCall") {
      currentMCPCallExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        if (mcpCallArgumentInputRefs.value.size > 0) {
          nextTick(() => openMCPCallExpressionFieldAtIndex(0));
        } else if (mcpCallConnectionEnvInputRef.value) {
          nextTick(() => mcpCallConnectionEnvInputRef.value?.openExpandDialog());
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
    } else if (nodeType === "discord") {
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        if (discordMessageInputRef.value) {
          nextTick(() => discordMessageInputRef.value?.openExpandDialog());
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "sendEmail") {
      currentSendEmailExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        if (sendEmailToInputRef.value) {
          nextTick(() => openSendEmailExpressionFieldAtIndex(0));
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
    } else if (nodeType === "codex") {
      const startIndex = resolveCodexExpressionStartIndex();
      currentCodexExpressionFieldIndex.value = startIndex;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        const n = workflowStore.selectedNode;
        if (!n || n.type !== "codex") {
          return;
        }
        const field = codexExpressionFields.value[startIndex];
        if (field && codexExpressionInputRefForKey(field.key)) {
          nextTick(() => openCodexExpressionFieldAtIndex(startIndex));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "github") {
      const startIndex = resolveGitHubExpressionStartIndex();
      currentGitHubExpressionFieldIndex.value = startIndex;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        const n = workflowStore.selectedNode;
        if (!n || n.type !== "github") {
          return;
        }
        if (githubExpressionFieldCount.value === 0) {
          return;
        }
        const field = githubExpressionFields.value[startIndex];
        if (field && githubExpressionInputRefForKey(field.key)) {
          nextTick(() => openGitHubExpressionFieldAtIndex(startIndex));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "sentry") {
      const startIndex = resolveSentryExpressionStartIndex();
      currentSentryExpressionFieldIndex.value = startIndex;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        const n = workflowStore.selectedNode;
        if (!n || n.type !== "sentry") {
          return;
        }
        if (sentryExpressionFieldCount.value === 0) {
          return;
        }
        const field = sentryExpressionFields.value[startIndex];
        if (field && sentryExpressionInputRefForKey(field.key)) {
          nextTick(() => openSentryExpressionFieldAtIndex(startIndex));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "linear") {
      const startIndex = resolveLinearExpressionStartIndex();
      currentLinearExpressionFieldIndex.value = startIndex;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        const n = workflowStore.selectedNode;
        if (!n || n.type !== "linear") {
          return;
        }
        if (linearExpressionFieldCount.value === 0) {
          return;
        }
        const field = linearExpressionFields.value[startIndex];
        if (field && linearExpressionInputRefForKey(field.key)) {
          nextTick(() => openLinearExpressionFieldAtIndex(startIndex));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "notion") {
      const startIndex = resolveNotionExpressionStartIndex();
      currentNotionExpressionFieldIndex.value = startIndex;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) {
          return;
        }
        const n = workflowStore.selectedNode;
        if (!n || n.type !== "notion") {
          return;
        }
        if (notionExpressionFieldCount.value === 0) {
          return;
        }
        const field = notionExpressionFields.value[startIndex];
        if (field && notionExpressionInputRefForField(field.key)) {
          nextTick(() => openNotionExpressionFieldAtIndex(startIndex));
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
        } else if (
          ["find", "count"].includes(op) &&
          dataTableFilterExpressionInputRef.value
        ) {
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
    } else if (nodeType === "supabase") {
      currentSupabaseExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        if (supabaseSchemaExpressionInputRef.value) {
          nextTick(() => openSupabaseExpressionFieldAtIndex(0));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "clickhouse") {
      currentClickhouseExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        const n = workflowStore.selectedNode;
        if (!n || n.type !== "clickhouse") return;
        const op = (n.data.clickhouseOperation as string | undefined) || "";
        const firstRef =
          op === "query"
            ? clickhouseQueryExpressionInputRef.value
            : clickhouseTableExpressionInputRef.value;
        if (firstRef) {
          nextTick(() => openClickhouseExpressionFieldAtIndex(0));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "drive") {
      currentDriveExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        const operation = workflowStore.selectedNode?.data.driveOperation;
        const firstRef =
          operation === "save"
            ? driveFilenameExpressionInputRef.value
            : driveFileIdExpressionInputRef.value;
        if (firstRef) {
          nextTick(() => openDriveExpressionFieldAtIndex(0));
        } else {
          setTimeout(() => tryOpenDialog(attempts + 1), 100);
        }
      };
      nextTick(() => tryOpenDialog());
    } else if (nodeType === "s3") {
      currentS3ExpressionFieldIndex.value = 0;
      const tryOpenDialog = (attempts = 0): void => {
        if (attempts > 20) return;
        if (s3BucketExpressionInputRef.value) {
          nextTick(() => openS3ExpressionFieldAtIndex(0));
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
      case "chartOutput":
      case "http":
      case "websocketSend":
      case "llm":
      case "agent":
      case "mcpCall":
      case "slack":
      case "discord":
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
      case "codex":
      case "github":
      case "linear":
      case "throwError":
      case "crawler":
      case "consoleLog":
      case "switch":
      case "loop":
      case "grist":
      case "googleSheets":
      case "bigquery":
      case "supabase":
      case "clickhouse":
      case "dataTable":
      case "drive":
      case "s3":
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

  const sendEmailExpressionFieldRefs = computed(
    (): (ExpandableFieldRef | null)[] => [
      sendEmailToInputRef.value,
      sendEmailCcInputRef.value,
      sendEmailBccInputRef.value,
      sendEmailSubjectInputRef.value,
      sendEmailBodyInputRef.value,
      sendEmailAttachmentsInputRef.value,
    ],
  );

  const sendEmailExpressionFieldCount = computed((): number => 6);

  function openSendEmailExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "sendEmail") {
      return;
    }
    currentSendEmailExpressionFieldIndex.value = index;
    sendEmailExpressionFieldRefs.value[index]?.openExpandDialog();
  }

  function handleSendEmailExpressionFieldNavigate(direction: "prev" | "next"): void {
    const n = selectedNode.value;
    if (!n || n.type !== "sendEmail") {
      return;
    }
    const total = sendEmailExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentSendEmailExpressionFieldIndex.value - 1
        : currentSendEmailExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    for (const inputRef of sendEmailExpressionFieldRefs.value) {
      inputRef?.closeExpandDialog();
    }
    currentSendEmailExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openSendEmailExpressionFieldAtIndex(newIndex);
    });
  }

  function onSendEmailRegisterExpressionFieldIndex(index: number): void {
    currentSendEmailExpressionFieldIndex.value = index;
  }

  function openAgentExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "agent") {
      return;
    }
    currentAgentExpressionFieldIndex.value = index;
    const baseCount = n.data.imageInputEnabled ? 3 : 2;
    if (index === 0) {
      agentSystemInstructionInputRef.value?.openExpandDialog();
    } else if (index === 1) {
      userMessageInputRef.value?.openExpandDialog();
    } else if (index === 2 && n.data.imageInputEnabled) {
      agentImageExpressionInputRef.value?.openExpandDialog();
    } else if (index >= baseCount) {
      const connId = agentMcpEnvConnectionIds.value[index - baseCount];
      if (connId) {
        agentMcpEnvInputRefs.value.get(connId)?.openExpandDialog();
      }
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
    for (const input of agentMcpEnvInputRefs.value.values()) {
      input.closeExpandDialog();
    }
    currentAgentExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openAgentExpressionFieldAtIndex(newIndex);
    });
  }

  function setAgentMCPEnvInputRef(
    connId: string,
    el: unknown,
  ): void {
    if (el) {
      agentMcpEnvInputRefs.value.set(connId, el as ExpandableFieldRef);
    } else {
      agentMcpEnvInputRefs.value.delete(connId);
    }
  }

  function agentMCPEnvExpressionIndex(connId: string): number {
    const n = selectedNode.value;
    const baseCount = n?.type === "agent" && n.data.imageInputEnabled ? 3 : 2;
    const envIndex = agentMcpEnvConnectionIds.value.indexOf(connId);
    return envIndex === -1 ? baseCount : baseCount + envIndex;
  }

  function openMCPCallExpressionFieldAtIndex(index: number): void {
    const key = mcpCallArgumentKeys.value[index];
    if (!key) {
      return;
    }
    currentMCPCallExpressionFieldIndex.value = index;
    mcpCallArgumentInputRefs.value.get(key)?.openExpandDialog();
  }

  function handleMCPCallExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = mcpCallExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentMCPCallExpressionFieldIndex.value - 1
        : currentMCPCallExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeMCPCallExpressionDialogs();
    currentMCPCallExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openMCPCallExpressionFieldAtIndex(newIndex);
    });
  }

  function setMCPCallArgumentInputRef(
    key: string,
    el: unknown,
  ): void {
    if (el) {
      mcpCallArgumentInputRefs.value.set(key, el as ExpandableFieldRef);
    } else {
      mcpCallArgumentInputRefs.value.delete(key);
    }
  }

  function onMCPCallRegisterExpressionFieldIndex(index: number): void {
    currentMCPCallExpressionFieldIndex.value = index;
  }

  function closeMCPCallExpressionDialogs(): void {
    mcpCallConnectionEnvInputRef.value?.closeExpandDialog();
    for (const input of mcpCallArgumentInputRefs.value.values()) {
      input.closeExpandDialog();
    }
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
      currentCodexExpressionFieldIndex.value = 0;
      currentSetMappingIndex.value = 0;
      currentExecuteMappingIndex.value = 0;
      currentGristExpressionFieldIndex.value = 0;
      currentGoogleSheetsExpressionFieldIndex.value = 0;
      currentBigQueryExpressionFieldIndex.value = 0;
      currentRabbitmqSendExpressionFieldIndex.value = 0;
      currentDataTableExpressionFieldIndex.value = 0;
      currentDriveExpressionFieldIndex.value = 0;
      currentS3ExpressionFieldIndex.value = 0;
      currentPlaywrightExpressionFieldIndex.value = 0;
      currentMCPCallExpressionFieldIndex.value = 0;
      currentGitHubExpressionFieldIndex.value = 0;
      currentSentryExpressionFieldIndex.value = 0;
      currentLinearExpressionFieldIndex.value = 0;
      currentNotionExpressionFieldIndex.value = 0;
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

  const clickhouseExpressionFieldCount = computed((): number => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "clickhouse") return 1;
    const op = (n.data.clickhouseOperation as string | undefined) || "";
    if (!op) return 1;
    if (op === "query" || op === "getAll") return 1;
    if (op === "find") return 3; // table, filter, sort
    if (op === "count" || op === "remove" || op === "getById") return 2;
    if (op === "update") return 3; // table, data, filter
    if (op === "insert" || op === "upsert") {
      const mode = (n.data.clickhouseInputMode as string | undefined) || "raw";
      if (mode === "selective") {
        const mappings = (n.data.clickhouseMappings as unknown[]) || [];
        if (loadingClickhouseColumns.value && mappings.length === 0) {
          return 1;
        }
        return 1 + mappings.length;
      }
      return 2; // table + data
    }
    return 1;
  });

  function getClickhouseExpressionInputAtIndex(
    index: number,
  ): ExpandableFieldRef | null {
    const n = selectedNode.value;
    if (!n || n.type !== "clickhouse") return null;
    const op = (n.data.clickhouseOperation as string | undefined) || "";
    if (op === "query") {
      return index === 0 ? clickhouseQueryExpressionInputRef.value : null;
    }
    if (index === 0) {
      return clickhouseTableExpressionInputRef.value;
    }
    if (op === "find") {
      if (index === 1) return clickhouseFilterExpressionInputRef.value;
      if (index === 2) return clickhouseSortExpressionInputRef.value;
      return null;
    }
    if (op === "count" || op === "remove") {
      return index === 1 ? clickhouseFilterExpressionInputRef.value : null;
    }
    if (op === "getById") {
      return index === 1 ? clickhouseRowIdExpressionInputRef.value : null;
    }
    if (op === "update") {
      if (index === 1) return clickhouseDataExpressionInputRef.value;
      if (index === 2) return clickhouseFilterExpressionInputRef.value;
      return null;
    }
    if (op === "insert" || op === "upsert") {
      const mode = (n.data.clickhouseInputMode as string | undefined) || "raw";
      if (mode === "selective") {
        const mapping = clickhouseMappings.value[index - 1];
        return mapping ? (clickhouseMappingInputRefs.value.get(mapping.key) ?? null) : null;
      }
      return index === 1 ? clickhouseDataExpressionInputRef.value : null;
    }
    return null;
  }

  function openClickhouseExpressionFieldAtIndex(index: number): boolean {
    const input = getClickhouseExpressionInputAtIndex(index);
    if (!input) {
      return false;
    }
    currentClickhouseExpressionFieldIndex.value = index;
    input.openExpandDialog();
    return true;
  }

  function closeClickhouseExpressionDialogs(): void {
    clickhouseQueryExpressionInputRef.value?.closeExpandDialog();
    clickhouseTableExpressionInputRef.value?.closeExpandDialog();
    clickhouseFilterExpressionInputRef.value?.closeExpandDialog();
    clickhouseSortExpressionInputRef.value?.closeExpandDialog();
    clickhouseRowIdExpressionInputRef.value?.closeExpandDialog();
    clickhouseDataExpressionInputRef.value?.closeExpandDialog();
    for (const inst of clickhouseMappingInputRefs.value.values()) inst.closeExpandDialog();
  }

  function handleClickhouseExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = clickhouseExpressionFieldCount.value;
    const currentIndex = currentClickhouseExpressionFieldIndex.value;
    const newIndex =
      direction === "prev"
        ? currentIndex - 1
        : currentIndex + 1;
    if (newIndex < 0 || newIndex >= total) return;
    if (!getClickhouseExpressionInputAtIndex(newIndex)) return;
    closeClickhouseExpressionDialogs();
    currentClickhouseExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      if (!openClickhouseExpressionFieldAtIndex(newIndex)) {
        currentClickhouseExpressionFieldIndex.value = currentIndex;
        void nextTick(() => {
          openClickhouseExpressionFieldAtIndex(currentIndex);
        });
      }
    });
  }

  function onClickhouseRegisterExpressionFieldIndex(index: number): void {
    currentClickhouseExpressionFieldIndex.value = index;
  }

  function clickhouseMappingInputRef(
    key: string,
    el: ExpandableFieldRef | null,
  ): void {
    if (!key) return;
    if (el) clickhouseMappingInputRefs.value.set(key, el);
    else clickhouseMappingInputRefs.value.delete(key);
  }

  const clickhouseMappings = computed<Array<{ key: string; value: string }>>(() => {
    if (!selectedNode.value) return [];
    return (
      (selectedNode.value.data.clickhouseMappings as Array<{ key: string; value: string }> | undefined) ||
      []
    );
  });

  function updateClickhouseMappingValue(index: number, value: string): void {
    if (!selectedNode.value) return;
    const current = [...clickhouseMappings.value];
    current[index] = { ...current[index], value };
    updateNodeData("clickhouseMappings", current);
  }

  function switchClickhouseToRaw(): void {
    const mappings = clickhouseMappings.value;
    if (mappings.length > 0) {
      const row: Record<string, string> = {};
      for (const m of mappings) {
        if (m.key) row[m.key] = m.value;
      }
      updateNodeData("clickhouseData", JSON.stringify([row], null, 2));
    }
    updateNodeData("clickhouseInputMode", "raw");
  }

  function clickhouseUsesDiscoveredMappings(): boolean {
    const node = workflowStore.selectedNode;
    if (!node || node.type !== "clickhouse") {
      return false;
    }
    const operation = String(node.data.clickhouseOperation || "");
    const inputMode = String(node.data.clickhouseInputMode || "raw");
    return ["insert", "upsert"].includes(operation) && inputMode === "selective";
  }

  function syncClickhouseMappingsToDiscoveredColumns(columns: ClickHouseColumn[]): void {
    const node = workflowStore.selectedNode;
    if (!node || node.type !== "clickhouse") {
      return;
    }

    const valuesByColumn = new Map(
      clickhouseMappings.value
        .filter((mapping) => mapping.key)
        .map((mapping) => [mapping.key, mapping.value]),
    );
    const nextMappings = columns.map((column) => ({
      key: column.name,
      value: valuesByColumn.get(column.name) ?? "",
    }));
    const currentMappings = clickhouseMappings.value;
    const unchanged =
      currentMappings.length === nextMappings.length &&
      currentMappings.every((mapping, index) => {
        const next = nextMappings[index];
        return mapping.key === next.key && mapping.value === next.value;
      });
    if (!unchanged) {
      updateNodeData("clickhouseMappings", nextMappings);
    }
  }

  function resetClickhouseColumnDiscovery(): void {
    clickhouseColumnsRequestSequence += 1;
    clickhouseDiscoveredColumns.value = [];
    loadingClickhouseColumns.value = false;
  }

  async function loadClickhouseColumnsForSelectedNode(): Promise<void> {
    const node = workflowStore.selectedNode;
    if (!node || node.type !== "clickhouse" || !clickhouseUsesDiscoveredMappings()) {
      resetClickhouseColumnDiscovery();
      return;
    }
    const credentialId = String(node.data.credentialId || "").trim();
    const table = String(node.data.clickhouseTable || "").trim();
    if (!credentialId || !table) {
      resetClickhouseColumnDiscovery();
      syncClickhouseMappingsToDiscoveredColumns([]);
      return;
    }
    const requestId = ++clickhouseColumnsRequestSequence;
    const selectedNodeId = node.id;
    loadingClickhouseColumns.value = true;
    try {
      const result = await credentialsApi.listClickhouseColumns(credentialId, table);
      const currentNode = workflowStore.selectedNode;
      if (
        requestId !== clickhouseColumnsRequestSequence ||
        !currentNode ||
        currentNode.type !== "clickhouse" ||
        currentNode.id !== selectedNodeId ||
        String(currentNode.data.credentialId || "").trim() !== credentialId ||
        String(currentNode.data.clickhouseTable || "").trim() !== table
      ) {
        return;
      }
      const columns = result.columns || [];
      clickhouseDiscoveredColumns.value = columns;
      syncClickhouseMappingsToDiscoveredColumns(columns);
    } catch {
      if (requestId === clickhouseColumnsRequestSequence) {
        clickhouseDiscoveredColumns.value = [];
        syncClickhouseMappingsToDiscoveredColumns([]);
      }
    } finally {
      if (requestId === clickhouseColumnsRequestSequence) {
        loadingClickhouseColumns.value = false;
      }
    }
  }

  watch(
    () => [
      workflowStore.selectedNode?.id,
      workflowStore.selectedNode?.type,
      workflowStore.selectedNode?.data.credentialId,
      workflowStore.selectedNode?.data.clickhouseOperation,
      workflowStore.selectedNode?.data.clickhouseInputMode,
      workflowStore.selectedNode?.data.clickhouseTable,
    ],
    async () => {
      await loadClickhouseColumnsForSelectedNode();
    },
    { immediate: true },
  );

  const supabaseExpressionFieldCount = computed((): number => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "supabase") return 1;
    const op = (n.data.supabaseOperation as string | undefined) || "";
    const rowsMode = (n.data.supabaseRowsInputMode as string | undefined) || "raw";
    const dataMode = (n.data.supabaseDataInputMode as string | undefined) || "raw";
    if (!op) return 2;
    if (op === "select") {
      return 5; // schema, table, select, filter, orderBy
    }
    if (op === "insert") return rowsMode === "auto" ? 2 : 3; // schema, table, rows
    if (op === "upsert") return rowsMode === "auto" ? 3 : 4; // schema, table, rows, onConflict
    if (op === "update") return dataMode === "auto" ? 3 : 4; // schema, table, data, filter
    if (op === "delete") return 3; // schema, table, filter
    return 2;
  });

  function openSupabaseExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "supabase") return;
    currentSupabaseExpressionFieldIndex.value = index;
    const op = (n.data.supabaseOperation as string | undefined) || "";
    if (index === 0) {
      supabaseSchemaExpressionInputRef.value?.openExpandDialog();
      return;
    }
    if (index === 1) {
      supabaseTableExpressionInputRef.value?.openExpandDialog();
      return;
    }
    if (op === "select") {
      if (index === 2) {
        supabaseSelectColumnsExpressionInputRef.value?.openExpandDialog();
        return;
      }
      if (index === 3) {
        supabaseFilterExpressionInputRef.value?.openExpandDialog();
        return;
      }
      if (index === 4) {
        supabaseOrderByExpressionInputRef.value?.openExpandDialog();
      }
      return;
    }
    if (op === "insert" || op === "upsert") {
      const rowsMode = (n.data.supabaseRowsInputMode as string | undefined) || "raw";
      if (rowsMode === "raw" && index === 2) {
        supabaseRowsExpressionInputRef.value?.openExpandDialog();
        return;
      }
      if (op === "upsert" && index === (rowsMode === "raw" ? 3 : 2)) {
        supabaseOnConflictExpressionInputRef.value?.openExpandDialog();
      }
      return;
    }
    if (op === "update") {
      const dataMode = (n.data.supabaseDataInputMode as string | undefined) || "raw";
      if (dataMode === "raw" && index === 2) {
        supabaseDataExpressionInputRef.value?.openExpandDialog();
        return;
      }
      if (index === (dataMode === "raw" ? 3 : 2)) {
        supabaseFilterExpressionInputRef.value?.openExpandDialog();
      }
      return;
    }
    if (op === "delete" && index === 2) {
      supabaseFilterExpressionInputRef.value?.openExpandDialog();
    }
  }

  function closeSupabaseExpressionDialogs(): void {
    supabaseSchemaExpressionInputRef.value?.closeExpandDialog();
    supabaseTableExpressionInputRef.value?.closeExpandDialog();
    supabaseSelectColumnsExpressionInputRef.value?.closeExpandDialog();
    supabaseFilterExpressionInputRef.value?.closeExpandDialog();
    supabaseOrderByExpressionInputRef.value?.closeExpandDialog();
    supabaseRowsExpressionInputRef.value?.closeExpandDialog();
    supabaseOnConflictExpressionInputRef.value?.closeExpandDialog();
    supabaseDataExpressionInputRef.value?.closeExpandDialog();
  }

  function handleSupabaseExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = supabaseExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentSupabaseExpressionFieldIndex.value - 1
        : currentSupabaseExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) return;
    closeSupabaseExpressionDialogs();
    currentSupabaseExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openSupabaseExpressionFieldAtIndex(newIndex);
    });
  }

  function onSupabaseRegisterExpressionFieldIndex(index: number): void {
    currentSupabaseExpressionFieldIndex.value = index;
  }

  const codexExpressionFields = computed<CodexExpressionField[]>(() => {
    if (!workflowStore.selectedNode || workflowStore.selectedNode.type !== "codex") {
      return [];
    }
    return [
      { key: "repositoryUrl", label: "Repository URL" },
      { key: "baseBranch", label: "Base branch" },
      { key: "taskPrompt", label: "Task prompt" },
      { key: "branchName", label: "Branch name" },
      { key: "setupCommand", label: "Setup command" },
    ];
  });

  const codexExpressionFieldCount = computed((): number => codexExpressionFields.value.length);

  const githubExpressionFields = computed(() => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "github") {
      return [];
    }
    const operation = (n.data.githubOperation as string | undefined) || "getRepository";
    return getGitHubExpressionFields(operation);
  });

  const githubExpressionFieldCount = computed((): number => githubExpressionFields.value.length);

  const sentryExpressionFields = computed(() => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "sentry") {
      return [];
    }
    const operation = (n.data.sentryOperation as string | undefined) || "listIssues";
    return getSentryExpressionFields(operation);
  });

  const sentryExpressionFieldCount = computed((): number => sentryExpressionFields.value.length);

  const linearExpressionFields = computed(() => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "linear") {
      return [];
    }
    const operation = (n.data.linearOperation as string | undefined) || "listIssues";
    return getLinearExpressionFields(operation, {
      returnAll: !!n.data.linearReturnAll,
    });
  });

  const linearExpressionFieldCount = computed((): number => linearExpressionFields.value.length);

  const linearPaginatedOperations = new Set([
    "listTeams",
    "listProjects",
    "listIssues",
    "listTeamMembers",
    "listComments",
  ]);

  const linearIssueIdOperations = new Set([
    "getIssue",
    "updateIssue",
    "deleteIssue",
    "addIssueLink",
    "createComment",
    "listComments",
  ]);

  const linearCommentIdOperations = new Set([
    "updateComment",
    "deleteComment",
    "resolveComment",
    "unresolveComment",
  ]);

  function selectedLinearOperation(): string {
    return (workflowStore.selectedNode?.data.linearOperation as string | undefined) || "listIssues";
  }

  function isLinearPaginatedOperation(): boolean {
    return linearPaginatedOperations.has(selectedLinearOperation());
  }

  function isLinearIssueIdOperation(): boolean {
    return linearIssueIdOperations.has(selectedLinearOperation());
  }

  function isLinearCommentIdOperation(): boolean {
    return linearCommentIdOperations.has(selectedLinearOperation());
  }

  function linearExpressionFieldIndex(key: LinearExpressionFieldKey): number {
    const index = linearExpressionFields.value.findIndex((field) => field.key === key);
    return index >= 0 ? index : -1;
  }

  function linearExpressionFieldLabel(key: LinearExpressionFieldKey): string {
    return linearExpressionFields.value.find((field) => field.key === key)?.label ?? "";
  }

  function linearExpressionNavBindings(key: LinearExpressionFieldKey): {
    navigationEnabled: boolean;
    navigationIndex: number;
    navigationTotal: number;
    dialogNodeLabel: string;
    dialogKeyLabel: string;
  } {
    const index = linearExpressionFieldIndex(key);
    return {
      navigationEnabled: linearExpressionFieldCount.value > 1 && index >= 0,
      navigationIndex: index >= 0 ? index : 0,
      navigationTotal: linearExpressionFieldCount.value,
      dialogNodeLabel: selectedNodeEvaluateDialogLabel.value,
      dialogKeyLabel: linearExpressionFieldLabel(key),
    };
  }

  function linearExpressionInputRefForKey(
    key: LinearExpressionFieldKey,
  ): ExpandableFieldRef | null {
    switch (key) {
      case "linearLimit":
        return linearLimitExpressionInputRef.value;
      case "linearAfter":
        return linearAfterExpressionInputRef.value;
      case "linearTeamId":
        return linearTeamIdExpressionInputRef.value;
      case "linearProjectId":
        return linearProjectIdExpressionInputRef.value;
      case "linearIssueId":
        return linearIssueIdExpressionInputRef.value;
      case "linearTitle":
        return linearTitleExpressionInputRef.value;
      case "linearDescription":
        return linearDescriptionExpressionInputRef.value;
      case "linearStateId":
        return linearStateIdExpressionInputRef.value;
      case "linearIssueLinkUrl":
        return linearIssueLinkUrlExpressionInputRef.value;
      case "linearAssigneeId":
        return linearAssigneeIdExpressionInputRef.value;
      case "linearPriority":
        return linearPriorityExpressionInputRef.value;
      case "linearCommentId":
        return linearCommentIdExpressionInputRef.value;
      case "linearCommentBody":
        return linearCommentBodyExpressionInputRef.value;
      case "linearParentCommentId":
        return linearParentCommentIdExpressionInputRef.value;
      default:
        return null;
    }
  }

  function resolveLinearExpressionStartIndex(): number {
    const focusField = workflowStore.focusField;
    if (focusField) {
      const index = linearExpressionFieldIndex(focusField as LinearExpressionFieldKey);
      if (index >= 0) {
        return index;
      }
    }
    return 0;
  }

  function openLinearExpressionFieldAtIndex(index: number): boolean {
    const n = selectedNode.value;
    if (!n || n.type !== "linear") {
      return false;
    }
    const field = linearExpressionFields.value[index];
    if (!field) {
      return false;
    }
    currentLinearExpressionFieldIndex.value = index;
    const input = linearExpressionInputRefForKey(field.key);
    if (!input) {
      return false;
    }
    input.openExpandDialog();
    return true;
  }

  function closeLinearExpressionDialogs(): void {
    linearLimitExpressionInputRef.value?.closeExpandDialog();
    linearAfterExpressionInputRef.value?.closeExpandDialog();
    linearTeamIdExpressionInputRef.value?.closeExpandDialog();
    linearProjectIdExpressionInputRef.value?.closeExpandDialog();
    linearIssueIdExpressionInputRef.value?.closeExpandDialog();
    linearTitleExpressionInputRef.value?.closeExpandDialog();
    linearDescriptionExpressionInputRef.value?.closeExpandDialog();
    linearStateIdExpressionInputRef.value?.closeExpandDialog();
    linearIssueLinkUrlExpressionInputRef.value?.closeExpandDialog();
    linearAssigneeIdExpressionInputRef.value?.closeExpandDialog();
    linearPriorityExpressionInputRef.value?.closeExpandDialog();
    linearCommentIdExpressionInputRef.value?.closeExpandDialog();
    linearCommentBodyExpressionInputRef.value?.closeExpandDialog();
    linearParentCommentIdExpressionInputRef.value?.closeExpandDialog();
  }

  function handleLinearExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = linearExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentLinearExpressionFieldIndex.value - 1
        : currentLinearExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeLinearExpressionDialogs();
    currentLinearExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openLinearExpressionFieldAtIndex(newIndex);
    });
  }

  function onLinearRegisterExpressionFieldIndex(index: number): void {
    currentLinearExpressionFieldIndex.value = index;
  }

  function codexExpressionFieldIndex(key: CodexExpressionFieldKey): number {
    const index = codexExpressionFields.value.findIndex((field) => field.key === key);
    return index >= 0 ? index : -1;
  }

  function codexExpressionFieldLabel(key: CodexExpressionFieldKey): string {
    return codexExpressionFields.value.find((field) => field.key === key)?.label ?? "";
  }

  function codexExpressionNavBindings(key: CodexExpressionFieldKey): {
    navigationEnabled: boolean;
    navigationIndex: number;
    navigationTotal: number;
    dialogNodeLabel: string;
    dialogKeyLabel: string;
  } {
    const index = codexExpressionFieldIndex(key);
    return {
      navigationEnabled: codexExpressionFieldCount.value > 1 && index >= 0,
      navigationIndex: index >= 0 ? index : 0,
      navigationTotal: codexExpressionFieldCount.value,
      dialogNodeLabel: selectedNodeEvaluateDialogLabel.value,
      dialogKeyLabel: codexExpressionFieldLabel(key),
    };
  }

  function codexExpressionInputRefForKey(
    key: CodexExpressionFieldKey,
  ): ExpandableFieldRef | null {
    switch (key) {
      case "repositoryUrl":
        return codexRepositoryUrlExpressionInputRef.value;
      case "baseBranch":
        return codexBaseBranchExpressionInputRef.value;
      case "taskPrompt":
        return codexTaskPromptExpressionInputRef.value;
      case "branchName":
        return codexBranchNameExpressionInputRef.value;
      case "setupCommand":
        return codexSetupCommandExpressionInputRef.value;
      default:
        return null;
    }
  }

  function resolveCodexExpressionStartIndex(): number {
    const focusField = workflowStore.focusField;
    if (focusField) {
      const index = codexExpressionFieldIndex(focusField as CodexExpressionFieldKey);
      if (index >= 0) {
        return index;
      }
    }
    return 2;
  }

  function openCodexExpressionFieldAtIndex(index: number): boolean {
    const n = selectedNode.value;
    if (!n || n.type !== "codex") {
      return false;
    }
    const field = codexExpressionFields.value[index];
    if (!field) {
      return false;
    }
    currentCodexExpressionFieldIndex.value = index;
    const input = codexExpressionInputRefForKey(field.key);
    if (!input) {
      return false;
    }
    input.openExpandDialog();
    return true;
  }

  function closeCodexExpressionDialogs(): void {
    codexRepositoryUrlExpressionInputRef.value?.closeExpandDialog();
    codexBaseBranchExpressionInputRef.value?.closeExpandDialog();
    codexTaskPromptExpressionInputRef.value?.closeExpandDialog();
    codexBranchNameExpressionInputRef.value?.closeExpandDialog();
    codexSetupCommandExpressionInputRef.value?.closeExpandDialog();
  }

  function handleCodexExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = codexExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentCodexExpressionFieldIndex.value - 1
        : currentCodexExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeCodexExpressionDialogs();
    currentCodexExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openCodexExpressionFieldAtIndex(newIndex);
    });
  }

  function onCodexRegisterExpressionFieldIndex(index: number): void {
    currentCodexExpressionFieldIndex.value = index;
  }

  function githubExpressionFieldIndex(key: GitHubExpressionFieldKey): number {
    const index = githubExpressionFields.value.findIndex((field) => field.key === key);
    return index >= 0 ? index : -1;
  }

  function githubExpressionFieldLabel(key: GitHubExpressionFieldKey): string {
    return githubExpressionFields.value.find((field) => field.key === key)?.label ?? "";
  }

  function githubExpressionNavBindings(key: GitHubExpressionFieldKey): {
    navigationEnabled: boolean;
    navigationIndex: number;
    navigationTotal: number;
    dialogNodeLabel: string;
    dialogKeyLabel: string;
  } {
    const index = githubExpressionFieldIndex(key);
    return {
      navigationEnabled: githubExpressionFieldCount.value > 1 && index >= 0,
      navigationIndex: index >= 0 ? index : 0,
      navigationTotal: githubExpressionFieldCount.value,
      dialogNodeLabel: selectedNodeEvaluateDialogLabel.value,
      dialogKeyLabel: githubExpressionFieldLabel(key),
    };
  }

  function githubExpressionInputRefForKey(
    key: GitHubExpressionFieldKey,
  ): ExpandableFieldRef | null {
    switch (key) {
      case "githubOwner":
        return githubOwnerExpressionInputRef.value;
      case "githubRepo":
        return githubRepoExpressionInputRef.value;
      case "githubOrganization":
        return githubOrganizationExpressionInputRef.value;
      case "githubInviteEmail":
        return githubInviteEmailExpressionInputRef.value;
      case "githubIssueNumber":
        return githubIssueNumberExpressionInputRef.value;
      case "githubAssignee":
        return githubAssigneeExpressionInputRef.value;
      case "githubCreator":
        return githubCreatorExpressionInputRef.value;
      case "githubMentioned":
        return githubMentionedExpressionInputRef.value;
      case "githubLabelsFilter":
        return githubLabelsFilterExpressionInputRef.value;
      case "githubSince":
        return githubSinceExpressionInputRef.value;
      case "githubTitle":
        return githubTitleExpressionInputRef.value;
      case "githubBody":
        return githubBodyExpressionInputRef.value;
      case "githubCommentBody":
        return githubCommentBodyExpressionInputRef.value;
      case "githubLabels":
        return githubLabelsExpressionInputRef.value;
      case "githubAssignees":
        return githubAssigneesExpressionInputRef.value;
      case "githubHead":
        return githubHeadExpressionInputRef.value;
      case "githubBase":
        return githubBaseExpressionInputRef.value;
      case "githubPullRequestNumber":
        return githubPullRequestNumberExpressionInputRef.value;
      case "githubReviewId":
        return githubReviewIdExpressionInputRef.value;
      case "githubReviewBody":
        return githubReviewBodyExpressionInputRef.value;
      case "githubCommitId":
        return githubCommitIdExpressionInputRef.value;
      case "githubReleaseId":
        return githubReleaseIdExpressionInputRef.value;
      case "githubTagName":
        return githubTagNameExpressionInputRef.value;
      case "githubBranch":
        return githubBranchExpressionInputRef.value;
      case "githubWorkflowId":
        return githubWorkflowIdExpressionInputRef.value;
      case "githubWorkflowInputs":
        return githubWorkflowInputsExpressionInputRef.value;
      case "githubFilePath":
        return githubFilePathExpressionInputRef.value;
      case "githubCommitMessage":
        return githubCommitMessageExpressionInputRef.value;
      case "githubFileContent":
        return githubFileContentExpressionInputRef.value;
      default:
        return null;
    }
  }

  function resolveGitHubExpressionStartIndex(): number {
    const focusField = workflowStore.focusField;
    if (focusField) {
      const index = githubExpressionFieldIndex(focusField as GitHubExpressionFieldKey);
      if (index >= 0) {
        return index;
      }
    }
    return 0;
  }

  function openGitHubExpressionFieldAtIndex(index: number): boolean {
    const n = selectedNode.value;
    if (!n || n.type !== "github") {
      return false;
    }
    const field = githubExpressionFields.value[index];
    if (!field) {
      return false;
    }
    currentGitHubExpressionFieldIndex.value = index;
    const input = githubExpressionInputRefForKey(field.key);
    if (!input) {
      return false;
    }
    input.openExpandDialog();
    return true;
  }

  function closeGitHubExpressionDialogs(): void {
    githubOwnerExpressionInputRef.value?.closeExpandDialog();
    githubRepoExpressionInputRef.value?.closeExpandDialog();
    githubOrganizationExpressionInputRef.value?.closeExpandDialog();
    githubInviteEmailExpressionInputRef.value?.closeExpandDialog();
    githubIssueNumberExpressionInputRef.value?.closeExpandDialog();
    githubAssigneeExpressionInputRef.value?.closeExpandDialog();
    githubCreatorExpressionInputRef.value?.closeExpandDialog();
    githubMentionedExpressionInputRef.value?.closeExpandDialog();
    githubLabelsFilterExpressionInputRef.value?.closeExpandDialog();
    githubSinceExpressionInputRef.value?.closeExpandDialog();
    githubTitleExpressionInputRef.value?.closeExpandDialog();
    githubBodyExpressionInputRef.value?.closeExpandDialog();
    githubCommentBodyExpressionInputRef.value?.closeExpandDialog();
    githubLabelsExpressionInputRef.value?.closeExpandDialog();
    githubAssigneesExpressionInputRef.value?.closeExpandDialog();
    githubHeadExpressionInputRef.value?.closeExpandDialog();
    githubBaseExpressionInputRef.value?.closeExpandDialog();
    githubPullRequestNumberExpressionInputRef.value?.closeExpandDialog();
    githubReviewIdExpressionInputRef.value?.closeExpandDialog();
    githubReviewBodyExpressionInputRef.value?.closeExpandDialog();
    githubCommitIdExpressionInputRef.value?.closeExpandDialog();
    githubReleaseIdExpressionInputRef.value?.closeExpandDialog();
    githubTagNameExpressionInputRef.value?.closeExpandDialog();
    githubBranchExpressionInputRef.value?.closeExpandDialog();
    githubWorkflowIdExpressionInputRef.value?.closeExpandDialog();
    githubWorkflowInputsExpressionInputRef.value?.closeExpandDialog();
    githubFilePathExpressionInputRef.value?.closeExpandDialog();
    githubCommitMessageExpressionInputRef.value?.closeExpandDialog();
    githubFileContentExpressionInputRef.value?.closeExpandDialog();
  }

  function handleGitHubExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = githubExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentGitHubExpressionFieldIndex.value - 1
        : currentGitHubExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeGitHubExpressionDialogs();
    currentGitHubExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openGitHubExpressionFieldAtIndex(newIndex);
    });
  }

  function onGitHubRegisterExpressionFieldIndex(index: number): void {
    currentGitHubExpressionFieldIndex.value = index;
  }

  function sentryExpressionFieldIndex(key: SentryExpressionFieldKey): number {
    const index = sentryExpressionFields.value.findIndex((field) => field.key === key);
    return index >= 0 ? index : -1;
  }

  function sentryExpressionFieldLabel(key: SentryExpressionFieldKey): string {
    return sentryExpressionFields.value.find((field) => field.key === key)?.label ?? "";
  }

  function sentryExpressionNavBindings(key: SentryExpressionFieldKey): {
    navigationEnabled: boolean;
    navigationIndex: number;
    navigationTotal: number;
    dialogNodeLabel: string;
    dialogKeyLabel: string;
  } {
    const index = sentryExpressionFieldIndex(key);
    return {
      navigationEnabled: sentryExpressionFieldCount.value > 1 && index >= 0,
      navigationIndex: index >= 0 ? index : 0,
      navigationTotal: sentryExpressionFieldCount.value,
      dialogNodeLabel: selectedNodeEvaluateDialogLabel.value,
      dialogKeyLabel: sentryExpressionFieldLabel(key),
    };
  }

  function sentryExpressionInputRefForKey(
    key: SentryExpressionFieldKey,
  ): ExpandableFieldRef | null {
    switch (key) {
      case "sentryOrganizationSlug":
        return sentryOrganizationSlugExpressionInputRef.value;
      case "sentryProjectSlug":
        return sentryProjectSlugExpressionInputRef.value;
      case "sentryTeamSlug":
        return sentryTeamSlugExpressionInputRef.value;
      case "sentryIssueId":
        return sentryIssueIdExpressionInputRef.value;
      case "sentryEventId":
        return sentryEventIdExpressionInputRef.value;
      case "sentryReleaseVersion":
        return sentryReleaseVersionExpressionInputRef.value;
      case "sentryName":
        return sentryNameExpressionInputRef.value;
      case "sentrySlug":
        return sentrySlugExpressionInputRef.value;
      case "sentryPlatform":
        return sentryPlatformExpressionInputRef.value;
      case "sentryStatus":
        return sentryStatusExpressionInputRef.value;
      case "sentryAssignedTo":
        return sentryAssignedToExpressionInputRef.value;
      case "sentryQuery":
        return sentryQueryExpressionInputRef.value;
      case "sentryStatsPeriod":
        return sentryStatsPeriodExpressionInputRef.value;
      case "sentryLimit":
        return sentryLimitExpressionInputRef.value;
      case "sentryReleaseProjects":
        return sentryReleaseProjectsExpressionInputRef.value;
      case "sentryReleaseRefs":
        return sentryReleaseRefsExpressionInputRef.value;
      case "sentryPayload":
        return sentryPayloadExpressionInputRef.value;
      default:
        return null;
    }
  }

  function resolveSentryExpressionStartIndex(): number {
    const focusField = workflowStore.focusField;
    if (focusField) {
      const index = sentryExpressionFieldIndex(focusField as SentryExpressionFieldKey);
      if (index >= 0) {
        return index;
      }
    }
    return 0;
  }

  function openSentryExpressionFieldAtIndex(index: number): boolean {
    const n = selectedNode.value;
    if (!n || n.type !== "sentry") {
      return false;
    }
    const field = sentryExpressionFields.value[index];
    if (!field) {
      return false;
    }
    currentSentryExpressionFieldIndex.value = index;
    const input = sentryExpressionInputRefForKey(field.key);
    if (!input) {
      return false;
    }
    input.openExpandDialog();
    return true;
  }

  function closeSentryExpressionDialogs(): void {
    sentryOrganizationSlugExpressionInputRef.value?.closeExpandDialog();
    sentryProjectSlugExpressionInputRef.value?.closeExpandDialog();
    sentryTeamSlugExpressionInputRef.value?.closeExpandDialog();
    sentryIssueIdExpressionInputRef.value?.closeExpandDialog();
    sentryEventIdExpressionInputRef.value?.closeExpandDialog();
    sentryReleaseVersionExpressionInputRef.value?.closeExpandDialog();
    sentryNameExpressionInputRef.value?.closeExpandDialog();
    sentrySlugExpressionInputRef.value?.closeExpandDialog();
    sentryPlatformExpressionInputRef.value?.closeExpandDialog();
    sentryStatusExpressionInputRef.value?.closeExpandDialog();
    sentryAssignedToExpressionInputRef.value?.closeExpandDialog();
    sentryQueryExpressionInputRef.value?.closeExpandDialog();
    sentryStatsPeriodExpressionInputRef.value?.closeExpandDialog();
    sentryLimitExpressionInputRef.value?.closeExpandDialog();
    sentryReleaseProjectsExpressionInputRef.value?.closeExpandDialog();
    sentryReleaseRefsExpressionInputRef.value?.closeExpandDialog();
    sentryPayloadExpressionInputRef.value?.closeExpandDialog();
  }

  function handleSentryExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = sentryExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentSentryExpressionFieldIndex.value - 1
        : currentSentryExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeSentryExpressionDialogs();
    currentSentryExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openSentryExpressionFieldAtIndex(newIndex);
    });
  }

  function onSentryRegisterExpressionFieldIndex(index: number): void {
    currentSentryExpressionFieldIndex.value = index;
  }

  function bqMappingInputRef(index: number, el: ExpandableFieldRef | null): void {
    if (el) {
      bqMappingInputRefs.value.set(index, el);
    } else {
      bqMappingInputRefs.value.delete(index);
    }
  }

  const s3ExpressionFieldCount = computed((): number => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "s3") return 1;
    const op = (n.data.s3Operation as string | undefined) || "";
    if (op === "listBuckets") {
      return 0;
    }
    if (op === "createBucket" || op === "deleteBucket") {
      return 1;
    }
    if (op === "createFolder" || op === "deleteFolder" || op === "getAllFolder") {
      return 2;
    }
    if (op === "listObjects") {
      return 3;
    }
    if (op === "copyObject") {
      return 4;
    }
    if (op === "putObject") {
      return 4;
    }
    return 2;
  });

  function openS3ExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "s3") return;
    currentS3ExpressionFieldIndex.value = index;
    const op = (n.data.s3Operation as string | undefined) || "";
    if (op === "listBuckets") {
      return;
    }
    if (index === 0) {
      s3BucketExpressionInputRef.value?.openExpandDialog();
      return;
    }
    if (op === "listObjects") {
      if (index === 2) {
        s3ContinuationTokenExpressionInputRef.value?.openExpandDialog();
        return;
      }
      s3PrefixExpressionInputRef.value?.openExpandDialog();
      return;
    }
    if (op === "copyObject") {
      if (index === 1) {
        s3SourceBucketExpressionInputRef.value?.openExpandDialog();
        return;
      }
      if (index === 2) {
        s3SourceKeyExpressionInputRef.value?.openExpandDialog();
        return;
      }
      s3KeyExpressionInputRef.value?.openExpandDialog();
      return;
    }
    if (index === 1) {
      s3KeyExpressionInputRef.value?.openExpandDialog();
      return;
    }
    if (index === 2) {
      s3BodyExpressionInputRef.value?.openExpandDialog();
      return;
    }
    s3BodyExpressionInputRef.value?.openExpandDialog();
  }

  function closeS3ExpressionDialogs(): void {
    s3BucketExpressionInputRef.value?.closeExpandDialog();
    s3KeyExpressionInputRef.value?.closeExpandDialog();
    s3SourceBucketExpressionInputRef.value?.closeExpandDialog();
    s3SourceKeyExpressionInputRef.value?.closeExpandDialog();
    s3PrefixExpressionInputRef.value?.closeExpandDialog();
    s3ContinuationTokenExpressionInputRef.value?.closeExpandDialog();
    s3BodyExpressionInputRef.value?.closeExpandDialog();
  }

  function handleS3ExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = s3ExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentS3ExpressionFieldIndex.value - 1
        : currentS3ExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) return;
    closeS3ExpressionDialogs();
    currentS3ExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openS3ExpressionFieldAtIndex(newIndex);
    });
  }

  function onS3RegisterExpressionFieldIndex(index: number): void {
    currentS3ExpressionFieldIndex.value = index;
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
    const inst = el as ExpandableFieldRef | null;
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
    if (op === "count") {
      dataTableFilterExpressionInputRef.value?.openExpandDialog();
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
    if (n.data.driveOperation === "getAll") {
      return 0;
    }
    if (n.data.driveOperation === "setPassword" || n.data.driveOperation === "save") {
      return 2;
    }
    return 1;
  });

  const isDriveFileIdAgentProvided = computed((): boolean => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "drive") {
      return false;
    }
    return (n.data.agentProvidedFields ?? []).includes("driveFileId");
  });

  function openDriveExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "drive") {
      return;
    }
    if (n.data.driveOperation === "getAll") {
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
    if (n.data.driveOperation === "save") {
      if (index === 0) {
        driveFilenameExpressionInputRef.value?.openExpandDialog();
      } else {
        driveBase64ContentExpressionInputRef.value?.openExpandDialog();
      }
      return;
    }
    driveFileIdExpressionInputRef.value?.openExpandDialog();
  }

  function handleDriveExpressionFieldNavigate(direction: "prev" | "next"): void {
    const n = selectedNode.value;
    if (
      !n
      || n.type !== "drive"
      || (n.data.driveOperation !== "setPassword" && n.data.driveOperation !== "save")
    ) {
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
    driveFilenameExpressionInputRef.value?.closeExpandDialog();
    driveBase64ContentExpressionInputRef.value?.closeExpandDialog();
    currentDriveExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openDriveExpressionFieldAtIndex(newIndex);
    });
  }

  function onDriveRegisterExpressionFieldIndex(index: number): void {
    currentDriveExpressionFieldIndex.value = index;
  }

  const chartOutputExpressionFields = computed<ChartOutputExpressionField[]>(() => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "chartOutput") {
      return [];
    }
    const chartType = n.data.chartType || "bar";
    const fields: ChartOutputExpressionField[] = [];

    if (chartType === "text") {
      fields.push(
        { key: "text", label: "Text (markdown)" },
        { key: "valueField", label: "Value field" },
      );
    }

    fields.push({ key: "dataPath", label: "Data path" });

    if (["bar", "line", "area", "pie", "proportion", "barGauge"].includes(chartType)) {
      fields.push({ key: "labelField", label: "Label field" });
    }

    if (["bar", "line", "area", "pie", "numeric", "gauge", "proportion", "barGauge"].includes(chartType)) {
      fields.push({ key: "valueField", label: "Value field" });
    }

    if (chartType === "scatter") {
      fields.push(
        { key: "xField", label: "X field" },
        { key: "yField", label: "Y field" },
      );
    }

    if (chartType === "gauge") {
      fields.push(
        { key: "min", label: "Min" },
        { key: "max", label: "Max" },
      );
    }

    if (chartType === "barGauge") {
      fields.push({ key: "max", label: "Max" });
    }

    if (["numeric", "gauge", "barGauge"].includes(chartType)) {
      fields.push({ key: "unit", label: "Unit" });
    }

    fields.push({ key: "title", label: "Title" });
    fields.push({ key: "url", label: "Website URL" });
    return fields;
  });

  const chartOutputExpressionFieldCount = computed((): number => {
    return chartOutputExpressionFields.value.length;
  });

  function chartOutputExpressionFieldIndex(key: ChartOutputExpressionFieldKey): number {
    const index = chartOutputExpressionFields.value.findIndex((field) => field.key === key);
    return index >= 0 ? index : 0;
  }

  function setChartOutputExpressionInputRef(
    key: ChartOutputExpressionFieldKey,
    el: unknown,
  ): void {
    if (el) {
      chartOutputExpressionInputRefs.value.set(key, el as ExpandableFieldRef);
    } else {
      chartOutputExpressionInputRefs.value.delete(key);
    }
  }

  function openChartOutputExpressionFieldAtIndex(index: number): void {
    const n = selectedNode.value;
    if (!n || n.type !== "chartOutput") {
      return;
    }
    const field = chartOutputExpressionFields.value[index];
    if (!field) {
      return;
    }
    currentChartOutputExpressionFieldIndex.value = index;
    chartOutputExpressionInputRefs.value.get(field.key)?.openExpandDialog();
  }

  function closeChartOutputExpressionDialogs(): void {
    for (const input of chartOutputExpressionInputRefs.value.values()) {
      input.closeExpandDialog();
    }
  }

  function handleChartOutputExpressionFieldNavigate(direction: "prev" | "next"): void {
    const total = chartOutputExpressionFieldCount.value;
    const newIndex =
      direction === "prev"
        ? currentChartOutputExpressionFieldIndex.value - 1
        : currentChartOutputExpressionFieldIndex.value + 1;
    if (newIndex < 0 || newIndex >= total) {
      return;
    }
    closeChartOutputExpressionDialogs();
    currentChartOutputExpressionFieldIndex.value = newIndex;
    nextTick(() => {
      openChartOutputExpressionFieldAtIndex(newIndex);
    });
  }

  function onChartOutputRegisterExpressionFieldIndex(index: number): void {
    currentChartOutputExpressionFieldIndex.value = index;
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
        const shouldOpenExpand = !workflowStore.skipPrimaryExpandOnNextPropertiesOpen;
        if (activeTab.value !== "properties") {
          activeTab.value = "properties";
        }
        workflowStore.clearSkipPrimaryExpandOnNextPropertiesOpen();
        workflowStore.propertiesPanelOpen = false;
        if (shouldOpenExpand) {
          nextTick(() => openPrimaryExpandDialogForSelectedNode());
        }
      }
    },
    { immediate: true },
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

  const discordCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "discord"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      discordCredentials.value,
      selectedCredentialId,
      "Select Discord credential...",
      "Shared Discord credential (from owner)",
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
    const node = selectedNode.value;
    const dbType =
      node && node.type === "rag"
        ? (node.data.dbType as string | undefined) || "qdrant"
        : "qdrant";
    return [
      { value: "", label: "Select a vector store" },
      ...vectorStores.value
        .filter((s) => s.backend === dbType)
        .map((s) => ({
          value: s.id,
          label: s.name,
        })),
    ];
  });

  const ragDbTypeOptions = [
    { value: "qdrant", label: "Qdrant" },
    { value: "pgvector", label: "Postgres (pgvector)" },
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

  const codexCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "codex"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      codexCredentials.value,
      selectedCredentialId,
      "Select Codex credential...",
      "Shared Codex credential (from owner)",
    );
  });

  const codexGithubCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "codex"
        ? (node.data.githubCredentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      githubCredentials.value,
      selectedCredentialId,
      "Select GitHub credential...",
      "Shared GitHub credential (from owner)",
    );
  });

  const codexPublishModeOptions = [
    { value: "diff_only", label: "Diff only" },
    { value: "draft_pr", label: "Draft PR" },
    { value: "open_pr", label: "Open PR" },
    { value: "commit_push", label: "Commit & push" },
    { value: "direct_commit", label: "Direct commit" },
    { value: "update_existing_pr", label: "Update existing PR" },
    { value: "patch_artifact", label: "Patch artifact" },
  ];

  const codexPublishModeDescriptions: Record<string, string> = {
    diff_only: "Edits files locally and returns the patch and changed files. Nothing is pushed.",
    draft_pr: "Commits to the branch, pushes it, and opens a draft pull request.",
    open_pr: "Commits to the branch, pushes it, and opens a review-ready (non-draft) pull request.",
    commit_push: "Commits to the branch and pushes it, without opening a pull request.",
    direct_commit: "Commits and pushes straight to the base branch (no separate branch or PR).",
    update_existing_pr:
      "Adds a commit to the existing branch/PR; opens one if none exists yet.",
    patch_artifact: "Saves the diff as a downloadable file and returns a patchUrl (nothing pushed).",
  };

  const githubCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "github"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      githubCredentials.value,
      selectedCredentialId,
      "Select GitHub credential...",
      "Shared GitHub credential (from owner)",
    );
  });

  const linearCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "linear"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      linearCredentials.value,
      selectedCredentialId,
      "Select Linear credential...",
      "Shared Linear credential (from owner)",
    );
  });

  const githubStateOptions = [
    { value: "open", label: "Open" },
    { value: "closed", label: "Closed" },
    { value: "all", label: "All" },
  ];

  const githubIssueSortOptions = [
    { value: "", label: "Default" },
    { value: "created", label: "Created" },
    { value: "updated", label: "Updated" },
    { value: "comments", label: "Comments" },
  ];

  const githubPullRequestSortOptions = [
    { value: "", label: "Default" },
    { value: "created", label: "Created" },
    { value: "updated", label: "Updated" },
    { value: "popularity", label: "Popularity" },
    { value: "long-running", label: "Long-running" },
  ];

  const githubDirectionOptions = [
    { value: "", label: "Default" },
    { value: "asc", label: "Ascending" },
    { value: "desc", label: "Descending" },
  ];

  const githubUpdateIssueStateOptions = [
    { value: "", label: "Don't change" },
    { value: "open", label: "Open" },
    { value: "closed", label: "Closed" },
  ];

  const githubIssueStateReasonOptions = [
    { value: "", label: "Don't change" },
    { value: "completed", label: "Completed" },
    { value: "not_planned", label: "Not Planned" },
    { value: "duplicate", label: "Duplicate" },
    { value: "reopened", label: "Reopened" },
  ];

  const githubLockReasonOptions = [
    { value: "", label: "No reason" },
    { value: "off-topic", label: "Off-topic" },
    { value: "too heated", label: "Too heated" },
    { value: "resolved", label: "Resolved" },
    { value: "spam", label: "Spam" },
  ];

  const githubReviewEventOptions = [
    { value: "APPROVE", label: "Approve" },
    { value: "REQUEST_CHANGES", label: "Request Changes" },
    { value: "COMMENT", label: "Comment" },
    { value: "PENDING", label: "Pending" },
  ];

  const githubRepoOptionalOperations = new Set([
    "listOrganizationRepositories",
    "listUserRepositories",
    "getUserRepositories",
    "getUserIssues",
    "inviteUser",
  ]);

  const githubOwnerOptionalOperations = new Set(["getUserIssues", "inviteUser"]);

  const githubPerPageOperations = new Set([
    "listIssues",
    "getRepositoryIssues",
    "getUserIssues",
    "listPullRequests",
    "getRepositoryPullRequests",
    "listReviews",
    "listReleases",
    "listWorkflows",
    "listOrganizationRepositories",
    "listUserRepositories",
    "getUserRepositories",
  ]);

  function isGitHubRepoRequired(operation: string | undefined): boolean {
    return !githubRepoOptionalOperations.has(operation || "");
  }

  function isGitHubOwnerRequired(operation: string | undefined): boolean {
    return !githubOwnerOptionalOperations.has(operation || "");
  }

  function usesGitHubPerPage(operation: string | undefined): boolean {
    return githubPerPageOperations.has(operation || "");
  }

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

  const clickhouseCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "clickhouse"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      clickhouseCredentials.value,
      selectedCredentialId,
      "Select ClickHouse credential...",
      "Shared ClickHouse credential (from owner)",
    );
  });

  const supabaseCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "supabase"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      supabaseCredentials.value,
      selectedCredentialId,
      "Select Supabase credential...",
      "Shared Supabase credential (from owner)",
    );
  });

  const notionCredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "notion"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      notionCredentials.value,
      selectedCredentialId,
      "Select Notion credential...",
      "Shared Notion credential (from owner)",
    );
  });

  const notionDataSourceOptions = computed(() => {
    const selectedId =
      selectedNode.value?.type === "notion"
        ? String(selectedNode.value.data.notionDataSourceId || "").trim()
        : "";
    const discoveredOptions = notionDiscoveredDataSources.value.map((dataSource) => ({
      value: dataSource.id,
      label: dataSource.title || dataSource.id,
    }));
    if (selectedId && !discoveredOptions.some((option) => option.value === selectedId)) {
      discoveredOptions.unshift({ value: selectedId, label: selectedId });
    }
    return [
      {
        value: "",
        label: loadingNotionDataSources.value
          ? "Loading data sources..."
          : "Select data source...",
      },
      ...discoveredOptions,
    ];
  });

  const notionAppendPositionOptions = [
    { value: "end", label: "End" },
    { value: "start", label: "Start" },
    { value: "after_block", label: "After Block" },
  ];

  const notionPageOptions = computed(() => {
    const selectedId =
      selectedNode.value?.type === "notion"
        ? String(selectedNode.value.data.notionParentPageId || "").trim()
        : "";
    const discoveredOptions = notionDiscoveredPages.value.map((page) => ({
      value: page.id,
      label: page.title || page.id,
    }));
    if (selectedId && !discoveredOptions.some((option) => option.value === selectedId)) {
      discoveredOptions.unshift({ value: selectedId, label: selectedId });
    }
    return [
      {
        value: "",
        label: loadingNotionPages.value ? "Loading pages..." : "Select parent page...",
      },
      ...discoveredOptions,
    ];
  });

  const supabaseDiscoveredTableOptions = computed(() => {
    return supabaseDiscoveredTables.value.map((tableName) => ({
      value: tableName,
      label: tableName,
    }));
  });

  function parseSupabaseSelectedColumns(rawValue: string): string[] {
    return rawValue
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  }

  function toggleSupabaseSelectedColumn(columnName: string): void {
    const node = selectedNode.value;
    if (!node || node.type !== "supabase") {
      return;
    }
    const current = new Set(parseSupabaseSelectedColumns(String(node.data.supabaseSelectColumns || "*")));
    if (current.has("*")) {
      current.delete("*");
    }
    if (current.has(columnName)) {
      current.delete(columnName);
    } else {
      current.add(columnName);
    }
    updateNodeData("supabaseSelectColumns", current.size > 0 ? Array.from(current).join(",") : "*");
  }

  function useAllDiscoveredSupabaseColumns(): void {
    if (supabaseDiscoveredColumns.value.length === 0) {
      return;
    }
    updateNodeData("supabaseSelectColumns", supabaseDiscoveredColumns.value.join(","));
  }

  const s3CredentialOptions = computed(() => {
    const node = selectedNode.value;
    const selectedCredentialId =
      node && node.type === "s3"
        ? (node.data.credentialId as string | undefined)
        : undefined;

    return buildCredentialOptions(
      s3Credentials.value,
      selectedCredentialId,
      "Select Amazon S3 credential...",
      "Shared Amazon S3 credential (from owner)",
    );
  });

  const S3_LIST_OBJECTS_MAX_KEYS = 1000;
  const s3MaxKeysWarning = ref("");

  const driveConvertFormatOptions = [
    { value: "pdf", label: "PDF (.pdf)" },
    { value: "docx", label: "Word Document (.docx)" },
    { value: "html", label: "HTML (.html)" },
    { value: "md", label: "Markdown (.md)" },
    { value: "txt", label: "Plain Text (.txt)" },
    { value: "csv", label: "CSV (.csv)" },
    { value: "epub", label: "EPUB (.epub)" },
    { value: "jpg", label: "JPEG Image (.jpg)" },
    { value: "png", label: "PNG Image (.png)" },
    { value: "bmp", label: "BMP Image (.bmp)" },
    { value: "webp", label: "WebP Image (.webp)" },
  ];

  const _IMAGE_MIMES = new Set([
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/bmp",
    "image/webp",
  ]);

  const _MIME_TO_FORMAT: Record<string, string> = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/html": "html",
    "text/markdown": "md",
    "text/plain": "txt",
    "text/csv": "csv",
    "application/epub+zip": "epub",
    "application/json": "json",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/bmp": "bmp",
    "image/webp": "webp",
  };

  const driveConvertFormatOptionsFiltered = computed(() => {
    const n = selectedNode.value;
    if (!n || n.type !== "drive" || n.data.driveOperation !== "convertFile") {
      return driveConvertFormatOptions;
    }
    const fileId = n.data.driveFileId;
    if (!fileId) return driveConvertFormatOptions;
    const file = driveFiles.value.find((f) => f.id === fileId);
    if (!file) return driveConvertFormatOptions;

    const inputFormat = _MIME_TO_FORMAT[file.mime_type];
    const isImage = _IMAGE_MIMES.has(file.mime_type);

    const allowed = isImage
      ? ["jpg", "png", "bmp", "webp"]
      : ["pdf", "docx", "html", "md", "txt", "csv", "epub"];

    return driveConvertFormatOptions.filter(
      (o) => allowed.includes(o.value) && o.value !== inputFormat,
    );
  });

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
    playwrightExprRefsBySlotKey.value[slotKey] = el as ExpandableFieldRef;
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
    return (n.data.imageInputEnabled ? 3 : 2) + agentMcpEnvConnectionIds.value.length;
  });

  const agentMcpEnvConnectionIds = computed((): string[] => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "agent") {
      return [];
    }
    return (n.data.mcpConnections || [])
      .filter((conn) => conn.transport === "stdio")
      .map((conn) => conn.id);
  });

  const mcpCallArgumentKeys = computed((): string[] => {
    const n = workflowStore.selectedNode;
    if (!n || n.type !== "mcpCall") {
      return [];
    }
    return Object.keys(n.data.toolArguments ?? {});
  });

  const mcpCallExpressionFieldCount = computed((): number => mcpCallArgumentKeys.value.length);

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

  function formatMCPJsonValue(value: unknown, fallback: unknown, compact = false): string {
    if (typeof value === "string") return value;
    const formatted = JSON.stringify(value ?? fallback, null, compact ? 0 : 2);
    return typeof formatted === "string" ? formatted : "";
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
  const skillHistoryOpen = ref(false);
  const skillHistoryTarget = ref<{ skill: AgentSkill; skillIndex: number } | null>(null);

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

  function openSkillHistory(skill: AgentSkill, skillIndex: number): void {
    skillHistoryTarget.value = { skill, skillIndex };
    skillHistoryOpen.value = true;
  }

  function applySkillHistorySnapshot(snapshot: AgentSkill, skillIndex: number): void {
    if (!selectedNode.value) return;
    const current = [...(selectedNode.value.data.skills || [])];
    const existingId = current[skillIndex]?.id;
    if (!existingId) return;
    current[skillIndex] = {
      ...snapshot,
      id: existingId,
    };
    updateNodeData("skills", current);
  }

  function handleSkillHistoryEdit(snapshot: AgentSkill, skillIndex: number): void {
    applySkillHistorySnapshot(snapshot, skillIndex);
  }

  function handleSkillHistoryRevert(snapshot: AgentSkill, skillIndex: number): void {
    applySkillHistorySnapshot(snapshot, skillIndex);
    showToast("Skill restored from history", "success");
  }

  function handleSkillHistoryFineTune(snapshot: AgentSkill): void {
    openSkillBuilderEdit(snapshot);
  }

  function handleSkillHistoryExpandSkill(): void {
    const skillId = skillHistoryTarget.value?.skill.id;
    if (!skillId) return;
    const next = new Set(expandedSkillIds.value);
    next.add(skillId);
    expandedSkillIds.value = next;
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

  // ─── mcpCall node helpers ────────────────────────────────────────────────────

  interface MCPCallFetchState {
    loading: boolean;
    error: string | null;
    tools: MCPFetchToolItem[];
  }

  const mcpCallFetchState = ref<MCPCallFetchState>({ loading: false, error: null, tools: [] });

  function updateMCPCallConnectionField(field: keyof AgentMCPConnection, value: unknown): void {
    if (!selectedNode.value) return;
    const current = { ...(selectedNode.value.data.connection ?? {}) };
    const transportChanged = field === "transport" && current.transport !== value;
    (current as Record<string, unknown>)[field] = value;
    updateNodeData("connection", current);
    if (transportChanged) {
      mcpCallFetchState.value = { loading: false, error: null, tools: [] };
      updateNodeData("selectedTool", "");
      updateNodeData("toolArguments", {});
    }
  }

  async function fetchMCPCallTools(): Promise<void> {
    if (!selectedNode.value) return;
    const conn = selectedNode.value.data.connection as AgentMCPConnection;
    mcpCallFetchState.value = { loading: true, error: null, tools: [] };
    const connection = {
      id: conn?.id || "mcpCall",
      transport: conn?.transport,
      label: conn?.label,
      timeoutSeconds: conn?.timeoutSeconds ?? 30,
      command: conn?.command,
      args: conn?.args,
      env: conn?.env,
      url: conn?.url,
      headers: conn?.headers,
    };
    try {
      const res = await mcpApi.fetchTools(connection);
      mcpCallFetchState.value = { loading: false, error: null, tools: res.tools };
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : String(e);
      mcpCallFetchState.value = { loading: false, error: msg || "Failed to connect", tools: [] };
    }
  }

  function selectMCPCallTool(toolName: string): void {
    if (!selectedNode.value) return;
    updateNodeData("selectedTool", toolName);
    const tool = mcpCallFetchState.value.tools.find((t) => t.name === toolName);
    const props = tool?.inputSchema?.properties ?? {};
    const freshArgs: Record<string, string> = {};
    for (const key of Object.keys(props)) {
      freshArgs[key] = (selectedNode.value.data.toolArguments?.[key] as string) ?? "";
    }
    updateNodeData("toolArguments", freshArgs);
  }

  function updateMCPCallArgument(key: string, value: string): void {
    if (!selectedNode.value) return;
    const current = { ...(selectedNode.value.data.toolArguments ?? {}) };
    current[key] = value;
    updateNodeData("toolArguments", current);
  }

  const mcpCallSelectedTool = computed(() => {
    if (!selectedNode.value) return null;
    const name = selectedNode.value.data.selectedTool as string | undefined;
    if (!name) return null;
    const fetched = mcpCallFetchState.value.tools.find((t) => t.name === name);
    if (fetched) return fetched;
    // After a page refresh the fetched list is empty but the saved toolArguments
    // keys are still in node data. Build a synthetic schema from them so the
    // argument fields remain editable without requiring a re-fetch.
    const savedKeys = Object.keys(selectedNode.value.data.toolArguments ?? {});
    type PropDef = { type?: string; description?: string };
    return {
      name,
      description: undefined as string | undefined,
      inputSchema: savedKeys.length
        ? {
            properties: Object.fromEntries(
              savedKeys.map((k): [string, PropDef] => [k, {}]),
            ) as Record<string, PropDef>,
            required: [] as string[],
          }
        : undefined,
    };
  });

  const mcpCallToolOptions = computed(() => {
    const saved = selectedNode.value?.data.selectedTool as string | undefined;
    const fetched = mcpCallFetchState.value.tools;
    const placeholder = fetched.length
      ? "Select a tool…"
      : saved
        ? "Fetch tools to update"
        : "Fetch tools first";
    const opts: { value: string; label: string }[] = [{ value: "", label: placeholder }];
    if (fetched.length > 0) {
      opts.push(...fetched.map((t) => ({ value: t.name, label: t.name })));
    } else if (saved) {
      opts.push({ value: saved, label: saved });
    }
    return opts;
  });

  // ─────────────────────────────────────────────────────────────────────────────

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
    const currentData = selectedNode.value.data as Record<string, unknown>;
    if (Object.is(currentData[key], value)) return;
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

  function handleS3MaxKeysChange(value: string | number): void {
    const raw = String(value ?? "").trim();
    if (!raw) {
      s3MaxKeysWarning.value = "";
      updateNodeData("s3MaxKeys", "100");
      return;
    }

    const numValue = parseInt(raw, 10);
    if (Number.isNaN(numValue)) {
      s3MaxKeysWarning.value = "";
      updateNodeData("s3MaxKeys", "100");
      return;
    }

    const clamped = Math.max(1, Math.min(S3_LIST_OBJECTS_MAX_KEYS, numValue));
    if (numValue > S3_LIST_OBJECTS_MAX_KEYS) {
      s3MaxKeysWarning.value = `Max Keys is limited to ${S3_LIST_OBJECTS_MAX_KEYS} (AWS S3 limit).`;
    } else if (numValue < 1) {
      s3MaxKeysWarning.value = "Max Keys must be at least 1.";
    } else {
      s3MaxKeysWarning.value = "";
    }
    updateNodeData("s3MaxKeys", String(clamped));
  }

  function normalizeStoredS3MaxKeys(): void {
    const node = selectedNode.value;
    if (!node || node.type !== "s3" || node.data.s3Operation !== "listObjects") {
      s3MaxKeysWarning.value = "";
      return;
    }

    const raw = String(node.data.s3MaxKeys ?? "100").trim();
    const numValue = parseInt(raw, 10);
    if (Number.isNaN(numValue)) {
      if (node.data.s3MaxKeys !== "100") {
        updateNodeData("s3MaxKeys", "100");
      }
      return;
    }

    if (numValue > S3_LIST_OBJECTS_MAX_KEYS || numValue < 1) {
      handleS3MaxKeysChange(raw);
    }
  }

  watch(
    () => [selectedNode.value?.id, selectedNode.value?.data.s3Operation] as const,
    () => {
      normalizeStoredS3MaxKeys();
    },
  );

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
      outputSchemaValueInputRefs.value.set(index, el as ExpandableFieldRef);
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

  function setMappingInputRef(index: number, el: ExpandableFieldRef | null): void {
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

  function setExecuteMappingInputRef(index: number, el: ExpandableFieldRef | null): void {
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
    workflowStore.setPropertiesPanelVisible(true);
    unsubDismissOverlays = onDismissOverlays(() => {
      isLastOutputExpanded.value = false;
      isOutputExpanded.value = false;
    });
    window.addEventListener("keydown", handleKeyDown, true);
    loadReservedVariableNames();
  });

  onUnmounted(() => {
    if (notionDataSourceSearchTimer) {
      clearTimeout(notionDataSourceSearchTimer);
    }
    if (notionPageSearchTimer) {
      clearTimeout(notionPageSearchTimer);
    }
    unsubDismissOverlays?.();
    unsubDismissOverlays = null;
    window.removeEventListener("keydown", handleKeyDown, true);
    workflowStore.setPropertiesPanelVisible(false);
    workflowStore.setExpressionGraphNavigateHandler(null);
  });

  return {
    nodeIcons,
    nodeColorMap,
    nodeDocSlugMap,
    workflowStore,
    isWorkflowOwner,
    autoRecoverRuns,
    onToggleAutoRecover,
    otherWorkflows,
    errorWorkflowId,
    onChangeErrorWorkflow,
    minutesSavedPerRun,
    onChangeMinutesSaved,
    workflowTimeoutSeconds,
    onChangeWorkflowTimeout,
    showRunAnalyzer,
    openAnalyzer,
    activeTab,
    runInputValues,
    runInputJson,
    allInputFields,
    isGenericWebhookBodyMode,
    slackTriggerWebhookUrl,
    discordTriggerWebhookUrl,
    telegramTriggerWebhookUrl,
    copySlackWebhookUrl,
    copyDiscordWebhookUrl,
    copyTelegramWebhookUrl,
    runBodyError,
    genericBodyPlaceholder,
    updateRunInputJson,
    updateInputValue,
    formatRunInputJson,
    labelError,
    copied,
    copiedOutput,
    isOutputExpanded,
    runOutputJsonTreeKey,
    runOutputJsonAutoDepth,
    runOutputExpandedPanelRef,
    expandAllRunOutputJson,
    collapseAllRunOutputJson,
    isLastOutputExpanded,
    lastOutputJsonTreeKey,
    lastOutputJsonAutoDepth,
    expandAllLastOutputJson,
    collapseAllLastOutputJson,
    workflowOptions,
    subWorkflowSearch,
    filteredWorkflowOptionsForSubWorkflows,
    isEditingPinnedData,
    editedPinnedData,
    outputMessageInputRef,
    httpCurlInputRef,
    websocketSendUrlInputRef,
    websocketSendHeadersInputRef,
    websocketSendMessageInputRef,
    userMessageInputRef,
    telegramChatIdInputRef,
    telegramMessageInputRef,
    slackMessageInputRef,
    discordMessageInputRef,
    discordUsernameInputRef,
    discordAvatarUrlInputRef,
    sendEmailToInputRef,
    sendEmailCcInputRef,
    sendEmailBccInputRef,
    sendEmailSubjectInputRef,
    sendEmailBodyInputRef,
    sendEmailAttachmentsInputRef,
    conditionInputRef,
    redisKeyInputRef,
    llmSystemInstructionInputRef,
    llmImageExpressionInputRef,
    agentSystemInstructionInputRef,
    agentImageExpressionInputRef,
    codexRepositoryUrlExpressionInputRef,
    codexBaseBranchExpressionInputRef,
    codexTaskPromptExpressionInputRef,
    codexBranchNameExpressionInputRef,
    codexSetupCommandExpressionInputRef,
    variableValueInputRef,
    throwErrorMessageInputRef,
    loadingModels,
    loadingGuardrailModels,
    loadingFallbackModels,
    jsonFormatError,
    slackTriggerCredentials,
    discordTriggerCredentials,
    loadingNotionDataSources,
    notionDataSourcesError,
    notionDataSourceSearch,
    notionDataSourcesHasMore,
    loadingNotionPages,
    notionPagesError,
    notionPageSearch,
    notionPagesHasMore,
    supabaseDiscoveredColumns,
    loadingSupabaseTables,
    loadingSupabaseColumns,
    clickhouseDiscoveredColumns,
    loadingClickhouseColumns,
    driveFileOptions,
    dataTableColumns,
    dataTableSelectiveValues,
    gristColumns,
    ragQueryInputRef,
    ragDocumentInputRef,
    rabbitmqExchangeInputRef,
    rabbitmqRoutingKeyInputRef,
    rabbitmqQueueNameInputRef,
    rabbitmqMessageBodyInputRef,
    websocketTriggerEventOptions,
    crawlerUrlInputRef,
    consoleLogMessageInputRef,
    switchExpressionInputRef,
    loopArrayExpressionInputRef,
    executeTemplateExpressionInputRef,
    gristDocIdExpressionInputRef,
    gristTableIdExpressionInputRef,
    gristRecordIdExpressionInputRef,
    gristRecordIdsExpressionInputRef,
    gristRecordsDataExpressionInputRef,
    gristSortExpressionInputRef,
    gristRecordDataJsonInputRef,
    gristFilterJsonInputRef,
    githubOwnerExpressionInputRef,
    githubRepoExpressionInputRef,
    githubOrganizationExpressionInputRef,
    githubInviteEmailExpressionInputRef,
    githubIssueNumberExpressionInputRef,
    githubAssigneeExpressionInputRef,
    githubCreatorExpressionInputRef,
    githubMentionedExpressionInputRef,
    githubLabelsFilterExpressionInputRef,
    githubSinceExpressionInputRef,
    githubTitleExpressionInputRef,
    githubBodyExpressionInputRef,
    githubCommentBodyExpressionInputRef,
    githubLabelsExpressionInputRef,
    githubAssigneesExpressionInputRef,
    githubHeadExpressionInputRef,
    githubBaseExpressionInputRef,
    githubPullRequestNumberExpressionInputRef,
    githubReviewIdExpressionInputRef,
    githubReviewBodyExpressionInputRef,
    githubCommitIdExpressionInputRef,
    githubFilePathExpressionInputRef,
    githubFileContentExpressionInputRef,
    githubCommitMessageExpressionInputRef,
    githubBranchExpressionInputRef,
    githubTagNameExpressionInputRef,
    githubReleaseIdExpressionInputRef,
    githubWorkflowIdExpressionInputRef,
    githubWorkflowInputsExpressionInputRef,
    sentryOrganizationSlugExpressionInputRef,
    sentryProjectSlugExpressionInputRef,
    sentryTeamSlugExpressionInputRef,
    sentryIssueIdExpressionInputRef,
    sentryEventIdExpressionInputRef,
    sentryReleaseVersionExpressionInputRef,
    sentryNameExpressionInputRef,
    sentrySlugExpressionInputRef,
    sentryPlatformExpressionInputRef,
    sentryStatusExpressionInputRef,
    sentryAssignedToExpressionInputRef,
    sentryQueryExpressionInputRef,
    sentryStatsPeriodExpressionInputRef,
    sentryLimitExpressionInputRef,
    sentryReleaseProjectsExpressionInputRef,
    sentryReleaseRefsExpressionInputRef,
    sentryPayloadExpressionInputRef,
    linearLimitExpressionInputRef,
    linearAfterExpressionInputRef,
    linearTeamIdExpressionInputRef,
    linearProjectIdExpressionInputRef,
    linearIssueIdExpressionInputRef,
    linearTitleExpressionInputRef,
    linearDescriptionExpressionInputRef,
    linearStateIdExpressionInputRef,
    linearIssueLinkUrlExpressionInputRef,
    linearAssigneeIdExpressionInputRef,
    linearPriorityExpressionInputRef,
    linearCommentIdExpressionInputRef,
    linearCommentBodyExpressionInputRef,
    linearParentCommentIdExpressionInputRef,
    googleSheetsSpreadsheetIdExpressionInputRef,
    googleSheetsSheetNameExpressionInputRef,
    googleSheetsValuesInputRef,
    bqProjectIdExpressionInputRef,
    bqQueryExpressionInputRef,
    bqDatasetIdExpressionInputRef,
    bqTableIdExpressionInputRef,
    bqRowsExpressionInputRef,
    clickhouseQueryExpressionInputRef,
    clickhouseTableExpressionInputRef,
    clickhouseFilterExpressionInputRef,
    clickhouseSortExpressionInputRef,
    clickhouseRowIdExpressionInputRef,
    clickhouseDataExpressionInputRef,
    supabaseSchemaExpressionInputRef,
    supabaseTableExpressionInputRef,
    supabaseSelectColumnsExpressionInputRef,
    supabaseFilterExpressionInputRef,
    supabaseOrderByExpressionInputRef,
    supabaseRowsExpressionInputRef,
    supabaseOnConflictExpressionInputRef,
    supabaseDataExpressionInputRef,
    notionQueryExpressionInputRef,
    notionPageIdExpressionInputRef,
    notionDatabaseIdExpressionInputRef,
    notionDatabaseExpressionInputRef,
    notionDataSourceIdExpressionInputRef,
    notionDataSourceExpressionInputRef,
    notionBlockIdExpressionInputRef,
    notionPropertiesExpressionInputRef,
    notionParentPageIdExpressionInputRef,
    notionBlockExpressionInputRef,
    notionIconExpressionInputRef,
    notionCoverExpressionInputRef,
    notionChildrenExpressionInputRef,
    notionFilterExpressionInputRef,
    notionSortExpressionInputRef,
    notionSortsExpressionInputRef,
    notionStartCursorExpressionInputRef,
    notionAfterBlockIdExpressionInputRef,
    dataTableRowIdExpressionInputRef,
    dataTableDataExpressionInputRef,
    dataTableFilterExpressionInputRef,
    dataTableSortExpressionInputRef,
    driveFileIdExpressionInputRef,
    drivePasswordExpressionInputRef,
    driveFilenameExpressionInputRef,
    driveBase64ContentExpressionInputRef,
    s3BucketExpressionInputRef,
    s3KeyExpressionInputRef,
    s3SourceBucketExpressionInputRef,
    s3SourceKeyExpressionInputRef,
    s3PrefixExpressionInputRef,
    s3ContinuationTokenExpressionInputRef,
    s3BodyExpressionInputRef,
    mcpCallConnectionEnvInputRef,
    validationErrors,
    showValidationDialog,
    selectorPickerOpen,
    expandedSavedStepKey,
    selectorPickerInitialUrl,
    openSelectorPickerPlaywright,
    openSelectorPickerCrawler,
    onSelectorPicked,
    loadSupabaseTablesForSelectedNode,
    loadSupabaseColumnsForSelectedNode,
    loadNotionDataSourcesForSelectedNode,
    loadNotionPagesForSelectedNode,
    targetWorkflowInputFields,
    loadingTargetInputs,
    executeWorkflowId,
    guardrailCredentialOptions,
    guardrailModelOptions,
    handleGuardrailCredentialChange,
    handleGuardrailModelChange,
    fallbackCredentialOptions,
    fallbackModelOptions,
    handleFallbackCredentialChange,
    handleFallbackModelChange,
    selectedNode,
    selectedNodeEvaluateDialogLabel,
    selectedNodeTypeLabel,
    isExecuting,
    isRunPanelFileDragActive,
    resetRunPanelFileDrag,
    onRunPanelFileDragEnter,
    onRunPanelFileDragLeave,
    onRunPanelFileDragOver,
    onRunPanelFileDrop,
    isRunbookPlaying,
    hasNodes,
    revealRunTabForRunbook,
    lastExecutedNode,
    exampleRef,
    nodeOutput,
    selectedNodeLoopItemNavigation,
    navigateToPreviousSelectedNodeLoopItem,
    navigateToNextSelectedNodeLoopItem,
    lastOutputExpandedPanelRef,
    httpLastRequest,
    pinnedData,
    isNodeActive,
    availableTargetNodes,
    toggleActive,
    notionExpressionNavBindings,
    handleNotionExpressionFieldNavigate,
    onNotionRegisterExpressionFieldIndex,
    handleLlmExpressionFieldNavigate,
    sendEmailExpressionFieldCount,
    handleSendEmailExpressionFieldNavigate,
    onSendEmailRegisterExpressionFieldIndex,
    handleAgentExpressionFieldNavigate,
    codexExpressionNavBindings,
    handleCodexExpressionFieldNavigate,
    onCodexRegisterExpressionFieldIndex,
    setAgentMCPEnvInputRef,
    agentMCPEnvExpressionIndex,
    handleMCPCallExpressionFieldNavigate,
    setMCPCallArgumentInputRef,
    onMCPCallRegisterExpressionFieldIndex,
    onLlmRegisterExpressionFieldIndex,
    onAgentRegisterExpressionFieldIndex,
    gristExpressionFieldCount,
    handleGristExpressionFieldNavigate,
    onGristRegisterExpressionFieldIndex,
    googleSheetsExpressionFieldCount,
    handleGoogleSheetsExpressionFieldNavigate,
    onGoogleSheetsRegisterExpressionFieldIndex,
    bigQueryExpressionFieldCount,
    handleBigQueryExpressionFieldNavigate,
    onBigQueryRegisterExpressionFieldIndex,
    clickhouseExpressionFieldCount,
    handleClickhouseExpressionFieldNavigate,
    onClickhouseRegisterExpressionFieldIndex,
    clickhouseMappingInputRef,
    clickhouseMappings,
    updateClickhouseMappingValue,
    switchClickhouseToRaw,
    supabaseExpressionFieldCount,
    handleSupabaseExpressionFieldNavigate,
    onSupabaseRegisterExpressionFieldIndex,
    isLinearPaginatedOperation,
    isLinearIssueIdOperation,
    isLinearCommentIdOperation,
    linearExpressionNavBindings,
    handleLinearExpressionFieldNavigate,
    onLinearRegisterExpressionFieldIndex,
    githubExpressionNavBindings,
    handleGitHubExpressionFieldNavigate,
    onGitHubRegisterExpressionFieldIndex,
    sentryExpressionNavBindings,
    handleSentryExpressionFieldNavigate,
    onSentryRegisterExpressionFieldIndex,
    bqMappingInputRef,
    s3ExpressionFieldCount,
    handleS3ExpressionFieldNavigate,
    onS3RegisterExpressionFieldIndex,
    rabbitmqSendExpressionFieldCount,
    handleRabbitmqSendExpressionFieldNavigate,
    onRabbitmqSendRegisterExpressionFieldIndex,
    setDataTableSelectiveExpressionInputRef,
    switchDataTableRowDataToSelectiveMode,
    handleDataTableIdChangedForSelect,
    handleDataTableSelectiveColumnInput,
    dataTableExpressionFieldCount,
    handleDataTableExpressionFieldNavigate,
    onDataTableRegisterExpressionFieldIndex,
    driveExpressionFieldCount,
    isDriveFileIdAgentProvided,
    handleDriveExpressionFieldNavigate,
    onDriveRegisterExpressionFieldIndex,
    chartOutputExpressionFieldCount,
    chartOutputExpressionFieldIndex,
    setChartOutputExpressionInputRef,
    handleChartOutputExpressionFieldNavigate,
    onChartOutputRegisterExpressionFieldIndex,
    onSetMappingRegisterFieldIndex,
    onExecuteMappingRegisterFieldIndex,
    credentialOptions,
    slackCredentialOptions,
    discordCredentialOptions,
    telegramCredentialOptions,
    telegramTriggerCredentialOptions,
    smtpCredentialOptions,
    imapTriggerCredentialOptions,
    redisCredentialOptions,
    vectorStoreOptions,
    ragDbTypeOptions,
    ragOperationOptions,
    redisOperationOptions,
    gristCredentialOptions,
    codexCredentialOptions,
    codexGithubCredentialOptions,
    codexPublishModeOptions,
    codexPublishModeDescriptions,
    githubCredentialOptions,
    linearCredentialOptions,
    linearOperationOptions,
    linearOperationGroups,
    githubOperationOptions,
    githubOperationGroups,
    githubStateOptions,
    githubIssueSortOptions,
    githubPullRequestSortOptions,
    githubDirectionOptions,
    githubUpdateIssueStateOptions,
    githubIssueStateReasonOptions,
    githubLockReasonOptions,
    githubReviewEventOptions,
    isGitHubRepoRequired,
    isGitHubOwnerRequired,
    usesGitHubPerPage,
    googleSheetsCredentialOptions,
    cohereCredentialOptions,
    gristOperationOptions,
    googleSheetsOperationOptions,
    googleSheetsAppendPlacementOptions,
    bigQueryCredentialOptions,
    bigQueryOperationOptions,
    clickhouseCredentialOptions,
    clickhouseOperationOptions,
    clickhouseOperationGroups,
    supabaseCredentialOptions,
    supabaseOperationOptions,
    notionCredentialOptions,
    notionOperationOptions,
    notionOperationGroups,
    notionDataSourceOptions,
    notionAppendPositionOptions,
    notionPageOptions,
    supabaseDiscoveredTableOptions,
    parseSupabaseSelectedColumns,
    toggleSupabaseSelectedColumn,
    useAllDiscoveredSupabaseColumns,
    s3CredentialOptions,
    s3OperationOptions,
    s3OperationGroups,
    s3MaxKeysWarning,
    dataTableOperationOptions,
    driveOperationOptions,
    driveConvertFormatOptionsFiltered,
    dataTableOptions,
    rabbitmqCredentialOptions,
    rabbitmqOperationOptions,
    crawlerCredentialOptions,
    crawlerModeOptions,
    addCrawlerSelector,
    removeCrawlerSelector,
    updateCrawlerSelector,
    updateCrawlerSelectorAttributes,
    playwrightStepActionOptions,
    loadPlaywrightAiStepModels,
    playwrightAiStepModelOptions,
    playwrightStepSections,
    getPlaywrightSteps,
    savedStepKey,
    addPlaywrightStep,
    removePlaywrightStep,
    movePlaywrightStepUp,
    movePlaywrightStepDown,
    playwrightStepDialogKey,
    playwrightStepActionLabel,
    playwrightExpressionNavPlan,
    playwrightExprNavGlobalIndexForAuthState,
    playwrightExprNavGlobalIndexForAuthSelector,
    playwrightExprNavGlobalIndexForStep,
    bindPlaywrightExprSlotRef,
    handlePlaywrightExpressionFieldNavigate,
    onPlaywrightRegisterExpressionFieldIndex,
    updatePlaywrightStep,
    updatePlaywrightStepSavedStep,
    removePlaywrightStepSavedStep,
    formatSavedStep,
    modelOptions,
    reasoningEffortOptions,
    outputTypeOptions,
    GUARDRAIL_CATEGORIES,
    GUARDRAIL_SEVERITY_OPTIONS,
    toggleGuardrailCategory,
    variableTypeOptions,
    httpStatusCodeOptions,
    reservedLabelError,
    variableNameError,
    getInputFieldError,
    getMappingKeyError,
    getExpressionWarning,
    isImageOutputMode,
    llmExpressionFieldCount,
    agentExpressionFieldCount,
    mcpCallArgumentKeys,
    mcpCallExpressionFieldCount,
    selectedModelIsReasoning,
    llmBatchCapabilityMessage,
    llmBatchCapabilityTone,
    llmBatchModeAvailable,
    agentModelContextLimit,
    handleModelChange,
    handleCredentialChange,
    handleLlmOutputTypeChange,
    handleLlmImageInputChange,
    handleLlmBatchModeChange,
    availableSubAgentLabels,
    toggleSubAgentLabel,
    toggleSubWorkflowId,
    openSubWorkflowEditor,
    openDataTableInNewTab,
    addAgentTool,
    removeAgentTool,
    updateAgentTool,
    addAgentMCPConnection,
    removeAgentMCPConnection,
    updateAgentMCPConnection,
    formatMCPJsonValue,
    addAgentSkill,
    removeAgentSkill,
    updateAgentSkill,
    updateAgentSkillFile,
    removeAgentSkillFile,
    skillZipLoading,
    skillZipError,
    skillDownloadLoadingId,
    skillBuilderOpen,
    skillBuilderTargetSkill,
    skillHistoryOpen,
    skillHistoryTarget,
    handleSkillZipDrop,
    downloadAgentSkill,
    expandedSkillIds,
    toggleSkillExpanded,
    openSkillBuilderNew,
    openSkillBuilderEdit,
    openSkillHistory,
    handleSkillHistoryEdit,
    handleSkillHistoryRevert,
    handleSkillHistoryFineTune,
    handleSkillHistoryExpandSkill,
    handleSkillBuilderSave,
    getMCPFetchState,
    fetchMCPTools,
    mcpCallFetchState,
    updateMCPCallConnectionField,
    fetchMCPCallTools,
    selectMCPCallTool,
    updateMCPCallArgument,
    mcpCallSelectedTool,
    mcpCallToolOptions,
    formatJsonSchema,
    updateNodeData,
    toggleWebSocketTriggerEvent,
    handleLabelChange,
    handleDurationChange,
    handleS3MaxKeysChange,
    handleCasesChange,
    outputSchema,
    addOutputSchemaField,
    updateOutputSchemaField,
    removeOutputSchemaField,
    outputExpressionFieldCount,
    setOutputSchemaValueInputRef,
    handleOutputExpressionFieldNavigate,
    onOutputRegisterExpressionFieldIndex,
    mappings,
    addMappingField,
    updateMappingField,
    removeMappingField,
    handleSetMappingNavigate,
    setMappingInputRef,
    bqMappings,
    addBqMapping,
    updateBqMapping,
    removeBqMapping,
    switchBqToRaw,
    executeMappings,
    handleExecuteMappingNavigate,
    setExecuteMappingInputRef,
    inputFields,
    addInputField,
    updateInputField,
    removeInputField,
    pinNodeOutput,
    clearPinnedData,
    startEditingPinnedData,
    cancelEditingPinnedData,
    updateInputCount,
    deleteNode,
    handleExecute,
    closeValidationDialog,
    selectNodeFromError,
    formatOutput,
    copyLastNodeOutput,
    displayPinnedData,
    displayNodeOutput,
    nodeOutputImageSrcs,
    imageLightboxSrc,
    copyOutput,
    canVisitWorkflow,
    visitWorkflow,
    updateExecuteWorkflowId,
    updateExecuteMapping,
  };
}

export type PropertiesPanelContext = ReturnType<typeof usePropertiesPanelController>;

const propertiesPanelContextKey: InjectionKey<PropertiesPanelContext> = Symbol(
  "PropertiesPanelContext",
);

export function providePropertiesPanelContext(context: PropertiesPanelContext): void {
  provide(propertiesPanelContextKey, context);
}

export function usePropertiesPanelContext(): PropertiesPanelContext {
  const context = inject(propertiesPanelContextKey);
  if (!context) {
    throw new Error("PropertiesPanel context is not available");
  }
  return context;
}
