<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { Check, ChevronLeft, ChevronRight } from "lucide-vue-next";
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRoot,
  DropdownMenuTrigger,
} from "radix-vue";

defineProps<{
  /** Node label of every span, in the timeline's start order. */
  labels: string[];
  /** Index of the open span in `labels`; -1 when it is not listed. */
  index: number;
}>();
const emit = defineEmits<{
  previous: [event: MouseEvent];
  next: [event: MouseEvent];
  jump: [index: number];
}>();

const menuOpen = ref(false);
const menuList = ref<HTMLElement | null>(null);

// Long loop runs push the open span far down the list; bring it into view on open.
watch(menuOpen, async (open) => {
  if (!open) return;
  await nextTick();
  menuList.value
    ?.querySelector<HTMLElement>('[data-current-span="true"]')
    ?.scrollIntoView({ block: "center" });
});
</script>

<template>
  <div class="flex shrink-0 items-center gap-0.5">
    <button
      type="button"
      class="inline-flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
      title="Previous span"
      aria-label="Previous span"
      data-testid="execution-span-previous"
      :disabled="index <= 0"
      @click="emit('previous', $event)"
    >
      <ChevronLeft class="h-3.5 w-3.5" />
    </button>
    <DropdownMenuRoot
      v-if="index >= 0"
      v-model:open="menuOpen"
    >
      <DropdownMenuTrigger
        class="h-6 min-w-[3rem] rounded px-1 text-center text-[10px] tabular-nums text-muted-foreground hover:bg-muted hover:text-foreground"
        title="Jump to span"
        :aria-label="`Span ${index + 1} of ${labels.length}, jump to another span`"
        data-testid="execution-span-position"
      >
        {{ index + 1 }} / {{ labels.length }}
      </DropdownMenuTrigger>
      <DropdownMenuPortal>
        <DropdownMenuContent
          :side-offset="4"
          :collision-padding="12"
          align="end"
          class="z-[200] rounded-lg border border-border/70 bg-popover/95 p-1 text-popover-foreground shadow-xl backdrop-blur-xl"
        >
          <div
            ref="menuList"
            class="max-h-72 min-w-[12rem] max-w-[20rem] overflow-y-auto"
            data-testid="execution-span-jump-menu"
          >
            <DropdownMenuItem
              v-for="(label, itemIndex) in labels"
              :key="itemIndex"
              class="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-[11px] outline-none transition-colors data-[highlighted]:bg-muted/70"
              :data-current-span="itemIndex === index"
              @select="emit('jump', itemIndex)"
            >
              <Check
                class="h-3 w-3 shrink-0"
                :class="itemIndex === index ? 'text-primary' : 'text-transparent'"
              />
              <span class="truncate"><span class="tabular-nums text-muted-foreground">{{ itemIndex + 1 }} -</span> {{ label }}</span>
            </DropdownMenuItem>
          </div>
        </DropdownMenuContent>
      </DropdownMenuPortal>
    </DropdownMenuRoot>
    <button
      type="button"
      class="inline-flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-muted disabled:pointer-events-none disabled:opacity-40"
      title="Next span"
      aria-label="Next span"
      data-testid="execution-span-next"
      :disabled="index < 0 || index >= labels.length - 1"
      @click="emit('next', $event)"
    >
      <ChevronRight class="h-3.5 w-3.5" />
    </button>
  </div>
</template>
