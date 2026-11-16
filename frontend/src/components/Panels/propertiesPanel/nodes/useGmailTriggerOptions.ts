import { onMounted, ref, watch } from "vue";
import type { Ref } from "vue";
import axios from "axios";

import type { CredentialListItem } from "@/types/credential";
import type { GmailAddress, GmailLabel } from "@/types/gmail";
import { credentialsApi, gmailApi } from "@/services/api";

export interface GmailTriggerOptions {
  credentials: Ref<CredentialListItem[]>;
  labels: Ref<GmailLabel[]>;
  addresses: Ref<GmailAddress[]>;
  loadingAccount: Ref<boolean>;
  accountError: Ref<string>;
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return "Could not read this Gmail account";
}

/** The user's Gmail credentials, and the selected account's labels and addresses. */
export function useGmailTriggerOptions(credentialId: Ref<string>): GmailTriggerOptions {
  const credentials = ref<CredentialListItem[]>([]);
  const labels = ref<GmailLabel[]>([]);
  const addresses = ref<GmailAddress[]>([]);
  const loadingAccount = ref(false);
  const accountError = ref("");
  let requested = "";

  async function loadAccount(id: string): Promise<void> {
    requested = id;
    labels.value = [];
    addresses.value = [];
    accountError.value = "";
    if (!id) return;
    loadingAccount.value = true;
    try {
      const [foundLabels, foundAddresses] = await Promise.all([
        gmailApi.listLabels(id),
        gmailApi.listAddresses(id),
      ]);
      if (requested !== id) return;
      labels.value = foundLabels;
      addresses.value = foundAddresses;
    } catch (error: unknown) {
      if (requested === id) accountError.value = errorMessage(error);
    } finally {
      if (requested === id) loadingAccount.value = false;
    }
  }

  onMounted(async () => {
    try {
      credentials.value = await credentialsApi.listByType("gmail");
    } catch {
      credentials.value = [];
    }
  });

  watch(credentialId, (id) => void loadAccount(id), { immediate: true });

  return { credentials, labels, addresses, loadingAccount, accountError };
}
