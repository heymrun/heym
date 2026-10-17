<script setup lang="ts">
import { computed, nextTick, ref } from "vue";

import type { SlackButton, SlackFormField } from "@/types/workflow";

import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";
import SlackButtonsEditor from "./SlackButtonsEditor.vue";
import SlackFormFieldsEditor from "./SlackFormFieldsEditor.vue";
import {
  SLACK_DEFAULT_OPERATION,
  SLACK_WAITING_OPERATIONS,
  slackFieldsFor,
  slackInteractionsPath,
  slackOperationGroups,
  slackOutcomeOptions,
  type SlackFieldSpec,
} from "./slackOperations";

interface ExpandableField {
  openExpandDialog(localIndex?: number): void;
  closeExpandDialog(): void;
}

const {
  workflowStore,
  slackMessageInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  slackCredentialOptions,
  slackCredentials,
  updateNodeData,
} = usePropertiesPanelContext();

const fieldRefs = new Map<number, ExpandableField>();
const currentFieldIndex = ref(0);

const credentialId = computed((): string => String(selectedNode.value?.data.credentialId || ""));
const isBot = computed((): boolean => {
  const match = slackCredentials.value.find((credential) => credential.id === credentialId.value);
  // A credential shared by the workflow's owner is not listed; its saved operation tells.
  return match ? match.type === "slack_bot" : !!selectedNode.value?.data.slackOperation;
});
const operation = computed(
  (): string => String(selectedNode.value?.data.slackOperation || SLACK_DEFAULT_OPERATION),
);
const fields = computed((): SlackFieldSpec[] =>
  isBot.value
    ? slackFieldsFor(operation.value)
    : [{ key: "message", label: "Message", placeholder: exampleRef.value, rows: 3 }],
);
const waits = computed((): boolean => isBot.value && SLACK_WAITING_OPERATIONS.has(operation.value));
const interactivityUrl = computed((): string =>
  credentialId.value ? `${window.location.origin}${slackInteractionsPath(credentialId.value)}` : "",
);
const buttons = computed((): SlackButton[] => selectedNode.value?.data.slackButtons ?? []);
const formFields = computed((): SlackFormField[] => selectedNode.value?.data.slackFormFields ?? []);

function fieldValue(key: string): string {
  const data = selectedNode.value?.data as Record<string, unknown> | undefined;
  return String(data?.[key] ?? "");
}

// The canvas double-click opens slackMessageInputRef, so it points at the first field.
function bindField(index: number, el: unknown): void {
  const field = (el as ExpandableField | null) ?? null;
  if (field) fieldRefs.set(index, field);
  else fieldRefs.delete(index);
  if (index === 0) slackMessageInputRef.value = field;
}

function navigate(direction: "prev" | "next"): void {
  const next = currentFieldIndex.value + (direction === "prev" ? -1 : 1);
  if (next < 0 || next >= fields.value.length) return;
  fieldRefs.get(currentFieldIndex.value)?.closeExpandDialog();
  currentFieldIndex.value = next;
  void nextTick(() => fieldRefs.get(next)?.openExpandDialog());
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="slackCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p class="text-xs text-muted-foreground">
        A Slack Webhook sends one message. A Slack Bot token adds DMs, threads, approvals, buttons and forms.
        <a
          v-if="!selectedNode.data.credentialId"
          href="/?tab=credentials"
          class="text-primary hover:underline"
          @click.prevent="$router.push('/?tab=credentials')"
        >Add credentials</a>
      </p>
    </div>

    <div
      v-if="isBot"
      class="space-y-2"
      data-testid="slack-operation-field"
    >
      <Label>Operation</Label>
      <SearchableSelect
        :model-value="operation"
        :groups="slackOperationGroups"
        search-placeholder="Search Slack operations..."
        @update:model-value="updateNodeData('slackOperation', $event)"
      />
    </div>

    <div
      v-for="(field, index) in fields"
      :key="`${operation}-${field.key}`"
      class="space-y-2"
    >
      <Label>{{ field.label }}</Label>
      <ExpressionInput
        :ref="(el) => bindField(index, el)"
        :model-value="fieldValue(field.key)"
        :placeholder="field.placeholder"
        :rows="field.rows ?? 1"
        :single-line="!field.rows"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :navigation-enabled="fields.length > 1"
        :navigation-index="index"
        :navigation-total="fields.length"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        :dialog-key-label="field.label"
        :field-key="field.key"
        @update:model-value="updateNodeData(field.key, $event)"
        @navigate="navigate"
        @register-field-index="currentFieldIndex = $event"
      />
      <p
        v-if="field.hint"
        class="text-xs text-muted-foreground"
      >
        {{ field.hint }}
      </p>
    </div>

    <template v-if="isBot">
      <div
        v-if="operation === 'postOutcome'"
        class="space-y-2"
      >
        <Label>Outcome</Label>
        <Select
          :model-value="selectedNode.data.slackOutcomeStatus || 'success'"
          :options="slackOutcomeOptions"
          @update:model-value="updateNodeData('slackOutcomeStatus', $event)"
        />
      </div>
      <label
        v-if="operation === 'replyInThread'"
        class="flex items-center gap-2 text-sm"
      >
        <input
          type="checkbox"
          :checked="!!selectedNode.data.slackBroadcast"
          @change="updateNodeData('slackBroadcast', ($event.target as HTMLInputElement).checked)"
        >
        <span>Also send to the channel</span>
      </label>
      <SlackButtonsEditor
        v-if="operation === 'sendButtons'"
        :buttons="buttons"
        @update="updateNodeData('slackButtons', $event)"
      />
      <SlackFormFieldsEditor
        v-if="operation === 'sendForm'"
        :fields="formFields"
        @update="updateNodeData('slackFormFields', $event)"
      />
      <div
        v-if="waits"
        class="space-y-1 rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground"
      >
        <p>
          The run waits here until someone answers in Slack. The same request shows in the Heym inbox,
          so it can be decided there too.
        </p>
        <p v-if="interactivityUrl">
          Slack app → Interactivity → Request URL:
          <code class="break-all rounded bg-background px-1">{{ interactivityUrl }}</code>
        </p>
      </div>
    </template>
  </template>
</template>
