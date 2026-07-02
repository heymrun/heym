<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  discordMessageInputRef,
  discordUsernameInputRef,
  discordAvatarUrlInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  discordCredentialOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="discordCredentialOptions"
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
      <Label>Message</Label>
      <ExpressionInput
        ref="discordMessageInputRef"
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
        Use $ expressions like {{ exampleRef }} or $error.message
      </p>
    </div>

    <div class="space-y-2">
      <Label>Username (optional)</Label>
      <ExpressionInput
        ref="discordUsernameInputRef"
        :model-value="selectedNode.data.username || ''"
        placeholder="Heym Bot"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Username"
        field-key="username"
        @update:model-value="updateNodeData('username', $event)"
      />
    </div>

    <div class="space-y-2">
      <Label>Avatar URL (optional)</Label>
      <ExpressionInput
        ref="discordAvatarUrlInputRef"
        :model-value="selectedNode.data.avatarUrl || ''"
        placeholder="https://example.com/avatar.png"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Avatar URL"
        field-key="avatarUrl"
        @update:model-value="updateNodeData('avatarUrl', $event)"
      />
    </div>
  </template>
</template>
