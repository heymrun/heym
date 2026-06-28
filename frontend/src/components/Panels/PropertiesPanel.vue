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
import {
  AlertTriangle,
  Ban,
  BarChart3,
  BookOpen,
  Bot,
  Braces,
  Brain,
  Bug,
  CalendarClock,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock,
  Copy,
  Database,
  ExternalLink,
  FileArchive,
  FileJson,
  FileText,
  GitBranch,
  GitMerge,
  Github,
  Globe,
  HardDrive,
  Inbox,
  ListTodo,
  Loader2,
  Mail,
  Maximize2,
  MessageSquare,
  Minus,
  Minimize2,
  MonitorPlay,
  MousePointerClick,
  Play,
  Plug,
  Plus,
  Power,
  Rabbit,
  Radio,
  RefreshCw,
  Repeat,
  Search,
  Send,
  Server,
  Settings,
  Settings2,
  Sheet,
  ShieldAlert,
  Shuffle,
  Sparkles,
  StickyNote,
  Table2,
  Terminal,
  Trash2,
  Type,
  Upload,
  Variable,
  X,
  XCircle,
  Zap,
} from "lucide-vue-next";

import type {
  ClickHouseColumn,
  CredentialListItem,
  LLMModel,
  NotionDataSourceItem,
  NotionPageItem,
} from "@/types/credential";
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
import SkillHistoryDialog from "@/components/Dialogs/SkillHistoryDialog.vue";
import AgentSkillCard from "@/components/Panels/AgentSkillCard.vue";
import SkillBuilderModal from "@/components/Panels/SkillBuilderModal.vue";
import Button from "@/components/ui/Button.vue";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import RunInputField from "@/components/Panels/RunInputField.vue";
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
import {
  getGitHubExpressionFields,
  type GitHubExpressionFieldKey,
} from "@/lib/githubExpressionFields";
import {
  getLinearExpressionFields,
  type LinearExpressionFieldKey,
} from "@/lib/linearExpressionFields";
import {
  getNotionExpressionFields,
  type NotionExpressionFieldKey,
} from "@/lib/notionExpressionFields";
import { parseWebhookJson, stringifyWebhookJson } from "@/lib/webhookBody";
import { cn } from "@/lib/utils";
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

const nodeIcons: Record<NodeType, ReturnType<typeof Type>> = {
  chartOutput: BarChart3,
  textInput: Type,
  cron: CalendarClock,
  websocketTrigger: Radio,
  fileUploadTrigger: Upload,
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
  throwError: XCircle,
  rabbitmq: Rabbit,
  crawler: Bug,
  consoleLog: Terminal,
  playwright: MonitorPlay,
  dataTable: Table2,
  drive: HardDrive,
  s3: Server,
  mcpCall: Plug,
};

const nodeColorMap: Record<NodeType, string> = {
  chartOutput: "node-output",
  textInput: "node-input",
  cron: "node-cron",
  websocketTrigger: "node-websocket",
  fileUploadTrigger: "node-websocket",
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
  throwError: "node-throw-error",
  rabbitmq: "node-rabbitmq",
  crawler: "node-crawler",
  consoleLog: "node-console-log",
  playwright: "node-playwright",
  dataTable: "node-datatable",
  drive: "node-drive",
  s3: "node-drive",
  mcpCall: "node-agent",
};

const nodeDocSlugMap: Record<NodeType, string> = {
  chartOutput: "chart-output-node",
  textInput: "input-node",
  cron: "cron-node",
  websocketTrigger: "websocket-trigger-node",
  fileUploadTrigger: "file-upload-trigger-node",
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
  throwError: "throw-error-node",
  rabbitmq: "rabbitmq-node",
  crawler: "crawler-node",
  consoleLog: "console-log-node",
  playwright: "playwright-node",
  dataTable: "datatable-node",
  drive: "drive-node",
  s3: "amazon-s3-node",
  mcpCall: "mcp-call-node",
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
const discordMessageInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const discordUsernameInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const discordAvatarUrlInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const sendEmailToInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const sendEmailCcInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const sendEmailBccInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const sendEmailSubjectInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const sendEmailBodyInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const sendEmailAttachmentsInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentSendEmailExpressionFieldIndex = ref(0);
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
const agentMcpEnvInputRefs = ref<Map<string, InstanceType<typeof ExpressionInput>>>(new Map());
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
const discordCredentials = ref<CredentialListItem[]>([]);
const discordTriggerCredentials = ref<CredentialListItem[]>([]);
const imapTriggerCredentials = ref<CredentialListItem[]>([]);
const smtpCredentials = ref<CredentialListItem[]>([]);
const redisCredentials = ref<CredentialListItem[]>([]);
const gristCredentials = ref<CredentialListItem[]>([]);
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
  Map<string, InstanceType<typeof ExpressionInput>>
>(new Map());
const gristColumns = ref<{ id: string; name: string; type: string }[]>([]);
const vectorStores = ref<{ id: string; name: string; backend: string }[]>([]);
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
const githubOwnerExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubRepoExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubOrganizationExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubInviteEmailExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubIssueNumberExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubAssigneeExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubCreatorExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubMentionedExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubLabelsFilterExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubSinceExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubTitleExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubBodyExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubCommentBodyExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubLabelsExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubAssigneesExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubHeadExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubBaseExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubPullRequestNumberExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubReviewIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubReviewBodyExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubCommitIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubFilePathExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubFileContentExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubCommitMessageExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubBranchExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubTagNameExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubReleaseIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubWorkflowIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const githubWorkflowInputsExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentGitHubExpressionFieldIndex = ref(0);
const linearLimitExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearAfterExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearTeamIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearProjectIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearIssueIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearTitleExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearDescriptionExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearStateIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearIssueLinkUrlExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearAssigneeIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearPriorityExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearCommentIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearCommentBodyExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const linearParentCommentIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentLinearExpressionFieldIndex = ref(0);
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
const clickhouseQueryExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const clickhouseTableExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const clickhouseFilterExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const clickhouseSortExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const clickhouseRowIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const clickhouseDataExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const clickhouseMappingInputRefs = ref<Map<string, InstanceType<typeof ExpressionInput>>>(new Map());
const currentClickhouseExpressionFieldIndex = ref(0);
const supabaseSchemaExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const supabaseTableExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const supabaseSelectColumnsExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const supabaseFilterExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const supabaseOrderByExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const supabaseRowsExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const supabaseOnConflictExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const supabaseDataExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentSupabaseExpressionFieldIndex = ref(0);
const notionQueryExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionPageIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionDatabaseIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionDatabaseExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionDataSourceIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionDataSourceExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionBlockIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionPropertiesExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionParentPageIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionBlockExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionIconExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionCoverExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionChildrenExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionFilterExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionSortExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionSortsExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionStartCursorExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const notionAfterBlockIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentNotionExpressionFieldIndex = ref(0);
const dataTableRowIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const dataTableDataExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const dataTableFilterExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const dataTableSortExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentDataTableExpressionFieldIndex = ref(0);
const driveFileIdExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const drivePasswordExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const driveFilenameExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const driveBase64ContentExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentDriveExpressionFieldIndex = ref(0);
const s3BucketExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const s3KeyExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const s3SourceBucketExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const s3SourceKeyExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const s3PrefixExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const s3ContinuationTokenExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const s3BodyExpressionInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
const currentS3ExpressionFieldIndex = ref(0);
const currentPlaywrightExpressionFieldIndex = ref(0);
/** ExpressionInput instances keyed by stable slot id (survives action changes / unmount). */
const playwrightExprRefsBySlotKey = ref<Record<string, InstanceType<typeof ExpressionInput> | null>>({});
const mcpCallArgumentInputRefs = ref<Map<string, InstanceType<typeof ExpressionInput>>>(new Map());
const mcpCallConnectionEnvInputRef = ref<InstanceType<typeof ExpressionInput> | null>(null);
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
  Map<ChartOutputExpressionFieldKey, InstanceType<typeof ExpressionInput>>
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
  closeGitHubExpressionDialogs();
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
): InstanceType<typeof ExpressionInput> | null {
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
  (): (InstanceType<typeof ExpressionInput> | null)[] => [
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
    agentMcpEnvInputRefs.value.set(connId, el as InstanceType<typeof ExpressionInput>);
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
    mcpCallArgumentInputRefs.value.set(key, el as InstanceType<typeof ExpressionInput>);
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
): InstanceType<typeof ExpressionInput> | null {
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
  el: InstanceType<typeof ExpressionInput> | null,
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

const githubExpressionFields = computed(() => {
  const n = workflowStore.selectedNode;
  if (!n || n.type !== "github") {
    return [];
  }
  const operation = (n.data.githubOperation as string | undefined) || "getRepository";
  return getGitHubExpressionFields(operation);
});

const githubExpressionFieldCount = computed((): number => githubExpressionFields.value.length);

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
): InstanceType<typeof ExpressionInput> | null {
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
): InstanceType<typeof ExpressionInput> | null {
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

function bqMappingInputRef(index: number, el: InstanceType<typeof ExpressionInput> | null): void {
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
    chartOutputExpressionInputRefs.value.set(key, el as InstanceType<typeof ExpressionInput>);
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

const linearOperationOptions = [
  { value: "getViewer", label: "Get Viewer" },
  { value: "listTeams", label: "List Teams" },
  { value: "listProjects", label: "List Projects" },
  { value: "listIssues", label: "List Issues" },
  { value: "listWorkflowStates", label: "List Workflow States" },
  { value: "listTeamMembers", label: "List Team Members" },
  { value: "getIssue", label: "Get Issue" },
  { value: "createIssue", label: "Create Issue" },
  { value: "updateIssue", label: "Update Issue" },
  { value: "deleteIssue", label: "Delete Issue" },
  { value: "addIssueLink", label: "Add Issue Link" },
  { value: "createComment", label: "Create Comment" },
  { value: "listComments", label: "List Comments" },
  { value: "updateComment", label: "Update Comment" },
  { value: "deleteComment", label: "Delete Comment" },
  { value: "resolveComment", label: "Resolve Comment" },
  { value: "unresolveComment", label: "Unresolve Comment" },
];

const githubOperationOptions = [
  { value: "getRepository", label: "Get Repository" },
  { value: "getRepositoryLicense", label: "Get Repository License" },
  { value: "getRepositoryProfile", label: "Get Repository Profile" },
  { value: "listPopularPaths", label: "List Popular Paths for Repository" },
  { value: "listReferrers", label: "List Top Referrers for Repository" },
  { value: "listOrganizationRepositories", label: "List Organization Repositories" },
  { value: "listUserRepositories", label: "List User Repositories" },
  { value: "getUserRepositories", label: "Get User Repositories" },
  { value: "getUserIssues", label: "Get User Issues" },
  { value: "inviteUser", label: "Invite User" },
  { value: "createIssue", label: "Create Issue" },
  { value: "getIssue", label: "Get Issue" },
  { value: "listIssues", label: "List Issues" },
  { value: "getRepositoryIssues", label: "Get Repository Issues" },
  { value: "lockIssue", label: "Lock Issue" },
  { value: "updateIssue", label: "Edit Issue" },
  { value: "createComment", label: "Create Comment" },
  { value: "createPullRequest", label: "Create Pull Request" },
  { value: "listPullRequests", label: "List Pull Requests" },
  { value: "getRepositoryPullRequests", label: "Get Repository Pull Requests" },
  { value: "createReview", label: "Create Review" },
  { value: "getReview", label: "Get Review" },
  { value: "listReviews", label: "List Reviews" },
  { value: "updateReview", label: "Update Review" },
  { value: "createRelease", label: "Create Release" },
  { value: "deleteRelease", label: "Delete Release" },
  { value: "getRelease", label: "Get Release" },
  { value: "listReleases", label: "List Releases" },
  { value: "updateRelease", label: "Update Release" },
  { value: "dispatchWorkflow", label: "Dispatch Workflow" },
  { value: "dispatchWorkflowAndWait", label: "Dispatch Workflow and Wait" },
  { value: "disableWorkflow", label: "Disable Workflow" },
  { value: "enableWorkflow", label: "Enable Workflow" },
  { value: "getWorkflow", label: "Get Workflow" },
  { value: "getWorkflowUsage", label: "Get Workflow Usage" },
  { value: "listWorkflows", label: "List Workflows" },
  { value: "upsertFile", label: "Create or Update File" },
  { value: "deleteFile", label: "Delete File" },
  { value: "getFile", label: "Get File" },
  { value: "listFiles", label: "List Files" },
];

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

const clickhouseOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "query", label: "Run SQL Query" },
  { value: "find", label: "Find Rows" },
  { value: "getAll", label: "Get All Rows" },
  { value: "count", label: "Count Rows" },
  { value: "getById", label: "Get By ID" },
  { value: "insert", label: "Insert Rows" },
  { value: "update", label: "Update Rows" },
  { value: "remove", label: "Remove Rows" },
  { value: "upsert", label: "Upsert Rows" },
];

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

const supabaseOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "select", label: "Select Rows" },
  { value: "insert", label: "Insert Rows" },
  { value: "update", label: "Update Rows" },
  { value: "upsert", label: "Upsert Rows" },
  { value: "delete", label: "Delete Rows" },
];

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

const notionOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "search", label: "Search" },
  { value: "getPage", label: "Get Page" },
  { value: "createPage", label: "Create Page" },
  { value: "updatePage", label: "Update Page" },
  { value: "trashPage", label: "Move Page to Trash" },
  { value: "restorePage", label: "Restore Page" },
  { value: "createDatabase", label: "Create Database" },
  { value: "retrieveDatabase", label: "Retrieve Database" },
  { value: "updateDatabase", label: "Update Database" },
  { value: "createDataSource", label: "Create Data Source" },
  { value: "retrieveDataSource", label: "Retrieve Data Source" },
  { value: "updateDataSource", label: "Update Data Source" },
  { value: "queryDataSource", label: "Query Data Source" },
  { value: "getBlockChildren", label: "Get Block Children" },
  { value: "updateBlock", label: "Update Block" },
  { value: "deleteBlock", label: "Delete Block" },
  { value: "appendBlocks", label: "Append Blocks" },
];

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

const s3OperationOptions = [
  { value: "createBucket", label: "Create Bucket" },
  { value: "deleteBucket", label: "Delete Bucket" },
  { value: "listBuckets", label: "List Buckets" },
  { value: "createFolder", label: "Create Folder" },
  { value: "deleteFolder", label: "Delete Folder" },
  { value: "getAllFolder", label: "Get All in Folder" },
  { value: "copyObject", label: "Copy Object" },
  { value: "deleteObject", label: "Delete Object" },
  { value: "getObject", label: "Get Object" },
  { value: "listObjects", label: "List Objects" },
  { value: "putObject", label: "Upload Object" },

];

const S3_LIST_OBJECTS_MAX_KEYS = 1000;
const s3MaxKeysWarning = ref("");

const dataTableOperationOptions = [
  { value: "", label: "Select operation..." },
  { value: "find", label: "Find Rows" },
  { value: "getAll", label: "Get All Rows" },
  { value: "count", label: "Count Rows" },
  { value: "getById", label: "Get Row by ID" },
  { value: "insert", label: "Insert Row" },
  { value: "update", label: "Update Row" },
  { value: "remove", label: "Remove Row" },
  { value: "upsert", label: "Upsert Row" },
];

