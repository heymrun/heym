<script setup lang="ts">
import { computed, ref } from "vue";
import { ArrowRight, ShieldCheck } from "lucide-vue-next";

import AuthenticatorSetup from "@/components/Auth/AuthenticatorSetup.vue";
import RecoveryCodesPanel from "@/components/Auth/RecoveryCodesPanel.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { apiErrorDetail } from "@/services/mfa";
import { useAuthStore } from "@/stores/auth";
import type { MfaChallenge } from "@/types/auth";

const props = defineProps<{
  challenge: MfaChallenge;
}>();

const emit = defineEmits<{
  done: [];
  cancel: [];
}>();

const authStore = useAuthStore();

const code = ref("");
const useRecoveryCode = ref(false);
const loading = ref(false);
const error = ref("");
const recoveryCodes = ref<string[] | null>(null);

const enrolling = computed<boolean>(() => props.challenge.purpose === "enroll");

async function submit(): Promise<void> {
  error.value = "";
  loading.value = true;
  try {
    const codes = await authStore.completeMfa(props.challenge, code.value.trim());
    if (codes && codes.length > 0) {
      recoveryCodes.value = codes;
      return;
    }
    emit("done");
  } catch (err) {
    error.value = apiErrorDetail(err, "That code is not valid. Try again.");
    code.value = "";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <RecoveryCodesPanel
    v-if="recoveryCodes"
    :codes="recoveryCodes"
    confirm-label="I saved my codes, continue"
    @confirm="emit('done')"
  />

  <form
    v-else
    class="space-y-5"
    data-testid="mfa-sign-in-step"
    @submit.prevent="submit"
  >
    <div class="flex items-start gap-3">
      <ShieldCheck class="w-5 h-5 text-primary shrink-0 mt-0.5" />
      <div class="space-y-1">
        <h2 class="text-base font-semibold">
          {{ enrolling ? "Set up two-factor authentication" : "Two-factor authentication" }}
        </h2>
        <p class="text-sm text-muted-foreground">
          {{
            enrolling
              ? "This workspace asks for a code from an authenticator app at every password sign-in."
              : useRecoveryCode
                ? "Enter one of the recovery codes you saved."
                : "Enter the 6-digit code from your authenticator app."
          }}
        </p>
      </div>
    </div>

    <AuthenticatorSetup
      v-if="enrolling && challenge.setup"
      :setup="challenge.setup"
    />

    <div
      v-if="error"
      class="p-3 rounded-xl bg-destructive/10 border border-destructive/20 text-destructive text-sm"
    >
      {{ error }}
    </div>

    <div class="space-y-2.5">
      <Label for="mfa-code">{{ useRecoveryCode ? "Recovery code" : "Authentication code" }}</Label>
      <Input
        id="mfa-code"
        v-model="code"
        :placeholder="useRecoveryCode ? 'XXXX-XXXX-XXXX-XXXX' : '123456'"
        :inputmode="useRecoveryCode ? 'text' : 'numeric'"
        autocomplete="one-time-code"
        autofocus
        required
        class="h-12 font-mono tracking-widest"
      />
    </div>

    <Button
      type="submit"
      variant="gradient"
      class="w-full h-12 min-h-[44px] text-base"
      :loading="loading"
    >
      {{ enrolling ? "Verify and continue" : "Sign in" }}
      <ArrowRight class="w-4 h-4 ml-1" />
    </Button>

    <div class="flex justify-between text-sm">
      <button
        v-if="!enrolling"
        type="button"
        class="text-muted-foreground hover:text-foreground underline underline-offset-4"
        @click="useRecoveryCode = !useRecoveryCode; code = ''"
      >
        {{ useRecoveryCode ? "Use the authenticator app" : "Use a recovery code" }}
      </button>
      <span v-else />
      <button
        type="button"
        class="text-muted-foreground hover:text-foreground underline underline-offset-4"
        @click="emit('cancel')"
      >
        Back
      </button>
    </div>
  </form>
</template>
