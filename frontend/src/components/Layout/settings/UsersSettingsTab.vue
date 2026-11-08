<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { Search } from "lucide-vue-next";

import UserAdminRow from "@/components/Layout/settings/UserAdminRow.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import {
  deactivateUser,
  listAdminUsers,
  reactivateUser,
  resetUserMfa,
  signOutUser,
} from "@/services/adminUsers";
import { apiErrorDetail } from "@/services/mfa";
import { useAuthStore } from "@/stores/auth";
import type {
  AdminUser,
  AdminUserAction,
  AdminUserStatusFilter,
  UserAdminAction,
} from "@/types/adminUsers";

const PAGE_SIZE = 50;

const authStore = useAuthStore();

const users = ref<AdminUser[]>([]);
const total = ref(0);
const offset = ref(0);
const query = ref("");
const statusFilter = ref<string | undefined>("all");
const loading = ref(false);
const busyId = ref<string | null>(null);
const error = ref("");
const notice = ref("");

const STATUS_OPTIONS = [
  { value: "all", label: "All accounts" },
  { value: "active", label: "Active" },
  { value: "deactivated", label: "Deactivated" },
];

const CONFIRM: Record<UserAdminAction, (user: AdminUser) => string> = {
  deactivate: (user) =>
    `Deactivate ${user.email}? They are signed out everywhere, their keys and tokens stop ` +
    "working, and the automatic triggers of the workflows they own are paused.",
  reactivate: (user) =>
    `Reactivate ${user.email}? They can sign in again and the triggers paused by the ` +
    "deactivation resume.",
  "sign-out": (user) => `Sign ${user.email} out of every session?`,
  "reset-mfa": (user) =>
    `Reset two-factor authentication for ${user.email}? They set up a new authenticator ` +
    "at their next password sign-in.",
};

const RUN: Record<UserAdminAction, (id: string) => Promise<AdminUserAction>> = {
  deactivate: deactivateUser,
  reactivate: reactivateUser,
  "sign-out": signOutUser,
  "reset-mfa": resetUserMfa,
};

function resultNotice(action: UserAdminAction, result: AdminUserAction): string {
  const email = result.user.email;
  const count = result.workflows_changed;
  if (action === "deactivate") return `${email} deactivated. Triggers paused on ${count} workflows.`;
  if (action === "reactivate") return `${email} reactivated. Triggers resumed on ${count} workflows.`;
  if (action === "sign-out") return `${email} was signed out everywhere.`;
  return `Two-factor authentication reset for ${email}.`;
}

function currentStatus(): AdminUserStatusFilter {
  if (statusFilter.value === "active" || statusFilter.value === "deactivated") {
    return statusFilter.value;
  }
  return "all";
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const page = await listAdminUsers({
      q: query.value,
      status: currentStatus(),
      limit: PAGE_SIZE,
      offset: offset.value,
    });
    users.value = page.items;
    total.value = page.total;
  } catch (err) {
    error.value = apiErrorDetail(err, "Failed to load users.");
  } finally {
    loading.value = false;
  }
}

async function handleAction(user: AdminUser, action: UserAdminAction): Promise<void> {
  if (!window.confirm(CONFIRM[action](user))) return;
  busyId.value = user.id;
  error.value = "";
  notice.value = "";
  try {
    const result = await RUN[action](user.id);
    users.value = users.value.map((row) => (row.id === user.id ? result.user : row));
    notice.value = resultNotice(action, result);
  } catch (err) {
    error.value = apiErrorDetail(err, "That action failed.");
  } finally {
    busyId.value = null;
  }
}

let searchTimer: number | undefined;
watch(query, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    offset.value = 0;
    void load();
  }, 250);
});

watch(statusFilter, () => {
  offset.value = 0;
  void load();
});

function page(delta: number): void {
  offset.value = Math.max(0, offset.value + delta * PAGE_SIZE);
  void load();
}

onMounted(load);
</script>

<template>
  <div
    class="space-y-4"
    data-testid="users-settings"
  >
    <p class="text-xs text-muted-foreground">
      Deactivating an account blocks every sign-in, ends its sessions, stops its MCP key and
      execution tokens, and pauses the automatic triggers of the workflows it owns.
    </p>

    <div class="flex flex-col gap-2 sm:flex-row">
      <div class="relative flex-1">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input
          v-model="query"
          placeholder="Search by name or email"
          class="pl-9"
        />
      </div>
      <Select
        v-model="statusFilter"
        :options="STATUS_OPTIONS"
        class="sm:w-44"
      />
    </div>

    <p
      v-if="error"
      class="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="text-xs text-emerald-500"
    >
      {{ notice }}
    </p>

    <p
      v-if="loading && users.length === 0"
      class="text-sm text-muted-foreground"
    >
      Loading...
    </p>
    <p
      v-else-if="users.length === 0"
      class="text-sm text-muted-foreground"
    >
      No accounts match.
    </p>

    <ul
      v-else
      class="divide-y divide-border rounded-lg border border-border"
    >
      <UserAdminRow
        v-for="user in users"
        :key="user.id"
        :user="user"
        :is-self="user.id === authStore.user?.id"
        :busy="busyId === user.id"
        @action="(action) => handleAction(user, action)"
      />
    </ul>

    <div
      v-if="total > PAGE_SIZE"
      class="flex items-center justify-between text-xs text-muted-foreground"
    >
      <span>{{ offset + 1 }}–{{ Math.min(offset + PAGE_SIZE, total) }} of {{ total }}</span>
      <div class="flex gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          :disabled="offset === 0"
          @click="page(-1)"
        >
          Previous
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          :disabled="offset + PAGE_SIZE >= total"
          @click="page(1)"
        >
          Next
        </Button>
      </div>
    </div>
  </div>
</template>
