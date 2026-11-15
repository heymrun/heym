import { createSSRApp, h, type Component } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "vue/server-renderer";

import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import { useWorkflowStore } from "@/stores/workflow";
import type { WorkflowNode, WorkflowEdge } from "@/types/workflow";

let capturedClick: (() => void) | null = null;

vi.mock("@/components/ui/Button.vue", () => ({
  default: {
    name: "Button",
    props: ["class", "title", "onClick", "variant", "size", "type"],
    ssrRender(ctx: Record<string, unknown>, push: (val: string) => void) {
      capturedClick = (ctx.onClick as (() => void)) ?? null;
      push(`<button class="${String(ctx.class ?? '')}" title="${String(ctx.title ?? '')}"></button>`);
    },
  },
}));

describe("AgentFieldToggle", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    capturedClick = null;
  });

  function setupStore(fields: string[] = ["gmIncludeBusyTitles"]) {
    const store = useWorkflowStore();
    const node: WorkflowNode = {
      id: "node-meet",
      type: "googleMeet",
      position: { x: 0, y: 0 },
      data: {
        label: "Google Meet",
        agentProvidedFields: [...fields],
      },
    };
    const edge: WorkflowEdge = {
      id: "edge-tool",
      source: "node-meet",
      target: "agent-node",
      targetHandle: "tool-input",
    };
    store.nodes = [node];
    store.edges = [edge];
    return { store, node };
  }

  async function render(nodeId = "node-meet", fieldKey = "gmIncludeBusyDetails"): Promise<string> {
    const app = createSSRApp({
      render: () =>
        h(AgentFieldToggle as Component, {
          nodeId,
          fieldKey,
        }),
    });
    return renderToString(app);
  }

  it("renders active when legacy gmIncludeBusyTitles is in agentProvidedFields", async () => {
    setupStore(["gmIncludeBusyTitles"]);
    const html = await render();

    expect(html).toContain("text-violet-500");
    expect(html).toContain("Agent fills this — click to use fixed value");
  });

  it("renders active when new gmIncludeBusyDetails is in agentProvidedFields", async () => {
    setupStore(["gmIncludeBusyDetails"]);
    const html = await render();

    expect(html).toContain("text-violet-500");
    expect(html).toContain("Agent fills this — click to use fixed value");
  });

  it("renders inactive when field is not in agentProvidedFields", async () => {
    setupStore([]);
    const html = await render();

    expect(html).toContain("text-muted-foreground");
    expect(html).toContain("Click to let agent fill this at runtime");
  });

  it("does not alias legacy key for unrelated fields", async () => {
    setupStore(["gmIncludeBusyTitles"]);
    const html = await render("node-meet", "gmCalendarId");

    expect(html).toContain("text-muted-foreground");
    expect(html).toContain("Click to let agent fill this at runtime");
  });

  it("does not render when node is not connected to a tool input", async () => {
    const { store } = setupStore(["gmIncludeBusyTitles"]);
    store.edges = [];
    const html = await render();

    expect(html).not.toContain("<button");
  });

  it("correctly transitions state when toggling legacy gmIncludeBusyTitles off and on", async () => {
    const { store } = setupStore(["gmIncludeBusyTitles", "otherField"]);
    const htmlInitial = await render();
    expect(htmlInitial).toContain("text-violet-500");
    expect(capturedClick).toBeTypeOf("function");

    // Toggle off: removes legacy and new key
    capturedClick?.();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["otherField"]);
    const htmlAfterToggleOff = await render();
    expect(htmlAfterToggleOff).toContain("text-muted-foreground");

    // Toggle on: adds the canonical new key, not the legacy key
    capturedClick?.();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["otherField", "gmIncludeBusyDetails"]);
    const htmlAfterToggleOn = await render();
    expect(htmlAfterToggleOn).toContain("text-violet-500");

    // Toggle off again: cleans up cleanly
    capturedClick?.();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["otherField"]);
  });

  it("deduplicates keys if both legacy and new key were present", async () => {
    const { store } = setupStore(["gmIncludeBusyTitles", "gmIncludeBusyDetails"]);
    await render();
    expect(capturedClick).toBeTypeOf("function");

    // Toggle off removes all occurrences
    capturedClick?.();
    expect(store.nodes[0].data.agentProvidedFields).toEqual([]);

    // Toggle on adds only single canonical key
    await render();
    capturedClick?.();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["gmIncludeBusyDetails"]);
  });
});
