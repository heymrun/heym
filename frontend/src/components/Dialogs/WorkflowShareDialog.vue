<script setup lang="ts">
import { computed, ref, watch } from "vue";
import axios from "axios";
import { Users } from "lucide-vue-next";

import type { Team } from "@/types/team";
import type {
  WorkflowShare,
  WorkflowSharePermission,
  WorkflowTeamShare,
} from "@/types/workflow";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import UserAvatar from "@/components/ui/UserAvatar.vue";
import { teamsApi, workflowApi } from "@/services/api";

interface Props {
  open: boolean;
  workflowId: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{ (e: "close"): void }>();

const PERMISSION_OPTIONS: Array<{ value: WorkflowSharePermission; label: string }> = [
  { value: "read", label: "Read" },
  { value: "write", label: "Write" },
];
const ROW_SELECT_CLASS = "h-9 min-h-0 md:h-9 rounded-lg py-1 pl-3 text-xs";

const shareEmail = ref("");
const emailPermission = ref<WorkflowSharePermission>("read");
const shareTeamId = ref("");
const teamPermission = ref<WorkflowSharePermission>("read");
const shareError = ref("");
const shareLoading = ref(false);
const shareSubmitting = ref(false);
const shareRemoving = ref<string | null>(null);
const sharePermissionSaving = ref<string | null>(null);
const workflowShares = ref<WorkflowShare[]>([]);
const workflowTeamShares = ref<WorkflowTeamShare[]>([]);
const teams = ref<Team[]>([]);

const workflowTeamOptions = computed(() => {
  const shared = new Set(workflowTeamShares.value.map((s) => s.team_id));
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

function asPermission(value: string | undefined): WorkflowSharePermission {
  return value === "write" ? "write" : "read";
}

async function loadShares(): Promise<void> {
  shareLoading.value = true;
  shareError.value = "";
  try {
    const [userShares, teamShares, teamList] = await Promise.all([
      workflowApi.listShares(props.workflowId),
      workflowApi.listTeamShares(props.workflowId),
      teamsApi.list(),
    ]);
    workflowShares.value = userShares;
    workflowTeamShares.value = teamShares;
    teams.value = teamList;
  } catch (error: unknown) {
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
    const share = await workflowApi.addShare(props.workflowId, email, emailPermission.value);
    const existingIndex = workflowShares.value.findIndex((entry) => entry.user_id === share.user_id);
    if (existingIndex >= 0) {
      workflowShares.value.splice(existingIndex, 1, share);
    } else {
      workflowShares.value.push(share);
    }
    workflowShares.value.sort((a, b) => a.email.localeCompare(b.email));
    shareEmail.value = "";
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to share workflow");
  } finally {
    shareSubmitting.value = false;
  }
}

async function updateSharePermission(
  share: WorkflowShare,
  value: string | undefined,
): Promise<void> {
  const permission = asPermission(value);
  if (permission === share.permission) return;
  sharePermissionSaving.value = share.user_id;
  shareError.value = "";
  try {
    const updated = await workflowApi.addShare(props.workflowId, share.email, permission);
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
    await workflowApi.removeShare(props.workflowId, userId);
    workflowShares.value = workflowShares.value.filter((share) => share.user_id !== userId);
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to remove share");
  } finally {
    shareRemoving.value = null;
  }
}

async function addWorkflowTeamShare(): Promise<void> {
  if (!shareTeamId.value) return;
  shareSubmitting.value = true;
  shareError.value = "";
  try {
    const share = await workflowApi.addTeamShare(
      props.workflowId,
      shareTeamId.value,
      teamPermission.value,
    );
    workflowTeamShares.value = [...workflowTeamShares.value, share];
    shareTeamId.value = "";
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to share with team");
  } finally {
    shareSubmitting.value = false;
  }
}

async function updateTeamSharePermission(
  share: WorkflowTeamShare,
  value: string | undefined,
): Promise<void> {
  const permission = asPermission(value);
  if (permission === share.permission) return;
  sharePermissionSaving.value = share.team_id;
  shareError.value = "";
  try {
    const updated = await workflowApi.addTeamShare(props.workflowId, share.team_id, permission);
    share.permission = updated.permission;
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to update permission");
  } finally {
    sharePermissionSaving.value = null;
  }
}

async function removeWorkflowTeamShare(teamId: string): Promise<void> {
  shareError.value = "";
  try {
    await workflowApi.removeTeamShare(props.workflowId, teamId);
    workflowTeamShares.value = workflowTeamShares.value.filter((s) => s.team_id !== teamId);
  } catch (error: unknown) {
    shareError.value = errorMessage(error, "Failed to remove team share");
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    await loadShares();
  },
  { immediate: true },
);
</script>

<template>
  <Dialog
    :open="open"
    title="Share workflow"
    @close="emit('close')"
  >
    <div
      class="space-y-6"
      data-testid="workflow-share-dialog"
    >
      <p class="text-sm text-muted-foreground">
        <strong class="font-medium text-foreground">Read</strong> lets collaborators view and run
        this workflow. <strong class="font-medium text-foreground">Write</strong> also lets them
        edit it. Credentials and sub-workflows used by this workflow are not shared automatically.
        Share each credential and sub-workflow with the same users or teams so recipients can run
        the workflow.
      </p>
      <div class="space-y-3">
        <div class="space-y-2">
          <Label>Invite by email</Label>
          <div class="flex gap-2">
            <Input
              v-model="shareEmail"
              placeholder="name@example.com"
              type="email"
              data-testid="workflow-share-email"
              @keydown.enter="addShare"
            />
            <Select
              :model-value="emailPermission"
              :options="PERMISSION_OPTIONS"
              :placeholder="''"
              class="w-32 shrink-0"
              data-testid="workflow-share-email-permission"
              @update:model-value="emailPermission = asPermission($event)"
            />
            <Button
              :loading="shareSubmitting"
              data-testid="workflow-share-add"
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
              :options="workflowTeamOptions"
              class="flex-1"
            />
            <Select
              :model-value="teamPermission"
              :options="PERMISSION_OPTIONS"
              :placeholder="''"
              class="w-32 shrink-0"
              data-testid="workflow-share-team-permission"
              @update:model-value="teamPermission = asPermission($event)"
            />
            <Button
              :loading="shareSubmitting"
              :disabled="!shareTeamId"
              data-testid="workflow-share-team-add"
              @click="addWorkflowTeamShare"
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
          v-else-if="workflowShares.length === 0"
          class="text-sm text-muted-foreground"
        >
          No users
        </div>
        <div
          v-else
          class="space-y-2"
        >
          <div
            v-for="share in workflowShares"
            :key="share.user_id"
            class="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
            :data-testid="`workflow-share-row-${share.email}`"
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
                :data-testid="`workflow-share-permission-${share.email}`"
                @update:model-value="updateSharePermission(share, $event)"
              />
              <Button
                variant="ghost"
                size="sm"
                class="text-destructive"
                :loading="shareRemoving === share.user_id"
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
          v-else-if="workflowTeamShares.length === 0"
          class="text-sm text-muted-foreground"
        >
          No teams
        </div>
        <div
          v-else
          class="space-y-2"
        >
          <div
            v-for="share in workflowTeamShares"
            :key="share.id"
            class="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
            :data-testid="`workflow-team-share-row-${share.team_name}`"
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
                :data-testid="`workflow-team-share-permission-${share.team_name}`"
                @update:model-value="updateTeamSharePermission(share, $event)"
              />
              <Button
                variant="ghost"
                size="sm"
                class="text-destructive"
                @click="removeWorkflowTeamShare(share.team_id)"
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
