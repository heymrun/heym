<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { X, Plus, Users } from "lucide-vue-next";

import { templatesApi, teamsApi } from "@/services/api";
import { useToast } from "@/composables/useToast";
import type { NodeTemplate, TemplateVisibility, WorkflowTemplate } from "../types/template.types";
import type { Team } from "@/types/team";

interface Props {
  kind: "workflow" | "node";
  template: WorkflowTemplate | NodeTemplate;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  close: [];
  updated: [template: WorkflowTemplate | NodeTemplate];
}>();

const { showToast } = useToast();

const name = ref(props.template.name);
const description = ref(props.template.description ?? "");
const tagsInput = ref(props.template.tags.join(", "));
const visibility = ref<TemplateVisibility>(props.template.visibility);
const sharedWith = ref<string[]>([...props.template.shared_with]);
const sharedWithTeams = ref<string[]>([...(props.template.shared_with_teams ?? [])]);
const sharedWithInput = ref("");
const shareTeamId = ref("");
const teams = ref<Team[]>([]);
const nameError = ref("");
const loading = ref(false);
let removeOverlayDismiss: (() => void) | null = null;

function parsedTags(): string[] {
  return tagsInput.value
    .split(",")
    .map((t) => t.trim().replace(/^#/, ""))
    .filter(Boolean);
}

function addSharedWith(): void {
  const val = sharedWithInput.value.trim();
  if (!val || sharedWith.value.includes(val)) return;
  sharedWith.value = [...sharedWith.value, val];
  sharedWithInput.value = "";
}

function removeSharedWith(v: string): void {
  sharedWith.value = sharedWith.value.filter((s) => s !== v);
}

const teamOptions = computed(() => {
  const shared = new Set(sharedWithTeams.value);
  return [
    { value: "", label: "Select a team" },
    ...teams.value
      .filter((t) => !shared.has(t.id))
      .map((t) => ({ value: t.id, label: t.name })),
  ];
});

function addTeamShare(): void {
  if (!shareTeamId.value) return;
  const team = teams.value.find((t) => t.id === shareTeamId.value);
  if (team && !sharedWithTeams.value.includes(team.id)) {
    sharedWithTeams.value = [...sharedWithTeams.value, team.id];
    shareTeamId.value = "";
  }
}

function removeTeamShare(teamId: string): void {
  sharedWithTeams.value = sharedWithTeams.value.filter((id) => id !== teamId);
}

async function submit(): Promise<void> {
  nameError.value = "";
  if (!name.value.trim()) {
    nameError.value = "Name is required";
    return;
  }

  loading.value = true;
  try {
    const payload = {
      name: name.value.trim(),
      description: description.value.trim() || undefined,
      tags: parsedTags(),
      visibility: visibility.value,
      shared_with: sharedWith.value,
      shared_with_teams: sharedWithTeams.value,
    };

    let updated: WorkflowTemplate | NodeTemplate;
    if (props.kind === "workflow") {
      updated = await templatesApi.updateWorkflow(props.template.id, payload);
    } else {
      updated = await templatesApi.updateNode(props.template.id, payload);
    }

    showToast(`Template "${updated.name}" updated`, "success");
    emit("updated", updated);
    emit("close");
  } catch {
    showToast("Failed to update template", "error");
  } finally {
    loading.value = false;
  }
}

function handleKeyDown(event: KeyboardEvent): void {
  if (event.key !== "Escape") return;

  event.preventDefault();
  event.stopImmediatePropagation();
  emit("close");
}

onMounted(async () => {
  document.body.dataset.heymOverlayEscapeTrap = "true";
  window.addEventListener("keydown", handleKeyDown, true);
  removeOverlayDismiss = onDismissOverlays(() => emit("close"));

  try {
    teams.value = await teamsApi.list();
  } catch {
    teams.value = [];
  }
});

onUnmounted(() => {
  delete document.body.dataset.heymOverlayEscapeTrap;
  window.removeEventListener("keydown", handleKeyDown, true);
  removeOverlayDismiss?.();
  removeOverlayDismiss = null;
});
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm"
      @click.self="emit('close')"
    >
      <div
        class="w-full max-w-lg rounded-2xl border border-border/50 bg-card shadow-2xl flex flex-col"
        @click.stop
      >
        <!-- Header -->
        <div class="flex items-center justify-between p-6 border-b border-border/40">
          <h2 class="text-base font-semibold text-foreground">
            Edit Template
          </h2>
          <button
            class="text-muted-foreground hover:text-foreground transition-colors"
            type="button"
            @click="emit('close')"
          >
            <X class="w-5 h-5" />
          </button>
        </div>

        <!-- Form -->
        <div class="p-6 flex flex-col gap-4">
          <!-- Name -->
          <div class="flex flex-col gap-1.5">
            <label class="text-sm font-medium text-foreground">Name *</label>
            <input
              v-model="name"
              type="text"
              placeholder="Template name…"
              class="px-3 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
            >
            <p
              v-if="nameError"
              class="text-xs text-destructive"
            >
              {{ nameError }}
            </p>
          </div>

          <!-- Description -->
          <div class="flex flex-col gap-1.5">
            <label class="text-sm font-medium text-foreground">Description</label>
            <textarea
              v-model="description"
              rows="2"
              placeholder="What does this template do?"
              class="px-3 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors resize-none"
            />
          </div>

          <!-- Tags -->
          <div class="flex flex-col gap-1.5">
            <label class="text-sm font-medium text-foreground">Tags (comma-separated)</label>
            <input
              v-model="tagsInput"
              type="text"
              placeholder="ai, http, data-processing"
              class="px-3 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
            >
          </div>

          <!-- Visibility -->
          <div class="flex flex-col gap-1.5">
            <label class="text-sm font-medium text-foreground">Visibility</label>
            <div class="flex gap-4">
              <label class="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  v-model="visibility"
                  type="radio"
                  value="everyone"
                  class="accent-primary"
                >
                Everyone
              </label>
              <label class="flex items-center gap-2 cursor-pointer text-sm">
                <input
                  v-model="visibility"
                  type="radio"
                  value="specific_users"
                  class="accent-primary"
                >
                Specific users
              </label>
            </div>
          </div>

          <!-- Shared with (when specific_users) -->
          <div
            v-if="visibility === 'specific_users'"
            class="flex flex-col gap-4"
          >
            <div class="flex flex-col gap-2">
              <label class="text-sm font-medium text-foreground">Share with users (emails)</label>
              <div class="flex gap-2">
                <input
                  v-model="sharedWithInput"
                  type="text"
                  placeholder="user@example.com"
                  class="flex-1 px-3 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
                  @keydown.enter.prevent="addSharedWith"
                >
                <button
                  class="px-3 py-2 rounded-lg bg-muted hover:bg-muted/80 transition-colors border border-border/50"
                  type="button"
                  @click="addSharedWith"
                >
                  <Plus class="w-4 h-4" />
                </button>
              </div>
              <div
                v-if="sharedWith.length"
                class="flex flex-wrap gap-1.5"
              >
                <span
                  v-for="s in sharedWith"
                  :key="s"
                  class="flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-muted/60 border border-border/40"
                >
                  {{ s }}
                  <button
                    class="hover:text-destructive transition-colors"
                    type="button"
                    @click="removeSharedWith(s)"
                  >
                    <X class="w-3 h-3" />
                  </button>
                </span>
              </div>
            </div>

            <div class="flex flex-col gap-2">
              <label class="text-sm font-medium text-foreground flex items-center gap-1.5">
                <Users class="w-4 h-4" />
                Share with teams
              </label>
              <div class="flex gap-2">
                <select
                  v-model="shareTeamId"
                  class="flex-1 px-3 py-2 text-sm rounded-lg border border-border/50 bg-muted/30 focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-colors"
                >
                  <option
                    v-for="opt in teamOptions"
                    :key="opt.value"
                    :value="opt.value"
                  >
                    {{ opt.label }}
                  </option>
                </select>
                <button
                  class="px-3 py-2 rounded-lg bg-muted hover:bg-muted/80 transition-colors border border-border/50 disabled:opacity-50"
                  type="button"
                  :disabled="!shareTeamId"
                  @click="addTeamShare"
                >
                  <Plus class="w-4 h-4" />
                </button>
              </div>
              <div
                v-if="sharedWithTeams.length"
                class="flex flex-wrap gap-1.5"
              >
                <span
                  v-for="tid in sharedWithTeams"
                  :key="tid"
                  class="flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-primary/10 text-primary border border-primary/20"
                >
                  {{ teams.find(t => t.id === tid)?.name ?? tid }}
                  <button
                    class="hover:text-destructive transition-colors"
                    type="button"
                    @click="removeTeamShare(tid)"
                  >
                    <X class="w-3 h-3" />
                  </button>
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="flex justify-end gap-3 px-6 pb-6">
          <button
            class="px-4 py-2 text-sm rounded-lg border border-border/50 hover:bg-muted/60 transition-colors"
            type="button"
            @click="emit('close')"
          >
            Cancel
          </button>
          <button
            class="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
            type="button"
            :disabled="loading"
            @click="submit"
          >
            {{ loading ? "Saving…" : "Save Changes" }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
