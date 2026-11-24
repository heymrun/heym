import { nextTick, ref, type Ref } from "vue";

export interface DashboardRefresh {
  /** Part of the grid's key: bumping it remounts every widget. */
  reloadKey: Ref<number>;
  /** True while the grid remounts for the toolbar Refresh, so its widgets skip the cache. */
  forceRefresh: Ref<boolean>;
  /** The toolbar Refresh passes `true`; auto-refresh passes `false` and keeps a fresh cache. */
  refreshWidgets: (force: boolean) => Promise<void>;
}

/**
 * Remounting the grid reloads every widget. The docs promise that the toolbar Refresh
 * bypasses the cache, as a widget's own Refresh does; auto-refresh fires on a timer and
 * keeps serving a fresh cache, so it does not.
 */
export function useDashboardRefresh(): DashboardRefresh {
  const reloadKey = ref(0);
  const forceRefresh = ref(false);

  async function refreshWidgets(force: boolean): Promise<void> {
    forceRefresh.value = force;
    reloadKey.value += 1;
    // The widgets mount in this tick; later remounts (a record change) use the cache.
    await nextTick();
    forceRefresh.value = false;
  }

  return { reloadKey, forceRefresh, refreshWidgets };
}
