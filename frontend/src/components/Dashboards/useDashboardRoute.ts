import { computed, ref, watch, type ComputedRef, type Ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  dashboardQuery,
  pageFromQuery,
  samePage,
  type DashboardPage,
} from "@/components/Dashboards/dashboardRoute";
import { useDashboardStore } from "@/stores/dashboard";

export interface DashboardRoute {
  page: ComputedRef<DashboardPage | null>;
  loadError: Ref<string | null>;
  loadDashboards: () => Promise<void>;
  openDashboard: (dashboardId: string, page?: DashboardPage | null) => Promise<void>;
  openRecord: (dashboardId: string, page: DashboardPage) => Promise<void>;
  clearRecord: () => Promise<void>;
}

/**
 * The dashboard and detail page the URL names. Opening a record pushes a history
 * entry, so Back returns to the list it was opened from.
 */
export function useDashboardRoute(): DashboardRoute {
  const route = useRoute();
  const router = useRouter();
  const dashboardStore = useDashboardStore();
  const loadError = ref<string | null>(null);
  const page = computed<DashboardPage | null>(() => pageFromQuery(route.query));

  async function show(
    dashboardId: string,
    nextPage: DashboardPage | null,
    navigate: "push" | "replace",
  ): Promise<void> {
    loadError.value = null;
    try {
      await dashboardStore.openDashboard(dashboardId);
    } catch {
      loadError.value = "Failed to load the dashboard";
      return;
    }
    const query = dashboardQuery(route.query, dashboardId, nextPage);
    if (!samePage(route.query, query)) {
      await (navigate === "push" ? router.push({ query }) : router.replace({ query }));
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
    if (target) await show(target, target === requested ? page.value : null, "replace");
  }

  // Back and Forward change the URL alone; follow it to the dashboard it names.
  watch(
    () => route.query.dashboard,
    (dashboardId) => {
      if (typeof dashboardId === "string" && dashboardId !== dashboardStore.activeDashboard?.id) {
        void dashboardStore.openDashboard(dashboardId).catch(() => {
          loadError.value = "Failed to load the dashboard";
        });
      }
    },
  );

  return {
    page,
    loadError,
    loadDashboards,
    openDashboard: (dashboardId, nextPage = null) => show(dashboardId, nextPage, "replace"),
    openRecord: (dashboardId, nextPage) => show(dashboardId, nextPage, "push"),
    clearRecord: async () => {
      const active = dashboardStore.activeDashboard;
      if (active) await show(active.id, null, "push");
    },
  };
}
