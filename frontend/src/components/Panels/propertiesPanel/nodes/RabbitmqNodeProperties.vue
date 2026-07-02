<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  rabbitmqExchangeInputRef,
  rabbitmqRoutingKeyInputRef,
  rabbitmqQueueNameInputRef,
  rabbitmqMessageBodyInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  rabbitmqSendExpressionFieldCount,
  handleRabbitmqSendExpressionFieldNavigate,
  onRabbitmqSendRegisterExpressionFieldIndex,
  rabbitmqCredentialOptions,
  rabbitmqOperationOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="rabbitmqCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <div v-if="!selectedNode.data.credentialId">
        <p class="text-xs text-amber-500 flex items-center gap-1">
          <AlertTriangle class="h-3 w-3" />
          Credential is required.
        </p>
        <p class="text-xs text-muted-foreground mt-1">
          <a
            href="/?tab=credentials"
            class="text-primary hover:underline"
            @click.prevent="$router.push('/?tab=credentials')"
          >Add credentials</a> in Dashboard
        </p>
      </div>
    </div>

    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.rabbitmqOperation || ''"
        :options="rabbitmqOperationOptions"
        @update:model-value="updateNodeData('rabbitmqOperation', $event)"
      />
      <p
        v-if="!selectedNode.data.rabbitmqOperation"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Operation is required
      </p>
    </div>

    <template v-if="selectedNode.data.rabbitmqOperation === 'send'">
      <div class="space-y-2">
        <Label>Exchange Name</Label>
        <ExpressionInput
          ref="rabbitmqExchangeInputRef"
          :model-value="selectedNode.data.rabbitmqExchange || ''"
          placeholder="my-exchange (optional)"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="rabbitmqSendExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Exchange name"
          field-key="rabbitmqExchange"
          @navigate="handleRabbitmqSendExpressionFieldNavigate"
          @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('rabbitmqExchange', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Exchange name (leave empty for default exchange)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Routing Key</Label>
        <ExpressionInput
          ref="rabbitmqRoutingKeyInputRef"
          :model-value="selectedNode.data.rabbitmqRoutingKey || ''"
          placeholder="my-routing-key"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="rabbitmqSendExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Routing key"
          field-key="rabbitmqRoutingKey"
          @navigate="handleRabbitmqSendExpressionFieldNavigate"
          @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('rabbitmqRoutingKey', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Routing key for message delivery
        </p>
      </div>

      <div class="space-y-2">
        <Label>Queue Name</Label>
        <ExpressionInput
          ref="rabbitmqQueueNameInputRef"
          :model-value="selectedNode.data.rabbitmqQueueName || ''"
          placeholder="my-queue (used as routing key if empty)"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="rabbitmqSendExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Queue name"
          field-key="rabbitmqQueueName"
          @navigate="handleRabbitmqSendExpressionFieldNavigate"
          @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('rabbitmqQueueName', $event)"
        />
        <p
          v-if="!selectedNode.data.rabbitmqRoutingKey && !selectedNode.data.rabbitmqQueueName"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Routing key or queue name is required
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Queue name (optional, used as routing key if routing key is empty)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Message Body</Label>
        <ExpressionInput
          ref="rabbitmqMessageBodyInputRef"
          :model-value="selectedNode.data.rabbitmqMessageBody || ''"
          placeholder="$input or {&quot;key&quot;: &quot;value&quot;}"
          :rows="4"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="rabbitmqSendExpressionFieldCount > 1"
          :navigation-index="3"
          :navigation-total="rabbitmqSendExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Message body"
          field-key="rabbitmqMessageBody"
          @navigate="handleRabbitmqSendExpressionFieldNavigate"
          @register-field-index="onRabbitmqSendRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('rabbitmqMessageBody', $event)"
        />
        <p class="text-xs text-muted-foreground">
          JSON message body to send (supports expressions)
        </p>
      </div>

      <div class="space-y-2">
        <Label>Delay (ms)</Label>
        <Input
          type="number"
          :model-value="selectedNode.data.rabbitmqDelayMs || ''"
          placeholder="0 (optional)"
          min="0"
          @update:model-value="updateNodeData('rabbitmqDelayMs', $event ? parseInt($event as string) : undefined)"
        />
        <p class="text-xs text-muted-foreground">
          x-delay header in milliseconds for delayed message exchange plugin
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-muted-foreground">Output</Label>
        <div class="text-xs font-mono space-y-1 text-muted-foreground">
          <div>${{ selectedNode.data.label }}.status - "published" on success</div>
          <div>${{ selectedNode.data.label }}.message_id - Unique message ID</div>
          <div>${{ selectedNode.data.label }}.exchange - Exchange name used</div>
          <div>${{ selectedNode.data.label }}.routing_key - Routing key used</div>
          <div>${{ selectedNode.data.label }}.delay_ms - Delay value (if set)</div>
        </div>
      </div>
    </template>

    <template v-if="selectedNode.data.rabbitmqOperation === 'receive'">
      <div class="space-y-2">
        <Label>Queue Name <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="rabbitmqQueueNameInputRef"
          :model-value="selectedNode.data.rabbitmqQueueName || ''"
          placeholder="my-queue"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Queue name"
          field-key="rabbitmqQueueName"
          @update:model-value="updateNodeData('rabbitmqQueueName', $event)"
        />
        <p
          v-if="!selectedNode.data.rabbitmqQueueName || selectedNode.data.rabbitmqQueueName.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Queue name is required
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Queue to consume messages from
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-muted-foreground">Trigger Behavior</Label>
        <p class="text-xs text-muted-foreground">
          This node acts as a trigger. When a message arrives in the specified queue, the workflow will be
          executed automatically.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-muted-foreground">Output</Label>
        <div class="text-xs font-mono space-y-1 text-muted-foreground">
          <div>${{ selectedNode.data.label }}.body - Message body (parsed JSON)</div>
          <div>${{ selectedNode.data.label }}.headers - Message headers</div>
          <div>${{ selectedNode.data.label }}.message_id - Message ID</div>
          <div>${{ selectedNode.data.label }}.routing_key - Routing key</div>
          <div>${{ selectedNode.data.label }}.exchange - Exchange name</div>
          <div>${{ selectedNode.data.label }}.timestamp - Message timestamp</div>
        </div>
      </div>
    </template>
  </template>
</template>
