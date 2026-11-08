<script setup lang="ts">
import { computed, ref } from "vue";
import { Check, Copy } from "lucide-vue-next";

import type { MfaSetup } from "@/types/auth";

const props = defineProps<{
  setup: MfaSetup;
}>();

const copied = ref(false);
const showKey = ref(false);

// Groups of four are far easier to type into an authenticator by hand.
const groupedSecret = computed<string>(() => props.setup.secret.match(/.{1,4}/g)?.join(" ") ?? "");

async function copySecret(): Promise<void> {
  await navigator.clipboard.writeText(props.setup.secret);
  copied.value = true;
  window.setTimeout(() => {
    copied.value = false;
  }, 1500);
}
</script>

<template>
  <div class="space-y-3">
    <p class="text-sm text-muted-foreground">
      Scan this QR code with an authenticator app such as Google Authenticator, Microsoft
      Authenticator or 1Password, then enter the 6-digit code it shows.
    </p>
    <div class="flex justify-center">
      <img
        :src="setup.qr_code"
        alt="QR code for your authenticator app"
        class="w-48 h-48 rounded-lg bg-white p-2"
        data-testid="mfa-qr-code"
      >
    </div>
    <button
      v-if="!showKey"
      type="button"
      class="w-full text-xs text-muted-foreground hover:text-foreground underline underline-offset-4"
      @click="showKey = true"
    >
      Can't scan it? Enter a setup key instead
    </button>
    <div
      v-else
      class="flex items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2"
    >
      <code class="font-mono text-sm break-all">{{ groupedSecret }}</code>
      <button
        type="button"
        class="shrink-0 text-muted-foreground hover:text-foreground"
        :aria-label="copied ? 'Copied' : 'Copy setup key'"
        @click="copySecret"
      >
        <Check
          v-if="copied"
          class="w-4 h-4"
        />
        <Copy
          v-else
          class="w-4 h-4"
        />
      </button>
    </div>
  </div>
</template>
