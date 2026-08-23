<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  htmlBodyInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  updateNodeData,
} = usePropertiesPanelContext();

function updateStatusCode(raw: string): void {
  const parsed = Number.parseInt(raw, 10);
  updateNodeData("statusCode", Number.isNaN(parsed) ? 200 : parsed);
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="grid grid-cols-2 gap-3">
      <div class="space-y-2">
        <Label for="html-status-code">Status Code</Label>
        <Input
          id="html-status-code"
          type="number"
          :model-value="String(selectedNode.data.statusCode ?? 200)"
          placeholder="200"
          @update:model-value="updateStatusCode(String($event))"
        />
      </div>
      <div class="space-y-2">
        <Label for="html-content-type">Content Type</Label>
        <Input
          id="html-content-type"
          :model-value="String(selectedNode.data.contentType ?? '')"
          placeholder="text/html; charset=utf-8"
          @update:model-value="updateNodeData('contentType', $event)"
        />
      </div>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label>HTML Body</Label>
      <ExpressionInput
        ref="htmlBodyInputRef"
        :model-value="selectedNode.data.html || ''"
        :placeholder="`<h1>${exampleRef}</h1>`"
        :rows="12"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="HTML body"
        field-key="html"
        @update:model-value="updateNodeData('html', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Use $ prefix to interpolate values: {{ exampleRef }}. When this is the only terminal node,
        the workflow's webhook responds with this page instead of JSON.
      </p>
    </div>
  </template>
</template>
