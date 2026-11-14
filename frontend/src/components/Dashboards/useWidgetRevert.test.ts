import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import type { DashboardWidget } from "@/types/dashboard";

const showToast = vi.fn();

vi.mock("@/services/api", () => ({
  dashboardApi: { revertWidget: vi.fn() },
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ showToast }),
}));

import { useWidgetRevert } from "@/components/Dashboards/useWidgetRevert";
import { dashboardApi } from "@/services/api";
import { useDashboardStore } from "@/stores/dashboard";
import { useWidgetRevertsStore } from "@/stores/widgetReverts";

function widget(id: string, extra: Partial<DashboardWidget> = {}): DashboardWidget {
  return {
    id,
    workflow_id: `wf-${id}`,
    title: `Widget ${id}`,
    description: null,
    chart_type: "bar",
    layout: { x: 0, y: 0, w: 4, h: 4 },
    cache_ttl_seconds: 300,
    position: 0,
    link_dashboard_id: null,
    link_record_field: null,
    link_label_field: null,
    link_accessible: false,
    updated_at: "2026-11-14T00:00:00Z",
    ...extra,
  };
}

describe("useWidgetRevert", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    const dashboards = useDashboardStore();
    dashboards.activeDashboard = {
      id: "d1",
      name: "Support",
      permission: "owner",
      widgets: [widget("w1"), widget("w2")],
    } as unknown as typeof dashboards.activeDashboard;
  });

  it("lists only widgets on the dashboard that have an offer", () => {
    const reverts = useWidgetRevertsStore();
    reverts.offer("w2", 4);
    reverts.offer("gone", 1);
    const { revertibleIds } = useWidgetRevert();
    expect(revertibleIds.value).toEqual(["w2"]);
  });

  it("offers a fine-tune's snapshot and drops the offer when the answer has none", () => {
    const reverts = useWidgetRevertsStore();
    const { offerFromRefine } = useWidgetRevert();
    offerFromRefine(widget("w1", { previous_version_number: 6 }));
    expect(reverts.offers).toEqual({ w1: 6 });
    offerFromRefine(widget("w1"));
    expect(reverts.offers).toEqual({});
  });

  it("restores the snapshot, swaps the widget in and ends the offer", async () => {
    const reverts = useWidgetRevertsStore();
    reverts.offer("w1", 7);
    const restored = widget("w1", { chart_type: "line", updated_at: "2026-11-14T01:00:00Z" });
    vi.mocked(dashboardApi.revertWidget).mockResolvedValue(restored);
    const { revert } = useWidgetRevert();

    await revert("w1");

    expect(dashboardApi.revertWidget).toHaveBeenCalledWith("w1", 7);
    expect(useDashboardStore().widgets[0]).toEqual(restored);
    expect(reverts.offers).toEqual({});
    expect(showToast).toHaveBeenCalledWith("Reverted Widget w1.", "success");
  });

  it("shows why Heym refused and ends the offer", async () => {
    const reverts = useWidgetRevertsStore();
    reverts.offer("w1", 7);
    vi.mocked(dashboardApi.revertWidget).mockRejectedValue({
      isAxiosError: true,
      response: {
        data: { detail: "This widget changed after that edit, so it can no longer be reverted" },
      },
    });
    const { revert } = useWidgetRevert();

    await revert("w1");

    expect(showToast).toHaveBeenCalledWith(
      "This widget changed after that edit, so it can no longer be reverted",
      "error",
    );
    expect(reverts.offers).toEqual({});
  });

  it("does nothing for a widget without an offer", async () => {
    const { revert } = useWidgetRevert();
    await revert("w1");
    expect(dashboardApi.revertWidget).not.toHaveBeenCalled();
  });
});
