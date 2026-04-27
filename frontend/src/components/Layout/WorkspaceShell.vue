<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from "vue";
import { storeToRefs } from "pinia";
import { useMediaQuery } from "@vueuse/core";
import { ChevronLeft, Sparkles } from "lucide-vue-next";

import ContextualShowcase from "@/features/showcase/components/ContextualShowcase.vue";
import ShowcaseIntroDialog from "@/features/showcase/components/ShowcaseIntroDialog.vue";
import QuickWorkflowDrawer from "@/components/Layout/QuickWorkflowDrawer.vue";
import type { ShowcaseContext } from "@/features/showcase/showcase.types";
import { getShowcaseIntroContent, getShowcaseIntroScreenKey, getShowcaseIntroVideo } from "@/features/showcase/showcaseIntroRegistry";
import { cn } from "@/lib/utils";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { useQuickDrawerStore } from "@/stores/quickDrawer";
import { useShowcaseStore } from "@/stores/showcase";

interface Props {
  enabled?: boolean;
  showcaseContext?: ShowcaseContext | null;
  showcaseEnabled?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  enabled: true,
  showcaseContext: null,
  showcaseEnabled: true,
});

const quickDrawerStore = useQuickDrawerStore();
const showcaseStore = useShowcaseStore();
const { isDrawerOpen } = storeToRefs(quickDrawerStore);
const { activeContext, isDesktopPanelOpen } = storeToRefs(showcaseStore);
const isMobile = useMediaQuery("(max-width: 767px)");
const canRenderDrawer = computed(() => props.enabled && !isMobile.value);
const canRenderShowcaseDesktop = computed(() => {
  return props.showcaseEnabled && props.showcaseContext !== null && !isMobile.value;
});
const showcaseIntroVideoSrc = computed(() => {
  return getShowcaseIntroVideo(props.showcaseContext);
});
const showcaseIntroScreenKey = computed(() => {
  return getShowcaseIntroScreenKey(props.showcaseContext);
});
const showcaseIntroContent = computed(() => {
  return getShowcaseIntroContent(props.showcaseContext);
});
const showcaseIntroEnabled = computed(() => {
  return props.showcaseEnabled && !isMobile.value;
});
const shouldShiftForQuickDrawer = computed(() => canRenderDrawer.value && isDrawerOpen.value);
const shouldShiftForShowcase = computed(() => {
  return canRenderShowcaseDesktop.value &&
    isDesktopPanelOpen.value &&
    activeContext.value === props.showcaseContext;
});
const quickTriggerTop = computed(() => "50%");
const shouldHideQuickTrigger = computed(() => shouldShiftForShowcase.value);
let unsubscribeDismissOverlays: (() => void) | null = null;

watch(
  canRenderDrawer,
  (enabled) => {
    if (enabled) {
      void quickDrawerStore.ensureWorkflows();
      return;
    }
    quickDrawerStore.closeDrawer();
  },
  { immediate: true },
);

watch(isDrawerOpen, (open, wasOpen) => {
  if (!canRenderDrawer.value) return;
  if (open && !wasOpen) {
    pushOverlayState();
    void quickDrawerStore.ensureWorkflowsIfStale();
  }
});

watch(
  [canRenderDrawer, isDrawerOpen],
  ([canShowDrawer, open]) => {
    if (canShowDrawer && open) {
      document.body.dataset.heymQuickDrawerOpen = "true";
      return;
    }
    delete document.body.dataset.heymQuickDrawerOpen;
  },
  { immediate: true },
);

onMounted(() => {
  unsubscribeDismissOverlays = onDismissOverlays(() => {
    quickDrawerStore.closeDrawer();
  });
});

onUnmounted(() => {
  unsubscribeDismissOverlays?.();
  unsubscribeDismissOverlays = null;
  delete document.body.dataset.heymQuickDrawerOpen;
});

