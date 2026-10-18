/** Sticky header covers the browser's native drag-scroll strip, so workflow drags scroll themselves. */
export const WORKFLOW_DRAG_SCROLL_HEADER_PX = 64;
export const WORKFLOW_DRAG_SCROLL_BAND_PX = 88;
export const WORKFLOW_DRAG_SCROLL_MAX_PX = 7;

const SCROLLABLE_OVERFLOW = new Set(["auto", "scroll", "overlay"]);

export interface WorkflowDragEdgeScrollInput {
  clientY: number;
  viewportHeight: number;
  topInset: number;
  band?: number;
  maxSpeed?: number;
}

export interface WorkflowDragEdgeScrollDeps {
  scrollBy: (deltaY: number) => void;
  viewportHeight: () => number;
  topInset: () => number;
  requestFrame: (callback: () => void) => number;
  cancelFrame: (handle: number) => void;
}

export interface WorkflowDragEdgeScroller {
  start: () => void;
  stop: () => void;
  track: (clientY: number) => void;
}

export interface WorkflowDragEdgeScrollBinding {
  start: () => void;
  stop: () => void;
}

function speedFromDepth(depth: number, maxSpeed: number): number {
  const clamped = Math.min(Math.max(depth, 0), 1);
  if (clamped <= 0) return 0;
  return Math.max(1, Math.round(clamped * maxSpeed));
}

/** Negative values scroll up. Speed grows as the pointer moves deeper into the edge band. */
export function workflowDragEdgeScrollDelta(input: WorkflowDragEdgeScrollInput): number {
  const { clientY, viewportHeight, topInset } = input;
  if (viewportHeight <= 0) return 0;

  const band = input.band ?? WORKFLOW_DRAG_SCROLL_BAND_PX;
  const maxSpeed = input.maxSpeed ?? WORKFLOW_DRAG_SCROLL_MAX_PX;
  const topZone = Math.min(Math.max(topInset, 0) + band, viewportHeight / 2);
  if (topZone <= 0) return 0;

  const bottomStart = Math.max(viewportHeight - band, topZone);
  if (clientY < topZone) {
    const depth = (topZone - Math.max(clientY, 0)) / topZone;
    return -speedFromDepth(depth, maxSpeed);
  }
  if (clientY > bottomStart) {
    const span = Math.max(viewportHeight - bottomStart, 1);
    const depth = (Math.min(clientY, viewportHeight) - bottomStart) / span;
    return speedFromDepth(depth, maxSpeed);
  }
  return 0;
}

export function createWorkflowDragEdgeScroller(
  deps: WorkflowDragEdgeScrollDeps,
): WorkflowDragEdgeScroller {
  let active = false;
  let frame: number | null = null;
  let clientY: number | null = null;

  function tick(): void {
    frame = null;
    if (!active || clientY === null) return;
    const deltaY = workflowDragEdgeScrollDelta({
      clientY,
      viewportHeight: deps.viewportHeight(),
      topInset: deps.topInset(),
    });
    if (deltaY !== 0) deps.scrollBy(deltaY);
    if (active) frame = deps.requestFrame(tick);
  }

  return {
    start(): void {
      active = true;
    },
    stop(): void {
      active = false;
      clientY = null;
      if (frame !== null) {
        deps.cancelFrame(frame);
        frame = null;
      }
    },
    track(nextClientY: number): void {
      if (!active) return;
      clientY = nextClientY;
      if (frame === null) frame = deps.requestFrame(tick);
    },
  };
}

function canScrollVertically(element: HTMLElement): boolean {
  const overflowY = window.getComputedStyle(element).overflowY;
  if (!SCROLLABLE_OVERFLOW.has(overflowY)) return false;
  return element.scrollHeight > element.clientHeight + 1;
}

/** Nearest ancestor that actually scrolls, otherwise the document scroller. */
export function findVerticalScrollParent(start: Element | null): HTMLElement | null {
  let current: Element | null = start?.parentElement ?? null;
  while (current) {
    if (current instanceof HTMLElement && canScrollVertically(current)) return current;
    current = current.parentElement;
  }
  const fallback = document.scrollingElement;
  if (fallback instanceof HTMLElement) return fallback;
  return document.documentElement;
}

function scrollElementBy(element: HTMLElement, deltaY: number): void {
  const maxScroll = Math.max(0, element.scrollHeight - element.clientHeight);
  const next = Math.min(maxScroll, Math.max(0, element.scrollTop + deltaY));
  if (next !== element.scrollTop) element.scrollTop = next;
}

export function readWorkflowDragScrollTopInset(): number {
  const header = document.querySelector(".app-header");
  if (!(header instanceof HTMLElement)) return WORKFLOW_DRAG_SCROLL_HEADER_PX;
  const bottom = header.getBoundingClientRect().bottom;
  if (bottom <= 0) return WORKFLOW_DRAG_SCROLL_HEADER_PX;
  return bottom;
}

/**
 * Listens in the capture phase because folder rows stop dragover from bubbling,
 * and that is when the pointer is over the folders the user is trying to reach.
 */
export function bindWorkflowDragEdgeScroll(): WorkflowDragEdgeScrollBinding {
  let listening = false;
  let scrollerElement: HTMLElement | null = null;
  let previousScrollBehavior = "";
  const engine = createWorkflowDragEdgeScroller({
    scrollBy(deltaY: number): void {
      if (scrollerElement) scrollElementBy(scrollerElement, deltaY);
    },
    viewportHeight: () => window.innerHeight,
    topInset: readWorkflowDragScrollTopInset,
    requestFrame: (callback) => window.requestAnimationFrame(callback),
    cancelFrame: (handle) => window.cancelAnimationFrame(handle),
  });

  function onDragOver(event: DragEvent): void {
    engine.track(event.clientY);
  }

  function attachScroller(): void {
    const list = document.querySelector("[data-testid='workflow-master-list']");
    const nextScroller = findVerticalScrollParent(list);
    if (scrollerElement === nextScroller) return;
    if (scrollerElement) scrollerElement.style.scrollBehavior = previousScrollBehavior;
    scrollerElement = nextScroller;
    if (!scrollerElement) return;
    previousScrollBehavior = scrollerElement.style.scrollBehavior;
    scrollerElement.style.scrollBehavior = "auto";
  }

  return {
    start(): void {
      attachScroller();
      engine.start();
      if (listening) return;
      listening = true;
      window.addEventListener("dragover", onDragOver, true);
    },
    stop(): void {
      if (listening) {
        listening = false;
        window.removeEventListener("dragover", onDragOver, true);
      }
      engine.stop();
      if (!scrollerElement) return;
      scrollerElement.style.scrollBehavior = previousScrollBehavior;
      scrollerElement = null;
    },
  };
}
