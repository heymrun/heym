<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import type { CSSProperties } from "vue";
import { storeToRefs } from "pinia";
import { useMediaQuery } from "@vueuse/core";
import { Compass } from "lucide-vue-next";
import { useRoute, useRouter } from "vue-router";

import ShowcaseMobileSheet from "@/features/showcase/components/ShowcaseMobileSheet.vue";
import ShowcasePanel from "@/features/showcase/components/ShowcasePanel.vue";
import { saveShowcaseChatDraft } from "@/features/showcase/showcaseChatDraft";
import { resolveShowcaseDefinition } from "@/features/showcase/showcaseResolver";
import type { ShowcaseAction, ShowcaseContext } from "@/features/showcase/showcase.types";
import { getDocPath } from "@/docs/manifest";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";
import { useShowcaseStore } from "@/stores/showcase";
import { cn } from "@/lib/utils";

interface Props {
  context: ShowcaseContext | null;
  enabled?: boolean;
  showDesktopTrigger?: boolean;
  showMobileTrigger?: boolean;
  behindDrawer?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  enabled: true,
  showDesktopTrigger: true,
  showMobileTrigger: true,
  behindDrawer: false,
});

const emit = defineEmits<{
  (e: "opening"): void;
}>();

const route = useRoute();
const router = useRouter();
const showcaseStore = useShowcaseStore();
const isMobile = useMediaQuery("(max-width: 767px)");
const MOBILE_FAB_STORAGE_KEY = "heym-showcase-mobile-fab-position";
const MOBILE_FAB_EDGE_PADDING = 16;
const MOBILE_FAB_BOTTOM_OFFSET = 88;
const DRAG_THRESHOLD_PX = 8;

const {
  activeContext,
  currentExpandedDetailId,
  isDesktopPanelOpen,
  isMobileSheetOpen,
  visibleTeaserContext,
} = storeToRefs(showcaseStore);

let teaserTimeoutId: number | null = null;
let heartbeatTimeoutId: number | null = null;
let unsubscribeDismissOverlays: (() => void) | null = null;
const fabContainerRef = ref<HTMLDivElement | null>(null);
const mobileFabPosition = ref({ x: 0, y: 0 });
const isDraggingFab = ref(false);
const mobileFabReady = ref(false);
const heartbeatActive = ref(false);
let dragStartTouchX = 0;
let dragStartTouchY = 0;
let dragStartFabX = 0;
let dragStartFabY = 0;
let didDragFab = false;

const currentDocPath = computed<string | null>(() => {
  if (route.name !== "docs") return null;
  const pathMatch = route.params.pathMatch;
  if (!pathMatch) return null;
  return Array.isArray(pathMatch) ? pathMatch.join("/") : String(pathMatch);
});

const definition = computed(() =>
  resolveShowcaseDefinition({
    context: props.enabled ? props.context : null,
    currentDocPath: currentDocPath.value,
  })
);

const teaserVisible = computed(() => {
  return visibleTeaserContext.value !== null && visibleTeaserContext.value === props.context;
});

const shouldRender = computed(() => props.enabled && definition.value !== null);
const isDesktopPanelVisible = computed(() => {
  return !isMobile.value && isDesktopPanelOpen.value && activeContext.value === props.context;
});
const isMobileSheetVisible = computed(() => {
  return isMobile.value && isMobileSheetOpen.value && activeContext.value === props.context;
});
const shouldShowFloatingButton = computed(() => {
  const desktopAllowed = !isMobile.value && props.showDesktopTrigger;
  const mobileAllowed = isMobile.value && props.showMobileTrigger;
  if (!desktopAllowed && !mobileAllowed) return false;
  if (isDesktopPanelVisible.value || isMobileSheetVisible.value) return false;
  if (isMobile.value && !mobileFabReady.value) return false;
  return true;
});
const askButtonLabel = computed(() => {
  if (props.context === "docs" && definition.value?.docsTarget?.title) {
    return "Ask About This Doc";
  }
  return "Ask About This Page";
});
const askButtonDescription = computed(() => {
  if (props.context === "docs" && definition.value?.docsTarget?.title) {
    return "Open Chat with a ready-to-edit prompt about this documentation page.";
  }
  return "Open Chat with a ready-to-edit prompt about the current page.";
});
const floatingButtonWrapperStyle = computed<CSSProperties>(() => {
  if (!isMobile.value) {
    return {};
  }

  return {
    left: `${mobileFabPosition.value.x}px`,
    top: `${mobileFabPosition.value.y}px`,
  };
});

