<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { Plus, Share2, Trash2, Users, Variable, X } from "lucide-vue-next";

import type {
  GlobalVariableListItem,
  GlobalVariableShare,
  GlobalVariableValue,
} from "@/types/globalVariable";
import type { Team, TeamShare } from "@/types/team";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { refreshGlobalVariablesCache } from "@/composables/useExpressionCompletion";
import { formatDate } from "@/lib/utils";
import { globalVariablesApi, teamsApi } from "@/services/api";

const variables = ref<GlobalVariableListItem[]>([]);
const loading = ref(true);
const showDialog = ref(false);
const editingId = ref<string | null>(null);
const formName = ref("");
const formValue = ref("");
const formValueType = ref("auto");
const saving = ref(false);
const formError = ref("");

const showShareDialog = ref(false);
const sharingVariable = ref<GlobalVariableListItem | null>(null);
const variableShares = ref<GlobalVariableShare[]>([]);
const variableTeamShares = ref<TeamShare[]>([]);
const teams = ref<Team[]>([]);
const shareEmail = ref("");
const shareTeamId = ref("");
const sharingLoading = ref(false);
const shareError = ref("");

const VALUE_TYPE_OPTIONS = [
  { value: "auto", label: "Auto" },
  { value: "string", label: "String" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Boolean" },
  { value: "array", label: "Array" },
  { value: "object", label: "Object" },
];

const DIALOG_HISTORY_STATE = "global-variable-dialog";

function handlePopState(): void {
  if (showDialog.value) closeDialog(true);
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && showDialog.value && !saving.value) {
    event.preventDefault();
    event.stopPropagation();
    closeDialog();
  }
}

onMounted(async () => {
  await loadVariables();
  window.addEventListener("popstate", handlePopState);
  window.addEventListener("keydown", handleKeydown, true);
});

onUnmounted(() => {
  window.removeEventListener("popstate", handlePopState);
  window.removeEventListener("keydown", handleKeydown, true);
});

watch(showDialog, (open) => {
  if (open) {
    history.pushState({ [DIALOG_HISTORY_STATE]: true }, "", window.location.href);
  }
});

async function loadVariables(): Promise<void> {
  loading.value = true;
  try {
    variables.value = await globalVariablesApi.list();
  } finally {
    loading.value = false;
  }
}

