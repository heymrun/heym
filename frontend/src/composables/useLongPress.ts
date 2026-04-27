import { ref } from "vue";

const LONG_PRESS_MS = 300;

export function useLongPress(
  onLongPress: () => void,
  options?: { delay?: number }
): {
  handlers: {
    onTouchStart: (e: TouchEvent) => void;
    onTouchEnd: () => void;
    onTouchMove: () => void;
  };
  isLongPressing: { value: boolean };
} {
  const delay = options?.delay ?? LONG_PRESS_MS;
  const timer = ref<ReturnType<typeof setTimeout> | null>(null);
  const isLongPressing = ref(false);

  function clearTimer(): void {
    if (timer.value) {
      clearTimeout(timer.value);
      timer.value = null;
    }
    isLongPressing.value = false;
  }

  function onTouchStart(e: TouchEvent): void {
    if (e.touches.length !== 1) return;
    clearTimer();
    isLongPressing.value = true;
    timer.value = setTimeout(() => {
      timer.value = null;
      onLongPress();
    }, delay);
  }

  function onTouchEnd(): void {
    clearTimer();
  }

  function onTouchMove(): void {
    clearTimer();
  }

  return {
    handlers: { onTouchStart, onTouchEnd, onTouchMove },
    isLongPressing,
  };
}
