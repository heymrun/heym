<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { AlertTriangle, Check } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import {
  OUTLOOK_AFTER_ACTION_OPTIONS,
  OUTLOOK_MAILBOX_OPTIONS,
  outlookAfterAction,
  outlookMailbox,
  parseOutlookAliases,
  toggleOutlookAlias,
} from "@/lib/outlookTriggerConfig";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";
import { useOutlookTriggerOptions } from "./useOutlookTriggerOptions";

const { selectedNode, isWorkflowOwner, updateNodeData } = usePropertiesPanelContext();

const credentialId = computed<string>(() => String(selectedNode.value?.data.credentialId ?? ""));
const { credentials, folders, addresses, loadingAccount, accountError } =
  useOutlookTriggerOptions(credentialId);

const credentialOptions = computed(() => {
  const options = [
    { value: "", label: "Select Outlook credential..." },
    ...credentials.value.map((item) => ({
      value: item.id,
      label: item.is_shared ? `${item.name} - shared` : item.name,
    })),
  ];
  if (credentialId.value && !options.some((option) => option.value === credentialId.value)) {
    options.push({ value: credentialId.value, label: "Shared Outlook credential (from owner)" });
  }
  return options;
});

const mailbox = computed(() => outlookMailbox(selectedNode.value?.data.outlookMailbox));
const isExchangeServer = computed(
  (): boolean =>
    credentials.value.find((item) => item.id === credentialId.value)?.public_fields?.auth_mode === "ews",
);
// Exchange Server has no Focused Inbox; a saved choice stays listed so it can be changed.
const mailboxOptions = computed(() =>
  OUTLOOK_MAILBOX_OPTIONS.filter(
    (option) =>
      !isExchangeServer.value || !["focused", "other"].includes(option.value) || option.value === mailbox.value,
  ),
);
const afterAction = computed(() => outlookAfterAction(selectedNode.value?.data.outlookAfterAction));
const aliases = computed<string[]>(() => parseOutlookAliases(selectedNode.value?.data.outlookAliases));
const flaggedOnly = computed(() => selectedNode.value?.data.outlookFlaggedOnly === true);

const folderOptions = computed(() => {
  const options = folders.value.map((folder) => ({ value: folder.id, label: folder.path }));
  const storedId = String(selectedNode.value?.data.outlookFolderId ?? "");
  if (storedId && !folders.value.some((folder) => folder.id === storedId)) {
    options.push({ value: storedId, label: String(selectedNode.value?.data.outlookFolderName || storedId) });
  }
  return options;
});

const aliasText = ref("");
watch(
  aliases,
  (current) => {
    if (parseOutlookAliases(aliasText.value).join(",") !== current.join(",")) {
      aliasText.value = current.join(", ");
    }
  },
  { immediate: true },
);

function setFolder(folderId: string | undefined): void {
  const found = folders.value.find((folder) => folder.id === folderId);
  updateNodeData("outlookFolderId", folderId ?? "");
  updateNodeData("outlookFolderName", found?.path ?? "");
}

function setAliasText(text: string): void {
  aliasText.value = text;
  updateNodeData("outlookAliases", parseOutlookAliases(text));
}

function toggleAddress(address: string): void {
  updateNodeData("outlookAliases", toggleOutlookAlias(aliases.value, address));
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div
        class="space-y-2"
        data-testid="outlook-credential-field"
      >
        <Label>Outlook Credential</Label>
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
          No Outlook credential set: polling is off
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
        data-testid="outlook-mailbox-field"
      >
        <Label>Mailbox</Label>
        <Select
          :model-value="mailbox"
          :options="mailboxOptions"
          @update:model-value="updateNodeData('outlookMailbox', $event || 'inbox')"
        />
        <SearchableSelect
          v-if="mailbox === 'folder'"
          :model-value="String(selectedNode.data.outlookFolderId ?? '') || undefined"
          :options="folderOptions"
          :placeholder="loadingAccount ? 'Loading folders...' : 'Select a folder...'"
          search-placeholder="Search folders..."
          empty-text="No folders found"
          data-testid="outlook-folder-field"
          @update:model-value="setFolder"
        />
        <p class="text-xs text-muted-foreground">
          A run starts when an email is received here. Drafts, Junk Email and Deleted Items never
          start runs.
        </p>
        <p
          v-if="isExchangeServer && (mailbox === 'focused' || mailbox === 'other')"
          class="text-xs text-amber-500"
        >
          Exchange Server has no Focused Inbox; choose another mailbox.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="outlook-flagged-field"
      >
        <div class="flex items-center gap-2">
          <input
            id="outlook-flagged-only"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="flaggedOnly"
            @change="updateNodeData('outlookFlaggedOnly', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="outlook-flagged-only"
            class="text-sm font-normal"
          >
            Flagged email only
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Only flagged email in this mailbox starts a run, at the next poll after you flag it. Older
          email counts too. Unflag and flag it again to start another run.
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="outlook-aliases-field"
      >
        <Label for="outlook-aliases">Only email sent to (optional)</Label>
        <Input
          id="outlook-aliases"
          :model-value="aliasText"
          placeholder="sales@contoso.com, me+invoices@contoso.com"
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
              ? 'border-[hsl(var(--node-outlook))] bg-[hsl(var(--node-outlook)/0.1)] text-foreground'
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
          Checks To, Cc and delivery headers. Use it for a Microsoft 365 alias or a plus address.
          Empty means any address.
        </p>
      </div>

      <div class="space-y-2">
        <Label for="outlook-poll-interval">Poll Interval (Minutes)</Label>
        <Input
          id="outlook-poll-interval"
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
        data-testid="outlook-after-action-field"
      >
        <Label>After the run starts</Label>
        <Select
          :model-value="afterAction"
          :options="OUTLOOK_AFTER_ACTION_OPTIONS"
          @update:model-value="updateNodeData('outlookAfterAction', $event || 'none')"
        />
        <p class="text-xs text-muted-foreground">
          Applied to the email once its run has started, whatever the outcome. Deleted email stays
          recoverable in Deleted Items.
        </p>
      </div>

      <div class="space-y-2">
        <div class="flex items-center gap-2">
          <input
            id="outlook-download-attachments"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.outlookDownloadAttachments === true"
            @change="updateNodeData('outlookDownloadAttachments', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="outlook-download-attachments"
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
          data-testid="outlook-output-fields"
        >
          <div>${{ selectedNode.data.label }}.email.subject: decoded subject</div>
          <div>${{ selectedNode.data.label }}.email.from: raw from header</div>
          <div>${{ selectedNode.data.label }}.email.text: plain-text body</div>
          <div>${{ selectedNode.data.label }}.email.html: HTML body</div>
          <div>${{ selectedNode.data.label }}.email.id: Outlook message id</div>
          <div>${{ selectedNode.data.label }}.email.conversationId: Outlook conversation id</div>
          <div>${{ selectedNode.data.label }}.email.flagged: whether the email is flagged</div>
          <div>${{ selectedNode.data.label }}.email.webLink: opens the email in Outlook</div>
          <div>${{ selectedNode.data.label }}.attachments: each attachment, with its Drive link when saved</div>
          <div>${{ selectedNode.data.label }}.file_ids: Drive ids of the saved attachments</div>
        </div>
      </div>
    </div>
  </template>
</template>