function truncateValue(val: GlobalVariableValue, maxLen = 60): string {
  if (val === null || val === undefined) return "";
  const str =
    typeof val === "object" ? JSON.stringify(val) : String(val);
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

function parseFormValue(): GlobalVariableValue {
  const v = formValue.value.trim();
  if (v === "") return "";

  if (formValueType.value === "string") return v;
  if (formValueType.value === "number") {
    const n = Number(v);
    return Number.isNaN(n) ? 0 : n;
  }
  if (formValueType.value === "boolean") {
    return ["true", "1", "yes"].includes(v.toLowerCase());
  }
  if (formValueType.value === "array" || formValueType.value === "object") {
    try {
      return JSON.parse(v) as GlobalVariableValue;
    } catch {
      return v;
    }
  }

  try {
    const parsed = JSON.parse(v);
    if (typeof parsed === "string" || typeof parsed === "number" || typeof parsed === "boolean") {
      return parsed;
    }
    return parsed;
  } catch {
    return v;
  }
}

function openCreateDialog(): void {
  editingId.value = null;
  formName.value = "";
  formValue.value = "";
  formValueType.value = "auto";
  formError.value = "";
  showDialog.value = true;
}

async function openEditDialog(v: GlobalVariableListItem): Promise<void> {
  const full = await globalVariablesApi.get(v.id);
  editingId.value = full.id;
  formName.value = full.name;
  formValue.value =
    typeof full.value === "object"
      ? JSON.stringify(full.value, null, 2)
      : String(full.value);
  formValueType.value = full.value_type;
  formError.value = "";
  showDialog.value = true;
}

async function saveVariable(): Promise<void> {
  formError.value = "";
  if (!formName.value.trim()) {
    formError.value = "Name is required";
    return;
  }

  saving.value = true;
  try {
    const value = parseFormValue();
    const payload = {
      name: formName.value.trim(),
      value,
      value_type: formValueType.value === "auto" ? undefined : formValueType.value,
    };

    if (editingId.value) {
      await globalVariablesApi.update(editingId.value, payload);
      const idx = variables.value.findIndex((x) => x.id === editingId.value);
      if (idx >= 0) {
        variables.value[idx] = {
          ...variables.value[idx],
          name: payload.name,
          value,
          value_type: formValueType.value === "auto" ? _inferType(value) : formValueType.value,
        };
      }
    } else {
      const created = await globalVariablesApi.create(payload);
      variables.value.unshift({ ...created, is_shared: false, shared_by: null });
    }
    refreshGlobalVariablesCache();
    showDialog.value = false;
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    formError.value = err.response?.data?.detail || "Failed to save variable";
  } finally {
    saving.value = false;
  }
}

function _inferType(v: GlobalVariableValue): string {
  if (typeof v === "boolean") return "boolean";
  if (typeof v === "number") return "number";
  if (Array.isArray(v)) return "array";
  if (typeof v === "object" && v !== null) return "object";
  return "string";
}

async function deleteVariable(id: string, event: Event): Promise<void> {
  event.stopPropagation();
  if (!confirm("Are you sure you want to delete this variable?")) return;
  await globalVariablesApi.delete(id);
  variables.value = variables.value.filter((x) => x.id !== id);
  refreshGlobalVariablesCache();
}

function closeDialog(fromPopState = false): void {
  if (saving.value) return;
  showDialog.value = false;
  if (!fromPopState) history.back();
}

async function openShareDialog(v: GlobalVariableListItem, event: Event): Promise<void> {
  event.stopPropagation();
  sharingVariable.value = v;
  shareEmail.value = "";
  shareTeamId.value = "";
  shareError.value = "";
  sharingLoading.value = true;
  showShareDialog.value = true;
  try {
    const [userShares, teamShares, teamList] = await Promise.all([
      globalVariablesApi.listShares(v.id),
      globalVariablesApi.listTeamShares(v.id),
      teamsApi.list(),
    ]);
    variableShares.value = userShares;
    variableTeamShares.value = teamShares;
    teams.value = teamList;
  } catch {
    variableShares.value = [];
    variableTeamShares.value = [];
    teams.value = [];
  } finally {
    sharingLoading.value = false;
  }
}

async function addVariableShare(): Promise<void> {
  if (!sharingVariable.value || !shareEmail.value.trim()) return;
  shareError.value = "";
  sharingLoading.value = true;
  try {
    const share = await globalVariablesApi.addShare(sharingVariable.value.id, shareEmail.value.trim());
    if (!variableShares.value.find((s) => s.id === share.id)) {
      variableShares.value.push(share);
    }
    shareEmail.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    shareError.value = err.response?.data?.detail || "Failed to share variable";
  } finally {
    sharingLoading.value = false;
  }
}

async function removeVariableShare(userId: string): Promise<void> {
  if (!sharingVariable.value) return;
  try {
    await globalVariablesApi.removeShare(sharingVariable.value.id, userId);
    variableShares.value = variableShares.value.filter((s) => s.user_id !== userId);
  } catch {
    shareError.value = "Failed to remove share";
  }
}

const variableTeamOptions = computed(() => {
  const shared = new Set(variableTeamShares.value.map((s) => s.team_id));
  return [
    { value: "", label: "Select a team" },
    ...teams.value
      .filter((t) => !shared.has(t.id))
      .map((t) => ({ value: t.id, label: t.name })),
  ];
});

async function addVariableTeamShare(): Promise<void> {
  if (!sharingVariable.value || !shareTeamId.value) return;
  shareError.value = "";
  sharingLoading.value = true;
  try {
    const share = await globalVariablesApi.addTeamShare(sharingVariable.value.id, shareTeamId.value);
    variableTeamShares.value = [...variableTeamShares.value, share];
    shareTeamId.value = "";
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } } };
    shareError.value = err.response?.data?.detail || "Failed to share with team";
  } finally {
    sharingLoading.value = false;
  }
}

