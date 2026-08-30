<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Grid3X3,
  MoreHorizontal,
  Play,
  SlidersHorizontal,
} from "lucide-vue-next";

import MobileWorkflowTreeHeader from "@/components/Canvas/MobileWorkflowTreeHeader.vue";
import MobileWorkflowTreeMore from "@/components/Canvas/MobileWorkflowTreeMore.vue";
import MobileWorkflowTreeNodesTab from "@/components/Canvas/MobileWorkflowTreeNodesTab.vue";
import DebugPanel from "@/components/Panels/DebugPanel.vue";
import { NODE_DEFINITIONS } from "@/types/node";
import { useThemeStore } from "@/stores/theme";
import { useWorkflowStore } from "@/stores/workflow";

const emit = defineEmits<{
  (event: "home"): void;
  (event: "save"): void;
  (event: "history"): void;
  (event: "search"): void;
  (event: "share"): void;
  (event: "clear"): void;
  (event: "edit-history"): void;
  (event: "download"): void;
  (event: "portal"): void;
  (event: "template"): void;
  (event: "curl"): void;
  (event: "guide"): void;
}>();

type MobileTab = "nodes" | "properties" | "run" | "more";

const workflowStore = useWorkflowStore();
const themeStore = useThemeStore();
const activeTab = computed({
  get: () => workflowStore.mobileEditorTab,
  set: (tab: MobileTab) => {
    workflowStore.mobileEditorTab = tab;
  },
});
const aiAssistantOpen = ref(false);
const execution = computed(() => workflowStore.executionResult);
const executionStartedAt = computed(() => {
  const historyId = execution.value?.execution_history_id;
  if (!historyId) return undefined;
  return workflowStore.executionHistoryList.find((entry) => entry.id === historyId)?.started_at;
});
const selectedNode = computed(() => workflowStore.selectedNode);
const status = computed(() => execution.value?.status ?? (workflowStore.isExecuting ? "running" : "idle"));
const statusText = computed(() => status.value.replace(/_/g, " "));
const duration = computed(() => formatDuration(execution.value?.execution_time_ms));
const isDashboardWidget = computed(() => workflowStore.currentWorkflow?.kind === "dashboard_widget");
const isStandardWorkflow = computed(() => !isDashboardWidget.value);

function formatDuration(value: number | undefined): string {
  if (!value) return "—";
  return value < 1_000 ? `${Math.round(value)}ms` : `${(value / 1_000).toFixed(1)}s`;
}

function formatExecutedAt(value: string | undefined): string {
  if (!value) return "Not run yet";
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1_000));
  if (elapsedSeconds < 60) return "Executed just now";
  if (elapsedSeconds < 3_600) return `Executed ${Math.floor(elapsedSeconds / 60)}m ago`;
  return `Executed ${Math.floor(elapsedSeconds / 3_600)}h ago`;
}

function openTab(tab: MobileTab): void {
  activeTab.value = tab;
}

function openProperties(): void {
  if (!workflowStore.selectedNode && workflowStore.nodes.length > 0) {
    workflowStore.selectNode(workflowStore.nodes[0].id);
  }
  workflowStore.propertiesPanelTab = "properties";
  openTab("properties");
}

function openRun(): void {
  workflowStore.propertiesPanelTab = "config";
  openTab("run");
}

function openWorkflowProperties(): void {
  workflowStore.clearSelection();
  workflowStore.propertiesPanelTab = "properties";
  openTab("properties");
}

function openAiAssistant(): void {
  aiAssistantOpen.value = true;
}

</script>

