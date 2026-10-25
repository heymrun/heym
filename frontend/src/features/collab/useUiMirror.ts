import { watch, type Ref } from "vue";
import { useEventListener, useIntervalFn, useThrottleFn } from "@vueuse/core";

import type { ClientMessage, ServerMessage, UiAction, UiTarget } from "@/features/collab/types";
import {
  applyScroll,
  applyValue,
  describeControl,
  describeHover,
  describeKey,
  describeScroller,
  moveHover,
  pressElement,
  pressKey,
  resolveTarget,
  scrollRatio,
  typedValue,
} from "@/features/collab/uiReplay";

const FIELD_MS = 120;
const FIELD_SCAN_MS = 300;
const HOVER_MS = 100;
const SCROLL_MS = 100;
const CLICK_SLOP_PX = 6;
const REPLAY_ATTEMPTS = 8;
const REPLAY_RETRY_MS = 100;
const MAX_VALUE_CHARS = 4000;

type UiMessage = Extract<ServerMessage, { t: "ui" }>;

export interface UiMirrorDeps {
  send: (message: ClientMessage) => void;
  followerCount: Ref<number>;
}

export interface UiMirror {
  /** Replays an interaction of the person this tab follows. */
  replay(message: UiMessage): void;
  /** Clears replayed hover when following stops. */
  reset(): void;
}

/** Per element: run at most every `ms`, and once more after the last call. */
function throttlePerElement(ms: number, run: (element: HTMLElement) => void): (element: HTMLElement) => void {
  const last = new WeakMap<HTMLElement, number>();
  const timers = new WeakMap<HTMLElement, ReturnType<typeof setTimeout>>();
  return (element) => {
    const timer = timers.get(element);
    if (timer) clearTimeout(timer);
    const fire = (): void => {
      last.set(element, Date.now());
      run(element);
    };
    const wait = ms - (Date.now() - (last.get(element) ?? 0));
    if (wait <= 0) fire();
    else timers.set(element, setTimeout(fire, wait));
  };
}

/**
 * Shares this tab's clicks, typing, hover and scroll with the people following it, and replays
 * those of the person it follows. Everything is replayed against this screen's own elements,
 * so what appears comes from this tab's own data and access.
 */
export function useUiMirror({ send, followerCount }: UiMirrorDeps): UiMirror {
  const watched = (): boolean => followerCount.value > 0;
  const emit = (action: UiAction): void => send({ t: "ui", ...action });

  // Clicks: a press and release in place. A drag is not a click.
  let pressed: { target: UiTarget; x: number; y: number } | null = null;
  useEventListener(document, "pointerdown", (event: PointerEvent) => {
    pressed = null;
    if (!event.isTrusted || !watched()) return;
    const target = describeControl(event.target);
    if (target) pressed = { target, x: event.clientX, y: event.clientY };
  }, { capture: true });
  useEventListener(document, "pointerup", (event: PointerEvent) => {
    const press = pressed;
    pressed = null;
    if (!press || !event.isTrusted) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) > CLICK_SLOP_PX) return;
    emit({ action: "click", target: press.target });
  }, { capture: true });

  // Fields: typing as it happens, plus text a page writes itself (a picked file's name).
  let lastValues = new WeakMap<HTMLElement, string>();
  const sendField = throttlePerElement(FIELD_MS, (field) => {
    const value = typedValue(field);
    const target = describeControl(field);
    if (value === null || !target) return;
    lastValues.set(field, value);
    emit({ action: "input", target, value: value.slice(0, MAX_VALUE_CHARS) });
  });
  const onField = (event: Event): void => {
    if (watched() && event.target instanceof HTMLElement && typedValue(event.target) !== null) {
      sendField(event.target);
    }
  };
  useEventListener(document, "input", onField, { capture: true });
  useEventListener(document, "change", onField, { capture: true });
  useIntervalFn(() => {
    if (!watched()) return;
    for (const field of document.querySelectorAll<HTMLElement>("input, textarea, select")) {
      const value = typedValue(field);
      if (value === null || field.getClientRects().length === 0) continue;
      const sent = lastValues.get(field);
      if (sent === undefined ? value !== "" : sent !== value) sendField(field);
    }
  }, FIELD_SCAN_MS);
  // A new follower gets the fields that are already filled in.
  watch(followerCount, (count, previous) => {
    if (count > (previous ?? 0)) lastValues = new WeakMap();
  });

  // Keys in dialogs that change them without typing (Escape clearing a search, shortcuts).
  // Window capture, added before any dialog opens, runs ahead of the dialog's own Escape
  // handler, which stops the event when Escape only clears its search.
  useEventListener(window, "keydown", (event: KeyboardEvent) => {
    if (!event.isTrusted || event.repeat || !watched()) return;
    const target = describeKey(event);
    if (target) emit({ action: "key", target, key: event.key });
  }, { capture: true });

  // Hover: whatever opens on hover (timeline details, menus) opens for followers too.
  let hovered: EventTarget | null = null;
  const sendHover = useThrottleFn(
    (target: UiTarget | null) => emit({ action: "hover", target }),
    HOVER_MS,
    true,
  );
  useEventListener(document, "pointerover", (event: PointerEvent) => {
    if (!event.isTrusted || !watched() || event.target === hovered) return;
    hovered = event.target;
    void sendHover(describeHover(event.target));
  }, { capture: true });

  // Scroll: panels and dialogs scroll to the same share of their length.
  const sendScroll = throttlePerElement(SCROLL_MS, (element) => {
    const target = describeScroller(element);
    if (target) emit({ action: "scroll", target, ...scrollRatio(element) });
  });
  useEventListener(document, "scroll", (event: Event) => {
    if (watched() && event.target instanceof HTMLElement) sendScroll(event.target);
  }, { capture: true, passive: true });

  // Replay. Clicks and typing keep their order: a field may only exist after an earlier click.
  let queue: Promise<void> = Promise.resolve();
  let replayedHover: HTMLElement | null = null;

  async function resolveSoon(target: UiTarget, attempts: number): Promise<HTMLElement | null> {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const element = resolveTarget(target);
      if (element) return element;
      await new Promise((resolve) => setTimeout(resolve, REPLAY_RETRY_MS));
    }
    return null;
  }

  function replay(message: UiMessage): void {
    switch (message.action) {
      case "hover": {
        const element = message.target ? resolveTarget(message.target) : null;
        if (element !== replayedHover) {
          moveHover(replayedHover, element);
          replayedHover = element;
        }
        return;
      }
      case "scroll":
        void resolveSoon(message.target, 3).then((element) => {
          if (element) applyScroll(element, message);
        });
        return;
      case "click":
        queue = queue.then(async () => {
          const element = await resolveSoon(message.target, REPLAY_ATTEMPTS);
          if (element) pressElement(element);
        });
        return;
      case "input":
        queue = queue.then(async () => {
          const element = await resolveSoon(message.target, REPLAY_ATTEMPTS);
          if (element) applyValue(element, message.value);
        });
        return;
      case "key":
        queue = queue.then(async () => {
          const element = await resolveSoon(message.target, REPLAY_ATTEMPTS);
          if (element) pressKey(element, message.key);
        });
        return;
    }
  }

  function reset(): void {
    moveHover(replayedHover, null);
    replayedHover = null;
  }

  return { replay, reset };
}
