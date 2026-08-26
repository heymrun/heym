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
  <!-- The tour slot is a fixed 168px, so every row below is sized to fit inside it. -->
  <div class="flex h-full w-full flex-col gap-1.5 p-2.5">
    <div class="flex h-[20px] shrink-0 items-center gap-1.5">
      <div class="flex items-center gap-1 rounded border border-primary/30 bg-primary/10 px-1.5 py-0.5">
        <ShieldCheck class="h-3 w-3 text-primary" />
        <span class="text-[10px] font-semibold leading-none text-foreground">Single sign-on</span>
      </div>
      <span class="ml-auto text-[9px] font-medium leading-none text-muted-foreground transition-colors duration-300">
        {{ statusLabel }}
      </span>
    </div>

    <div class="relative min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-surface-sunken p-2">
      <div class="flex h-full flex-col justify-center gap-1.5">
        <!-- The password form stays put and dims, so choosing SSO never empties the card. -->
        <div
          class="flex h-[22px] items-center gap-1.5 rounded border border-border bg-background px-1.5 transition-opacity duration-500"
          :class="ssoChosen ? 'opacity-30' : 'opacity-100'"
        >
          <Mail class="h-2.5 w-2.5 shrink-0 text-muted-foreground" />
          <span class="truncate text-[10px] leading-none text-muted-foreground">ada@heym.run</span>
        </div>
        <div
          class="flex h-[22px] items-center gap-1.5 rounded border border-border bg-background px-1.5 transition-opacity duration-500"
          :class="ssoChosen ? 'opacity-30' : 'opacity-100'"
        >
          <Lock class="h-2.5 w-2.5 shrink-0 text-muted-foreground" />
          <span class="text-[10px] leading-none tracking-[0.18em] text-muted-foreground">••••••</span>
        </div>

        <div
          class="text-center text-[8px] uppercase leading-none tracking-wide text-muted-foreground transition-opacity duration-500"
          :class="ssoChosen ? 'opacity-30' : 'opacity-100'"
        >
          or
        </div>

        <div
          class="flex h-[26px] items-center justify-center gap-1.5 rounded border transition-all duration-300"
          :class="ssoChosen
            ? 'border-primary bg-primary/12 text-foreground'
            : 'border-border bg-background text-muted-foreground'"
        >
          <KeyRound class="h-3 w-3" />
          <span class="text-[10px] font-medium leading-none">Sign in with SSO</span>
        </div>
      </div>

      <!-- Hand-off and result cover the box, so its height never changes. -->
      <Transition
        enter-active-class="transition-opacity duration-300"
        leave-active-class="transition-opacity duration-200"
        enter-from-class="opacity-0"
        leave-to-class="opacity-0"
      >
        <div
          v-if="atProvider || signedIn"
          class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-surface-sunken px-2"
        >
          <template v-if="atProvider">
            <div class="flex items-center gap-1.5">
              <span class="rounded border border-border bg-background px-2 py-1 text-[11px] font-medium leading-none text-muted-foreground">
                Heym
              </span>
              <ArrowRight class="h-3 w-3 text-primary" />
              <span class="rounded border border-primary/40 bg-primary/10 px-2 py-1 text-[11px] font-medium leading-none text-foreground">
                Your provider
              </span>
            </div>
            <div class="h-1 w-24 overflow-hidden rounded-full bg-border">
              <div class="h-full w-1/2 animate-pulse rounded-full bg-primary" />
            </div>
          </template>

          <template v-else>
            <div class="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500/15">
              <Check class="h-4 w-4 text-emerald-500" />
            </div>
            <span class="text-[12px] font-medium leading-none text-foreground">ada@heym.run</span>
            <span class="text-[10.5px] leading-none text-muted-foreground">Account created on first sign-in</span>
          </template>
        </div>
      </Transition>
    </div>
  </div>
</template>
