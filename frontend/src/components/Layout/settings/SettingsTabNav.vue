<script setup lang="ts" generic="T extends string">
import { nextTick, onMounted, onUnmounted, ref } from "vue";

interface SettingsNavTab {
  id: T;
  label: string;
  testId?: string;
}

defineProps<{
  tabs: SettingsNavTab[];
  modelValue: T;
}>();

const emit = defineEmits<{
  "update:modelValue": [id: T];
}>();

// Below the `sm` breakpoint the list lies flat and scrolls sideways, so the edge
// shadows hint that more tabs are off screen. From `sm` up it is a vertical rail.
const tabbarRef = ref<HTMLElement | null>(null);
const showLeftShadow = ref(false);
const showRightShadow = ref(false);
let resizeObserver: ResizeObserver | null = null;

function updateShadows(): void {
  const container = tabbarRef.value;
  if (!container) return;
  showLeftShadow.value = container.scrollLeft > 2;
  showRightShadow.value = container.scrollLeft + container.clientWidth < container.scrollWidth - 2;
}

onMounted(() => {
  void nextTick(() => {
    const container = tabbarRef.value;
    if (!container) return;
    updateShadows();
    resizeObserver = new ResizeObserver(() => updateShadows());
    resizeObserver.observe(container);
  });
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
});
</script>

<template>
  <div class="relative sm:sticky sm:top-0 sm:w-40 sm:shrink-0 sm:self-start">
    <Transition name="tab-fade">
      <div
        v-if="showLeftShadow"
        class="pointer-events-none absolute left-0 top-0 bottom-0 z-10 w-8 sm:hidden"
        style="background: linear-gradient(to right, hsl(var(--card)) 0%, transparent 100%)"
      />
    </Transition>
    <Transition name="tab-fade">
      <div
        v-if="showRightShadow"
        class="pointer-events-none absolute right-0 top-0 bottom-0 z-10 w-8 sm:hidden"
        style="background: linear-gradient(to left, hsl(var(--card)) 0%, transparent 100%)"
      />
    </Transition>
    <div
      ref="tabbarRef"
      class="scrollbar-thin flex overflow-x-auto border-b border-border pb-1 sm:flex-col sm:gap-0.5 sm:overflow-visible sm:border-b-0 sm:border-r sm:pb-0 sm:pr-3"
      @scroll="updateShadows"
    >
      <button
        v-for="tab in tabs"
        :key="tab.id"
        type="button"
        :data-testid="tab.testId"
        :aria-current="modelValue === tab.id ? 'true' : undefined"
        class="-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-left text-sm font-medium transition-colors sm:mb-0"
        :class="
          modelValue === tab.id
            ? 'border-primary text-primary'
            : 'border-transparent text-muted-foreground hover:text-foreground'
        "
        @click="emit('update:modelValue', tab.id)"
      >
        {{ tab.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.tab-fade-enter-active,
.tab-fade-leave-active {
  transition: opacity 0.15s ease;
}
.tab-fade-enter-from,
.tab-fade-leave-to {
  opacity: 0;
}
</style>
