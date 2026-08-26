<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch, type CSSProperties } from "vue";
import { useWindowSize } from "@vueuse/core";
import { ArrowLeft, ArrowRight, BookOpen, X } from "lucide-vue-next";
import { useRouter } from "vue-router";

import { getDocPath } from "@/docs/manifest";
import { resolveTourVisual } from "@/features/release-tour/tourVisuals";
import type { ReleaseTour } from "@/features/release-tour/releaseTour.types";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";

interface Props {
  release: ReleaseTour | null;
  open: boolean;
  /** Viewport coords of the launcher button, so the panel hangs off it. */
  anchorLeft?: number;
  anchorBottom?: number;
}

const props = withDefaults(defineProps<Props>(), {
  anchorLeft: 0,
  anchorBottom: 64,
});

const emit = defineEmits<{
  (e: "complete"): void;
}>();

const PANEL_MAX_WIDTH = 380;
const VIEWPORT_MARGIN = 16;
const ANCHOR_GAP = 8;

const router = useRouter();
const { width: windowWidth } = useWindowSize();
const panelRef = ref<HTMLDivElement | null>(null);
/** -1 is the intro screen; 0..n-1 are slides. */
const slideIndex = ref(-1);
let unsubscribeDismissOverlays: (() => void) | null = null;

const slides = computed(() => props.release?.slides ?? []);
const isIntro = computed(() => slideIndex.value < 0);
const currentSlide = computed(() => slides.value[slideIndex.value] ?? null);
const currentVisual = computed(() =>
  currentSlide.value ? resolveTourVisual(currentSlide.value.tourVisual) : null,
);
const isLastSlide = computed(() => slideIndex.value >= slides.value.length - 1);
const isVisible = computed(() => props.open && props.release !== null && slides.value.length > 0);

/** Left-aligned under the launcher, nudged back inside the viewport if it would overflow. */
const panelStyle = computed<CSSProperties>(() => {
  const width = Math.min(PANEL_MAX_WIDTH, windowWidth.value - VIEWPORT_MARGIN * 2);
  const maxLeft = Math.max(VIEWPORT_MARGIN, windowWidth.value - width - VIEWPORT_MARGIN);
  const left = Math.min(Math.max(props.anchorLeft, VIEWPORT_MARGIN), maxLeft);
  const top = props.anchorBottom + ANCHOR_GAP;

  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    maxHeight: `calc(100vh - ${top + VIEWPORT_MARGIN}px)`,
  };
});

const publishedLabel = computed(() => {
  if (!props.release) return "";
  return props.release.publishedAt.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
});

function startTour(): void {
  slideIndex.value = 0;
}

function goBack(): void {
  slideIndex.value = Math.max(-1, slideIndex.value - 1);
}

function goNext(): void {
  if (isLastSlide.value) {
    complete();
    return;
  }
  slideIndex.value += 1;
}

function goToSlide(index: number): void {
  slideIndex.value = index;
}

function complete(): void {
  emit("complete");
}

function openDocs(): void {
  const target = currentSlide.value?.docTarget;
  if (!target) return;

  complete();
  void router.push(getDocPath(target.categoryId, target.slug));
}

/** Clicking anywhere else dismisses the panel. It has no backdrop to catch the click. */
function handlePointerDown(event: MouseEvent): void {
  if (!isVisible.value) return;

  const node = event.target;
  const element = node instanceof Element ? node : (node as Node | null)?.parentElement;
  if (!element) return;
  if (panelRef.value?.contains(element)) return;
  // The launcher toggles the panel itself; closing here too would fight that.
  if (element.closest("#release-tour-launcher-slot")) return;

  complete();
}

function handleKeydown(event: KeyboardEvent): void {
  if (!isVisible.value) return;

  if (event.key === "ArrowRight" && !isIntro.value) {
    event.preventDefault();
    goNext();
    return;
  }
  if (event.key === "ArrowLeft" && !isIntro.value) {
    event.preventDefault();
    goBack();
  }
}

watch(
  () => props.release?.versionedReleaseId,
  () => {
    slideIndex.value = -1;
  },
);

watch(isVisible, (visible, wasVisible) => {
  if (visible && !wasVisible) {
    slideIndex.value = -1;
    pushOverlayState();
    void Promise.resolve().then(() => panelRef.value?.focus());
  }
});

