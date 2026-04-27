<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { ExternalLink, GitBranch, ArrowRight } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { workflowApi } from "@/services/api";
import { useWorkflowStore } from "@/stores/workflow";
import { generateId, replaceNodeLabelRefs } from "@/lib/utils";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

interface Props {
  open: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "extracted", workflowId: string): void;
}>();

const workflowStore = useWorkflowStore();

const name = ref("");
const description = ref("");
const isExtracting = ref(false);
const error = ref("");

const extractInfo = computed(() => {
  if (!props.open) return null;
  return workflowStore.getExtractInfo();
});

const selectedNodeLabels = computed(() => {
  if (!extractInfo.value) return [];
  return extractInfo.value.nodes.map((n) => n.data.label);
});

const externalInputLabels = computed(() => {
  if (!extractInfo.value) return [];
  const unique = new Map<string, string>();
  for (const input of extractInfo.value.externalInputs) {
    unique.set(input.sourceNodeId, input.sourceNodeLabel);
  }
  return Array.from(unique.values());
});

watch(
  () => props.open,
  (open) => {
    if (open) {
      name.value = "";
      description.value = "";
      error.value = "";
    }
  }
);

onMounted(() => {
  const unsub = onDismissOverlays(() => {
    if (props.open) closeDialog();
  });
  onUnmounted(unsub);
});

function closeDialog(): void {
  emit("close");
}