function getFabDimensions(): { width: number; height: number } {
  const rect = fabContainerRef.value?.getBoundingClientRect();
  return {
    width: rect?.width ?? 56,
    height: rect?.height ?? 56,
  };
}

function clampMobileFabPosition(position: { x: number; y: number }): { x: number; y: number } {
  const { width, height } = getFabDimensions();
  const maxX = Math.max(MOBILE_FAB_EDGE_PADDING, window.innerWidth - width - MOBILE_FAB_EDGE_PADDING);
  const maxY = Math.max(MOBILE_FAB_EDGE_PADDING, window.innerHeight - height - MOBILE_FAB_EDGE_PADDING);

  return {
    x: Math.min(Math.max(position.x, MOBILE_FAB_EDGE_PADDING), maxX),
    y: Math.min(Math.max(position.y, MOBILE_FAB_EDGE_PADDING), maxY),
  };
}

function defaultMobileFabPosition(): { x: number; y: number } {
  const { width, height } = getFabDimensions();
  return clampMobileFabPosition({
    x: window.innerWidth - width - MOBILE_FAB_EDGE_PADDING,
    y: window.innerHeight - height - MOBILE_FAB_BOTTOM_OFFSET,
  });
}

function saveMobileFabPosition(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MOBILE_FAB_STORAGE_KEY, JSON.stringify(mobileFabPosition.value));
  } catch {
    // Ignore storage failures so dragging still works for the current session.
  }
}

function restoreMobileFabPosition(): void {
  if (typeof window === "undefined" || !isMobile.value || !props.showMobileTrigger) {
    mobileFabReady.value = true;
    return;
  }

  try {
    const raw = window.localStorage.getItem(MOBILE_FAB_STORAGE_KEY);
    if (!raw) {
      mobileFabPosition.value = defaultMobileFabPosition();
      mobileFabReady.value = true;
      return;
    }

    const parsed = JSON.parse(raw) as Partial<{ x: number; y: number }>;
    if (typeof parsed.x === "number" && typeof parsed.y === "number") {
      mobileFabPosition.value = clampMobileFabPosition({ x: parsed.x, y: parsed.y });
    } else {
      mobileFabPosition.value = defaultMobileFabPosition();
    }
  } catch {
    mobileFabPosition.value = defaultMobileFabPosition();
  } finally {
    mobileFabReady.value = true;
  }
}

function handleViewportResize(): void {
  if (!isMobile.value || !props.showMobileTrigger) return;
  mobileFabPosition.value = clampMobileFabPosition(
    mobileFabReady.value ? mobileFabPosition.value : defaultMobileFabPosition(),
  );
  mobileFabReady.value = true;
  saveMobileFabPosition();
}

function clearTeaserTimeout(): void {
  if (teaserTimeoutId !== null) {
    window.clearTimeout(teaserTimeoutId);
    teaserTimeoutId = null;
  }
}

function clearHeartbeatTimeout(): void {
  if (heartbeatTimeoutId !== null) {
    window.clearTimeout(heartbeatTimeoutId);
    heartbeatTimeoutId = null;
  }
}

function triggerHeartbeat(): void {
  clearHeartbeatTimeout();
  heartbeatActive.value = false;

  window.requestAnimationFrame(() => {
    heartbeatActive.value = true;
    heartbeatTimeoutId = window.setTimeout(() => {
      heartbeatActive.value = false;
      heartbeatTimeoutId = null;
    }, 1400);
  });
}

function syncContext(context: ShowcaseContext | null): void {
  showcaseStore.setCurrentContext(context);
  clearTeaserTimeout();

  if (!context || !props.enabled) {
    showcaseStore.hideTeaser();
    return;
  }

  if (showcaseStore.hasSeenTeaser(context)) {
    showcaseStore.hideTeaser(context);
    return;
  }

  showcaseStore.showTeaser(context);
  teaserTimeoutId = window.setTimeout(() => {
    showcaseStore.markTeaserSeen(context);
    teaserTimeoutId = null;
  }, 3600);
}

