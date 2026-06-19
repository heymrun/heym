<script setup lang="ts">
import { nextTick, ref } from "vue";
import { Pin, PinOff, Pencil, Trash2, Check, X } from "lucide-vue-next";

import type { Conversation } from "@/types/chat";
import { cn } from "@/lib/utils";

interface Props {
  conversation: Conversation;
  isActive: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  select: [id: string];
  rename: [id: string, title: string];
  togglePin: [id: string];
  delete: [id: string];
}>();

const isEditing = ref(false);
const editTitle = ref("");
const isConfirmingDelete = ref(false);
const editInputRef = ref<HTMLInputElement | null>(null);
const confirmDeleteButtonRef = ref<HTMLButtonElement | null>(null);

function startEdit(): void {
  editTitle.value = props.conversation.title;
  isEditing.value = true;
  nextTick(() => {
    editInputRef.value?.focus();
    editInputRef.value?.select();
  });
}

function commitEdit(): void {
  const trimmed = editTitle.value.trim();
  if (trimmed && trimmed !== props.conversation.title) {
    emit("rename", props.conversation.id, trimmed);
  }
  isEditing.value = false;
}

function cancelEdit(): void {
  isEditing.value = false;
}

function onEditKeydown(e: KeyboardEvent): void {
  if (e.key === "Enter") commitEdit();
  if (e.key === "Escape") cancelEdit();
}

function confirmDelete(): void {
  isConfirmingDelete.value = true;
  nextTick(() => {
    confirmDeleteButtonRef.value?.focus();
  });
}

function doDelete(): void {
  emit("delete", props.conversation.id);
  isConfirmingDelete.value = false;
}

function cancelDelete(): void {
  isConfirmingDelete.value = false;
}

function handleSelect(): void {
  emit("select", props.conversation.id);
}
</script>

<template>
  <div
    :data-testid="`chat-list-item-${conversation.id}`"
    :class="cn(
      'group relative flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors overflow-hidden',
      isActive
        ? 'bg-primary/10 text-primary'
        : 'hover:bg-muted/60 text-foreground'
    )"
    @click="handleSelect"
  >
    <div
      class="chat-item-bar absolute left-0 top-0 bottom-0 w-[3px]"
      :class="{ 'chat-item-bar--running': conversation.is_running }"
    />

    <Pin
      v-if="conversation.is_pinned"
      class="w-3 h-3 shrink-0 text-primary opacity-60"
    />

    <div class="flex-1 min-w-0">
      <template v-if="isEditing">
        <input
          ref="editInputRef"
          v-model="editTitle"
          class="w-full text-sm bg-background border border-border rounded px-1 py-0.5 outline-none"
          @keydown="onEditKeydown"
          @blur="commitEdit"
          @click.stop
        >
      </template>
      <template v-else>
        <span
          class="block text-sm truncate leading-5"
          @dblclick.stop="startEdit"
        >
          {{ conversation.title }}
        </span>
      </template>
    </div>

    <div
      v-if="conversation.has_unread && !isActive && !isEditing && !isConfirmingDelete"
      class="w-2 h-2 rounded-full bg-primary shrink-0 shadow-[0_0_6px_rgba(99,102,241,0.6)]"
      aria-label="Unread message"
    />

    <div
      v-if="!isEditing && !isConfirmingDelete"
      class="hidden items-center gap-0.5 group-hover:flex group-focus-within:flex"
      @click.stop
    >
      <button
        class="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
        :title="conversation.is_pinned ? 'Unpin' : 'Pin to top'"
        @click="emit('togglePin', conversation.id)"
      >
        <PinOff
          v-if="conversation.is_pinned"
          class="w-3.5 h-3.5"
        />
        <Pin
          v-else
          class="w-3.5 h-3.5"
        />
      </button>
      <button
        class="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
        title="Rename"
        @click="startEdit"
      >
        <Pencil class="w-3.5 h-3.5" />
      </button>
      <button
        class="p-1 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
        title="Delete"
        @click="confirmDelete"
      >
        <Trash2 class="w-3.5 h-3.5" />
      </button>
    </div>

    <div
      v-if="isConfirmingDelete"
      class="flex items-center gap-0.5"
      @click.stop
    >
      <button
        ref="confirmDeleteButtonRef"
        type="button"
        class="p-1 rounded bg-destructive/10 text-destructive hover:bg-destructive/20"
        title="Confirm delete"
        @click="doDelete"
      >
        <Check class="w-3.5 h-3.5" />
      </button>
      <button
        class="p-1 rounded hover:bg-muted text-muted-foreground hover:text-foreground"
        title="Cancel"
        @click="cancelDelete"
      >
        <X class="w-3.5 h-3.5" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-item-bar {
  border-radius: 0 2px 2px 0;
  background: transparent;
  transition: background 200ms ease;
}

.chat-item-bar--running {
  background: linear-gradient(
    to bottom,
    transparent 0%,
    hsl(var(--primary)) 30%,
    hsl(var(--primary) / 0.7) 50%,
    hsl(var(--primary)) 70%,
    transparent 100%
  );
  background-size: 100% 300%;
  animation: chat-bar-shimmer 1.6s ease-in-out infinite;
}

@keyframes chat-bar-shimmer {
  0% { background-position: 0% 0%; }
  50% { background-position: 0% 100%; }
  100% { background-position: 0% 0%; }
}
</style>
