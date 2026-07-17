<script setup lang="ts">
import { computed, ref, watch } from "vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { validateOutputContract } from "@/lib/jsonSchemaValidation";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, updateNodeData } = usePropertiesPanelContext();
const outputContractDraft = ref("");

watch(
  () => selectedNode.value?.data.outputContract,
  (value) => {
    if (value !== outputContractDraft.value) {
      outputContractDraft.value = value || "";
    }
  },
  { immediate: true },
);

const schemaError = computed<string | null>(() => {
  const value = outputContractDraft.value.trim();
  if (!value) {
    return null;
  }
  try {
    return validateOutputContract(value);
  } catch {
    return "Contract schema could not be validated.";
  }
});

function updateOutputContract(value: string): void {
  outputContractDraft.value = value;
  if (!value.trim() || !validateOutputContract(value)) {
    updateNodeData("outputContract", value);
  }
}
</script>

<template>
  <div
    v-if="selectedNode"
    class="mt-4 border-t border-border pt-3 space-y-2"
  >
    <Label>Output contract (JSON Schema)</Label>
    <Textarea
      :model-value="outputContractDraft"
      placeholder="{ &quot;type&quot;: &quot;object&quot;, &quot;required&quot;: [&quot;result&quot;] }"
      :rows="4"
      class="font-mono text-xs"
      @update:model-value="updateOutputContract($event)"
    />
    <p class="text-xs text-muted-foreground">
      The node fails with a contract error when its output does not match this schema.
    </p>
    <p
      v-if="schemaError"
      class="text-xs text-destructive"
    >
      {{ schemaError }}
    </p>
  </div>
</template>
