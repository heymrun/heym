<script setup lang="ts">
import { ref, watch } from "vue";
import { X } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { alertsApi, teamsApi } from "@/services/api";
import type { Alert, AlertShareEntry, AlertTeamShareEntry } from "@/types/alerts";

interface Props {
  open: boolean;
  alert: Alert | null;
}

const props = defineProps<Props>();
const emit = defineEmits<{ close: [] }>();

const shares = ref<AlertShareEntry[]>([]);
const teamShares = ref<AlertTeamShareEntry[]>([]);
const teamOptions = ref<{ value: string; label: string }[]>([]);
const email = ref("");
const selectedTeamId = ref<string | undefined>(undefined);
const error = ref<string | null>(null);
const loading = ref(false);

async function load(): Promise<void> {
  if (!props.alert) return;
  loading.value = true;
  error.value = null;
  try {
    const [userShares, teams, allTeams] = await Promise.all([
      alertsApi.listShares(props.alert.id),
      alertsApi.listTeamShares(props.alert.id),
      teamsApi.list(),
    ]);
    shares.value = userShares;
    teamShares.value = teams;
    teamOptions.value = allTeams.map((team) => ({ value: team.id, label: team.name }));
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : "Could not load sharing";
  } finally {
    loading.value = false;
  }
}

watch(() => props.open, (isOpen) => { if (isOpen) void load(); });

async function addShare(): Promise<void> {
  if (!props.alert || !email.value.trim()) return;
  error.value = null;
  try {
    const created = await alertsApi.addShare(props.alert.id, email.value.trim());
    shares.value = [...shares.value.filter((s) => s.user_id !== created.user_id), created];
    email.value = "";
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : "Could not share the alert";
  }
}

async function removeShare(share: AlertShareEntry): Promise<void> {
  if (!props.alert) return;
  await alertsApi.removeShare(props.alert.id, share.user_id);
  shares.value = shares.value.filter((s) => s.id !== share.id);
}

async function addTeamShare(): Promise<void> {
  if (!props.alert || !selectedTeamId.value) return;
  error.value = null;
  try {
    const created = await alertsApi.addTeamShare(props.alert.id, selectedTeamId.value);
    teamShares.value = [
      ...teamShares.value.filter((s) => s.team_id !== created.team_id),
      created,
    ];
    selectedTeamId.value = undefined;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : "Could not share with the team";
  }
}

async function removeTeamShare(share: AlertTeamShareEntry): Promise<void> {
  if (!props.alert) return;
  await alertsApi.removeTeamShare(props.alert.id, share.team_id);
  teamShares.value = teamShares.value.filter((s) => s.id !== share.id);
}
</script>

<template>
  <Dialog
    :open="open"
    title="Share alert"
    size="md"
    @close="emit('close')"
  >
    <div class="space-y-5">
      <p class="text-xs text-muted-foreground">
        People you share with can see the alert and its firing history. Only you can edit, pause, or
        delete it.
      </p>

      <div class="space-y-2">
        <Label for="alert-share-email">Share with a person</Label>
        <div class="flex gap-2">
          <Input
            id="alert-share-email"
            v-model="email"
            type="email"
            placeholder="teammate@example.com"
            class="flex-1"
          />
          <Button
            :disabled="!email.trim()"
            @click="addShare"
          >
            Add
          </Button>
        </div>

        <ul
          v-if="shares.length > 0"
          class="space-y-1 pt-1"
        >
          <li
            v-for="share in shares"
            :key="share.id"
            class="flex items-center justify-between rounded-md border border-border px-3 py-1.5 text-sm"
          >
            <span class="truncate">{{ share.user_email }}</span>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Remove share"
              @click="removeShare(share)"
            >
              <X class="h-3.5 w-3.5" />
            </Button>
          </li>
        </ul>
      </div>

      <div class="space-y-2">
        <Label for="alert-share-team">Share with a team</Label>
        <div class="flex gap-2">
          <Select
            id="alert-share-team"
            v-model="selectedTeamId"
            :options="teamOptions"
            placeholder="Choose a team..."
            class="flex-1"
          />
          <Button
            :disabled="!selectedTeamId"
            @click="addTeamShare"
          >
            Add
          </Button>
        </div>

        <ul
          v-if="teamShares.length > 0"
          class="space-y-1 pt-1"
        >
          <li
            v-for="share in teamShares"
            :key="share.id"
            class="flex items-center justify-between rounded-md border border-border px-3 py-1.5 text-sm"
          >
            <span class="truncate">{{ share.team_name }}</span>
            <Button
              variant="ghost"
              size="sm"
              aria-label="Remove team share"
              @click="removeTeamShare(share)"
            >
              <X class="h-3.5 w-3.5" />
            </Button>
          </li>
        </ul>
      </div>

      <p
        v-if="error"
        class="text-sm text-destructive"
      >
        {{ error }}
      </p>
      <p
        v-if="loading"
        class="text-sm text-muted-foreground"
      >
        Loading...
      </p>
    </div>
  </Dialog>
</template>
