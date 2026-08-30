<script setup lang="ts">
import { nextTick, ref } from "vue";
import { History, Save, Search, Settings2 } from "lucide-vue-next";

import { useWorkflowStore } from "@/stores/workflow";

const emit = defineEmits<{
  (event: "home"): void;
  (event: "save"): void;
  (event: "history"): void;
  (event: "search"): void;
  (event: "settings"): void;
}>();

const workflowStore = useWorkflowStore();
const editingTitle = ref(false);
const editingDescription = ref(false);
const titleDraft = ref("");
const descriptionDraft = ref("");
const titleInput = ref<HTMLInputElement | null>(null);
const descriptionInput = ref<HTMLInputElement | null>(null);

function startTitleEdit(): void {
  titleDraft.value = workflowStore.currentWorkflow?.name ?? "";
  editingTitle.value = true;
  void nextTick(() => titleInput.value?.select());
}

async function commitTitleEdit(): Promise<void> {
  const title = titleDraft.value.trim();
  if (title && title !== workflowStore.currentWorkflow?.name) {
    await workflowStore.updateMetadata(title, workflowStore.currentWorkflow?.description ?? null);
  }
  editingTitle.value = false;
}

function cancelTitleEdit(): void {
  editingTitle.value = false;
}

function startDescriptionEdit(): void {
  descriptionDraft.value = workflowStore.currentWorkflow?.description ?? "";
  editingDescription.value = true;
  void nextTick(() => descriptionInput.value?.focus());
}

async function commitDescriptionEdit(): Promise<void> {
  const description = descriptionDraft.value.trim() || null;
  if (description !== (workflowStore.currentWorkflow?.description ?? null)) {
    await workflowStore.updateMetadata(workflowStore.currentWorkflow?.name ?? "", description);
  }
  editingDescription.value = false;
}

function cancelDescriptionEdit(): void {
  editingDescription.value = false;
}
</script>

<template>
  <header class="flex h-16 shrink-0 items-center justify-between border-b border-border/70 bg-background px-4">
    <div class="flex min-w-0 items-center gap-2.5">
      <button
        type="button"
        class="shrink-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        aria-label="Return to dashboard"
        @click="emit('home')"
      >
        <img
          src="/fav.svg"
          alt="Heym"
          class="h-8 w-8"
        >
      </button>
      <div class="min-w-0">
        <input
          v-if="editingTitle"
          ref="titleInput"
          v-model="titleDraft"
          class="block w-full max-w-44 border-b border-primary bg-transparent text-sm font-bold leading-4 outline-none"
          maxlength="100"
          aria-label="Workflow name"
          @blur="commitTitleEdit"
          @keydown.enter.prevent="commitTitleEdit"
          @keydown.escape.prevent="cancelTitleEdit"
        >
        <button
          v-else
          type="button"
          data-testid="mobile-workflow-title"
          class="block max-w-44 truncate text-left text-sm font-bold leading-4 hover:text-primary"
          :title="workflowStore.currentWorkflow?.name ?? 'Workflow'"
          @click="startTitleEdit"
        >
          {{ workflowStore.currentWorkflow?.name ?? "Workflow" }}
        </button>
        <input
          v-if="editingDescription"
          ref="descriptionInput"
          v-model="descriptionDraft"
          class="block w-full max-w-44 border-b border-primary bg-transparent text-[11px] leading-4 text-muted-foreground outline-none"
          maxlength="300"
          placeholder="Add description..."
          aria-label="Workflow description"
          @blur="commitDescriptionEdit"
          @keydown.enter.prevent="commitDescriptionEdit"
          @keydown.escape.prevent="cancelDescriptionEdit"
        >
        <button
          v-else
          type="button"
          class="block max-w-44 truncate text-left text-[11px] leading-4 text-muted-foreground hover:text-foreground"
          :title="workflowStore.currentWorkflow?.description ?? 'Add description...'"
          @click="startDescriptionEdit"
        >
          {{ workflowStore.currentWorkflow?.description || "Add description..." }}
        </button>
      </div>
    </div>
    <div class="flex shrink-0 items-center gap-0.5 text-muted-foreground">
      <button
        class="mobile-workflow-action relative"
        title="Save workflow"
        :aria-label="workflowStore.hasUnsavedChanges ? 'Save workflow (unsaved changes)' : 'Save workflow'"
        @click="emit('save')"
      >
        <Save class="h-4 w-4" />
        <span
          v-if="workflowStore.hasUnsavedChanges"
          class="absolute right-0.5 top-0.5 h-2 w-2 rounded-full border border-background bg-orange-400"
          aria-hidden="true"
        />
      </button>
      <button
        class="mobile-workflow-action"
        title="Execution history"
        @click="emit('history')"
      >
        <History class="h-4 w-4" />
      </button>
      <button
        class="mobile-workflow-action"
        title="Search"
        @click="emit('search')"
      >
        <Search class="h-4 w-4" />
      </button>
      <button
        class="mobile-workflow-action"
        title="Workflow properties"
        @click="emit('settings')"
      >
        <Settings2 class="h-4 w-4" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.mobile-workflow-action { @apply inline-flex h-8 w-6 items-center justify-center rounded-md transition-colors hover:bg-muted hover:text-foreground; }
</style>
