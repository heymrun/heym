import { onMounted, onUnmounted, ref, type Ref } from "vue";

/** Gap kept between the assistant panel and the viewport edges. */
export const AI_PANEL_GAP = 24;
/** Editor toolbar height the default placement sits below. */
export const AI_PANEL_HEADER_OFFSET = 64;
export const AI_PANEL_MIN_WIDTH = 360;
export const AI_PANEL_MIN_HEIGHT = 480;
const DRAG_THRESHOLD_PX = 4;
const STORAGE_KEY = "heym-ai-assistant-panel-frame";

export interface AiPanelFrame {
  left: number;
  top: number;
  width: number;
  height: number;
}

export type AiPanelResizeEdge =
  | "top"
  | "bottom"
  | "left"
  | "right"
  | "top-left"
  | "top-right"
  | "bottom-left"
  | "bottom-right";

interface Viewport {
  width: number;
  height: number;
}

/** Default width: about 34% of the viewport, between 360px and 620px. */
export function estimateAiPanelWidth(viewportWidth: number): number {
  const preferred = Math.min(620, Math.max(360, viewportWidth * 0.34));
  const maxWidth = Math.max(AI_PANEL_MIN_WIDTH, viewportWidth - AI_PANEL_GAP * 2);
  return Math.min(preferred, maxWidth);
}

export function defaultAiPanelFrame(viewport: Viewport): AiPanelFrame {
  const width = estimateAiPanelWidth(viewport.width);
  const top = AI_PANEL_HEADER_OFFSET + AI_PANEL_GAP;
  const available = Math.max(AI_PANEL_MIN_HEIGHT, viewport.height - top - AI_PANEL_GAP);
  return clampAiPanelFrame(
    {
      left: viewport.width - AI_PANEL_GAP - width,
      top,
      width,
      height: available,
    },
    viewport,
  );
}

export function clampAiPanelFrame(frame: AiPanelFrame, viewport: Viewport): AiPanelFrame {
  const maxWidth = Math.max(AI_PANEL_MIN_WIDTH, viewport.width - AI_PANEL_GAP * 2);
  const maxHeight = Math.max(AI_PANEL_MIN_HEIGHT, viewport.height - AI_PANEL_GAP * 2);
  const width = Math.min(Math.max(AI_PANEL_MIN_WIDTH, frame.width), maxWidth);
  const height = Math.min(Math.max(AI_PANEL_MIN_HEIGHT, frame.height), maxHeight);
  const maxLeft = Math.max(AI_PANEL_GAP, viewport.width - width - AI_PANEL_GAP);
  const maxTop = Math.max(AI_PANEL_GAP, viewport.height - height - AI_PANEL_GAP);
  return {
    left: Math.min(Math.max(AI_PANEL_GAP, frame.left), maxLeft),
    top: Math.min(Math.max(AI_PANEL_GAP, frame.top), maxTop),
    width,
    height,
  };
}

function suppressClickAfterDrag(): void {
  const suppress = (clickEvent: Event): void => {
    clickEvent.preventDefault();
    clickEvent.stopPropagation();
    window.removeEventListener("click", suppress, true);
  };
  window.addEventListener("click", suppress, true);
}

function readStoredFrame(): Partial<AiPanelFrame> | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const record = parsed as Partial<AiPanelFrame>;
    if (
      typeof record.left !== "number" ||
      typeof record.top !== "number" ||
      typeof record.height !== "number"
    ) {
      return null;
    }
    return record;
  } catch {
    return null;
  }
}

/**
 * Desktop placement for the canvas AI Assistant. Drag the header to move it,
 * and drag an edge to change width or height. Mobile sheets ignore this.
 */