async function handleExtract(): Promise<void> {
  if (!name.value.trim()) {
    error.value = "Name is required";
    return;
  }

  if (!extractInfo.value || extractInfo.value.nodes.length === 0) {
    error.value = "No nodes selected";
    return;
  }

  isExtracting.value = true;
  error.value = "";

  try {
    const newWorkflow = await workflowApi.create({
      name: name.value.trim(),
      description: description.value.trim() || undefined,
    });

    const oldToNewIdMap = new Map<string, string>();
    const newNodes: WorkflowNode[] = [];

    let minX = Infinity;
    let minY = Infinity;
    for (const node of extractInfo.value.nodes) {
      minX = Math.min(minX, node.position.x);
      minY = Math.min(minY, node.position.y);
    }

    const hasExternalInputs = extractInfo.value.externalInputs.length > 0;
    let textInputNodeId: string | null = null;
    const startNodeLabel = "start";

    if (hasExternalInputs) {
      textInputNodeId = generateId();
      const textInputNode: WorkflowNode = {
        id: textInputNodeId,
        type: "textInput",
        position: { x: minX - 300, y: minY },
        data: {
          label: startNodeLabel,
          value: "",
          inputFields: [{ key: "data" }],
        },
      };
      newNodes.push(textInputNode);
    }

    const externalInputLabelMap = new Map<string, string>();
    for (const input of extractInfo.value.externalInputs) {
      if (!externalInputLabelMap.has(input.sourceNodeLabel)) {
        const sourceNode = workflowStore.nodes.find((n) => n.id === input.sourceNodeId);
        const isTextInput = sourceNode?.type === "textInput";
        if (isTextInput) {
          const inputFields = sourceNode?.data.inputFields as Array<{ key: string }> | undefined;
          const fieldKey = inputFields?.[0]?.key || "text";
          externalInputLabelMap.set(`${input.sourceNodeLabel}.body.${fieldKey}`, `$${startNodeLabel}.body.data`);
        } else {
          externalInputLabelMap.set(input.sourceNodeLabel, `$${startNodeLabel}.body.data`);
        }
      }
    }

    for (const node of extractInfo.value.nodes) {
      const newId = generateId();
      oldToNewIdMap.set(node.id, newId);

      let nodeData = { ...node.data };
      if (externalInputLabelMap.size > 0) {
        nodeData = replaceNodeLabelRefs(nodeData, externalInputLabelMap);
      }

      const newNode: WorkflowNode = {
        id: newId,
        type: node.type,
        position: {
          x: node.position.x - minX + 50,
          y: node.position.y - minY + 50,
        },
        data: nodeData,
      };
      newNodes.push(newNode);
    }

    const newEdges: WorkflowEdge[] = [];

    for (const edge of extractInfo.value.edges) {
      const newSourceId = oldToNewIdMap.get(edge.source);
      const newTargetId = oldToNewIdMap.get(edge.target);
      if (newSourceId && newTargetId) {
        newEdges.push({
          id: `edge_${newSourceId}_${newTargetId}_${Date.now()}`,
          source: newSourceId,
          target: newTargetId,
          sourceHandle: edge.sourceHandle,
          targetHandle: edge.targetHandle,
        });
      }
    }

    if (textInputNodeId && hasExternalInputs) {
      const connectedTargets = new Set<string>();
      for (const input of extractInfo.value.externalInputs) {
        const newTargetId = oldToNewIdMap.get(input.targetNodeId);
        if (newTargetId && !connectedTargets.has(newTargetId)) {
          connectedTargets.add(newTargetId);
          newEdges.push({
            id: `edge_${textInputNodeId}_${newTargetId}_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
            source: textInputNodeId,
            target: newTargetId,
            sourceHandle: undefined,
            targetHandle: "input",
          });
        }
      }
    }

    const hasOutputNode = newNodes.some((n) => n.type === "output");
    if (!hasOutputNode && extractInfo.value.externalOutputs.length > 0) {
      const lastNode = extractInfo.value.externalOutputs[0];
      const newSourceId = oldToNewIdMap.get(lastNode.sourceNodeId);
      if (newSourceId) {
        const sourceNode = newNodes.find((n) => n.id === newSourceId);
        const originalSourceNode = extractInfo.value.nodes.find((n) => n.id === lastNode.sourceNodeId);
        const sourceLabel = originalSourceNode?.data.label || "input";

        let outputFieldPath = "";
        if (originalSourceNode?.type === "set") {
          const mappings = originalSourceNode.data.mappings as Array<{ key: string }> | undefined;
          if (mappings && mappings.length > 0) {
            outputFieldPath = `.${mappings[0].key}`;
          }
        } else if (originalSourceNode?.type === "llm") {
          outputFieldPath = ".text";
        }

        const outputNodeId = generateId();
        const outputNode: WorkflowNode = {
          id: outputNodeId,
          type: "output",
          position: {
            x: (sourceNode?.position.x || 0) + 300,
            y: sourceNode?.position.y || 0,
          },
          data: {
            label: "output",
            message: `$${sourceLabel}${outputFieldPath}`,
            allowDownstream: false,
          },
        };
        newNodes.push(outputNode);
        newEdges.push({
          id: `edge_${newSourceId}_${outputNodeId}_${Date.now()}`,
          source: newSourceId,
          target: outputNodeId,
          sourceHandle: lastNode.sourceHandle,
          targetHandle: "input",
        });
      }
    }

    await workflowApi.update(newWorkflow.id, {
      nodes: newNodes,
      edges: newEdges,
    });

    const nodeIdsToReplace = extractInfo.value.nodes.map((n) => n.id);
    const extractedNodeLabels = extractInfo.value.nodes.map((n) => n.data.label);
    workflowStore.replaceNodesWithExecute(
      nodeIdsToReplace,
      newWorkflow.id,
      newWorkflow.name,
      extractedNodeLabels,
    );

    emit("extracted", newWorkflow.id);
    closeDialog();
  } catch (err) {
    if (err instanceof Error) {
      error.value = err.message;
    } else {
      error.value = "Failed to extract workflow";
    }
  } finally {
    isExtracting.value = false;
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center"
    >
      <div
        class="absolute inset-0 bg-background/80 backdrop-blur-sm"
        @click="closeDialog"
      />

      <div class="relative bg-card border rounded-lg shadow-lg w-full max-w-lg p-6 animate-in fade-in zoom-in-95">
        <div class="flex items-center gap-3 mb-6">
          <div class="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10">
            <ExternalLink class="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 class="text-lg font-semibold">
              Extract to Sub-Workflow
            </h2>
            <p class="text-sm text-muted-foreground">
              Create a new workflow from selected nodes
            </p>
          </div>
        </div>

        <div class="space-y-4">
          <div class="space-y-2">
            <Label for="workflow-name">
              Workflow Name
            </Label>
            <Input
              id="workflow-name"
              v-model="name"
              placeholder="My Sub-Workflow"
              @keydown.enter="handleExtract"
            />
          </div>

          <div class="space-y-2">
            <Label for="workflow-description">
              Description (optional)
            </Label>
            <Textarea
              id="workflow-description"
              v-model="description"
              placeholder="What does this workflow do?"
              :rows="2"
            />
          </div>

          <div class="space-y-3 p-3 rounded-lg bg-muted/50">
            <div class="flex items-center gap-2 text-sm font-medium">
              <GitBranch class="w-4 h-4 text-muted-foreground" />
              <span>{{ selectedNodeLabels.length }} nodes will be extracted</span>
            </div>

            <div
              v-if="selectedNodeLabels.length > 0"
              class="flex flex-wrap gap-1.5"
            >
              <span
                v-for="label in selectedNodeLabels.slice(0, 8)"
                :key="label"
                class="px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary"
              >
                {{ label }}
              </span>
              <span
                v-if="selectedNodeLabels.length > 8"
                class="px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground"
              >
                +{{ selectedNodeLabels.length - 8 }} more
              </span>
            </div>

            <div
              v-if="externalInputLabels.length > 0"
              class="pt-2 border-t border-border/50"
            >
              <div class="flex items-center gap-2 text-xs text-muted-foreground mb-1.5">
                <ArrowRight class="w-3 h-3" />
                <span>Inputs from external nodes:</span>
              </div>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="label in externalInputLabels"
                  :key="label"
                  class="px-2 py-0.5 text-xs rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400"
                >
                  {{ label }}
                </span>
              </div>
            </div>
          </div>

          <p
            v-if="error"
            class="text-sm text-destructive"
          >
            {{ error }}
          </p>
        </div>

        <div class="flex justify-end gap-3 mt-6">
          <Button
            variant="outline"
            @click="closeDialog"
          >
            Cancel
          </Button>
          <Button
            :loading="isExtracting"
            :disabled="!name.trim() || selectedNodeLabels.length === 0"
            @click="handleExtract"
          >
            Extract
          </Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
