import { onBeforeUnmount, ref, type Ref } from "vue";
import { useResizeObserver } from "@vueuse/core";

/** The input area (message box, YOLO line and buttons) may take this share of the panel. */
export const ASSISTANT_INPUT_MAX_PANEL_SHARE = 0.6;

/**
 * Keep a dragged message-box height between its default and the height at which the whole
 * input area reaches 60% of the panel. `chromeHeight` is the part of the input area that is
 * not the message box.
 */
export function clampAssistantInputHeight(
  height: number,
  minHeight: number,
  panelHeight: number,
  chromeHeight: number,
): number {
  const maxHeight = Math.max(
    minHeight,
    Math.floor(panelHeight * ASSISTANT_INPUT_MAX_PANEL_SHARE) - chromeHeight,
  );
  return Math.min(Math.max(height, minHeight), maxHeight);
}

export interface AssistantInputResize {
  /** The dragged height in px, or null for the default two-row height. */
  height: Ref<number | null>;
  resizing: Ref<boolean>;
  onHandlePointerDown: (event: PointerEvent) => void;
}

/**
 * Drag the top edge of the AI Assistant's input area to make the message box taller.
 * The height lasts for the session only.
 */
export function useAssistantInputResize(
  textarea: Ref<HTMLTextAreaElement | null>,
  inputArea: Ref<HTMLElement | null>,
  panel: Ref<HTMLElement | null>,
): AssistantInputResize {
  const height = ref<number | null>(null);
  const resizing = ref(false);
  let minHeight = 0;
  let startY = 0;
  let startHeight = 0;

  function clamp(next: number): number {
    const box = textarea.value;
    const area = inputArea.value;
    const chromeHeight = box && area ? area.offsetHeight - box.offsetHeight : 0;
    const panelHeight = panel.value?.clientHeight ?? window.innerHeight;
    return clampAssistantInputHeight(next, minHeight, panelHeight, chromeHeight);
  }

  function onPointerMove(event: PointerEvent): void {
    // Dragging up (a smaller clientY) makes the box taller.
    height.value = clamp(startHeight + (startY - event.clientY));
  }

  function stop(): void {
    resizing.value = false;
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
  }

  function onHandlePointerDown(event: PointerEvent): void {
    const box = textarea.value;
    if (!box) return;
    event.preventDefault();
    // The default two-row height, measured before the first drag changes it, is the floor.
    if (minHeight === 0) minHeight = box.offsetHeight;
    startY = event.clientY;
    startHeight = box.offsetHeight;
    resizing.value = true;
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }

  // A smaller panel lowers the ceiling, so a dragged height is clamped again.
  useResizeObserver(panel, () => {
    if (height.value !== null) height.value = clamp(height.value);
  });

  onBeforeUnmount(stop);

  return { height, resizing, onHandlePointerDown };
}