function openShowcase(): void {
  if (!props.enabled || !definition.value) return;

  emit("opening");
  if (props.context) {
    showcaseStore.setCurrentContext(props.context);
  }

  if (isMobile.value) {
    showcaseStore.openMobileSheet();
  } else {
    showcaseStore.openDesktopPanel();
  }
  pushOverlayState();
}

function handleFabTouchStart(event: TouchEvent): void {
  if (!isMobile.value || event.touches.length !== 1) return;

  const touch = event.touches[0];
  dragStartTouchX = touch.clientX;
  dragStartTouchY = touch.clientY;
  dragStartFabX = mobileFabPosition.value.x;
  dragStartFabY = mobileFabPosition.value.y;
  isDraggingFab.value = false;
  didDragFab = false;
}

function handleFabTouchMove(event: TouchEvent): void {
  if (!isMobile.value || event.touches.length !== 1) return;

  const touch = event.touches[0];
  const deltaX = touch.clientX - dragStartTouchX;
  const deltaY = touch.clientY - dragStartTouchY;

  if (!didDragFab && Math.hypot(deltaX, deltaY) >= DRAG_THRESHOLD_PX) {
    didDragFab = true;
    isDraggingFab.value = true;
  }

  if (!didDragFab) return;

  mobileFabPosition.value = clampMobileFabPosition({
    x: dragStartFabX + deltaX,
    y: dragStartFabY + deltaY,
  });
}

function handleFabTouchEnd(): void {
  if (!isMobile.value) return;

  if (didDragFab) {
    saveMobileFabPosition();
  }
  isDraggingFab.value = false;
}

function handleFabClick(event: MouseEvent): void {
  if (didDragFab) {
    event.preventDefault();
    event.stopPropagation();
    didDragFab = false;
    return;
  }
  openShowcase();
}

function closeShowcase(): void {
  showcaseStore.closeAll();
}

function toggleDetail(detailId: string): void {
  if (!props.context) return;

  showcaseStore.setExpandedDetail(
    props.context,
    currentExpandedDetailId.value === detailId ? null : detailId,
  );
}

async function selectAction(action: ShowcaseAction): Promise<void> {
  if (action.kind === "external" && action.href) {
    window.open(action.href, "_blank", "noopener,noreferrer");
    closeShowcase();
    return;
  }

  if (action.kind === "route" && action.to) {
    closeShowcase();
    await router.push(action.to);
    return;
  }

  if (action.kind === "docs" && action.docTarget) {
    closeShowcase();
    await router.push(getDocPath(action.docTarget.categoryId, action.docTarget.slug));
  }
}

function buildAskAboutPagePrompt(): string {
  const pageTitle = definition.value?.title ?? "this Heym page";
  return `I am currently looking at the Heym page "${pageTitle}". Please help me understand , my question: [replace this with your question]`;
}

async function askAboutPage(): Promise<void> {
  saveShowcaseChatDraft(buildAskAboutPagePrompt());
  closeShowcase();
  await router.push({ path: "/", query: { tab: "chat" } });
}

watch(
  () => props.context,
  (context) => {
    syncContext(context);
  },
  { immediate: true },
);

watch(
  () => props.enabled,
  (enabled) => {
    if (!enabled) {
      showcaseStore.closeAll();
      showcaseStore.hideTeaser();
      clearTeaserTimeout();
      return;
    }
    syncContext(props.context);
  },
);

watch(
  [isDesktopPanelOpen, isMobileSheetOpen],
  ([desktopOpen, mobileOpen]) => {
    if (desktopOpen || mobileOpen) {
      document.body.dataset.heymShowcaseOpen = "true";
      return;
    }
    delete document.body.dataset.heymShowcaseOpen;
  },
  { immediate: true },
);

watch(
  () => route.fullPath,
  () => {
    if (!props.context) return;
    showcaseStore.setCurrentContext(props.context);
    if (shouldRender.value) {
      triggerHeartbeat();
    }
  },
);

