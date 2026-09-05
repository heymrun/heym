import { createSSRApp, h, type Component } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";
import { renderToString } from "vue/server-renderer";

vi.mock("@/stores/theme", () => ({
  useThemeStore: () => ({
    isDark: false,
    toggle: vi.fn(),
    setTheme: vi.fn(),
  }),
}));

import type { NodeType, WorkflowNode } from "@/types/workflow";
import MobileNodeExecutionDetail from "@/components/Panels/propertiesPanel/MobileNodeExecutionDetail.vue";
import MobileWorkflowTree from "@/components/Canvas/MobileWorkflowTree.vue";
import MobileWorkflowTreeConnectionSheet from "@/components/Canvas/MobileWorkflowTreeConnectionSheet.vue";
import MobileWorkflowTreeNode from "@/components/Canvas/MobileWorkflowTreeNode.vue";
import MobileWorkflowTreeNodesTab from "@/components/Canvas/MobileWorkflowTreeNodesTab.vue";
import { useWorkflowStore } from "@/stores/workflow";

async function renderComponent(component: Component, props: Record<string, unknown> = {}): Promise<string> {
  const pinia = createPinia();
  setActivePinia(pinia);
  const app = createSSRApp({
    render: () => h(component, props),
  });
  app.use(pinia);
  const ssrContext: { teleports?: Record<string, string> } = {};
  const html = await renderToString(app, ssrContext);
  const teleports = ssrContext.teleports
    ? Object.values(ssrContext.teleports).join("\n")
    : "";
  return `${html}\n${teleports}`;
}

