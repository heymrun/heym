<script setup lang="ts">
import { computed } from "vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import type { HeymChatFieldKey } from "@/lib/heymOperations";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

type HeymChatToggleKey = "heymChatNoHistory" | "heymChatContinue" | "heymChatFireAndForget";

interface HeymChatToggle {
  key: HeymChatToggleKey;
  label: string;
  help: string;
}

const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  updateNodeData,
  heymExpressionFieldCount,
  heymExpressionFieldIndex,
  setHeymExpressionInputRef,
  handleHeymExpressionFieldNavigate,
  onHeymRegisterExpressionFieldIndex,
} = usePropertiesPanelContext();

const toggles: HeymChatToggle[] = [
  {
    key: "heymChatNoHistory",
    label: "Don't save chat history",
    help: "Runs in a temporary conversation that is deleted when the turn ends. Off: the "
      + "conversation is saved in the Chat tab.",
  },
  {
    key: "heymChatContinue",
    label: "Continue a conversation",
    help: "Writes into an existing conversation. The node fails if it was deleted.",
  },
  {
    key: "heymChatFireAndForget",
    label: "Don't wait for the reply",
    help: "Moves on to the next node right away; the turn finishes in the background.",
  },
];

const noHistory = computed((): boolean => selectedNode.value?.data.heymChatNoHistory === true);
const continuing = computed((): boolean => selectedNode.value?.data.heymChatContinue === true);

function isOn(key: HeymChatToggleKey): boolean {
  return selectedNode.value?.data[key] === true;
}

/** A continued conversation is saved, so these two cannot both be on. */
function isDisabled(key: HeymChatToggleKey): boolean {
  if (key === "heymChatNoHistory") return continuing.value;
  if (key === "heymChatContinue") return noHistory.value;
  return false;
}

function onToggle(key: HeymChatToggleKey, event: Event): void {
  updateNodeData(key, (event.target as HTMLInputElement).checked);
}

function expressionProps(key: HeymChatFieldKey, label: string): Record<string, unknown> {
  return {
    nodes: workflowStore.nodes,
    nodeResults: workflowStore.nodeResults,
    edges: workflowStore.edges,
    currentNodeId: selectedNode.value?.id,
    dialogNodeLabel: selectedNodeEvaluateDialogLabel.value,
    dialogKeyLabel: label,
    fieldKey: key,
    navigationEnabled: heymExpressionFieldCount.value > 1,
    navigationIndex: heymExpressionFieldIndex(key),
    navigationTotal: heymExpressionFieldCount.value,
  };
}
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="heym-field-heymChatMessage"
    >
      <Label>Message</Label>
      <ExpressionInput
        :ref="(el: unknown) => setHeymExpressionInputRef('heymChatMessage', el)"
        v-bind="expressionProps('heymChatMessage', 'Message')"
        :model-value="selectedNode.data.heymChatMessage || ''"
        placeholder="Summarize today's failed runs: $input.date"
        :rows="3"
        @navigate="handleHeymExpressionFieldNavigate"
        @register-field-index="onHeymRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('heymChatMessage', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Uses the Chat default model of whoever runs the workflow, and the owner's on scheduled
        and triggered runs. The assistant can use its tools and build workflows.
      </p>
    </div>

    <div
      v-for="toggle in toggles"
      :key="toggle.key"
      class="space-y-1"
      :data-testid="`heym-toggle-${toggle.key}`"
    >
      <div class="flex items-center gap-2">
        <input
          :id="`heym-${toggle.key}`"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background disabled:opacity-50"
          :checked="isOn(toggle.key)"
          :disabled="isDisabled(toggle.key)"
          @change="onToggle(toggle.key, $event)"
        >
        <Label
          :for="`heym-${toggle.key}`"
          class="text-sm font-normal"
          :class="{ 'text-muted-foreground': isDisabled(toggle.key) }"
        >
          {{ toggle.label }}
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        {{ toggle.help }}
      </p>
    </div>

    <div
      v-if="continuing"
      class="space-y-2"
      data-testid="heym-field-heymChatConversationId"
    >
      <Label>Conversation ID</Label>
      <ExpressionInput
        :ref="(el: unknown) => setHeymExpressionInputRef('heymChatConversationId', el)"
        v-bind="expressionProps('heymChatConversationId', 'Conversation ID')"
        :model-value="selectedNode.data.heymChatConversationId || ''"
        placeholder="$previousChat.conversation_id"
        :rows="1"
        @navigate="handleHeymExpressionFieldNavigate"
        @register-field-index="onHeymRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('heymChatConversationId', $event)"
      />
    </div>

    <p class="text-xs text-muted-foreground">
      OUT fires with the reply. QUESTION fires when the assistant asks a clarifying question or
      needs a credential; answer it later with Continue a conversation and the same
      <code>conversation_id</code>.
    </p>
  </template>
</template>
