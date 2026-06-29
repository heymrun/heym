<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  telegramChatIdInputRef,
  telegramMessageInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  telegramCredentialOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Telegram Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="telegramCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-muted-foreground"
      >
        <a
          href="/?tab=credentials"
          class="text-primary hover:underline"
          @click.prevent="$router.push('/?tab=credentials')"
        >Add credentials</a> in Dashboard
      </p>
    </div>

    <div class="space-y-2">
      <Label>Chat ID</Label>
      <ExpressionInput
        ref="telegramChatIdInputRef"
        :model-value="selectedNode.data.chatId || ''"
        placeholder="$telegramTrigger.message.chat.id"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Chat ID"
        field-key="chatId"
        @update:model-value="updateNodeData('chatId', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Usually comes from the trigger: $telegramTrigger.message.chat.id
      </p>
    </div>

    <div class="space-y-2">
      <Label>Message</Label>
      <ExpressionInput
        ref="telegramMessageInputRef"
        :model-value="selectedNode.data.message || ''"
        :placeholder="exampleRef"
        :rows="3"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Message"
        field-key="message"
        @update:model-value="updateNodeData('message', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Use $ expressions like {{ exampleRef }} or $telegramTrigger.message.text
      </p>
    </div>
  </template>
</template>