export function useAiAssistantPanelFrame(enabled: () => boolean): {
  frame: Ref<AiPanelFrame | null>;
  dragging: Ref<boolean>;
  resizing: Ref<boolean>;
  onHeaderPointerDown: (event: PointerEvent) => void;
  onResizePointerDown: (edge: AiPanelResizeEdge, event: PointerEvent) => void;
  resetFrame: () => void;
} {
  const frame = ref<AiPanelFrame | null>(null);
  const dragging = ref(false);
  const resizing = ref(false);

  function viewport(): Viewport {
    return { width: window.innerWidth, height: window.innerHeight };
  }

  function place(next: AiPanelFrame): void {
    frame.value = clampAiPanelFrame(next, viewport());
  }

  function persist(): void {
    if (!frame.value) return;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(frame.value));
  }

  function restore(): void {
    if (!enabled()) return;
    const stored = readStoredFrame();
    const fallback = defaultAiPanelFrame(viewport());
    place({
      left: stored?.left ?? fallback.left,
      top: stored?.top ?? fallback.top,
      width: typeof stored?.width === "number" ? stored.width : fallback.width,
      height: stored?.height ?? fallback.height,
    });
  }

  function onHeaderPointerDown(event: PointerEvent): void {
    if (!enabled() || !frame.value || event.button !== 0) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("[data-ai-panel-no-drag]")) return;

    const origin = { ...frame.value };
    const startX = event.clientX;
    const startY = event.clientY;
    const pointerId = event.pointerId;
    let moved = false;
    if (event.currentTarget instanceof HTMLElement) {
      event.currentTarget.setPointerCapture(pointerId);
    }

    function onMove(ev: PointerEvent): void {
      if (ev.pointerId !== pointerId) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      if (!moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
      moved = true;
      dragging.value = true;
      place({
        left: origin.left + dx,
        top: origin.top + dy,
        width: origin.width,
        height: origin.height,
      });
    }

    function onUp(ev: PointerEvent): void {
      if (ev.pointerId !== pointerId) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      dragging.value = false;
      if (moved) {
        persist();
        suppressClickAfterDrag();
      }
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function onResizePointerDown(edge: AiPanelResizeEdge, event: PointerEvent): void {
    if (!enabled() || !frame.value || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const origin = { ...frame.value };
    const startX = event.clientX;
    const startY = event.clientY;
    const pointerId = event.pointerId;
    resizing.value = true;
    if (event.currentTarget instanceof HTMLElement) {
      event.currentTarget.setPointerCapture(pointerId);
    }

    function onMove(ev: PointerEvent): void {
      if (ev.pointerId !== pointerId) return;
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      const fromTop = edge === "top" || edge.startsWith("top-");
      const fromBottom = edge === "bottom" || edge.startsWith("bottom-");
      const fromLeft = edge === "left" || edge.endsWith("-left");
      const fromRight = edge === "right" || edge.endsWith("-right");
      const next = { ...origin };
      if (fromBottom) next.height = origin.height + dy;
      if (fromTop) next.height = origin.height - dy;
      if (fromRight) next.width = origin.width + dx;
      if (fromLeft) next.width = origin.width - dx;
      const clamped = clampAiPanelFrame(next, viewport());
      if (fromTop) clamped.top = origin.top + origin.height - clamped.height;
      if (fromLeft) clamped.left = origin.left + origin.width - clamped.width;
      frame.value = clampAiPanelFrame(clamped, viewport());
    }

    function onUp(ev: PointerEvent): void {
      if (ev.pointerId !== pointerId) return;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      resizing.value = false;
      persist();
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  function resetFrame(): void {
    localStorage.removeItem(STORAGE_KEY);
    if (!enabled()) return;
    place(defaultAiPanelFrame(viewport()));
  }

  function onWindowResize(): void {
    if (!enabled() || !frame.value) return;
    place(frame.value);
  }

  onMounted(() => {
    restore();
    window.addEventListener("resize", onWindowResize);
  });

  onUnmounted(() => {
    window.removeEventListener("resize", onWindowResize);
  });

  return { frame, dragging, resizing, onHeaderPointerDown, onResizePointerDown, resetFrame };
}
