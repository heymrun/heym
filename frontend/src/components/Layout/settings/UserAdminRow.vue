<script setup lang="ts">
import { computed } from "vue";

import type { AdminUser, UserAdminAction } from "@/types/adminUsers";

const props = defineProps<{
  user: AdminUser;
  isSelf: boolean;
  busy: boolean;
}>();

const emit = defineEmits<{
  action: [action: UserAdminAction];
}>();

const lastSignIn = computed<string>(() => {
  const value = props.user.last_login_at;
  return value ? new Date(value).toLocaleString() : "Never";
});

const methods = computed<string>(() =>
  props.user.sign_in_methods.map((method) => (method === "sso" ? "SSO" : "Password")).join(" + "),
);

// A list row holds several of these, so they stay small rather than the 44px form buttons.
const BASE =
  "h-7 rounded-md px-2.5 text-xs font-medium whitespace-nowrap transition-colors " +
  "disabled:pointer-events-none disabled:opacity-50";
const OUTLINE = `${BASE} border border-border bg-background hover:bg-accent`;
const DANGER = `${BASE} border border-destructive/40 text-destructive hover:bg-destructive/10`;
const PRIMARY = `${BASE} bg-primary text-primary-foreground hover:bg-primary/90`;
</script>

<template>
  <li
    class="flex items-center justify-between gap-3 px-3 py-2.5"
    :data-testid="`admin-user-${user.email}`"
  >
    <div class="min-w-0 flex-1 space-y-0.5">
      <div class="flex min-w-0 items-center gap-2">
        <span class="truncate text-sm font-medium">{{ user.name }}</span>
        <span
          v-if="user.is_admin"
          class="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary"
        >Admin</span>
        <span
          v-if="!user.is_active"
          class="shrink-0 rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] text-destructive"
        >Deactivated</span>
        <span
          v-if="user.mfa_enabled"
          class="shrink-0 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-400"
        >2FA</span>
      </div>
      <p class="truncate text-xs text-muted-foreground">
        {{ user.email }}
      </p>
      <p class="truncate text-xs text-muted-foreground">
        {{ methods || "No sign-in method" }} · Last sign-in: {{ lastSignIn }}
      </p>
    </div>

    <div
      v-if="!isSelf"
      class="flex shrink-0 items-center gap-1.5"
    >
      <button
        v-if="user.mfa_enabled"
        type="button"
        :class="OUTLINE"
        :disabled="busy"
        @click="emit('action', 'reset-mfa')"
      >
        Reset 2FA
      </button>
      <button
        v-if="user.is_active"
        type="button"
        :class="OUTLINE"
        :disabled="busy"
        @click="emit('action', 'sign-out')"
      >
        Sign out
      </button>
      <button
        v-if="user.is_active"
        type="button"
        :class="DANGER"
        :disabled="busy"
        @click="emit('action', 'deactivate')"
      >
        Deactivate
      </button>
      <button
        v-else
        type="button"
        :class="PRIMARY"
        :disabled="busy"
        @click="emit('action', 'reactivate')"
      >
        Reactivate
      </button>
    </div>
    <span
      v-else
      class="shrink-0 text-xs text-muted-foreground"
    >You</span>
  </li>
</template>
