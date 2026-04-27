import { computed, ref, watch } from "vue";

import { templatesApi } from "@/services/api";
import type { NodeTemplate, TemplateKind, WorkflowTemplate } from "../types/template.types";

export function useTemplates(initialKind: TemplateKind = "workflow") {
  const kind = ref<TemplateKind>(initialKind);
  const searchQuery = ref("");
  const workflowTemplates = ref<WorkflowTemplate[]>([]);
  const nodeTemplates = ref<NodeTemplate[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  async function fetchTemplates(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const result = await templatesApi.list({
        type: kind.value,
        search: searchQuery.value || undefined,
      });
      workflowTemplates.value = result.workflow_templates;
      nodeTemplates.value = result.node_templates;
    } catch (e) {
      error.value = e instanceof Error ? e.message : "Failed to load templates";
    } finally {
      loading.value = false;
    }
  }

  function onSearchChange(q: string): void {
    searchQuery.value = q;
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      fetchTemplates();
    }, 200);
  }

  watch(kind, () => {
    fetchTemplates();
  });

  const filteredWorkflowTemplates = computed<WorkflowTemplate[]>(() => {
    if (!searchQuery.value) return workflowTemplates.value;
    const q = searchQuery.value.toLowerCase();
    return workflowTemplates.value.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.description ?? "").toLowerCase().includes(q) ||
        t.tags.some((tag) => tag.toLowerCase().includes(q)),
    );
  });

  const filteredNodeTemplates = computed<NodeTemplate[]>(() => {
    if (!searchQuery.value) return nodeTemplates.value;
    const q = searchQuery.value.toLowerCase();
    return nodeTemplates.value.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.description ?? "").toLowerCase().includes(q) ||
        t.tags.some((tag) => tag.toLowerCase().includes(q)),
    );
  });

  return {
    kind,
    searchQuery,
    loading,
    error,
    workflowTemplates,
    nodeTemplates,
    filteredWorkflowTemplates,
    filteredNodeTemplates,
    fetchTemplates,
    onSearchChange,
  };
}
