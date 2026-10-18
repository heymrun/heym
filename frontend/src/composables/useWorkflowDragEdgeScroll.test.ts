import { describe, expect, it } from "vitest";

import {
  WORKFLOW_DRAG_SCROLL_MAX_PX,
  createWorkflowDragEdgeScroller,
  workflowDragEdgeScrollDelta,
} from "./useWorkflowDragEdgeScroll";
import type { WorkflowDragEdgeScroller } from "./useWorkflowDragEdgeScroll";

const VIEWPORT = 800;
const HEADER = 64;
const BAND = 80;
const MAX_SPEED = 8;

function delta(clientY: number, viewportHeight = VIEWPORT): number {
  return workflowDragEdgeScrollDelta({
    clientY,
    viewportHeight,
    topInset: HEADER,
    band: BAND,
    maxSpeed: MAX_SPEED,
  });
}

describe("workflowDragEdgeScrollDelta", () => {
  it("stays still while the pointer is in the middle of the page", () => {
    expect(delta(400)).toBe(0);
  });

  it("scrolls up slowly just under the header and faster at the top edge", () => {
    expect(delta(143)).toBe(-1);
    expect(delta(72)).toBe(-4);
    expect(delta(0)).toBe(-MAX_SPEED);
  });

  it("scrolls down slowly at the inner bottom band and faster at the bottom edge", () => {
    expect(delta(721)).toBe(1);
    expect(delta(760)).toBe(4);
    expect(delta(VIEWPORT)).toBe(MAX_SPEED);
  });

  it("clamps a pointer outside the viewport to the nearest edge speed", () => {
    expect(delta(-20)).toBe(-MAX_SPEED);
    expect(delta(VIEWPORT + 40)).toBe(MAX_SPEED);
  });

  it("returns zero when the viewport has no height", () => {
    expect(delta(10, 0)).toBe(0);
  });

  it("keeps a dead zone on a short viewport so both edges do not cover the screen", () => {
    expect(delta(110, 200)).toBe(0);
    expect(delta(40, 200)).toBeLessThan(0);
    expect(delta(180, 200)).toBeGreaterThan(0);
  });
});

function createHarness(): {
  engine: WorkflowDragEdgeScroller;
  scrolled: number[];
  pending: Map<number, () => void>;
  flush: () => void;
} {
  const scrolled: number[] = [];
  const pending = new Map<number, () => void>();
  let nextId = 1;
  const engine = createWorkflowDragEdgeScroller({
    scrollBy: (deltaY) => {
      scrolled.push(deltaY);
    },
    viewportHeight: () => VIEWPORT,
    topInset: () => HEADER,
    requestFrame: (callback) => {
      const id = nextId;
      nextId += 1;
      pending.set(id, callback);
      return id;
    },
    cancelFrame: (handle) => {
      pending.delete(handle);
    },
  });

  function flush(): void {
    const batch = [...pending.values()];
    pending.clear();
    for (const callback of batch) callback();
  }

  return { engine, scrolled, pending, flush };
}

describe("createWorkflowDragEdgeScroller", () => {
  it("keeps scrolling while the pointer stays in the top band", () => {
    const { engine, scrolled, flush } = createHarness();
    engine.start();
    engine.track(0);
    flush();
    flush();
    expect(scrolled).toEqual([-WORKFLOW_DRAG_SCROLL_MAX_PX, -WORKFLOW_DRAG_SCROLL_MAX_PX]);
  });

  it("stops scrolling when the pointer returns to the middle", () => {
    const { engine, scrolled, flush } = createHarness();
    engine.start();
    engine.track(0);
    flush();
    engine.track(400);
    flush();
    expect(scrolled).toEqual([-WORKFLOW_DRAG_SCROLL_MAX_PX]);
  });

  it("ignores the pointer until a workflow drag has started", () => {
    const { engine, scrolled, pending, flush } = createHarness();
    engine.track(0);
    flush();
    expect(scrolled).toEqual([]);
    expect(pending.size).toBe(0);
  });

  it("cancels a pending frame when the drag ends", () => {
    const { engine, scrolled, pending, flush } = createHarness();
    engine.start();
    engine.track(0);
    expect(pending.size).toBe(1);
    engine.stop();
    flush();
    expect(pending.size).toBe(0);
    expect(scrolled).toEqual([]);
  });
});
