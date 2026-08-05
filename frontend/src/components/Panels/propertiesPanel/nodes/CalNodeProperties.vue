<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import { AlertTriangle } from "lucide-vue-next";

import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import {
  getCalExpressionFields,
  type CalExpressionFieldKey,
} from "@/lib/calExpressionFields";

import { usePropertiesPanelContext } from "../usePropertiesPanelController";

interface ExpressionInputRef {
  openExpandDialog(localIndex?: number): void;
  closeExpandDialog(): void;
}

const {
  calApiCredentialOptions,
  calOperationGroups,
  selectedNode,
  updateNodeData,
  workflowStore,
} = usePropertiesPanelContext();

const calWebhookIdExpressionInputRef = ref<ExpressionInputRef | null>(null);
const calWebhookExpressionInputRef = ref<ExpressionInputRef | null>(null);
const currentFieldIndex = ref(0);

const expressionFields = computed(() =>
  getCalExpressionFields(String(selectedNode.value?.data.calOperation || "listWebhooks")),
);

function navBindings(key: CalExpressionFieldKey): {
  navigationEnabled: boolean;
  navigationIndex: number;
  navigationTotal: number;
  dialogNodeLabel: string;
  dialogKeyLabel: string;
} {
  const index = expressionFields.value.findIndex((field) => field.key === key);
  return {
    navigationEnabled: expressionFields.value.length > 1,
    navigationIndex: Math.max(index, 0),
    navigationTotal: expressionFields.value.length,
    dialogNodeLabel: String(selectedNode.value?.data.label || "Cal.com"),
    dialogKeyLabel: expressionFields.value[index]?.label || "",
  };
}

function closeDialogs(): void {
  calWebhookIdExpressionInputRef.value?.closeExpandDialog();
  calWebhookExpressionInputRef.value?.closeExpandDialog();
}

function openField(index: number): void {
  currentFieldIndex.value = index;
  const field = expressionFields.value[index]?.key;
  if (field === "calWebhookId") calWebhookIdExpressionInputRef.value?.openExpandDialog();
  if (field === "calWebhook") calWebhookExpressionInputRef.value?.openExpandDialog();
}

function handleNavigate(direction: "prev" | "next"): void {
  const nextIndex = currentFieldIndex.value + (direction === "prev" ? -1 : 1);
  if (nextIndex < 0 || nextIndex >= expressionFields.value.length) return;
  closeDialogs();
  nextTick(() => openField(nextIndex));
}

function registerFieldIndex(index: number): void {
  currentFieldIndex.value = index;
}
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="cal-credential-field"
    >
      <Label>Cal.com API Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="calApiCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Credential is required.
      </p>
    </div>

    <div
      class="space-y-2"
      data-testid="cal-operation-field"
    >
      <Label>Operation</Label>
      <SearchableSelect
        :model-value="selectedNode.data.calOperation || 'listWebhooks'"
        :groups="calOperationGroups"
        search-placeholder="Search Cal.com operations..."
        @update:model-value="updateNodeData('calOperation', $event)"
      />
    </div>

    <div
      v-if="selectedNode.data.calOperation === 'updateWebhook' || selectedNode.data.calOperation === 'deleteWebhook'"
      class="space-y-2"
      data-testid="cal-webhook-id-field"
    >
      <Label>Webhook ID *</Label>
      <ExpressionInput
        ref="calWebhookIdExpressionInputRef"
        :model-value="selectedNode.data.calWebhookId || ''"
        placeholder="Webhook ID or expression"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="calWebhookId"
        v-bind="navBindings('calWebhookId')"
        @update:model-value="updateNodeData('calWebhookId', $event)"
        @navigate="handleNavigate"
        @register-field-index="registerFieldIndex"
      />
    </div>

    <div
      v-if="selectedNode.data.calOperation === 'createWebhook' || selectedNode.data.calOperation === 'updateWebhook'"
      class="space-y-2"
      data-testid="cal-webhook-data-field"
    >
      <Label>Webhook Data *</Label>
      <ExpressionInput
        ref="calWebhookExpressionInputRef"
        :model-value="selectedNode.data.calWebhook || '{}'"
        placeholder="{ &quot;subscriberUrl&quot;: &quot;https://...&quot;, &quot;triggers&quot;: [&quot;BOOKING_CREATED&quot;], &quot;secret&quot;: &quot;...&quot; }"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="calWebhook"
        v-bind="navBindings('calWebhook')"
        @update:model-value="updateNodeData('calWebhook', $event)"
        @navigate="handleNavigate"
        @register-field-index="registerFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        JSON object sent to Cal.com API v2. Create typically needs subscriberUrl, triggers, secret,
        active, and version. Update accepts any supported webhook fields.
      </p>
    </div>
  </template>
</template>
