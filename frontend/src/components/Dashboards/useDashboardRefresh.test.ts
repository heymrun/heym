import { describe, expect, it } from "vitest";

import { useDashboardRefresh } from "@/components/Dashboards/useDashboardRefresh";

describe("useDashboardRefresh", () => {
  it("forces only the remount of the toolbar Refresh", async () => {
    const { reloadKey, forceRefresh, refreshWidgets } = useDashboardRefresh();

    const forced = refreshWidgets(true);
    // The widgets mount in this tick and see the flag.
    expect(forceRefresh.value).toBe(true);
    expect(reloadKey.value).toBe(1);
    await forced;
    // A later remount, such as a record or dashboard change, uses the cache again.
    expect(forceRefresh.value).toBe(false);

    await refreshWidgets(false);
    expect(forceRefresh.value).toBe(false);
    expect(reloadKey.value).toBe(2);
  });
});
