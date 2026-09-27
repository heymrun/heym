<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { Check, Copy } from "lucide-vue-next";

interface Props {
  /** The text to put on the clipboard. */
  text: string;
}

const props = defineProps<Props>();

const COPIED_MS = 1600;
const copied = ref(false);
let resetTimer: ReturnType<typeof setTimeout> | null = null;

async function copy(): Promise<void> {
  if (!props.text) return;
  try {
    await navigator.clipboard.writeText(props.text);
  } catch {
    return;
  }
  copied.value = true;
  if (resetTimer) clearTimeout(resetTimer);
  resetTimer = setTimeout(() => {
    copied.value = false;
  }, COPIED_MS);
}

onBeforeUnmount(() => {
  if (resetTimer) clearTimeout(resetTimer);
});
</script>

<template>
  <!-- Sits in the top-right corner of a `relative` bubble; from `sm` up it appears when the
       nearest `group/message` ancestor is hovered, as in the Chat tab. -->
  <button
    type="button"
    class="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-lg text-current opacity-60 transition-opacity hover:bg-black/10 sm:opacity-0 sm:group-hover/message:opacity-70 hover:opacity-100"
    :title="copied ? 'Copied' : 'Copy'"
    :aria-label="copied ? 'Copied' : 'Copy message'"
    @click="copy"
  >
    <Check
      v-if="copied"
      class="h-3.5 w-3.5"
    />
    <Copy
      v-else
      class="h-3.5 w-3.5"
    />
  </button>
</template>
