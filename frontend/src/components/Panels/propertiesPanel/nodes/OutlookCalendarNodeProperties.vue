<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import axios from "axios";

import type { CredentialListItem } from "@/types/credential";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import {
  OUTLOOK_CALENDAR_OPERATIONS,
  getOutlookCalendarOption,
  type OutlookCalendarOperation,
} from "@/lib/outlookCalendarFields";
import { credentialsApi } from "@/services/api";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  selectedNode, workflowStore, isWorkflowOwner, updateNodeData,
  selectedNodeEvaluateDialogLabel, outlookCalendarExpressionFields,
} = usePropertiesPanelContext();
const { fields, register, navigate, registerIndex } = outlookCalendarExpressionFields;

const operation = computed((): OutlookCalendarOperation => selectedNode.value?.data.ocOperation || "read");
const option = computed(() => getOutlookCalendarOption(operation.value));
const isOptionChecked = computed((): boolean => {
  const current = option.value;
  const data = selectedNode.value?.data;
  if (!current || !data) return false;
  const value = data[current.key];
  return value === undefined ? current.defaultValue : value === true;
});

const credentials = ref<CredentialListItem[]>([]);
const credentialError = ref("");
const credentialOptions = computed(() => {
  const options = [
    { value: "", label: "Select Outlook Calendar credential..." },
    ...credentials.value.map((credential) => ({
      value: credential.id,
      label: credential.is_shared ? `${credential.name} - shared` : credential.name,
    })),
  ];
  const selected = selectedNode.value?.data.credentialId;
  if (selected && !options.some((item) => item.value === selected)) {
    options.push({ value: selected, label: "Outlook Calendar credential (from owner)" });
  }
  return options;
});

onMounted(async (): Promise<void> => {
  try {
    credentials.value = await credentialsApi.listByType("outlook_calendar");
  } catch (error: unknown) {
    credentialError.value = axios.isAxiosError(error)
      ? "Could not load Outlook Calendar credentials. Reopen the panel to retry."
      : "Could not load credentials.";
  }
});
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Outlook Calendar Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="credentialOptions"
        :disabled="!isWorkflowOwner"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="credentialError"
        class="text-xs text-destructive"
      >
        {{ credentialError }}
      </p>
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-muted-foreground"
      >
        Connect your Microsoft account in Dashboard → Credentials → Outlook Calendar (OAuth2).
      </p>
    </div>
    <div
      class="space-y-2"
      data-testid="oc-operation-field"
    >
      <Label>Operation</Label>
      <Select
        :model-value="operation"
        :options="OUTLOOK_CALENDAR_OPERATIONS"
        @update:model-value="updateNodeData('ocOperation', $event)"
      />
    </div>
    <div
      v-for="(field, index) in fields"
      :key="field.key"
      class="space-y-2"
      :data-testid="`oc-field-${field.key}`"
    >
      <Label :for="`oc-${field.key}`">{{ field.label }}</Label>
      <ExpressionInput
        :id="`oc-${field.key}`"
        :ref="(instance) => register(field.key, instance)"
        :model-value="String(selectedNode.data[field.key] ?? '')"
        :placeholder="field.placeholder"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :field-key="field.key"
        :dialog-key-label="field.label"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        :navigation-enabled="fields.length > 1"
        :navigation-index="index"
        :navigation-total="fields.length"
        @navigate="navigate"
        @register-field-index="registerIndex"
        @update:model-value="updateNodeData(field.key, $event)"
      />
      <p
        v-if="field.help"
        class="text-xs text-muted-foreground"
      >
        {{ field.help }}
      </p>
    </div>
    <div
      v-if="option"
      class="space-y-2"
      :data-testid="`oc-option-${option.key}`"
    >
      <div class="flex items-center gap-2">
        <input
          :id="`oc-${option.key}`"
          type="checkbox"
          class="rounded border-border"
          :checked="isOptionChecked"
          @change="updateNodeData(option.key, ($event.target as HTMLInputElement).checked)"
        >
        <Label :for="`oc-${option.key}`">{{ option.label }}</Label>
        <AgentFieldToggle
          :node-id="selectedNode.id"
          :field-key="option.key"
        />
      </div>
      <p class="text-xs text-muted-foreground">
        {{ option.help }}
      </p>
    </div>
    <p
      v-if="operation === 'update'"
      class="text-xs text-muted-foreground"
    >
      Empty fields keep their values. Guests get update emails.
    </p>
    <p
      v-else-if="operation === 'create'"
      class="text-xs text-muted-foreground"
    >
      Guests get invitation emails.
    </p>
    <p
      v-else-if="operation === 'delete'"
      class="text-xs text-muted-foreground"
    >
      Guests get cancellation emails.
    </p>
  </template>
</template>
