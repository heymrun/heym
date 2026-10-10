import { createSSRApp, h, type Component } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it } from "vitest";
import { renderToString } from "vue/server-renderer";

import QuickWorkflowRunPanel from "@/components/Layout/QuickWorkflowRunPanel.vue";
import { useQuickDrawerStore } from "@/stores/quickDrawer";
import type { QuickDrawerRunState, QuickDrawerWorkflowViewModel } from "@/types/quickDrawer";

function workflow(inputKeys: string[]): QuickDrawerWorkflowViewModel {
  return {
    id: "wf-1",
    name: "Daily report",
    description: "Sends the morning brief",
    inputFields: inputKeys.map((key) => ({ key })),
    fileInput: null,
    outputNode: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    pinned: false,
    searchableText: "daily report",
  };
}

function mountPinia(): ReturnType<typeof createPinia> {
  const pinia = createPinia();
  setActivePinia(pinia);
  return pinia;
}

async function renderPanel(pinia: ReturnType<typeof createPinia>): Promise<string> {
  const app = createSSRApp({
    render: () => h(QuickWorkflowRunPanel as Component, {
      showClose: false,
      showPin: false,
      showEyebrow: false,
      backLabel: "Back to preview",
    }),
  });
  app.use(pinia);
  return renderToString(app);
}

describe("QuickWorkflowRunPanel", () => {
  it("shows input fields and waits to run when the workflow needs them", async () => {
    const pinia = mountPinia();
    const store = useQuickDrawerStore();
    store.workflows = [workflow(["topic"])];
    store.selectWorkflow("wf-1");

    const html = await renderPanel(pinia);

    expect(html).toContain("Daily report");
    expect(html).toContain("topic");
    expect(html).toContain("Run Workflow");
    expect(html).toContain("Back to preview");
    expect(html).not.toContain("Close quick workflows drawer");
    expect(html).not.toContain("Selected Workflow");
    expect(html).not.toContain("Pin Daily report");
    expect(html).not.toContain("Unpin Daily report");
  });

  it("shows the no-input note and a live run when the workflow starts immediately", async () => {
    const pinia = mountPinia();
    const store = useQuickDrawerStore();
    store.workflows = [workflow([])];
    store.selectWorkflow("wf-1");
    const running: QuickDrawerRunState = {
      status: "running",
      executionId: "exec-1",
      outputs: null,
      executionTimeMs: null,
      executionHistoryId: null,
      errorMessage: null,
      nodeResults: [
        {
          node_id: "n1",
          node_label: "start",
          node_type: "textInput",
          status: "success",
          output: { ok: true },
          execution_time_ms: 12,
          error: null,
        },
      ],
      startedAt: 1,
    };
    store.runState = running;

    const html = await renderPanel(pinia);

    expect(html).toContain("This workflow does not require any input fields.");
    expect(html).toContain("Stop Workflow");
    expect(html).toContain("start");
    expect(html).not.toContain("Run Workflow");
  });
});
