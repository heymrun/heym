<script setup lang="ts">
import { computed } from "vue";
import {
  Clock,
  Copy,
  FolderInput,
  FolderOutput,
  RotateCcw,
  Settings,
  Trash2,
  Workflow,
} from "lucide-vue-next";

import Dialog from "@/components/ui/Dialog.vue";
import { nodeIcons } from "@/lib/nodeIcons";
import type { FolderTree, WorkflowListItem } from "@/types/workflow";

interface Props {
  open: boolean;
  workflow: WorkflowListItem | null;
  folderTree: FolderTree[];
}

const props = defineProps<Props>();

const emit = defineEmits<{
  close: [];
  "move-to-folder": [folderId: string];
  "move-to-root": [];
  "schedule-deletion": [];
  restore: [];
  copy: [event: Event];
  edit: [event: Event];
  delete: [event: Event];
}>();

function flattenFolders(folders: FolderTree[], depth = 0): { folder: FolderTree; depth: number }[] {
  const result: { folder: FolderTree; depth: number }[] = [];
  for (const f of folders) {
    result.push({ folder: f, depth });
    result.push(...flattenFolders(f.children, depth + 1));
  }
  return result;
}

const flatFolders = computed(() => flattenFolders(props.folderTree));

const moveableFolders = computed(() =>
  props.workflow?.folder_id
    ? flatFolders.value.filter(({ folder }) => folder.id !== props.workflow!.folder_id)
    : flatFolders.value
);

const showMoveToFolder = computed(
  () => props.workflow && !props.workflow.scheduled_for_deletion && moveableFolders.value.length > 0
);
const showMoveToRoot = computed(
  () => props.workflow && props.workflow.folder_id && !props.workflow.scheduled_for_deletion
);
const showScheduleDeletion = computed(
  () => props.workflow && !props.workflow.scheduled_for_deletion
);
const showRestore = computed(() => props.workflow?.scheduled_for_deletion ?? false);

function close(): void {
  emit("close");
}

function handleMoveToFolder(folderId: string): void {
  emit("move-to-folder", folderId);
  close();
}

function handleMoveToRoot(): void {
  emit("move-to-root");
  close();
}

function handleScheduleDeletion(): void {
  emit("schedule-deletion");
  close();
}

function handleRestore(): void {
  emit("restore");
  close();
}

function handleCopy(e: Event): void {
  e.stopPropagation();
  emit("copy", e);
  close();
}

function handleEdit(e: Event): void {
  e.stopPropagation();
  emit("edit", e);
  close();
}

function handleDelete(e: Event): void {
  e.stopPropagation();
  emit("delete", e);
  close();
}
</script>

<template>
  <Dialog
    :open="open"
    title="Workflow actions"
    size="sm"
    @close="close"
  >
    <div
      v-if="workflow"
      class="space-y-1"
    >
      <div class="flex items-center gap-3 px-3 py-2 rounded-xl bg-muted/50 mb-4">
        <div
          class="flex items-center justify-center w-10 h-10 rounded-lg bg-primary/10 text-primary shrink-0"
        >
          <component
            :is="workflow.first_node_type && nodeIcons[workflow.first_node_type] ? nodeIcons[workflow.first_node_type] : Workflow"
            class="w-5 h-5"
          />
        </div>
        <div class="min-w-0 flex-1">
          <h3 class="font-medium text-sm truncate">
            {{ workflow.name }}
          </h3>
          <p class="text-xs text-muted-foreground">
            {{ workflow.scheduled_for_deletion ? "Scheduled for deletion" : workflow.folder_id ? "In folder" : "Root" }}
          </p>
        </div>
      </div>

      <div
        v-if="showMoveToFolder"
        class="space-y-1"
      >
        <p class="text-xs font-medium text-muted-foreground px-2 mb-2">
          Move to folder
        </p>
        <button
          v-for="({ folder }) in moveableFolders"
          :key="folder.id"
          type="button"
          class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-left text-sm hover:bg-muted/80 transition-colors min-h-[44px]"
          @click="handleMoveToFolder(folder.id)"
        >
          <FolderInput class="w-4 h-4 text-amber-500 shrink-0" />
          <span class="truncate">{{ folder.name }}</span>
        </button>
      </div>

      <div class="border-t border-border/60 my-4" />

      <button
        v-if="showMoveToRoot"
        type="button"
        class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-left text-sm hover:bg-muted/80 transition-colors min-h-[44px]"
        @click="handleMoveToRoot"
      >
        <FolderOutput class="w-4 h-4 text-primary shrink-0" />
        Move to root
      </button>

      <button
        v-if="showScheduleDeletion"
        type="button"
        class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-left text-sm hover:bg-destructive/10 text-destructive transition-colors min-h-[44px]"
        @click="handleScheduleDeletion"
      >
        <Clock class="w-4 h-4 shrink-0" />
        Schedule for deletion
      </button>

      <button
        v-if="showRestore"
        type="button"
        class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-left text-sm hover:bg-primary/10 text-primary transition-colors min-h-[44px]"
        @click="handleRestore"
      >
        <RotateCcw class="w-4 h-4 shrink-0" />
        Restore
      </button>

      <div class="border-t border-border/60 my-4" />

      <button
        type="button"
        class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-left text-sm hover:bg-muted/80 transition-colors min-h-[44px]"
        @click="handleCopy"
      >
        <Copy class="w-4 h-4 shrink-0" />
        Copy
      </button>

      <button
        type="button"
        class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-left text-sm hover:bg-muted/80 transition-colors min-h-[44px]"
        @click="handleEdit"
      >
        <Settings class="w-4 h-4 shrink-0" />
        Edit
      </button>

      <button
        type="button"
        class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-left text-sm hover:bg-destructive/10 text-destructive transition-colors min-h-[44px]"
        @click="handleDelete"
      >
        <Trash2 class="w-4 h-4 shrink-0" />
        Delete permanently
      </button>
    </div>
  </Dialog>
</template>
