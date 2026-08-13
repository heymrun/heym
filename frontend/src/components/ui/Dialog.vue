<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, useSlots, watch } from "vue";
import { Maximize2, Minimize2, X } from "lucide-vue-next";

import { useDialogBackHistory } from "@/composables/useDialogBackHistory";
import {
  addToDialogStack,
  dialogStackPosition,
  isBottommostDialog,
  isTopmostDialog,
  removeFromDialogStack,
} from "@/composables/useDialogStack";

const slots = useSlots();
const hasHeaderActions = computed(() => typeof slots["header-actions"] === "function");

interface Props {
  open: boolean;
  title?: string;
  titleClass?: string;
  size?: "sm" | "md" | "lg" | "xl" | "2xl" | "3xl" | "4xl" | "5xl" | "6xl" | "7xl" | "full";
  allowFullscreen?: boolean;
  defaultFullscreen?: boolean;
  hideFullscreenToggleOnMobile?: boolean;
  closeOnEscape?: boolean;
  closeOnBack?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  title: undefined,
  titleClass: undefined,
  size: "lg",
  allowFullscreen: false,
  defaultFullscreen: false,
  hideFullscreenToggleOnMobile: false,
  closeOnEscape: true,
  closeOnBack: false,
});

const isFullscreen = ref(props.defaultFullscreen);
const dialogId = Symbol("dialog");
const isTopmost = computed(() => props.open && isTopmostDialog(dialogId));
const isNestedBackdrop = computed(() => props.open && !isBottommostDialog(dialogId));
const dialogZIndex = computed(() => 50 + dialogStackPosition(dialogId) * 10);

const sizeClasses = computed(() => {
  if (isFullscreen.value) {
    return "max-w-[100vw] w-[100vw] h-[100vh] !rounded-none";
  }
  const sizes: Record<string, string> = {
    sm: "max-w-sm",
    md: "max-w-md",
    lg: "max-w-lg",
    xl: "max-w-xl",
    "2xl": "max-w-2xl",
    "3xl": "max-w-3xl",
    "4xl": "max-w-4xl",
    "5xl": "max-w-5xl",
    "6xl": "max-w-6xl",
    "7xl": "max-w-7xl",
    full: "max-w-[95vw] md:max-w-4xl",
  };
  return sizes[props.size] || "max-w-lg";
});

const emit = defineEmits<{
  (e: "close"): void;
  (e: "escape", event: KeyboardEvent): void;
}>();

const containerRef = ref<HTMLDivElement | null>(null);
const { pushDialogHistoryEntry, removeDialogHistoryEntry } = useDialogBackHistory({
  enabled: () => props.closeOnBack,
  isOpen: () => props.open,
  onBack: () => emit("close"),
});

function handleEscape(event: KeyboardEvent): void {
  if (event.key !== "Escape" || !isTopmost.value) {
    return;
  }
  emit("escape", event);
  if (!props.closeOnEscape || event.defaultPrevented) {
    return;
  }
  event.preventDefault();
  event.stopImmediatePropagation();
  if (isFullscreen.value) {
    isFullscreen.value = false;
  } else {
    emit("close");
  }
}

const captureOptions = { capture: true };

