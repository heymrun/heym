<script setup lang="ts">
import { onMounted, ref } from "vue";
import axios from "axios";
import { useRoute, useRouter } from "vue-router";
import { Loader2, Plus, Sparkles } from "lucide-vue-next";

import AddWidgetDialog from "@/components/Dashboards/AddWidgetDialog.vue";
import AiWidgetDialog from "@/components/Dashboards/AiWidgetDialog.vue";
import DashboardCreateDialog from "@/components/Dashboards/DashboardCreateDialog.vue";
import DashboardGrid from "@/components/Dashboards/DashboardGrid.vue";
import DashboardHeader from "@/components/Dashboards/DashboardHeader.vue";
import DashboardSettingsDialog from "@/components/Dashboards/DashboardSettingsDialog.vue";
import WidgetSettingsDialog from "@/components/Dashboards/WidgetSettingsDialog.vue";
import Button from "@/components/ui/Button.vue";
import { tidyLayouts } from "@/lib/dashboardTidy";
import { dashboardApi } from "@/services/api";
import { useDashboardStore } from "@/stores/dashboard";
import type {
  DashboardWidget,
  WidgetCreateRequest,
  WidgetLayout,
  WidgetUpdateRequest,
} from "@/types/dashboard";
import { playSuccessSound } from "@/utils/audio";

const route = useRoute();
const router = useRouter();
const dashboardStore = useDashboardStore();

const editMode = ref(false);
const showAdd = ref(false);
const showAi = ref(false);
const showCreate = ref(false);
const showSettings = ref(false);
const refineWidget = ref<DashboardWidget | null>(null);
const settingsWidget = ref<DashboardWidget | null>(null);
const reloadKey = ref(0);
const cloningWidgetId = ref<string | null>(null);
const cloneError = ref<string | null>(null);
const loadError = ref<string | null>(null);

async function openDashboardWithUrl(dashboardId: string): Promise<void> {
  editMode.value = false;
  loadError.value = null;
  try {
    await dashboardStore.openDashboard(dashboardId);
  } catch {
    loadError.value = "Failed to load the dashboard";
    return;
  }
  if (route.query.dashboard !== dashboardId) {
    await router.replace({ query: { ...route.query, tab: "dashboard", dashboard: dashboardId } });
  }
}

async function loadDashboards(): Promise<void> {
  try {
    await dashboardStore.fetchDashboards();
  } catch {
    loadError.value = "Failed to load dashboards";
    return;
  }
  const requested = typeof route.query.dashboard === "string" ? route.query.dashboard : null;
  const target = dashboardStore.defaultDashboardId(requested);
  if (target) await openDashboardWithUrl(target);
}

function openEditor(workflowId: string): void {
  void router.push({ name: "editor", params: { id: workflowId } });
}

async function handleCreate(body: WidgetCreateRequest): Promise<void> {
  showAdd.value = false;
  const dashboard = dashboardStore.activeDashboard;
  if (!dashboard) return;
  const widget = await dashboardApi.createWidget(dashboard.id, body);
  dashboardStore.addWidget(widget);
  openEditor(widget.workflow_id);
}

async function handleGenerate(payload: {
  prompt: string;
  credentialId: string;
  model: string;
}): Promise<void> {
  const dashboard = dashboardStore.activeDashboard;
  if (!dashboard) return;
  try {
    const widget = await dashboardApi.aiGenerateWidget(
      dashboard.id,
      payload.prompt,
      payload.credentialId,
      payload.model,
    );
    dashboardStore.addWidget(widget);
    showAi.value = false;
    playSuccessSound();
  } catch {
    // keep the dialog open on failure so the user can retry
  }
}

async function handleDelete(widgetId: string): Promise<void> {
  await dashboardApi.deleteWidget(widgetId);
  dashboardStore.removeWidget(widgetId);
}

