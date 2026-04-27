<script setup lang="ts">
import { computed, onMounted, watch, nextTick, ref } from "vue";
import { AlertTriangle, Ban, Bot, Brain, Braces, Bug, CalendarClock, Clock, Database, FileJson, GitBranch, GitMerge, Globe, HardDrive, Inbox, LayoutTemplate, Mail, MessageSquare, MonitorPlay, Play, Rabbit, Radio, Repeat, Search, Send, Settings2, Sheet, Shuffle, StickyNote, Table2, Terminal, Type, Variable, X, XCircle } from "lucide-vue-next";

import type { NodeTemplate } from "@/features/templates/types/template.types";
import type { NodeType, WorkflowNode } from "@/types/workflow";

import { buildWorkflowNodeFromNodeTemplate } from "@/lib/nodeFromTemplate";
import { nodeIcons } from "@/lib/nodeIcons";
import { cn, generateId, replaceInputRefs } from "@/lib/utils";
import { templatesApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { useWorkflowStore } from "@/stores/workflow";
import { NODE_DEFINITIONS } from "@/types/node";

const workflowStore = useWorkflowStore();
const authStore = useAuthStore();
const searchInputRef = ref<HTMLInputElement | null>(null);
const selectedIndex = ref<number>(-1);
const nodeTemplates = ref<NodeTemplate[]>([]);
const templatesLoadError = ref(false);

async function loadNodeTemplates(): Promise<void> {
  try {
    const res = await templatesApi.list();
    nodeTemplates.value = res.node_templates;
    templatesLoadError.value = false;
  } catch {
    nodeTemplates.value = [];
    templatesLoadError.value = true;
  }
}

onMounted(() => {
  void loadNodeTemplates();
});

const searchQuery = computed({
  get: () => workflowStore.nodeSearchQuery,
  set: (value: string) => workflowStore.setNodeSearchQuery(value),
});

watch(
  () => workflowStore.nodeSearchQuery,
  (newValue) => {
    selectedIndex.value = -1;
    if (newValue && searchInputRef.value) {
      nextTick(() => {
        searchInputRef.value?.focus();
      });
    }
  }
);

watch(
  () => workflowStore.pendingConnectionSource,
  (source) => {
    if (source && searchInputRef.value) {
      nextTick(() => {
        searchInputRef.value?.focus();
      });
    }
  }
);

watch(
  () => workflowStore.pendingInsertEdge,
  (pendingInsert) => {
    if (pendingInsert && searchInputRef.value) {
      nextTick(() => {
        searchInputRef.value?.focus();
      });
    }
  }
);

const hasPendingAction = computed(() => {
  return !!workflowStore.pendingConnectionSource || !!workflowStore.pendingInsertEdge;
});

function handleEscape(): void {
  workflowStore.clearNodeSearchQuery();
  workflowStore.clearPendingConnectionSource();
  workflowStore.clearPendingInsertEdge();
  selectedIndex.value = -1;
  searchInputRef.value?.blur();
}

function handleKeyDown(event: KeyboardEvent): void {
  const rows = paletteRows.value;
  if (rows.length === 0) return;

  if (event.key === "Tab") {
    event.preventDefault();
    if (event.shiftKey) {
      selectedIndex.value = selectedIndex.value <= 0 ? rows.length - 1 : selectedIndex.value - 1;
    } else {
      selectedIndex.value = selectedIndex.value >= rows.length - 1 ? 0 : selectedIndex.value + 1;
    }
    scrollToSelectedNode();
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    selectedIndex.value = selectedIndex.value >= rows.length - 1 ? 0 : selectedIndex.value + 1;
    scrollToSelectedNode();
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    selectedIndex.value = selectedIndex.value <= 0 ? rows.length - 1 : selectedIndex.value - 1;
    scrollToSelectedNode();
  } else if ((event.key === "Enter" || event.key === " ") && selectedIndex.value >= 0) {
    event.preventDefault();
    const row = rows[selectedIndex.value];
    if (row?.kind === "builtin") {
      handleDoubleClick(row.type);
    } else if (row?.kind === "template") {
      addNodeFromTemplate(row.template);
    }
    selectedIndex.value = -1;
  }
}

function scrollToSelectedNode(): void {
  nextTick(() => {
    const selectedElement = document.querySelector(`[data-node-index="${selectedIndex.value}"]`);
    if (selectedElement) {
      selectedElement.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
}

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

const allNodeTypes = Object.values(NODE_DEFINITIONS);

const nodeTypes = computed(() => {
  const query = searchQuery.value.toLowerCase().trim();
  if (!query) return allNodeTypes;
  return allNodeTypes.filter(
    (node) =>
      node.label.toLowerCase().includes(query) ||
      node.description.toLowerCase().includes(query)
  );
});

const filteredNodeTemplates = computed(() => {
  const query = searchQuery.value.toLowerCase().trim();
  const uid = authStore.user?.id;
  const list = [...nodeTemplates.value];
  list.sort((a, b) => {
    const aShared = uid && a.author_id !== uid ? 0 : 1;
    const bShared = uid && b.author_id !== uid ? 0 : 1;
    if (aShared !== bShared) {
      return aShared - bShared;
    }
    return 0;
  });
  if (!query) {
    return list;
  }
  return list.filter((t) => {
    const tagHit = t.tags.some((tag) => tag.toLowerCase().includes(query));
    return (
      t.name.toLowerCase().includes(query) ||
      (t.description ?? "").toLowerCase().includes(query) ||
      t.node_type.toLowerCase().includes(query) ||
      tagHit
    );
  });
});

interface PaletteBuiltin {
  kind: "builtin";
  type: NodeType;
  label: string;
  description: string;
}

interface PaletteTemplate {
  kind: "template";
  template: NodeTemplate;
}

type PaletteRow = PaletteBuiltin | PaletteTemplate;

const paletteRows = computed<PaletteRow[]>(() => {
  const builtins: PaletteRow[] = nodeTypes.value.map((node) => ({
    kind: "builtin",
    type: node.type,
    label: node.label,
    description: node.description,
  }));
  const templates: PaletteRow[] = filteredNodeTemplates.value.map((template) => ({
    kind: "template",
    template,
  }));
  return [...builtins, ...templates];
});

function isSharedTemplate(template: NodeTemplate): boolean {
  const uid = authStore.user?.id;
  return Boolean(uid && template.author_id !== uid);
}

function templateNodeColor(nodeType: string): string {
  const def = NODE_DEFINITIONS[nodeType as NodeType];
  return def?.color ?? "muted";
}

function templateRowIcon(nodeType: string) {
  const typed = nodeType as NodeType;
  return nodeIcons[typed] ?? LayoutTemplate;
}

function handleMouseDown(): void {
  if (searchInputRef.value) {
    searchInputRef.value.blur();
  }
}

function handleDragStart(event: DragEvent, type: NodeType): void {
  if (event.dataTransfer) {
    event.dataTransfer.setData("application/heym-node", type);
    event.dataTransfer.effectAllowed = "move";
  }
}

function handleTemplateDragStart(event: DragEvent, template: NodeTemplate): void {
  if (event.dataTransfer) {
    event.dataTransfer.setData("application/heym-node-template", template.id);
    event.dataTransfer.effectAllowed = "move";
  }
}

function recordTemplateUse(templateId: string): void {
  void templatesApi.useNode(templateId).catch(() => {
    // use count is best-effort
  });
}

function addNodeFromTemplate(template: NodeTemplate): void {
  const noInputTypes: NodeType[] = ["textInput", "cron", "sticky", "merge", "errorHandler", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger"];

  const pendingInsert = workflowStore.pendingInsertEdge;
  if (pendingInsert && !noInputTypes.includes(template.node_type as NodeType)) {
    const sourceNode = workflowStore.nodes.find((n) => n.id === pendingInsert.sourceId);
    const newNode = buildWorkflowNodeFromNodeTemplate(
      template,
      { x: 0, y: 0 },
      sourceNode
        ? { label: String(sourceNode.data.label), type: sourceNode.type }
        : null,
    );
    workflowStore.insertNodeBetween(newNode);
    workflowStore.clearNodeSearchQuery();
    searchInputRef.value?.blur();
    workflowStore.requestTidyUp();
    recordTemplateUse(template.id);
    return;
  }

  const canvas = document.querySelector(".vue-flow");
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const centerX = rect.width / 2 - 90;
  const centerY = rect.height / 2 - 30;

  const existingNodes = workflowStore.nodes;
  const offset = existingNodes.length * 20;

  const pendingSource = workflowStore.pendingConnectionSource;
  const sourceNode = pendingSource
    ? workflowStore.nodes.find((n) => n.id === pendingSource.nodeId)
    : null;

  const newNode = buildWorkflowNodeFromNodeTemplate(
    template,
    { x: centerX + offset, y: centerY + offset },
    sourceNode ? { label: String(sourceNode.data.label), type: sourceNode.type } : null,
  );

  workflowStore.addNode(newNode);

  if (pendingSource) {
    if (!noInputTypes.includes(template.node_type as NodeType)) {
      const edge = {
        id: `edge_${pendingSource.nodeId}_${newNode.id}_${Date.now()}`,
        source: pendingSource.nodeId,
        target: newNode.id,
        sourceHandle: pendingSource.handleId || undefined,
        targetHandle: "input",
      };
      workflowStore.addEdge(edge);
      workflowStore.clearNodeSearchQuery();
      searchInputRef.value?.blur();
      workflowStore.requestTidyUp();
    }
    workflowStore.clearPendingConnectionSource();
  }

  recordTemplateUse(template.id);
}

function handleDoubleClick(type: NodeType): void {
  const noInputTypes: NodeType[] = ["textInput", "cron", "sticky", "merge", "errorHandler", "telegramTrigger", "websocketTrigger", "slackTrigger", "imapTrigger"];

  const pendingInsert = workflowStore.pendingInsertEdge;
  if (pendingInsert && !noInputTypes.includes(type)) {
    const newNode: WorkflowNode = {
      id: generateId(),
      type,
      position: { x: 0, y: 0 },
      data: { ...NODE_DEFINITIONS[type].defaultData },
    };

    const sourceNode = workflowStore.nodes.find((n) => n.id === pendingInsert.sourceId);
    if (sourceNode) {
      newNode.data = replaceInputRefs(newNode.data, {
        label: sourceNode.data.label,
        type: sourceNode.type,
      });
    }

    workflowStore.insertNodeBetween(newNode);
    workflowStore.clearNodeSearchQuery();
    searchInputRef.value?.blur();
    workflowStore.requestTidyUp();
    return;
  }

  const canvas = document.querySelector(".vue-flow");
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const centerX = rect.width / 2 - 90;
  const centerY = rect.height / 2 - 30;

  const existingNodes = workflowStore.nodes;
  const offset = existingNodes.length * 20;

  let defaultData = { ...NODE_DEFINITIONS[type].defaultData };

  const pendingSource = workflowStore.pendingConnectionSource;
  if (pendingSource) {
    const sourceNode = workflowStore.nodes.find((n) => n.id === pendingSource.nodeId);
    if (sourceNode) {
      defaultData = replaceInputRefs(defaultData, {
        label: sourceNode.data.label,
        type: sourceNode.type,
      });
    }
  }

  const newNode: WorkflowNode = {
    id: generateId(),
    type,
    position: { x: centerX + offset, y: centerY + offset },
    data: defaultData,
  };

  workflowStore.addNode(newNode);

  if (pendingSource) {
    if (!noInputTypes.includes(type)) {
      const edge = {
        id: `edge_${pendingSource.nodeId}_${newNode.id}_${Date.now()}`,
        source: pendingSource.nodeId,
        target: newNode.id,
        sourceHandle: pendingSource.handleId || undefined,
        targetHandle: "input",
      };
      workflowStore.addEdge(edge);
      workflowStore.clearNodeSearchQuery();
      searchInputRef.value?.blur();
      workflowStore.requestTidyUp();
    }
    workflowStore.clearPendingConnectionSource();
  }
}
</script>

<template>
  <div
    :class="cn(
      'node-panel w-80 sm:w-72 md:w-[280px] border-r border-border/40 p-4 flex flex-col h-full transition-all max-w-full overflow-x-hidden',
      hasPendingAction && 'ring-2 ring-primary/40 ring-inset'
    )"
  >
    <div class="flex items-center justify-between mb-4 shrink-0">
      <h2 class="font-semibold text-sm text-foreground flex items-center gap-2">
        Nodes
        <span
          v-if="workflowStore.pendingInsertEdge"
          class="text-xs font-medium text-primary px-2 py-0.5 rounded-full bg-primary/10"
        >
          Insert
        </span>
      </h2>
      <span class="text-xs text-muted-foreground">
        <span class="hidden sm:inline">{{ paletteRows.length }} available</span>
      </span>
    </div>
    <div class="relative mb-4 shrink-0">
      <Search class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
      <input
        ref="searchInputRef"
        v-model="searchQuery"
        type="text"
        :placeholder="workflowStore.pendingInsertEdge ? 'Select node...' : 'Search nodes...'"
        :class="cn(
          'w-full h-11 min-h-[44px] pl-10 pr-9 text-sm bg-background border border-border rounded-xl shadow-sm',
          'focus:outline-none focus:ring-2 focus:ring-primary/15 focus:border-primary',
          'placeholder:text-muted-foreground/60 transition-all duration-200',
          hasPendingAction && 'border-primary/50 ring-2 ring-primary/10'
        )"
        @keydown="handleKeyDown"
        @keydown.esc="handleEscape"
      >
      <button
        v-if="searchQuery"
        class="absolute right-2.5 top-1/2 -translate-y-1/2 w-11 h-11 min-h-[44px] min-w-[44px] flex items-center justify-center rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
        @click="workflowStore.clearNodeSearchQuery()"
      >
        <X class="w-4 h-4" />
      </button>
    </div>
    <div class="flex-1 overflow-y-auto min-h-0 scrollbar-thin">
      <div class="space-y-2 pr-1">
        <div
          v-for="(node, index) in nodeTypes"
          :key="node.type"
          :data-node-index="index"
          :draggable="true"
          :class="cn(
            'node-item flex items-center gap-3 p-3 rounded-xl border border-border/40 cursor-grab transition-all duration-200 min-h-[44px]',
            'hover:border-primary/40 hover:bg-accent/50 hover:shadow-sm active:cursor-grabbing',
            selectedIndex === index && 'border-primary bg-accent ring-2 ring-primary/20'
          )
          "
          @mousedown="handleMouseDown"
          @dragstart="handleDragStart($event, node.type)"
          @dblclick="handleDoubleClick(node.type)"
        >
          <div
            :class="cn(
              'node-icon flex items-center justify-center w-10 h-10 rounded-xl shrink-0 transition-all duration-200'
            )
            "
            :style="{
              backgroundColor: `hsl(var(--${node.color}) / 0.12)`,
              color: `hsl(var(--${node.color}))`,
            }"
          >
            <component
              :is="icons[node.type]"
              class="w-5 h-5"
            />
          </div>
          <div class="min-w-0 flex-1">
            <div class="font-medium text-sm leading-tight">
              {{ node.label }}
            </div>
            <div class="text-xs text-muted-foreground line-clamp-1 mt-0.5 hidden md:block">
              {{ node.description }}
            </div>
          </div>
        </div>
        <template v-if="filteredNodeTemplates.length > 0 || templatesLoadError">
          <div class="pt-4 pb-1">
            <h3 class="text-xs font-semibold uppercase tracking-wide text-muted-foreground flex items-center gap-2">
              <LayoutTemplate class="w-3.5 h-3.5" />
              Templates
            </h3>
          </div>
          <p
            v-if="templatesLoadError"
            class="text-xs text-muted-foreground px-1 pb-2"
          >
            Could not load templates.
          </p>
          <div
            v-for="(row, tIndex) in filteredNodeTemplates"
            :key="row.id"
            :data-node-index="nodeTypes.length + tIndex"
            :draggable="true"
            :class="cn(
              'node-item flex items-center gap-3 p-3 rounded-xl border border-border/40 cursor-grab transition-all duration-200 min-h-[44px]',
              'hover:border-primary/40 hover:bg-accent/50 hover:shadow-sm active:cursor-grabbing',
              selectedIndex === nodeTypes.length + tIndex && 'border-primary bg-accent ring-2 ring-primary/20'
            )"
            @mousedown="handleMouseDown"
            @dragstart="handleTemplateDragStart($event, row)"
            @dblclick="addNodeFromTemplate(row)"
          >
            <div
              class="node-icon flex items-center justify-center w-10 h-10 rounded-xl shrink-0 transition-all duration-200"
              :style="{
                backgroundColor: `hsl(var(--${templateNodeColor(row.node_type)}) / 0.12)`,
                color: `hsl(var(--${templateNodeColor(row.node_type)}))`,
              }"
            >
              <component
                :is="templateRowIcon(row.node_type)"
                class="w-5 h-5"
              />
            </div>
            <div class="min-w-0 flex-1">
              <div class="font-medium text-sm leading-tight flex items-center gap-2 flex-wrap">
                {{ row.name }}
                <span
                  v-if="isSharedTemplate(row)"
                  class="text-[10px] font-medium uppercase tracking-wide text-primary px-1.5 py-0.5 rounded bg-primary/10"
                >
                  Shared
                </span>
              </div>
              <div class="text-xs text-muted-foreground line-clamp-1 mt-0.5 hidden md:block">
                {{ row.description || row.node_type }}
              </div>
            </div>
          </div>
        </template>
        <div
          v-if="paletteRows.length === 0"
          class="text-center py-8"
        >
          <Search class="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
          <p class="text-sm text-muted-foreground">
            No nodes found
          </p>
          <p class="text-xs text-muted-foreground/60 mt-1">
            Try a different search term
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.node-panel {
  background: hsl(var(--card) / 0.98);
  backdrop-filter: blur(12px);
}

.node-item {
  background: hsl(var(--background) / 0.6);
}

.node-item:hover .node-icon {
  transform: scale(1.08);
  box-shadow: 0 4px 12px hsl(var(--primary) / 0.15);
}
</style>
