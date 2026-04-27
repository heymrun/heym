import { ref } from "vue";

import { templatesApi } from "@/services/api";
import type {
  CreateTemplateRequest,
  NodeTemplate,
  TemplateVisibility,
  WorkflowTemplate,
} from "../types/template.types";

export interface ShareWorkflowPayload {
  name: string;
  description?: string;
  tags?: string[];
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  canvas_snapshot?: string;
  visibility?: TemplateVisibility;
  shared_with?: string[];
  shared_with_teams?: string[];
}

export interface ShareNodePayload {
  name: string;
  description?: string;
  tags?: string[];
  node_type: string;
  node_data: Record<string, unknown>;
  visibility?: TemplateVisibility;
  shared_with?: string[];
  shared_with_teams?: string[];
}

export function useShareTemplate() {
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function shareWorkflow(payload: ShareWorkflowPayload): Promise<WorkflowTemplate> {
    loading.value = true;
    error.value = null;
    try {
      const req: CreateTemplateRequest = {
        kind: "workflow",
        workflow: {
          name: payload.name,
          description: payload.description,
          tags: payload.tags ?? [],
          nodes: payload.nodes,
          edges: payload.edges,
          canvas_snapshot: payload.canvas_snapshot,
          visibility: payload.visibility ?? "everyone",
          shared_with: payload.shared_with ?? [],
          shared_with_teams: payload.shared_with_teams ?? [],
        },
      };
      return (await templatesApi.create(req)) as WorkflowTemplate;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Failed to share template";
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function shareNode(payload: ShareNodePayload): Promise<NodeTemplate> {
    loading.value = true;
    error.value = null;
    try {
      const req: CreateTemplateRequest = {
        kind: "node",
        node: {
          name: payload.name,
          description: payload.description,
          tags: payload.tags ?? [],
          node_type: payload.node_type,
          node_data: payload.node_data,
          visibility: payload.visibility ?? "everyone",
          shared_with: payload.shared_with ?? [],
          shared_with_teams: payload.shared_with_teams ?? [],
        },
      };
      return (await templatesApi.create(req)) as NodeTemplate;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Failed to share template";
      throw e;
    } finally {
      loading.value = false;
    }
  }

  return { loading, error, shareWorkflow, shareNode };
}