const driveOperationOptions = [
  { value: "get", label: "Get File" },
  { value: "getAll", label: "Get All Files" },
  { value: "downloadUrl", label: "Download from URL" },
  { value: "save", label: "Save from Base64" },
  { value: "convertFile", label: "Convert File" },
  { value: "delete", label: "Delete File" },
  { value: "setPassword", label: "Set Password" },
  { value: "setTtl", label: "Set TTL (Expiry)" },
  { value: "setMaxDownloads", label: "Set Max Downloads" },
];

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
            ? 'text-primary bg-primary/10 shadow-sm dark:bg-primary/20 dark:text-primary-foreground'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
        )"
        @click="activeTab = 'properties'"
      >
        <Settings class="w-4 h-4" />
        <span class="hidden md:inline">Properties</span>
      </button>
      <button
        data-runbook-run
        :class="cn(
          'flex-1 px-3 py-2 min-h-[44px] text-sm font-medium transition-all flex items-center justify-center gap-2 rounded-lg',
          activeTab === 'config'
            ? 'text-primary bg-primary/10 shadow-sm dark:bg-primary/20 dark:text-primary-foreground'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted/50',
          isRunbookPlaying && 'runbook-pulse'
        )"
        @click="activeTab = 'config'"
        @focus="revealRunTabForRunbook"
        @mouseenter="revealRunTabForRunbook"
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
                >{{ selectedNodeTypeLabel
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

          <template v-if="selectedNode.type === 'fileUploadTrigger'">
            <div class="space-y-4">
              <p class="text-xs text-muted-foreground">
                Running this workflow returns a single-use <code>curl</code> upload link.
                Uploading a file to that link starts the run with the file available as
                <code>${{ selectedNode.data.label || "fileUpload" }}.file</code>.
              </p>

              <div class="space-y-2">
                <Label>Link TTL (minutes)</Label>
                <Input
                  type="number"
                  :min="1"
                  :max="10080"
                  :model-value="selectedNode.data.ttlMinutes ?? 60"
                  placeholder="60"
                  @update:model-value="updateNodeData('ttlMinutes', Number($event) || 60)"
                />
                <p class="text-xs text-muted-foreground">
                  How long the upload link stays valid (1–10080 minutes). Default 60.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Max file size (MB)</Label>
                <Input
                  type="number"
                  :min="1"
                  :max="100"
                  :model-value="selectedNode.data.maxSizeMb ?? 100"
                  placeholder="100"
                  @update:model-value="updateNodeData('maxSizeMb', Number($event) || 100)"
                />
                <p class="text-xs text-muted-foreground">
                  Hard ceiling is 100 MB. Larger uploads are rejected.
                </p>
              </div>

              <div class="space-y-2">
                <Label>Allowed types (optional)</Label>
                <Input
                  :model-value="selectedNode.data.allowedTypes || ''"
                  placeholder="audio/*, .wav"
                  @update:model-value="updateNodeData('allowedTypes', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Comma-separated MIME types or extensions. Leave empty to allow any type.
                </p>
              </div>
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

          <template v-if="selectedNode.type === 'discordTrigger'">
            <div class="space-y-4">
              <div class="space-y-2">
                <Label>Public Key Credential</Label>
                <Select
                  :model-value="selectedNode.data.credentialId || ''"
                  :options="discordTriggerCredentials.map((c) => ({ value: c.id, label: c.name }))"
                  placeholder="Select Discord Trigger credential"
                  @update:model-value="updateNodeData('credentialId', $event)"
                />
                <p
                  v-if="!selectedNode.data.credentialId"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  No credential set — Discord requests will be rejected
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Used to verify incoming Discord interaction signatures (Ed25519)
                </p>
              </div>

              <div class="space-y-2">
                <Label>Interactions URL</Label>
                <div class="flex gap-2">
                  <Input
                    :model-value="discordTriggerWebhookUrl"
                    readonly
                    class="font-mono text-xs"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    @click="copyDiscordWebhookUrl"
                  >
                    Copy
                  </Button>
                </div>
                <p class="text-xs text-muted-foreground">
                  Paste this URL into Discord Developer Portal → your application → Interactions Endpoint URL.
                  PING verification is handled automatically.
                </p>
              </div>

              <div class="space-y-2 pt-2 border-t">
                <Label class="text-xs text-muted-foreground">Available output fields</Label>
                <div class="text-xs text-muted-foreground space-y-1 font-mono">
                  <div>${{ selectedNode.data.label }}.interaction — full Discord interaction payload</div>
                  <div>${{ selectedNode.data.label }}.type — interaction type (2 = slash command)</div>
                  <div>${{ selectedNode.data.label }}.data — command/button/modal data</div>
                  <div>${{ selectedNode.data.label }}.data.options — slash command options</div>
                  <div>${{ selectedNode.data.label }}.headers — sanitized HTTP headers</div>
                  <div>${{ selectedNode.data.label }}.triggered_at — ISO timestamp</div>
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
                  field-key="userMessage"
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
                  field-key="imageInput"
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
                  field-key="systemInstruction"
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
                  field-key="userMessage"
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
                  field-key="imageInput"
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
                <Label>Request Timeout (seconds)</Label>
                <Input
                  type="number"
                  :model-value="String(selectedNode.data.requestTimeoutSeconds ?? 60)"
                  min="1"
                  max="3600"
                  placeholder="60"
                  @update:model-value="updateNodeData('requestTimeoutSeconds', parseInt($event, 10) || 60)"
                />
                <p class="text-xs text-muted-foreground">
                  Max seconds to wait for the model response before timing out
                </p>
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
                field-key="systemInstruction"
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
                field-key="userMessage"
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
                field-key="imageInput"
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
              <Label>Request Timeout (seconds)</Label>
              <Input
                type="number"
                :model-value="String(selectedNode.data.requestTimeoutSeconds ?? 60)"
                min="1"
                max="3600"
                placeholder="60"
                @update:model-value="updateNodeData('requestTimeoutSeconds', parseInt($event, 10) || 60)"
              />
              <p class="text-xs text-muted-foreground">
                Max seconds to wait for the model response before timing out
              </p>
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
                max="3600"
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
                          { value: 'streamable_http', label: 'Streamable HTTP' },
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
                        max="3600"
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
                        :model-value="formatMCPJsonValue(conn.args, [])"
                        placeholder="[&quot;-y&quot;, &quot;@modelcontextprotocol/server-filesystem&quot;, &quot;--path&quot;, &quot;/tmp&quot;]"
                        :rows="2"
                        wrap="off"
                        class="overflow-x-auto whitespace-pre font-mono text-xs"
                        @update:model-value="updateAgentMCPConnection(idx, 'args', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Env (JSON object)</Label>
                      <ExpressionInput
                        :ref="(el) => setAgentMCPEnvInputRef(conn.id, el)"
                        :model-value="formatMCPJsonValue(conn.env, {})"
                        placeholder="{&quot;API_KEY&quot;: &quot;your_key&quot;}"
                        :rows="2"
                        wrap="off"
                        :nodes="workflowStore.nodes"
                        :node-results="workflowStore.nodeResults"
                        :edges="workflowStore.edges"
                        :current-node-id="selectedNode.id"
                        expandable
                        navigation-enabled
                        :navigation-index="agentMCPEnvExpressionIndex(conn.id)"
                        :navigation-total="agentExpressionFieldCount"
                        :dialog-node-label="selectedNodeEvaluateDialogLabel"
                        :dialog-key-label="`MCP ${idx + 1} env`"
                        @update:model-value="updateAgentMCPConnection(idx, 'env', $event)"
                        @navigate="handleAgentExpressionFieldNavigate"
                        @register-field-index="onAgentRegisterExpressionFieldIndex"
                      />
                    </div>
                  </template>
                  <template v-else-if="conn.transport === 'sse' || conn.transport === 'streamable_http'">
                    <div>
                      <Label class="text-xs">URL</Label>
                      <Input
                        :model-value="conn.url ?? ''"
                        :placeholder="conn.transport === 'streamable_http' ? 'https://example.com/mcp' : 'https://example.com/mcp/sse'"
                        @update:model-value="updateAgentMCPConnection(idx, 'url', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Headers (JSON object)</Label>
                      <Textarea
                        :model-value="formatMCPJsonValue(conn.headers, {})"
                        placeholder="{&quot;Authorization&quot;: &quot;Bearer ...&quot;, &quot;X-Custom&quot;: &quot;value&quot;}"
                        :rows="2"
                        wrap="off"
                        class="overflow-x-auto whitespace-pre font-mono text-xs"
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
                        ((conn.transport === 'sse' || conn.transport === 'streamable_http') && !conn.url) ||
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
                      class="space-y-0.5 text-xs"
                    >
                      <div class="font-medium text-foreground break-words">
                        {{ t.name }}
                      </div>
                      <p
                        v-if="t.description"
                        class="text-muted-foreground leading-snug break-words"
                      >
                        {{ t.description }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
              <p class="text-xs text-muted-foreground">
                MCP servers the agent can call. Optional. stdio: command + args. SSE / Streamable HTTP: url + headers.
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
              <AgentSkillCard
                v-for="(skill, idx) in (selectedNode.data.skills || [])"
                :key="skill.id"
                :skill="skill"
                :index="idx"
                :expanded="expandedSkillIds.has(skill.id)"
                :ai-edit-disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
                :download-loading="skillDownloadLoadingId === skill.id"
                @toggle-expand="toggleSkillExpanded(skill.id)"
                @ai-edit="openSkillBuilderEdit(skill)"
                @download="downloadAgentSkill(skill)"
                @remove="removeAgentSkill(idx)"
                @history="openSkillHistory(skill, idx)"
                @update:name="updateAgentSkill(idx, 'name', $event)"
                @update:timeout-seconds="updateAgentSkill(idx, 'timeoutSeconds', $event)"
                @update:content="updateAgentSkill(idx, 'content', $event)"
                @update:file-content="(fileIndex, value) => updateAgentSkillFile(idx, fileIndex, 'content', value)"
                @remove-file="removeAgentSkillFile(idx, $event)"
              />
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
                field-key="hitlSummary"
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
                field-key="condition"
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
                field-key="expression"
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
                field-key="executeInput"
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
                field-key="curl"
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
                  field-key="websocketUrl"
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
                  field-key="websocketHeaders"
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
                  field-key="websocketMessage"
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
                field-key="message"
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
                field-key="logMessage"
                @update:model-value="updateNodeData('logMessage', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Written to backend (server) console only; not visible in the browser.
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'chartOutput'">
            <div class="space-y-2">
              <Label>Chart type</Label>
              <Select
                :model-value="selectedNode.data.chartType || 'bar'"
                :options="[
                  { value: 'bar', label: 'Bar' },
                  { value: 'line', label: 'Line' },
                  { value: 'area', label: 'Area' },
                  { value: 'pie', label: 'Pie' },
                  { value: 'table', label: 'Table' },
                  { value: 'numeric', label: 'Numeric' },
                  { value: 'gauge', label: 'Gauge' },
                  { value: 'scatter', label: 'Scatter' },
                  { value: 'proportion', label: 'Proportion' },
                  { value: 'barGauge', label: 'Bar gauge' },
                  { value: 'text', label: 'Text' },
                ]"
                @update:model-value="updateNodeData('chartType', $event)"
              />
            </div>

            <div
              v-if="selectedNode.data.chartType === 'text'"
              class="space-y-2"
            >
              <Label>Text (markdown)</Label>
              <ExpressionInput
                :ref="(el: unknown) => setChartOutputExpressionInputRef('text', el)"
                :model-value="selectedNode.data.text || ''"
                :rows="5"
                placeholder="e.g. **Last execution** at `19:47`"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Text (markdown)"
                field-key="text"
                :navigation-enabled="chartOutputExpressionFieldCount > 1"
                :navigation-index="chartOutputExpressionFieldIndex('text')"
                :navigation-total="chartOutputExpressionFieldCount"
                @navigate="handleChartOutputExpressionFieldNavigate"
                @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('text', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Markdown is supported. Leave empty and set a Value field below to pull the message
                from upstream data instead.
              </p>
            </div>

            <div
              v-if="selectedNode.data.chartType === 'text'"
              class="space-y-2"
            >
              <Label>Value field (optional)</Label>
              <ExpressionInput
                :ref="(el: unknown) => setChartOutputExpressionInputRef('valueField', el)"
                :model-value="selectedNode.data.valueField || ''"
                placeholder="row key holding the markdown string"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Value field"
                field-key="valueField"
                :navigation-enabled="chartOutputExpressionFieldCount > 1"
                :navigation-index="chartOutputExpressionFieldIndex('valueField')"
                :navigation-total="chartOutputExpressionFieldCount"
                @navigate="handleChartOutputExpressionFieldNavigate"
                @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('valueField', $event)"
              />
            </div>

            <div
              v-if="selectedNode.data.chartType === 'bar'"
              class="space-y-2"
            >
              <Label>Orientation</Label>
              <Select
                :model-value="selectedNode.data.orientation || 'vertical'"
                :options="[
                  { value: 'vertical', label: 'Vertical' },
                  { value: 'horizontal', label: 'Horizontal' },
                ]"
                @update:model-value="updateNodeData('orientation', $event)"
              />
            </div>

            <div class="space-y-2">
              <Label>Data path</Label>
              <ExpressionInput
                :ref="(el: unknown) => setChartOutputExpressionInputRef('dataPath', el)"
                :model-value="selectedNode.data.dataPath || ''"
                placeholder="e.g. data or result.items"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Data path"
                field-key="dataPath"
                :navigation-enabled="chartOutputExpressionFieldCount > 1"
                :navigation-index="chartOutputExpressionFieldIndex('dataPath')"
                :navigation-total="chartOutputExpressionFieldCount"
                @navigate="handleChartOutputExpressionFieldNavigate"
                @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('dataPath', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Dot path to the rows array inside the upstream output. Leave empty to auto-detect.
              </p>
            </div>

            <template
              v-if="['bar', 'line', 'area', 'pie', 'numeric', 'gauge', 'proportion', 'barGauge'].includes(selectedNode.data.chartType || 'bar')"
            >
              <div
                v-if="['bar', 'line', 'area', 'pie', 'proportion', 'barGauge'].includes(selectedNode.data.chartType || 'bar')"
                class="space-y-2"
              >
                <Label>Label field</Label>
                <ExpressionInput
                  :ref="(el: unknown) => setChartOutputExpressionInputRef('labelField', el)"
                  :model-value="selectedNode.data.labelField || ''"
                  placeholder="row key used as category label"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Label field"
                  field-key="labelField"
                  :navigation-enabled="chartOutputExpressionFieldCount > 1"
                  :navigation-index="chartOutputExpressionFieldIndex('labelField')"
                  :navigation-total="chartOutputExpressionFieldCount"
                  @navigate="handleChartOutputExpressionFieldNavigate"
                  @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('labelField', $event)"
                />
              </div>

              <div class="space-y-2">
                <Label>Value field</Label>
                <ExpressionInput
                  :ref="(el: unknown) => setChartOutputExpressionInputRef('valueField', el)"
                  :model-value="selectedNode.data.valueField || ''"
                  placeholder="row key used as numeric value"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Value field"
                  field-key="valueField"
                  :navigation-enabled="chartOutputExpressionFieldCount > 1"
                  :navigation-index="chartOutputExpressionFieldIndex('valueField')"
                  :navigation-total="chartOutputExpressionFieldCount"
                  @navigate="handleChartOutputExpressionFieldNavigate"
                  @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('valueField', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.chartType === 'scatter'">
              <div class="space-y-2">
                <Label>X field</Label>
                <ExpressionInput
                  :ref="(el: unknown) => setChartOutputExpressionInputRef('xField', el)"
                  :model-value="selectedNode.data.xField || ''"
                  placeholder="row key for the X axis (numeric)"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="X field"
                  field-key="xField"
                  :navigation-enabled="chartOutputExpressionFieldCount > 1"
                  :navigation-index="chartOutputExpressionFieldIndex('xField')"
                  :navigation-total="chartOutputExpressionFieldCount"
                  @navigate="handleChartOutputExpressionFieldNavigate"
                  @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('xField', $event)"
                />
              </div>
              <div class="space-y-2">
                <Label>Y field</Label>
                <ExpressionInput
                  :ref="(el: unknown) => setChartOutputExpressionInputRef('yField', el)"
                  :model-value="selectedNode.data.yField || ''"
                  placeholder="row key for the Y axis (numeric)"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Y field"
                  field-key="yField"
                  :navigation-enabled="chartOutputExpressionFieldCount > 1"
                  :navigation-index="chartOutputExpressionFieldIndex('yField')"
                  :navigation-total="chartOutputExpressionFieldCount"
                  @navigate="handleChartOutputExpressionFieldNavigate"
                  @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('yField', $event)"
                />
              </div>
            </template>

            <div
              v-if="selectedNode.data.chartType === 'gauge'"
              class="grid grid-cols-2 gap-2"
            >
              <div class="space-y-2">
                <Label>Min</Label>
                <ExpressionInput
                  :ref="(el: unknown) => setChartOutputExpressionInputRef('min', el)"
                  :model-value="String(selectedNode.data.min ?? 0)"
                  placeholder="0"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Min"
                  field-key="min"
                  :navigation-enabled="chartOutputExpressionFieldCount > 1"
                  :navigation-index="chartOutputExpressionFieldIndex('min')"
                  :navigation-total="chartOutputExpressionFieldCount"
                  @navigate="handleChartOutputExpressionFieldNavigate"
                  @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('min', $event)"
                />
              </div>
              <div class="space-y-2">
                <Label>Max</Label>
                <ExpressionInput
                  :ref="(el: unknown) => setChartOutputExpressionInputRef('max', el)"
                  :model-value="String(selectedNode.data.max ?? 100)"
                  placeholder="100"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Max"
                  field-key="max"
                  :navigation-enabled="chartOutputExpressionFieldCount > 1"
                  :navigation-index="chartOutputExpressionFieldIndex('max')"
                  :navigation-total="chartOutputExpressionFieldCount"
                  @navigate="handleChartOutputExpressionFieldNavigate"
                  @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('max', $event)"
                />
              </div>
            </div>

            <div
              v-if="selectedNode.data.chartType === 'barGauge'"
              class="space-y-2"
            >
              <Label>Max (optional)</Label>
              <ExpressionInput
                :ref="(el: unknown) => setChartOutputExpressionInputRef('max', el)"
                :model-value="selectedNode.data.max === undefined || selectedNode.data.max === null ? '' : String(selectedNode.data.max)"
                placeholder="defaults to the largest row value"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Max"
                field-key="max"
                :navigation-enabled="chartOutputExpressionFieldCount > 1"
                :navigation-index="chartOutputExpressionFieldIndex('max')"
                :navigation-total="chartOutputExpressionFieldCount"
                @navigate="handleChartOutputExpressionFieldNavigate"
                @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('max', $event)"
              />
            </div>

            <div
              v-if="['numeric', 'gauge', 'barGauge'].includes(selectedNode.data.chartType || 'bar')"
              class="space-y-2"
            >
              <Label>Unit</Label>
              <ExpressionInput
                :ref="(el: unknown) => setChartOutputExpressionInputRef('unit', el)"
                :model-value="selectedNode.data.unit || ''"
                placeholder="e.g. USD, %, ms"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Unit"
                field-key="unit"
                :navigation-enabled="chartOutputExpressionFieldCount > 1"
                :navigation-index="chartOutputExpressionFieldIndex('unit')"
                :navigation-total="chartOutputExpressionFieldCount"
                @navigate="handleChartOutputExpressionFieldNavigate"
                @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('unit', $event)"
              />
            </div>

            <div class="space-y-2">
              <Label>Title</Label>
              <ExpressionInput
                :ref="(el: unknown) => setChartOutputExpressionInputRef('title', el)"
                :model-value="selectedNode.data.title || ''"
                placeholder="optional chart title"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Title"
                field-key="title"
                :navigation-enabled="chartOutputExpressionFieldCount > 1"
                :navigation-index="chartOutputExpressionFieldIndex('title')"
                :navigation-total="chartOutputExpressionFieldCount"
                @navigate="handleChartOutputExpressionFieldNavigate"
                @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('title', $event)"
              />
            </div>

            <div class="space-y-2">
              <Label>Website URL</Label>
              <ExpressionInput
                :ref="(el: unknown) => setChartOutputExpressionInputRef('url', el)"
                :model-value="selectedNode.data.url || ''"
                placeholder="https://… (optional)"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Website URL"
                field-key="url"
                :navigation-enabled="chartOutputExpressionFieldCount > 1"
                :navigation-index="chartOutputExpressionFieldIndex('url')"
                :navigation-total="chartOutputExpressionFieldCount"
                @navigate="handleChartOutputExpressionFieldNavigate"
                @register-field-index="onChartOutputRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('url', $event)"
              />
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
                field-key="message"
                @update:model-value="updateNodeData('message', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $ expressions like {{ exampleRef }} or $error.message
              </p>
            </div>
          </template>

          <template v-if="selectedNode.type === 'discord'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="discordCredentialOptions"
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
                ref="discordMessageInputRef"
                :model-value="selectedNode.data.message || ''"
                :placeholder="exampleRef"
                :rows="3"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Message"
                field-key="message"
                @update:model-value="updateNodeData('message', $event)"
              />
              <p class="text-xs text-muted-foreground">
                Use $ expressions like {{ exampleRef }} or $error.message
              </p>
            </div>

            <div class="space-y-2">
              <Label>Username (optional)</Label>
              <ExpressionInput
                ref="discordUsernameInputRef"
                :model-value="selectedNode.data.username || ''"
                placeholder="Heym Bot"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Username"
                field-key="username"
                @update:model-value="updateNodeData('username', $event)"
              />
            </div>

            <div class="space-y-2">
              <Label>Avatar URL (optional)</Label>
              <ExpressionInput
                ref="discordAvatarUrlInputRef"
                :model-value="selectedNode.data.avatarUrl || ''"
                placeholder="https://example.com/avatar.png"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Avatar URL"
                field-key="avatarUrl"
                @update:model-value="updateNodeData('avatarUrl', $event)"
              />
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
                field-key="chatId"
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
                field-key="message"
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
                ref="sendEmailToInputRef"
                :model-value="selectedNode.data.to || ''"
                placeholder="recipient@example.com"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                dialog-title="Edit To"
                navigation-enabled
                :navigation-index="0"
                :navigation-total="sendEmailExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="To"
                field-key="to"
                @update:model-value="updateNodeData('to', $event)"
                @navigate="handleSendEmailExpressionFieldNavigate"
                @register-field-index="onSendEmailRegisterExpressionFieldIndex"
              />
              <p class="text-xs text-muted-foreground">
                Recipient email (comma-separated for multiple)
              </p>
            </div>

            <div class="space-y-2">
              <Label>Cc</Label>
              <ExpressionInput
                ref="sendEmailCcInputRef"
                :model-value="selectedNode.data.cc || ''"
                placeholder="cc@example.com"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                dialog-title="Edit Cc"
                navigation-enabled
                :navigation-index="1"
                :navigation-total="sendEmailExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Cc"
                field-key="cc"
                @update:model-value="updateNodeData('cc', $event)"
                @navigate="handleSendEmailExpressionFieldNavigate"
                @register-field-index="onSendEmailRegisterExpressionFieldIndex"
              />
              <p class="text-xs text-muted-foreground">
                Carbon copy (comma-separated for multiple)
              </p>
            </div>

            <div class="space-y-2">
              <Label>Bcc</Label>
              <ExpressionInput
                ref="sendEmailBccInputRef"
                :model-value="selectedNode.data.bcc || ''"
                placeholder="bcc@example.com"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                dialog-title="Edit Bcc"
                navigation-enabled
                :navigation-index="2"
                :navigation-total="sendEmailExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Bcc"
                field-key="bcc"
                @update:model-value="updateNodeData('bcc', $event)"
                @navigate="handleSendEmailExpressionFieldNavigate"
                @register-field-index="onSendEmailRegisterExpressionFieldIndex"
              />
              <p class="text-xs text-muted-foreground">
                Blind carbon copy — hidden from other recipients
              </p>
            </div>

            <div class="space-y-2">
              <Label>Subject</Label>
              <ExpressionInput
                ref="sendEmailSubjectInputRef"
                :model-value="selectedNode.data.subject || ''"
                placeholder="Email Subject"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                dialog-title="Edit Subject"
                navigation-enabled
                :navigation-index="3"
                :navigation-total="sendEmailExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Subject"
                field-key="subject"
                @update:model-value="updateNodeData('subject', $event)"
                @navigate="handleSendEmailExpressionFieldNavigate"
                @register-field-index="onSendEmailRegisterExpressionFieldIndex"
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
                navigation-enabled
                :navigation-index="4"
                :navigation-total="sendEmailExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Body"
                field-key="emailBody"
                @update:model-value="updateNodeData('emailBody', $event)"
                @navigate="handleSendEmailExpressionFieldNavigate"
                @register-field-index="onSendEmailRegisterExpressionFieldIndex"
              />
              <p class="text-xs text-muted-foreground">
                Use $ expressions like {{ exampleRef }}
              </p>
            </div>

            <div class="space-y-2">
              <Label>Attachments</Label>
              <ExpressionInput
                ref="sendEmailAttachmentsInputRef"
                :model-value="selectedNode.data.attachments || ''"
                placeholder="$drive.id"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                expandable
                dialog-title="Edit Attachments"
                navigation-enabled
                :navigation-index="5"
                :navigation-total="sendEmailExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Attachments"
                field-key="attachments"
                @update:model-value="updateNodeData('attachments', $event)"
                @navigate="handleSendEmailExpressionFieldNavigate"
                @register-field-index="onSendEmailRegisterExpressionFieldIndex"
              />
              <p class="text-xs text-muted-foreground">
                Comma-separated Drive file IDs. Use $ expressions, e.g. an upstream Drive node's id.
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
                field-key="message"
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
                <div class="grid grid-cols-[4rem_auto_minmax(0,1fr)_auto_auto] items-center gap-1.5">
                  <Input
                    :model-value="mapping.key"
                    placeholder="key"
                    :class="[
                      'w-full font-mono text-xs',
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
                  <button
                    type="button"
                    class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-input bg-background text-muted-foreground shadow-sm transition-colors hover:bg-destructive/10 hover:text-destructive"
                    title="Remove"
                    @click="removeMappingField(index)"
                  >
                    <X class="w-3 h-3" />
                  </button>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    :field-key="mapping.key || `mapping_${index}`"
                  />
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
                field-key="variableValue"
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
                field-key="arrayExpression"
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
                field-key="redisKey"
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
                  field-key="redisValue"
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
              <Label>Database</Label>
              <Select
                :model-value="selectedNode.data.dbType || 'qdrant'"
                :options="ragDbTypeOptions"
                @update:model-value="
                  updateNodeData('dbType', $event);
                  updateNodeData('vectorStoreId', '');
                "
              />
              <p class="text-xs text-muted-foreground">
                Qdrant uses an external server; Postgres (pgvector) stores vectors in
                Heym's own database.
              </p>
            </div>

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
                  field-key="documentContent"
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
                  field-key="queryText"
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

          <template v-if="selectedNode.type === 'linear'">
            <div
              class="space-y-2"
              data-testid="linear-credential-field"
            >
              <Label>Linear Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="linearCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <p
                v-if="!selectedNode.data.credentialId"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Credential is required.
              </p>
            </div>

            <div
              class="space-y-2"
              data-testid="linear-operation-field"
            >
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.linearOperation || 'listIssues'"
                :options="linearOperationOptions"
                @update:model-value="updateNodeData('linearOperation', $event)"
              />
            </div>

            <label
              v-if="isLinearPaginatedOperation()"
              class="flex items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                :checked="!!selectedNode.data.linearReturnAll"
                @change="updateNodeData('linearReturnAll', ($event.target as HTMLInputElement).checked)"
              >
              <span>Return All</span>
            </label>

            <div
              v-if="isLinearPaginatedOperation() && !selectedNode.data.linearReturnAll"
              class="space-y-2"
              data-testid="linear-limit-field"
            >
              <Label>Limit</Label>
              <ExpressionInput
                ref="linearLimitExpressionInputRef"
                :model-value="selectedNode.data.linearLimit || '50'"
                placeholder="50"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearLimit')"
                @update:model-value="updateNodeData('linearLimit', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="isLinearPaginatedOperation() && !selectedNode.data.linearReturnAll"
              class="space-y-2"
              data-testid="linear-after-field"
            >
              <Label>After Cursor (Optional)</Label>
              <ExpressionInput
                ref="linearAfterExpressionInputRef"
                :model-value="selectedNode.data.linearAfter || ''"
                placeholder="pageInfo.endCursor from a previous list"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearAfter')"
                @update:model-value="updateNodeData('linearAfter', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'listIssues' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue' || selectedNode.data.linearOperation === 'listWorkflowStates' || selectedNode.data.linearOperation === 'listTeamMembers'"
              class="space-y-2"
              data-testid="linear-team-id-field"
            >
              <Label>
                Team ID
                <span v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'listWorkflowStates' || selectedNode.data.linearOperation === 'listTeamMembers'">*</span>
              </Label>
              <ExpressionInput
                ref="linearTeamIdExpressionInputRef"
                :model-value="selectedNode.data.linearTeamId || ''"
                placeholder="team UUID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearTeamId')"
                @update:model-value="updateNodeData('linearTeamId', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'listIssues' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
              class="space-y-2"
            >
              <Label>Project ID (Optional)</Label>
              <ExpressionInput
                ref="linearProjectIdExpressionInputRef"
                :model-value="selectedNode.data.linearProjectId || ''"
                placeholder="project UUID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearProjectId')"
                @update:model-value="updateNodeData('linearProjectId', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="isLinearIssueIdOperation()"
              class="space-y-2"
              data-testid="linear-issue-id-field"
            >
              <Label>
                Issue ID or Identifier
                <span>*</span>
              </Label>
              <ExpressionInput
                ref="linearIssueIdExpressionInputRef"
                :model-value="selectedNode.data.linearIssueId || ''"
                placeholder="ENG-123 or issue UUID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearIssueId')"
                @update:model-value="updateNodeData('linearIssueId', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
              class="space-y-2"
            >
              <Label>
                Title
                <span v-if="selectedNode.data.linearOperation === 'createIssue'">*</span>
              </Label>
              <ExpressionInput
                ref="linearTitleExpressionInputRef"
                :model-value="selectedNode.data.linearTitle || ''"
                placeholder="Issue title"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearTitle')"
                @update:model-value="updateNodeData('linearTitle', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
              class="space-y-2"
            >
              <Label>Description (Optional)</Label>
              <ExpressionInput
                ref="linearDescriptionExpressionInputRef"
                :model-value="selectedNode.data.linearDescription || ''"
                placeholder="$input.text"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearDescription')"
                @update:model-value="updateNodeData('linearDescription', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
              class="space-y-2"
            >
              <Label>State ID (Optional)</Label>
              <ExpressionInput
                ref="linearStateIdExpressionInputRef"
                :model-value="selectedNode.data.linearStateId || ''"
                placeholder="workflow state UUID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearStateId')"
                @update:model-value="updateNodeData('linearStateId', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'addIssueLink'"
              class="space-y-2"
            >
              <Label>
                Link URL
                <span>*</span>
              </Label>
              <ExpressionInput
                ref="linearIssueLinkUrlExpressionInputRef"
                :model-value="selectedNode.data.linearIssueLinkUrl || ''"
                placeholder="https://example.com"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearIssueLinkUrl')"
                @update:model-value="updateNodeData('linearIssueLinkUrl', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
              class="grid grid-cols-2 gap-3"
            >
              <div class="space-y-2">
                <Label>Assignee ID</Label>
                <ExpressionInput
                  ref="linearAssigneeIdExpressionInputRef"
                  :model-value="selectedNode.data.linearAssigneeId || ''"
                  placeholder="user UUID"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  v-bind="linearExpressionNavBindings('linearAssigneeId')"
                  @update:model-value="updateNodeData('linearAssigneeId', $event)"
                  @navigate="handleLinearExpressionFieldNavigate"
                  @register-field-index="onLinearRegisterExpressionFieldIndex"
                />
              </div>
              <div class="space-y-2">
                <Label>Priority (0–4)</Label>
                <ExpressionInput
                  ref="linearPriorityExpressionInputRef"
                  :model-value="selectedNode.data.linearPriority || ''"
                  placeholder="0"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  v-bind="linearExpressionNavBindings('linearPriority')"
                  @update:model-value="updateNodeData('linearPriority', $event)"
                  @navigate="handleLinearExpressionFieldNavigate"
                  @register-field-index="onLinearRegisterExpressionFieldIndex"
                />
              </div>
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'updateIssue'"
              class="text-xs text-muted-foreground"
            >
              Leave optional update fields empty to keep their current values. Set a field to
              <code class="font-mono">null</code> to clear description, project, assignee, or state.
            </div>

            <div
              v-if="isLinearCommentIdOperation()"
              class="space-y-2"
              data-testid="linear-comment-id-field"
            >
              <Label>
                Comment ID
                <span>*</span>
              </Label>
              <ExpressionInput
                ref="linearCommentIdExpressionInputRef"
                :model-value="selectedNode.data.linearCommentId || ''"
                placeholder="comment UUID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearCommentId')"
                @update:model-value="updateNodeData('linearCommentId', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'createComment' || selectedNode.data.linearOperation === 'updateComment'"
              class="space-y-2"
              data-testid="linear-comment-body-field"
            >
              <Label>Comment Body</Label>
              <ExpressionInput
                ref="linearCommentBodyExpressionInputRef"
                :model-value="selectedNode.data.linearCommentBody || '$input.text'"
                placeholder="$input.text"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearCommentBody')"
                @update:model-value="updateNodeData('linearCommentBody', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div
              v-if="selectedNode.data.linearOperation === 'createComment'"
              class="space-y-2"
              data-testid="linear-parent-comment-id-field"
            >
              <Label>Parent Comment ID (Optional)</Label>
              <ExpressionInput
                ref="linearParentCommentIdExpressionInputRef"
                :model-value="selectedNode.data.linearParentCommentId || ''"
                placeholder="comment UUID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                v-bind="linearExpressionNavBindings('linearParentCommentId')"
                @update:model-value="updateNodeData('linearParentCommentId', $event)"
                @navigate="handleLinearExpressionFieldNavigate"
                @register-field-index="onLinearRegisterExpressionFieldIndex"
              />
            </div>

            <div class="p-3 rounded-lg bg-muted/50 space-y-1">
              <div class="text-xs font-medium">
                Output
              </div>
              <div class="text-xs text-muted-foreground font-mono space-y-0.5">
                <div>${{ selectedNode.data.label }}.success - Boolean</div>
                <div>${{ selectedNode.data.label }}.operation - String</div>
                <div v-if="selectedNode.data.linearOperation === 'getViewer'">
                  ${{ selectedNode.data.label }}.viewer - User
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'listTeams'">
                  ${{ selectedNode.data.label }}.teams - Team array
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'listProjects'">
                  ${{ selectedNode.data.label }}.projects - Project array
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'listIssues'">
                  ${{ selectedNode.data.label }}.issues - Issue array
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'listWorkflowStates'">
                  ${{ selectedNode.data.label }}.states - Workflow state array
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'listTeamMembers'">
                  ${{ selectedNode.data.label }}.members - Team member array
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'listComments'">
                  ${{ selectedNode.data.label }}.comments - Comment array
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'createComment' || selectedNode.data.linearOperation === 'updateComment' || selectedNode.data.linearOperation === 'resolveComment' || selectedNode.data.linearOperation === 'unresolveComment'">
                  ${{ selectedNode.data.label }}.comment - Comment
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'addIssueLink'">
                  ${{ selectedNode.data.label }}.link - Link result
                </div>
                <div v-else-if="selectedNode.data.linearOperation === 'deleteIssue' || selectedNode.data.linearOperation === 'deleteComment'">
                  ${{ selectedNode.data.label }}.deleted - Boolean
                </div>
                <div v-if="selectedNode.data.linearOperation === 'deleteComment'">
                  ${{ selectedNode.data.label }}.entityId - Deleted comment ID
                </div>
                <div v-if="selectedNode.data.linearOperation === 'getIssue' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'">
                  ${{ selectedNode.data.label }}.issue - Issue
                </div>
                <div
                  v-if="isLinearPaginatedOperation() || selectedNode.data.linearOperation === 'listWorkflowStates'"
                >
                  ${{ selectedNode.data.label }}.count - Number
                </div>
                <div
                  v-if="isLinearPaginatedOperation()"
                >
                  ${{ selectedNode.data.label }}.pageInfo.hasNextPage - Boolean
                </div>
                <div
                  v-if="isLinearPaginatedOperation()"
                >
                  ${{ selectedNode.data.label }}.pageInfo.endCursor - String
                </div>
                <div
                  v-if="selectedNode.data.linearOperation === 'getIssue' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
                >
                  ${{ selectedNode.data.label }}.identifier - String
                </div>
                <div
                  v-if="selectedNode.data.linearOperation === 'getIssue' || selectedNode.data.linearOperation === 'createIssue' || selectedNode.data.linearOperation === 'updateIssue'"
                >
                  ${{ selectedNode.data.label }}.url - String
                </div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'github'">
            <div class="space-y-2">
              <Label>GitHub Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="githubCredentialOptions"
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
                :model-value="selectedNode.data.githubOperation || 'getRepository'"
                :options="githubOperationOptions"
                @update:model-value="updateNodeData('githubOperation', $event)"
              />
            </div>

            <div
              class="grid gap-3"
              :class="isGitHubRepoRequired(selectedNode.data.githubOperation) ? 'grid-cols-2' : 'grid-cols-1'"
            >
              <div
                v-if="isGitHubOwnerRequired(selectedNode.data.githubOperation)"
                class="space-y-2"
              >
                <Label>
                  {{ selectedNode.data.githubOperation === 'listOrganizationRepositories' ? 'Organization' : 'Owner' }}
                </Label>
                <ExpressionInput
                  ref="githubOwnerExpressionInputRef"
                  :model-value="selectedNode.data.githubOwner || ''"
                  placeholder="octocat"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubOwner"
                  v-bind="githubExpressionNavBindings('githubOwner')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubOwner', $event)"
                />
              </div>
              <div
                v-if="isGitHubRepoRequired(selectedNode.data.githubOperation)"
                class="space-y-2"
              >
                <Label>Repository</Label>
                <ExpressionInput
                  ref="githubRepoExpressionInputRef"
                  :model-value="selectedNode.data.githubRepo || ''"
                  placeholder="hello-world"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubRepo"
                  v-bind="githubExpressionNavBindings('githubRepo')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubRepo', $event)"
                />
              </div>
            </div>

            <template v-if="selectedNode.data.githubOperation === 'inviteUser'">
              <div class="space-y-2">
                <Label>Organization</Label>
                <ExpressionInput
                  ref="githubOrganizationExpressionInputRef"
                  :model-value="selectedNode.data.githubOrganization || ''"
                  placeholder="octo-org"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubOrganization"
                  v-bind="githubExpressionNavBindings('githubOrganization')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubOrganization', $event)"
                />
              </div>
              <div class="space-y-2">
                <Label>Email</Label>
                <ExpressionInput
                  ref="githubInviteEmailExpressionInputRef"
                  :model-value="selectedNode.data.githubInviteEmail || ''"
                  placeholder="user@example.com"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubInviteEmail"
                  v-bind="githubExpressionNavBindings('githubInviteEmail')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubInviteEmail', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'getIssue' || selectedNode.data.githubOperation === 'updateIssue' || selectedNode.data.githubOperation === 'createComment' || selectedNode.data.githubOperation === 'lockIssue'">
              <div class="space-y-2">
                <Label>Issue Number</Label>
                <ExpressionInput
                  ref="githubIssueNumberExpressionInputRef"
                  :model-value="selectedNode.data.githubIssueNumber || ''"
                  placeholder="123"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubIssueNumber"
                  v-bind="githubExpressionNavBindings('githubIssueNumber')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubIssueNumber', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues' || selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests' || selectedNode.data.githubOperation === 'updateIssue'">
              <div
                class="grid gap-3"
                :class="usesGitHubPerPage(selectedNode.data.githubOperation) ? 'grid-cols-2' : 'grid-cols-1'"
              >
                <div class="space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <Label>State</Label>
                    <AgentFieldToggle
                      :node-id="selectedNode.id"
                      field-key="githubState"
                    />
                  </div>
                  <Select
                    :model-value="selectedNode.data.githubOperation === 'updateIssue' ? (selectedNode.data.githubState ?? '') : (selectedNode.data.githubState || 'open')"
                    :options="selectedNode.data.githubOperation === 'updateIssue' ? githubUpdateIssueStateOptions : githubStateOptions"
                    @update:model-value="updateNodeData('githubState', $event)"
                  />
                </div>
                <div
                  v-if="usesGitHubPerPage(selectedNode.data.githubOperation)"
                  class="space-y-2"
                >
                  <div class="flex items-center justify-between gap-2">
                    <Label>Per Page</Label>
                    <AgentFieldToggle
                      :node-id="selectedNode.id"
                      field-key="githubPerPage"
                    />
                  </div>
                  <Input
                    type="number"
                    min="1"
                    max="100"
                    :model-value="selectedNode.data.githubPerPage || '30'"
                    placeholder="30"
                    @update:model-value="updateNodeData('githubPerPage', $event)"
                  />
                </div>
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues'">
              <div class="grid grid-cols-2 gap-3">
                <div
                  v-if="selectedNode.data.githubOperation !== 'getUserIssues'"
                  class="space-y-2"
                >
                  <Label>Assignee</Label>
                  <ExpressionInput
                    ref="githubAssigneeExpressionInputRef"
                    :model-value="selectedNode.data.githubAssignee || ''"
                    placeholder="octocat"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubAssignee"
                    v-bind="githubExpressionNavBindings('githubAssignee')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubAssignee', $event)"
                  />
                </div>
                <div
                  v-if="selectedNode.data.githubOperation !== 'getUserIssues'"
                  class="space-y-2"
                >
                  <Label>Creator</Label>
                  <ExpressionInput
                    ref="githubCreatorExpressionInputRef"
                    :model-value="selectedNode.data.githubCreator || ''"
                    placeholder="octocat"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubCreator"
                    v-bind="githubExpressionNavBindings('githubCreator')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubCreator', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <Label>
                    {{ selectedNode.data.githubOperation === 'getUserIssues' ? 'Mentioned Filter' : 'Mentioned User' }}
                  </Label>
                  <ExpressionInput
                    ref="githubMentionedExpressionInputRef"
                    :model-value="selectedNode.data.githubMentioned || ''"
                    :placeholder="selectedNode.data.githubOperation === 'getUserIssues' ? 'true' : 'octocat'"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubMentioned"
                    v-bind="githubExpressionNavBindings('githubMentioned')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubMentioned', $event)"
                  />
                  <p
                    v-if="selectedNode.data.githubOperation === 'getUserIssues'"
                    class="text-xs text-muted-foreground"
                  >
                    Set any non-empty value to return issues mentioning the authenticated user
                    instead of issues assigned to them.
                  </p>
                </div>
                <div class="space-y-2">
                  <Label>Labels</Label>
                  <ExpressionInput
                    ref="githubLabelsFilterExpressionInputRef"
                    :model-value="selectedNode.data.githubLabelsFilter || ''"
                    placeholder="bug,backend"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubLabelsFilter"
                    v-bind="githubExpressionNavBindings('githubLabelsFilter')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubLabelsFilter', $event)"
                  />
                </div>
              </div>
              <div class="space-y-2">
                <Label>Updated Since</Label>
                <ExpressionInput
                  ref="githubSinceExpressionInputRef"
                  :model-value="selectedNode.data.githubSince || ''"
                  placeholder="2026-01-01T00:00:00Z"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubSince"
                  v-bind="githubExpressionNavBindings('githubSince')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubSince', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues' || selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests'">
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <Label>Sort</Label>
                    <AgentFieldToggle
                      :node-id="selectedNode.id"
                      field-key="githubSort"
                    />
                  </div>
                  <Select
                    :model-value="selectedNode.data.githubSort || ''"
                    :options="selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests' ? githubPullRequestSortOptions : githubIssueSortOptions"
                    @update:model-value="updateNodeData('githubSort', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <Label>Direction</Label>
                    <AgentFieldToggle
                      :node-id="selectedNode.id"
                      field-key="githubDirection"
                    />
                  </div>
                  <Select
                    :model-value="selectedNode.data.githubDirection || ''"
                    :options="githubDirectionOptions"
                    @update:model-value="updateNodeData('githubDirection', $event)"
                  />
                </div>
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'updateIssue'">
              <div class="space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <Label>State Reason</Label>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="githubStateReason"
                  />
                </div>
                <Select
                  :model-value="selectedNode.data.githubStateReason ?? ''"
                  :options="githubIssueStateReasonOptions"
                  @update:model-value="updateNodeData('githubStateReason', $event)"
                />
              </div>
            </template>

            <template v-if="usesGitHubPerPage(selectedNode.data.githubOperation) && selectedNode.data.githubOperation !== 'listIssues' && selectedNode.data.githubOperation !== 'listPullRequests'">
              <div class="space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <Label>Per Page</Label>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="githubPerPage"
                  />
                </div>
                <Input
                  type="number"
                  min="1"
                  max="100"
                  :model-value="selectedNode.data.githubPerPage || '30'"
                  placeholder="30"
                  @update:model-value="updateNodeData('githubPerPage', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue' || selectedNode.data.githubOperation === 'createPullRequest' || selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
              <div class="space-y-2">
                <Label>{{ selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease' ? 'Name / Title' : 'Title' }}</Label>
                <ExpressionInput
                  ref="githubTitleExpressionInputRef"
                  :model-value="selectedNode.data.githubTitle || ''"
                  placeholder="Fix flaky workflow run"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubTitle"
                  v-bind="githubExpressionNavBindings('githubTitle')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubTitle', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue' || selectedNode.data.githubOperation === 'createPullRequest' || selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
              <div class="space-y-2">
                <Label>Body</Label>
                <ExpressionInput
                  ref="githubBodyExpressionInputRef"
                  :model-value="selectedNode.data.githubBody || ''"
                  placeholder="$input.text"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubBody"
                  v-bind="githubExpressionNavBindings('githubBody')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubBody', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createComment'">
              <div class="space-y-2">
                <Label>Comment Body</Label>
                <ExpressionInput
                  ref="githubCommentBodyExpressionInputRef"
                  :model-value="selectedNode.data.githubCommentBody || '$input.text'"
                  placeholder="$input.text"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubCommentBody"
                  v-bind="githubExpressionNavBindings('githubCommentBody')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubCommentBody', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue'">
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-2">
                  <Label>Labels (JSON Array)</Label>
                  <ExpressionInput
                    ref="githubLabelsExpressionInputRef"
                    :model-value="selectedNode.data.githubLabels ?? ''"
                    placeholder="[&quot;bug&quot;, &quot;backend&quot;]"
                    :rows="2"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubLabels"
                    v-bind="githubExpressionNavBindings('githubLabels')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubLabels', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <Label>Assignees (JSON Array)</Label>
                  <ExpressionInput
                    ref="githubAssigneesExpressionInputRef"
                    :model-value="selectedNode.data.githubAssignees ?? ''"
                    placeholder="[&quot;octocat&quot;]"
                    :rows="2"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubAssignees"
                    v-bind="githubExpressionNavBindings('githubAssignees')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubAssignees', $event)"
                  />
                </div>
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'lockIssue'">
              <div class="space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <Label>Lock Reason</Label>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="githubLockReason"
                  />
                </div>
                <Select
                  :model-value="selectedNode.data.githubLockReason ?? ''"
                  :options="githubLockReasonOptions"
                  @update:model-value="updateNodeData('githubLockReason', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createPullRequest'">
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-2">
                  <Label>Head Branch</Label>
                  <ExpressionInput
                    ref="githubHeadExpressionInputRef"
                    :model-value="selectedNode.data.githubHead || ''"
                    placeholder="feature/my-branch"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubHead"
                    v-bind="githubExpressionNavBindings('githubHead')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubHead', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <Label>Base Branch</Label>
                  <ExpressionInput
                    ref="githubBaseExpressionInputRef"
                    :model-value="selectedNode.data.githubBase || 'main'"
                    placeholder="main"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubBase"
                    v-bind="githubExpressionNavBindings('githubBase')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubBase', $event)"
                  />
                </div>
              </div>
              <div class="flex items-center gap-2">
                <input
                  id="github-draft-pr"
                  type="checkbox"
                  :checked="selectedNode.data.githubDraft === true"
                  class="rounded border-border"
                  @change="updateNodeData('githubDraft', ($event.target as HTMLInputElement).checked)"
                >
                <label
                  for="github-draft-pr"
                  class="text-sm cursor-pointer select-none"
                >Create as draft pull request</label>
                <AgentFieldToggle
                  :node-id="selectedNode.id"
                  field-key="githubDraft"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createReview' || selectedNode.data.githubOperation === 'getReview' || selectedNode.data.githubOperation === 'listReviews' || selectedNode.data.githubOperation === 'updateReview'">
              <div class="space-y-2">
                <Label>Pull Request Number</Label>
                <ExpressionInput
                  ref="githubPullRequestNumberExpressionInputRef"
                  :model-value="selectedNode.data.githubPullRequestNumber || ''"
                  placeholder="123"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubPullRequestNumber"
                  v-bind="githubExpressionNavBindings('githubPullRequestNumber')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubPullRequestNumber', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'getReview' || selectedNode.data.githubOperation === 'updateReview'">
              <div class="space-y-2">
                <Label>Review ID</Label>
                <ExpressionInput
                  ref="githubReviewIdExpressionInputRef"
                  :model-value="selectedNode.data.githubReviewId || ''"
                  placeholder="987654"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubReviewId"
                  v-bind="githubExpressionNavBindings('githubReviewId')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubReviewId', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createReview'">
              <div class="space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <Label>Review Event</Label>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="githubReviewEvent"
                  />
                </div>
                <Select
                  :model-value="selectedNode.data.githubReviewEvent || 'APPROVE'"
                  :options="githubReviewEventOptions"
                  @update:model-value="updateNodeData('githubReviewEvent', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createReview' || selectedNode.data.githubOperation === 'updateReview'">
              <div class="space-y-2">
                <Label>Review Body</Label>
                <ExpressionInput
                  ref="githubReviewBodyExpressionInputRef"
                  :model-value="selectedNode.data.githubReviewBody || ''"
                  placeholder="Looks good to me"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubReviewBody"
                  v-bind="githubExpressionNavBindings('githubReviewBody')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubReviewBody', $event)"
                />
                <p
                  v-if="selectedNode.data.githubOperation === 'createReview'"
                  class="text-xs text-muted-foreground"
                >
                  Required for Comment and Request Changes events.
                </p>
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createReview'">
              <div class="space-y-2">
                <Label>Commit ID <span class="text-muted-foreground font-normal">(optional)</span></Label>
                <ExpressionInput
                  ref="githubCommitIdExpressionInputRef"
                  :model-value="selectedNode.data.githubCommitId || ''"
                  placeholder="Latest PR commit when empty"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubCommitId"
                  v-bind="githubExpressionNavBindings('githubCommitId')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubCommitId', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'getRelease' || selectedNode.data.githubOperation === 'updateRelease' || selectedNode.data.githubOperation === 'deleteRelease'">
              <div class="space-y-2">
                <Label>Release ID</Label>
                <ExpressionInput
                  ref="githubReleaseIdExpressionInputRef"
                  :model-value="selectedNode.data.githubReleaseId || ''"
                  placeholder="123456"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubReleaseId"
                  v-bind="githubExpressionNavBindings('githubReleaseId')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubReleaseId', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-2">
                  <Label>Tag Name</Label>
                  <ExpressionInput
                    ref="githubTagNameExpressionInputRef"
                    :model-value="selectedNode.data.githubTagName || ''"
                    placeholder="v1.2.3"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubTagName"
                    v-bind="githubExpressionNavBindings('githubTagName')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubTagName', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <Label>Target Commitish / Branch</Label>
                  <ExpressionInput
                    ref="githubBranchExpressionInputRef"
                    :model-value="selectedNode.data.githubBranch || ''"
                    placeholder="main"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="githubBranch"
                    v-bind="githubExpressionNavBindings('githubBranch')"
                    @navigate="handleGitHubExpressionFieldNavigate"
                    @register-field-index="onGitHubRegisterExpressionFieldIndex"
                    @update:model-value="updateNodeData('githubBranch', $event)"
                  />
                </div>
              </div>
              <div class="flex items-center gap-4">
                <label class="flex items-center gap-2 text-sm cursor-pointer select-none">
                  <input
                    id="github-release-draft"
                    type="checkbox"
                    :checked="selectedNode.data.githubDraft === true"
                    class="rounded border-border"
                    @change="updateNodeData('githubDraft', ($event.target as HTMLInputElement).checked)"
                  >
                  <span>Draft release</span>
                </label>
                <AgentFieldToggle
                  :node-id="selectedNode.id"
                  field-key="githubDraft"
                />
                <label class="flex items-center gap-2 text-sm cursor-pointer select-none">
                  <input
                    id="github-release-prerelease"
                    type="checkbox"
                    :checked="selectedNode.data.githubPrerelease === true"
                    class="rounded border-border"
                    @change="updateNodeData('githubPrerelease', ($event.target as HTMLInputElement).checked)"
                  >
                  <span>Prerelease</span>
                </label>
                <AgentFieldToggle
                  :node-id="selectedNode.id"
                  field-key="githubPrerelease"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'getWorkflow' || selectedNode.data.githubOperation === 'dispatchWorkflow' || selectedNode.data.githubOperation === 'dispatchWorkflowAndWait' || selectedNode.data.githubOperation === 'enableWorkflow' || selectedNode.data.githubOperation === 'disableWorkflow' || selectedNode.data.githubOperation === 'getWorkflowUsage'">
              <div class="space-y-2">
                <Label>Workflow ID or File Name</Label>
                <ExpressionInput
                  ref="githubWorkflowIdExpressionInputRef"
                  :model-value="selectedNode.data.githubWorkflowId || ''"
                  placeholder="build.yml"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubWorkflowId"
                  v-bind="githubExpressionNavBindings('githubWorkflowId')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubWorkflowId', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'dispatchWorkflow' || selectedNode.data.githubOperation === 'dispatchWorkflowAndWait'">
              <div class="space-y-2">
                <Label>Ref or Branch</Label>
                <ExpressionInput
                  ref="githubBranchExpressionInputRef"
                  :model-value="selectedNode.data.githubBranch || ''"
                  placeholder="main"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubBranch"
                  v-bind="githubExpressionNavBindings('githubBranch')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubBranch', $event)"
                />
              </div>
              <div class="space-y-2">
                <Label>Workflow Inputs (JSON Object)</Label>
                <ExpressionInput
                  ref="githubWorkflowInputsExpressionInputRef"
                  :model-value="selectedNode.data.githubWorkflowInputs ?? ''"
                  placeholder="{&quot;environment&quot;:&quot;prod&quot;}"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubWorkflowInputs"
                  v-bind="githubExpressionNavBindings('githubWorkflowInputs')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubWorkflowInputs', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'dispatchWorkflowAndWait'">
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <Label>Wait Timeout (seconds)</Label>
                    <AgentFieldToggle
                      :node-id="selectedNode.id"
                      field-key="githubWaitTimeoutSeconds"
                    />
                  </div>
                  <Input
                    type="number"
                    min="1"
                    :model-value="selectedNode.data.githubWaitTimeoutSeconds || '600'"
                    @update:model-value="updateNodeData('githubWaitTimeoutSeconds', $event)"
                  />
                </div>
                <div class="space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <Label>Poll Interval (seconds)</Label>
                    <AgentFieldToggle
                      :node-id="selectedNode.id"
                      field-key="githubPollIntervalSeconds"
                    />
                  </div>
                  <Input
                    type="number"
                    min="0.1"
                    step="0.1"
                    :model-value="selectedNode.data.githubPollIntervalSeconds || '5'"
                    @update:model-value="updateNodeData('githubPollIntervalSeconds', $event)"
                  />
                </div>
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'getFile' || selectedNode.data.githubOperation === 'listFiles' || selectedNode.data.githubOperation === 'upsertFile' || selectedNode.data.githubOperation === 'deleteFile'">
              <div class="space-y-2">
                <Label>{{ selectedNode.data.githubOperation === 'listFiles' ? 'Directory Path' : 'File Path' }}</Label>
                <ExpressionInput
                  ref="githubFilePathExpressionInputRef"
                  :model-value="selectedNode.data.githubFilePath || ''"
                  placeholder="docs/README.md"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubFilePath"
                  v-bind="githubExpressionNavBindings('githubFilePath')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubFilePath', $event)"
                />
              </div>
              <div class="space-y-2">
                <Label>{{ selectedNode.data.githubOperation === 'getFile' || selectedNode.data.githubOperation === 'listFiles' ? 'Ref or Branch' : 'Target Branch' }}</Label>
                <ExpressionInput
                  ref="githubBranchExpressionInputRef"
                  :model-value="selectedNode.data.githubBranch || ''"
                  placeholder="main"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubBranch"
                  v-bind="githubExpressionNavBindings('githubBranch')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubBranch', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'upsertFile' || selectedNode.data.githubOperation === 'deleteFile'">
              <div class="space-y-2">
                <Label>Commit Message</Label>
                <ExpressionInput
                  ref="githubCommitMessageExpressionInputRef"
                  :model-value="selectedNode.data.githubCommitMessage || ''"
                  placeholder="Update generated report"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubCommitMessage"
                  v-bind="githubExpressionNavBindings('githubCommitMessage')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubCommitMessage', $event)"
                />
              </div>
            </template>

            <template v-if="selectedNode.data.githubOperation === 'upsertFile'">
              <div class="space-y-2">
                <Label>File Content</Label>
                <ExpressionInput
                  ref="githubFileContentExpressionInputRef"
                  :model-value="selectedNode.data.githubFileContent || '$input.text'"
                  placeholder="$input.text"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="githubFileContent"
                  v-bind="githubExpressionNavBindings('githubFileContent')"
                  @navigate="handleGitHubExpressionFieldNavigate"
                  @register-field-index="onGitHubRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('githubFileContent', $event)"
                />
              </div>
            </template>

            <div class="space-y-2 pt-2 border-t">
              <Label class="text-muted-foreground">Output</Label>
              <div class="text-xs font-mono space-y-1 text-muted-foreground">
                <template v-if="selectedNode.data.githubOperation === 'getRepository'">
                  <div>${{ selectedNode.data.label }}.repository - Repository payload</div>
                  <div>${{ selectedNode.data.label }}.full_name - owner/repo</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getRepositoryLicense'">
                  <div>${{ selectedNode.data.label }}.license - License payload</div>
                  <div>${{ selectedNode.data.label }}.spdx_id - SPDX identifier</div>
                  <div>${{ selectedNode.data.label }}.content - Decoded license content</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getRepositoryProfile'">
                  <div>${{ selectedNode.data.label }}.profile - Community profile payload</div>
                  <div>${{ selectedNode.data.label }}.health_percentage - Health score</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listPopularPaths'">
                  <div>${{ selectedNode.data.label }}.paths - Popular path array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of paths</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listReferrers'">
                  <div>${{ selectedNode.data.label }}.referrers - Referrer array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of referrers</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listOrganizationRepositories' || selectedNode.data.githubOperation === 'listUserRepositories' || selectedNode.data.githubOperation === 'getUserRepositories'">
                  <div>${{ selectedNode.data.label }}.repositories - Repository array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of repositories</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'inviteUser'">
                  <div>${{ selectedNode.data.label }}.invitation - Invitation payload</div>
                  <div>${{ selectedNode.data.label }}.id - Invitation ID</div>
                  <div>${{ selectedNode.data.label }}.email - Invited email</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getIssue' || selectedNode.data.githubOperation === 'createIssue' || selectedNode.data.githubOperation === 'updateIssue'">
                  <div>${{ selectedNode.data.label }}.issue - Issue payload</div>
                  <div>${{ selectedNode.data.label }}.number - Issue number</div>
                  <div>${{ selectedNode.data.label }}.url - GitHub URL</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'createComment'">
                  <div>${{ selectedNode.data.label }}.comment - Comment payload</div>
                  <div>${{ selectedNode.data.label }}.id - Comment ID</div>
                  <div>${{ selectedNode.data.label }}.url - Comment URL</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'lockIssue'">
                  <div>${{ selectedNode.data.label }}.locked - Boolean</div>
                  <div>${{ selectedNode.data.label }}.issue_number - Locked issue number</div>
                  <div>${{ selectedNode.data.label }}.lock_reason - Lock reason if provided</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listIssues' || selectedNode.data.githubOperation === 'getRepositoryIssues' || selectedNode.data.githubOperation === 'getUserIssues'">
                  <div>${{ selectedNode.data.label }}.issues - Issue array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of issues</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listPullRequests' || selectedNode.data.githubOperation === 'getRepositoryPullRequests'">
                  <div>${{ selectedNode.data.label }}.pull_requests - PR array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of pull requests</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'createPullRequest'">
                  <div>${{ selectedNode.data.label }}.pull_request - PR payload</div>
                  <div>${{ selectedNode.data.label }}.number - Pull request number</div>
                  <div>${{ selectedNode.data.label }}.url - Pull request URL</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getReview' || selectedNode.data.githubOperation === 'createReview' || selectedNode.data.githubOperation === 'updateReview'">
                  <div>${{ selectedNode.data.label }}.review - Review payload</div>
                  <div>${{ selectedNode.data.label }}.id - Review ID</div>
                  <div>${{ selectedNode.data.label }}.state - Review state</div>
                  <div>${{ selectedNode.data.label }}.url - Review URL</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listReviews'">
                  <div>${{ selectedNode.data.label }}.reviews - Review array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of reviews</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listReleases'">
                  <div>${{ selectedNode.data.label }}.releases - Release array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of releases</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getRelease' || selectedNode.data.githubOperation === 'createRelease' || selectedNode.data.githubOperation === 'updateRelease'">
                  <div>${{ selectedNode.data.label }}.release - Release payload</div>
                  <div>${{ selectedNode.data.label }}.id - Release ID</div>
                  <div>${{ selectedNode.data.label }}.tag_name - Tag name</div>
                  <div>${{ selectedNode.data.label }}.url - Release URL</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'deleteRelease'">
                  <div>${{ selectedNode.data.label }}.deleted - Boolean</div>
                  <div>${{ selectedNode.data.label }}.release_id - Deleted release ID</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listWorkflows'">
                  <div>${{ selectedNode.data.label }}.workflows - Workflow array</div>
                  <div>${{ selectedNode.data.label }}.count - Number of workflows</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getWorkflow'">
                  <div>${{ selectedNode.data.label }}.workflow - Workflow payload</div>
                  <div>${{ selectedNode.data.label }}.id - Workflow ID</div>
                  <div>${{ selectedNode.data.label }}.path - Workflow file path</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'enableWorkflow'">
                  <div>${{ selectedNode.data.label }}.enabled - Boolean</div>
                  <div>${{ selectedNode.data.label }}.workflow_id - Workflow target</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'disableWorkflow'">
                  <div>${{ selectedNode.data.label }}.disabled - Boolean</div>
                  <div>${{ selectedNode.data.label }}.workflow_id - Workflow target</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getWorkflowUsage'">
                  <div>${{ selectedNode.data.label }}.usage - Workflow usage payload</div>
                  <div>${{ selectedNode.data.label }}.billable - Usage by runner OS</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'dispatchWorkflow'">
                  <div>${{ selectedNode.data.label }}.dispatched - Boolean</div>
                  <div>${{ selectedNode.data.label }}.workflow_id - Workflow target</div>
                  <div>${{ selectedNode.data.label }}.ref - Workflow ref</div>
                  <div>${{ selectedNode.data.label }}.inputs - Dispatch inputs object</div>
                  <div>${{ selectedNode.data.label }}.workflow_run_id - Run ID when returned</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'dispatchWorkflowAndWait'">
                  <div>${{ selectedNode.data.label }}.completed - Boolean</div>
                  <div>${{ selectedNode.data.label }}.workflow_run - Completed run payload</div>
                  <div>${{ selectedNode.data.label }}.conclusion - Run conclusion</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'listFiles'">
                  <div>${{ selectedNode.data.label }}.path - Directory path</div>
                  <div>${{ selectedNode.data.label }}.items - Directory entries</div>
                  <div>${{ selectedNode.data.label }}.count - Number of items</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'getFile'">
                  <div>${{ selectedNode.data.label }}.file - File payload</div>
                  <div>${{ selectedNode.data.label }}.path - Repository path</div>
                  <div>${{ selectedNode.data.label }}.sha - File SHA</div>
                  <div>${{ selectedNode.data.label }}.content - Decoded text content</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'upsertFile'">
                  <div>${{ selectedNode.data.label }}.file - File payload</div>
                  <div>${{ selectedNode.data.label }}.path - Repository path</div>
                  <div>${{ selectedNode.data.label }}.sha - File SHA</div>
                  <div>${{ selectedNode.data.label }}.commit_sha - Commit SHA</div>
                  <div>${{ selectedNode.data.label }}.created - True when file was newly created</div>
                </template>
                <template v-else-if="selectedNode.data.githubOperation === 'deleteFile'">
                  <div>${{ selectedNode.data.label }}.deleted - Boolean</div>
                  <div>${{ selectedNode.data.label }}.path - Deleted repository path</div>
                  <div>${{ selectedNode.data.label }}.sha - Deleted file SHA</div>
                  <div>${{ selectedNode.data.label }}.commit_sha - Deletion commit SHA</div>
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
                  field-key="gsSpreadsheetId"
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
                  field-key="gsSheetName"
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
                    field-key="bqQuery"
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
                    field-key="bqRows"
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

          <template v-if="selectedNode.type === 'supabase'">
            <div class="space-y-2">
              <Label>Supabase Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="supabaseCredentialOptions"
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
                :model-value="selectedNode.data.supabaseOperation || ''"
                :options="supabaseOperationOptions"
                @update:model-value="updateNodeData('supabaseOperation', $event)"
              />
            </div>

            <div class="space-y-2">
              <Label>Schema</Label>
              <ExpressionInput
                ref="supabaseSchemaExpressionInputRef"
                :model-value="selectedNode.data.supabaseSchema ?? 'public'"
                placeholder="public"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="supabaseSchema"
                :navigation-enabled="supabaseExpressionFieldCount > 1"
                :navigation-index="0"
                :navigation-total="supabaseExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Schema"
                @update:model-value="updateNodeData('supabaseSchema', $event)"
                @navigate="handleSupabaseExpressionFieldNavigate"
                @register-field-index="onSupabaseRegisterExpressionFieldIndex"
              />
            </div>

            <div class="space-y-2">
              <Label>Table</Label>
              <ExpressionInput
                ref="supabaseTableExpressionInputRef"
                :model-value="selectedNode.data.supabaseTable || ''"
                placeholder="users"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="supabaseTable"
                :navigation-enabled="supabaseExpressionFieldCount > 1"
                :navigation-index="1"
                :navigation-total="supabaseExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Table"
                @update:model-value="updateNodeData('supabaseTable', $event)"
                @navigate="handleSupabaseExpressionFieldNavigate"
                @register-field-index="onSupabaseRegisterExpressionFieldIndex"
              />
              <div class="flex items-center gap-2">
                <Select
                  :model-value="String(selectedNode.data.supabaseTable || '')"
                  :options="supabaseDiscoveredTableOptions"
                  placeholder="Discovered tables..."
                  :disabled="loadingSupabaseTables || supabaseDiscoveredTableOptions.length === 0"
                  @update:model-value="updateNodeData('supabaseTable', $event || '')"
                />
                <Button
                  variant="outline"
                  size="sm"
                  class="shrink-0"
                  :loading="loadingSupabaseTables"
                  :disabled="!selectedNode.data.credentialId"
                  @click="loadSupabaseTablesForSelectedNode"
                >
                  Refresh
                </Button>
              </div>
            </div>

            <template v-if="selectedNode.data.supabaseOperation === 'select'">
              <div class="space-y-2">
                <Label>Select Columns</Label>
                <ExpressionInput
                  ref="supabaseSelectColumnsExpressionInputRef"
                  :model-value="selectedNode.data.supabaseSelectColumns || '*'"
                  placeholder="id,name,email"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="supabaseSelectColumns"
                  :navigation-enabled="supabaseExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="supabaseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Select Columns"
                  @update:model-value="updateNodeData('supabaseSelectColumns', $event)"
                  @navigate="handleSupabaseExpressionFieldNavigate"
                  @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                />
                <div class="flex items-center justify-between gap-2">
                  <p class="text-xs text-muted-foreground">
                    Discover columns from the selected table, then click to add or remove them.
                  </p>
                  <div class="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      class="shrink-0"
                      :loading="loadingSupabaseColumns"
                      :disabled="!selectedNode.data.credentialId || !selectedNode.data.supabaseTable"
                      @click="loadSupabaseColumnsForSelectedNode"
                    >
                      Refresh
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="shrink-0"
                      :disabled="supabaseDiscoveredColumns.length === 0"
                      @click="useAllDiscoveredSupabaseColumns"
                    >
                      Use all
                    </Button>
                  </div>
                </div>
                <div
                  v-if="supabaseDiscoveredColumns.length > 0"
                  class="flex flex-wrap gap-2"
                >
                  <button
                    v-for="columnName in supabaseDiscoveredColumns"
                    :key="columnName"
                    type="button"
                    :class="[
                      'rounded-full border px-2 py-1 text-xs transition-colors',
                      parseSupabaseSelectedColumns(String(selectedNode.data.supabaseSelectColumns || '*')).includes(columnName)
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border text-muted-foreground hover:text-foreground hover:border-border/80'
                    ]"
                    @click="toggleSupabaseSelectedColumn(columnName)"
                  >
                    {{ columnName }}
                  </button>
                </div>
              </div>

              <div class="space-y-2">
                <Label>Filter (JSON object)</Label>
                <ExpressionInput
                  ref="supabaseFilterExpressionInputRef"
                  :model-value="selectedNode.data.supabaseFilter || '{}'"
                  placeholder="{&quot;status&quot;:&quot;active&quot;}"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="supabaseFilter"
                  :navigation-enabled="supabaseExpressionFieldCount > 1"
                  :navigation-index="3"
                  :navigation-total="supabaseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Filter"
                  @update:model-value="updateNodeData('supabaseFilter', $event)"
                  @navigate="handleSupabaseExpressionFieldNavigate"
                  @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                />
              </div>

              <div class="space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <Label>Limit <span class="text-muted-foreground font-normal">(0 = unlimited)</span></Label>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="supabaseLimit"
                  />
                </div>
                <input
                  type="number"
                  min="0"
                  :value="selectedNode.data.supabaseLimit ?? '100'"
                  placeholder="100"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  @input="updateNodeData('supabaseLimit', String(($event.target as HTMLInputElement).value))"
                >
              </div>

              <div class="space-y-2">
                <Label>Order By</Label>
                <ExpressionInput
                  ref="supabaseOrderByExpressionInputRef"
                  :model-value="selectedNode.data.supabaseOrderBy || ''"
                  placeholder="created_at"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="supabaseOrderBy"
                  :navigation-enabled="supabaseExpressionFieldCount > 1"
                  :navigation-index="4"
                  :navigation-total="supabaseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Order By"
                  @update:model-value="updateNodeData('supabaseOrderBy', $event)"
                  @navigate="handleSupabaseExpressionFieldNavigate"
                  @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                />
                <div class="flex items-center justify-between gap-2">
                  <label class="flex items-center gap-2 text-sm text-muted-foreground">
                    <input
                      type="checkbox"
                      class="rounded border-input"
                      :checked="selectedNode.data.supabaseAscending !== false"
                      @change="updateNodeData('supabaseAscending', ($event.target as HTMLInputElement).checked)"
                    >
                    Ascending sort
                  </label>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="supabaseAscending"
                  />
                </div>
              </div>
            </template>

            <template v-else-if="selectedNode.data.supabaseOperation === 'insert' || selectedNode.data.supabaseOperation === 'upsert'">
              <div class="flex items-center gap-2 rounded-md border border-input p-1">
                <button
                  :class="[
                    'flex-1 rounded text-xs py-1 transition-colors',
                    (selectedNode.data.supabaseRowsInputMode || 'raw') === 'raw'
                      ? 'bg-primary text-primary-foreground font-medium'
                      : 'text-muted-foreground hover:text-foreground'
                  ]"
                  @click="updateNodeData('supabaseRowsInputMode', 'raw')"
                >
                  JSON array
                </button>
                <button
                  :class="[
                    'flex-1 rounded text-xs py-1 transition-colors',
                    selectedNode.data.supabaseRowsInputMode === 'auto'
                      ? 'bg-primary text-primary-foreground font-medium'
                      : 'text-muted-foreground hover:text-foreground'
                  ]"
                  @click="updateNodeData('supabaseRowsInputMode', 'auto')"
                >
                  Auto-map input
                </button>
              </div>

              <div class="space-y-2">
                <template v-if="(selectedNode.data.supabaseRowsInputMode || 'raw') === 'raw'">
                  <Label>Rows (JSON array)</Label>
                  <ExpressionInput
                    ref="supabaseRowsExpressionInputRef"
                    :model-value="selectedNode.data.supabaseRows || '[]'"
                    placeholder="[{&quot;name&quot;:&quot;$input.name&quot;}]"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="supabaseRows"
                    :navigation-enabled="supabaseExpressionFieldCount > 1"
                    :navigation-index="2"
                    :navigation-total="supabaseExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Rows"
                    @update:model-value="updateNodeData('supabaseRows', $event)"
                    @navigate="handleSupabaseExpressionFieldNavigate"
                    @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                  />
                </template>
                <template v-else>
                  <Label>Auto-map rows</Label>
                  <p class="text-xs text-muted-foreground">
                    Uses the single upstream input automatically. Objects become one row; arrays
                    of objects or upstream <code class="font-mono">rows</code> arrays become many rows.
                  </p>
                  <div class="space-y-2">
                    <div class="flex items-center justify-between gap-2">
                      <Label class="text-xs text-muted-foreground">Ignore fields</Label>
                      <AgentFieldToggle
                        :node-id="selectedNode.id"
                        field-key="supabaseIgnoredInputFields"
                      />
                    </div>
                    <Input
                      :model-value="String(selectedNode.data.supabaseIgnoredInputFields || '')"
                      placeholder="id, created_at"
                      @input="updateNodeData('supabaseIgnoredInputFields', String(($event.target as HTMLInputElement).value))"
                    />
                  </div>
                </template>
              </div>

              <div
                v-if="selectedNode.data.supabaseOperation === 'upsert'"
                class="space-y-2"
              >
                <Label>On Conflict</Label>
                <ExpressionInput
                  ref="supabaseOnConflictExpressionInputRef"
                  :model-value="selectedNode.data.supabaseOnConflict || ''"
                  placeholder="id or tenant_id,email"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="supabaseOnConflict"
                  :navigation-enabled="supabaseExpressionFieldCount > 1"
                  :navigation-index="(selectedNode.data.supabaseRowsInputMode || 'raw') === 'raw' ? 3 : 2"
                  :navigation-total="supabaseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="On Conflict"
                  @update:model-value="updateNodeData('supabaseOnConflict', $event)"
                  @navigate="handleSupabaseExpressionFieldNavigate"
                  @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  Optional comma-separated conflict target columns passed to PostgREST
                  `on_conflict`.
                </p>
              </div>
            </template>

            <template v-else-if="selectedNode.data.supabaseOperation === 'update'">
              <div class="flex items-center gap-2 rounded-md border border-input p-1">
                <button
                  :class="[
                    'flex-1 rounded text-xs py-1 transition-colors',
                    (selectedNode.data.supabaseDataInputMode || 'raw') === 'raw'
                      ? 'bg-primary text-primary-foreground font-medium'
                      : 'text-muted-foreground hover:text-foreground'
                  ]"
                  @click="updateNodeData('supabaseDataInputMode', 'raw')"
                >
                  JSON object
                </button>
                <button
                  :class="[
                    'flex-1 rounded text-xs py-1 transition-colors',
                    selectedNode.data.supabaseDataInputMode === 'auto'
                      ? 'bg-primary text-primary-foreground font-medium'
                      : 'text-muted-foreground hover:text-foreground'
                  ]"
                  @click="updateNodeData('supabaseDataInputMode', 'auto')"
                >
                  Auto-map input
                </button>
              </div>

              <div class="space-y-2">
                <template v-if="(selectedNode.data.supabaseDataInputMode || 'raw') === 'raw'">
                  <Label>Data (JSON object)</Label>
                  <ExpressionInput
                    ref="supabaseDataExpressionInputRef"
                    :model-value="selectedNode.data.supabaseData || '{}'"
                    placeholder="{&quot;status&quot;:&quot;processed&quot;}"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="supabaseData"
                    :navigation-enabled="supabaseExpressionFieldCount > 1"
                    :navigation-index="2"
                    :navigation-total="supabaseExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Data"
                    @update:model-value="updateNodeData('supabaseData', $event)"
                    @navigate="handleSupabaseExpressionFieldNavigate"
                    @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                  />
                </template>
                <template v-else>
                  <Label>Auto-map update data</Label>
                  <p class="text-xs text-muted-foreground">
                    Uses the single upstream object as the update payload. Ignore any fields you
                    do not want to write.
                  </p>
                  <div class="space-y-2">
                    <div class="flex items-center justify-between gap-2">
                      <Label class="text-xs text-muted-foreground">Ignore fields</Label>
                      <AgentFieldToggle
                        :node-id="selectedNode.id"
                        field-key="supabaseIgnoredInputFields"
                      />
                    </div>
                    <Input
                      :model-value="String(selectedNode.data.supabaseIgnoredInputFields || '')"
                      placeholder="id, created_at"
                      @input="updateNodeData('supabaseIgnoredInputFields', String(($event.target as HTMLInputElement).value))"
                    />
                  </div>
                </template>
              </div>

              <div class="space-y-2">
                <Label>Filter (JSON object)</Label>
                <ExpressionInput
                  ref="supabaseFilterExpressionInputRef"
                  :model-value="selectedNode.data.supabaseFilter || '{}'"
                  placeholder="{&quot;id&quot;:123}"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="supabaseFilter"
                  :navigation-enabled="supabaseExpressionFieldCount > 1"
                  :navigation-index="(selectedNode.data.supabaseDataInputMode || 'raw') === 'raw' ? 3 : 2"
                  :navigation-total="supabaseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Filter"
                  @update:model-value="updateNodeData('supabaseFilter', $event)"
                  @navigate="handleSupabaseExpressionFieldNavigate"
                  @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  Supports exact matches plus operator objects like
                  <code class="font-mono">{&quot;created_at&quot;:{&quot;gte&quot;:&quot;2026-01-01&quot;}}</code>
                  and logical groups like
                  <code class="font-mono">{&quot;or&quot;:[{&quot;status&quot;:&quot;active&quot;},{&quot;score&quot;:{&quot;gte&quot;:10}}]}</code>.
                </p>
              </div>
            </template>

            <template v-else-if="selectedNode.data.supabaseOperation === 'delete'">
              <div class="space-y-2">
                <Label>Filter (JSON object)</Label>
                <ExpressionInput
                  ref="supabaseFilterExpressionInputRef"
                  :model-value="selectedNode.data.supabaseFilter || '{}'"
                  placeholder="{&quot;id&quot;:123}"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="supabaseFilter"
                  :navigation-enabled="supabaseExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="supabaseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Filter"
                  @update:model-value="updateNodeData('supabaseFilter', $event)"
                  @navigate="handleSupabaseExpressionFieldNavigate"
                  @register-field-index="onSupabaseRegisterExpressionFieldIndex"
                />
              </div>
            </template>

            <div class="rounded-md bg-muted/40 border p-3 space-y-1">
              <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Output
              </p>
              <div class="text-xs font-mono space-y-0.5">
                <div>${{ selectedNode.data.label }}.rows - Returned row objects</div>
                <div>${{ selectedNode.data.label }}.count - Number of affected rows</div>
                <div>${{ selectedNode.data.label }}.success - Boolean success flag</div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'clickhouse'">
            <div class="space-y-2">
              <Label>ClickHouse Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="clickhouseCredentialOptions"
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
                :model-value="selectedNode.data.clickhouseOperation || ''"
                :options="clickhouseOperationOptions"
                @update:model-value="updateNodeData('clickhouseOperation', $event)"
              />
            </div>

            <template v-if="selectedNode.data.clickhouseOperation === 'query'">
              <div class="space-y-2">
                <Label>SQL Query</Label>
                <ExpressionInput
                  ref="clickhouseQueryExpressionInputRef"
                  :model-value="selectedNode.data.clickhouseQuery || ''"
                  placeholder="SELECT * FROM events LIMIT 10"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="clickhouseQuery"
                  :navigation-enabled="clickhouseExpressionFieldCount > 1"
                  :navigation-index="0"
                  :navigation-total="clickhouseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="SQL Query"
                  @update:model-value="updateNodeData('clickhouseQuery', $event)"
                  @navigate="handleClickhouseExpressionFieldNavigate"
                  @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  SELECT/SHOW return rows; other statements (INSERT, ALTER, DELETE) run as commands.
                </p>
              </div>
            </template>

            <template v-else-if="selectedNode.data.clickhouseOperation">
              <div class="space-y-2">
                <Label>Table</Label>
                <ExpressionInput
                  ref="clickhouseTableExpressionInputRef"
                  :model-value="selectedNode.data.clickhouseTable || ''"
                  placeholder="events"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="clickhouseTable"
                  :navigation-enabled="clickhouseExpressionFieldCount > 1"
                  :navigation-index="0"
                  :navigation-total="clickhouseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Table"
                  @update:model-value="updateNodeData('clickhouseTable', $event)"
                  @navigate="handleClickhouseExpressionFieldNavigate"
                  @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                />
              </div>

              <div
                v-if="['find', 'count', 'update', 'remove'].includes(String(selectedNode.data.clickhouseOperation))"
                class="space-y-2"
              >
                <Label>Filter (JSON object)</Label>
                <ExpressionInput
                  ref="clickhouseFilterExpressionInputRef"
                  :model-value="selectedNode.data.clickhouseFilter || '{}'"
                  placeholder="{&quot;status&quot;:&quot;active&quot;}"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="clickhouseFilter"
                  :navigation-enabled="clickhouseExpressionFieldCount > 1"
                  :navigation-index="selectedNode.data.clickhouseOperation === 'update' ? 2 : 1"
                  :navigation-total="clickhouseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Filter"
                  @update:model-value="updateNodeData('clickhouseFilter', $event)"
                  @navigate="handleClickhouseExpressionFieldNavigate"
                  @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                />
                <p
                  v-if="['update', 'remove'].includes(String(selectedNode.data.clickhouseOperation))"
                  class="text-xs text-amber-500"
                >
                  Required. ClickHouse {{ selectedNode.data.clickhouseOperation }} runs as an
                  asynchronous mutation; a filter prevents a full-table change.
                </p>
              </div>

              <div
                v-if="selectedNode.data.clickhouseOperation === 'getById'"
                class="space-y-2"
              >
                <Label>Row ID</Label>
                <ExpressionInput
                  ref="clickhouseRowIdExpressionInputRef"
                  :model-value="selectedNode.data.clickhouseRowId || ''"
                  placeholder="$input.id"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="clickhouseRowId"
                  :navigation-enabled="clickhouseExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="clickhouseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Row ID"
                  @update:model-value="updateNodeData('clickhouseRowId', $event)"
                  @navigate="handleClickhouseExpressionFieldNavigate"
                  @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  Matched against the table's `id` column.
                </p>
              </div>

              <div
                v-if="selectedNode.data.clickhouseOperation === 'find'"
                class="space-y-2"
              >
                <Label>Sort</Label>
                <ExpressionInput
                  ref="clickhouseSortExpressionInputRef"
                  :model-value="selectedNode.data.clickhouseSort || ''"
                  placeholder="created_at DESC"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="clickhouseSort"
                  :navigation-enabled="clickhouseExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="clickhouseExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Sort"
                  @update:model-value="updateNodeData('clickhouseSort', $event)"
                  @navigate="handleClickhouseExpressionFieldNavigate"
                  @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                />
              </div>

              <div
                v-if="['find', 'getAll'].includes(String(selectedNode.data.clickhouseOperation))"
                class="space-y-2"
              >
                <Label>Limit <span class="text-muted-foreground font-normal">(0 = unlimited)</span></Label>
                <input
                  type="number"
                  min="0"
                  :value="selectedNode.data.clickhouseLimit ?? '100'"
                  placeholder="100"
                  class="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  @input="updateNodeData('clickhouseLimit', String(($event.target as HTMLInputElement).value))"
                >
              </div>

              <template v-if="selectedNode.data.clickhouseOperation === 'update'">
                <div class="space-y-2">
                  <Label>Data (JSON object)</Label>
                  <ExpressionInput
                    ref="clickhouseDataExpressionInputRef"
                    :model-value="selectedNode.data.clickhouseData || '{}'"
                    placeholder="{&quot;status&quot;:&quot;archived&quot;}"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="clickhouseData"
                    :navigation-enabled="clickhouseExpressionFieldCount > 1"
                    :navigation-index="1"
                    :navigation-total="clickhouseExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Data"
                    @update:model-value="updateNodeData('clickhouseData', $event)"
                    @navigate="handleClickhouseExpressionFieldNavigate"
                    @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                  />
                  <p class="text-xs text-muted-foreground">
                    JSON object of column values to set on matching rows.
                  </p>
                </div>
              </template>

              <template
                v-if="['insert', 'upsert'].includes(String(selectedNode.data.clickhouseOperation))"
              >
                <div class="flex items-center gap-2 rounded-md border border-input p-1">
                  <button
                    :class="[
                      'flex-1 rounded text-xs py-1 transition-colors',
                      (selectedNode.data.clickhouseInputMode || 'raw') === 'raw'
                        ? 'bg-primary text-primary-foreground font-medium'
                        : 'text-muted-foreground hover:text-foreground'
                    ]"
                    @click="switchClickhouseToRaw()"
                  >
                    JSON array
                  </button>
                  <button
                    :class="[
                      'flex-1 rounded text-xs py-1 transition-colors',
                      selectedNode.data.clickhouseInputMode === 'selective'
                        ? 'bg-primary text-primary-foreground font-medium'
                        : 'text-muted-foreground hover:text-foreground'
                    ]"
                    @click="updateNodeData('clickhouseInputMode', 'selective')"
                  >
                    Key-value
                  </button>
                </div>

                <div
                  v-if="(selectedNode.data.clickhouseInputMode || 'raw') === 'raw'"
                  class="space-y-2"
                >
                  <Label>Rows (JSON array)</Label>
                  <ExpressionInput
                    ref="clickhouseDataExpressionInputRef"
                    :model-value="selectedNode.data.clickhouseData || '[]'"
                    placeholder="[{&quot;id&quot;: &quot;$input.id&quot;, &quot;event&quot;: &quot;signup&quot;}]"
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    field-key="clickhouseData"
                    :navigation-enabled="clickhouseExpressionFieldCount > 1"
                    :navigation-index="1"
                    :navigation-total="clickhouseExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    dialog-key-label="Rows"
                    @update:model-value="updateNodeData('clickhouseData', $event)"
                    @navigate="handleClickhouseExpressionFieldNavigate"
                    @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                  />
                  <p class="text-xs text-muted-foreground">
                    JSON array of row objects; each key must match a column in the table.
                  </p>
                </div>

                <div
                  v-else
                  class="space-y-3"
                >
                  <div
                    v-if="loadingClickhouseColumns && clickhouseMappings.length === 0"
                    class="flex h-9 items-center"
                    title="Loading ClickHouse columns"
                  >
                    <Loader2 class="h-4 w-4 animate-spin text-muted-foreground" />
                  </div>
                  <template v-else>
                    <div
                      v-for="(mapping, index) in clickhouseMappings"
                      :key="mapping.key"
                      class="flex gap-2 items-center"
                    >
                      <div
                        class="h-9 w-28 shrink-0 truncate rounded-md border border-input bg-muted/40 px-2 py-2 font-mono text-xs"
                        :title="clickhouseDiscoveredColumns.find((col) => col.name === mapping.key)?.type || mapping.key"
                      >
                        {{ mapping.key }}
                      </div>
                      <span class="text-muted-foreground text-xs">=</span>
                      <ExpressionInput
                        :ref="(el: any) => clickhouseMappingInputRef(mapping.key, el)"
                        :model-value="mapping.value"
                        :placeholder="exampleRef"
                        single-line
                        class="flex-1 text-xs"
                        :nodes="workflowStore.nodes"
                        :node-results="workflowStore.nodeResults"
                        :edges="workflowStore.edges"
                        :current-node-id="selectedNode.id"
                        :navigation-enabled="clickhouseExpressionFieldCount > 1"
                        :navigation-index="index + 1"
                        :navigation-total="clickhouseExpressionFieldCount"
                        :dialog-node-label="selectedNodeEvaluateDialogLabel"
                        :dialog-key-label="mapping.key"
                        @update:model-value="updateClickhouseMappingValue(index, $event)"
                        @navigate="handleClickhouseExpressionFieldNavigate"
                        @register-field-index="onClickhouseRegisterExpressionFieldIndex"
                      />
                    </div>
                  </template>
                </div>
              </template>
            </template>

            <div class="rounded-md bg-muted/40 border p-3 space-y-1">
              <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Output
              </p>
              <div class="text-xs font-mono space-y-0.5">
                <div>${{ selectedNode.data.label }}.rows - Returned row objects (read ops)</div>
                <div>${{ selectedNode.data.label }}.count - Row count (find/getAll/count/insert)</div>
                <div>${{ selectedNode.data.label }}.row - Single row (getById)</div>
                <div>${{ selectedNode.data.label }}.success - Boolean success flag</div>
              </div>
            </div>
          </template>

          <template v-if="selectedNode.type === 'notion'">
            <div class="space-y-2">
              <Label>Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="notionCredentialOptions"
                @update:model-value="updateNodeData('credentialId', $event)"
              />
              <p
                v-if="!selectedNode.data.credentialId"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Notion credential is required.
              </p>
            </div>

            <div class="space-y-2">
              <Label>Operation</Label>
              <Select
                :model-value="selectedNode.data.notionOperation || ''"
                :options="notionOperationOptions"
                @update:model-value="updateNodeData('notionOperation', $event)"
              />
            </div>

            <div
              v-if="selectedNode.data.notionOperation === 'search'"
              class="space-y-2"
            >
              <Label>Search Query</Label>
              <ExpressionInput
                ref="notionQueryExpressionInputRef"
                :model-value="selectedNode.data.notionQuery || ''"
                placeholder="Roadmap"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionQuery"
                v-bind="notionExpressionNavBindings('notionQuery')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionQuery', $event)"
              />
            </div>

            <div
              v-if="['getPage', 'updatePage', 'trashPage', 'restorePage'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Page ID</Label>
              <ExpressionInput
                ref="notionPageIdExpressionInputRef"
                :model-value="selectedNode.data.notionPageId || ''"
                placeholder="Notion page ID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionPageId"
                v-bind="notionExpressionNavBindings('notionPageId')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionPageId', $event)"
              />
            </div>

            <div
              v-if="['retrieveDatabase', 'updateDatabase'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Database ID</Label>
              <ExpressionInput
                ref="notionDatabaseIdExpressionInputRef"
                :model-value="selectedNode.data.notionDatabaseId || ''"
                placeholder="Notion database ID, URL, or expression"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionDatabaseId"
                v-bind="notionExpressionNavBindings('notionDatabaseId')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionDatabaseId', $event)"
              />
            </div>

            <div
              v-if="['createDatabase', 'updateDatabase'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Database Request (JSON object)</Label>
              <ExpressionInput
                ref="notionDatabaseExpressionInputRef"
                :model-value="selectedNode.data.notionDatabase || '{}'"
                :placeholder="selectedNode.data.notionOperation === 'createDatabase'
                  ? '{&quot;parent&quot;:{&quot;type&quot;:&quot;page_id&quot;,&quot;page_id&quot;:&quot;...&quot;},&quot;title&quot;:[{&quot;type&quot;:&quot;text&quot;,&quot;text&quot;:{&quot;content&quot;:&quot;Tasks&quot;}}],&quot;initial_data_source&quot;:{&quot;properties&quot;:{&quot;Name&quot;:{&quot;title&quot;:{}}}}}'
                  : '{&quot;title&quot;:[{&quot;type&quot;:&quot;text&quot;,&quot;text&quot;:{&quot;content&quot;:&quot;Updated&quot;}}]}'"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionDatabase"
                v-bind="notionExpressionNavBindings('notionDatabase')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionDatabase', $event)"
              />
              <p class="text-xs text-muted-foreground">
                {{
                  selectedNode.data.notionOperation === "createDatabase"
                    ? "Create requires a parent object. The request supports the current Notion Database API fields."
                    : "Provide one or more fields supported by the current Notion Update Database API."
                }}
              </p>
            </div>

            <div
              v-if="['createPage', 'retrieveDataSource', 'updateDataSource', 'queryDataSource'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <div class="flex items-center justify-between gap-2">
                <Label>Data Source</Label>
                <div class="flex items-center gap-1">
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="notionDataSourceId"
                  />
                  <Button
                    v-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
                    type="button"
                    variant="outline"
                    size="sm"
                    :disabled="!selectedNode.data.credentialId || loadingNotionDataSources"
                    @click="loadNotionDataSourcesForSelectedNode(false)"
                  >
                    <RefreshCw
                      class="mr-1 h-3.5 w-3.5"
                      :class="{ 'animate-spin': loadingNotionDataSources }"
                    />
                    Refresh
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    @click="updateNodeData(
                      'notionDataSourceInputMode',
                      (selectedNode.data.notionDataSourceInputMode || 'select') === 'select'
                        ? 'expression'
                        : 'select',
                    )"
                  >
                    {{
                      (selectedNode.data.notionDataSourceInputMode || "select") === "select"
                        ? "Use expression"
                        : "Use selector"
                    }}
                  </Button>
                </div>
              </div>
              <Select
                v-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
                :model-value="selectedNode.data.notionDataSourceId || ''"
                :options="notionDataSourceOptions"
                :disabled="!selectedNode.data.credentialId || loadingNotionDataSources"
                @update:model-value="updateNodeData('notionDataSourceId', $event)"
              />
              <Input
                v-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
                v-model="notionDataSourceSearch"
                placeholder="Search data sources..."
                :disabled="!selectedNode.data.credentialId"
              />
              <Button
                v-if="
                  (selectedNode.data.notionDataSourceInputMode || 'select') === 'select' &&
                    notionDataSourcesHasMore
                "
                type="button"
                variant="outline"
                size="sm"
                :loading="loadingNotionDataSources"
                :disabled="loadingNotionDataSources"
                @click="loadNotionDataSourcesForSelectedNode(true)"
              >
                Load more
              </Button>
              <ExpressionInput
                v-else
                ref="notionDataSourceIdExpressionInputRef"
                :model-value="selectedNode.data.notionDataSourceId || ''"
                placeholder="$input.dataSourceId or a Notion URL"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionDataSourceId"
                v-bind="notionExpressionNavBindings('notionDataSourceId')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionDataSourceId', $event)"
              />
              <p
                v-if="notionDataSourcesError && (selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
                class="text-xs text-destructive"
              >
                {{ notionDataSourcesError }}
              </p>
              <p
                v-else-if="(selectedNode.data.notionDataSourceInputMode || 'select') === 'select'"
                class="text-xs text-muted-foreground"
              >
                Shows data sources shared with the selected Notion integration.
              </p>
              <p
                v-else
                class="text-xs text-muted-foreground"
              >
                Accepts an expression, raw data source ID, or full Notion URL.
              </p>
            </div>

            <div
              v-if="['createDataSource', 'updateDataSource'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Data Source Request (JSON object)</Label>
              <ExpressionInput
                ref="notionDataSourceExpressionInputRef"
                :model-value="selectedNode.data.notionDataSource || '{}'"
                :placeholder="selectedNode.data.notionOperation === 'createDataSource'
                  ? '{&quot;parent&quot;:{&quot;type&quot;:&quot;database_id&quot;,&quot;database_id&quot;:&quot;...&quot;},&quot;properties&quot;:{&quot;Name&quot;:{&quot;title&quot;:{}}}}'
                  : '{&quot;properties&quot;:{&quot;Status&quot;:{&quot;status&quot;:{}}}}'"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionDataSource"
                v-bind="notionExpressionNavBindings('notionDataSource')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionDataSource', $event)"
              />
              <p class="text-xs text-muted-foreground">
                {{
                  selectedNode.data.notionOperation === "createDataSource"
                    ? "Create requires a parent database object and a property schema."
                    : "Provide one or more fields supported by the Notion Update Data Source API."
                }}
              </p>
            </div>

            <template v-if="selectedNode.data.notionOperation === 'createPage'">
              <div class="space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <Label>Parent Page</Label>
                  <div class="flex items-center gap-1">
                    <AgentFieldToggle
                      :node-id="selectedNode.id"
                      field-key="notionParentPageId"
                    />
                    <Button
                      v-if="(selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
                      type="button"
                      variant="outline"
                      size="sm"
                      :disabled="!selectedNode.data.credentialId || loadingNotionPages"
                      @click="loadNotionPagesForSelectedNode(false)"
                    >
                      <RefreshCw
                        class="mr-1 h-3.5 w-3.5"
                        :class="{ 'animate-spin': loadingNotionPages }"
                      />
                      Refresh
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      @click="updateNodeData(
                        'notionParentPageInputMode',
                        (selectedNode.data.notionParentPageInputMode || 'select') === 'select'
                          ? 'expression'
                          : 'select',
                      )"
                    >
                      {{
                        (selectedNode.data.notionParentPageInputMode || "select") === "select"
                          ? "Use expression"
                          : "Use selector"
                      }}
                    </Button>
                  </div>
                </div>
                <Select
                  v-if="(selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
                  :model-value="selectedNode.data.notionParentPageId || ''"
                  :options="notionPageOptions"
                  :disabled="!selectedNode.data.credentialId || loadingNotionPages"
                  @update:model-value="updateNodeData('notionParentPageId', $event)"
                />
                <Input
                  v-if="(selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
                  v-model="notionPageSearch"
                  placeholder="Search pages..."
                  :disabled="!selectedNode.data.credentialId"
                />
                <Button
                  v-if="
                    (selectedNode.data.notionParentPageInputMode || 'select') === 'select' &&
                      notionPagesHasMore
                  "
                  type="button"
                  variant="outline"
                  size="sm"
                  :loading="loadingNotionPages"
                  :disabled="loadingNotionPages"
                  @click="loadNotionPagesForSelectedNode(true)"
                >
                  Load more
                </Button>
                <ExpressionInput
                  v-else
                  ref="notionParentPageIdExpressionInputRef"
                  :model-value="selectedNode.data.notionParentPageId || ''"
                  placeholder="$input.parentPageId or a Notion URL"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="notionParentPageId"
                  v-bind="notionExpressionNavBindings('notionParentPageId')"
                  @navigate="handleNotionExpressionFieldNavigate"
                  @register-field-index="onNotionRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('notionParentPageId', $event)"
                />
                <p
                  v-if="notionPagesError && (selectedNode.data.notionParentPageInputMode || 'select') === 'select'"
                  class="text-xs text-destructive"
                >
                  {{ notionPagesError }}
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Set exactly one parent. Data Source ID takes precedence when both are present.
                </p>
              </div>
            </template>

            <div
              v-if="['getBlockChildren', 'updateBlock', 'deleteBlock', 'appendBlocks'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Block or Page ID</Label>
              <ExpressionInput
                ref="notionBlockIdExpressionInputRef"
                :model-value="selectedNode.data.notionBlockId || ''"
                placeholder="Notion block or page ID"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionBlockId"
                v-bind="notionExpressionNavBindings('notionBlockId')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionBlockId', $event)"
              />
            </div>

            <div
              v-if="selectedNode.data.notionOperation === 'updateBlock'"
              class="space-y-2"
            >
              <Label>Block Update (JSON object)</Label>
              <ExpressionInput
                ref="notionBlockExpressionInputRef"
                :model-value="selectedNode.data.notionBlock || '{}'"
                placeholder="{&quot;paragraph&quot;:{&quot;rich_text&quot;:[{&quot;type&quot;:&quot;text&quot;,&quot;text&quot;:{&quot;content&quot;:&quot;Updated&quot;}}]}}"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionBlock"
                v-bind="notionExpressionNavBindings('notionBlock')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionBlock', $event)"
              />
            </div>

            <div
              v-if="['createPage', 'updatePage'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Properties (JSON object)</Label>
              <ExpressionInput
                ref="notionPropertiesExpressionInputRef"
                :model-value="selectedNode.data.notionProperties || '{}'"
                placeholder="{&quot;Name&quot;:{&quot;title&quot;:[{&quot;text&quot;:{&quot;content&quot;:&quot;$input.title&quot;}}]}}"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionProperties"
                v-bind="notionExpressionNavBindings('notionProperties')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionProperties', $event)"
              />
            </div>

            <div
              v-if="['createPage', 'updatePage'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Icon (JSON object)</Label>
              <ExpressionInput
                ref="notionIconExpressionInputRef"
                :model-value="selectedNode.data.notionIcon || '{}'"
                placeholder="{&quot;type&quot;:&quot;emoji&quot;,&quot;emoji&quot;:&quot;📌&quot;}"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionIcon"
                v-bind="notionExpressionNavBindings('notionIcon')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionIcon', $event)"
              />
            </div>

            <div
              v-if="['createPage', 'updatePage'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Cover (JSON object)</Label>
              <ExpressionInput
                ref="notionCoverExpressionInputRef"
                :model-value="selectedNode.data.notionCover || '{}'"
                placeholder="{&quot;type&quot;:&quot;external&quot;,&quot;external&quot;:{&quot;url&quot;:&quot;https://example.com/cover.jpg&quot;}}"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionCover"
                v-bind="notionExpressionNavBindings('notionCover')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionCover', $event)"
              />
            </div>

            <div
              v-if="['createPage', 'appendBlocks'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Children (JSON array)</Label>
              <ExpressionInput
                ref="notionChildrenExpressionInputRef"
                :model-value="selectedNode.data.notionChildren || '[]'"
                placeholder="[{&quot;object&quot;:&quot;block&quot;,&quot;type&quot;:&quot;paragraph&quot;,&quot;paragraph&quot;:{&quot;rich_text&quot;:[]}}]"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionChildren"
                v-bind="notionExpressionNavBindings('notionChildren')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionChildren', $event)"
              />
            </div>

            <div
              v-if="['search', 'queryDataSource'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <Label>Filter (JSON object)</Label>
              <ExpressionInput
                ref="notionFilterExpressionInputRef"
                :model-value="selectedNode.data.notionFilter || '{}'"
                placeholder="{}"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionFilter"
                v-bind="notionExpressionNavBindings('notionFilter')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionFilter', $event)"
              />
            </div>

            <div
              v-if="selectedNode.data.notionOperation === 'search'"
              class="space-y-2"
            >
              <Label>Sort (JSON object)</Label>
              <ExpressionInput
                ref="notionSortExpressionInputRef"
                :model-value="selectedNode.data.notionSort || '{}'"
                placeholder="{&quot;direction&quot;:&quot;descending&quot;,&quot;timestamp&quot;:&quot;last_edited_time&quot;}"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionSort"
                v-bind="notionExpressionNavBindings('notionSort')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionSort', $event)"
              />
            </div>

            <div
              v-if="selectedNode.data.notionOperation === 'queryDataSource'"
              class="space-y-2"
            >
              <Label>Sorts (JSON array)</Label>
              <ExpressionInput
                ref="notionSortsExpressionInputRef"
                :model-value="selectedNode.data.notionSorts || '[]'"
                placeholder="[{&quot;property&quot;:&quot;Created&quot;,&quot;direction&quot;:&quot;descending&quot;}]"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionSorts"
                v-bind="notionExpressionNavBindings('notionSorts')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionSorts', $event)"
              />
            </div>

            <div
              v-if="['search', 'queryDataSource', 'getBlockChildren'].includes(selectedNode.data.notionOperation || '')"
              class="space-y-2"
            >
              <div class="flex items-center justify-between gap-2">
                <Label>Page Size <span class="font-normal text-muted-foreground">(0 = fetch all)</span></Label>
                <AgentFieldToggle
                  :node-id="selectedNode.id"
                  field-key="notionPageSize"
                />
              </div>
              <Input
                type="number"
                min="0"
                max="100"
                :model-value="selectedNode.data.notionPageSize || '100'"
                @input="updateNodeData('notionPageSize', String(($event.target as HTMLInputElement).value))"
              />
              <Label>Start Cursor</Label>
              <ExpressionInput
                ref="notionStartCursorExpressionInputRef"
                :model-value="selectedNode.data.notionStartCursor || ''"
                placeholder="Optional cursor"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionStartCursor"
                v-bind="notionExpressionNavBindings('notionStartCursor')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionStartCursor', $event)"
              />
            </div>

            <div
              v-if="selectedNode.data.notionOperation === 'appendBlocks'"
              class="space-y-2"
            >
              <div class="flex items-center justify-between gap-2">
                <Label>Position</Label>
                <AgentFieldToggle
                  :node-id="selectedNode.id"
                  field-key="notionAppendPosition"
                />
              </div>
              <Select
                :model-value="selectedNode.data.notionAppendPosition || (selectedNode.data.notionAfterBlockId ? 'after_block' : 'end')"
                :options="notionAppendPositionOptions"
                @update:model-value="updateNodeData('notionAppendPosition', $event)"
              />
              <Label
                v-if="(selectedNode.data.notionAppendPosition || (selectedNode.data.notionAfterBlockId ? 'after_block' : 'end')) === 'after_block'"
              >
                After Block ID
              </Label>
              <ExpressionInput
                v-if="(selectedNode.data.notionAppendPosition || (selectedNode.data.notionAfterBlockId ? 'after_block' : 'end')) === 'after_block'"
                ref="notionAfterBlockIdExpressionInputRef"
                :model-value="selectedNode.data.notionAfterBlockId || ''"
                placeholder="Block ID, URL, or expression"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="notionAfterBlockId"
                v-bind="notionExpressionNavBindings('notionAfterBlockId')"
                @navigate="handleNotionExpressionFieldNavigate"
                @register-field-index="onNotionRegisterExpressionFieldIndex"
                @update:model-value="updateNodeData('notionAfterBlockId', $event)"
              />
            </div>

            <div class="rounded-md bg-muted/40 border p-3 space-y-1">
              <p class="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Output
              </p>
              <div class="text-xs font-mono space-y-0.5">
                <div>${{ selectedNode.data.label }}.success - Boolean success flag</div>
                <div>${{ selectedNode.data.label }}.results - Search/query/block results</div>
                <div>${{ selectedNode.data.label }}.page - Created, retrieved, or updated page</div>
                <div>${{ selectedNode.data.label }}.database - Created, retrieved, or updated database</div>
                <div>${{ selectedNode.data.label }}.data_source - Retrieved data source schema</div>
                <div>${{ selectedNode.data.label }}.block - Updated or deleted block</div>
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
                  class="font-medium text-violet-600 hover:underline dark:text-violet-400"
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

            <!-- Filter — for find, upsert, count -->
            <div
              v-if="['find', 'upsert', 'count'].includes(selectedNode.data.dataTableOperation || '')"
              class="space-y-2"
            >
              <div class="flex items-center justify-between">
                <Label>Filter (JSON)</Label>
                <button
                  class="text-xs font-medium text-violet-600 hover:underline dark:text-violet-400"
                  @click="() => { try { const parsed = JSON.parse(selectedNode?.data.dataTableFilter || '{}'); updateNodeData('dataTableFilter', JSON.stringify(parsed, null, 2)); } catch {} }"
                >
                  Format
                </button>
              </div>
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
                  ['find', 'count'].includes(selectedNode.data.dataTableOperation || '')
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
              <p class="text-xs text-muted-foreground">
                <template v-if="['find', 'count'].includes(selectedNode.data.dataTableOperation || '')">
                  Plain value = equals. Use operators like
                  <code>{"age": {"$gt": 18}}</code>
                  or
                  <code>{"created_at": {"$contains": "2026-06"}}</code>.
                </template>
                <template v-else>
                  Exact-match lookup for upsert:
                  <code>{"column": "$input.value"}</code>
                </template>
              </p>
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

          <template v-if="selectedNode.type === 's3'">
            <div class="space-y-2">
              <Label>Amazon S3 Credential</Label>
              <Select
                :model-value="selectedNode.data.credentialId || ''"
                :options="s3CredentialOptions"
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
                :model-value="selectedNode.data.s3Operation || 'putObject'"
                :options="s3OperationOptions"
                @update:model-value="updateNodeData('s3Operation', $event)"
              />
              <p
                v-if="!selectedNode.data.s3Operation"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Operation is required
              </p>
            </div>

            <div
              v-if="selectedNode.data.s3Operation !== 'listBuckets'"
              class="space-y-2"
            >
              <Label>
                <template v-if="selectedNode.data.s3Operation === 'copyObject'">
                  Destination Bucket
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'createBucket' || selectedNode.data.s3Operation === 'deleteBucket'">
                  Bucket Name
                </template>
                <template v-else>
                  Bucket
                </template>
                <span class="text-destructive">*</span>
              </Label>
              <ExpressionInput
                ref="s3BucketExpressionInputRef"
                :model-value="selectedNode.data.s3Bucket || ''"
                placeholder="my-bucket"
                single-line
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                field-key="s3Bucket"
                :navigation-enabled="s3ExpressionFieldCount > 1"
                :navigation-index="0"
                :navigation-total="s3ExpressionFieldCount"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                dialog-key-label="Amazon S3 Bucket"
                @update:model-value="updateNodeData('s3Bucket', $event)"
                @navigate="handleS3ExpressionFieldNavigate"
                @register-field-index="onS3RegisterExpressionFieldIndex"
              />
              <p
                v-if="!selectedNode.data.s3Bucket || selectedNode.data.s3Bucket.trim() === ''"
                class="text-xs text-amber-500 flex items-center gap-1"
              >
                <AlertTriangle class="h-3 w-3" />
                Bucket is required
              </p>
            </div>

            <template v-if="selectedNode.data.s3Operation === 'listBuckets'">
              <p class="text-xs text-muted-foreground">
                Lists all buckets visible to the credential. Requires `s3:ListAllMyBuckets` permission.
              </p>
            </template>

            <template v-else-if="selectedNode.data.s3Operation === 'createBucket'">
              <p class="text-xs text-muted-foreground">
                Creates the bucket in the credential region. Requires `s3:CreateBucket` permission.
              </p>
            </template>

            <template v-else-if="selectedNode.data.s3Operation === 'deleteBucket'">
              <p class="text-xs text-muted-foreground">
                Deletes an empty bucket. Requires `s3:DeleteBucket` permission. Remove all objects first.
              </p>
            </template>

            <template v-else-if="selectedNode.data.s3Operation === 'listObjects'">
              <div class="space-y-2">
                <Label>Prefix</Label>
                <ExpressionInput
                  ref="s3PrefixExpressionInputRef"
                  :model-value="selectedNode.data.s3Prefix || ''"
                  placeholder="docs/"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3Prefix"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Prefix"
                  @update:model-value="updateNodeData('s3Prefix', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
              </div>
              <div class="space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <Label>Max Keys</Label>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="s3MaxKeys"
                  />
                </div>
                <Input
                  :model-value="selectedNode.data.s3MaxKeys || '100'"
                  type="number"
                  min="1"
                  max="1000"
                  @update:model-value="handleS3MaxKeysChange($event)"
                />
                <p
                  v-if="s3MaxKeysWarning"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  {{ s3MaxKeysWarning }}
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Maximum number of objects to return per page (1–1000). Use Continuation Token to fetch the next page.
                </p>
              </div>
              <div class="space-y-2">
                <Label>Continuation Token</Label>
                <ExpressionInput
                  ref="s3ContinuationTokenExpressionInputRef"
                  :model-value="selectedNode.data.s3ContinuationToken || ''"
                  placeholder="Leave empty for first page; use $previousNode.next_continuation_token"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3ContinuationToken"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Continuation Token"
                  @update:model-value="updateNodeData('s3ContinuationToken', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
                <p class="text-xs text-muted-foreground">
                  Optional. Pass the previous response's <span class="font-mono">next_continuation_token</span> to list the next page (n8n limit-mode pagination).
                </p>
              </div>
            </template>

            <template v-else-if="selectedNode.data.s3Operation === 'createFolder' || selectedNode.data.s3Operation === 'deleteFolder' || selectedNode.data.s3Operation === 'getAllFolder'">
              <div class="space-y-2">
                <Label>Folder Path <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="s3KeyExpressionInputRef"
                  :model-value="selectedNode.data.s3Key || ''"
                  placeholder="docs/archive"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3Key"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Folder Path"
                  @update:model-value="updateNodeData('s3Key', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
                <p
                  v-if="!selectedNode.data.s3Key || selectedNode.data.s3Key.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Folder path is required
                </p>
                <p
                  v-else-if="selectedNode.data.s3Operation === 'createFolder'"
                  class="text-xs text-muted-foreground"
                >
                  Creates a zero-byte folder marker. A trailing `/` is added automatically.
                </p>
                <p
                  v-else-if="selectedNode.data.s3Operation === 'deleteFolder'"
                  class="text-xs text-muted-foreground"
                >
                  Deletes all objects under this prefix, including nested files and subfolders.
                </p>
                <p
                  v-else
                  class="text-xs text-muted-foreground"
                >
                  Lists all object metadata under this prefix (paginated server-side).
                </p>
              </div>
            </template>

            <template v-else-if="selectedNode.data.s3Operation === 'copyObject'">
              <div class="space-y-2">
                <Label>Source Bucket</Label>
                <ExpressionInput
                  ref="s3SourceBucketExpressionInputRef"
                  :model-value="selectedNode.data.s3SourceBucket || ''"
                  placeholder="Leave empty to use destination bucket"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3SourceBucket"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Source Bucket"
                  @update:model-value="updateNodeData('s3SourceBucket', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
              </div>
              <div class="space-y-2">
                <Label>Source Object Key <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="s3SourceKeyExpressionInputRef"
                  :model-value="selectedNode.data.s3SourceKey || ''"
                  placeholder="docs/source.txt"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3SourceKey"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Source Object Key"
                  @update:model-value="updateNodeData('s3SourceKey', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
                <p
                  v-if="!selectedNode.data.s3SourceKey || selectedNode.data.s3SourceKey.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Source object key is required for copy operation
                </p>
              </div>
              <div class="space-y-2">
                <Label>Destination Object Key <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="s3KeyExpressionInputRef"
                  :model-value="selectedNode.data.s3Key || ''"
                  placeholder="archive/source.txt"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3Key"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="3"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Destination Object Key"
                  @update:model-value="updateNodeData('s3Key', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
                <p
                  v-if="!selectedNode.data.s3Key || selectedNode.data.s3Key.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Destination object key is required for copy operation
                </p>
              </div>
            </template>

            <template v-else>
              <div class="space-y-2">
                <Label>Object Key <span class="text-destructive">*</span></Label>
                <ExpressionInput
                  ref="s3KeyExpressionInputRef"
                  :model-value="selectedNode.data.s3Key || ''"
                  placeholder="docs/report.txt"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3Key"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="1"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Object Key"
                  @update:model-value="updateNodeData('s3Key', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
                <p
                  v-if="!selectedNode.data.s3Key || selectedNode.data.s3Key.trim() === ''"
                  class="text-xs text-amber-500 flex items-center gap-1"
                >
                  <AlertTriangle class="h-3 w-3" />
                  Object key is required for this operation
                </p>
              </div>

              <div
                v-if="selectedNode.data.s3Operation === 'putObject'"
                class="space-y-2"
              >
                <Label>Body</Label>
                <ExpressionInput
                  ref="s3BodyExpressionInputRef"
                  :model-value="selectedNode.data.s3Body || ''"
                  placeholder="$input.text"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3Body"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="2"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Object Body"
                  @update:model-value="updateNodeData('s3Body', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
              </div>

              <div
                v-if="selectedNode.data.s3Operation === 'putObject'"
                class="space-y-2"
              >
                <Label>Content Type</Label>
                <ExpressionInput
                  :model-value="selectedNode.data.s3ContentType || ''"
                  placeholder="text/plain"
                  single-line
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  field-key="s3ContentType"
                  :navigation-enabled="s3ExpressionFieldCount > 1"
                  :navigation-index="3"
                  :navigation-total="s3ExpressionFieldCount"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Amazon S3 Content Type"
                  @update:model-value="updateNodeData('s3ContentType', $event)"
                  @navigate="handleS3ExpressionFieldNavigate"
                  @register-field-index="onS3RegisterExpressionFieldIndex"
                />
              </div>

              <div
                v-if="selectedNode.data.s3Operation === 'getObject'"
                class="space-y-2"
              >
                <Label>Options</Label>
                <div class="flex items-center justify-between gap-2">
                  <div class="flex items-center gap-2">
                    <input
                      id="s3-include-binary"
                      type="checkbox"
                      class="h-4 w-4 rounded border-input bg-background"
                      :checked="!!selectedNode.data.s3IncludeBinary"
                      @change="updateNodeData('s3IncludeBinary', ($event.target as HTMLInputElement).checked)"
                    >
                    <Label
                      for="s3-include-binary"
                      class="font-normal text-sm"
                    >
                      Return binary as base64
                    </Label>
                  </div>
                  <AgentFieldToggle
                    :node-id="selectedNode.id"
                    field-key="s3IncludeBinary"
                  />
                </div>
              </div>
            </template>

            <div class="rounded-lg bg-muted/50 p-3 space-y-1">
              <p class="text-xs font-medium text-foreground">
                Output
              </p>
              <div class="text-xs text-muted-foreground space-y-0.5 font-mono">
                <template v-if="selectedNode.data.s3Operation === 'putObject'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
                  <div>${{ selectedNode.data.label }}.key - object key</div>
                  <div>${{ selectedNode.data.label }}.etag - uploaded object etag</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'getObject'">
                  <div>${{ selectedNode.data.label }}.content_type - MIME type</div>
                  <div>${{ selectedNode.data.label }}.content_length - byte size</div>
                  <div>${{ selectedNode.data.label }}.body_text - decoded text body</div>
                  <div>${{ selectedNode.data.label }}.body_base64 - base64 body when enabled</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'listObjects'">
                  <div>${{ selectedNode.data.label }}.objects - object metadata array</div>
                  <div>${{ selectedNode.data.label }}.count - number of returned objects</div>
                  <div>${{ selectedNode.data.label }}.truncated - more pages available</div>
                  <div>${{ selectedNode.data.label }}.next_continuation_token - token for next page</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'deleteObject'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
                  <div>${{ selectedNode.data.label }}.key - object key</div>
                  <div>${{ selectedNode.data.label }}.delete_marker - delete marker flag</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'createBucket'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
                  <div>${{ selectedNode.data.label }}.region - bucket region</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'deleteBucket'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'createFolder'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
                  <div>${{ selectedNode.data.label }}.folder - folder key ending with /</div>
                  <div>${{ selectedNode.data.label }}.etag - folder marker etag</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'deleteFolder'">
                  <div>${{ selectedNode.data.label }}.success - Boolean</div>
                  <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
                  <div>${{ selectedNode.data.label }}.folder - folder prefix</div>
                  <div>${{ selectedNode.data.label }}.deleted_count - number of deleted objects</div>
                  <div>${{ selectedNode.data.label }}.deleted_keys - deleted object keys</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'getAllFolder'">
                  <div>${{ selectedNode.data.label }}.folder - folder prefix</div>
                  <div>${{ selectedNode.data.label }}.count - number of objects</div>
                  <div>${{ selectedNode.data.label }}.objects - object metadata array</div>
                  <div>${{ selectedNode.data.label }}.objects[0].key - first object key</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'listBuckets'">
                  <div>${{ selectedNode.data.label }}.buckets - bucket metadata array</div>
                  <div>${{ selectedNode.data.label }}.count - number of buckets</div>
                  <div>${{ selectedNode.data.label }}.buckets[0].name - bucket name</div>
                </template>
                <template v-else-if="selectedNode.data.s3Operation === 'copyObject'">
                  <div>${{ selectedNode.data.label }}.source_bucket - source bucket</div>
                  <div>${{ selectedNode.data.label }}.source_key - source object key</div>
                  <div>${{ selectedNode.data.label }}.bucket - destination bucket</div>
                  <div>${{ selectedNode.data.label }}.key - destination object key</div>
                  <div>${{ selectedNode.data.label }}.etag - copied object etag</div>
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
              v-if="selectedNode.data.driveOperation === 'save'"
              class="space-y-4"
            >
              <div class="space-y-2">
                <Label>Filename</Label>
                <ExpressionInput
                  ref="driveFilenameExpressionInputRef"
                  :model-value="selectedNode.data.driveFilename || ''"
                  placeholder="1.mp3"
                  :rows="1"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Drive save · Filename"
                  field-key="driveFilename"
                  :navigation-enabled="true"
                  :navigation-index="0"
                  :navigation-total="driveExpressionFieldCount"
                  @navigate="handleDriveExpressionFieldNavigate"
                  @register-field-index="onDriveRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('driveFilename', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Full filename including extension (for example, 1.mp3)
                </p>
              </div>
              <div class="space-y-2">
                <Label>Base64 Content</Label>
                <ExpressionInput
                  ref="driveBase64ContentExpressionInputRef"
                  :model-value="selectedNode.data.driveBase64Content || ''"
                  placeholder="$userInput.body.base64"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  expandable
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  dialog-key-label="Drive save · Base64 Content"
                  field-key="driveBase64Content"
                  :navigation-enabled="true"
                  :navigation-index="1"
                  :navigation-total="driveExpressionFieldCount"
                  @navigate="handleDriveExpressionFieldNavigate"
                  @register-field-index="onDriveRegisterExpressionFieldIndex"
                  @update:model-value="updateNodeData('driveBase64Content', $event)"
                />
                <p class="text-xs text-muted-foreground">
                  Raw base64 string or data URL to decode and store in Drive
                </p>
              </div>
            </div>

            <div
              v-if="selectedNode.data.driveOperation && !['downloadUrl', 'getAll', 'save'].includes(selectedNode.data.driveOperation)"
              class="space-y-2"
            >
              <div class="flex items-center justify-between gap-2">
                <Label>File ID</Label>
                <AgentFieldToggle
                  :node-id="selectedNode.id"
                  field-key="driveFileId"
                />
              </div>
              <template v-if="selectedNode.data.driveOperation === 'get' || selectedNode.data.driveOperation === 'convertFile'">
                <Select
                  :model-value="selectedNode.data.driveFileId || ''"
                  :options="driveFileOptions"
                  :disabled="isDriveFileIdAgentProvided"
                  @update:model-value="updateNodeData('driveFileId', $event || undefined)"
                />
                <div
                  v-if="isDriveFileIdAgentProvided"
                  class="rounded-md border border-violet-800/30 bg-violet-950/20 px-3 py-2 text-xs italic text-violet-400"
                >
                  Agent will provide this at runtime.
                </div>
                <ExpressionInput
                  v-else
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
                <div
                  v-if="isDriveFileIdAgentProvided"
                  class="rounded-md border border-violet-800/30 bg-violet-950/20 px-3 py-2 text-xs italic text-violet-400"
                >
                  Agent will provide this at runtime.
                </div>
                <ExpressionInput
                  v-else
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
              v-if="selectedNode.data.driveOperation === 'getAll'"
              class="space-y-2"
            >
              <Label>Limit</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.driveLimit ?? ''"
                min="0"
                placeholder="No limit"
                @update:model-value="updateNodeData('driveLimit', $event !== '' ? Number($event) : undefined)"
              />
              <p class="text-xs text-muted-foreground">
                Maximum number of files to return
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
                field-key="drivePassword"
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

            <div
              v-if="selectedNode.data.driveOperation === 'convertFile'"
              class="space-y-2"
            >
              <Label>Target Format</Label>
              <Select
                :model-value="selectedNode.data.driveConvertTargetFormat || ''"
                :options="driveConvertFormatOptionsFiltered"
                @update:model-value="updateNodeData('driveConvertTargetFormat', $event || undefined)"
              />
              <p class="text-xs text-muted-foreground">
                Format to convert the file to
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
                <template v-else-if="selectedNode.data.driveOperation === 'getAll'">
                  <div>${{ selectedNode.data.label }}.files - file metadata array</div>
                  <div>${{ selectedNode.data.label }}.count - number of files</div>
                  <div>${{ selectedNode.data.label }}.files[0].filename - file name</div>
                  <div>${{ selectedNode.data.label }}.files[0].size_bytes - file size</div>
                  <div>${{ selectedNode.data.label }}.files[0].download_url - public download URL</div>
                </template>
                <template v-else-if="selectedNode.data.driveOperation === 'downloadUrl'">
                  <div>${{ selectedNode.data.label }}.id - new file UUID</div>
                  <div>${{ selectedNode.data.label }}.filename - file name</div>
                  <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
                  <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
                  <div>${{ selectedNode.data.label }}.download_url - Drive download URL</div>
                </template>
                <template v-else-if="selectedNode.data.driveOperation === 'save'">
                  <div>${{ selectedNode.data.label }}.id - new file UUID</div>
                  <div>${{ selectedNode.data.label }}.filename - file name</div>
                  <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
                  <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
                  <div>${{ selectedNode.data.label }}.download_url - Drive download URL</div>
                </template>
                <template v-else-if="selectedNode.data.driveOperation === 'convertFile'">
                  <div>${{ selectedNode.data.label }}.id - new converted file UUID</div>
                  <div>${{ selectedNode.data.label }}.filename - converted filename</div>
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
                field-key="errorMessage"
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
                  field-key="rabbitmqExchange"
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
                  field-key="rabbitmqRoutingKey"
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
                  field-key="rabbitmqQueueName"
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
                  field-key="rabbitmqMessageBody"
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
                  field-key="rabbitmqQueueName"
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
                field-key="crawlerUrl"
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

          <template v-if="selectedNode.type === 'mcpCall'">
            <div class="space-y-4">
              <!-- Connection -->
              <div class="space-y-2">
                <Label class="text-muted-foreground flex items-center gap-1">
                  <Plug class="w-3.5 h-3.5" />
                  MCP Connection
                </Label>
                <div class="rounded border p-3 space-y-2">
                  <div class="flex gap-2">
                    <div class="flex-1">
                      <Label class="text-xs">Transport</Label>
                      <Select
                        :model-value="selectedNode.data.connection?.transport ?? 'sse'"
                        :options="[
                          { value: 'stdio', label: 'stdio' },
                          { value: 'sse', label: 'SSE' },
                          { value: 'streamable_http', label: 'Streamable HTTP' },
                        ]"
                        @update:model-value="updateMCPCallConnectionField('transport', $event)"
                      />
                    </div>
                    <div class="w-24">
                      <Label class="text-xs">Timeout (s)</Label>
                      <Input
                        type="number"
                        :model-value="String(selectedNode.data.connection?.timeoutSeconds ?? 30)"
                        min="1"
                        max="3600"
                        placeholder="30"
                        @update:model-value="updateMCPCallConnectionField('timeoutSeconds', parseInt($event, 10) || 30)"
                      />
                    </div>
                  </div>
                  <div>
                    <Label class="text-xs">Label (optional)</Label>
                    <Input
                      :model-value="selectedNode.data.connection?.label ?? ''"
                      placeholder="my-mcp-server"
                      @update:model-value="updateMCPCallConnectionField('label', $event)"
                    />
                  </div>
                  <template v-if="selectedNode.data.connection?.transport === 'stdio'">
                    <div>
                      <Label class="text-xs">Command</Label>
                      <Input
                        :model-value="selectedNode.data.connection?.command ?? ''"
                        placeholder="npx"
                        @update:model-value="updateMCPCallConnectionField('command', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Args (JSON array)</Label>
                      <Textarea
                        :model-value="formatMCPJsonValue(selectedNode.data.connection?.args, [])"
                        placeholder="[&quot;-y&quot;, &quot;@modelcontextprotocol/server-filesystem&quot;]"
                        :rows="2"
                        wrap="off"
                        class="overflow-x-auto whitespace-pre font-mono text-xs"
                        @update:model-value="updateMCPCallConnectionField('args', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Env (JSON object)</Label>
                      <ExpressionInput
                        ref="mcpCallConnectionEnvInputRef"
                        :model-value="formatMCPJsonValue(selectedNode.data.connection?.env, {})"
                        placeholder="{&quot;API_KEY&quot;: &quot;your_key&quot;}"
                        :rows="2"
                        wrap="off"
                        :nodes="workflowStore.nodes"
                        :node-results="workflowStore.nodeResults"
                        :edges="workflowStore.edges"
                        :current-node-id="selectedNode.id"
                        expandable
                        :dialog-node-label="selectedNodeEvaluateDialogLabel"
                        dialog-key-label="MCP env"
                        @update:model-value="updateMCPCallConnectionField('env', $event)"
                      />
                    </div>
                  </template>
                  <template v-else-if="selectedNode.data.connection?.transport === 'sse' || selectedNode.data.connection?.transport === 'streamable_http'">
                    <div>
                      <Label class="text-xs">URL</Label>
                      <Input
                        :model-value="selectedNode.data.connection?.url ?? ''"
                        :placeholder="selectedNode.data.connection?.transport === 'streamable_http' ? 'https://example.com/mcp' : 'https://example.com/mcp/sse'"
                        @update:model-value="updateMCPCallConnectionField('url', $event)"
                      />
                    </div>
                    <div>
                      <Label class="text-xs">Headers (JSON object)</Label>
                      <Textarea
                        :model-value="formatMCPJsonValue(selectedNode.data.connection?.headers, {})"
                        placeholder="{&quot;Authorization&quot;: &quot;Bearer ...&quot;}"
                        :rows="2"
                        wrap="off"
                        class="overflow-x-auto whitespace-pre font-mono text-xs"
                        @update:model-value="updateMCPCallConnectionField('headers', $event)"
                      />
                    </div>
                  </template>
                  <!-- Fetch tools button -->
                  <div class="pt-2 flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      class="gap-1"
                      :disabled="
                        (selectedNode.data.connection?.transport === 'stdio' && !selectedNode.data.connection?.command) ||
                          ((selectedNode.data.connection?.transport === 'sse' || selectedNode.data.connection?.transport === 'streamable_http') && !selectedNode.data.connection?.url) ||
                          mcpCallFetchState.loading
                      "
                      @click="fetchMCPCallTools"
                    >
                      <Loader2
                        v-if="mcpCallFetchState.loading"
                        class="w-3.5 h-3.5 animate-spin"
                      />
                      <Server
                        v-else
                        class="w-3.5 h-3.5"
                      />
                      {{ mcpCallFetchState.loading ? "Connecting…" : "Fetch tools" }}
                    </Button>
                    <span
                      v-if="mcpCallFetchState.error"
                      class="text-xs text-destructive truncate min-w-0 flex-1"
                      :title="mcpCallFetchState.error"
                    >{{ mcpCallFetchState.error }}</span>
                    <span
                      v-else-if="mcpCallFetchState.tools.length > 0"
                      class="text-xs text-muted-foreground"
                    >{{ mcpCallFetchState.tools.length }} tool(s) found</span>
                  </div>
                </div>
              </div>

              <!-- Tool selection (required) -->
              <div class="space-y-2">
                <Label class="text-xs flex items-center gap-1">
                  Tool
                  <span class="text-destructive">*</span>
                </Label>
                <Select
                  :model-value="selectedNode.data.selectedTool ?? ''"
                  :options="mcpCallToolOptions"
                  :class="!selectedNode.data.selectedTool ? 'border-destructive' : ''"
                  @update:model-value="selectMCPCallTool($event ?? '')"
                />
                <p
                  v-if="!selectedNode.data.selectedTool"
                  class="text-xs text-destructive"
                >
                  A tool must be selected — this node will not run without one.
                </p>
                <p
                  v-else-if="mcpCallSelectedTool?.description"
                  class="text-xs text-muted-foreground leading-snug break-words"
                >
                  {{ mcpCallSelectedTool.description }}
                </p>
              </div>

              <!-- Tool arguments -->
              <div
                v-if="mcpCallSelectedTool"
                class="space-y-2"
              >
                <Label class="text-xs text-muted-foreground">Arguments</Label>
                <div
                  v-if="Object.keys(mcpCallSelectedTool.inputSchema?.properties ?? {}).length === 0"
                  class="text-xs text-muted-foreground italic"
                >
                  This tool takes no arguments.
                </div>
                <div
                  v-for="(propDef, propKey) in (mcpCallSelectedTool.inputSchema?.properties ?? {})"
                  :key="propKey"
                  class="space-y-1"
                >
                  <Label class="text-xs flex items-center gap-1">
                    {{ propKey }}
                    <span
                      v-if="mcpCallSelectedTool.inputSchema?.required?.includes(String(propKey))"
                      class="text-destructive"
                    >*</span>
                  </Label>
                  <p
                    v-if="propDef.description"
                    class="text-xs text-muted-foreground leading-snug break-words"
                  >
                    {{ propDef.description }}
                  </p>
                  <ExpressionInput
                    :ref="(el) => setMCPCallArgumentInputRef(String(propKey), el)"
                    :model-value="String(selectedNode.data.toolArguments?.[propKey] ?? '')"
                    placeholder="value or $expr"
                    single-line
                    :nodes="workflowStore.nodes"
                    :node-results="workflowStore.nodeResults"
                    :edges="workflowStore.edges"
                    :current-node-id="selectedNode.id"
                    expandable
                    navigation-enabled
                    :navigation-index="mcpCallArgumentKeys.indexOf(String(propKey))"
                    :navigation-total="mcpCallExpressionFieldCount"
                    :dialog-node-label="selectedNodeEvaluateDialogLabel"
                    :dialog-key-label="`MCP argument · ${String(propKey)}`"
                    @update:model-value="updateMCPCallArgument(String(propKey), $event)"
                    @navigate="handleMCPCallExpressionFieldNavigate"
                    @register-field-index="onMCPCallRegisterExpressionFieldIndex"
                  />
                </div>
                <p class="text-xs text-muted-foreground">
                  Values support DSL expressions: <code class="bg-muted px-1 rounded">$nodeLabel.field</code>
                </p>
              </div>

              <!-- Output reference -->
              <div class="space-y-1 pt-2 border-t">
                <Label class="text-xs text-muted-foreground">Output</Label>
                <div class="text-xs font-mono">
                  <div>${{ selectedNode.data.label }}.result — tool result (object or string)</div>
                </div>
              </div>
            </div>
          </template>

          <div
            v-if="!['textInput', 'cron', 'sticky', 'errorHandler', 'output', 'throwError', 'telegramTrigger', 'websocketTrigger', 'slackTrigger', 'discordTrigger', 'imapTrigger'].includes(selectedNode.type) && !(selectedNode.type === 'rabbitmq' && selectedNode.data.rabbitmqOperation === 'receive')"
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
            <div
              :class="[
                'flex gap-2 min-w-0',
                selectedNodeLoopItemNavigation
                  ? 'flex-col items-start'
                  : 'items-center justify-between'
              ]"
            >
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
                :class="[
                  'flex min-w-0 flex-wrap items-center gap-1.5',
                  selectedNodeLoopItemNavigation ? 'w-full justify-start' : 'shrink-0 justify-end'
                ]"
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
      @dragenter="onRunPanelFileDragEnter"
      @dragleave="onRunPanelFileDragLeave"
      @dragover="onRunPanelFileDragOver"
      @drop="onRunPanelFileDrop"
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
              <RunInputField
                :field-key="field.key"
                :model-value="runInputValues[field.key] ?? ''"
                :placeholder="field.defaultValue || `Enter ${field.key}...`"
                :disabled="isExecuting"
                :panel-file-drag-active="isRunPanelFileDragActive"
                @update:model-value="updateInputValue(field.key, $event)"
                @file-dropped="resetRunPanelFileDrag"
              />
            </div>
          </template>

          <Button
            class="w-full min-w-0"
            :class="isRunbookPlaying && 'runbook-pulse'"
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

  <SkillHistoryDialog
    :open="skillHistoryOpen"
    :workflow-id="workflowStore.currentWorkflow?.id ?? ''"
    :agent-node-id="selectedNode?.id ?? ''"
    :skill="skillHistoryTarget?.skill ?? null"
    :skill-index="skillHistoryTarget?.skillIndex ?? -1"
    :ai-edit-disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
    @edit-snapshot="handleSkillHistoryEdit"
    @revert-snapshot="handleSkillHistoryRevert"
    @fine-tune="handleSkillHistoryFineTune"
    @expand-skill="handleSkillHistoryExpandSkill"
    @update:open="skillHistoryOpen = $event"
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
