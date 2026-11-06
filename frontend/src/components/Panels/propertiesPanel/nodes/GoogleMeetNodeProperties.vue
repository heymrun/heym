<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import axios from "axios";

import type { CredentialListItem } from "@/types/credential";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { GOOGLE_MEET_OPERATIONS } from "@/lib/googleMeetFields";
import { credentialsApi } from "@/services/api";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  selectedNode, workflowStore, isWorkflowOwner, updateNodeData,
  selectedNodeEvaluateDialogLabel, googleMeetExpressionFields,
} = usePropertiesPanelContext();
const { fields, register, navigate, registerIndex } = googleMeetExpressionFields;
const credentials = ref<CredentialListItem[]>([]);
const credentialError = ref("");
const credentialOptions = computed(() => {
  const options = [
    { value: "", label: "Select Google Meet credential..." },
    ...credentials.value.map((credential) => ({
      value: credential.id,
      label: credential.is_shared ? `${credential.name} - shared` : credential.name,
    })),
  ];
  const selected = selectedNode.value?.data.credentialId;
  if (selected && !options.some((option) => option.value === selected)) {
    options.push({ value: selected, label: "Google Meet credential (from owner)" });
  }
  return options;
});

onMounted(async (): Promise<void> => {
  try {
    credentials.value = await credentialsApi.listByType("google_meet");
  } catch (error: unknown) {
    credentialError.value = axios.isAxiosError(error)
      ? "Could not load Google Meet credentials. Reopen the panel to retry."
      : "Could not load credentials.";
  }
});
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Google Meet Credential</Label>
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
        Connect your Google account in Dashboard → Credentials → Google Meet (OAuth2).
      </p>
    </div>
    <div
      class="space-y-2"
      data-testid="gm-operation-field"
    >
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.gmOperation || 'read'"
        :options="GOOGLE_MEET_OPERATIONS"
        @update:model-value="updateNodeData('gmOperation', $event)"
      />
    </div>
    <div
      v-for="(field, index) in fields"
      :key="field.key"
      class="space-y-2"
      :data-testid="`gm-field-${field.key}`"
    >
      <Label :for="`gm-${field.key}`">{{ field.label }}</Label>
      <ExpressionInput
        :id="`gm-${field.key}`"
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
    <p
      v-if="selectedNode.data.gmOperation === 'read'"
      class="text-xs text-muted-foreground"
      data-testid="gm-availability-help"
    >
      Returns available_slots and busy_slots from now until next month's first day.
      Override the dates for a shorter range or up to 60 days. Availability includes nights
      and weekends; it reflects calendar conflicts, not working hours.
    </p>
    <p
      v-else-if="selectedNode.data.gmOperation === 'update'"
      class="text-xs text-muted-foreground"
    >
      Empty fields keep their existing values. Supply both times to reschedule.
      Existing Meet details are preserved. Guests receive update emails.
    </p>
    <p
      v-else-if="selectedNode.data.gmOperation === 'create'"
      class="text-xs text-muted-foreground"
    >
      Creates a Google Calendar event with a Meet link from the connected account.
      Use $input.email to invite a visitor who selected an available time.
    </p>
    <p
      v-else
      class="text-xs text-muted-foreground"
    >
      Guests receive cancellation emails.
    </p>
  </template>
</template>
