<script setup lang="ts">
import { computed, inject, onMounted, provide, ref, watch } from "vue";
import {
  Copy,
  ExternalLink,
  History,
  Loader2,
  Pencil,
  RefreshCw,
  Settings,
  Sparkles,
  Trash2,
} from "lucide-vue-next";

import type { ChartPayload, DashboardWidget } from "@/types/dashboard";
import ChartRenderer from "@/components/Dashboards/ChartRenderer.vue";
import WidgetActionsMenu from "@/components/Dashboards/WidgetActionsMenu.vue";
import {
  openHitlHistoryKey,
  setHitlHistoryTargetKey,
  type HitlHistoryTarget,
} from "@/components/Dashboards/hitlHistory";
import type { TableRecord, TableRowLink } from "@/components/Dashboards/chartTable";
import type { DashboardPage } from "@/components/Dashboards/dashboardRoute";
import { useWidgetData } from "@/components/Dashboards/useWidgetData";
import type { WidgetAction } from "@/components/Dashboards/widgetActions";

const props = defineProps<{
  widget: DashboardWidget;
  editMode: boolean;
  cloning: boolean;
  canWrite: boolean;
  record?: string | null;
}>();

const emit = defineEmits<{
  (e: "edit", workflowId: string): void;
  (e: "delete", widgetId: string): void;
  (e: "clone", widgetId: string): void;
  (e: "refine", widget: DashboardWidget): void;
  (e: "settings", widget: DashboardWidget): void;
  (e: "title-change", payload: { id: string; title: string }): void;
  (e: "open-record", dashboardId: string, page: DashboardPage): void;
}>();

const {
  payload,
  loading,
  error,
  markdownTaskSaving,
  loadData,
  toggleMarkdownTask,
  updateMarkdownTask,
} = useWidgetData(
  () => props.widget.id,
  () => props.record ?? null,
);

// Rows open the linked detail page only for viewers who can open it.
const rowLink = computed<TableRowLink | null>(() => {
  const { link_dashboard_id, link_record_field, link_accessible } = props.widget;
  if (!link_dashboard_id || !link_record_field || !link_accessible) return null;
  return { recordField: link_record_field, labelField: props.widget.link_label_field };
});

function onRowOpen(record: TableRecord): void {
  if (props.widget.link_dashboard_id) emit("open-record", props.widget.link_dashboard_id, record);
}

// Only surface http(s) links. The url can come from a dynamic expression over upstream
// data, so reject javascript:/data:/relative values to avoid an injected-link XSS.
const externalUrl = computed<string | null>(() => {
  const raw = payload.value?.url;
  if (!raw) return null;
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
});
const editingTitle = ref(false);
const titleDraft = ref(props.widget.title);

const actions: WidgetAction[] = [
  {
    key: "refine",
    icon: Sparkles,
    label: "Fine-tune with AI",
    run: () => emit("refine", props.widget),
  },
  { key: "refresh", icon: RefreshCw, label: "Refresh", run: () => void loadData(true) },
  {
    key: "edit",
    icon: Pencil,
    label: "Edit workflow",
    run: () => emit("edit", props.widget.workflow_id),
  },
  {
    key: "clone",
    icon: Copy,
    label: "Clone widget",
    disabled: () => props.cloning,
    run: () => emit("clone", props.widget.id),
  },
  {
    key: "settings",
    icon: Settings,
    label: "Settings",
    run: () => emit("settings", props.widget),
  },
  {
    key: "delete",
    icon: Trash2,
    label: "Delete widget",
    danger: true,
    run: () => emit("delete", props.widget.id),
  },
];

const openHitlHistory = inject(openHitlHistoryKey, null);
const hitlTarget = ref<HitlHistoryTarget | null>(null);
provide(setHitlHistoryTargetKey, (target) => {
  hitlTarget.value = target;
});

function openWidgetHistory(): void {
  const target = hitlTarget.value;
  if (!target || !openHitlHistory) return;
  openHitlHistory(target.workflowId, target.executionId);
}

// A read-only share keeps only Refresh; every other action changes the widget.
// History stays first so it shares the same gap as the widget icons.
const visibleActions = computed<WidgetAction[]>(() => {
  const base = props.canWrite ? actions : actions.filter((action) => action.key === "refresh");
  if (!hitlTarget.value) return base;
  return [
    {
      key: "history",
      icon: History,
      label: "Open history",
      run: openWidgetHistory,
    },
    ...base,
  ];
});

// Read-only viewers see task lists as plain checkboxes they cannot tick.
const displayPayload = computed<ChartPayload | null>(() =>
  props.canWrite || !payload.value ? payload.value : { ...payload.value, text_interactive: false },
);

function commitTitle(): void {
  editingTitle.value = false;
  const next = titleDraft.value.trim();
  if (next && next !== props.widget.title) {
    emit("title-change", { id: props.widget.id, title: next });
  } else {
    titleDraft.value = props.widget.title;
  }
}

function onBodyDoubleClick(): void {
  if (props.canWrite) emit("edit", props.widget.workflow_id);
}

// Reload when the widget's workflow changes (AI refine, settings) — updated_at bumps.
watch(
  () => props.widget.updated_at,
  () => {
    titleDraft.value = props.widget.title;
    void loadData(true);
  },
);

onMounted(() => {
  void loadData();
});
</script>

<template>
  <div class="relative flex h-full flex-col rounded-lg border bg-card shadow-sm">
    <div class="flex items-center justify-between gap-2 border-b px-3 py-2">
      <input
        v-if="editingTitle"
        v-model="titleDraft"
        class="w-full min-w-0 bg-transparent text-sm font-medium outline-none"
        autofocus
        @blur="commitTitle"
        @keyup.enter="commitTitle"
      >
      <button
        v-else-if="canWrite"
        class="min-w-0 flex-1 truncate text-left text-sm font-medium hover:text-primary"
        :title="widget.title"
        @click="editingTitle = true"
      >
        {{ widget.title }}
      </button>
      <span
        v-else
        class="min-w-0 flex-1 truncate text-sm font-medium"
        :title="widget.title"
      >
        {{ widget.title }}
      </span>

      <a
        v-if="externalUrl"
        :href="externalUrl"
        target="_blank"
        rel="noopener noreferrer"
        class="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        title="Open link"
      >
        <ExternalLink class="h-3.5 w-3.5" />
      </a>

      <WidgetActionsMenu :actions="visibleActions" />
    </div>

    <div
      class="flex-1 overflow-hidden p-3"
      @dblclick="onBodyDoubleClick"
    >
      <div
        v-if="loading"
        class="flex h-full min-h-[120px] items-center justify-center text-muted-foreground"
      >
        <Loader2 class="h-5 w-5 animate-spin" />
      </div>
      <div
        v-else-if="error"
        class="flex h-full min-h-[120px] items-center justify-center px-2 text-center text-xs text-destructive"
      >
        {{ error }}
      </div>
      <ChartRenderer
        v-else
        :payload="displayPayload"
        :markdown-task-saving="markdownTaskSaving"
        :row-link="rowLink"
        @row-open="onRowOpen"
        @markdown-task-toggle="toggleMarkdownTask"
        @markdown-task-update="updateMarkdownTask"
      />
    </div>
  </div>
</template>
