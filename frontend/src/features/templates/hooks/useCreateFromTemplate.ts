import { ref } from "vue";
import { useRouter } from "vue-router";

import { templatesApi, workflowApi } from "@/services/api";
import { useRecentWorkflows } from "@/composables/useRecentWorkflows";
import type { NodeTemplate, WorkflowTemplate } from "../types/template.types";
import type { WorkflowNode, WorkflowEdge, NodeType, NodeData } from "@/types/workflow";

export type NodeTemplateDestination = "new" | "last" | "existing";

export function useCreateFromTemplate() {
  const router = useRouter();
  const { getRecent, addRecent } = useRecentWorkflows();
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function useWorkflowTemplate(template: WorkflowTemplate): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const used = await templatesApi.useWorkflow(template.id);
      const created = await workflowApi.create({
        name: used.name,
        description: used.description ?? undefined,
      });
      await workflowApi.update(created.id, {
        nodes: used.nodes as unknown as WorkflowNode[],
        edges: used.edges as unknown as WorkflowEdge[],
      });
      addRecent(created.id, created.name);
      router.push({ name: "editor", params: { id: created.id } });
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Failed to use template";
    } finally {
      loading.value = false;
    }
  }

  async function useNodeTemplate(
    template: NodeTemplate,
    destination: NodeTemplateDestination,
    existingWorkflowId?: string,
  ): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const used = await templatesApi.useNode(template.id);

      if (destination === "new") {
        const created = await workflowApi.create({
          name: `Workflow with ${used.name}`,
        });
        const nodeId = `node_${Date.now()}`;
        await workflowApi.update(created.id, {
          nodes: [
            {
              id: nodeId,
              type: used.node_type as NodeType,
              position: { x: 200, y: 200 },
              data: { label: String(used.node_data?.label ?? used.name), ...used.node_data } as NodeData,
            },
          ],
          edges: [],
        });
        addRecent(created.id, created.name);
        router.push({ name: "editor", params: { id: created.id } });
      } else if (destination === "existing" && existingWorkflowId) {
        router.push({
          name: "editor",
          params: { id: existingWorkflowId },
          query: { addNodeTemplate: template.id },
        });
      } else {
        // "last" fallback
        const recent = getRecent();
        const lastId = recent[0]?.id;
        if (!lastId) {
          await useNodeTemplate(template, "new");
          return;
        }
        router.push({ name: "editor", params: { id: lastId }, query: { addNodeTemplate: template.id } });
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Failed to use template";
    } finally {
      loading.value = false;
    }
  }

  function getLastWorkflow(): { id: string; name: string } | null {
    const recent = getRecent();
    return recent[0] ?? null;
  }

  return {
    loading,
    error,
    useWorkflowTemplate,
    useNodeTemplate,
    getLastWorkflow,
  };
}