describe("Mobile surface SSR rendering with unknown/stale node types", () => {
  describe("mobile node tree", () => {
    it("renders MobileWorkflowTreeNode with unknown node type safely", async () => {
      const unknownNode: WorkflowNode = {
        id: "node-unknown-1",
        type: "legacyCustomAction" as NodeType,
        position: { x: 0, y: 0 },
        data: {
          label: "Custom Stale Action",
          url: "https://example.com/api",
        },
      };

      const html = await renderComponent(MobileWorkflowTreeNode, {
        entry: {
          node: unknownNode,
          children: [],
          depth: 0,
          accent: "violet",
          hasSuccessor: false,
        },
      });

      expect(html).toContain("Custom Stale Action");
      expect(html).toContain("https://example.com/api");
    });

    it("renders MobileWorkflowTreeNode with default humanized label when label is absent", async () => {
      const unknownNode: WorkflowNode = {
        id: "node-unknown-2",
        type: "stalePluginNode" as NodeType,
        position: { x: 0, y: 0 },
        data: { label: "" },
      };

      const html = await renderComponent(MobileWorkflowTreeNode, {
        entry: {
          node: unknownNode,
          children: [],
          depth: 0,
          accent: "emerald",
          hasSuccessor: false,
        },
      });

      expect(html).toContain("Stale Plugin Node");
    });

    it("renders MobileWorkflowTreeNodesTab containing selected unknown node without label safely", async () => {
      const pinia = createPinia();
      setActivePinia(pinia);
      const store = useWorkflowStore();

      const unknownNode: WorkflowNode = {
        id: "node-unknown-tab",
        type: "deprecatedCustomAction" as NodeType,
        position: { x: 0, y: 0 },
        data: { label: "" },
      };

      store.nodes = [unknownNode];
      store.selectNode(unknownNode.id);

      const app = createSSRApp({
        render: () => h(MobileWorkflowTreeNodesTab),
      });
      app.use(pinia);

      const ssrContext: { teleports?: Record<string, string> } = {};
      const html = await renderToString(app, ssrContext);

      expect(html).toContain("Deprecated Custom Action");
    });

    it("renders MobileWorkflowTree containing unknown node types and selections safely", async () => {
      const pinia = createPinia();
      setActivePinia(pinia);
      const store = useWorkflowStore();

      const unknownNode: WorkflowNode = {
        id: "node-unknown-tree",
        type: "deprecatedTrigger" as NodeType,
        position: { x: 0, y: 0 },
        data: {
          label: "Legacy Webhook Trigger",
        },
      };

      store.nodes = [unknownNode];
      store.selectNode(unknownNode.id);

      const app = createSSRApp({
        render: () => h(MobileWorkflowTree),
      });
      app.use(pinia);

      const ssrContext: { teleports?: Record<string, string> } = {};
      const html = await renderToString(app, ssrContext);

      expect(html).toContain("Legacy Webhook Trigger");
    });
  });

  describe("connection sheet", () => {
    it("renders connection sheet with known and unknown candidate node types without throwing", async () => {
      const activeNode: WorkflowNode = {
        id: "source-node",
        type: "http",
        position: { x: 0, y: 0 },
        data: { label: "Source HTTP" },
      };

      const knownCandidate: WorkflowNode = {
        id: "candidate-known",
        type: "http",
        position: { x: 0, y: 100 },
        data: {
          label: "My Webhook Step",
          url: "https://api.example.com/hook",
        },
      };

      const unknownCandidate: WorkflowNode = {
        id: "candidate-unknown",
        type: "staleCustomIntegration" as NodeType,
        position: { x: 0, y: 200 },
        data: {
          label: "Archived Integration",
          url: "https://archive.example.com",
        },
      };

      const unlabelledCandidate: WorkflowNode = {
        id: "candidate-unlabelled",
        type: "deletedWorkerType" as NodeType,
        position: { x: 0, y: 300 },
        data: {
          label: "   ",
        },
      };

      const html = await renderComponent(MobileWorkflowTreeConnectionSheet, {
        open: true,
        node: activeNode,
        nodes: [activeNode, knownCandidate, unknownCandidate, unlabelledCandidate],
      });

      // Verify connection sheet dialog renders
      expect(html).toContain("Connect Source HTTP");

      // Verify candidates render their labels
      expect(html).toContain("My Webhook Step");
      expect(html).toContain("Archived Integration");

      // Verify candidate secondary lines display typeLabel, not summary URL
      expect(html).toContain("HTTP");
      expect(html).toContain("Stale Custom Integration");
      expect(html).not.toContain("https://api.example.com/hook");

      // Verify candidate with empty/whitespace label falls back to typeLabel
      expect(html).toContain("Deleted Worker Type");
    });
  });

  describe("mobile node execution detail", () => {
    it("renders execution detail with unknown node type safely", async () => {
      const unknownNode: WorkflowNode = {
        id: "node-exec-unknown",
        type: "deletedWorkerType" as NodeType,
        position: { x: 0, y: 0 },
        data: {
          label: "Stale Worker Step",
        },
      };

      const html = await renderComponent(MobileNodeExecutionDetail, {
        open: true,
        node: unknownNode,
        result: {
          node_id: "node-exec-unknown",
          node_label: "Stale Worker Step",
          node_type: "deletedWorkerType",
          status: "success",
          output: { count: 42 },
          execution_time_ms: 120,
          error: null,
        },
        output: { count: 42 },
        workflowName: "Demo Workflow",
      });

      expect(html).toContain("Stale Worker Step");
      expect(html).toContain("Deleted Worker Type");
      expect(html).toContain("node-exec-unknown");
      expect(html).toContain("success");
    });

    it("renders execution detail when node is null and only result has unknown node type", async () => {
      const html = await renderComponent(MobileNodeExecutionDetail, {
        open: true,
        node: null,
        result: {
          node_id: "orphan-node-1",
          node_label: "Orphan Execution",
          node_type: "unregisteredCustomNode",
          status: "error",
          output: {},
          execution_time_ms: 350,
          error: "Execution failed",
        },
        output: {},
        workflowName: "Demo Workflow",
      });

      expect(html).toContain("Orphan Execution");
      expect(html).toContain("Unregistered Custom Node");
      expect(html).toContain("orphan-node-1");
    });
  });
});
