<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { AlertTriangle, Check } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import {
  GMAIL_AFTER_ACTION_OPTIONS,
  GMAIL_MAILBOX_OPTIONS,
  gmailAfterAction,
  gmailMailbox,
  parseGmailAliases,
  toggleGmailAlias,
} from "@/lib/gmailTriggerConfig";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";
import { useGmailTriggerOptions } from "./useGmailTriggerOptions";

const { selectedNode, isWorkflowOwner, updateNodeData } = usePropertiesPanelContext();

const credentialId = computed<string>(() => String(selectedNode.value?.data.credentialId ?? ""));
const { credentials, labels, addresses, loadingAccount, accountError } =
  useGmailTriggerOptions(credentialId);

const credentialOptions = computed(() => {
  const options = [
    { value: "", label: "Select Gmail credential..." },
    ...credentials.value.map((item) => ({
      value: item.id,
      label: item.is_shared ? `${item.name} - shared` : item.name,
    })),
  ];
  if (credentialId.value && !options.some((option) => option.value === credentialId.value)) {
    options.push({ value: credentialId.value, label: "Shared Gmail credential (from owner)" });
  }
  return options;
});

const mailbox = computed(() => gmailMailbox(selectedNode.value?.data.gmailMailbox));
const afterAction = computed(() => gmailAfterAction(selectedNode.value?.data.gmailAfterAction));
const aliases = computed<string[]>(() => parseGmailAliases(selectedNode.value?.data.gmailAliases));

const labelOptions = computed(() => {
  const options = [
    { value: "", label: loadingAccount.value ? "Loading labels..." : "Select a label..." },
    ...labels.value.map((label) => ({ value: label.id, label: label.name })),
  ];
  const storedId = String(selectedNode.value?.data.gmailLabelId ?? "");
  if (storedId && !labels.value.some((label) => label.id === storedId)) {
    options.push({ value: storedId, label: String(selectedNode.value?.data.gmailLabelName || storedId) });
  }
  return options;
});

const aliasText = ref("");
watch(
  aliases,
  (current) => {
    if (parseGmailAliases(aliasText.value).join(",") !== current.join(",")) {
      aliasText.value = current.join(", ");
    }
  },
  { immediate: true },
);

function setLabel(labelId: string | undefined): void {
  const found = labels.value.find((label) => label.id === labelId);
  updateNodeData("gmailLabelId", labelId ?? "");
  updateNodeData("gmailLabelName", found?.name ?? "");
}

function setAliasText(text: string): void {
  aliasText.value = text;
  updateNodeData("gmailAliases", parseGmailAliases(text));
}

function toggleAddress(address: string): void {
  updateNodeData("gmailAliases", toggleGmailAlias(aliases.value, address));
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div
        class="space-y-2"
        data-testid="gmail-credential-field"
      >
        <Label>Gmail Credential</Label>
        <Select
          :model-value="credentialId"
          :options="credentialOptions"
          :disabled="!isWorkflowOwner"
          @update:model-value="updateNodeData('credentialId', $event ?? '')"
        />
        <p
          v-if="!credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No Gmail credential set: polling is off
        </p>
        <p
          v-else-if="accountError"
          class="text-xs text-amber-500"
        >
          {{ accountError }}
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gmail-mailbox-field"
      >
        <Label>Mailbox</Label>
        <Select
          :model-value="mailbox"
          :options="GMAIL_MAILBOX_OPTIONS"
          @update:model-value="updateNodeData('gmailMailbox', $event || 'inbox')"
        />
        <Select
          v-if="mailbox === 'label'"
          :model-value="String(selectedNode.data.gmailLabelId ?? '')"
          :options="labelOptions"
          data-testid="gmail-label-field"
          @update:model-value="setLabel"
        />
        <p class="text-xs text-muted-foreground">
          A run starts when an email arrives here, or is moved or labelled into it later. Drafts,
          Spam and Trash never start runs.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gmail-aliases-field"
      >
        <Label for="gmail-aliases">Only email sent to (optional)</Label>
        <Input
          id="gmail-aliases"
          :model-value="aliasText"
          placeholder="sales@example.com, me+invoices@gmail.com"
          @update:model-value="setAliasText(String($event ?? ''))"
        />
        <div
          v-if="addresses.length"
          class="flex flex-wrap gap-1.5"
        >
          <button
            v-for="address in addresses"
            :key="address.email"
            type="button"
            class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors"
            :class="aliases.includes(address.email.toLowerCase())
              ? 'border-[hsl(var(--node-gmail))] bg-[hsl(var(--node-gmail)/0.1)] text-foreground'
              : 'text-muted-foreground hover:text-foreground'"
            @click="toggleAddress(address.email)"
          >
            <Check
              v-if="aliases.includes(address.email.toLowerCase())"
              class="h-3 w-3"
            />
            {{ address.email }}
          </button>
        </div>
        <p class="text-xs text-muted-foreground">
          Checks To, Cc and delivery headers. Use it for a Send mail as alias, a plus address or a
          Workspace alias. Empty means any address.
        </p>
      </div>

      <div class="space-y-2">
        <Label for="gmail-poll-interval">Poll Interval (Minutes)</Label>
        <Input
          id="gmail-poll-interval"
          :model-value="String(selectedNode.data.pollIntervalMinutes ?? 1)"
          type="number"
          min="1"
          step="1"
          @update:model-value="updateNodeData('pollIntervalMinutes', Number.parseInt($event, 10) || 1)"
        />
        <p class="text-xs text-muted-foreground">
          The first poll records where the mailbox is; only newer email starts runs.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gmail-after-action-field"
      >
        <Label>After the run starts</Label>
        <Select
          :model-value="afterAction"
          :options="GMAIL_AFTER_ACTION_OPTIONS"
          @update:model-value="updateNodeData('gmailAfterAction', $event || 'none')"
        />
        <p class="text-xs text-muted-foreground">
          Applied to the email once its run has started, whatever the outcome. Trash keeps it for
          30 days.
        </p>
      </div>

      <div class="space-y-2">
        <div class="flex items-center gap-2">
          <input
            id="gmail-download-attachments"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.gmailDownloadAttachments === true"
            @change="updateNodeData('gmailDownloadAttachments', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="gmail-download-attachments"
            class="text-sm font-normal"
          >
            Download attachments to Drive
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Saves each attachment to your Heym Drive and adds its link to the output.
        </p>
      </div>

      <div class="space-y-2 pt-2 border-t">
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div
          class="text-xs text-muted-foreground space-y-1 font-mono"
          data-testid="gmail-output-fields"
        >
          <div>${{ selectedNode.data.label }}.email.subject: decoded subject</div>
          <div>${{ selectedNode.data.label }}.email.from: raw from header</div>
          <div>${{ selectedNode.data.label }}.email.text: plain-text body</div>
          <div>${{ selectedNode.data.label }}.email.html: HTML body</div>
          <div>${{ selectedNode.data.label }}.email.id: Gmail message id</div>
          <div>${{ selectedNode.data.label }}.email.threadId: Gmail thread id</div>
          <div>${{ selectedNode.data.label }}.email.labelIds: Gmail labels</div>
          <div>${{ selectedNode.data.label }}.attachments: each attachment, with its Drive link when saved</div>
          <div>${{ selectedNode.data.label }}.file_ids: Drive ids of the saved attachments</div>
        </div>
      </div>
    </div>
  </template>
</template>
