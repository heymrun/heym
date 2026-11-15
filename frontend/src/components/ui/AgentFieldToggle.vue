<script setup lang="ts">
import { computed } from "vue";
import { Bot } from "lucide-vue-next";
import { useWorkflowStore } from "@/stores/workflow";
import Button from "@/components/ui/Button.vue";

interface Props {
  nodeId: string;
  fieldKey: string;
}

const props = defineProps<Props>();
const workflowStore = useWorkflowStore();

const isToolNodeField = computed((): boolean =>
  workflowStore.edges.some(
    (edge) => edge.source === props.nodeId && edge.targetHandle === "tool-input",
  ),
);

const isAgentProvided = computed((): boolean => {
  if (!isToolNodeField.value) return false;
  const node = workflowStore.nodes.find((n) => n.id === props.nodeId);
  const fields: string[] = node?.data.agentProvidedFields ?? [];
  if (fields.includes(props.fieldKey)) return true;
  if (props.fieldKey === "gmIncludeBusyDetails" && fields.includes("gmIncludeBusyTitles")) {
    return true;
  }
  return false;
});

function toggle(): void {
  if (!isToolNodeField.value) return;
  const node = workflowStore.nodes.find((n) => n.id === props.nodeId);
  if (!node) return;
  const current: string[] = node.data.agentProvidedFields ?? [];
  const keysToRemove = new Set(
    props.fieldKey === "gmIncludeBusyDetails"
      ? ["gmIncludeBusyDetails", "gmIncludeBusyTitles"]
      : [props.fieldKey],
  );
  const updated = isAgentProvided.value
    ? current.filter((f) => !keysToRemove.has(f))
    : [...current.filter((f) => !keysToRemove.has(f)), props.fieldKey];
  workflowStore.updateNode(props.nodeId, { agentProvidedFields: updated });
}
</script>

<template>
  <Button
    v-if="isToolNodeField"
    variant="outline"
    size="icon"
    class="h-8 min-h-0 w-8 min-w-0 shrink-0 rounded-md p-0 md:h-8 md:min-h-0 md:w-8 md:min-w-0"
    :class="
      isAgentProvided
        ? 'text-violet-500 hover:text-violet-400'
        : 'text-muted-foreground hover:text-foreground'
    "
    :title="
      isAgentProvided
        ? 'Agent fills this — click to use fixed value'
        : 'Click to let agent fill this at runtime'
    "
    type="button"
    @click="toggle"
  >
    <Bot class="h-3.5 w-3.5" />
  </Button>
</template>
