<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import axios from "axios";
import { useRoute } from "vue-router";
import { CheckCircle2, Clock3, Loader2, ShieldAlert, ShieldCheck } from "lucide-vue-next";

import type { ClarifyCredentialRef } from "@/types/clarify";
import type { Credential } from "@/types/credential";
import type { CredentialSetupRequest } from "@/types/credentialSetup";

import CredentialFormButton from "@/components/Credentials/CredentialFormButton.vue";
import Button from "@/components/ui/Button.vue";
import { credentialSetupApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { CREDENTIAL_TYPE_LABELS } from "@/types/credential";

const route = useRoute();
const authStore = useAuthStore();
const requestId = computed((): string => String(route.params.id || ""));

const setup = ref<CredentialSetupRequest | null>(null);
const saved = ref<ClarifyCredentialRef | undefined>(undefined);
const isLoading = ref(true);
const isDeclining = ref(false);
const error = ref("");

const isPending = computed((): boolean => setup.value?.status === "pending");
const typeLabel = computed((): string =>
  setup.value ? (CREDENTIAL_TYPE_LABELS[setup.value.credential_type] ?? setup.value.credential_type) : "",
);
const title = computed((): string =>
  setup.value?.action === "update"
    ? `Update your ${typeLabel.value} credential`
    : `Add a ${typeLabel.value} credential`,
);
const preset = computed((): ClarifyCredentialRef | undefined =>
  setup.value?.action === "create"
    ? { type: setup.value.credential_type, name: setup.value.suggested_name ?? "" }
    : undefined,
);
const editId = computed((): string | undefined =>
  setup.value?.action === "update" ? (setup.value.credential_id ?? undefined) : undefined,
);
const closedMessage = computed((): string => {
  switch (setup.value?.status) {
    case "completed":
      return "Saved. Go back to the app you were chatting in; the assistant continues there.";
    case "declined":
      return "This form was declined. Ask the assistant again when you want to add the credential.";
    case "expired":
      return "This form has expired. Ask the assistant to open a new one.";
    default:
      return "";
  }
});

function errorDetail(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    if (err.response?.status === 404) {
      return "This credential form was not found. It may have been opened for another Heym account.";
    }
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

async function load(): Promise<void> {
  isLoading.value = true;
  error.value = "";
  try {
    setup.value = await credentialSetupApi.get(requestId.value);
  } catch (err) {
    error.value = errorDetail(err, "This credential form could not be loaded.");
  } finally {
    isLoading.value = false;
  }
}

async function onSaved(credential: Credential): Promise<void> {
  error.value = "";
  saved.value = { type: credential.type, name: credential.name };
  try {
    setup.value = await credentialSetupApi.complete(requestId.value, credential.id);
  } catch (err) {
    error.value = errorDetail(err, "The credential was saved, but this form could not be closed.");
  }
}

async function decline(): Promise<void> {
  isDeclining.value = true;
  error.value = "";
  try {
    setup.value = await credentialSetupApi.decline(requestId.value);
  } catch (err) {
    error.value = errorDetail(err, "This form could not be declined.");
  } finally {
    isDeclining.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="min-h-screen bg-muted/20 text-foreground">
    <main class="mx-auto max-w-2xl px-4 py-10 sm:px-6">
      <div class="rounded-2xl border border-border/60 bg-background/95 shadow-xl">
        <div class="border-b border-border/60 px-6 py-5 sm:px-8">
          <div class="flex flex-wrap items-center gap-3">
            <span class="inline-flex items-center gap-2 rounded-full border border-border/70 bg-muted/50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              <ShieldCheck class="h-3.5 w-3.5" />
              Heym credential form
            </span>
            <span
              v-if="setup"
              class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium"
              :class="isPending ? 'bg-amber-500/15 text-amber-600 dark:text-amber-300' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'"
            >
              <Clock3
                v-if="isPending"
                class="h-3.5 w-3.5"
              />
              <CheckCircle2
                v-else
                class="h-3.5 w-3.5"
              />
              {{ isPending ? "Waiting for you" : "Closed" }}
            </span>
          </div>
          <h1 class="mt-4 text-2xl font-semibold tracking-tight">
            {{ setup ? title : "Credential form" }}
          </h1>
          <p
            v-if="authStore.user"
            class="mt-1 text-sm text-muted-foreground"
          >
            Signed in to Heym as {{ authStore.user.email }}
          </p>
        </div>

        <div class="space-y-6 px-6 py-6 sm:px-8">
          <div
            v-if="isLoading"
            class="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 class="h-4 w-4 animate-spin" />
            Loading the form...
          </div>

          <template v-else-if="setup">
            <p
              v-if="setup.reason"
              class="rounded-xl border border-border/60 bg-muted/30 p-4 text-sm"
            >
              {{ setup.reason }}
            </p>
            <p class="text-sm text-muted-foreground">
              The Heym assistant you are chatting with in another app asked for this credential.
              What you enter here is saved in Heym and never passes through that app or its AI
              model; the assistant only learns the credential's name and type.
            </p>

            <div
              v-if="isPending"
              class="flex flex-wrap items-center justify-between gap-3"
            >
              <CredentialFormButton
                :create="preset"
                :edit-id="editId"
                :saved="saved"
                @saved="onSaved"
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                :loading="isDeclining"
                :disabled="!!saved"
                @click="decline"
              >
                Decline
              </Button>
            </div>
            <div
              v-else
              class="rounded-xl border p-3 text-sm"
              :class="setup.status === 'completed' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' : 'border-border/60 bg-muted/30 text-muted-foreground'"
            >
              {{ closedMessage }}
            </div>
          </template>

          <div
            v-if="error"
            class="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          >
            <ShieldAlert class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
