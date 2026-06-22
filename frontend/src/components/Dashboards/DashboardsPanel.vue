<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { LayoutGrid, Loader2, Pencil, Plus, RefreshCw, Sparkles } from "lucide-vue-next";

import AddWidgetDialog from "@/components/Dashboards/AddWidgetDialog.vue";
import AiWidgetDialog from "@/components/Dashboards/AiWidgetDialog.vue";
import DashboardAutoRefreshControl from "@/components/Dashboards/DashboardAutoRefreshControl.vue";
import DashboardGrid from "@/components/Dashboards/DashboardGrid.vue";
import WidgetSettingsDialog from "@/components/Dashboards/WidgetSettingsDialog.vue";
import Button from "@/components/ui/Button.vue";
import { dashboardApi } from "@/services/api";
import type {
  DashboardWidget,
  WidgetCreateRequest,
  WidgetLayout,
  WidgetUpdateRequest,
} from "@/types/dashboard";
import { playSuccessSound } from "@/utils/audio";

const router = useRouter();

const widgets = ref<DashboardWidget[]>([]);
const loading = ref(true);
const editMode = ref(false);
const showAdd = ref(false);
const showAi = ref(false);
const refineWidget = ref<DashboardWidget | null>(null);
const settingsWidget = ref<DashboardWidget | null>(null);
const reloadKey = ref(0);

async function loadDashboard(): Promise<void> {
  loading.value = true;
  try {
    const data = await dashboardApi.getDashboard();
    widgets.value = data.widgets;
  } finally {
    loading.value = false;
  }
}

function openEditor(workflowId: string): void {
  void router.push({ name: "editor", params: { id: workflowId } });
}

async function handleCreate(body: WidgetCreateRequest): Promise<void> {
  showAdd.value = false;
  const widget = await dashboardApi.createWidget(body);
  widgets.value = [...widgets.value, widget];
  openEditor(widget.workflow_id);
}

async function handleGenerate(payload: {
  prompt: string;
  credentialId: string;
  model: string;
}): Promise<void> {
  try {
    const widget = await dashboardApi.aiGenerateWidget(
      payload.prompt,
      payload.credentialId,
      payload.model,
    );
    widgets.value = [...widgets.value, widget];
    showAi.value = false;
    playSuccessSound();
  } catch {
    // keep the dialog open on failure so the user can retry
  }
}

async function handleDelete(widgetId: string): Promise<void> {
  await dashboardApi.deleteWidget(widgetId);
  widgets.value = widgets.value.filter((w) => w.id !== widgetId);
}

async function handleRefine(payload: {
  prompt: string;
  credentialId: string;
  model: string;
}): Promise<void> {
  const target = refineWidget.value;
  if (!target) return;
  try {
    const updated = await dashboardApi.aiRefineWidget(
      target.id,
      payload.prompt,
      payload.credentialId,
      payload.model,
    );
    widgets.value = widgets.value.map((w) => (w.id === updated.id ? updated : w));
    refineWidget.value = null;
    playSuccessSound();
  } catch {
    // keep the dialog open on failure so the user can retry
  }
}

async function handleSettingsSave(payload: WidgetUpdateRequest): Promise<void> {
  const target = settingsWidget.value;
  if (!target) return;
  const updated = await dashboardApi.updateWidget(target.id, payload);
  widgets.value = widgets.value.map((w) => (w.id === updated.id ? updated : w));
  settingsWidget.value = null;
}

async function handleTitleChange(payload: { id: string; title: string }): Promise<void> {
  const updated = await dashboardApi.updateWidget(payload.id, { title: payload.title });
  widgets.value = widgets.value.map((w) => (w.id === updated.id ? updated : w));
}

async function handleLayoutChange(payload: { id: string; layout: WidgetLayout }): Promise<void> {
  await dashboardApi.updateWidget(payload.id, { layout: payload.layout });
  widgets.value = widgets.value.map((w) =>
    w.id === payload.id ? { ...w, layout: payload.layout } : w,
  );
}

function refreshAll(): void {
  reloadKey.value += 1;
}

// Randomly split N widgets into rows of 2 or 3 (with an occasional trailing 1),
// producing variations like 2-2-2, 2-3-3, or 3-3-1 on each press.
function buildRowSizes(count: number): number[] {
  const rows: number[] = [];
  let remaining = count;
  while (remaining > 0) {
    if (remaining <= 2) {
      rows.push(remaining);
      break;
    }
    const size = Math.random() < 0.5 ? 2 : 3;
    rows.push(size);
    remaining -= size;
  }
  return rows;
}

const TIDY_ROW_HEIGHT = 5; // grid row units per widget

