<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ChevronDown, Trash2, Users } from "lucide-vue-next";

import type { DataTableShare, DataTableTeamShare } from "@/types/dataTable";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { dataTablesApi, teamsApi } from "@/services/api";

const props = defineProps<{ tableId: string }>();
const emit = defineEmits<{ close: [] }>();

const email = ref("");
const permission = ref<"read" | "write">("read");
const shares = ref<DataTableShare[]>([]);
const teamShares = ref<DataTableTeamShare[]>([]);
const teams = ref<Array<{ id: string; name: string }>>([]);
const selectedTeamId = ref("");
const teamPermission = ref<"read" | "write">("read");
const loading = ref(false);
const error = ref("");

async function load() {
  loading.value = true;
  try {
    const [s, ts, t] = await Promise.all([
      dataTablesApi.listShares(props.tableId),
      dataTablesApi.listTeamShares(props.tableId),
      teamsApi.list(),
    ]);
    shares.value = s;
    teamShares.value = ts;
    teams.value = t.map((team: { id: string; name: string }) => ({ id: team.id, name: team.name }));
  } catch {
    error.value = "Failed to load shares";
  } finally {
    loading.value = false;
  }
}

async function addShare() {
  if (!email.value.trim()) return;
  try {
    await dataTablesApi.addShare(props.tableId, email.value.trim(), permission.value);
    email.value = "";
    await load();
  } catch {
    error.value = "Failed to add share";
  }
}

async function removeShare(userId: string) {
  try {
    await dataTablesApi.removeShare(props.tableId, userId);
    await load();
  } catch {
    error.value = "Failed to remove share";
  }
}

async function addTeamShare() {
  if (!selectedTeamId.value) return;
  try {
    await dataTablesApi.addTeamShare(props.tableId, selectedTeamId.value, teamPermission.value);
    selectedTeamId.value = "";
    await load();
  } catch {
    error.value = "Failed to add team share";
  }
}

async function removeTeamShare(teamId: string) {
  try {
    await dataTablesApi.removeTeamShare(props.tableId, teamId);
    await load();
  } catch {
    error.value = "Failed to remove team share";
  }
}

onMounted(load);
</script>

<template>
  <Dialog
    :open="true"
    title="Share DataTable"
    @close="emit('close')"
  >
    <div class="flex flex-col gap-4 pb-2">
      <div
        v-if="error"
        class="text-sm text-red-500"
      >
        {{ error }}
      </div>

      <!-- Share with user -->
      <div>
        <Label>Share with user</Label>
        <div class="mt-1 flex gap-2">
          <Input
            v-model="email"
            placeholder="user@example.com"
            class="flex-1"
            @keydown.enter="addShare"
          />
          <div class="relative">
            <select
              v-model="permission"
              class="h-full appearance-none rounded border bg-background py-1 pl-3 pr-7 text-sm"
            >
              <option value="read">
                Read
              </option>
              <option value="write">
                Write
              </option>
            </select>
            <ChevronDown class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          </div>
          <Button
            size="sm"
            @click="addShare"
          >
            Share
          </Button>
        </div>
      </div>

      <!-- Current user shares -->
      <div
        v-if="shares.length > 0"
        class="flex flex-col gap-2"
      >
        <div
          v-for="share in shares"
          :key="share.id"
          class="flex items-center justify-between rounded border px-3 py-2 text-sm"
        >
          <div>
            <span class="font-medium">{{ share.name }}</span>
            <span class="ml-2 text-muted-foreground">{{ share.email }}</span>
            <span class="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs">{{ share.permission }}</span>
          </div>
          <button
            class="rounded p-1 hover:bg-destructive/10"
            @click="removeShare(share.user_id)"
          >
            <Trash2 class="h-3.5 w-3.5 text-destructive" />
          </button>
        </div>
      </div>

      <!-- Share with team -->
      <div v-if="teams.length > 0">
        <Label>Share with team</Label>
        <div class="mt-1 flex gap-2">
          <div class="relative flex-1">
            <select
              v-model="selectedTeamId"
              class="h-full w-full appearance-none rounded border bg-background py-1 pl-3 pr-7 text-sm"
            >
              <option value="">
                Select a team
              </option>
              <option
                v-for="team in teams"
                :key="team.id"
                :value="team.id"
              >
                {{ team.name }}
              </option>
            </select>
            <ChevronDown class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          </div>
          <div class="relative">
            <select
              v-model="teamPermission"
              class="h-full appearance-none rounded border bg-background py-1 pl-3 pr-7 text-sm"
            >
              <option value="read">
                Read
              </option>
              <option value="write">
                Write
              </option>
            </select>
            <ChevronDown class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          </div>
          <Button
            size="sm"
            @click="addTeamShare"
          >
            Share
          </Button>
        </div>
      </div>

      <!-- Current team shares -->
      <div
        v-if="teamShares.length > 0"
        class="flex flex-col gap-2"
      >
        <div
          v-for="share in teamShares"
          :key="share.id"
          class="flex items-center justify-between rounded border px-3 py-2 text-sm"
        >
          <div>
            <Users class="mr-1 inline h-3.5 w-3.5" />
            <span class="font-medium">{{ share.team_name }}</span>
            <span class="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs">{{ share.permission }}</span>
          </div>
          <button
            class="rounded p-1 hover:bg-destructive/10"
            @click="removeTeamShare(share.team_id)"
          >
            <Trash2 class="h-3.5 w-3.5 text-destructive" />
          </button>
        </div>
      </div>
    </div>
  </Dialog>
</template>