async function removeVariableTeamShare(teamId: string): Promise<void> {
  if (!sharingVariable.value) return;
  try {
    await globalVariablesApi.removeTeamShare(sharingVariable.value.id, teamId);
    variableTeamShares.value = variableTeamShares.value.filter((s) => s.team_id !== teamId);
  } catch {
    shareError.value = "Failed to remove team share";
  }
}
</script>

<template>
  <div class="overflow-x-hidden">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
      <div>
        <h2 class="text-2xl md:text-3xl font-bold tracking-tight">
          Global Variables
        </h2>
        <p class="text-muted-foreground mt-1">
          Persistent variables available across workflows via $global.name
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="gradient"
          @click="openCreateDialog"
        >
          <Plus class="w-4 h-4" />
          New Variable
        </Button>
      </div>
    </div>

    <div
      v-if="loading"
      class="space-y-3"
    >
      <Card
        v-for="i in 5"
        :key="i"
        class="p-4"
      >
        <div class="h-5 bg-muted rounded w-1/4 mb-2 animate-pulse" />
        <div class="h-4 bg-muted rounded w-3/4 animate-pulse" />
      </Card>
    </div>

    <div
      v-else-if="variables.length === 0"
      class="text-center py-16"
    >
      <div class="flex items-center justify-center w-20 h-20 rounded-2xl bg-muted/30 mx-auto mb-6">
        <Variable class="w-10 h-10 text-primary" />
      </div>
      <h3 class="text-xl font-semibold mb-2">
        No global variables yet
      </h3>
      <p class="text-muted-foreground mb-6 max-w-sm mx-auto">
        Create variables to reuse values across workflows
      </p>
      <Button
        variant="gradient"
        @click="openCreateDialog"
      >
        <Plus class="w-4 h-4" />
        Add Variable
      </Button>
    </div>

    <Card
      v-else
      class="overflow-hidden"
    >
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-border">
              <th class="text-left p-4 font-medium">
                Name
              </th>
              <th class="text-left p-4 font-medium">
                Value
              </th>
              <th class="text-left p-4 font-medium w-24">
                Type
              </th>
              <th class="text-left p-4 font-medium w-36">
                Updated
              </th>
              <th class="text-right p-4 w-24" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="v in variables"
              :key="v.id"
              class="border-b border-border/50 transition-colors hover:bg-muted/30 cursor-pointer"
              @click="openEditDialog(v)"
            >
              <td class="p-4 font-medium">
                <div class="flex items-center gap-2">
                  {{ v.name }}
                  <span
                    v-if="v.is_shared"
                    class="inline-flex items-center rounded-full bg-blue-500/10 px-2 py-0.5 text-xs font-medium text-blue-500 ring-1 ring-inset ring-blue-500/20"
                  >
                    Shared
                  </span>
                </div>
                <p
                  v-if="v.is_shared && v.shared_by"
                  class="text-xs text-muted-foreground mt-0.5"
                >
                  Shared by {{ v.shared_by }}
                </p>
              </td>
              <td class="p-4 font-mono text-muted-foreground text-xs max-w-[280px] truncate">
                {{ truncateValue(v.value) }}
              </td>
              <td class="p-4 text-muted-foreground">
                {{ v.value_type }}
              </td>
              <td class="p-4 text-muted-foreground">
                {{ formatDate(v.updated_at) }}
              </td>
              <td class="p-4 text-right">
                <div class="flex items-center justify-end gap-1">
                  <Button
                    v-if="!v.is_shared"
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-muted-foreground hover:text-primary"
                    title="Share"
                    @click.stop="openShareDialog(v, $event)"
                  >
                    <Share2 class="w-4 h-4" />
                  </Button>
                  <Button
                    v-if="!v.is_shared"
                    variant="ghost"
                    size="icon"
                    class="h-8 w-8 text-muted-foreground hover:text-destructive"
                    title="Delete"
                    @click.stop="deleteVariable(v.id, $event)"
                  >
                    <Trash2 class="w-4 h-4" />
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <!-- Create / Edit dialog -->
    <Dialog
      :open="showDialog"
      :title="editingId ? 'Edit Variable' : 'New Variable'"
      @close="closeDialog"
    >
      <form
        class="space-y-4"
        @submit.prevent="saveVariable"
      >
        <div class="space-y-2">
          <Label for="gv-name">Name</Label>
          <Input
            id="gv-name"
            v-model="formName"
            placeholder="myVariable"
            required
          />
        </div>
        <div class="space-y-2">
          <Label for="gv-value">Value</Label>
          <Textarea
            id="gv-value"
            v-model="formValue"
            placeholder="e.g. &quot;hello&quot; or {&quot;key&quot;: &quot;value&quot;} or 42"
            :rows="4"
            class="font-mono text-sm"
          />
        </div>
        <div class="space-y-2">
          <Label for="gv-type">Value Type</Label>
          <Select
            id="gv-type"
            v-model="formValueType"
            :options="VALUE_TYPE_OPTIONS"
            placeholder="Auto-detect"
          />
        </div>
        <p
          v-if="formError"
          class="text-sm text-destructive"
        >
          {{ formError }}
        </p>
        <div class="flex flex-col-reverse sm:flex-row justify-end gap-3 pt-4">
          <Button
            variant="outline"
            type="button"
            @click="() => closeDialog()"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="gradient"
            :loading="saving"
            :disabled="!formName.trim()"
          >
            {{ editingId ? "Save" : "Create" }}
          </Button>
        </div>
      </form>
    </Dialog>

    <!-- Share dialog -->
    <Dialog
      :open="showShareDialog"
      title="Share Variable"
      @close="showShareDialog = false"
    >
      <div class="space-y-4">
        <p class="text-sm text-muted-foreground">
          Share <strong>{{ sharingVariable?.name }}</strong> with other users.
          They will be able to use this variable in their workflows (read-only).
        </p>

        <div class="space-y-3">
          <div>
            <Label class="text-xs">Share with user</Label>
            <div class="flex gap-2 mt-1">
              <Input
                v-model="shareEmail"
                type="email"
                placeholder="user@example.com"
                class="flex-1"
                @keyup.enter="addVariableShare"
              />
              <Button
                :disabled="!shareEmail.trim() || sharingLoading"
                @click="addVariableShare"
              >
                Share
              </Button>
            </div>
          </div>
          <div>
            <Label class="text-xs">Share with team</Label>
            <div class="flex gap-2 mt-1">
              <Select
                v-model="shareTeamId"
                :options="variableTeamOptions"
                class="flex-1"
              />
              <Button
                :disabled="!shareTeamId || sharingLoading"
                @click="addVariableTeamShare"
              >
                <Users class="w-4 h-4" />
                Add
              </Button>
            </div>
          </div>
        </div>

        <p
          v-if="shareError"
          class="text-sm text-destructive"
        >
          {{ shareError }}
        </p>

        <div class="space-y-2">
          <Label>Shared with users:</Label>
          <div
            v-if="variableShares.length > 0"
            class="space-y-2 max-h-32 overflow-y-auto"
          >
            <div
              v-for="share in variableShares"
              :key="share.id"
              class="flex items-center justify-between p-2 rounded bg-muted/50"
            >
              <div>
                <p class="text-sm font-medium">
                  {{ share.name }}
                </p>
                <p class="text-xs text-muted-foreground">
                  {{ share.email }}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="removeVariableShare(share.user_id)"
              >
                <X class="w-4 h-4" />
              </Button>
            </div>
          </div>
          <p
            v-else-if="!sharingLoading"
            class="text-sm text-muted-foreground"
          >
            No users
          </p>
        </div>
        <div class="space-y-2">
          <Label>Shared with teams:</Label>
          <div
            v-if="variableTeamShares.length > 0"
            class="space-y-2 max-h-32 overflow-y-auto"
          >
            <div
              v-for="share in variableTeamShares"
              :key="share.id"
              class="flex items-center justify-between p-2 rounded bg-muted/50"
            >
              <p class="text-sm font-medium">
                {{ share.team_name }}
              </p>
              <Button
                variant="ghost"
                size="icon"
                class="h-8 w-8 text-muted-foreground hover:text-destructive"
                @click="removeVariableTeamShare(share.team_id)"
              >
                <X class="w-4 h-4" />
              </Button>
            </div>
          </div>
          <p
            v-else-if="!sharingLoading"
            class="text-sm text-muted-foreground"
          >
            No teams
          </p>
        </div>
      </div>
    </Dialog>
  </div>
</template>