async function tidyUp(): Promise<void> {
  if (widgets.value.length === 0) return;
  const ordered = [...widgets.value].sort((a, b) => a.position - b.position);
  const rowSizes = buildRowSizes(ordered.length);

  const updates: { id: string; layout: WidgetLayout }[] = [];
  let index = 0;
  let y = 0;
  for (const size of rowSizes) {
    const w = Math.floor(12 / size);
    for (let col = 0; col < size; col++) {
      const widget = ordered[index];
      if (widget) {
        updates.push({ id: widget.id, layout: { x: col * w, y, w, h: TIDY_ROW_HEIGHT } });
      }
      index += 1;
    }
    y += TIDY_ROW_HEIGHT;
  }

  const layoutById = Object.fromEntries(updates.map((u) => [u.id, u.layout]));
  // Replacing the layouts triggers DashboardGrid's deep watch, which repositions
  // the items reactively (no remount, so widgets keep their already-loaded data).
  widgets.value = widgets.value.map((w) =>
    layoutById[w.id] ? { ...w, layout: layoutById[w.id] } : w,
  );
  await Promise.all(updates.map((u) => dashboardApi.updateWidget(u.id, { layout: u.layout })));
}

onMounted(() => {
  void loadDashboard();
});
</script>

<template>
  <div class="flex h-full flex-col">
    <div
      data-testid="dashboard-header"
      class="flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <h1 class="shrink-0 text-lg font-semibold">
          Dashboard
        </h1>
        <DashboardAutoRefreshControl
          class="ml-auto sm:ml-0"
          @refresh="refreshAll"
        />
      </div>
      <div class="flex flex-wrap items-center gap-1 sm:gap-2">
        <Button
          variant="ghost"
          size="sm"
          class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
          title="Refresh dashboard"
          aria-label="Refresh dashboard"
          @click="refreshAll"
        >
          <RefreshCw class="h-4 w-4 sm:mr-1" />
          <span class="hidden sm:inline">Refresh</span>
        </Button>
        <Button
          v-if="widgets.length > 0"
          variant="ghost"
          size="sm"
          class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
          title="Rearrange widgets into a random tidy grid"
          aria-label="Tidy up dashboard"
          @click="tidyUp"
        >
          <LayoutGrid class="h-4 w-4 sm:mr-1" />
          <span class="hidden sm:inline">Tidy up</span>
        </Button>
        <Button
          :variant="editMode ? 'default' : 'ghost'"
          size="sm"
          class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
          :title="editMode ? 'Finish editing dashboard' : 'Edit dashboard'"
          :aria-label="editMode ? 'Finish editing dashboard' : 'Edit dashboard'"
          @click="editMode = !editMode"
        >
          <Pencil class="h-4 w-4 sm:mr-1" />
          <span class="hidden sm:inline">{{ editMode ? "Done" : "Edit" }}</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
          title="Generate widget with AI"
          aria-label="Generate widget with AI"
          @click="showAi = true"
        >
          <Sparkles class="h-4 w-4 sm:mr-1" />
          <span class="hidden sm:inline">AI</span>
        </Button>
        <Button
          size="sm"
          class="h-11 min-w-[4.5rem] flex-1 justify-center px-2 sm:h-auto sm:min-w-0 sm:flex-none sm:px-3"
          title="Add widget"
          aria-label="Add widget"
          @click="showAdd = true"
        >
          <Plus class="mr-1 h-4 w-4" />
          <span class="sm:hidden">Add</span>
          <span class="hidden sm:inline">Add widget</span>
        </Button>
      </div>
    </div>

    <div class="flex-1 overflow-auto p-4">
      <div
        v-if="loading"
        class="flex h-full items-center justify-center text-muted-foreground"
      >
        <Loader2 class="h-6 w-6 animate-spin" />
      </div>
      <div
        v-else-if="widgets.length === 0"
        class="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground"
      >
        <p>No widgets yet.</p>
        <div class="flex gap-2">
          <Button
            size="sm"
            @click="showAdd = true"
          >
            <Plus class="mr-1 h-4 w-4" /> Add widget
          </Button>
          <Button
            variant="ghost"
            size="sm"
            @click="showAi = true"
          >
            <Sparkles class="mr-1 h-4 w-4" /> Generate with AI
          </Button>
        </div>
      </div>
      <DashboardGrid
        v-else
        :key="reloadKey"
        :widgets="widgets"
        :edit-mode="editMode"
        @edit="openEditor"
        @delete="handleDelete"
        @refine="refineWidget = $event"
        @settings="settingsWidget = $event"
        @title-change="handleTitleChange"
        @layout-change="handleLayoutChange"
      />
    </div>

    <AddWidgetDialog
      v-if="showAdd"
      @close="showAdd = false"
      @create="handleCreate"
    />
    <AiWidgetDialog
      v-if="showAi"
      @close="showAi = false"
      @generate="handleGenerate"
    />
    <AiWidgetDialog
      v-if="refineWidget"
      heading="Fine-tune widget with AI"
      placeholder="e.g. Make it a horizontal bar chart and only show the top 5"
      submit-label="Apply"
      @close="refineWidget = null"
      @generate="handleRefine"
    />
    <WidgetSettingsDialog
      v-if="settingsWidget"
      :widget="settingsWidget"
      @close="settingsWidget = null"
      @save="handleSettingsSave"
    />
  </div>
</template>