onMounted(() => {
  document.addEventListener("keydown", handleKeydown);
  document.addEventListener("mousedown", handlePointerDown);
  unsubscribeDismissOverlays = onDismissOverlays(() => {
    if (isVisible.value) complete();
  });
});

onUnmounted(() => {
  document.removeEventListener("keydown", handleKeydown);
  document.removeEventListener("mousedown", handlePointerDown);
  unsubscribeDismissOverlays?.();
  unsubscribeDismissOverlays = null;
});
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="-translate-y-3 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="-translate-y-3 opacity-0"
    >
      <div
        v-if="isVisible && release"
        ref="panelRef"
        class="release-tour fixed z-[56] overflow-y-auto overscroll-contain rounded-xl border border-border bg-card shadow-2xl outline-none"
        :style="panelStyle"
        role="dialog"
        aria-modal="false"
        :aria-label="`${release.label} — ${release.introTitle}`"
        tabindex="-1"
      >
        <div class="flex items-center gap-2 border-b border-border/70 px-3 py-2">
          <img
            src="/fav.svg"
            alt=""
            class="h-4 w-4 shrink-0"
          >
          <span class="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {{ release.label }}
          </span>
          <span class="ml-auto shrink-0 text-[10px] text-muted-foreground/80">
            {{ publishedLabel }}
          </span>
          <button
            type="button"
            class="-mr-1 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Close what's new"
            @click="complete"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>

        <div
          v-if="isIntro"
          class="p-4"
        >
          <img
            v-if="release.introCoverImage"
            :src="release.introCoverImage"
            alt=""
            class="mb-3 h-28 w-full rounded-lg border border-border object-cover"
          >
          <h2 class="text-sm font-semibold text-foreground">
            {{ release.introTitle }}
          </h2>
          <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
            {{ release.introDescription }}
          </p>

          <button
            type="button"
            class="mt-4 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            @click="startTour"
          >
            Start tour
            <ArrowRight class="h-3.5 w-3.5" />
          </button>
        </div>

        <div
          v-else-if="currentSlide"
          class="p-4"
        >
          <div class="h-[168px] overflow-hidden rounded-lg border border-border bg-surface-elevated">
            <Transition
              mode="out-in"
              enter-active-class="transition duration-200 ease-out"
              enter-from-class="opacity-0"
              enter-to-class="opacity-100"
              leave-active-class="transition duration-150 ease-in"
              leave-from-class="opacity-100"
              leave-to-class="opacity-0"
            >
              <component
                :is="currentVisual"
                :key="currentSlide.id"
              />
            </Transition>
          </div>

          <h2 class="mt-3 text-sm font-semibold text-foreground">
            {{ currentSlide.title }}
          </h2>
          <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
            {{ currentSlide.description }}
          </p>

          <ul class="mt-2.5 space-y-1">
            <li
              v-for="useCase in currentSlide.useCases"
              :key="useCase"
              class="flex items-start gap-1.5 text-[11px] leading-relaxed text-muted-foreground"
            >
              <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary/70" />
              <span>{{ useCase }}</span>
            </li>
          </ul>

          <button
            v-if="currentSlide.docTarget"
            type="button"
            class="mt-2.5 inline-flex items-center gap-1.5 rounded-md text-[11px] font-medium text-primary transition-colors hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:text-brand-primary-soft"
            @click="openDocs"
          >
            <BookOpen class="h-3 w-3" />
            {{ currentSlide.docTarget.title ?? "Read the docs" }}
          </button>

          <div class="mt-4 flex items-center gap-2">
            <button
              type="button"
              class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Previous feature"
              @click="goBack"
            >
              <ArrowLeft class="h-3.5 w-3.5" />
            </button>

            <div class="flex flex-1 items-center justify-center gap-1.5">
              <button
                v-for="(slide, index) in slides"
                :key="slide.id"
                type="button"
                class="h-1.5 rounded-full transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                :class="index === slideIndex ? 'w-4 bg-primary' : 'w-1.5 bg-border hover:bg-muted-foreground/50'"
                :aria-label="`Go to ${slide.title}`"
                :aria-current="index === slideIndex"
                @click="goToSlide(index)"
              />
            </div>

            <button
              type="button"
              class="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              @click="goNext"
            >
              {{ isLastSlide ? "Done" : "Next" }}
              <ArrowRight
                v-if="!isLastSlide"
                class="h-3.5 w-3.5"
              />
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
@media (prefers-reduced-motion: reduce) {
  .release-tour,
  .release-tour :deep(*) {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
</style>