async function handleClone(widgetId: string): Promise<void> {
  if (cloningWidgetId.value) return;
  cloningWidgetId.value = widgetId;
  cloneError.value = null;
  try {
    await dashboardApi.cloneWidget(widgetId);
    await dashboardStore.reloadActiveDashboard();
    playSuccessSound();
  } catch (error: unknown) {
    if (axios.isAxiosError(error) && typeof error.response?.data?.detail === "string") {
      cloneError.value = error.response.data.detail;
    } else {
      cloneError.value = error instanceof Error ? error.message : "Failed to clone widget";
    }
  } finally {
    cloningWidgetId.value = null;
  }
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
    dashboardStore.replaceWidget(updated);
    refineWidget.value = null;
    playSuccessSound();
  } catch {
    // keep the dialog open on failure so the user can retry
  }
}

async function handleSettingsSave(payload: WidgetUpdateRequest): Promise<void> {
  const target = settingsWidget.value;
  if (!target) return;
  dashboardStore.replaceWidget(await dashboardApi.updateWidget(target.id, payload));
  settingsWidget.value = null;
}

async function handleTitleChange(payload: { id: string; title: string }): Promise<void> {
  dashboardStore.replaceWidget(
    await dashboardApi.updateWidget(payload.id, { title: payload.title }),
  );
}

async function handleLayoutChange(payload: { id: string; layout: WidgetLayout }): Promise<void> {
  await dashboardApi.updateWidget(payload.id, { layout: payload.layout });
  dashboardStore.applyLayouts({ [payload.id]: payload.layout });
}

async function tidyUp(): Promise<void> {
  if (dashboardStore.widgets.length === 0) return;
  const updates = tidyLayouts(dashboardStore.widgets);
  // Replacing the layouts triggers DashboardGrid's deep watch, which repositions
  // the items reactively (no remount, so widgets keep their already-loaded data).
  dashboardStore.applyLayouts(Object.fromEntries(updates.map((u) => [u.id, u.layout])));
  await Promise.all(updates.map((u) => dashboardApi.updateWidget(u.id, { layout: u.layout })));
}

async function onDashboardDeleted(): Promise<void> {
  const next = dashboardStore.defaultDashboardId(null);
  if (next) await openDashboardWithUrl(next);
}

onMounted(() => {
  void loadDashboards();
});
</script>

<template>
  <div class="flex h-full flex-col">
    <DashboardHeader
      :edit-mode="editMode"
      :has-widgets="dashboardStore.widgets.length > 0"
      @select="openDashboardWithUrl"
      @create="showCreate = true"
      @settings="showSettings = true"
      @refresh="reloadKey += 1"
      @tidy="tidyUp"
      @toggle-edit="editMode = !editMode"
      @ai="showAi = true"
      @add="showAdd = true"
    />

    <div class="flex-1 overflow-auto p-4">
      <div
        v-if="cloneError"
        class="mb-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        role="alert"
      >
        {{ cloneError }}
      </div>
      <div
        v-if="loadError"
        class="flex h-full items-center justify-center text-sm text-destructive"
        role="alert"
      >
        {{ loadError }}
      </div>
      <div
        v-else-if="!dashboardStore.activeDashboard || dashboardStore.dashboardLoading"
        class="flex h-full items-center justify-center text-muted-foreground"
      >
        <Loader2 class="h-6 w-6 animate-spin" />
      </div>
      <div
        v-else-if="dashboardStore.widgets.length === 0"
        class="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground"
      >
        <p>No widgets yet.</p>
        <div
          v-if="dashboardStore.canWrite"
          class="flex gap-2"
        >
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
        :key="`${dashboardStore.activeDashboard.id}-${reloadKey}`"
        :widgets="dashboardStore.widgets"
        :edit-mode="editMode"
        :cloning-widget-id="cloningWidgetId"
        :can-write="dashboardStore.canWrite"
        @edit="openEditor"
        @delete="handleDelete"
        @clone="handleClone"
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
    <DashboardCreateDialog
      :open="showCreate"
      @close="showCreate = false"
      @created="openDashboardWithUrl"
    />
    <DashboardSettingsDialog
      :open="showSettings"
      @close="showSettings = false"
      @deleted="onDashboardDeleted"
    />
  </div>
</template>
