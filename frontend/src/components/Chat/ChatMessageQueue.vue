<script setup lang="ts">
import { nextTick, ref } from "vue";
import { Check, Loader2, Paperclip, Pencil, Send, X } from "lucide-vue-next";

import type { QueuedMessage } from "@/types/chat";

import { extractChatContext } from "@/lib/chatContext";
import { getErrorDetail } from "@/services/api";
import { useChatStore } from "@/stores/chat";

const props = defineProps<{ conversationId: string; messages: QueuedMessage[] }>();
const chatStore = useChatStore();
const root = ref<HTMLElement | null>(null);
const editingId = ref<string | null>(null);
const editingValue = ref("");
const busyId = ref<string | null>(null);
const error = ref("");

function attachmentNames(message: QueuedMessage): string[] {
  if (message.attachment_names?.length) return message.attachment_names;
  return message.attachment_name ? [message.attachment_name] : [];
}

async function startEdit(message: QueuedMessage): Promise<void> {
  editingId.value = message.id;
  editingValue.value = message.content;
  error.value = "";
  await nextTick();
  root.value?.querySelector<HTMLTextAreaElement>("[data-queued-edit]")?.focus();
}

function cancelEdit(): void {
  editingId.value = null;
  editingValue.value = "";
}

async function act(message: QueuedMessage, action: "save" | "delete" | "send"): Promise<void> {
  if (busyId.value || (action === "save" && !editingValue.value.trim())) return;
  busyId.value = message.id;
  error.value = "";
  try {
    if (action === "save") {
      await chatStore.updateQueuedMessage(props.conversationId, message.id, editingValue.value.trim());
    } else if (action === "delete") {
      await chatStore.deleteQueuedMessage(props.conversationId, message.id);
    } else {
      await chatStore.sendQueuedMessageNow(props.conversationId, message.id);
    }
    if (editingId.value === message.id) cancelEdit();
  } catch (caught: unknown) {
    error.value = getErrorDetail(caught, "The queued message could not be updated. Please try again.");
  } finally {
    busyId.value = null;
  }
}
</script>

<template>
  <div
    ref="root"
    class="w-full min-w-0 rounded-lg border border-border/50 bg-muted/35 px-2.5 py-2"
  >
    <p class="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
      Queue
    </p>
    <ul class="flex max-h-24 flex-col divide-y divide-border/40 overflow-y-auto">
      <li
        v-for="message in messages"
        :key="message.id"
        data-testid="chat-queue-item"
        class="min-w-0 py-1.5 first:pt-0 last:pb-0"
      >
        <template v-if="editingId === message.id">
          <textarea
            v-model="editingValue"
            data-queued-edit
            rows="2"
            aria-label="Edit queued message"
            class="min-h-16 w-full resize-y rounded-lg border border-border/60 bg-background/80 px-2 py-1.5 text-sm text-foreground outline-none focus:border-primary/40"
            :disabled="busyId !== null"
            @keydown.enter.exact.prevent="act(message, 'save')"
            @keydown.esc.prevent="cancelEdit"
          />
          <div class="mt-2 flex justify-end gap-1.5">
            <button
              type="button"
              class="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
              title="Cancel edit"
              :disabled="busyId !== null"
              @click="cancelEdit"
            >
              <X class="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              class="flex h-7 w-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
              title="Save queued message"
              :disabled="!editingValue.trim() || busyId !== null"
              @click="act(message, 'save')"
            >
              <Loader2
                v-if="busyId === message.id"
                class="h-3.5 w-3.5 animate-spin"
              />
              <Check
                v-else
                class="h-3.5 w-3.5"
              />
            </button>
          </div>
        </template>
        <div
          v-else
          class="flex min-w-0 items-center gap-2 text-sm text-foreground"
        >
          <span
            class="shrink-0 text-xs text-muted-foreground"
            aria-hidden="true"
          >•</span>
          <div class="min-w-0 flex-1">
            <p class="truncate leading-5">
              {{ extractChatContext(message.content).text }}
            </p>
            <div
              v-if="attachmentNames(message).length > 0"
              class="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground"
            >
              <Paperclip class="h-3 w-3 shrink-0" />
              <span class="truncate">{{ attachmentNames(message).join(", ") }}</span>
            </div>
          </div>
          <div class="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              class="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              title="Send now"
              aria-label="Send now"
              :disabled="busyId !== null"
              @click="act(message, 'send')"
            >
              <Loader2
                v-if="busyId === message.id"
                class="h-3.5 w-3.5 animate-spin"
              />
              <Send
                v-else
                class="h-3.5 w-3.5"
              />
            </button>
            <button
              type="button"
              class="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              title="Edit queued message"
              :disabled="busyId !== null"
              @click="startEdit(message)"
            >
              <Pencil class="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              class="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-40"
              title="Delete queued message"
              :disabled="busyId !== null"
              @click="act(message, 'delete')"
            >
              <X class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </li>
    </ul>
    <p
      v-if="error"
      role="alert"
      class="mt-1.5 text-xs text-destructive"
    >
      {{ error }}
    </p>
  </div>
</template>
