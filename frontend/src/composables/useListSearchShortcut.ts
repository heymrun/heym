import { computed, onMounted, onUnmounted, type ComputedRef, type Ref } from "vue";
import { useMediaQuery } from "@vueuse/core";

import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { isTypingTarget } from "@/lib/keyboardTargets";

interface ListSearchShortcutOptions {
  input: Ref<HTMLInputElement | null>;
  query: Ref<string>;
  noun: string;
  isEnabled?: () => boolean;
}

interface ListSearchShortcut {
  normalizedQuery: ComputedRef<string>;
  isActive: ComputedRef<boolean>;
  placeholder: ComputedRef<string>;
  clear: () => void;
  clearAndKeepFocus: () => void;
}

function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") {
    return false;
  }
  return navigator.platform.toLowerCase().startsWith("mac") || navigator.userAgent.includes("Mac");
}

/** Ctrl/Cmd+F focuses a list search box and Escape clears it, like the Workflows tab. */
export function useListSearchShortcut(options: ListSearchShortcutOptions): ListSearchShortcut {
  const isMobile = useMediaQuery("(max-width: 767px)");

  const normalizedQuery = computed((): string => options.query.value.trim().toLowerCase());
  const isActive = computed((): boolean => normalizedQuery.value.length > 0);

  const placeholder = computed((): string => {
    if (isMobile.value) {
      return `Search ${options.noun}`;
    }
    return `Search ${options.noun} (${isMacPlatform() ? "⌘F" : "Ctrl+F"})`;
  });

  function clear(): void {
    options.query.value = "";
    options.input.value?.blur();
  }

  function clearAndKeepFocus(): void {
    options.query.value = "";
    options.input.value?.focus();
  }

  function handleKeyDown(event: KeyboardEvent): void {
    const input = options.input.value;
    if (!input || options.isEnabled?.() === false) return;

    const canHandle = !isTypingTarget(event.target) || event.target === input;
    if (!canHandle) return;

    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      input.focus();
      input.select();
    }
  }

  // The global Escape handler swallows the key and dispatches this event instead.
  const unsubscribeDismissOverlays = onDismissOverlays(clear);

  onMounted(() => window.addEventListener("keydown", handleKeyDown));
  onUnmounted(() => {
    window.removeEventListener("keydown", handleKeyDown);
    unsubscribeDismissOverlays();
  });

  return { normalizedQuery, isActive, placeholder, clear, clearAndKeepFocus };
}