<template>
  <section class="flex h-full min-h-0 flex-col bg-background text-foreground md:hidden">
    <MobileWorkflowTreeHeader
      @home="emit('home')"
      @save="emit('save')"
      @history="emit('history')"
      @search="emit('search')"
      @settings="openWorkflowProperties"
    />

    <div class="flex h-9 shrink-0 items-center justify-between border-b border-border/70 px-4 text-[11px] text-muted-foreground">
      <div class="flex min-w-0 items-center gap-3">
        <span class="inline-flex items-center gap-1.5 capitalize">
          <span
            class="h-2 w-2 rounded-full"
            :class="status === 'success' ? 'bg-emerald-400' : status === 'error' ? 'bg-destructive' : 'bg-amber-400'"
          />
          Status: <strong :class="status === 'success' ? 'text-emerald-400' : 'text-foreground'">{{ statusText }}</strong>
        </span>
        <span>Duration: <strong class="text-foreground">{{ duration }}</strong></span>
      </div>
      <span class="shrink-0 text-[10px] text-muted-foreground/70">{{ formatExecutedAt(executionStartedAt) }}</span>
    </div>

    <main class="min-h-0 flex-1 overflow-y-auto p-3">
      <MobileWorkflowTreeNodesTab
        v-if="activeTab === 'nodes'"
        @open-properties="openProperties"
      />

      <slot
        v-else-if="activeTab === 'properties'"
        name="properties"
      >
        <section class="rounded-xl border border-border/70 bg-card p-4">
          <p class="text-xs font-semibold">
            Node properties
          </p>
          <p class="mt-2 text-xs text-muted-foreground">
            {{ selectedNode ? `${selectedNode.data.label || NODE_DEFINITIONS[selectedNode.type].label} is selected.` : "Select a node from the workflow tree." }}
          </p>
        </section>
      </slot>

      <slot
        v-else-if="activeTab === 'run'"
        name="run"
      >
        <section class="rounded-xl border border-border/70 bg-card p-4 text-sm text-muted-foreground">
          Open the Run panel to configure inputs and execute this workflow.
        </section>
      </slot>

      <MobileWorkflowTreeMore
        v-else
        :is-dashboard-widget="isDashboardWidget"
        :is-standard-workflow="isStandardWorkflow"
        :is-dark="themeStore.isDark"
        @back="emit('home')"
        @clear="emit('clear')"
        @edit-history="emit('edit-history')"
        @download="emit('download')"
        @portal="emit('portal')"
        @template="emit('template')"
        @curl="emit('curl')"
        @guide="emit('guide')"
        @theme="themeStore.toggle"
        @share="emit('share')"
        @ai="openAiAssistant"
      />
    </main>

    <nav class="grid h-[72px] shrink-0 grid-cols-4 border-t border-border/70 bg-background px-4 py-2">
      <button
        class="mobile-workflow-tab"
        :class="activeTab === 'nodes' ? 'text-violet-600 dark:text-violet-300' : 'text-muted-foreground'"
        @click="openTab('nodes')"
      >
        <Grid3X3 class="h-5 w-5" />Nodes
      </button>
      <button
        class="mobile-workflow-tab"
        :class="activeTab === 'properties' ? 'text-violet-600 dark:text-violet-300' : 'text-muted-foreground'"
        @click="openProperties"
      >
        <SlidersHorizontal class="h-5 w-5" />Properties
      </button>
      <button
        class="mobile-workflow-tab"
        :class="activeTab === 'run' ? 'text-violet-600 dark:text-violet-300' : 'text-muted-foreground'"
        @click="openRun"
      >
        <Play class="h-5 w-5" />Run
      </button>
      <button
        class="mobile-workflow-tab"
        :class="activeTab === 'more' ? 'text-violet-600 dark:text-violet-300' : 'text-muted-foreground'"
        @click="openTab('more')"
      >
        <MoreHorizontal class="h-5 w-5" />More
      </button>
    </nav>

    <Teleport to="body">
      <Transition name="mobile-ai-backdrop">
        <button
          v-if="aiAssistantOpen"
          type="button"
          class="fixed inset-0 z-[100] bg-slate-950/45 backdrop-blur-[1px]"
          aria-label="Close AI Assistant"
          @click="aiAssistantOpen = false"
        />
      </Transition>
    </Teleport>
    <DebugPanel
      v-if="aiAssistantOpen"
      embedded
      ai-only
      mobile-ai-sheet
      :open-ai="aiAssistantOpen"
      @ai-close="aiAssistantOpen = false"
    />
  </section>
</template>

<style scoped>
.mobile-workflow-tab { @apply flex flex-col items-center justify-center gap-1 rounded-lg text-[11px] font-medium transition-colors; }
</style>
