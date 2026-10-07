import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWidgetData } from "@/components/Dashboards/useWidgetData";
import { dashboardApi } from "@/services/api";

vi.mock("@/services/api", () => ({
  dashboardApi: {
    getWidgetData: vi.fn(),
    toggleMarkdownTask: vi.fn(),
    updateMarkdownTask: vi.fn(),
  },
}));

const api = vi.mocked(dashboardApi);

function response(payload: unknown, error: string | null = null): never {
  return { widget_id: "w-1", payload, cached: false, computed_at: null, error } as never;
}

describe("useWidgetData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the chart and the widget's error", async () => {
    api.getWidgetData.mockResolvedValue(response({ type: "numeric", value: 3 }, "Stale"));
    const data = useWidgetData(() => "w-1");

    await data.loadData(true);

    expect(api.getWidgetData).toHaveBeenCalledWith("w-1", true);
    expect(data.payload.value).toEqual({ type: "numeric", value: 3 });
    expect(data.error.value).toBe("Stale");
    expect(data.loading.value).toBe(false);
  });

  it("puts a checklist back when the toggle fails", async () => {
    const checklist = { type: "text", text: "- [ ] Ship", text_interactive: true } as const;
    api.getWidgetData.mockResolvedValue(response(checklist));
    api.toggleMarkdownTask.mockRejectedValue(new Error("Offline"));
    const data = useWidgetData(() => "w-1");
    await data.loadData();

    await data.toggleMarkdownTask(0);

    expect(data.payload.value).toEqual(checklist);
    expect(data.error.value).toBe("Offline");
    expect(data.markdownTaskSaving.value).toBe(false);
  });

  it("leaves charts that are not interactive checklists alone", async () => {
    api.getWidgetData.mockResolvedValue(response({ type: "text", text: "Hello" }));
    const data = useWidgetData(() => "w-1");
    await data.loadData();

    await data.updateMarkdownTask({ lineIndex: 0, text: "Bye" });

    expect(api.updateMarkdownTask).not.toHaveBeenCalled();
  });
});
