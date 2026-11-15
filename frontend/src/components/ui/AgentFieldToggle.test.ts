import { createSSRApp, h, type Component } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { renderToString } from "vue/server-renderer";

import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import { useWorkflowStore } from "@/stores/workflow";
import type { WorkflowNode, WorkflowEdge } from "@/types/workflow";

describe("AgentFieldToggle", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
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

  it("renders active when legacy gmIncludeBusyTitles is in agentProvidedFields", async () => {
    setupStore(["gmIncludeBusyTitles"]);
    const app = createSSRApp({
      render: () =>
        h(AgentFieldToggle as Component, {
          nodeId: "node-meet",
          fieldKey: "gmIncludeBusyDetails",
        }),
    });
    const html = await renderToString(app);

    expect(html).toContain("text-violet-500");
    expect(html).toContain("Agent fills this — click to use fixed value");
  });

  it("renders active when new gmIncludeBusyDetails is in agentProvidedFields", async () => {
    setupStore(["gmIncludeBusyDetails"]);
    const app = createSSRApp({
      render: () =>
        h(AgentFieldToggle as Component, {
          nodeId: "node-meet",
          fieldKey: "gmIncludeBusyDetails",
        }),
    });
    const html = await renderToString(app);

    expect(html).toContain("text-violet-500");
    expect(html).toContain("Agent fills this — click to use fixed value");
  });

  it("renders inactive when field is not in agentProvidedFields", async () => {
    setupStore([]);
    const app = createSSRApp({
      render: () =>
        h(AgentFieldToggle as Component, {
          nodeId: "node-meet",
          fieldKey: "gmIncludeBusyDetails",
        }),
    });
    const html = await renderToString(app);

    expect(html).toContain("text-muted-foreground");
    expect(html).toContain("Click to let agent fill this at runtime");
  });

  it("does not alias legacy key for unrelated fields", async () => {
    setupStore(["gmIncludeBusyTitles"]);
    const app = createSSRApp({
      render: () =>
        h(AgentFieldToggle as Component, {
          nodeId: "node-meet",
          fieldKey: "gmCalendarId",
        }),
    });
    const html = await renderToString(app);

    expect(html).toContain("text-muted-foreground");
    expect(html).toContain("Click to let agent fill this at runtime");
  });

  it("does not render when node is not connected to a tool input", async () => {
    const { store } = setupStore(["gmIncludeBusyTitles"]);
    store.edges = [];
    const app = createSSRApp({
      render: () =>
        h(AgentFieldToggle as Component, {
          nodeId: "node-meet",
          fieldKey: "gmIncludeBusyDetails",
        }),
    });
    const html = await renderToString(app);

    expect(html).not.toContain("<button");
  });

  it("correctly transitions state when toggling legacy gmIncludeBusyTitles off and on", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const { store } = setupStore(["gmIncludeBusyTitles", "otherField"]);

    interface ExposedToggle {
      isAgentProvided: { value: boolean };
      isToolNodeField: { value: boolean };
      toggle: () => void;
    }

    let exposed!: ExposedToggle;
    const app = createSSRApp({
      render: () => null,
    });
    app.use(pinia);
    app.provide(Symbol.for("v-scx"), { modules: new Set() });

    app.runWithContext(() => {
      const setupFn = (AgentFieldToggle as unknown as { setup: (props: unknown, ctx: unknown) => unknown }).setup;
      setupFn(
        { nodeId: "node-meet", fieldKey: "gmIncludeBusyDetails" },
        { expose: (exp: ExposedToggle) => { exposed = exp; } },
      );
    });

    // Initial state: legacy key enables the toggle for new key
    expect(exposed.isAgentProvided.value).toBe(true);

    // Toggle off: removes both legacy and new key
    exposed.toggle();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["otherField"]);
    expect(exposed.isAgentProvided.value).toBe(false);

    // Toggle on: adds the canonical new key, not the legacy key
    exposed.toggle();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["otherField", "gmIncludeBusyDetails"]);
    expect(exposed.isAgentProvided.value).toBe(true);

    // Toggle off again: cleans up cleanly
    exposed.toggle();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["otherField"]);
    expect(exposed.isAgentProvided.value).toBe(false);
  });

  it("deduplicates keys if both legacy and new key were present", () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const { store } = setupStore(["gmIncludeBusyTitles", "gmIncludeBusyDetails"]);

    interface ExposedToggle {
      isAgentProvided: { value: boolean };
      toggle: () => void;
    }

    let exposed!: ExposedToggle;
    const app = createSSRApp({
      render: () => null,
    });
    app.use(pinia);
    app.provide(Symbol.for("v-scx"), { modules: new Set() });

    app.runWithContext(() => {
      const setupFn = (AgentFieldToggle as unknown as { setup: (props: unknown, ctx: unknown) => unknown }).setup;
      setupFn(
        { nodeId: "node-meet", fieldKey: "gmIncludeBusyDetails" },
        { expose: (exp: ExposedToggle) => { exposed = exp; } },
      );
    });

    expect(exposed.isAgentProvided.value).toBe(true);

    // Toggle off removes all occurrences
    exposed.toggle();
    expect(store.nodes[0].data.agentProvidedFields).toEqual([]);
    expect(exposed.isAgentProvided.value).toBe(false);

    // Toggle on adds only single canonical key
    exposed.toggle();
    expect(store.nodes[0].data.agentProvidedFields).toEqual(["gmIncludeBusyDetails"]);
    expect(exposed.isAgentProvided.value).toBe(true);
  });
});
