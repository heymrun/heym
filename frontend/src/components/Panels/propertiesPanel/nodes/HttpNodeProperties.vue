<script setup lang="ts">
import { ExternalLink } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  httpCurlInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  httpLastRequest,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>cURL Command</Label>
      <ExpressionInput
        ref="httpCurlInputRef"
        :model-value="selectedNode.data.curl || ''"
        placeholder="curl -X GET https://api.example.com"
        :rows="4"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="cURL command"
        dialog-title="Edit cURL Command"
        field-key="curl"
        @update:model-value="updateNodeData('curl', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Double-click to expand. Use $ expressions like {{ exampleRef }}
      </p>
    </div>

    <div
      v-if="httpLastRequest"
      class="space-y-2 pt-3 border-t"
    >
      <Label class="flex items-center gap-2">
        <ExternalLink class="w-3.5 h-3.5" />
        Last Request
      </Label>
      <div class="bg-muted/50 rounded-md p-3 space-y-3 text-xs font-mono max-h-80 overflow-y-auto">
        <div class="flex items-center gap-2">
          <span
            :class="[
              'px-1.5 py-0.5 rounded text-[10px] font-semibold shrink-0',
              httpLastRequest.status >= 200 && httpLastRequest.status < 300
                ? 'bg-green-500/20 text-green-600'
                : httpLastRequest.status >= 400
                  ? 'bg-red-500/20 text-red-600'
                  : 'bg-yellow-500/20 text-yellow-600'
            ]"
          >
            {{ httpLastRequest.status }}
          </span>
          <span class="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-600 text-[10px] font-semibold shrink-0">
            {{ httpLastRequest.method }}
          </span>
        </div>
        <div class="break-all text-foreground text-[11px]">
          {{ httpLastRequest.url || 'N/A' }}
        </div>
        <div
          v-if="httpLastRequest.requestHeaders && Object.keys(httpLastRequest.requestHeaders).length > 0"
          class="space-y-1.5"
        >
          <span class="text-muted-foreground text-[10px] uppercase font-semibold">Request Headers:</span>
          <div class="text-[11px] space-y-1 pl-2 border-l-2 border-primary/20">
            <div
              v-for="(value, key) in httpLastRequest.requestHeaders"
              :key="key"
              class="break-all"
            >
              <span class="text-primary font-medium">{{ key }}:</span>
              <span class="text-muted-foreground ml-1">{{ value }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>
