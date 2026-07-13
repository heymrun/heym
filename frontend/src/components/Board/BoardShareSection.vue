<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ChevronDown, Trash2, Users } from "lucide-vue-next";

import type { BoardShare, BoardTeamShare } from "@/types/board";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import { boardApi, teamsApi } from "@/services/api";

const props = defineProps<{ boardId: string }>();

const email = ref("");
const permission = ref<"read" | "write">("read");
const shares = ref<BoardShare[]>([]);
const teamShares = ref<BoardTeamShare[]>([]);
const teams = ref<{ id: string; name: string }[]>([]);
const selectedTeamId = ref("");
const teamPermission = ref<"read" | "write">("read");
const error = ref("");

async function load(): Promise<void> {
  try {
    const [users, teamList, allTeams] = await Promise.all([
      boardApi.listShares(props.boardId),
      boardApi.listTeamShares(props.boardId),
      teamsApi.list(),
    ]);
    shares.value = users;
    teamShares.value = teamList;
    teams.value = allTeams.map((team) => ({ id: team.id, name: team.name }));
    error.value = "";
  } catch {
    error.value = "Failed to load shares";
  }
}

async function addShare(): Promise<void> {
  const target = email.value.trim();
  if (!target) return;
  try {
    await boardApi.addShare(props.boardId, target, permission.value);
    email.value = "";
    await load();
  } catch {
    error.value = "Failed to share the board — check the email address";
  }
}

async function removeShare(userId: string): Promise<void> {
  await boardApi.removeShare(props.boardId, userId);
  await load();
}

async function addTeamShare(): Promise<void> {
  if (!selectedTeamId.value) return;
  try {
    await boardApi.addTeamShare(props.boardId, selectedTeamId.value, teamPermission.value);
    selectedTeamId.value = "";
    await load();
  } catch {
    error.value = "Failed to share the board with the team";
  }
}

async function removeTeamShare(teamId: string): Promise<void> {
  await boardApi.removeTeamShare(props.boardId, teamId);
  await load();
}

onMounted(load);
</script>

<template>
  <div class="flex flex-col gap-2">
    <span class="text-xs font-semibold uppercase text-muted-foreground"> Share </span>
    <p
      v-if="error"
      class="text-xs text-red-500"
    >
      {{ error }}
    </p>

    <div class="flex items-center gap-2">
      <Input
        v-model="email"
        placeholder="user@example.com"
        class="h-9 flex-1"
        data-testid="board-share-email"
        @keydown.enter="addShare"
      />
      <div class="relative flex items-center">
        <select
          v-model="permission"
          class="h-9 appearance-none rounded-md border bg-background pl-3 pr-7 text-sm"
          aria-label="User permission"
        >
          <option value="read">
            Read
          </option>
          <option value="write">
            Write
          </option>
        </select>
        <ChevronDown
          class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        />
      </div>
      <Button
        size="sm"
        class="h-9 shrink-0 px-4"
        data-testid="board-share-add"
        @click="addShare"
      >
        Share
      </Button>
    </div>

    <div
      v-for="share in shares"
      :key="share.id"
      class="flex items-center justify-between rounded-md border border-border/60 px-2 py-1.5 text-sm"
      :data-testid="`board-share-${share.email}`"
    >
      <div class="min-w-0 truncate">
        <span class="font-medium">{{ share.name || share.email }}</span>
        <span class="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs">{{ share.permission }}</span>
      </div>
      <button
        class="rounded p-1 hover:bg-destructive/10"
        :aria-label="`Remove ${share.email}`"
        @click="removeShare(share.user_id)"
      >
        <Trash2 class="h-3.5 w-3.5 text-destructive" />
      </button>
    </div>

    <div
      v-if="teams.length"
      class="flex items-center gap-2"
    >
      <div class="relative flex flex-1 items-center">
        <select
          v-model="selectedTeamId"
          class="h-9 w-full appearance-none rounded-md border bg-background pl-3 pr-7 text-sm"
          aria-label="Team"
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
        <ChevronDown
          class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        />
      </div>
      <div class="relative flex items-center">
        <select
          v-model="teamPermission"
          class="h-9 appearance-none rounded-md border bg-background pl-3 pr-7 text-sm"
          aria-label="Team permission"
        >
          <option value="read">
            Read
          </option>
          <option value="write">
            Write
          </option>
        </select>
        <ChevronDown
          class="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        />
      </div>
      <Button
        size="sm"
        class="h-9 shrink-0 px-4"
        data-testid="board-team-share-add"
        @click="addTeamShare"
      >
        Share
      </Button>
    </div>

    <div
      v-for="share in teamShares"
      :key="share.id"
      class="flex items-center justify-between rounded-md border border-border/60 px-2 py-1.5 text-sm"
    >
      <div class="min-w-0 truncate">
        <Users class="mr-1 inline h-3.5 w-3.5" />
        <span class="font-medium">{{ share.team_name }}</span>
        <span class="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs">{{ share.permission }}</span>
      </div>
      <button
        class="rounded p-1 hover:bg-destructive/10"
        :aria-label="`Remove ${share.team_name}`"
        @click="removeTeamShare(share.team_id)"
      >
        <Trash2 class="h-3.5 w-3.5 text-destructive" />
      </button>
    </div>
  </div>
</template>
