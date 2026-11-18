import { computed, ref } from "vue";
import type { ComputedRef, Ref } from "vue";

import {
  agentModelChoice,
  aiInsertSummary,
  clearAllConfirmText,
} from "@/components/Dialogs/agentMemoryBulkActions";
import type { AgentMemoryModelChoice } from "@/components/Dialogs/agentMemoryBulkActions";
import { useToast } from "@/composables/useToast";
import { getErrorDetail, workflowApi } from "@/services/api";
import type { AgentMemoryGraphResponse } from "@/types/agentMemory";

interface Options {
  workflowId: () => string | undefined;
  canvasNodeId: () => string | undefined;
  /** The agent canvas node's data, where its credential and model live. */
  agentNodeData: () => Record<string, unknown> | undefined;
  graph: Ref<AgentMemoryGraphResponse | null>;
  /** Called with the server's graph after an insert or clear; it replaces the dialog's graph. */
  applyGraph: (next: AgentMemoryGraphResponse) => Promise<void>;
  /** Called once an insert added something, after the panel closed and the graph was applied. */
  onInserted?: () => Promise<void> | void;
}

interface AgentMemoryBulkActions {
  modelChoice: ComputedRef<AgentMemoryModelChoice | null>;
  insertOpen: Ref<boolean>;
  insertText: Ref<string>;
  inserting: Ref<boolean>;
  clearing: Ref<boolean>;
  toggleInsert: () => void;
  closeInsert: () => void;
  submitInsert: () => Promise<void>;
  clearAll: () => Promise<void>;
  reset: () => void;
}

export function useAgentMemoryBulkActions(options: Options): AgentMemoryBulkActions {
  const { showToast } = useToast();

  const modelChoice = computed(() => agentModelChoice(options.agentNodeData()));
  const insertOpen = ref(false);
  const insertText = ref("");
  const inserting = ref(false);
  const clearing = ref(false);

  function toggleInsert(): void {
    if (inserting.value) {
      return;
    }
    insertOpen.value = !insertOpen.value;
  }

  function closeInsert(): void {
    if (!inserting.value) {
      insertOpen.value = false;
    }
  }

  async function submitInsert(): Promise<void> {
    const workflowId = options.workflowId();
    const canvasNodeId = options.canvasNodeId();
    const choice = modelChoice.value;
    const text = insertText.value.trim();
    if (!workflowId || !canvasNodeId || !choice || !text || inserting.value) {
      return;
    }
    inserting.value = true;
    try {
      const result = await workflowApi.aiInsertAgentMemory(workflowId, canvasNodeId, {
        text,
        credential_id: choice.credentialId,
        model: choice.model,
      });
      const summary = aiInsertSummary(result.entities_applied, result.relationships_applied);
      if (summary !== null) {
        // Close before applying: the open panel squeezes the canvas, and the graph is fitted to
        // whatever size the canvas has when it lands.
        insertText.value = "";
        insertOpen.value = false;
      }
      await options.applyGraph(result.graph);
      if (summary === null) {
        // Keep the text so it can be reworded instead of pasted again.
        showToast("No entities or relationships found in that text", "info");
        return;
      }
      showToast(summary, "success");
      await options.onInserted?.();
    } catch (error: unknown) {
      showToast(getErrorDetail(error, "AI insert failed"), "error");
    } finally {
      inserting.value = false;
    }
  }

  async function clearAll(): Promise<void> {
    const workflowId = options.workflowId();
    const canvasNodeId = options.canvasNodeId();
    const g = options.graph.value;
    if (!workflowId || !canvasNodeId || !g?.nodes.length || clearing.value) {
      return;
    }
    if (!window.confirm(clearAllConfirmText(g.nodes.length, g.edges.length))) {
      return;
    }
    clearing.value = true;
    try {
      await workflowApi.clearAgentMemoryGraph(workflowId, canvasNodeId);
      await options.applyGraph({ nodes: [], edges: [] });
      showToast("Memory cleared", "success");
    } catch (error: unknown) {
      showToast(getErrorDetail(error, "Clear failed"), "error");
    } finally {
      clearing.value = false;
    }
  }

  function reset(): void {
    insertOpen.value = false;
    insertText.value = "";
  }

  return {
    modelChoice,
    insertOpen,
    insertText,
    inserting,
    clearing,
    toggleInsert,
    closeInsert,
    submitInsert,
    clearAll,
    reset,
  };
}
