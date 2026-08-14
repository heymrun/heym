<script setup lang="ts">
import { computed, ref } from "vue";

interface Props {
  modelValue: string;
  placeholder?: string;
  rows?: number;
  /** Fixed height for the expanded dialog; overrides `rows` when set. */
  height?: string;
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: "",
  rows: 10,
  height: undefined,
});

const emit = defineEmits<{ "update:modelValue": [value: string] }>();

const gutterRef = ref<HTMLElement | null>(null);
const textareaRef = ref<HTMLTextAreaElement | null>(null);

// Soft wrapping is off, so one newline is always exactly one rendered row and
// the gutter stays aligned without measuring anything.
const lineNumbers = computed<number[]>(() => {
  const total = Math.max(1, props.modelValue.split("\n").length);
  return Array.from({ length: total }, (_unused, index) => index + 1);
});

const gutterWidth = computed<string>(
  () => `${Math.max(2, String(lineNumbers.value.length).length) + 1.25}ch`,
);

function syncScroll(): void {
  if (gutterRef.value && textareaRef.value) {
    gutterRef.value.scrollTop = textareaRef.value.scrollTop;
  }
}

function onInput(event: Event): void {
  emit("update:modelValue", (event.target as HTMLTextAreaElement).value);
}

/** Keep Tab inside the editor instead of moving focus out of it. */
function onTab(event: KeyboardEvent): void {
  const field = textareaRef.value;
  if (!field) {
    return;
  }
  event.preventDefault();
  const { selectionStart, selectionEnd, value } = field;
  const next = `${value.slice(0, selectionStart)}    ${value.slice(selectionEnd)}`;
  emit("update:modelValue", next);
  requestAnimationFrame(() => {
    field.selectionStart = selectionStart + 4;
    field.selectionEnd = selectionStart + 4;
  });
}

defineExpose({ focus: () => textareaRef.value?.focus() });
</script>

<template>
  <!-- No top inset: the gutter and textarea already carry their own py-2.
       The right side gets 8px so the code clears the scrollbar. -->
  <div
    class="flex overflow-hidden rounded-md border border-input bg-background pb-1 pl-1 pr-2 font-mono text-xs leading-5"
    :style="height ? { height } : undefined"
  >
    <div
      ref="gutterRef"
      aria-hidden="true"
      class="select-none overflow-hidden rounded-l-sm border-r border-input/60 bg-muted/40 py-2 text-right text-muted-foreground/70"
      :style="{ width: gutterWidth, paddingRight: '0.5ch' }"
    >
      <div
        v-for="line in lineNumbers"
        :key="line"
      >
        {{ line }}
      </div>
    </div>
    <textarea
      ref="textareaRef"
      :value="modelValue"
      :placeholder="placeholder"
      :rows="height ? undefined : rows"
      wrap="off"
      spellcheck="false"
      autocapitalize="off"
      autocomplete="off"
      autocorrect="off"
      class="flex-1 resize-none bg-transparent px-2 py-2 leading-5 outline-none placeholder:text-muted-foreground"
      :class="height ? 'h-full' : ''"
      @input="onInput"
      @scroll="syncScroll"
      @keydown.tab="onTab"
    />
  </div>
</template>
