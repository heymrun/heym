<script setup lang="ts">
import { computed, ref, watch } from "vue";
import axios from "axios";
import { Users } from "lucide-vue-next";

import type { Team } from "@/types/team";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import UserAvatar from "@/components/ui/UserAvatar.vue";
import {
  teamsApi,
  vectorStoresApi,
  type VectorStoreShare,
  type VectorStoreSharePermission,
  type VectorStoreTeamShare,
} from "@/services/api";

interface Props {
  open: boolean;
  storeId: string;
  storeName: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{ (e: "close"): void }>();

const PERMISSION_OPTIONS: Array<{ value: VectorStoreSharePermission; label: string }> = [
  { value: "read", label: "Read" },
  { value: "write", label: "Write" },
];
const ROW_SELECT_CLASS = "h-9 min-h-0 md:h-9 rounded-lg py-1 pl-3 text-xs";

const shareEmail = ref("");
const emailPermission = ref<VectorStoreSharePermission>("read");
const shareTeamId = ref("");
const teamPermission = ref<VectorStoreSharePermission>("read");
const shareError = ref("");
const shareLoading = ref(false);
const shareSubmitting = ref(false);
const shareRemoving = ref<string | null>(null);
const sharePermissionSaving = ref<string | null>(null);
const userShares = ref<VectorStoreShare[]>([]);
const teamShares = ref<VectorStoreTeamShare[]>([]);
const teams = ref<Team[]>([]);

const teamOptions = computed(() => {
  const shared = new Set(teamShares.value.map((s) => s.team_id));
  return [
    { value: "", label: "Select a team" },
    ...teams.value.filter((t) => !shared.has(t.id)).map((t) => ({ value: t.id, label: t.name })),
  ];
});

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return fallback;
}

function asPermission(value: string | undefined): VectorStoreSharePermission {
  return value === "write" ? "write" : "read";
}

async function loadShares(): Promise<void> {
  shareLoading.value = true;
  shareError.value = "";
  shareEmail.value = "";
  shareTeamId.value = "";
  try {
    const [users, teamList, allTeams] = await Promise.all([
      vectorStoresApi.listShares(props.storeId),
      vectorStoresApi.listTeamShares(props.storeId),
      teamsApi.list(),
    ]);
    userShares.value = users;
    teamShares.value = teamList;
    teams.value = allTeams;
  } catch (error: unknown) {
    userShares.value = [];
    teamShares.value = [];
    shareError.value = errorMessage(error, "Failed to load shares");
  } finally {
    shareLoading.value = false;
  }
}

async function addShare(): Promise<void> {
  const email = shareEmail.value.trim();
  if (!email) return;
  shareSubmitting.value = true;
  shareError.value = "";
  try {
    const share = await vectorStoresApi.addShare(props.storeId, email, emailPermission.value);
    const existingIndex = userShares.value.findIndex((entry) => entry.user_id === share.user_id);
    if (existingIndex >= 0) {
      userShares.value.splice(existingIndex, 1, share);
    } else {
      userShares.value.push(share);
    }
    shareEmail.value = "";
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to share vector store");
  } finally {
    shareSubmitting.value = false;
  }
}

async function updateSharePermission(
  share: VectorStoreShare,
  value: string | undefined,
): Promise<void> {
  const permission = asPermission(value);
  if (permission === share.permission) return;
  sharePermissionSaving.value = share.user_id;
  shareError.value = "";
  try {
    const updated = await vectorStoresApi.addShare(props.storeId, share.email, permission);
    share.permission = updated.permission;
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to update permission");
  } finally {
    sharePermissionSaving.value = null;
  }
}

async function removeShare(userId: string): Promise<void> {
  shareRemoving.value = userId;
  shareError.value = "";
  try {
    await vectorStoresApi.removeShare(props.storeId, userId);
    userShares.value = userShares.value.filter((share) => share.user_id !== userId);
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to remove share");
  } finally {
    shareRemoving.value = null;
  }
}

async function addTeamShare(): Promise<void> {
  if (!shareTeamId.value) return;
  shareSubmitting.value = true;
  shareError.value = "";
  try {
    const share = await vectorStoresApi.addTeamShare(
      props.storeId,
      shareTeamId.value,
      teamPermission.value,
    );
    teamShares.value = [...teamShares.value, share];
    shareTeamId.value = "";
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to share with team");
  } finally {
    shareSubmitting.value = false;
  }
}

async function updateTeamSharePermission(
  share: VectorStoreTeamShare,
  value: string | undefined,
): Promise<void> {
  const permission = asPermission(value);
  if (permission === share.permission) return;
  sharePermissionSaving.value = share.team_id;
  shareError.value = "";
  try {
    const updated = await vectorStoresApi.addTeamShare(props.storeId, share.team_id, permission);
    share.permission = updated.permission;
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to update permission");
  } finally {
    sharePermissionSaving.value = null;
  }
}

async function removeTeamShare(teamId: string): Promise<void> {
  shareRemoving.value = teamId;
  shareError.value = "";
  try {
    await vectorStoresApi.removeTeamShare(props.storeId, teamId);
    teamShares.value = teamShares.value.filter((s) => s.team_id !== teamId);
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to remove team share");
  } finally {
    shareRemoving.value = null;
  }
}

