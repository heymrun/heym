<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import axios from "axios";
import { Check, Copy, KeyRound } from "lucide-vue-next";

import type { WorkIntegrationConfig } from "@/types/workIntegration";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import SettingsToggle from "@/components/Layout/settings/SettingsToggle.vue";
import {
  getWorkIntegrationConfig,
  rotateWorkIntegrationKey,
  saveWorkIntegrationConfig,
} from "@/services/workIntegration";
import { heymWebUrl } from "@/lib/heymWeb";

const enterpriseUrl = heymWebUrl("/enterprise");

const config = ref<WorkIntegrationConfig | null>(null);
const workUrl = ref("");
const freshKey = ref<string | null>(null);
const loading = ref(false);
const saving = ref(false);
const rotating = ref(false);
const copied = ref(false);
const error = ref<string | null>(null);

const lastSeen = computed((): string => {
  const value = config.value?.last_seen_at;
  return value ? new Date(value).toLocaleString() : "Never";
});

function errorDetail(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err) && typeof err.response?.data?.detail === "string") {
    return err.response.data.detail;
  }
  return fallback;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    config.value = await getWorkIntegrationConfig();
    workUrl.value = config.value.work_url;
  } catch (err: unknown) {
    error.value = errorDetail(err, "Failed to load Heym Work settings.");
  } finally {
    loading.value = false;
  }
}

async function save(enabled?: boolean): Promise<void> {
  if (!config.value) return;
  saving.value = true;
  error.value = null;
  try {
    config.value = await saveWorkIntegrationConfig({
      work_url: workUrl.value,
      enabled: enabled ?? config.value.enabled,
    });
    workUrl.value = config.value.work_url;
  } catch (err: unknown) {
    error.value = errorDetail(err, "Failed to save Heym Work settings.");
    await load();
  } finally {
    saving.value = false;
  }
}

async function rotateKey(): Promise<void> {
  const confirmed =
    !config.value?.key_set ||
    window.confirm(
      "Generate a new key? Heym Work stops working until the new key is entered there, and everyone there is signed out.",
    );
  if (!confirmed) return;
  rotating.value = true;
  error.value = null;
  try {
    const result = await rotateWorkIntegrationKey();
    freshKey.value = result.key;
    config.value = result.config;
  } catch (err: unknown) {
    error.value = errorDetail(err, "Failed to generate a key.");
  } finally {
    rotating.value = false;
  }
}

async function copyKey(): Promise<void> {
  if (!freshKey.value) return;
  await navigator.clipboard.writeText(freshKey.value);
  copied.value = true;
  window.setTimeout(() => {
    copied.value = false;
  }, 1500);
}

onMounted(load);
</script>

<template>
  <div class="space-y-5">
    <p class="text-sm text-muted-foreground">
      Heym Work is a second interface for business teams. People sign in through Heym, and every
      job runs here.
      <a
        :href="enterpriseUrl"
        target="_blank"
        rel="noopener"
        class="font-medium text-primary hover:underline dark:text-brand-primary-soft"
      >Learn more about Heym Work</a>
    </p>

    <p
      v-if="error"
      class="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm"
    >
      {{ error }}
    </p>

    <p
      v-if="loading"
      class="text-sm text-muted-foreground"
    >
      Loading...
    </p>

    <template v-if="config">
      <div class="space-y-2">
        <Label for="work-url">Heym Work address</Label>
        <p class="text-xs text-muted-foreground">
          Where Heym Work runs, for example https://work.example.com. Sign-in returns there.
        </p>
        <div class="flex gap-2">
          <Input
            id="work-url"
            v-model="workUrl"
            placeholder="https://work.example.com"
          />
          <Button
            variant="outline"
            :loading="saving"
            @click="save()"
          >
            Save
          </Button>
        </div>
      </div>

      <div class="space-y-2">
        <Label>Integration key</Label>
        <p class="text-xs text-muted-foreground">
          Enter this key in Heym Work's setup. It is shown only once.
        </p>
        <div
          v-if="freshKey"
          class="flex gap-2 items-center"
        >
          <code class="flex-1 truncate rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs">
            {{ freshKey }}
          </code>
          <Button
            variant="outline"
            size="icon"
            :aria-label="copied ? 'Copied' : 'Copy key'"
            @click="copyKey"
          >
            <Check
              v-if="copied"
              class="w-4 h-4"
            />
            <Copy
              v-else
              class="w-4 h-4"
            />
          </Button>
        </div>
        <p
          v-else
          class="text-sm"
        >
          {{ config.key_set ? "Key configured" : "No key yet" }}
        </p>
        <Button
          variant="outline"
          :loading="rotating"
          @click="rotateKey"
        >
          <KeyRound class="w-4 h-4" />
          {{ config.key_set ? "Rotate key" : "Generate key" }}
        </Button>
      </div>

      <SettingsToggle
        id="work-enabled"
        :model-value="config.enabled"
        label="Enable Heym Work"
        :disabled="saving"
        @update:model-value="save"
      />

      <div class="rounded-lg border border-border p-3 text-sm space-y-1">
        <div class="flex justify-between">
          <span class="text-muted-foreground">Last seen</span>
          <span>{{ lastSeen }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-muted-foreground">Work version</span>
          <span>{{ config.last_work_version || "Unknown" }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-muted-foreground">License</span>
          <span>{{ config.last_license_status || "Unknown" }}</span>
        </div>
      </div>
    </template>
  </div>
</template>
