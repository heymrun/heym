<script setup lang="ts">
import { computed } from "vue";
import { Check, KeyRound, ShieldCheck } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// 0: password + SSO side by side · 1: SSO button focused · 2: provider hand-off · 3: signed in
const step = useCycleStep(4, 1300);

const showPasswordForm = computed(() => step.value === 0);
const ssoFocused = computed(() => step.value === 1);
const atProvider = computed(() => step.value === 2);
const signedIn = computed(() => step.value === 3);
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 p-3">
    <div class="flex items-center gap-2">
      <div class="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1">
        <ShieldCheck class="h-3.5 w-3.5 text-primary" />
        <span class="text-[11px] font-semibold text-foreground">Single sign-on</span>
      </div>
      <span class="ml-auto text-[10px] font-medium text-muted-foreground transition-colors duration-300">
        {{ atProvider ? "Redirecting to your provider" : signedIn ? "Signed in" : "OpenID Connect" }}
      </span>
    </div>

    <div class="flex flex-1 flex-col justify-center gap-2 overflow-hidden rounded-lg border border-border bg-surface-sunken p-3">
      <Transition
        enter-active-class="transition-all duration-300"
        leave-active-class="transition-all duration-200"
        enter-from-class="opacity-0 -translate-y-1"
        leave-to-class="opacity-0 -translate-y-1"
        mode="out-in"
      >
        <div
          v-if="signedIn"
          key="done"
          class="flex flex-col items-center gap-1.5 py-3"
        >
          <Check class="h-5 w-5 text-emerald-500" />
          <span class="text-[11px] font-medium text-foreground">ada@example.com</span>
          <span class="text-[10px] text-muted-foreground">Account created on first sign-in</span>
        </div>

        <div
          v-else
          key="form"
          class="flex flex-col gap-2"
        >
          <div
            v-if="showPasswordForm"
            class="flex flex-col gap-1.5"
          >
            <div class="h-6 rounded border border-border bg-background" />
            <div class="h-6 rounded border border-border bg-background" />
          </div>

          <div
            v-if="showPasswordForm"
            class="text-center text-[9px] uppercase tracking-wide text-muted-foreground"
          >
            or
          </div>

          <div
            class="flex items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 transition-all duration-300"
            :class="ssoFocused || atProvider
              ? 'border-primary bg-primary/12 text-foreground'
              : 'border-border bg-background text-muted-foreground'"
          >
            <KeyRound class="h-3.5 w-3.5" />
            <span class="text-[11px] font-medium">Sign in with SSO</span>
          </div>

          <div
            class="h-1 overflow-hidden rounded-full bg-border transition-opacity duration-300"
            :class="atProvider ? 'opacity-100' : 'opacity-0'"
          >
            <div class="h-full w-1/2 animate-pulse rounded-full bg-primary" />
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>