watch(
  () => [props.open, props.storeId] as const,
  async ([open]) => {
    if (!open) return;
    await loadShares();
  },
  { immediate: true },
);
</script>

<template>
  <Dialog
    :open="open"
    title="Share Vector Store"
    @close="emit('close')"
  >
    <div
      class="space-y-6"
      data-testid="vector-store-share-dialog"
    >
      <p class="text-sm text-muted-foreground">
        <strong class="font-medium text-foreground">Read</strong> lets collaborators search
        <strong class="font-medium text-foreground">{{ storeName }}</strong> and use it in their
        workflows. <strong class="font-medium text-foreground">Write</strong> also lets them add
        and delete documents. Only you can rename, delete or share the store.
      </p>
      <div class="space-y-3">
        <div class="space-y-2">
          <Label>Invite by email</Label>
          <div class="flex gap-2">
            <Input
              v-model="shareEmail"
              placeholder="name@example.com"
              type="email"
              data-testid="vector-store-share-email"
              @keydown.enter="addShare"
            />
            <Select
              :model-value="emailPermission"
              :options="PERMISSION_OPTIONS"
              :placeholder="''"
              class="w-32 shrink-0"
              data-testid="vector-store-share-email-permission"
              @update:model-value="emailPermission = asPermission($event)"
            />
            <Button
              :loading="shareSubmitting"
              :disabled="!shareEmail.trim()"
              data-testid="vector-store-share-add"
              @click="addShare"
            >
              Add
            </Button>
          </div>
        </div>
        <div class="space-y-2">
          <Label>Share with team</Label>
          <div class="flex gap-2">
            <Select
              v-model="shareTeamId"
              :options="teamOptions"
              class="flex-1"
            />
            <Select
              :model-value="teamPermission"
              :options="PERMISSION_OPTIONS"
              :placeholder="''"
              class="w-32 shrink-0"
              data-testid="vector-store-share-team-permission"
              @update:model-value="teamPermission = asPermission($event)"
            />
            <Button
              :loading="shareSubmitting"
              :disabled="!shareTeamId"
              data-testid="vector-store-share-team-add"
              @click="addTeamShare"
            >
              <Users class="w-4 h-4" />
              Add
            </Button>
          </div>
        </div>
        <p
          v-if="shareError"
          class="text-xs text-destructive"
        >
          {{ shareError }}
        </p>
      </div>
      <div class="space-y-2">
        <Label>Shared with users</Label>
        <div
          v-if="shareLoading"
          class="text-sm text-muted-foreground"
        >
          Loading...
        </div>
        <div
          v-else-if="userShares.length === 0"
          class="text-sm text-muted-foreground"
        >
          No users
        </div>
        <div
          v-else
          class="space-y-2"
        >
          <div
            v-for="share in userShares"
            :key="share.user_id"
            class="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
            :data-testid="`vector-store-share-row-${share.email}`"
          >
            <div class="flex min-w-0 items-center gap-2.5">
              <UserAvatar
                :user-id="share.user_id"
                :name="share.name"
                :email="share.email"
                class="h-8 w-8 bg-primary/10 text-xs font-semibold text-primary dark:bg-primary/20 dark:text-accent-foreground"
              />
              <div class="min-w-0">
                <div class="truncate text-sm font-medium">
                  {{ share.name }}
                </div>
                <div class="truncate text-xs text-muted-foreground">
                  {{ share.email }}
                </div>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <Select
                :model-value="share.permission"
                :options="PERMISSION_OPTIONS"
                :placeholder="''"
                :disabled="sharePermissionSaving === share.user_id"
                :select-class="ROW_SELECT_CLASS"
                class="w-28"
                :data-testid="`vector-store-share-permission-${share.email}`"
                @update:model-value="updateSharePermission(share, $event)"
              />
              <Button
                variant="ghost"
                size="sm"
                class="text-destructive"
                :loading="shareRemoving === share.user_id"
                :data-testid="`vector-store-share-remove-${share.email}`"
                @click="removeShare(share.user_id)"
              >
                Remove
              </Button>
            </div>
          </div>
        </div>
      </div>
      <div class="space-y-2">
        <Label>Shared with teams</Label>
        <div
          v-if="shareLoading"
          class="text-sm text-muted-foreground"
        >
          Loading...
        </div>
        <div
          v-else-if="teamShares.length === 0"
          class="text-sm text-muted-foreground"
        >
          No teams
        </div>
        <div
          v-else
          class="space-y-2"
        >
          <div
            v-for="share in teamShares"
            :key="share.id"
            class="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
            :data-testid="`vector-store-team-share-row-${share.team_name}`"
          >
            <div class="min-w-0 truncate text-sm font-medium">
              {{ share.team_name }}
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <Select
                :model-value="share.permission"
                :options="PERMISSION_OPTIONS"
                :placeholder="''"
                :disabled="sharePermissionSaving === share.team_id"
                :select-class="ROW_SELECT_CLASS"
                class="w-28"
                :data-testid="`vector-store-team-share-permission-${share.team_name}`"
                @update:model-value="updateTeamSharePermission(share, $event)"
              />
              <Button
                variant="ghost"
                size="sm"
                class="text-destructive"
                :loading="shareRemoving === share.team_id"
                :data-testid="`vector-store-team-share-remove-${share.team_name}`"
                @click="removeTeamShare(share.team_id)"
              >
                Remove
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Dialog>
</template>
