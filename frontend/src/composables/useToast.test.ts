import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useToast } from "./useToast";

// toastMessage/toastType/toastVisible/hideTimer are ALL module-scoped - a
// deliberate singleton so any component can trigger a toast, per the
// source's own comment. That means state from one test can leak into the
// next unless every test ends with a known-clean state. hideToast() is a
// reliable reset (clears the timer and sets visible to false) - call it in
// afterEach regardless of what a given test did, so leftover visible/timer
// state never reaches the next test.
beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  const { hideToast } = useToast();
  hideToast();
  vi.useRealTimers();
});

describe("showToast", () => {
  it("sets message, type, and visible", () => {
    const { showToast, toastMessage, toastType, toastVisible } = useToast();

    showToast("Saved", "success");

    expect(toastMessage.value).toBe("Saved");
    expect(toastType.value).toBe("success");
    expect(toastVisible.value).toBe(true);
  });

  it("defaults to type success when none is given", () => {
    const { showToast, toastType } = useToast();

    showToast("Done");

    expect(toastType.value).toBe("success");
  });

  it("hides itself automatically after the default duration", () => {
    const { showToast, toastVisible } = useToast();

    showToast("Saved");
    expect(toastVisible.value).toBe(true);

    vi.advanceTimersByTime(4000);

    expect(toastVisible.value).toBe(false);
  });

  it("honors a custom duration", () => {
    const { showToast, toastVisible } = useToast();

    showToast("Saved", "success", 1000);
    vi.advanceTimersByTime(999);
    expect(toastVisible.value).toBe(true);

    vi.advanceTimersByTime(1);
    expect(toastVisible.value).toBe(false);
  });

  it("a new showToast call before the previous one hides resets the hide timer", () => {
    const { showToast, toastMessage, toastVisible } = useToast();

    showToast("First", "success", 1000);
    vi.advanceTimersByTime(900);
    showToast("Second", "info", 1000);

    // Only 100ms has passed since "Second" was shown - the first toast's
    // timer must have been cleared, or this would hide "Second" too early.
    vi.advanceTimersByTime(100);
    expect(toastVisible.value).toBe(true);
    expect(toastMessage.value).toBe("Second");

    vi.advanceTimersByTime(900);
    expect(toastVisible.value).toBe(false);
  });
});

describe("hideToast", () => {
  it("hides an active toast immediately, before its timer would have fired", () => {
    const { showToast, hideToast, toastVisible } = useToast();

    showToast("Saved", "success", 4000);
    hideToast();

    expect(toastVisible.value).toBe(false);
  });

  it("clears the pending hide timer so it does not fire later and affect a new toast", () => {
    const { showToast, hideToast, toastVisible } = useToast();

    showToast("First", "success", 1000);
    hideToast();
    showToast("Second", "success", 5000);

    // If the first toast's timer weren't cleared by hideToast(), it would
    // fire at the 1000ms mark and incorrectly hide "Second" early.
    vi.advanceTimersByTime(1000);
    expect(toastVisible.value).toBe(true);
  });

  it("calling hideToast with nothing shown is a no-op", () => {
    const { hideToast, toastVisible } = useToast();

    expect(() => hideToast()).not.toThrow();
    expect(toastVisible.value).toBe(false);
  });
});
