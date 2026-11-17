import { onMounted, ref, watch } from "vue";
import type { Ref } from "vue";
import axios from "axios";

import type { CredentialListItem } from "@/types/credential";
import type { OutlookAddress, OutlookFolder } from "@/types/outlook";
import { credentialsApi, outlookApi } from "@/services/api";

export interface OutlookTriggerOptions {
  credentials: Ref<CredentialListItem[]>;
  folders: Ref<OutlookFolder[]>;
  addresses: Ref<OutlookAddress[]>;
  loadingAccount: Ref<boolean>;
  accountError: Ref<string>;
}

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return "Could not read this Outlook mailbox";
}

/** The user's Outlook credentials, and the selected account's folders and addresses. */
export function useOutlookTriggerOptions(credentialId: Ref<string>): OutlookTriggerOptions {
  const credentials = ref<CredentialListItem[]>([]);
  const folders = ref<OutlookFolder[]>([]);
  const addresses = ref<OutlookAddress[]>([]);
  const loadingAccount = ref(false);
  const accountError = ref("");
  let requested = "";

  async function loadAccount(id: string): Promise<void> {
    requested = id;
    folders.value = [];
    addresses.value = [];
    accountError.value = "";
    if (!id) return;
    loadingAccount.value = true;
    try {
      const [foundFolders, foundAddresses] = await Promise.all([
        outlookApi.listFolders(id),
        outlookApi.listAddresses(id),
      ]);
      if (requested !== id) return;
      folders.value = foundFolders;
      addresses.value = foundAddresses;
    } catch (error: unknown) {
      if (requested === id) accountError.value = errorMessage(error);
    } finally {
      if (requested === id) loadingAccount.value = false;
    }
  }

  onMounted(async () => {
    try {
      credentials.value = await credentialsApi.listByType("outlook");
    } catch {
      credentials.value = [];
    }
  });

  watch(credentialId, (id) => void loadAccount(id), { immediate: true });

  return { credentials, folders, addresses, loadingAccount, accountError };
}
