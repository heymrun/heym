<script setup lang="ts">
import { computed } from "vue";
import { ArrowRight, Check, KeyRound, Lock, Mail, ShieldCheck } from "lucide-vue-next";

import { useCycleStep } from "@/features/release-tour/useCycleStep";

// 0: password and SSO side by side · 1: SSO chosen · 2: provider hand-off · 3: signed in
const step = useCycleStep(4, 1400);

const ssoChosen = computed(() => step.value >= 1);
const atProvider = computed(() => step.value === 2);
const signedIn = computed(() => step.value === 3);

const statusLabel = computed(() => {
  if (signedIn.value) return "Signed in";
  if (atProvider.value) return "Redirecting";
  return "OpenID Connect";
});
</script>

<template>
  <div class="flex h-full w-full flex-col gap-2 p-3">
    <div class="flex items-center gap-2">
      <div class="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1">
        <ShieldCheck class="h-3.5 w-3.5 text-primary" />
        <span class="text-[11px] font-semibold text-foreground">Single sign-on</span>
      </div>
      <span class="ml-auto text-[10px] font-medium text-muted-foreground transition-colors duration-300">
        {{ statusLabel }}
      </span>
    </div>

    <div class="relative flex flex-1 flex-col justify-center gap-2 overflow-hidden rounded-lg border border-border bg-surface-sunken p-3">
      <!-- The password form stays in place and dims, so choosing SSO never empties the card. -->
      <div
        class="flex flex-col gap-1.5 transition-opacity duration-500"
        :class="ssoChosen ? 'opacity-30' : 'opacity-100'"
      >
        <div class="flex items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5">
          <Mail class="h-3 w-3 shrink-0 text-muted-foreground" />
          <span class="truncate text-[10.5px] text-muted-foreground">ada@heym.run</span>
        </div>
        <div class="flex items-center gap-2 rounded-md border border-border bg-background px-2 py-1.5">
          <Lock class="h-3 w-3 shrink-0 text-muted-foreground" />
          <span class="tracking-[0.2em] text-[10.5px] text-muted-foreground">••••••••</span>
        </div>
      </div>

      <div
        class="text-center text-[9px] uppercase tracking-wide text-muted-foreground transition-opacity duration-500"
        :class="ssoChosen ? 'opacity-30' : 'opacity-100'"
      >
        or
      </div>

      <div
        class="flex items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 transition-all duration-300"
        :class="ssoChosen
          ? 'border-primary bg-primary/12 text-foreground shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]'
          : 'border-border bg-background text-muted-foreground'"
      >
        <KeyRound class="h-3.5 w-3.5" />
        <span class="text-[11px] font-medium">Sign in with SSO</span>
      </div>

      <!-- Hand-off and result cover the card so its height never changes. -->
      <Transition
        enter-active-class="transition-all duration-300"
        leave-active-class="transition-all duration-200"
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
      >
        <div
          v-if="atProvider || signedIn"
          class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-surface-sunken/95 px-3"
        >
          <template v-if="atProvider">
            <div class="flex items-center gap-2">
              <div class="rounded-md border border-border bg-background px-2 py-1 text-[10px] font-medium text-muted-foreground">
                Heym
              </div>
              <ArrowRight class="h-3 w-3 text-primary" />
              <div class="rounded-md border border-primary/40 bg-primary/10 px-2 py-1 text-[10px] font-medium text-foreground">
                Your provider
              </div>
            </div>
            <div class="h-1 w-24 overflow-hidden rounded-full bg-border">
              <div class="h-full w-1/2 animate-pulse rounded-full bg-primary" />
            </div>
          </template>

          <template v-else>
            <div class="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500/15">
              <Check class="h-4 w-4 text-emerald-500" />
            </div>
            <span class="text-[11px] font-medium text-foreground">ada@heym.run</span>
            <span class="text-[10px] text-muted-foreground">Account created on first sign-in</span>
          </template>
        </div>
      </Transition>
    </div>
  </div>
</template>
