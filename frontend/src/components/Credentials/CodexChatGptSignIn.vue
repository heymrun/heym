<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { Check, Copy, Loader2 } from "lucide-vue-next";

import type { CodexSignInResult } from "@/components/Credentials/codexDeviceSignIn";

import { createCodexDeviceSignIn, errorDetail } from "@/components/Credentials/codexDeviceSignIn";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { credentialsPortKey, usePort } from "@/ports";

const props = defineProps<{
  saving: boolean;
  connected: boolean;
}>();

const emit = defineEmits<{
  signedIn: [result: CodexSignInResult];
}>();

const credentialsApi = usePort(credentialsPortKey);

const POPUP_FEATURES = "width=520,height=760";

const device = createCodexDeviceSignIn({
  start: () => credentialsApi.codexDeviceStart(),
  poll: (state) => credentialsApi.codexDevicePoll(state),
  onSignedIn: (result) => emit("signedIn", result),
  openWindow: (url) => window.open(url, "codex-chatgpt-sign-in", POPUP_FEATURES),
});
const { phase, userCode, error: deviceError } = device;

const copied = ref(false);
const opened = ref(false);

// The redirect URL flow stays as a fallback for accounts where device code sign-in is off.
const usePaste = ref(false);
const pasteState = ref("");
const authorizeUrl = ref("");
const redirectUrl = ref("");
const completing = ref(false);
const pasteError = ref("");

const signInLabel = computed((): string => {
  if (phase.value === "starting") return "Getting a code...";
  return props.connected ? "Re-sign in with ChatGPT" : "Sign in with ChatGPT";
});

async function copyCode(): Promise<void> {
  try {
    await navigator.clipboard.writeText(userCode.value);
    copied.value = true;
  } catch {
    copied.value = false;
  }
}

async function beginDevice(): Promise<void> {
  copied.value = false;
  opened.value = false;
  await device.begin();
  // Copy while this page still has focus: once the OpenAI window opens, the clipboard refuses.
  if (phase.value === "waiting") await copyCode();
}

function openOpenAi(): void {
  device.openVerificationPage();
  opened.value = true;
}

function switchToPaste(): void {
  device.cancel();
  usePaste.value = true;
}

function switchToDevice(): void {
  usePaste.value = false;
  pasteError.value = "";
}

async function startPaste(): Promise<void> {
  pasteError.value = "";
  try {
    const { authorize_url, state } = await credentialsApi.codexOAuthStart();
    pasteState.value = state;
    authorizeUrl.value = authorize_url;
    window.open(authorize_url, "_blank", "noopener,noreferrer");
  } catch {
    pasteError.value = "Could not start ChatGPT sign-in. Try again.";
  }
}

async function completePaste(): Promise<void> {
  completing.value = true;
  pasteError.value = "";
  try {
    const { config, account_id } = await credentialsApi.codexOAuthComplete(
      pasteState.value,
      redirectUrl.value.trim(),
    );
    redirectUrl.value = "";
    emit("signedIn", { config, accountId: account_id });
  } catch (err) {
    pasteError.value = errorDetail(err, "ChatGPT sign-in failed. Restart and try again.");
  } finally {
    completing.value = false;
  }
}

onBeforeUnmount(() => device.cancel());
</script>

<template>
  <div class="space-y-2">
    <template v-if="!usePaste">
      <template v-if="phase !== 'waiting'">
        <Button
          type="button"
          variant="outline"
          class="w-full"
          :disabled="saving || phase === 'starting'"
          data-testid="codex-device-sign-in"
          @click="beginDevice"
        >
          {{ signInLabel }}
        </Button>
        <p class="text-xs text-muted-foreground">
          Heym shows a short code. Enter it on the OpenAI page and Heym finishes the sign-in on
          its own. Nothing to paste back.
        </p>
      </template>

      <div
        v-else
        class="space-y-3 rounded-md border bg-muted/40 p-3"
        data-testid="codex-device-code-panel"
      >
        <p class="text-xs text-muted-foreground">
          Enter this code on the OpenAI page{{ copied ? " (it is already copied)" : "" }}:
        </p>
        <div class="flex items-center justify-center gap-2">
          <span
            class="select-all font-mono text-2xl font-semibold tracking-[0.2em]"
            data-testid="codex-device-code"
          >
            {{ userCode }}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            :title="copied ? 'Copied' : 'Copy code'"
            :aria-label="copied ? 'Copied' : 'Copy code'"
            @click="copyCode"
          >
            <Check
              v-if="copied"
              class="h-4 w-4"
            />
            <Copy
              v-else
              class="h-4 w-4"
            />
          </Button>
        </div>
        <Button
          type="button"
          class="w-full"
          :disabled="saving"
          data-testid="codex-open-openai"
          @click="openOpenAi"
        >
          {{ opened ? "Open the OpenAI page again" : "Open the OpenAI page" }}
        </Button>
        <p class="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 class="h-3.5 w-3.5 shrink-0 animate-spin" />
          <span>Waiting for you to approve on OpenAI. This finishes by itself.</span>
        </p>
        <button
          type="button"
          class="text-xs text-muted-foreground underline hover:text-foreground"
          @click="device.cancel"
        >
          Cancel
        </button>
      </div>

      <p class="text-xs text-muted-foreground">
        OpenAI says device code sign-in is off? Turn it on in ChatGPT under Settings, Security
        (workspace accounts need an admin to allow it), or
        <button
          type="button"
          class="text-primary underline"
          data-testid="codex-use-redirect"
          @click="switchToPaste"
        >
          paste a redirect URL instead
        </button>.
      </p>
      <p
        v-if="deviceError"
        class="text-xs text-destructive"
      >
        {{ deviceError }}
      </p>
    </template>

    <template v-else>
      <Button
        type="button"
        variant="outline"
        :disabled="saving || completing"
        class="w-full"
        @click="startPaste"
      >
        {{ connected ? "Re-sign in with ChatGPT" : "Sign in with ChatGPT" }}
      </Button>
      <p class="text-xs text-muted-foreground">
        A new tab opens the OpenAI sign-in. After you authorize, your browser lands on a
        <code class="bg-muted px-1 rounded">localhost:1455</code> page (it may fail to load,
        which is expected). Copy that full URL from the address bar and paste it below.
      </p>
      <p
        v-if="authorizeUrl"
        class="text-xs text-muted-foreground"
      >
        Sign-in tab didn't open?
        <a
          :href="authorizeUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="text-primary underline"
        >Open the OpenAI sign-in page</a>
      </p>
      <Input
        v-model="redirectUrl"
        placeholder="http://localhost:1455/auth/callback?code=..."
        :disabled="saving || completing || !pasteState"
      />
      <Button
        type="button"
        :disabled="saving || completing || !pasteState || !redirectUrl.trim()"
        class="w-full"
        @click="completePaste"
      >
        {{ completing ? "Finishing sign-in..." : "Finish sign-in" }}
      </Button>
      <button
        type="button"
        class="text-xs text-primary underline"
        @click="switchToDevice"
      >
        Use a sign-in code instead
      </button>
      <p
        v-if="pasteError"
        class="text-xs text-destructive"
      >
        {{ pasteError }}
      </p>
    </template>
  </div>
</template>
