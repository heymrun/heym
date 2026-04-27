<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { Maximize2, Minimize2, X } from "lucide-vue-next";

interface Props {
  open: boolean;
  title?: string;
  size?: "sm" | "md" | "lg" | "xl" | "2xl" | "3xl" | "4xl" | "full";
  allowFullscreen?: boolean;
  defaultFullscreen?: boolean;
  closeOnEscape?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  title: undefined,
  size: "lg",
  allowFullscreen: false,
  defaultFullscreen: false,
  closeOnEscape: true,
});

const isFullscreen = ref(props.defaultFullscreen);

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
    full: "max-w-[95vw] md:max-w-4xl",
  };
  return sizes[props.size] || "max-w-lg";
});

const emit = defineEmits<{
  (e: "close"): void;
  (e: "escape", event: KeyboardEvent): void;
}>();

const containerRef = ref<HTMLDivElement | null>(null);

function handleEscape(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    emit("escape", event);
    if (!props.closeOnEscape) {
      return;
    }
    if (event.defaultPrevented) {
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
}

const captureOptions = { capture: true };

watch(
  () => props.open,
  (open) => {
    if (open) {
      document.body.style.overflow = "hidden";
      isFullscreen.value = props.defaultFullscreen;
      window.addEventListener("keydown", handleEscape, captureOptions);
      nextTick(() => {
        containerRef.value?.focus();
      });
    } else {
      document.body.style.overflow = "";
      isFullscreen.value = props.defaultFullscreen;
      window.removeEventListener("keydown", handleEscape, captureOptions);
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  window.removeEventListener("keydown", handleEscape, captureOptions);
});

function toggleFullscreen(): void {
  isFullscreen.value = !isFullscreen.value;
}
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog">
      <div
        v-if="open"
        ref="containerRef"
        :class="[
          'fixed inset-0 z-50 flex items-center justify-center',
          isFullscreen ? 'p-0' : 'p-4 sm:p-6'
        ]"
        tabindex="0"
      >
        <div
          class="dialog-backdrop fixed inset-0"
          @click="emit('close')"
        />
        <div
          :class="[
            'dialog-content relative z-50 w-full border border-border/60',
            'bg-card',
            'p-6 md:p-7 flex flex-col',
            isFullscreen ? 'max-h-[100vh]' : 'max-h-[90vh] sm:max-h-[85vh] rounded-2xl',
            'overflow-hidden',
            sizeClasses
          ]"
          @click.stop
        >
          <div class="dialog-header flex items-center justify-between pb-4 mb-5 shrink-0 gap-2">
            <div class="flex items-center gap-2 md:gap-4 min-w-0 flex-1 overflow-hidden">
              <h2
                v-if="title"
                class="text-base md:text-lg font-semibold tracking-tight truncate flex-shrink-0"
              >
                {{ title }}
              </h2>
              <template v-if="$slots['header-actions']">
                <div class="h-5 w-px bg-border/60 shrink-0 hidden sm:block" />
                <div class="min-w-0 flex-1 overflow-hidden">
                  <slot name="header-actions" />
                </div>
              </template>
            </div>
            <div class="flex items-center gap-1.5 flex-shrink-0">
              <button
                v-if="allowFullscreen"
                class="dialog-btn flex items-center justify-center w-11 h-11 min-h-[44px] min-w-[44px] md:w-8 md:h-8 rounded-xl text-muted-foreground hover:text-foreground transition-all duration-200"
                @click="toggleFullscreen"
              >
                <Minimize2
                  v-if="isFullscreen"
                  class="h-4 w-4"
                />
                <Maximize2
                  v-else
                  class="h-4 w-4"
                />
              </button>
              <div
                v-if="$slots['header-trailing']"
                class="flex items-center gap-1.5"
              >
                <slot name="header-trailing" />
              </div>
              <button
                class="dialog-btn flex items-center justify-center w-11 h-11 min-h-[44px] min-w-[44px] md:w-8 md:h-8 rounded-xl text-muted-foreground hover:text-foreground transition-all duration-200"
                @click="emit('close')"
              >
                <X class="h-4 w-4" />
              </button>
            </div>
          </div>
          <div class="dialog-body overflow-y-auto overflow-x-hidden flex-1 min-h-0 -mx-1 px-1">
            <slot />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop {
  background: hsl(0 0% 0% / 0.65);
  backdrop-filter: blur(12px);
}

.dialog-content {
  box-shadow:
    0 0 0 1px hsl(var(--border) / 0.5),
    0 0 1px hsl(0 0% 0% / 0.0125),
    0 0 1px hsl(0 0% 0% / 0.0075);
  animation: dialog-scale-in 0.25s cubic-bezier(0.22, 1, 0.36, 1);
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

.dialog-enter-active {
  transition: opacity 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.dialog-leave-active {
  transition: opacity 0.2s ease;
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
}

.dialog-enter-from .dialog-content {
  transform: scale(0.96) translateY(8px);
}
</style>
