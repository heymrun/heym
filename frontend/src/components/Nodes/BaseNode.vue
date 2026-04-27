<script setup lang="ts">
import { computed } from "vue";
import { Handle, Position } from "@vue-flow/core";
import { AlertTriangle, Ban, Bot, Brain, Braces, Bug, CalendarClock, Clock, Database, FileJson, GitBranch, GitMerge, Globe, HardDrive, Inbox, Loader2, Mail, MessageSquare, MonitorPlay, Pin, Play, Rabbit, Radio, RefreshCw, Repeat, Search, Send, Settings2, Sheet, Shuffle, StickyNote, Table2, Terminal, Type, Variable, XCircle } from "lucide-vue-next";

import type { NodeData, NodeType } from "@/types/workflow";

import { nodeIconColorClass } from "@/lib/nodeIcons";
import { cn } from "@/lib/utils";

interface Props {
  id: string;
  type: NodeType;
  data: NodeData;
  selected?: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "openAgentMemory", nodeId: string): void;
}>();

const icons = {
  textInput: Type,
  cron: CalendarClock,
  telegramTrigger: MessageSquare,
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

const nodeColorMap = {
  textInput: "node-input",
  cron: "node-cron",
  telegramTrigger: "node-telegram",
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
  dataTable: "node-datatable",
  throwError: "node-throw-error",
  rabbitmq: "node-rabbitmq",
  crawler: "node-crawler",
  consoleLog: "node-console-log",
  playwright: "node-playwright",
  drive: "node-drive",
};

const isSubAgentNode = computed(
  () => props.type === "agent" && !!props.data.isSubAgent
);

const hasInput = computed(
  () => !isSubAgentNode.value
    && props.type !== "textInput"
    && props.type !== "cron"
    && props.type !== "sticky"
    && props.type !== "merge"
    && props.type !== "errorHandler"
    && props.type !== "telegramTrigger"
    && props.type !== "websocketTrigger"
    && props.type !== "slackTrigger"
    && props.type !== "imapTrigger"
    && !(props.type === "rabbitmq" && props.data.rabbitmqOperation === "receive")
);
const hasOutput = computed(() => {
  if (isSubAgentNode.value) return false;
  if (props.type === "output") {
    return props.data.allowDownstream === true;
  }
  return (
    props.type !== "condition"
    && props.type !== "switch"
    && props.type !== "sticky"
    && props.type !== "loop"
    && props.type !== "throwError"
    && props.type !== "jsonOutputMapper"
  );
});
const hasSecondOutput = computed(() => props.type === "condition");
const hasLoopOutput = computed(() => props.type === "loop");
const hasMultiOutput = computed(() => props.type === "switch");
const hasHitlOutput = computed(
  () => !isSubAgentNode.value && props.type === "agent" && props.data.hitlEnabled === true
);
const hasBatchStatusOutput = computed(
  () => !isSubAgentNode.value && props.type === "llm" && props.data.batchModeEnabled === true,
);
const hasErrorOutput = computed(() => {
  if (isSubAgentNode.value) return false;
  const excludedTypes = [
    "textInput",
    "cron",
    "sticky",
    "errorHandler",
    "output",
    "throwError",
    "telegramTrigger",
  ];
  if (excludedTypes.includes(props.type)) return false;
  return props.data.onErrorEnabled === true;
});
const specialOutputCount = computed(
  () => Number(hasHitlOutput.value) + Number(hasBatchStatusOutput.value) + Number(hasErrorOutput.value),
);
const outputStackPaddingClass = computed(() => {
  if (specialOutputCount.value >= 3) return "pr-32";
  if (specialOutputCount.value === 2) return "pr-28";
  if (hasBatchStatusOutput.value) return "pr-28";
  if (hasHitlOutput.value) return "pr-24";
  if (hasErrorOutput.value) return "pr-16";
  return "";
});
const hasMultiInput = computed(() => props.type === "merge");
const switchCases = computed(() => props.data.cases || []);
const switchHandles = computed(() => [
  ...switchCases.value.map((caseValue, index) => ({
    id: `case-${index}`,
    label: caseValue || `case ${index + 1}`,
  })),
  { id: "default", label: "default" },
]);
const mergeInputCount = computed(() => props.data.inputCount || 2);
const executeTargetInfo = computed(() => {
  if (props.type !== "execute") return null;
  const fields = props.data.targetWorkflowInputFields || [];
  const name = props.data.targetWorkflowName || null;
  return { name, fieldCount: fields.length, fields };
});
const subWorkflowTargetInfo = computed(() => {
  if (props.type !== "agent") return null;
  const ids = props.data.subWorkflowIds || [];
  const names = props.data.subWorkflowNames || {};
  const labels = ids.map((id) => names[id] || id.slice(0, 8) + "...");
  return { labels, count: ids.length };
});
const mergeInputHandles = computed(() =>
  Array.from({ length: mergeInputCount.value }, (_, i) => ({
    id: `input-${i}`,
    label: `${i + 1}`,
  }))
);
const nodeHeight = computed(() => {
  if (props.type === "switch") {
    const count = Math.max(1, switchHandles.value.length);
    const baseHeight = 80;
    const extraHeight = Math.max(0, count - 2) * 18;
    return `${baseHeight + extraHeight}px`;
  }
  if (props.type === "merge") {
    const count = Math.max(2, mergeInputCount.value);
    const baseHeight = 60;
    const extraHeight = Math.max(0, count - 2) * 24;
    return `${baseHeight + extraHeight}px`;
  }
  return undefined;
});
const isRunning = computed(() => props.data.status === "running");
const isSuccess = computed(() => props.data.status === "success");
const isError = computed(() => props.data.status === "error");
const isSkipped = computed(() => props.data.status === "skipped");
const isInactive = computed(() => props.data.active === false);
const batchRuntimeLabel = computed(() => {
  if (!props.data.batchRuntimeStatus) return null;
  const counts = props.data.batchRuntimeRequestCounts;
  if (counts && typeof counts.total === "number" && counts.total > 0) {
    return `${props.data.batchRuntimeStatus} ${counts.completed}/${counts.total}`;
  }
  return props.data.batchRuntimeStatus;
});
const batchRuntimeBadgeClass = computed(() => {
  if (props.data.batchRuntimeStatus === "completed") {
    return "text-success bg-success/10";
  }
  if (props.data.batchRuntimeStatus === "failed") {
    return "text-destructive bg-destructive/10";
  }
  return "text-node-llm bg-node-llm/10";
});

const Icon = computed(() => icons[props.type]);

const RESERVED_NAMES = new Set([
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

const hasReservedLabelError = computed(() => {
  const label = props.data.label;
  if (!label) return false;
  return RESERVED_NAMES.has(label.toLowerCase());
});

const hasReservedKeyError = computed(() => {
  const data = props.data;

  if (props.type === "variable" && data.variableName) {
    if (RESERVED_NAMES.has(data.variableName.toLowerCase())) {
      return true;
    }
  }

  if (data.mappings) {
    for (const mapping of data.mappings) {
      if (mapping.key && RESERVED_NAMES.has(mapping.key.toLowerCase())) {
        return true;
      }
    }
  }

  if (data.inputFields) {
    for (const field of data.inputFields) {
      if (field.key && RESERVED_NAMES.has(field.key.toLowerCase())) {
        return true;
      }
    }
  }

  return false;
});

const hasExpressionWarning = computed(() => {
  return false;
});

const hasThrowErrorWarning = computed(() => {
  if (props.type !== "throwError") return false;
  const hasMessage = props.data.errorMessage && props.data.errorMessage.trim() !== "";
  const hasHttpCode = props.data.httpStatusCode !== undefined && props.data.httpStatusCode !== null;
  return !hasMessage && !hasHttpCode;
});

</script>

<template>
  <div
    :style="{
      minHeight: nodeHeight || '60px',
      '--tw-ring-color': selected && !isRunning && !isSuccess && !isError ? `hsl(var(--${nodeColorMap[type]}))` : undefined,
      borderColor: !isInactive && !isRunning ? `hsl(var(--${nodeColorMap[type]}) / 0.6)` : undefined,
      backgroundColor: !isInactive ? `hsl(var(--card))` : undefined
    }"
    :class="cn(
      'node-base px-4 pt-5 pb-3.5 border rounded-xl min-w-[190px] transition-all duration-200 relative overflow-hidden',
      outputStackPaddingClass,
      isInactive && 'border-muted-foreground/30 bg-muted/50',
      selected && !isRunning && !isSuccess && !isError && 'ring-2 ring-offset-2 ring-offset-background shadow-lg',
      isRunning && 'animate-heartbeat ring-2 ring-success ring-offset-2 ring-offset-background border-success',
      isSuccess && 'ring-2 ring-success/80 ring-offset-1 ring-offset-background',
      isError && 'ring-2 ring-destructive/80 ring-offset-1 ring-offset-background',
      isSkipped && 'opacity-60 ring-1 ring-muted-foreground ring-offset-1 ring-offset-background',
      isInactive && 'opacity-60',
      (hasExpressionWarning || hasReservedKeyError || hasReservedLabelError || hasThrowErrorWarning) && 'pb-8'
    )
    "
  >
    <div
      v-if="!isInactive"
      class="node-accent absolute top-0 left-0 right-0 h-[3px]"
      :style="{
        backgroundColor: `hsl(var(--${nodeColorMap[type]}))`
      }"
    />
    <div
      v-else
      class="node-accent absolute top-0 left-0 right-0 h-[3px] bg-muted-foreground/40"
    />

    <Handle
      v-if="hasInput"
      id="input"
      type="target"
      :position="Position.Left"
      class="!w-3.5 !h-3.5"
    />

    <div
      v-if="type === 'agent' && data.isSubAgent"
      class="absolute -top-1 left-1/2 -translate-x-1/2"
    >
      <Handle
        id="sub-agent-input"
        type="target"
        :position="Position.Top"
        :connectable="false"
        class="!w-3.5 !h-3.5"
      />
    </div>

    <div
      v-if="hasMultiInput"
      class="absolute -left-1 top-1/2 -translate-y-1/2 flex flex-col items-start gap-3"
    >
      <div
        v-for="handle in mergeInputHandles"
        :key="handle.id"
        class="flex items-center"
      >
        <Handle
          :id="handle.id"
          type="target"
          :position="Position.Left"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !left-0"
        />
        <span class="text-[10px] text-muted-foreground font-medium ml-1.5">
          {{ handle.label }}
        </span>
      </div>
    </div>

    <div class="flex items-center gap-3.5">
      <div
        :class="cn(
          'flex items-center justify-center w-9 h-9 rounded-lg shrink-0 transition-all',
          isInactive ? 'bg-muted-foreground/15' : ''
        )
        "
        :style="!isInactive ? {
          backgroundColor: `hsl(var(--${nodeColorMap[type]}) / 0.12)`,
        } : undefined"
      >
        <Loader2
          v-if="isRunning"
          :class="cn('w-4.5 h-4.5 animate-spin', nodeIconColorClass[type])"
        />
        <component
          :is="Icon"
          v-else
          :class="cn('w-4.5 h-4.5', isInactive ? 'text-muted-foreground/70' : nodeIconColorClass[type])"
        />
      </div>
      <div class="min-w-0">
        <div class="font-semibold text-sm flex items-center gap-2 leading-tight">
          <span :class="cn('truncate max-w-[140px]', isInactive && 'text-muted-foreground')">{{ data.label }}</span>
          <Pin
            v-if="data.pinnedData"
            class="w-3 h-3 text-warning shrink-0"
          />
          <RefreshCw
            v-if="data.retryEnabled"
            class="w-3 h-3 text-accent-blue shrink-0"
            title="Retry on failure enabled"
          />
          <span
            v-if="isRunning && data.retryAttempt && data.retryAttempt > 1"
            class="text-[10px] text-accent-blue font-medium px-1.5 py-0.5 bg-accent-blue/10 rounded"
          >retry {{ data.retryAttempt }}/{{ data.retryMaxAttempts || 3 }}</span>
          <span
            v-else-if="isRunning"
            class="text-[10px] text-success font-medium px-1.5 py-0.5 bg-success/10 rounded"
          >running</span>
          <span
            v-if="isInactive"
            class="text-[10px] text-muted-foreground/80 font-medium px-1.5 py-0.5 bg-muted-foreground/10 rounded"
          >off</span>
          <span
            v-if="type === 'agent' && data.isSubAgent && !isInactive"
            class="text-[10px] text-muted-foreground font-medium px-1.5 py-0.5 bg-muted/50 rounded border border-dashed border-muted-foreground/40"
          >sub-agent</span>
        </div>
        <div
          v-if="type === 'llm' && data.model"
          class="text-xs text-muted-foreground flex items-center gap-1.5 flex-wrap"
        >
          <span>{{ data.model }}</span>
          <span
            v-if="type === 'llm' && batchRuntimeLabel"
            :class="['text-[10px] font-medium px-1.5 py-0.5 rounded', batchRuntimeBadgeClass]"
          >{{ batchRuntimeLabel }}</span>
        </div>
        <div
          v-if="type === 'agent' && (data.model || data.persistentMemoryEnabled)"
          class="text-xs text-muted-foreground flex items-center gap-1.5 flex-wrap"
        >
          <span v-if="data.model">{{ data.model }}</span>
          <button
            v-if="data.persistentMemoryEnabled"
            type="button"
            class="inline-flex items-center justify-center rounded-md p-0.5 text-pink-500 hover:bg-pink-500/15 animate-pulse shrink-0"
            title="Persistent memory (background updates after runs). Click to edit graph."
            aria-label="Open agent memory graph"
            @click.stop="emit('openAgentMemory', id)"
          >
            <Brain class="w-3.5 h-3.5" />
          </button>
        </div>
        <div
          v-if="type === 'wait' && data.duration"
          class="text-xs text-muted-foreground"
        >
          {{ data.duration }}ms
        </div>
        <div
          v-if="type === 'execute' && executeTargetInfo?.name"
          class="text-xs text-muted-foreground truncate max-w-[120px]"
          :title="executeTargetInfo.name"
        >
          → {{ executeTargetInfo.name }}
        </div>
        <div
          v-if="type === 'agent' && subWorkflowTargetInfo && subWorkflowTargetInfo.count > 0"
          class="text-xs text-muted-foreground truncate max-w-[140px]"
          :title="subWorkflowTargetInfo.labels.join(', ')"
        >
          {{ subWorkflowTargetInfo.count > 1 ? `${subWorkflowTargetInfo.count} ` : "" }}→ {{ subWorkflowTargetInfo.labels.slice(0, 2).join(", ") }}{{ subWorkflowTargetInfo.count > 2 ? ` +${subWorkflowTargetInfo.count - 2}` : "" }}
        </div>
        <div
          v-if="type === 'variable' && data.variableName"
          class="text-xs text-muted-foreground"
        >
          {{ data.variableName }}
        </div>
        <div
          v-if="type === 'loop' && data.arrayExpression"
          class="text-xs text-muted-foreground truncate max-w-[120px]"
          :title="data.arrayExpression"
        >
          {{ data.arrayExpression }}
        </div>
        <div
          v-if="type === 'grist' && data.gristOperation"
          class="text-xs text-muted-foreground"
        >
          {{ data.gristOperation }}
        </div>
        <div
          v-if="type === 'grist' && data.gristTableId"
          class="text-xs text-muted-foreground truncate max-w-[120px]"
          :title="data.gristTableId"
        >
          {{ data.gristTableId }}
        </div>
        <div
          v-if="type === 'drive' && data.driveOperation"
          class="text-xs text-muted-foreground"
        >
          {{ data.driveOperation }}
        </div>
      </div>
    </div>

    <div
      v-if="type === 'execute' && executeTargetInfo && executeTargetInfo.fieldCount > 0"
      class="mt-2 pt-2 border-t border-border/50"
    >
      <div class="flex flex-wrap gap-1">
        <span
          v-for="field in executeTargetInfo.fields.slice(0, 4)"
          :key="field.key"
          class="text-[10px] px-1.5 py-0.5 rounded bg-node-execute/20 text-node-execute"
        >
          {{ field.key }}
        </span>
        <span
          v-if="executeTargetInfo.fieldCount > 4"
          class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground"
        >
          +{{ executeTargetInfo.fieldCount - 4 }}
        </span>
      </div>
    </div>

    <div
      v-if="hasOutput && !hasSecondOutput && !hasErrorOutput && !hasHitlOutput && !hasBatchStatusOutput"
      class="absolute right-0 top-1/2 -translate-y-1/2"
    >
      <Handle
        id="output"
        type="source"
        :position="Position.Right"
        class="!w-3.5 !h-3.5"
      />
    </div>

    <div
      v-if="hasOutput && !hasSecondOutput && (hasErrorOutput || hasHitlOutput || hasBatchStatusOutput)"
      class="absolute -right-1 top-1/2 -translate-y-1/2 flex flex-col items-end gap-2.5"
    >
      <div class="flex items-center">
        <span class="text-[9px] uppercase tracking-[0.16em] text-muted-foreground font-semibold mr-1.5 px-1.5 py-0.5 rounded bg-muted/60">OUT</span>
        <Handle
          id="output"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div
        v-if="hasBatchStatusOutput"
        class="flex items-center"
      >
        <span class="text-[9px] uppercase tracking-[0.16em] text-node-llm font-semibold mr-1.5 px-1.5 py-0.5 rounded bg-node-llm/12">STATUS</span>
        <Handle
          id="batchStatus"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div
        v-if="hasHitlOutput"
        class="flex items-center"
      >
        <span class="text-[9px] uppercase tracking-[0.16em] text-node-agent font-semibold mr-1.5 px-1.5 py-0.5 rounded bg-node-agent/12">HITL</span>
        <Handle
          id="hitl"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div
        v-if="hasErrorOutput"
        class="flex items-center"
      >
        <span class="text-[9px] uppercase tracking-[0.16em] text-destructive font-semibold mr-1.5 px-1.5 py-0.5 rounded bg-destructive/10">ERR</span>
        <Handle
          id="error"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
    </div>

    <div
      v-if="hasSecondOutput"
      class="absolute -right-1 top-1/2 -translate-y-1/2 flex flex-col items-end gap-5"
    >
      <div class="flex items-center">
        <span class="text-[10px] text-success font-medium mr-1.5 px-1.5 py-0.5 rounded bg-success/10">true</span>
        <Handle
          id="true"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div class="flex items-center">
        <span class="text-[10px] text-destructive font-medium mr-1.5 px-1.5 py-0.5 rounded bg-destructive/10">false</span>
        <Handle
          id="false"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div
        v-if="hasErrorOutput"
        class="flex items-center"
      >
        <span class="text-[10px] text-destructive font-medium mr-1.5 px-1.5 py-0.5 rounded bg-destructive/10">error</span>
        <Handle
          id="error"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
    </div>

    <div
      v-if="hasLoopOutput"
      class="absolute -right-1 top-1/2 -translate-y-1/2 flex flex-col items-end gap-5"
    >
      <div class="flex items-center">
        <span class="text-[10px] text-node-loop font-medium mr-1.5 px-1.5 py-0.5 rounded bg-node-loop/10">loop</span>
        <Handle
          id="loop"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div class="flex items-center">
        <span class="text-[10px] text-success font-medium mr-1.5 px-1.5 py-0.5 rounded bg-success/10">done</span>
        <Handle
          id="done"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div
        v-if="hasErrorOutput"
        class="flex items-center"
      >
        <span class="text-[10px] text-destructive font-medium mr-1.5 px-1.5 py-0.5 rounded bg-destructive/10">error</span>
        <Handle
          id="error"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
    </div>

    <div
      v-if="hasMultiOutput"
      class="absolute -right-1 top-1/2 -translate-y-1/2 flex flex-col items-end gap-3"
    >
      <div
        v-for="handle in switchHandles"
        :key="handle.id"
        class="flex items-center"
      >
        <span class="text-[10px] text-muted-foreground font-medium mr-1.5 truncate max-w-[65px] px-1.5 py-0.5 rounded bg-muted/50">
          {{ handle.label }}
        </span>
        <Handle
          :id="handle.id"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
      <div
        v-if="hasErrorOutput"
        class="flex items-center"
      >
        <span class="text-[10px] text-destructive font-medium mr-1.5 px-1.5 py-0.5 rounded bg-destructive/10">error</span>
        <Handle
          id="error"
          type="source"
          :position="Position.Right"
          class="!w-3.5 !h-3.5 !relative !transform-none !top-0 !right-0"
        />
      </div>
    </div>

    <div
      v-if="type === 'agent' && data.isOrchestrator && (data.subAgentLabels?.length ?? 0) > 0"
      class="absolute -bottom-1 left-1/2 -translate-x-1/2"
    >
      <Handle
        id="sub-agents"
        type="source"
        :position="Position.Bottom"
        :connectable="false"
        class="!w-3.5 !h-3.5"
      />
    </div>

    <div
      v-if="hasReservedLabelError || hasReservedKeyError || hasExpressionWarning || hasThrowErrorWarning"
      class="absolute bottom-1 left-2 flex items-center gap-1"
    >
      <div
        v-if="hasReservedLabelError"
        class="group relative"
        title="Reserved name"
      >
        <AlertTriangle class="w-4 h-4 text-red-500" />
        <div class="pointer-events-none absolute bottom-full left-0 mb-2 hidden group-hover:block z-50">
          <div
            class="w-max max-w-[220px] bg-red-500/10 border border-red-500/50 text-red-500 text-xs px-2 py-1 rounded shadow-lg whitespace-normal leading-relaxed"
          >
            "{{ data.label }}" is a reserved name
          </div>
        </div>
      </div>
      <div
        v-if="hasReservedKeyError && !hasReservedLabelError"
        class="group relative"
        title="Reserved key name used"
      >
        <AlertTriangle class="w-4 h-4 text-red-500" />
        <div class="pointer-events-none absolute bottom-full left-0 mb-2 hidden group-hover:block z-50">
          <div
            class="w-max max-w-[220px] bg-red-500/10 border border-red-500/50 text-red-500 text-xs px-2 py-1 rounded shadow-lg whitespace-normal leading-relaxed"
          >
            Reserved key name used
          </div>
        </div>
      </div>
      <div
        v-if="hasExpressionWarning"
        class="group relative"
        title="Nested $ in method parameter is not allowed"
      >
        <AlertTriangle class="w-4 h-4 text-amber-500" />
        <div class="pointer-events-none absolute bottom-full left-0 mb-2 hidden group-hover:block z-50">
          <div
            class="w-max max-w-[220px] bg-amber-500/10 border border-amber-500/50 text-amber-500 text-xs px-2 py-1 rounded shadow-lg whitespace-normal leading-relaxed"
          >
            Nested $ in method parameter is not allowed
          </div>
        </div>
      </div>
      <div
        v-if="hasThrowErrorWarning"
        class="group relative"
        title="Error message or HTTP status code is required"
      >
        <AlertTriangle class="w-4 h-4 text-amber-500" />
        <div class="pointer-events-none absolute bottom-full left-0 mb-2 hidden group-hover:block z-50">
          <div
            class="w-max max-w-[220px] bg-amber-500/10 border border-amber-500/50 text-amber-500 text-xs px-2 py-1 rounded shadow-lg whitespace-normal leading-relaxed"
          >
            Error message or HTTP status code is required
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.node-base {
  box-shadow:
    0 1px 2px hsl(0 0% 0% / 0.04),
    0 2px 8px hsl(0 0% 0% / 0.06);
}

.node-base:hover {
  box-shadow:
    0 4px 12px hsl(0 0% 0% / 0.08),
    0 2px 4px hsl(0 0% 0% / 0.04);
}

.dark .node-base {
  box-shadow:
    0 1px 2px hsl(0 0% 0% / 0.15),
    0 4px 12px hsl(0 0% 0% / 0.2);
}

.dark .node-base:hover {
  box-shadow:
    0 8px 24px hsl(0 0% 0% / 0.25),
    0 2px 8px hsl(0 0% 0% / 0.15);
}
</style>
