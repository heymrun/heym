import { ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  agentModelChoice,
  aiInsertSummary,
  aiInsertTooltip,
  clearAllConfirmText,
  clearAllTooltip,
} from "@/components/Dialogs/agentMemoryBulkActions";
import { useAgentMemoryBulkActions } from "@/components/Dialogs/useAgentMemoryBulkActions";
import type { AgentMemoryGraphResponse, AgentMemoryNodeDTO } from "@/types/agentMemory";

const { aiInsertAgentMemory, clearAgentMemoryGraph, showToast } = vi.hoisted(() => ({
  aiInsertAgentMemory: vi.fn(),
  clearAgentMemoryGraph: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  workflowApi: { aiInsertAgentMemory, clearAgentMemoryGraph },
  getErrorDetail: (_error: unknown, fallback: string): string => fallback,
}));
vi.mock("@/composables/useToast", () => ({ useToast: () => ({ showToast }) }));

function memoryNode(name: string): AgentMemoryNodeDTO {
  return {
    id: `id-${name}`,
    entity_name: name,
    entity_type: "topic",
    properties: {},
    confidence: 1,
    created_at: "2026-11-18T00:00:00Z",
    updated_at: "2026-11-18T00:00:00Z",
  };
}

describe("agentModelChoice", () => {
  it("needs both a credential and a model", () => {
    expect(agentModelChoice({ credentialId: "c1", model: "gpt-x" })).toEqual({
      credentialId: "c1",
      model: "gpt-x",
    });
    expect(agentModelChoice({ credentialId: "c1", model: "  " })).toBeNull();
    expect(agentModelChoice({ model: "gpt-x" })).toBeNull();
    expect(agentModelChoice(undefined)).toBeNull();
  });
});

describe("tooltips and messages", () => {
  it("explains why AI insert is disabled and names the model when it is not", () => {
    expect(aiInsertTooltip(null)).toMatch(/Select a credential and model/);
    expect(aiInsertTooltip("gpt-x")).toContain("gpt-x");
  });

  it("explains why Clear all is disabled on an empty memory", () => {
    expect(clearAllTooltip(0)).toBe("Memory is already empty");
    expect(clearAllTooltip(3)).toMatch(/^Clear all/);
  });

  it("pluralizes counts", () => {
    expect(clearAllConfirmText(1, 2)).toContain("1 entity and 2 relationships");
    expect(aiInsertSummary(2, 1)).toBe("Inserted 2 entities and 1 relationship");
    expect(aiInsertSummary(0, 0)).toBeNull();
  });
});

describe("useAgentMemoryBulkActions", () => {
  const confirmSpy = vi.fn(() => true);

  beforeEach(() => {
    vi.stubGlobal("window", { confirm: confirmSpy });
    aiInsertAgentMemory.mockReset();
    clearAgentMemoryGraph.mockReset();
    showToast.mockReset();
    confirmSpy.mockReset();
    confirmSpy.mockReturnValue(true);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function setup(nodeData: Record<string, unknown> | undefined): {
    actions: ReturnType<typeof useAgentMemoryBulkActions>;
    applyGraph: ReturnType<typeof vi.fn>;
    onInserted: ReturnType<typeof vi.fn>;
    panelOpenWhenApplied: () => boolean | null;
  } {
    let openWhenApplied: boolean | null = null;
    const graph = ref<AgentMemoryGraphResponse | null>({
      nodes: [memoryNode("Acme"), memoryNode("Berlin")],
      edges: [],
    });
    const applyGraph = vi.fn(async (next: AgentMemoryGraphResponse) => {
      openWhenApplied = actions.insertOpen.value;
      graph.value = next;
    });
    const onInserted = vi.fn();
    const actions = useAgentMemoryBulkActions({
      workflowId: () => "wf-1",
      canvasNodeId: () => "agent-1",
      agentNodeData: () => nodeData,
      graph,
      applyGraph,
      onInserted,
    });
    return { actions, applyGraph, onInserted, panelOpenWhenApplied: () => openWhenApplied };
  }

  it("sends the agent's own credential and model, then applies the returned graph", async () => {
    const returned = { nodes: [memoryNode("Acme")], edges: [] };
    aiInsertAgentMemory.mockResolvedValue({
      graph: returned,
      entities_applied: 1,
      relationships_applied: 0,
    });
    const { actions, applyGraph, onInserted, panelOpenWhenApplied } = setup({
      credentialId: "cred-1",
      model: "gpt-x",
    });
    actions.insertOpen.value = true;
    actions.insertText.value = "  Acme is in Berlin.  ";

    await actions.submitInsert();

    expect(aiInsertAgentMemory).toHaveBeenCalledWith("wf-1", "agent-1", {
      text: "Acme is in Berlin.",
      credential_id: "cred-1",
      model: "gpt-x",
    });
    expect(applyGraph).toHaveBeenCalledWith(returned);
    expect(showToast).toHaveBeenCalledWith("Inserted 1 entity and 0 relationships", "success");
    expect(actions.insertOpen.value).toBe(false);
    expect(actions.insertText.value).toBe("");
    // The canvas is fitted at full size, then scrolled into view.
    expect(panelOpenWhenApplied()).toBe(false);
    expect(onInserted).toHaveBeenCalledOnce();
  });

  it("keeps the panel and text when the model found nothing", async () => {
    aiInsertAgentMemory.mockResolvedValue({
      graph: { nodes: [], edges: [] },
      entities_applied: 0,
      relationships_applied: 0,
    });
    const { actions, onInserted } = setup({ credentialId: "cred-1", model: "gpt-x" });
    actions.insertOpen.value = true;
    actions.insertText.value = "hello";

    await actions.submitInsert();

    expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/No entities/), "info");
    expect(actions.insertOpen.value).toBe(true);
    expect(actions.insertText.value).toBe("hello");
    expect(onInserted).not.toHaveBeenCalled();
  });

  it("does nothing without a model on the agent", async () => {
    const { actions } = setup({ credentialId: "cred-1" });
    actions.insertText.value = "Acme is in Berlin.";

    await actions.submitInsert();

    expect(actions.modelChoice.value).toBeNull();
    expect(aiInsertAgentMemory).not.toHaveBeenCalled();
  });

  it("clears only after the user confirms", async () => {
    const { actions, applyGraph } = setup({ credentialId: "cred-1", model: "gpt-x" });
    confirmSpy.mockReturnValueOnce(false);
    await actions.clearAll();
    expect(clearAgentMemoryGraph).not.toHaveBeenCalled();

    clearAgentMemoryGraph.mockResolvedValue({ deleted_nodes: 2, deleted_edges: 0 });
    await actions.clearAll();
    expect(clearAgentMemoryGraph).toHaveBeenCalledWith("wf-1", "agent-1");
    expect(applyGraph).toHaveBeenCalledWith({ nodes: [], edges: [] });
    expect(showToast).toHaveBeenCalledWith("Memory cleared", "success");
  });

  it("leaves the graph alone when the clear request fails", async () => {
    clearAgentMemoryGraph.mockRejectedValue(new Error("boom"));
    const { actions, applyGraph } = setup({ credentialId: "cred-1", model: "gpt-x" });

    await actions.clearAll();

    expect(applyGraph).not.toHaveBeenCalled();
    expect(showToast).toHaveBeenCalledWith("Clear failed", "error");
    expect(actions.clearing.value).toBe(false);
  });
});
