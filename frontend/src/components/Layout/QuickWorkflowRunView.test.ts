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
  fileInput: null,
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

const idle: QuickDrawerRunState = { ...failed, status: "idle", errorMessage: null };

/** Whether the Run button carries the disabled attribute (its classes mention it too). */
function runDisabled(html: string): boolean {
  const tag = html.match(/<button[^>]*data-testid="quick-workflow-run-start"[^>]*>/)?.[0] ?? "";
  return /\sdisabled(?=[\s=>])/.test(tag);
}

// No Pinia: the workflow, the input values and the run arrive as props.
async function render(
  runState: QuickDrawerRunState,
  view: Partial<QuickDrawerWorkflowViewModel> = {},
  selectedFile: File | null = null,
): Promise<string> {
  const app = createSSRApp({
    render: () =>
      h(QuickWorkflowRunView, {
        workflow: { ...workflow, ...view },
        inputValues: { topic: "churn" },
        runState,
        selectedFile,
      }),
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

  it("asks a File Upload workflow for its file before it can run", async () => {
    const fileWorkflow = {
      inputFields: [],
      fileInput: { label: "invoice", maxSizeMb: 5, allowedTypes: ["application/pdf"] },
    };

    const empty = await render(idle, fileWorkflow);
    expect(empty).toContain("Drop a file here or click to choose one");
    expect(empty).toContain("application/pdf, up to 5 MB");
    expect(empty).not.toContain("does not require any input fields");
    expect(runDisabled(empty)).toBe(true);

    const chosen = await render(idle, fileWorkflow, new File(["%PDF"], "march.pdf"));
    expect(chosen).toContain("march.pdf");
    expect(runDisabled(chosen)).toBe(false);
  });
});
