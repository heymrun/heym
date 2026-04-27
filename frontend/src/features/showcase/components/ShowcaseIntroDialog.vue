<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { X } from "lucide-vue-next";
import type { ShowcaseIntroContent } from "@/features/showcase/showcaseIntroRegistry";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";

interface Props {
  screenKey: string | null;
  videoSrc: string | null;
  content?: ShowcaseIntroContent | null;
  enabled?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  enabled: true,
  content: null,
});

const isOpen = ref(false);
let unsubscribeDismissOverlays: (() => void) | null = null;

const storageKey = computed(() => {
  if (!props.screenKey) return null;
  return `showcase_seen_${props.screenKey}`;
});

const canRender = computed(() => {
  return props.enabled && Boolean(props.screenKey) && Boolean(props.videoSrc);
});

function hasSeen(): boolean {
  if (!storageKey.value || typeof window === "undefined") return true;

  try {
    return window.localStorage.getItem(storageKey.value) === "1";
  } catch {
    return false;
  }
}

function markSeen(): void {
  if (!storageKey.value || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(storageKey.value, "1");
  } catch {
    // Ignore persistence errors and allow current-session dismissal.
  }
}

function maybeOpen(): void {
  if (!canRender.value) {
    isOpen.value = false;
    return;
  }

  isOpen.value = !hasSeen();
}

function dismiss(): void {
  if (!isOpen.value) return;
  markSeen();
  isOpen.value = false;
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    dismiss();
  }
}

watch(
  () => [props.screenKey, props.videoSrc, props.enabled] as const,
  () => {
    maybeOpen();
  },
  { immediate: true },
);

watch(
  isOpen,
  (open, wasOpen) => {
    if (open && !wasOpen) {
      pushOverlayState();
    }
  },
);

onMounted(() => {
  document.addEventListener("keydown", handleKeydown, true);
  unsubscribeDismissOverlays = onDismissOverlays(() => {
    dismiss();
  });
});

onUnmounted(() => {
  document.removeEventListener("keydown", handleKeydown, true);
  unsubscribeDismissOverlays?.();
  unsubscribeDismissOverlays = null;
});
</script>

<template>
  <template v-if="canRender && isOpen">
    <div class="fixed inset-0 z-[54] bg-background/28 backdrop-blur-md" />
    <div
      class="fixed bottom-8 left-1/2 z-[55] w-[min(92vw,460px)] -translate-x-1/2"
      role="dialog"
      aria-label="Screen showcase"
    >
      <div class="rounded-xl border border-border/70 bg-card/98 p-3 shadow-2xl backdrop-blur-sm">
        <div class="mb-2 flex items-center justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-semibold text-foreground">
              {{ content?.title ?? "Welcome to this screen" }}
            </p>
            <p class="mt-0.5 text-xs text-muted-foreground">
              {{ content?.description ?? "Watch this quick overview before you continue." }}
            </p>
          </div>
          <button
            type="button"
            class="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Close showcase"
            @click="dismiss"
          >
            <X class="h-4 w-4" />
          </button>
        </div>

        <video
          v-if="videoSrc"
          class="w-full overflow-hidden rounded-lg border border-border/60 bg-black/90"
          :src="videoSrc"
          autoplay
          muted
          playsinline
          loop
          controls
        />
        <p class="mt-2 text-[11px] text-muted-foreground">
          Press <kbd class="rounded border border-border bg-muted px-1 py-0.5 text-[10px] font-semibold">Esc</kbd> to close
        </p>
      </div>
    </div>
  </template>
</template>
