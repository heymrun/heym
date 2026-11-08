<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ShieldCheck } from "lucide-vue-next";

import AuthenticatorSetup from "@/components/Auth/AuthenticatorSetup.vue";
import RecoveryCodesPanel from "@/components/Auth/RecoveryCodesPanel.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import {
  apiErrorDetail,
  confirmMfaSetup,
  getMfaStatus,
  regenerateRecoveryCodes,
  startMfaSetup,
} from "@/services/mfa";
import type { MfaSetup, MfaStatus } from "@/types/auth";

type Step = "idle" | "verify-device" | "scan" | "regenerate" | "codes";

const status = ref<MfaStatus | null>(null);
const step = ref<Step>("idle");
const password = ref("");
const code = ref("");
const setup = ref<MfaSetup | null>(null);
const recoveryCodes = ref<string[]>([]);
const busy = ref(false);
const error = ref("");

const enabledSince = computed<string>(() => {
  const value = status.value?.enabled_at;
  return value ? new Date(value).toLocaleDateString() : "";
});

async function load(): Promise<void> {
  try {
    status.value = await getMfaStatus();
  } catch {
    status.value = null;
  }
}

function reset(): void {
  step.value = "idle";
  password.value = "";
  code.value = "";
  setup.value = null;
  error.value = "";
}

async function run(action: () => Promise<void>, fallback: string): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    await action();
  } catch (err) {
    error.value = apiErrorDetail(err, fallback);
  } finally {
    busy.value = false;
  }
}

function submitDevice(): Promise<void> {
  return run(async () => {
    const current = status.value?.enabled ? code.value.trim() : null;
    setup.value = await startMfaSetup(password.value, current);
    password.value = "";
    code.value = "";
    step.value = "scan";
  }, "Could not start the setup.");
}

function submitScan(): Promise<void> {
  return run(async () => {
    if (!setup.value) return;
    recoveryCodes.value = await confirmMfaSetup(setup.value.setup_token, code.value.trim());
    step.value = "codes";
    await load();
  }, "That code is not valid. Try again.");
}

function submitRegenerate(): Promise<void> {
  return run(async () => {
    recoveryCodes.value = await regenerateRecoveryCodes(code.value.trim());
    step.value = "codes";
    await load();
  }, "That code is not valid. Try again.");
}

onMounted(load);
</script>

<template>
  <section
    v-if="status?.available"
    class="space-y-4 border-t border-border pt-6"
    data-testid="mfa-settings"
  >
    <div class="flex items-start gap-3">
      <ShieldCheck class="w-5 h-5 text-primary shrink-0 mt-0.5" />
      <div class="space-y-1">
        <h3 class="text-sm font-semibold">
          Two-factor authentication
        </h3>
        <p class="text-xs text-muted-foreground">
          <template v-if="status.enabled">
            On since {{ enabledSince }}. Required by this workspace for password sign-in.
            {{ status.recovery_codes_remaining }} recovery codes left.
          </template>
          <template v-else>
            Required by this workspace. Set up an authenticator app to keep signing in.
          </template>
        </p>
      </div>
    </div>

    <p
      v-if="error"
      class="text-xs text-destructive"
    >
      {{ error }}
    </p>

    <div
      v-if="step === 'idle'"
      class="flex flex-wrap gap-2"
    >
      <Button
        type="button"
        variant="outline"
        size="sm"
        @click="step = 'verify-device'"
      >
        {{ status.enabled ? "Move to a new phone" : "Set up authenticator" }}
      </Button>
      <Button
        v-if="status.enabled"
        type="button"
        variant="outline"
        size="sm"
        @click="step = 'regenerate'"
      >
        New recovery codes
      </Button>
    </div>

    <form
      v-else-if="step === 'verify-device'"
      class="space-y-3"
      @submit.prevent="submitDevice"
    >
      <div class="space-y-2">
        <Label for="mfa-password">Current password</Label>
        <Input
          id="mfa-password"
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
        />
      </div>
      <div
        v-if="status.enabled"
        class="space-y-2"
      >
        <Label for="mfa-current-code">Code from your current authenticator or a recovery code</Label>
        <Input
          id="mfa-current-code"
          v-model="code"
          autocomplete="one-time-code"
          required
        />
      </div>
      <div class="flex gap-2">
        <Button
          type="submit"
          size="sm"
          :loading="busy"
        >
          Continue
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          @click="reset"
        >
          Cancel
        </Button>
      </div>
    </form>

    <form
      v-else-if="step === 'scan' && setup"
      class="space-y-3"
      @submit.prevent="submitScan"
    >
      <AuthenticatorSetup :setup="setup" />
      <div class="space-y-2">
        <Label for="mfa-new-code">Code from the new authenticator</Label>
        <Input
          id="mfa-new-code"
          v-model="code"
          inputmode="numeric"
          autocomplete="one-time-code"
          required
        />
      </div>
      <div class="flex gap-2">
        <Button
          type="submit"
          size="sm"
          :loading="busy"
        >
          Verify
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          @click="reset"
        >
          Cancel
        </Button>
      </div>
    </form>

    <form
      v-else-if="step === 'regenerate'"
      class="space-y-3"
      @submit.prevent="submitRegenerate"
    >
      <div class="space-y-2">
        <Label for="mfa-regen-code">Code from your authenticator</Label>
        <Input
          id="mfa-regen-code"
          v-model="code"
          inputmode="numeric"
          autocomplete="one-time-code"
          required
        />
        <p class="text-xs text-muted-foreground">
          Your current recovery codes stop working as soon as the new ones are made.
        </p>
      </div>
      <div class="flex gap-2">
        <Button
          type="submit"
          size="sm"
          :loading="busy"
        >
          Make new codes
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          @click="reset"
        >
          Cancel
        </Button>
      </div>
    </form>

    <RecoveryCodesPanel
      v-else-if="step === 'codes'"
      :codes="recoveryCodes"
      confirm-label="Done"
      @confirm="reset"
    />
  </section>
</template>