function toggleQuickDrawer(): void {
  showcaseStore.closeAll();
  quickDrawerStore.toggleDrawer();
}
</script>

<template>
  <div
    class="workspace-shell relative overflow-x-hidden"
    :style="{
      '--quick-drawer-width': 'min(420px, 32vw)',
      '--showcase-width': 'min(390px, 31vw)',
    }"
  >
    <div
      :class="cn(
        'workspace-shell__content transition-transform duration-300 ease-out',
        shouldShiftForQuickDrawer && 'workspace-shell__content--open-quick',
        shouldShiftForShowcase && 'workspace-shell__content--open-showcase'
      )"
    >
      <slot />
    </div>

    <ContextualShowcase
      :context="showcaseContext"
      :enabled="showcaseEnabled"
      :behind-drawer="isDrawerOpen"
      @opening="quickDrawerStore.closeDrawer()"
    />
    <ShowcaseIntroDialog
      :screen-key="showcaseIntroScreenKey"
      :video-src="showcaseIntroVideoSrc"
      :content="showcaseIntroContent"
      :enabled="showcaseIntroEnabled"
    />

    <template v-if="canRenderDrawer">
      <div
        v-if="isDrawerOpen"
        class="fixed inset-0 z-30 bg-slate-950/10 backdrop-blur-[1.5px]"
        aria-hidden="true"
        @click="quickDrawerStore.closeDrawer()"
      />

      <button
        v-if="!shouldHideQuickTrigger"
        type="button"
        :class="cn(
          'quick-drawer-trigger fixed right-0 top-1/2 z-50 h-44 w-9 -translate-y-1/2 rounded-l-[16px] border border-r-0 border-sky-500/25 bg-card/94 shadow-xl backdrop-blur-xl transition-transform duration-300 ease-out hover:border-sky-500/40',
          isDrawerOpen && 'quick-drawer-trigger--open'
        )"
        :style="{ top: quickTriggerTop }"
        aria-label="Open quick workflows drawer"
        :aria-expanded="isDrawerOpen"
        @click="toggleQuickDrawer()"
      >
        <div class="quick-drawer-trigger__inner">
          <Sparkles class="quick-drawer-trigger__icon h-3.5 w-3.5 text-primary/90" />
          <div class="quick-drawer-trigger__label">
            Quick Workflows
          </div>
          <ChevronLeft
            class="quick-drawer-trigger__chevron h-3.5 w-3.5 text-muted-foreground/80 transition-transform duration-300"
            :class="isDrawerOpen ? 'quick-drawer-trigger__chevron--open' : ''"
          />
        </div>
      </button>

      <QuickWorkflowDrawer :open="isDrawerOpen" />
    </template>
  </div>
</template>

<style scoped>
.workspace-shell__content {
  transform-origin: right center;
  will-change: transform;
}

.workspace-shell__content--open-quick {
  transform: translateX(calc(var(--quick-drawer-width) * -0.34)) scale(0.972);
}

.workspace-shell__content--open-showcase {
  transform: translateX(calc(var(--showcase-width) * -0.28)) scale(0.978);
}

.quick-drawer-trigger {
  transform: translate3d(0, -50%, 0);
}

.quick-drawer-trigger--open {
  transform: translate3d(calc(var(--quick-drawer-width) * -1), -50%, 0);
}

.quick-drawer-trigger__inner {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  transform: translate(-50%, -50%) rotate(-90deg);
}

.quick-drawer-trigger__label {
  white-space: nowrap;
  font-size: 0.72rem;
  font-weight: 650;
  letter-spacing: -0.01em;
  color: hsl(var(--foreground));
}

.quick-drawer-trigger__chevron {
  flex-shrink: 0;
  transform: rotate(90deg);
}

.quick-drawer-trigger__chevron--open {
  transform: rotate(270deg);
}

.quick-drawer-trigger__icon {
  flex-shrink: 0;
  transform: rotate(90deg);
}
</style>
