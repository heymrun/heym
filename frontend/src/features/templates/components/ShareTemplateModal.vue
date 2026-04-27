<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { X, Plus, Users } from "lucide-vue-next";

import { useShareTemplate } from "../hooks/useShareTemplate";
import { useToast } from "@/composables/useToast";
import type { TemplateVisibility } from "../types/template.types";
import type { Team } from "@/types/team";
import { teamsApi } from "@/services/api";

interface Props {
  kind: "workflow" | "node";
  nodes?: Record<string, unknown>[];
  edges?: Record<string, unknown>[];
  nodeType?: string;
  nodeData?: Record<string, unknown>;
  canvasSnapshot?: string;
}

const props = withDefaults(defineProps<Props>(), {
  nodes: () => [],
  edges: () => [],
  nodeType: "",
  nodeData: () => ({}),
  canvasSnapshot: undefined,
});

const emit = defineEmits<{
  close: [];
  shared: [];
}>();

const { loading, shareWorkflow, shareNode } = useShareTemplate();
const { showToast } = useToast();

const name = ref("");
const description = ref("");
const tagsInput = ref("");
const visibility = ref<TemplateVisibility>("everyone");
const sharedWithInput = ref("");
const sharedWith = ref<string[]>([]);
const sharedWithTeams = ref<string[]>([]);
const shareTeamId = ref("");
const teams = ref<Team[]>([]);
const nameError = ref("");

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

  try {
    if (props.kind === "workflow") {
      await shareWorkflow({
        name: name.value.trim(),
        description: description.value.trim() || undefined,
        tags: parsedTags(),
        nodes: props.nodes,
        edges: props.edges,
        canvas_snapshot: props.canvasSnapshot,
        visibility: visibility.value,
        shared_with: sharedWith.value,
        shared_with_teams: sharedWithTeams.value,
      });
    } else {
      await shareNode({
        name: name.value.trim(),
        description: description.value.trim() || undefined,
        tags: parsedTags(),
        node_type: props.nodeType,
        node_data: props.nodeData,
        visibility: visibility.value,
        shared_with: sharedWith.value,
        shared_with_teams: sharedWithTeams.value,
      });
    }
    showToast(`Template "${name.value.trim()}" shared successfully`, "success");
    emit("shared");
    emit("close");
  } catch {
    // error handled inside useShareTemplate
  }
}

onMounted(async () => {
  try {
    teams.value = await teamsApi.list();
  } catch {
    teams.value = [];
  }
  const unsub = onDismissOverlays(() => emit("close"));
  onUnmounted(unsub);
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
            Share as Template
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
            {{ loading ? "Sharing…" : "Share Template" }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
