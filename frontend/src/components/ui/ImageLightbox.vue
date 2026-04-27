<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from "vue";

import {
  DISMISS_OVERLAYS_EVENT,
  pushOverlayState,
} from "@/composables/useOverlayBackHandler";

interface Props {
  src: string | null;
  alt?: string;
}

const props = withDefaults(defineProps<Props>(), {
  alt: "Image",
});

const emit = defineEmits<{
  close: [];
}>();

const overlayRef = ref<HTMLElement | null>(null);

function close(): void {
  emit("close");
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

function setupListeners(): void {
  document.body.style.overflow = "hidden";
  document.body.dataset.heymLightboxOpen = "true";
  pushOverlayState();
  hasPushedState = true;
  window.addEventListener("popstate", handlePopState);
  window.addEventListener(DISMISS_OVERLAYS_EVENT, handleDismissOverlays, true);
  nextTick(() => overlayRef.value?.focus());
}

function teardownListeners(): void {
  document.body.style.overflow = "";
  delete document.body.dataset.heymLightboxOpen;
  window.removeEventListener("popstate", handlePopState);
  window.removeEventListener(DISMISS_OVERLAYS_EVENT, handleDismissOverlays, true);
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
  (newSrc) => {
    if (newSrc) {
      setupListeners();
    } else {
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
        :aria-label="alt"
        @click.self.stop="close"
        @keydown.escape.prevent.stop="close"
      >
        <img
          :src="src"
          :alt="alt"
          class="max-w-[95vw] max-h-[95vh] object-contain rounded-lg shadow-2xl"
          @click.stop
        >
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
