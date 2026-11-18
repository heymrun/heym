<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { Loader2, Sparkles } from "lucide-vue-next";

import { AI_INSERT_MAX_CHARS } from "@/components/Dialogs/agentMemoryBulkActions";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";

interface Props {
  modelValue: string;
  model: string;
  inserting: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
  (e: "submit"): void;
  (e: "cancel"): void;
}>();

const rootRef = ref<HTMLElement | null>(null);
const textareaRef = ref<InstanceType<typeof Textarea> | null>(null);

const isMacPlatform =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.userAgent);
const submitShortcutLabel = isMacPlatform ? "⌘↵" : "Ctrl↵";

const trimmedLength = computed<number>(() => props.modelValue.trim().length);
const overLimit = computed<boolean>(() => props.modelValue.length > AI_INSERT_MAX_CHARS);
const canSubmit = computed<boolean>(
  () => trimmedLength.value > 0 && !overLimit.value && !props.inserting,
);

function submit(): void {
  if (canSubmit.value) {
    emit("submit");
  }
}

onMounted(async () => {
  await nextTick();
  textareaRef.value?.focus();
});

defineExpose({
  contains: (target: EventTarget | null): boolean =>
    target instanceof Node && Boolean(rootRef.value?.contains(target)),
});
</script>

<template>
  <div
    ref="rootRef"
    class="shrink-0 space-y-2 rounded-lg border border-dashed border-primary/40 bg-primary/5 p-3"
    data-testid="agent-memory-ai-insert-panel"
  >
    <div class="flex items-center gap-2 text-sm font-medium">
      <Sparkles class="h-4 w-4 text-primary" />
      Insert from text
    </div>
    <p class="text-xs leading-relaxed text-muted-foreground">
      {{ model }} reads the text and adds the entities and relationships it finds to this
      graph. Entities that already exist are merged. Nothing is deleted.
    </p>
    <Textarea
      ref="textareaRef"
      :model-value="modelValue"
      :rows="5"
      :disabled="inserting"
      placeholder="Paste notes, an email or a document. e.g. Acme is based in Berlin, sells warehouse robots and uses Zendesk for support."
      aria-label="Text to insert into memory"
      @update:model-value="emit('update:modelValue', $event)"
      @keydown.enter.ctrl.exact.prevent.stop="submit"
      @keydown.enter.meta.exact.prevent.stop="submit"
    />
    <div class="flex flex-wrap items-center gap-2">
      <span
        class="text-[11px]"
        :class="overLimit ? 'text-destructive' : 'text-muted-foreground'"
      >
        {{ modelValue.length.toLocaleString() }} / {{ AI_INSERT_MAX_CHARS.toLocaleString() }}
      </span>
      <div class="ml-auto flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          class="h-8"
          :disabled="inserting"
          @click="emit('cancel')"
        >
          Cancel
        </Button>
        <Button
          type="button"
          size="sm"
          class="h-8 gap-1.5"
          :disabled="!canSubmit"
          data-testid="agent-memory-ai-insert-submit"
          @click="submit"
        >
          <Loader2
            v-if="inserting"
            class="h-3.5 w-3.5 animate-spin"
          />
          <Sparkles
            v-else
            class="h-3.5 w-3.5"
          />
          {{ inserting ? "Inserting…" : "Insert" }}
          <span
            v-if="!inserting"
            class="text-[11px] font-normal tracking-wide text-primary-foreground/80"
          >
            {{ submitShortcutLabel }}
          </span>
        </Button>
      </div>
    </div>
  </div>
</template>
