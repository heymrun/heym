<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { onClickOutside } from "@vueuse/core";
import { MoreVertical } from "lucide-vue-next";

import type { WidgetAction } from "@/components/Dashboards/widgetActions";

defineProps<{
  actions: WidgetAction[];
}>();

const menuOpen = ref(false);
const triggerRef = ref<HTMLElement | null>(null);
const menuPanelRef = ref<HTMLElement | null>(null);
const menuPos = ref<{ top: number; left: number }>({ top: 0, left: 0 });
const MENU_WIDTH = 176;

// The menu is teleported to <body> because each grid item is transformed and so
// forms its own stacking/clipping context — a z-indexed dropdown would otherwise
// be hidden behind neighbouring widgets.
onClickOutside(
  triggerRef,
  () => {
    menuOpen.value = false;
  },
  { ignore: [menuPanelRef] },
);

function toggleMenu(): void {
  if (menuOpen.value) {
    menuOpen.value = false;
    return;
  }
  const rect = triggerRef.value?.getBoundingClientRect();
  if (rect) {
    menuPos.value = {
      top: rect.bottom + 4,
      left: Math.max(8, rect.right - MENU_WIDTH),
    };
  }
  menuOpen.value = true;
}

function closeMenu(): void {
  menuOpen.value = false;
}

function runAction(action: WidgetAction): void {
  menuOpen.value = false;
  action.run();
}

watch(menuOpen, (open) => {
  if (open) {
    window.addEventListener("scroll", closeMenu, true);
    window.addEventListener("resize", closeMenu);
  } else {
    window.removeEventListener("scroll", closeMenu, true);
    window.removeEventListener("resize", closeMenu);
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("scroll", closeMenu, true);
  window.removeEventListener("resize", closeMenu);
});
</script>

<template>
  <!-- sm+: inline icon row -->
  <div class="hidden shrink-0 items-center gap-1 sm:flex">
    <button
      v-for="action in actions"
      :key="action.key"
      class="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      :class="[
        action.danger ? 'hover:bg-destructive/10 hover:text-destructive' : '',
        action.disabled?.() ? 'cursor-not-allowed opacity-50' : '',
      ]"
      :title="action.label"
      :aria-label="action.label"
      :disabled="action.disabled?.()"
      @click="action.run()"
    >
      <component
        :is="action.icon"
        class="h-3.5 w-3.5"
      />
    </button>
  </div>

  <!-- below sm: collapsed 3-dot menu so the title keeps its space -->
  <div
    ref="triggerRef"
    class="shrink-0 sm:hidden"
  >
    <button
      class="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
      title="Actions"
      @click.stop="toggleMenu"
    >
      <MoreVertical class="h-4 w-4" />
    </button>
  </div>

  <Teleport to="body">
    <div
      v-if="menuOpen"
      ref="menuPanelRef"
      class="fixed z-[100] w-44 overflow-hidden rounded-lg border border-border bg-card py-1 shadow-lg"
      :style="{ top: `${menuPos.top}px`, left: `${menuPos.left}px` }"
    >
      <button
        v-for="action in actions"
        :key="action.key"
        class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent"
        :class="action.danger ? 'text-destructive hover:bg-destructive/10' : 'text-foreground'"
        :disabled="action.disabled?.()"
        @click.stop="runAction(action)"
      >
        <component
          :is="action.icon"
          class="h-4 w-4 shrink-0"
        />
        {{ action.label }}
      </button>
    </div>
  </Teleport>
</template>
