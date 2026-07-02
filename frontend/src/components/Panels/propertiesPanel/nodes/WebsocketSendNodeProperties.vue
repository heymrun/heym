<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  websocketSendUrlInputRef,
  websocketSendHeadersInputRef,
  websocketSendMessageInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>WebSocket URL</Label>
        <ExpressionInput
          ref="websocketSendUrlInputRef"
          :model-value="selectedNode.data.websocketUrl || ''"
          placeholder="wss://example.com/socket"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="WebSocket URL"
          field-key="websocketUrl"
          @update:model-value="updateNodeData('websocketUrl', $event)"
        />
        <p
          v-if="!selectedNode.data.websocketUrl || selectedNode.data.websocketUrl.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          URL is required
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Supports expressions, so you can choose the destination socket from upstream data or variables.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Headers (JSON object)</Label>
        <ExpressionInput
          ref="websocketSendHeadersInputRef"
          :model-value="selectedNode.data.websocketHeaders || ''"
          placeholder="{&quot;Authorization&quot;: &quot;Bearer $vars.socketToken&quot;}"
          :rows="3"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="WebSocket headers"
          field-key="websocketHeaders"
          @update:model-value="updateNodeData('websocketHeaders', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Optional headers for the outbound handshake. Use a JSON object string or a full-expression object.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Subprotocols</Label>
        <Input
          :model-value="selectedNode.data.websocketSubprotocols || ''"
          placeholder="json, graphql-ws"
          @update:model-value="updateNodeData('websocketSubprotocols', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Optional comma-separated subprotocol list.
        </p>
      </div>

      <div class="space-y-2">
        <Label>Message</Label>
        <ExpressionInput
          ref="websocketSendMessageInputRef"
          :model-value="selectedNode.data.websocketMessage || ''"
          placeholder="$input"
          :rows="4"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="WebSocket message"
          field-key="websocketMessage"
          @update:model-value="updateNodeData('websocketMessage', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Full expressions keep objects and arrays as JSON before sending. Plain strings are sent as text frames.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-muted-foreground">Output</Label>
        <div class="text-xs font-mono space-y-1 text-muted-foreground">
          <div>${{ selectedNode.data.label }}.status - "sent" on success</div>
          <div>${{ selectedNode.data.label }}.url - resolved socket URL</div>
          <div>${{ selectedNode.data.label }}.message_type - text / json / binary</div>
          <div>${{ selectedNode.data.label }}.size_bytes - payload size in bytes</div>
          <div>${{ selectedNode.data.label }}.subprotocol - negotiated subprotocol</div>
          <div>${{ selectedNode.data.label }}.sent_at - ISO timestamp</div>
        </div>
      </div>
    </div>
  </template>
</template>
