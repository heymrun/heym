<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  Database,
  Edit2,
  Key,
  Layout,
  LayoutTemplate,
  Plus,
  Trash2,
  UserPlus,
  Users,
  Variable,
  Workflow,
  X,
} from "lucide-vue-next";

import type {
  Team,
  TeamDetail,
  TeamMember,
  TeamSharedEntities,
} from "@/types/team";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { teamsApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const authStore = useAuthStore();
const teams = ref<Team[]>([]);
const loading = ref(true);
const showCreateDialog = ref(false);
const showDetailDialog = ref(false);
const showEditDialog = ref(false);
const selectedTeam = ref<TeamDetail | null>(null);
const newTeamName = ref("");
const newTeamDescription = ref("");
const editTeamName = ref("");
const editTeamDescription = ref("");
const addMemberEmail = ref("");
const creating = ref(false);
const editing = ref(false);
const addingMember = ref(false);
const createError = ref("");
const editError = ref("");
const addMemberError = ref("");
const sharedEntities = ref<TeamSharedEntities | null>(null);
const loadingSharedEntities = ref(false);

const unsubOverlays = onDismissOverlays(() => {
  showCreateDialog.value = false;
  closeDetailDialog();
});

onMounted(async () => {
  await loadTeams();
});

onUnmounted(() => {
  unsubOverlays();
});

async function loadTeams(): Promise<void> {
  loading.value = true;
  try {
    teams.value = await teamsApi.list();
  } finally {
    loading.value = false;
  }
}

function openCreateDialog(): void {
  newTeamName.value = "";
  newTeamDescription.value = "";
  createError.value = "";
  showCreateDialog.value = true;
}

async function createTeam(): Promise<void> {
  if (!newTeamName.value.trim()) return;
  creating.value = true;
  createError.value = "";
  try {
    const team = await teamsApi.create({
      name: newTeamName.value.trim(),
      description: newTeamDescription.value.trim() || null,
    });
    teams.value = [team, ...teams.value];
    showCreateDialog.value = false;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    createError.value = err.response?.data?.detail || "Failed to create team";
  } finally {
    creating.value = false;
  }
}

async function openDetailDialog(team: Team): Promise<void> {
  try {
    selectedTeam.value = await teamsApi.get(team.id);
    showDetailDialog.value = true;
    addMemberEmail.value = "";
    addMemberError.value = "";
    sharedEntities.value = null;
    loadingSharedEntities.value = true;
    try {
      sharedEntities.value = await teamsApi.getSharedEntities(team.id);
    } finally {
      loadingSharedEntities.value = false;
    }
  } catch {
    selectedTeam.value = null;
  }
}

function closeDetailDialog(): void {
  showDetailDialog.value = false;
  selectedTeam.value = null;
  showEditDialog.value = false;
  sharedEntities.value = null;
}

function navigateToWorkflow(id: string): void {
  closeDetailDialog();
  router.push({ name: "editor", params: { id } });
}

function navigateToTab(tab: string): void {
  closeDetailDialog();
  router.push({ path: "/", query: { tab } });
}

function openEditDialog(): void {
  if (!selectedTeam.value) return;
  editTeamName.value = selectedTeam.value.name;
  editTeamDescription.value = selectedTeam.value.description || "";
  editError.value = "";
  showEditDialog.value = true;
}

async function saveEdit(): Promise<void> {
  if (!selectedTeam.value) return;
  editing.value = true;
  editError.value = "";
  try {
    const updated = await teamsApi.update(selectedTeam.value.id, {
      name: editTeamName.value.trim(),
      description: editTeamDescription.value.trim() || null,
    });
    selectedTeam.value = {
      ...selectedTeam.value,
      name: updated.name,
      description: updated.description,
    };
    const idx = teams.value.findIndex((t) => t.id === updated.id);
    if (idx >= 0) {
      teams.value[idx] = { ...teams.value[idx], ...updated };
    }
    showEditDialog.value = false;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    editError.value = err.response?.data?.detail || "Failed to update team";
  } finally {
    editing.value = false;
  }
}

async function addMember(): Promise<void> {
  if (!selectedTeam.value || !addMemberEmail.value.trim()) return;
  addingMember.value = true;
  addMemberError.value = "";
  try {
    const updated = await teamsApi.addMember(selectedTeam.value.id, {
      email: addMemberEmail.value.trim(),
    });
    selectedTeam.value = updated;
    addMemberEmail.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    addMemberError.value = err.response?.data?.detail || "Failed to add member";
  } finally {
    addingMember.value = false;
  }
}

async function removeMember(userId: string): Promise<void> {
  if (!selectedTeam.value) return;
  if (userId === selectedTeam.value.creator_id) return;
  if (!confirm("Remove this member from the team?")) return;
  try {
    await teamsApi.removeMember(selectedTeam.value.id, userId);
    const updated = await teamsApi.get(selectedTeam.value.id);
    selectedTeam.value = updated;
  } catch {
    addMemberError.value = "Failed to remove member";
  }
}

async function deleteTeam(): Promise<void> {
  if (!selectedTeam.value) return;
  if (selectedTeam.value.creator_id !== authStore.user?.id) return;
  if (!confirm("Delete this team? All team shares will be removed.")) return;
  try {
    await teamsApi.delete(selectedTeam.value.id);
    teams.value = teams.value.filter((t) => t.id !== selectedTeam.value!.id);
    closeDetailDialog();
  } catch {
    addMemberError.value = "Failed to delete team";
  }
}

function isCreator(team: Team): boolean {
  return team.creator_id === authStore.user?.id;
}

function isCreatorMember(member: TeamMember): boolean {
  return member.user_id === selectedTeam.value?.creator_id;
}

function hasAnySharedEntities(entities: TeamSharedEntities | null): boolean {
  if (!entities) return false;
  return (
    entities.workflows.length > 0 ||
    entities.credentials.length > 0 ||
    entities.global_variables.length > 0 ||
    entities.vector_stores.length > 0 ||
    entities.workflow_templates.length > 0 ||
    entities.node_templates.length > 0
  );
}
</script>

<template>
  <div class="overflow-x-hidden">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
      <div>
        <h2 class="text-2xl md:text-3xl font-bold tracking-tight">
          Teams
        </h2>
        <p class="text-muted-foreground mt-1">
          Create teams and share workflows, credentials, and more
        </p>
      </div>
      <Button
        variant="gradient"
        @click="openCreateDialog"
      >
        <Plus class="w-4 h-4" />
        New Team
      </Button>
    </div>

    <div
      v-if="loading"
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
    >
      <Card
        v-for="i in 3"
        :key="i"
        class="p-4"
      >
        <div class="flex items-start gap-3 mb-3">
          <div class="w-10 h-10 rounded-lg bg-muted animate-pulse" />
          <div class="flex-1">
            <div class="h-4 bg-muted rounded w-2/3 mb-2 animate-pulse" />
            <div class="h-3 bg-muted rounded w-1/3 animate-pulse" />
          </div>
        </div>
        <div class="h-3 bg-muted rounded w-full animate-pulse" />
      </Card>
    </div>

    <div
      v-else-if="teams.length === 0"
      class="text-center py-16"
    >
      <div class="empty-state-icon flex items-center justify-center w-20 h-20 rounded-2xl mx-auto mb-6">
        <Users class="w-10 h-10 text-primary" />
      </div>
      <h3 class="text-xl font-semibold mb-2">
        No teams yet
      </h3>
      <p class="text-muted-foreground mb-6 max-w-sm mx-auto">
        Create a team to share workflows, credentials, and variables with others
      </p>
      <Button
        variant="gradient"
        @click="openCreateDialog"
      >
        <Plus class="w-4 h-4" />
        Create Team
      </Button>
    </div>

    <div
      v-else
      class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"
    >
      <Card
        v-for="team in teams"
        :key="team.id"
        class="p-4 cursor-pointer group hover:border-primary/30 transition-colors"
        @click="openDetailDialog(team)"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="flex items-center gap-3 min-w-0">
            <div class="team-icon flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0">
              <Users class="w-5 h-5" />
            </div>
            <div class="min-w-0">
              <h3 class="font-semibold text-sm truncate">
                {{ team.name }}
              </h3>
              <p class="text-xs text-muted-foreground">
                {{ team.member_count }} member{{ team.member_count !== 1 ? "s" : "" }}
              </p>
            </div>
          </div>
        </div>
        <p
          v-if="team.description"
          class="text-xs text-muted-foreground mt-2 line-clamp-2"
        >
          {{ team.description }}
        </p>
        <p class="text-xs text-muted-foreground mt-2">
          Created by {{ team.creator_name }}
        </p>
      </Card>
    </div>

    <Dialog
      :open="showCreateDialog"
      title="Create Team"
      @close="showCreateDialog = false"
    >
      <div class="space-y-4">
        <div>
          <Label for="new-name">Name</Label>
          <Input
            id="new-name"
            v-model="newTeamName"
            placeholder="Team name"
            class="mt-1"
            @keyup.enter="createTeam"
          />
        </div>
        <div>
          <Label for="new-desc">Description (optional)</Label>
          <Textarea
            id="new-desc"
            v-model="newTeamDescription"
            placeholder="Brief description"
            :rows="2"
            class="mt-1"
          />
        </div>
        <p
          v-if="createError"
          class="text-sm text-destructive"
        >
          {{ createError }}
        </p>
        <div class="flex justify-end gap-2">
          <Button
            variant="outline"
            @click="showCreateDialog = false"
          >
            Cancel
          </Button>
          <Button
            :disabled="!newTeamName.trim() || creating"
            @click="createTeam"
          >
            Create
          </Button>
        </div>
      </div>
    </Dialog>

    <Dialog
      :open="showDetailDialog"
      :title="selectedTeam?.name ?? 'Team'"
      @close="closeDetailDialog"
    >
      <div
        v-if="selectedTeam"
        class="space-y-4"
      >
        <div
          v-if="!showEditDialog"
          class="flex items-start justify-between gap-4"
        >
          <div>
            <p
              v-if="selectedTeam.description"
              class="text-sm text-muted-foreground"
            >
              {{ selectedTeam.description }}
            </p>
            <p class="text-xs text-muted-foreground mt-1">
              Created by {{ selectedTeam.creator_name }} · {{ selectedTeam.member_count }} member{{ selectedTeam.member_count !== 1 ? "s" : "" }}
            </p>
          </div>
          <div
            v-if="isCreator(selectedTeam)"
            class="flex gap-1 shrink-0"
          >
            <Button
              variant="ghost"
              size="icon"
              class="h-8 w-8"
              title="Edit"
              @click="openEditDialog"
            >
              <Edit2 class="w-4 h-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              class="h-8 w-8 text-destructive hover:text-destructive"
              title="Delete team"
              @click="deleteTeam"
            >
              <Trash2 class="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div
          v-else
          class="space-y-4"
        >
          <div>
            <Label for="edit-name">Name</Label>
            <Input
              id="edit-name"
              v-model="editTeamName"
              class="mt-1"
            />
          </div>
          <div>
            <Label for="edit-desc">Description</Label>
            <Textarea
              id="edit-desc"
              v-model="editTeamDescription"
              :rows="2"
              class="mt-1"
            />
          </div>
          <p
            v-if="editError"
            class="text-sm text-destructive"
          >
            {{ editError }}
          </p>
          <div class="flex justify-end gap-2">
            <Button
              variant="outline"
              @click="showEditDialog = false"
            >
              Cancel
            </Button>
            <Button
              :disabled="editing"
              @click="saveEdit"
            >
              Save
            </Button>
          </div>
        </div>

        <div
          v-if="!showEditDialog"
          class="flex gap-2"
        >
          <Input
            v-model="addMemberEmail"
            type="email"
            placeholder="user@example.com"
            class="flex-1"
            @keyup.enter="addMember"
          />
          <Button
            :disabled="!addMemberEmail.trim() || addingMember"
            @click="addMember"
          >
            <UserPlus class="w-4 h-4" />
            Add
          </Button>
        </div>

        <p
          v-if="addMemberError"
          class="text-sm text-destructive"
        >
          {{ addMemberError }}
        </p>

        <div
          v-if="!showEditDialog"
          class="space-y-2"
        >
          <Label>Members</Label>
          <div class="space-y-2 max-h-48 overflow-y-auto">
            <div
              v-for="member in selectedTeam.members"
              :key="member.id"
              class="flex items-center justify-between p-2 rounded bg-muted/50"
            >
              <div>
                <p class="text-sm font-medium">
                  {{ member.name }}
                  <span
                    v-if="isCreatorMember(member)"
                    class="text-xs text-muted-foreground"
                  >
                    (creator)
                  </span>
                </p>
                <p class="text-xs text-muted-foreground">
                  {{ member.email }}
                </p>
              </div>
              <Button
                v-if="!isCreatorMember(member)"
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="removeMember(member.user_id)"
              >
                <X class="w-4 h-4" />
              </Button>
            </div>
          </div>
        </div>

        <div
          v-if="!showEditDialog"
          class="space-y-2"
        >
          <Label>Shared with team</Label>
          <div
            v-if="loadingSharedEntities"
            class="py-4 text-center text-sm text-muted-foreground"
          >
            Loading...
          </div>
          <div
            v-else-if="!hasAnySharedEntities(sharedEntities)"
            class="py-4 text-center text-sm text-muted-foreground rounded bg-muted/30"
          >
            No resources shared with this team yet.
          </div>
          <div
            v-else
            class="space-y-3 max-h-64 overflow-y-auto"
          >
            <div
              v-if="sharedEntities?.workflows.length"
              class="space-y-1"
            >
              <p class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Workflow class="w-3.5 h-3.5" />
                Workflows
              </p>
              <div class="space-y-1">
                <button
                  v-for="item in sharedEntities.workflows"
                  :key="item.id"
                  type="button"
                  class="w-full text-left text-sm px-2 py-1.5 rounded hover:bg-muted/50 truncate"
                  @click="navigateToWorkflow(item.id)"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
            <div
              v-if="sharedEntities?.credentials.length"
              class="space-y-1"
            >
              <p class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Key class="w-3.5 h-3.5" />
                Credentials
              </p>
              <div class="space-y-1">
                <button
                  v-for="item in sharedEntities.credentials"
                  :key="item.id"
                  type="button"
                  class="w-full text-left text-sm px-2 py-1.5 rounded hover:bg-muted/50 truncate"
                  @click="navigateToTab('credentials')"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
            <div
              v-if="sharedEntities?.global_variables.length"
              class="space-y-1"
            >
              <p class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Variable class="w-3.5 h-3.5" />
                Variables
              </p>
              <div class="space-y-1">
                <button
                  v-for="item in sharedEntities.global_variables"
                  :key="item.id"
                  type="button"
                  class="w-full text-left text-sm px-2 py-1.5 rounded hover:bg-muted/50 truncate"
                  @click="navigateToTab('globalvariables')"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
            <div
              v-if="sharedEntities?.vector_stores.length"
              class="space-y-1"
            >
              <p class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Database class="w-3.5 h-3.5" />
                Vector Stores
              </p>
              <div class="space-y-1">
                <button
                  v-for="item in sharedEntities.vector_stores"
                  :key="item.id"
                  type="button"
                  class="w-full text-left text-sm px-2 py-1.5 rounded hover:bg-muted/50 truncate"
                  @click="navigateToTab('vectorstores')"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
            <div
              v-if="sharedEntities?.workflow_templates.length"
              class="space-y-1"
            >
              <p class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <LayoutTemplate class="w-3.5 h-3.5" />
                Workflow Templates
              </p>
              <div class="space-y-1">
                <button
                  v-for="item in sharedEntities.workflow_templates"
                  :key="item.id"
                  type="button"
                  class="w-full text-left text-sm px-2 py-1.5 rounded hover:bg-muted/50 truncate"
                  @click="navigateToTab('templates')"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
            <div
              v-if="sharedEntities?.node_templates.length"
              class="space-y-1"
            >
              <p class="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                <Layout class="w-3.5 h-3.5" />
                Node Templates
              </p>
              <div class="space-y-1">
                <button
                  v-for="item in sharedEntities.node_templates"
                  :key="item.id"
                  type="button"
                  class="w-full text-left text-sm px-2 py-1.5 rounded hover:bg-muted/50 truncate"
                  @click="navigateToTab('templates')"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Dialog>
  </div>
</template>

<style scoped>
.empty-state-icon {
  background: linear-gradient(
    135deg,
    hsl(var(--primary) / 0.15) 0%,
    hsl(var(--accent-blue) / 0.1) 100%
  );
  box-shadow:
    0 2px 8px hsl(var(--primary) / 0.1),
    inset 0 1px 0 hsl(0 0% 100% / 0.1);
}

.team-icon {
  transition: all 0.3s ease;
}
</style>
