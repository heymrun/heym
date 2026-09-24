import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type {
  DashboardData,
  DashboardSummary,
  DashboardWidget,
  WidgetLayout,
} from "@/types/dashboard";
import { dashboardApi } from "@/services/api";

const LAST_DASHBOARD_KEY = "heym-last-dashboard";

function readLastDashboardId(): string | null {
  try {
    return window.localStorage.getItem(LAST_DASHBOARD_KEY);
  } catch {
    return null;
  }
}

function writeLastDashboardId(dashboardId: string): void {
  try {
    window.localStorage.setItem(LAST_DASHBOARD_KEY, dashboardId);
  } catch {
    // Storage can be unavailable (private mode); the URL still carries the choice.
  }
}

export const useDashboardStore = defineStore("dashboard", () => {
  const dashboards = ref<DashboardSummary[]>([]);
  const activeDashboard = ref<DashboardData | null>(null);
  const listLoading = ref(false);
  const dashboardLoading = ref(false);

  // Viewers of a read-only share can refresh but not change anything; only the owner
  // renames, shares or deletes a dashboard.
  const canWrite = computed<boolean>(
    () => activeDashboard.value !== null && activeDashboard.value.permission !== "read",
  );
  const isOwner = computed<boolean>(() => activeDashboard.value?.permission === "owner");
  const ownedCount = computed<number>(
    () => dashboards.value.filter((dashboard) => dashboard.permission === "owner").length,
  );
  const widgets = computed<DashboardWidget[]>(() => activeDashboard.value?.widgets ?? []);

  async function fetchDashboards(): Promise<void> {
    listLoading.value = true;
    try {
      dashboards.value = await dashboardApi.list();
    } finally {
      listLoading.value = false;
    }
  }

  /** The dashboard to open when the URL names none: the last one used, else the first. */
  function defaultDashboardId(requestedId: string | null): string | null {
    const known = (id: string | null): string | null =>
      id && dashboards.value.some((dashboard) => dashboard.id === id) ? id : null;
    return known(requestedId) ?? known(readLastDashboardId()) ?? dashboards.value[0]?.id ?? null;
  }

  async function openDashboard(dashboardId: string): Promise<void> {
    dashboardLoading.value = true;
    try {
      activeDashboard.value = await dashboardApi.get(dashboardId);
      writeLastDashboardId(dashboardId);
    } finally {
      dashboardLoading.value = false;
    }
  }

  async function reloadActiveDashboard(): Promise<void> {
    if (activeDashboard.value) {
      activeDashboard.value = await dashboardApi.get(activeDashboard.value.id);
    }
  }

  async function createDashboard(name: string): Promise<DashboardSummary> {
    const created = await dashboardApi.create(name);
    dashboards.value = [
      ...dashboards.value.filter((dashboard) => dashboard.permission === "owner"),
      created,
      ...dashboards.value.filter((dashboard) => dashboard.permission !== "owner"),
    ];
    return created;
  }

  async function renameDashboard(dashboardId: string, name: string): Promise<void> {
    const renamed = await dashboardApi.rename(dashboardId, name);
    dashboards.value = dashboards.value.map((dashboard) =>
      dashboard.id === dashboardId ? { ...dashboard, name: renamed.name } : dashboard,
    );
    if (activeDashboard.value?.id === dashboardId) {
      activeDashboard.value = { ...activeDashboard.value, name: renamed.name };
    }
  }

  async function deleteDashboard(dashboardId: string): Promise<void> {
    await dashboardApi.remove(dashboardId);
    dashboards.value = dashboards.value.filter((dashboard) => dashboard.id !== dashboardId);
    if (activeDashboard.value?.id === dashboardId) {
      activeDashboard.value = null;
    }
  }

  function setWidgets(next: DashboardWidget[]): void {
    if (activeDashboard.value) {
      activeDashboard.value = { ...activeDashboard.value, widgets: next };
    }
  }

  function addWidget(widget: DashboardWidget): void {
    setWidgets([...widgets.value, widget]);
  }

  function replaceWidget(updated: DashboardWidget): void {
    setWidgets(widgets.value.map((widget) => (widget.id === updated.id ? updated : widget)));
  }

  function removeWidget(widgetId: string): void {
    setWidgets(widgets.value.filter((widget) => widget.id !== widgetId));
  }

  function applyLayouts(layoutById: Record<string, WidgetLayout>): void {
    setWidgets(
      widgets.value.map((widget) =>
        layoutById[widget.id] ? { ...widget, layout: layoutById[widget.id] } : widget,
      ),
    );
  }

  return {
    dashboards,
    activeDashboard,
    listLoading,
    dashboardLoading,
    canWrite,
    isOwner,
    ownedCount,
    widgets,
    fetchDashboards,
    defaultDashboardId,
    openDashboard,
    reloadActiveDashboard,
    createDashboard,
    renameDashboard,
    deleteDashboard,
    addWidget,
    replaceWidget,
    removeWidget,
    applyLayouts,
  };
});
