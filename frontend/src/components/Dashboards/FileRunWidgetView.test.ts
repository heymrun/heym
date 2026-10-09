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
async function render(
  runState: QuickDrawerRunState,
  file: File | null = null,
  shown: FileRunPayload = payload,
  slots: Record<string, (props: { disabled: boolean }) => unknown> = {},
): Promise<string> {
  const app = createSSRApp({
    render: () => h(FileRunWidgetView, { payload: shown, file, runState }, slots),
  });
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
    // Long output lines wrap until the reader turns wrapping off.
    expect(html).toMatch(/<button(?=[^>]*data-testid="output-wrap-toggle")(?=[^>]*aria-pressed="true")[^>]*>/);
    expect(html).toContain("whitespace-pre-wrap");
  });

  it("asks for a file workflow's text input fields too, and runs with Run once a file is chosen", async () => {
    const html = await render(idle, null, {
      ...payload,
      mode: "file",
      input_fields: [{ key: "text", defaultValue: null }],
    });

    expect(html).toContain("application/pdf, up to 5 MB");
    expect(html).toContain("text");
    expect(html).toMatch(/<button(?=[^>]*type="submit")(?=[^>]*disabled)[^>]*>/);
  });

  it("lets the host draw its own Run button", async () => {
    const html = await render(idle, null, { type: "fileRun", mode: "run", input_fields: [] }, {
      run: ({ disabled }) => h("button", { class: "host-run", disabled }, "Go"),
    });

    expect(html).toContain("host-run");
    expect(html).not.toContain(">Run<");
  });

  it("asks for a workflow's start fields, with their defaults", async () => {
    const html = await render(idle, null, {
      type: "fileRun",
      mode: "form",
      input_fields: [
        { key: "vendor", defaultValue: null },
        { key: "amount", defaultValue: "10" },
      ],
    });

    expect(html).toContain("vendor");
    expect(html).toContain('value="10"');
    expect(html).toContain("Run");
    expect(html).not.toContain("up to");
  });

  it("offers a Run button for a workflow without inputs", async () => {
    const html = await render(idle, null, { type: "fileRun", mode: "run", input_fields: [] });

    expect(html).toContain("Run");
    expect(html).not.toContain("<input");
  });
});
