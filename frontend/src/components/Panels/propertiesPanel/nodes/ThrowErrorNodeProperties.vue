<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  throwErrorMessageInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  httpStatusCodeOptions,
  getExpressionWarning,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>HTTP Status Code</Label>
      <Select
        :model-value="selectedNode.data.httpStatusCode?.toString() || ''"
        :options="httpStatusCodeOptions"
        @update:model-value="updateNodeData('httpStatusCode', $event ? parseInt($event) : undefined)"
      />
      <p class="text-xs text-muted-foreground">
        HTTP status code to return when this error is thrown
      </p>
    </div>

    <div class="space-y-2">
      <Label>Error Message</Label>
      <ExpressionInput
        ref="throwErrorMessageInputRef"
        :model-value="selectedNode.data.errorMessage || ''"
        :placeholder="`${exampleRef} or error message`"
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Error message"
        field-key="errorMessage"
        @update:model-value="updateNodeData('errorMessage', $event)"
      />
      <p
        v-if="getExpressionWarning(selectedNode.data.errorMessage || '')"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        {{ getExpressionWarning(selectedNode.data.errorMessage || '') }}
      </p>
      <p
        v-if="!selectedNode.data.errorMessage && !selectedNode.data.httpStatusCode"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Error message or HTTP status code is required
      </p>
      <p
        v-else
        class="text-xs text-muted-foreground"
      >
        Message to include in the error response
      </p>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Behavior</Label>
      <p class="text-xs text-muted-foreground">
        When this node executes, workflow execution will stop and return an error response with the specified
        HTTP status code and message.
      </p>
    </div>
  </template>
</template>
