<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { Paperclip } from "lucide-vue-next";

import type { ChatContextItem } from "@/lib/chatContext";
import ChatContextChips from "@/components/Chat/ChatContextChips.vue";
import Button from "@/components/ui/Button.vue";

interface Props {
  /** The message text as it was sent. */
  text: string;
  /** Context chips that stay with the message. */
  items?: readonly ChatContextItem[];
  /** The attachments that stay with the message. */
  attachmentNames?: readonly string[];
  sending?: boolean;
  error?: string | null;
  /** Why the edit cannot be sent right now (no model, a reply running). */
  blockedReason?: string | null;
}

const props = withDefaults(defineProps<Props>(), {
  items: () => [],
  attachmentNames: () => [],
  sending: false,
  error: null,
  blockedReason: null,
});

const emit = defineEmits<{
  save: [text: string];
  cancel: [];
}>();

const draft = ref(props.text);
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const canSave = computed(
  () => draft.value.trim().length > 0 && !props.sending && !props.blockedReason,
);

function resize(): void {
  const textarea = textareaRef.value;
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = `${textarea.scrollHeight}px`;
}

function save(): void {
  if (canSave.value) emit("save", draft.value);
}

onMounted(() => {
  nextTick(() => {
    const textarea = textareaRef.value;
    if (!textarea) return;
    resize();
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  });
});
</script>

<template>
  <div
    class="w-full max-w-[88%] rounded-2xl border border-border bg-background p-3 shadow-sm sm:max-w-[72%]"
    data-testid="chat-message-editor"
    data-heym-inline-edit
  >
    <textarea
      ref="textareaRef"
      v-model="draft"
      rows="1"
      aria-label="Edit message"
      class="block max-h-60 w-full resize-none overflow-y-auto bg-transparent text-sm leading-relaxed text-foreground outline-none"
      :disabled="sending"
      @input="resize"
      @keydown.enter.exact.prevent="save"
      @keydown.esc.prevent.stop="emit('cancel')"
    />
    <ChatContextChips
      v-if="items.length > 0"
      class="mt-2"
      :items="items"
    />
    <div
      v-for="(name, index) in attachmentNames"
      :key="index"
      class="mt-1.5 flex items-center gap-1 text-xs text-muted-foreground"
    >
      <Paperclip class="h-3 w-3 shrink-0" />
      <span class="truncate">{{ name }}</span>
    </div>
    <p class="mt-2 text-xs text-muted-foreground">
      {{ blockedReason ?? "Sending removes the messages after this one and asks the model again." }}
    </p>
    <p
      v-if="error"
      class="mt-1 text-xs text-destructive"
      role="alert"
    >
      {{ error }}
    </p>
    <div class="mt-2 flex justify-end gap-2">
      <Button
        variant="ghost"
        size="sm"
        :disabled="sending"
        @click="emit('cancel')"
      >
        Cancel
      </Button>
      <Button
        size="sm"
        :disabled="!canSave"
        :loading="sending"
        data-testid="chat-message-edit-send"
        @click="save"
      >
        Save and send
      </Button>
    </div>
  </div>
</template>