watch(
  () => props.open,
  (open) => {
    if (open) {
      addToDialogStack(dialogId);
      isFullscreen.value = props.defaultFullscreen;
      window.addEventListener("keydown", handleEscape, captureOptions);
      pushDialogHistoryEntry();
      nextTick(() => {
        containerRef.value?.focus();
      });
    } else {
      removeFromDialogStack(dialogId);
      isFullscreen.value = props.defaultFullscreen;
      window.removeEventListener("keydown", handleEscape, captureOptions);
      removeDialogHistoryEntry();
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  window.removeEventListener("keydown", handleEscape, captureOptions);
  removeFromDialogStack(dialogId);
  removeDialogHistoryEntry();
});

function toggleFullscreen(): void {
  isFullscreen.value = !isFullscreen.value;
}
</script>

<template>
  <Teleport to="body">
    <Transition
      name="dialog"
      :duration="{ enter: 250, leave: 200 }"
    >
      <div
        v-if="open"
        ref="containerRef"
        :class="[
          'fixed inset-0 z-50 flex items-center justify-center',
          isFullscreen ? 'p-0' : 'p-4 sm:p-6'
        ]"
        :style="{ zIndex: dialogZIndex }"
        tabindex="0"
      >
        <div
          :class="['dialog-backdrop fixed inset-0', isNestedBackdrop ? 'dialog-backdrop-nested' : '']"
          @click="emit('close')"
        />
        <div
          :class="[
            'dialog-content relative z-50 w-full border border-border/60',
            'bg-card',
            'p-4 sm:p-6 md:p-7 flex flex-col',
            isFullscreen ? 'max-h-[100vh]' : 'max-h-[90vh] sm:max-h-[85vh] rounded-2xl',
            'overflow-hidden',
            sizeClasses
          ]"
          @click.stop
        >
          <div
            :class="[
              'dialog-header shrink-0 pb-3 sm:pb-4 mb-3 sm:mb-5 gap-x-1.5 sm:gap-x-2 gap-y-2',
              hasHeaderActions
                ? 'grid grid-cols-[minmax(0,1fr)_auto] sm:grid-cols-[auto_minmax(0,1fr)_auto] items-center'
                : 'flex items-center justify-between',
            ]"
          >
            <div class="min-w-0 flex items-center gap-1.5 sm:gap-2 md:gap-4 overflow-hidden">
              <div
                v-if="title || $slots.subtitle"
                class="min-w-0"
              >
                <h2
                  v-if="title"
                  :title="title"
                  :class="[
                    'font-semibold tracking-tight line-clamp-1',
                    titleClass || 'text-sm sm:text-base md:text-lg',
                  ]"
                >
                  {{ title }}
                </h2>
                <div
                  v-if="$slots.subtitle"
                  class="line-clamp-1 leading-snug sm:leading-none"
                >
                  <slot name="subtitle" />
                </div>
              </div>
            </div>
            <div
              v-if="hasHeaderActions"
              class="col-span-2 sm:col-span-1 min-w-0 flex items-center justify-center sm:justify-start gap-1.5 sm:gap-2"
            >
              <div class="h-5 w-px bg-border/60 shrink-0 hidden sm:block" />
              <div class="min-w-0 overflow-hidden flex justify-center sm:justify-start sm:flex-1">
                <slot name="header-actions" />
              </div>
            </div>
            <div
              :class="[
                'flex items-center gap-1 sm:gap-1.5 flex-shrink-0',
                hasHeaderActions ? 'row-start-1 col-start-2 sm:col-start-3' : '',
              ]"
            >
              <div
                v-if="$slots['header-trailing']"
                class="flex items-center gap-1"
              >
                <slot name="header-trailing" />
              </div>
              <button
                v-if="allowFullscreen"
                :class="[
                  'dialog-btn items-center justify-center h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground transition-all duration-200',
                  hideFullscreenToggleOnMobile ? 'hidden sm:flex' : 'flex',
                ]"
                @click="toggleFullscreen"
              >
                <Minimize2
                  v-if="isFullscreen"
                  class="h-3.5 w-3.5"
                />
                <Maximize2
                  v-else
                  class="h-3.5 w-3.5"
                />
              </button>
              <button
                class="dialog-btn flex items-center justify-center h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground transition-all duration-200"
                @click="emit('close')"
              >
                <X class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <div class="dialog-body overflow-y-auto overflow-x-hidden flex-1 min-h-0 -ml-1 pl-1 -mr-3 pr-3 sm:-mr-4 sm:pr-4 md:-mr-5 md:pr-5">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop {
  --dialog-backdrop-tint: 0.65;
  --dialog-backdrop-blur: 12px;
  background: hsl(0 0% 0% / var(--dialog-backdrop-tint));
  backdrop-filter: blur(var(--dialog-backdrop-blur));
}

/* A stacked dialog pushes the one under it back rather than dimming the page a second time. */
.dialog-backdrop-nested {
  --dialog-backdrop-tint: 0.4;
  --dialog-backdrop-blur: 8px;
}

.dialog-content {
  box-shadow:
    0 0 0 1px hsl(var(--border) / 0.5),
    0 0 1px hsl(0 0% 0% / 0.0125),
    0 0 1px hsl(0 0% 0% / 0.0075);
}

.dark .dialog-content {
  box-shadow:
    0 0 0 1px hsl(var(--border) / 0.5),
    0 0 1px hsl(0 0% 0% / 0.0375),
    0 0 1px hsl(0 0% 0% / 0.025);
}

@keyframes dialog-scale-in {
  from {
    opacity: 0;
    transform: scale(0.96) translateY(8px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

@keyframes dialog-scale-out {
  from {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
  to {
    opacity: 0;
    transform: scale(0.98) translateY(4px);
  }
}

@keyframes dialog-backdrop-in {
  from {
    background-color: hsl(0 0% 0% / 0);
    backdrop-filter: blur(0px);
  }
  to {
    background-color: hsl(0 0% 0% / var(--dialog-backdrop-tint));
    backdrop-filter: blur(var(--dialog-backdrop-blur));
  }
}

@keyframes dialog-backdrop-out {
  from {
    background-color: hsl(0 0% 0% / var(--dialog-backdrop-tint));
    backdrop-filter: blur(var(--dialog-backdrop-blur));
  }
  to {
    background-color: hsl(0 0% 0% / 0);
    backdrop-filter: blur(0px);
  }
}

.dialog-header {
  position: relative;
}

.dialog-header::after {
  content: '';
  position: absolute;
  bottom: -1px;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    hsl(var(--border)) 20%,
    hsl(var(--primary) / 0.4) 50%,
    hsl(var(--border)) 80%,
    transparent 100%
  );
}

.dialog-btn {
  background: hsl(var(--muted) / 0.5);
}

.dialog-btn:hover {
  background: hsl(var(--muted));
}

/* Fading the container would make the backdrop its own backdrop root and snap the blur on at the end. */
.dialog-enter-active .dialog-backdrop {
  animation: dialog-backdrop-in 0.25s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.dialog-leave-active .dialog-backdrop {
  animation: dialog-backdrop-out 0.2s ease both;
}

.dialog-enter-active .dialog-content {
  animation: dialog-scale-in 0.25s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.dialog-leave-active .dialog-content {
  animation: dialog-scale-out 0.2s ease both;
}
</style>
