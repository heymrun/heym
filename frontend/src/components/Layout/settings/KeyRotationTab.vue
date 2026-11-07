<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RefreshCw } from "lucide-vue-next";
import axios from "axios";

import Button from "@/components/ui/Button.vue";
import { getKeyRotation, startKeyRotation } from "@/services/keyRotation";

import type { KeyRotationStatus } from "@/types/keyRotation";

const state = ref<KeyRotationStatus | null>(null);
const loading = ref(false);
const starting = ref(false);
const error = ref<string | null>(null);
let poll: ReturnType<typeof setInterval> | null = null;

const rotation = computed(() => state.value?.rotation ?? null);
const active = computed(
  () => rotation.value?.state === "running" || rotation.value?.state === "paused",
);

const STATE_LABELS = { running: "Running", paused: "Paused", completed: "Completed" } as const;

function stateClass(value: string): string {
  if (value === "completed") return "text-emerald-600 dark:text-emerald-400";
  if (value === "paused") return "text-amber-600 dark:text-amber-400";
  return "text-primary";
}

function keysOf(primary: string, decrypts: string[]): string {
  const extra = decrypts.filter((fingerprint) => fingerprint !== primary);
  return extra.length ? `${primary} (also ${extra.join(", ")})` : primary;
}

function syncPolling(): void {
  if (active.value && poll === null) {
    poll = setInterval(() => void load(), 3000);
  } else if (!active.value && poll !== null) {
    clearInterval(poll);
    poll = null;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    state.value = await getKeyRotation();
    error.value = null;
  } catch {
    error.value = "Failed to load the encryption key status.";
  } finally {
    loading.value = false;
    syncPolling();
  }
}

async function start(): Promise<void> {
  starting.value = true;
  error.value = null;
  try {
    state.value = await startKeyRotation();
  } catch (err) {
    error.value =
      axios.isAxiosError(err) && typeof err.response?.data?.detail === "string"
        ? err.response.data.detail
        : "Failed to start the re-encryption.";
  } finally {
    starting.value = false;
    syncPolling();
  }
}

onMounted(load);
onUnmounted(() => {
  if (poll !== null) clearInterval(poll);
});
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between gap-4">
      <p class="text-sm text-muted-foreground">
        Rotating <code>ENCRYPTION_KEY</code>: add the new key to
        <code>ENCRYPTION_KEYS_EXTRA</code> everywhere, then make it <code>ENCRYPTION_KEY</code>
        with the old one as the extra, then re-encrypt here. Keys are shown by fingerprint only.
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

    <template v-if="state">
      <div class="rounded-md border border-border p-3">
        <p class="mb-2 text-xs font-medium text-muted-foreground">
          Instances
        </p>
        <div
          v-for="instance in state.instances"
          :key="instance.id"
          :data-testid="`key-rotation-instance-${instance.id}`"
          class="flex items-center justify-between gap-3 border-b border-border/50 py-1.5 text-sm last:border-b-0"
        >
          <span class="truncate">
            {{ instance.name || instance.id }}
            <span
              v-if="!instance.live"
              class="text-xs text-muted-foreground"
            >· offline</span>
          </span>
          <span class="truncate font-mono text-xs text-muted-foreground">
            {{ keysOf(instance.primary_fingerprint, instance.decrypt_fingerprints) }}
          </span>
        </div>
      </div>

      <div
        class="rounded-md border border-border p-3 space-y-2"
        data-testid="key-rotation-progress"
      >
        <template v-if="rotation">
          <p class="text-sm">
            <span
              class="font-medium"
              :class="stateClass(rotation.state)"
            >{{ STATE_LABELS[rotation.state] }}</span>
            <span class="text-muted-foreground">
              · to key <span class="font-mono">{{ rotation.target_fingerprint }}</span>
              · {{ rotation.done }} re-encrypted, {{ rotation.remaining }} remaining,
              {{ rotation.unreadable }} unreadable
            </span>
          </p>
          <p
            v-if="rotation.message"
            class="text-xs text-amber-600 dark:text-amber-400"
          >
            {{ rotation.message }}
          </p>
          <p
            v-if="rotation.state === 'completed' && rotation.retired_fingerprints.length"
            class="text-xs text-muted-foreground"
          >
            Every readable value is under the new key. You can remove the old key
            (<span class="font-mono">{{ rotation.retired_fingerprints.join(", ") }}</span>) from
            <code>ENCRYPTION_KEYS_EXTRA</code>, unless a backup taken before this rotation
            may need restoring. Instances refuse to start with it as
            <code>ENCRYPTION_KEY</code> from now on.
          </p>
        </template>
        <p
          v-else
          class="text-sm text-muted-foreground"
        >
          No rotation has run yet.
        </p>
        <div class="flex items-center gap-3">
          <Button
            size="sm"
            data-testid="key-rotation-start"
            :disabled="!state.can_start || starting"
            @click="start"
          >
            Re-encrypt under key {{ state.primary_fingerprint }}
          </Button>
          <span
            v-if="!state.can_start && state.reason"
            class="text-xs text-muted-foreground"
          >{{ state.reason }}</span>
        </div>
      </div>

      <div
        v-if="state.unreadable.length"
        class="rounded-md border border-border p-3"
        data-testid="key-rotation-unreadable"
      >
        <p class="mb-2 text-xs font-medium text-muted-foreground">
          Credentials no configured key can read. Their owners see them as unreadable and can
          delete and re-create them.
        </p>
        <div
          v-for="credential in state.unreadable"
          :key="credential.id"
          class="flex items-center justify-between gap-3 border-b border-border/50 py-1.5 text-sm last:border-b-0"
        >
          <span class="truncate">
            {{ credential.name }}
            <span class="text-muted-foreground">· {{ credential.type }}</span>
          </span>
          <span class="truncate text-xs text-muted-foreground">
            {{ credential.owner_email }}
            <template v-if="credential.updated_at">
              · {{ new Date(credential.updated_at).toLocaleDateString() }}
            </template>
          </span>
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
