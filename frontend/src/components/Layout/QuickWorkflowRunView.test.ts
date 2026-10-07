import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";
import { describe, expect, it } from "vitest";

import type { QuickDrawerRunState, QuickDrawerWorkflowViewModel } from "@/types/quickDrawer";
import QuickWorkflowRunView from "@/components/Layout/QuickWorkflowRunView.vue";

const workflow: QuickDrawerWorkflowViewModel = {
  id: "wf-1",
  name: "Daily report",
  description: null,
  inputFields: [{ key: "topic", defaultValue: "pricing" }],
  outputNode: null,
  createdAt: "2026-01-01T00:00:00Z",
  updatedAt: "2026-01-01T00:00:00Z",
  pinned: true,
  searchableText: "daily report",
};

const failed: QuickDrawerRunState = {
  status: "error",
  executionId: "exec-1",
  outputs: null,
  executionTimeMs: 1500,
  executionHistoryId: "hist-1",
  errorMessage: "The model credential is missing.",
  nodeResults: [],
  startedAt: 1,
};

// No Pinia: the workflow, the input values and the run arrive as props.
async function render(runState: QuickDrawerRunState): Promise<string> {
  const app = createSSRApp({
    render: () =>
      h(QuickWorkflowRunView, { workflow, inputValues: { topic: "churn" }, runState }),
  });
  return renderToString(app);
}

describe("QuickWorkflowRunView", () => {
  it("renders the workflow, its inputs and a failed run from props", async () => {
    const html = await render(failed);

    expect(html).toContain("Daily report");
    expect(html).toContain("churn");
    expect(html).toContain("Unpin Daily report");
    expect(html).toContain("The model credential is missing.");
    expect(html).toContain("1.50 s");
    expect(html).toContain("Run Workflow");
  });
});
