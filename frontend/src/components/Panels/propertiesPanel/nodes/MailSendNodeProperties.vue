<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { mailAccountProvider, type MailAccountProvider } from "@/lib/emailSendNodes";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";
import EmailMessageFields from "./EmailMessageFields.vue";
import { useMailSendAccount } from "./useMailSendAccount";

/** Gmail Send and Outlook Send: an account credential, an optional From, then Send Email's fields. */
const {
  workflowStore,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  sendEmailFromInputRef,
  sendEmailExpressionFieldCount,
  handleSendEmailExpressionFieldNavigate,
  onSendEmailRegisterExpressionFieldIndex,
  updateNodeData,
} = usePropertiesPanelContext();

const provider = computed<MailAccountProvider>(
  () => mailAccountProvider(selectedNode.value?.type) ?? "gmail",
);
const providerName = computed((): string => (provider.value === "gmail" ? "Gmail" : "Outlook"));
const credentialId = computed<string>(() => String(selectedNode.value?.data.credentialId ?? ""));
const fromAddress = computed<string>(() => String(selectedNode.value?.data.fromAddress ?? ""));
const { credentials, addresses, accountError } = useMailSendAccount(provider, credentialId);

const credentialOptions = computed(() => {
  const options = [
    { value: "", label: `Select ${providerName.value} credential...` },
    ...credentials.value.map((item) => ({
      value: item.id,
      label: item.is_shared ? `${item.name} - shared` : item.name,
    })),
  ];
  if (credentialId.value && !options.some((option) => option.value === credentialId.value)) {
    options.push({
      value: credentialId.value,
      label: `Shared ${providerName.value} credential (from owner)`,
    });
  }
  return options;
});

/** An Outlook sign-in from before Outlook Send lacks Mail.Send until it is reconnected. */
const needsReconnect = computed((): boolean => {
  if (provider.value !== "outlook" || !credentialId.value) return false;
  const found = credentials.value.find((item) => item.id === credentialId.value);
  return !!found && found.public_fields?.can_send !== "true";
});

/** The chip of the address the node sends as; a blank From is the account's own address. */
function isChosenAddress(address: string, index: number): boolean {
  const chosen = fromAddress.value.trim().toLowerCase();
  return chosen ? address.toLowerCase() === chosen : index === 0;
}

const fromHint = computed((): string =>
  provider.value === "gmail"
    ? "Blank sends as the account. Use one of its Send mail as addresses."
    : "Blank sends as the account. Use an alias or a shared mailbox it may send as.",
);
</script>

<template>
  <template v-if="selectedNode">
    <div
      class="space-y-2"
      data-testid="mail-send-credential-field"
    >
      <Label>{{ providerName }} Credential</Label>
      <Select
        :model-value="credentialId"
        :options="credentialOptions"
        @update:model-value="updateNodeData('credentialId', $event ?? '')"
      />
      <p
        v-if="!credentialId"
        class="text-xs text-muted-foreground"
      >
        <a
          href="/?tab=credentials"
          class="text-primary hover:underline"
          @click.prevent="$router.push('/?tab=credentials')"
        >Add credentials</a> in Dashboard
      </p>
      <p
        v-else-if="needsReconnect"
        class="text-xs text-amber-500 flex items-start gap-1"
        data-testid="mail-send-reconnect-hint"
      >
        <AlertTriangle class="h-3 w-3 mt-0.5 shrink-0" />
        Reconnect this credential in Credentials to allow sending (Mail.Send).
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
      data-testid="mail-send-from-field"
    >
      <Label>From</Label>
      <ExpressionInput
        ref="sendEmailFromInputRef"
        :model-value="fromAddress"
        placeholder="Account address"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        dialog-title="Edit From"
        navigation-enabled
        :navigation-index="0"
        :navigation-total="sendEmailExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="From"
        field-key="fromAddress"
        @update:model-value="updateNodeData('fromAddress', $event)"
        @navigate="handleSendEmailExpressionFieldNavigate"
        @register-field-index="onSendEmailRegisterExpressionFieldIndex"
      />
      <div
        v-if="addresses.length > 1"
        class="flex flex-wrap gap-1"
      >
        <button
          v-for="(address, index) in addresses"
          :key="address"
          type="button"
          class="rounded-full border px-2 py-0.5 text-[11px] transition-colors"
          :class="isChosenAddress(address, index)
            ? 'border-primary bg-primary/10 text-primary'
            : 'border-border text-muted-foreground hover:text-foreground'"
          @click="updateNodeData('fromAddress', index === 0 ? '' : address)"
        >
          {{ address }}
        </button>
      </div>
      <p class="text-xs text-muted-foreground">
        {{ fromHint }}
      </p>
    </div>

    <EmailMessageFields :field-offset="1" />
  </template>
</template>
