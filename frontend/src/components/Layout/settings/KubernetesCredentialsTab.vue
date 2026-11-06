<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RefreshCw, Trash2 } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import { getK8sCredentials, removeK8sCredential } from "@/services/k8sCredentials";

import type { K8sCredential, K8sCredentialStatus, K8sCredentialsState } from "@/types/k8sCredentials";

const state = ref<K8sCredentialsState | null>(null);
const loading = ref(false);
const removing = ref<string | null>(null);
const error = ref<string | null>(null);

const STATUS_LABELS: Record<K8sCredentialStatus, string> = {
  available: "Available",
  unavailable: "Secret gone",
  invalid: "Invalid",
  owner_missing: "Owner missing",
  name_conflict: "Name conflict",
};

function statusClass(status: K8sCredentialStatus): string {
  if (status === "available") return "text-emerald-600 dark:text-emerald-400";
  if (status === "unavailable") return "text-muted-foreground";
  return "text-destructive";
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    state.value = await getK8sCredentials();
  } catch {
    error.value = "Failed to load Kubernetes credentials.";
  } finally {
    loading.value = false;
  }
}

async function remove(credential: K8sCredential): Promise<void> {
  removing.value = credential.credential_id;
  error.value = null;
  try {
    await removeK8sCredential(credential.credential_id);
    await load();
  } catch {
    error.value = `Failed to remove ${credential.name}.`;
  } finally {
    removing.value = null;
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between gap-4">
      <p class="text-sm text-muted-foreground">
        Credentials declared as labelled Kubernetes Secrets. They are read-only here: change
        them where the Secret is managed.
      </p>
      <Button
        variant="outline"
        size="sm"
        class="shrink-0 px-2"
        title="Refresh"
        aria-label="Refresh"
        :disabled="loading"
        @click="load"
      >
        <RefreshCw class="h-4 w-4" />
      </Button>
    </div>

    <p
      v-if="state && !state.enabled"
      class="text-sm text-muted-foreground"
    >
      Kubernetes credentials are off. Set <code>HEYM_K8S_CREDENTIALS=true</code> and grant the
      backend's ServiceAccount <code>get</code>, <code>list</code> and <code>watch</code> on
      Secrets to turn them on.
    </p>

    <template v-else-if="state">
      <p
        class="text-sm text-muted-foreground"
        data-testid="k8s-credentials-sync"
      >
        <template v-if="state.synced">
          This process synced at {{ state.synced_at ? new Date(state.synced_at).toLocaleString() : "" }}.
        </template>
        <template v-else>
          This process has not synced yet; runs that need these credentials wait until it has.
        </template>
        <span
          v-if="state.last_error"
          class="text-destructive"
        >
          Last error: {{ state.last_error }}
        </span>
      </p>

      <div class="rounded-md border border-border p-3">
        <p
          v-if="!state.credentials.length"
          class="text-sm text-muted-foreground"
        >
          No labelled Secrets found.
        </p>
        <div
          v-for="credential in state.credentials"
          :key="credential.credential_id"
          :data-testid="`k8s-credential-${credential.credential_id}`"
          class="flex items-start justify-between gap-3 border-b border-border/50 py-2 last:border-b-0"
        >
          <div class="min-w-0">
            <p class="truncate text-sm font-medium">
              {{ credential.name }}
              <span class="font-normal text-muted-foreground">· {{ credential.type }}</span>
            </p>
            <p class="truncate text-xs font-mono text-muted-foreground">
              {{ credential.namespace }}/{{ credential.secret_name }}
              <template v-if="credential.owner_email">
                · {{ credential.owner_email }}
              </template>
            </p>
            <p
              v-if="credential.detail"
              class="text-xs text-muted-foreground"
            >
              {{ credential.detail }}
            </p>
            <p
              v-for="warning in credential.warnings"
              :key="warning"
              class="text-xs text-amber-600 dark:text-amber-400"
            >
              {{ warning }}
            </p>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <span
              class="text-xs font-medium"
              :class="statusClass(credential.status)"
            >
              {{ STATUS_LABELS[credential.status] }}
            </span>
            <Button
              v-if="credential.status === 'unavailable'"
              variant="ghost"
              size="icon"
              class="h-7 w-7 text-muted-foreground hover:text-destructive"
              title="Remove this credential. Workflows that use it will fail."
              :aria-label="`Remove ${credential.name}`"
              :disabled="removing === credential.credential_id"
              @click="remove(credential)"
            >
              <Trash2 class="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </template>

    <p
      v-if="error"
      class="text-sm text-destructive"
    >
      {{ error }}
    </p>
  </div>
</template>
