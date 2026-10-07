import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";
import { describe, expect, it, vi } from "vitest";

import type { ChartPayload } from "@/types/dashboard";
import ChartView from "@/components/Dashboards/ChartView.vue";
import { hitlPortKey, type HitlPort } from "@/ports";

// DOMPurify needs a browser DOM; these tests check structure, not sanitizing.
vi.mock("@/lib/markdown", () => ({ renderChartMarkdown: (text: string): string => text }));

const hitl: HitlPort = { inbox: vi.fn(), inboxDecide: vi.fn(), openRun: vi.fn() };

// No Pinia and no router: the host passes the theme and provides the HITL port.
async function render(payload: ChartPayload): Promise<string> {
  const app = createSSRApp({ render: () => h(ChartView, { payload, dark: false }) });
  app.component("Apexchart", { render: () => null });
  app.provide(hitlPortKey, hitl);
  return renderToString(app);
}

describe("ChartView", () => {
  it("renders a numeric chart", async () => {
    const html = await render({ type: "numeric", value: 3.14159, decimals: 2, unit: "ms" });

    expect(html).toContain("3.14");
    expect(html).toContain("ms");
  });

  it("renders a table chart, and No data when it has no rows", async () => {
    const html = await render({ type: "table", columns: ["Lead"], rows: [["Acme"]] });

    expect(html).toContain("Lead");
    expect(html).toContain("Acme");
    expect(await render({ type: "table", columns: ["Lead"], rows: [] })).toContain("No data");
  });

  it("renders the HITL preview items without asking the port for the inbox", async () => {
    const html = await render({
      type: "hitl",
      pending_total: 1,
      items: [
        {
          id: "r-1",
          workflow_name: "Invoice approval",
          agent_label: "Reviewer",
          summary: "Approve the March invoice",
          text: "Total: 1,200 EUR",
        },
      ],
    });

    expect(html).toContain("Invoice approval");
    expect(html).toContain("1/1 pending");
    expect(hitl.inbox).not.toHaveBeenCalled();
  });
});
