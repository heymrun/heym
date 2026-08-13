<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { ChevronLeft, ChevronRight } from "lucide-vue-next";

import {
  DISMISS_OVERLAYS_EVENT,
  pushOverlayState,
} from "@/composables/useOverlayBackHandler";
import { adjacentImageSrc, imageGalleryPosition } from "@/lib/imageLightboxGallery";

interface Props {
  src: string | null;
  srcs?: string[];
  alt?: string;
}

const props = withDefaults(defineProps<Props>(), {
  srcs: () => [],
  alt: "Image",
});

const emit = defineEmits<{
  close: [];
  "update:src": [string];
}>();

const overlayRef = ref<HTMLElement | null>(null);

const gallery = computed((): string[] => {
  if (props.srcs.length > 0) {
    return props.srcs;
  }
  return props.src ? [props.src] : [];
});

const position = computed(() => imageGalleryPosition(gallery.value, props.src));
const canNavigate = computed(() => position.value !== null);

function close(): void {
  emit("close");
}

function go(delta: number): void {
  const next = adjacentImageSrc(gallery.value, props.src, delta);
  if (next && next !== props.src) {
    emit("update:src", next);
  }
}

let closedByPopState = false;
let hasPushedState = false;

function handleDismissOverlays(): void {
  closedByPopState = true;
}

function handlePopState(): void {
  if (props.src) {
    closedByPopState = true;
    close();
  }
}

function handleKeydown(event: KeyboardEvent): void {
  if (!props.src) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopImmediatePropagation();
    close();
    return;
  }
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    event.stopImmediatePropagation();
    go(-1);
    return;
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    event.stopImmediatePropagation();
    go(1);
  }
}

function setupListeners(): void {
  document.body.style.overflow = "hidden";
  document.body.dataset.heymLightboxOpen = "true";
  pushOverlayState();
  hasPushedState = true;
  window.addEventListener("popstate", handlePopState);
  window.addEventListener(DISMISS_OVERLAYS_EVENT, handleDismissOverlays, true);
  window.addEventListener("keydown", handleKeydown, true);
  nextTick(() => overlayRef.value?.focus());
}

function teardownListeners(): void {
  document.body.style.overflow = "";
  delete document.body.dataset.heymLightboxOpen;
  window.removeEventListener("popstate", handlePopState);
  window.removeEventListener(DISMISS_OVERLAYS_EVENT, handleDismissOverlays, true);
  window.removeEventListener("keydown", handleKeydown, true);
  if (!closedByPopState && hasPushedState) {
    if (document.body.dataset.heymQuickDrawerOpen === "true") {
      closedByPopState = false;
      hasPushedState = false;
      return;
    }
    document.body.dataset.heymIgnoreNextOverlayDismiss = "true";
    window.history.back();
  }
  closedByPopState = false;
  hasPushedState = false;
}

watch(
  () => props.src,
  (newSrc, oldSrc) => {
    if (newSrc && !oldSrc) {
      setupListeners();
    } else if (!newSrc && oldSrc) {
      teardownListeners();
    }
  },
  { immediate: true },
);

onUnmounted(teardownListeners);
</script>

<template>
  <Teleport to="body">
    <Transition name="lightbox-fade">
      <div
        v-if="src"
        ref="overlayRef"
        tabindex="-1"
        class="fixed inset-0 z-[200] flex items-center justify-center bg-black/90 backdrop-blur-sm p-4 outline-none"
        role="dialog"
        aria-modal="true"
        data-testid="image-lightbox"
        :aria-label="alt"
        @click.self.stop="close"
        @keydown.escape.prevent.stop="close"
      >
        <button
          v-if="canNavigate"
          type="button"
          class="absolute left-3 sm:left-6 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-black/60 text-white hover:bg-black/80"
          data-testid="image-lightbox-prev"
          aria-label="Previous image"
          @click.stop="go(-1)"
        >
          <ChevronLeft class="h-6 w-6" />
        </button>
        <img
          :src="src"
          :alt="alt"
          class="max-w-[95vw] max-h-[95vh] object-contain rounded-lg shadow-2xl"
          @click.stop
        >
        <button
          v-if="canNavigate"
          type="button"
          class="absolute right-3 sm:right-6 z-10 flex h-11 w-11 items-center justify-center rounded-full bg-black/60 text-white hover:bg-black/80"
          data-testid="image-lightbox-next"
          aria-label="Next image"
          @click.stop="go(1)"
        >
          <ChevronRight class="h-6 w-6" />
        </button>
        <div
          v-if="position"
          class="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-3 py-1 text-xs text-white"
          data-testid="image-lightbox-counter"
        >
          {{ position.index }} / {{ position.total }}
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.lightbox-fade-enter-active,
.lightbox-fade-leave-active {
  transition: opacity 0.2s ease;
}
.lightbox-fade-enter-from,
.lightbox-fade-leave-to {
  opacity: 0;
}
</style>