watch(
  () => isMobile.value,
  (mobile) => {
    if (!mobile) {
      mobileFabReady.value = true;
      return;
    }
    restoreMobileFabPosition();
  },
  { immediate: true },
);

onMounted(() => {
  unsubscribeDismissOverlays = onDismissOverlays(() => {
    showcaseStore.closeAll();
  });

  window.addEventListener("resize", handleViewportResize);
  if (isMobile.value) {
    restoreMobileFabPosition();
  } else {
    mobileFabReady.value = true;
  }

  if (shouldRender.value) {
    triggerHeartbeat();
  }
});

onUnmounted(() => {
  unsubscribeDismissOverlays?.();
  unsubscribeDismissOverlays = null;
  window.removeEventListener("resize", handleViewportResize);
  clearTeaserTimeout();
  clearHeartbeatTimeout();
  delete document.body.dataset.heymShowcaseOpen;
});
</script>

<template>
  <template v-if="shouldRender && definition">
    <div
      v-if="shouldShowFloatingButton"
      ref="fabContainerRef"
      :class="cn(
        'fixed',
        isMobile ? '' : 'bottom-5 right-6',
        props.behindDrawer ? 'z-20' : 'z-50',
        isDraggingFab && 'contextual-showcase-fab-wrapper--dragging'
      )"
      :style="floatingButtonWrapperStyle"
      @touchstart.passive="handleFabTouchStart"
      @touchmove.prevent="handleFabTouchMove"
      @touchend="handleFabTouchEnd"
      @touchcancel="handleFabTouchEnd"
    >
      <button
        type="button"
        :class="cn(
          'inline-flex items-center gap-2 rounded-full border border-sky-500/20 bg-card/96 px-3 py-3 text-sm font-medium text-foreground shadow-xl backdrop-blur-xl',
          heartbeatActive && 'contextual-showcase-fab--heartbeat',
          'transition-transform duration-300 active:scale-[0.98]'
        )"
        aria-label="Open page guide"
        @click="handleFabClick"
      >
        <Compass class="h-5 w-5 text-sky-500" />
        <span
          v-if="teaserVisible"
          class="inline-flex h-2.5 w-2.5 rounded-full bg-primary"
        />
      </button>
    </div>

    <ShowcasePanel
      :open="isDesktopPanelVisible"
      :definition="definition"
      :expanded-detail-id="currentExpandedDetailId"
      :ask-button-label="askButtonLabel"
      :ask-button-description="askButtonDescription"
      @ask-about-page="askAboutPage"
      @close="closeShowcase"
      @select-action="selectAction"
      @toggle-detail="toggleDetail"
    />

    <ShowcaseMobileSheet
      :open="isMobileSheetVisible"
      :definition="definition"
      :expanded-detail-id="currentExpandedDetailId"
      :ask-button-label="askButtonLabel"
      :ask-button-description="askButtonDescription"
      @ask-about-page="askAboutPage"
      @close="closeShowcase"
      @select-action="selectAction"
      @toggle-detail="toggleDetail"
    />
  </template>
</template>

<style scoped>
.contextual-showcase-fab-wrapper--dragging {
  transition: none !important;
}

.contextual-showcase-fab--heartbeat {
  animation: contextual-showcase-heartbeat 1.15s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes contextual-showcase-heartbeat {
  0% {
    transform: scale(1);
    box-shadow: 0 10px 26px hsl(199 89% 48% / 0.14);
  }
  20% {
    transform: scale(1.08);
    box-shadow: 0 14px 34px hsl(199 89% 48% / 0.28);
  }
  38% {
    transform: scale(0.98);
    box-shadow: 0 10px 24px hsl(199 89% 48% / 0.16);
  }
  58% {
    transform: scale(1.05);
    box-shadow: 0 13px 30px hsl(199 89% 48% / 0.24);
  }
  100% {
    transform: scale(1);
    box-shadow: 0 10px 26px hsl(199 89% 48% / 0.14);
  }
}

@media (prefers-reduced-motion: reduce) {
  .contextual-showcase-fab--heartbeat {
    animation: none;
  }
}
</style>
