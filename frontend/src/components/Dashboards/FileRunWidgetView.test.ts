import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";
import { describe, expect, it } from "vitest";

import type { FileRunPayload } from "@/types/dashboard";
import type { QuickDrawerRunState } from "@/types/quickDrawer";
import FileRunWidgetView from "@/components/Dashboards/FileRunWidgetView.vue";
import { fileRunState } from "@/components/Layout/quickWorkflowRun";

const payload: FileRunPayload = {
  type: "fileRun",
  file_label: "invoice",
  max_size_mb: 5,
  allowed_types: ["application/pdf"],
};

const idle: QuickDrawerRunState = {
  status: "idle",
  executionId: null,
  outputs: null,
  executionTimeMs: null,
  executionHistoryId: null,
  errorMessage: null,
  nodeResults: [],
  startedAt: null,
};

// No Pinia and no API: the host passes the file, the run and its result.
async function render(runState: QuickDrawerRunState, file: File | null = null): Promise<string> {
  const app = createSSRApp({ render: () => h(FileRunWidgetView, { payload, file, runState }) });
  return renderToString(app);
}

describe("FileRunWidgetView", () => {
  it("asks for the file its workflow takes", async () => {
    const html = await render(idle);

    expect(html).toContain("invoice");
    expect(html).toContain("application/pdf, up to 5 MB");
    expect(html).not.toContain("Progress &amp; Result");
  });

  it("shows the last drop's result", async () => {
    const result = fileRunState(
      {
        run_id: "run-1",
        status: "error",
        file: { id: "f", name: "march.pdf", mime: "application/pdf", size: 4, download_url: "" },
        output: { error: "No total on the invoice" },
      },
      1_000,
      2_500,
    );

    const html = await render(result, new File(["%PDF"], "march.pdf"));

    expect(html).toContain("march.pdf");
    expect(html).toContain("No total on the invoice");
    expect(html).toContain("1.50 s");
  });
});
