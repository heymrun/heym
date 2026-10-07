import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useLongPress } from "./useLongPress";

// Pure timer logic, no DOM/window/document faking needed - `TouchEvent` is
// never constructed for real, just a plain object with a `.touches` array
// matching the one field the source reads.
function buildTouchEvent(touchCount: number): TouchEvent {
  return { touches: new Array(touchCount).fill({}) } as unknown as TouchEvent;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("onTouchStart", () => {
  it("fires onLongPress after the default delay for a single-touch start", () => {
    const onLongPress = vi.fn();
    const { handlers } = useLongPress(onLongPress);

    handlers.onTouchStart(buildTouchEvent(1));
    expect(onLongPress).not.toHaveBeenCalled();

    vi.advanceTimersByTime(300);

    expect(onLongPress).toHaveBeenCalledTimes(1);
  });

  it("uses a custom delay when provided", () => {
    const onLongPress = vi.fn();
    const { handlers } = useLongPress(onLongPress, { delay: 1000 });

    handlers.onTouchStart(buildTouchEvent(1));
    vi.advanceTimersByTime(300);
    expect(onLongPress).not.toHaveBeenCalled();

    vi.advanceTimersByTime(700);
    expect(onLongPress).toHaveBeenCalledTimes(1);
  });

  it("sets isLongPressing to true immediately on touch start", () => {
    const { handlers, isLongPressing } = useLongPress(vi.fn());

    handlers.onTouchStart(buildTouchEvent(1));

    expect(isLongPressing.value).toBe(true);
  });

  it("ignores multi-touch starts (more than one finger)", () => {
    const onLongPress = vi.fn();
    const { handlers, isLongPressing } = useLongPress(onLongPress);

    handlers.onTouchStart(buildTouchEvent(2));
    vi.advanceTimersByTime(300);

    expect(onLongPress).not.toHaveBeenCalled();
    expect(isLongPressing.value).toBe(false);
  });

  it("restarts the timer if onTouchStart fires again before the delay elapses", () => {
    const onLongPress = vi.fn();
    const { handlers } = useLongPress(onLongPress);

    handlers.onTouchStart(buildTouchEvent(1));
    vi.advanceTimersByTime(200);
    handlers.onTouchStart(buildTouchEvent(1));
    vi.advanceTimersByTime(200);

    // 400ms of real elapsed time but the second start reset the clock -
    // only 200ms has passed since the most recent start, so it shouldn't
    // have fired yet.
    expect(onLongPress).not.toHaveBeenCalled();

    vi.advanceTimersByTime(100);
    expect(onLongPress).toHaveBeenCalledTimes(1);
  });
});

describe("onTouchEnd / onTouchMove", () => {
  it("onTouchEnd before the delay cancels the long press", () => {
    const onLongPress = vi.fn();
    const { handlers, isLongPressing } = useLongPress(onLongPress);

    handlers.onTouchStart(buildTouchEvent(1));
    handlers.onTouchEnd();
    vi.advanceTimersByTime(300);

    expect(onLongPress).not.toHaveBeenCalled();
    expect(isLongPressing.value).toBe(false);
  });

  it("onTouchMove before the delay cancels the long press", () => {
    const onLongPress = vi.fn();
    const { handlers, isLongPressing } = useLongPress(onLongPress);

    handlers.onTouchStart(buildTouchEvent(1));
    handlers.onTouchMove();
    vi.advanceTimersByTime(300);

    expect(onLongPress).not.toHaveBeenCalled();
    expect(isLongPressing.value).toBe(false);
  });

  it("calling onTouchEnd with no active press is a no-op", () => {
    const { handlers, isLongPressing } = useLongPress(vi.fn());

    expect(() => handlers.onTouchEnd()).not.toThrow();
    expect(isLongPressing.value).toBe(false);
  });
});
