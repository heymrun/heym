import { ref, watch } from "vue";
import type { Ref } from "vue";
import axios from "axios";

import type { CredentialListItem } from "@/types/credential";
import type { MailAccountProvider } from "@/lib/emailSendNodes";
import { credentialsApi, gmailApi, outlookApi } from "@/services/api";

export interface MailSendAccount {
  credentials: Ref<CredentialListItem[]>;
  /** Addresses the account can send as: the primary one first, then its aliases. */
  addresses: Ref<string[]>;
  loadingAccount: Ref<boolean>;
  accountError: Ref<string>;
}

const PROVIDER_NAMES: Record<MailAccountProvider, string> = { gmail: "Gmail", outlook: "Outlook" };

function errorMessage(error: unknown, provider: MailAccountProvider): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return `Could not read this ${PROVIDER_NAMES[provider]} account`;
}

async function listAddresses(provider: MailAccountProvider, credentialId: string): Promise<string[]> {
  const found =
    provider === "gmail"
      ? await gmailApi.listAddresses(credentialId)
      : await outlookApi.listAddresses(credentialId);
  return found.map((address) => address.email);
}

/** The user's Gmail or Outlook credentials, and the addresses the chosen account sends as. */
export function useMailSendAccount(
  provider: Ref<MailAccountProvider>,
  credentialId: Ref<string>,
): MailSendAccount {
  const credentials = ref<CredentialListItem[]>([]);
  const addresses = ref<string[]>([]);
  const loadingAccount = ref(false);
  const accountError = ref("");
  let requested = "";

  async function loadCredentials(kind: MailAccountProvider): Promise<void> {
    try {
      const found = await credentialsApi.listByType(kind);
      if (provider.value === kind) credentials.value = found;
    } catch {
      if (provider.value === kind) credentials.value = [];
    }
  }

  async function loadAccount(kind: MailAccountProvider, id: string): Promise<void> {
    const key = `${kind}:${id}`;
    requested = key;
    addresses.value = [];
    accountError.value = "";
    if (!id) return;
    loadingAccount.value = true;
    try {
      const found = await listAddresses(kind, id);
      if (requested === key) addresses.value = found;
    } catch (error: unknown) {
      if (requested === key) accountError.value = errorMessage(error, kind);
    } finally {
      if (requested === key) loadingAccount.value = false;
    }
  }

  watch(provider, (kind) => void loadCredentials(kind), { immediate: true });
  watch(
    [provider, credentialId],
    ([kind, id]) => void loadAccount(kind, id),
    { immediate: true },
  );

  return { credentials, addresses, loadingAccount, accountError };
}
