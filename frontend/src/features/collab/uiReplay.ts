import type { CursorAnchor, UiTarget } from "@/features/collab/types";
import { dialogKey } from "@/features/collab/regions";

/**
 * Finds "the same element" on another screen. Clicks and typing match by meaning (test id,
 * label, visible text, icon) among identical ones in the same dialog or panel, never by DOM
 * path: an owner's dialog can differ from a collaborator's, and a wrong match must not click.
 * Hover and scroll, which change nothing, may also match by structure.
 */

const INTERACTIVE = [
  "button",
  "a",
  "summary",
  "label",
  "select",
  "textarea",
  "input",
  '[role="button"]',
  '[role="tab"]',
  '[role="option"]',
  '[role="menuitem"]',
  '[role="checkbox"]',
  '[role="switch"]',
  '[role="radio"]',
].join(", ");
// Never replayed: they leave the page, download, pick local files or use the microphone.
const SKIP = 'a[href][target], [download], input[type="file"]';
// Collaboration's own controls (avatars, mic, follow label) stay each person's own.
const SKIP_WITHIN = "[data-collab-no-mirror], [data-collab-keep-follow]";
// The canvas is mirrored by live editing and follow; only buttons on nodes are replayed.
const CANVAS = ".vue-flow";
const CANVAS_CONTROLS = ".vue-flow__node button, .vue-flow__node [role='button']";
const TEXT_FIELD_TYPES = new Set(["", "text", "email", "search", "url", "number", "tel"]);
const MAX_TEXT = 60;
const SCROLL_TAG = "#scroll";
const SCOPE_TAG = "#scope";
const ANCHOR_DEPTH = 6;
const ANCHOR_MISS_MS = 500;

type Signature = Omit<UiTarget, "scope" | "index">;

function isFormField(element: Element): boolean {
  return (
    element instanceof HTMLInputElement ||
    element instanceof HTMLTextAreaElement ||
    element instanceof HTMLSelectElement
  );
}

function scopeOf(element: Element): { key: string; root: HTMLElement } {
  const dialog = element.closest<HTMLElement>('[role="dialog"]');
  const region = element.closest<HTMLElement>("[data-collab-region]");
  if (dialog && (!region || !dialog.contains(region))) {
    return { key: `dialog:${dialogKey(dialog)}`, root: dialog };
  }
  if (region) return { key: `region:${region.dataset.collabRegion}`, root: region };
  return { key: "page", root: document.body };
}

function findScope(key: string): HTMLElement | null {
  if (key === "page") return document.body;
  if (key.startsWith("region:")) {
    return document.querySelector<HTMLElement>(`[data-collab-region="${key.slice(7)}"]`);
  }
  const title = key.slice(7);
  return (
    [...document.querySelectorAll<HTMLElement>('[role="dialog"]')].find(
      (dialog) => dialogKey(dialog) === title,
    ) ?? null
  );
}

function iconOf(element: HTMLElement): string | null {
  const svg = element.querySelector("svg");
  const name = [...(svg?.classList ?? [])].find(
    (token) => token.startsWith("lucide-") && token !== "lucide-icon",
  );
  return name ?? null;
}

function signature(element: HTMLElement, structural: boolean): Signature {
  const text = isFormField(element)
    ? ""
    : (element.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, MAX_TEXT);
  // A wrapped control (a native select inside a Select) borrows its wrapper's test id.
  const named = element.closest<HTMLElement>("[data-testid]");
  const own: Signature = {
    tag: element.tagName.toLowerCase(),
    testid: named?.dataset.testid ?? null,
    label:
      element.getAttribute("aria-label") ??
      element.getAttribute("title") ??
      element.getAttribute("placeholder") ??
      element.getAttribute("name"),
    text: text || null,
    icon: text ? null : iconOf(element),
    classes: null,
  };
  if (structural && !own.label && !own.text && !own.icon) {
    own.classes = [...element.classList].slice(0, 2).join(" ") || null;
  }
  return own;
}

function sameSignature(a: Signature, b: Signature): boolean {
  return (
    a.tag === b.tag &&
    a.testid === b.testid &&
    a.label === b.label &&
    a.text === b.text &&
    a.icon === b.icon &&
    a.classes === b.classes
  );
}

function candidates(root: HTMLElement, wanted: Signature): HTMLElement[] {
  const structural = wanted.classes !== null;
  return [...root.querySelectorAll<HTMLElement>(wanted.tag)].filter((element) =>
    sameSignature(signature(element, structural), wanted),
  );
}

function describe(element: HTMLElement, structural: boolean): UiTarget | null {
  const scope = scopeOf(element);
  const own = signature(element, structural);
  // Nothing names it: a match on another screen would be a guess.
  if (!own.testid && !own.label && !own.text && !own.icon && !own.classes) return null;
  const index = candidates(scope.root, own).indexOf(element);
  return { scope: scope.key, ...own, index: Math.max(0, index) };
}

/** The control a click or keystroke hit, or null when it is not one to replay. */
export function describeControl(node: EventTarget | null): UiTarget | null {
  if (!(node instanceof Element)) return null;
  const control = node.closest<HTMLElement>(INTERACTIVE);
  if (!control || control.matches(SKIP) || control.closest(SKIP_WITHIN)) return null;
  if (control.closest(CANVAS) && !control.matches(CANVAS_CONTROLS)) return null;
  return describe(control, false);
}

/** The element under a hovering pointer, matched loosely: hovering changes nothing. */
export function describeHover(node: EventTarget | null): UiTarget | null {
  if (!(node instanceof HTMLElement) || node.closest(CANVAS) || node.closest(SKIP_WITHIN)) return null;
  return describe(node, true);
}

/** The element a pointer is over: the control under it, else the nearest nameable ancestor. */
export function anchorElement(node: EventTarget | null): { element: HTMLElement; target: UiTarget } | null {
  if (!(node instanceof Element) || node.closest(CANVAS)) return null;
  const control = node.closest<HTMLElement>(INTERACTIVE);
  const own = control ? describe(control, false) : null;
  if (control && own) return { element: control, target: own };
  let element: Element | null = node;
  while (element && !(element instanceof HTMLElement)) element = element.parentElement;
  for (let depth = 0; element instanceof HTMLElement && element !== document.body; depth += 1) {
    if (depth >= ANCHOR_DEPTH) return null;
    const target = describe(element, true);
    if (target) return { element, target };
    element = element.parentElement;
  }
  return null;
}

/** Where a pointer is inside its anchor, as shares of the element's size. */
export function anchorOffset(
  found: { element: HTMLElement; target: UiTarget } | null,
  clientX: number,
  clientY: number,
): CursorAnchor | null {
  const rect = found?.element.getBoundingClientRect();
  if (!found || !rect || rect.width === 0 || rect.height === 0) return null;
  const share = (value: number): number => Math.min(1, Math.max(0, Math.round(value * 1000) / 1000));
  return {
    target: found.target,
    fx: share((clientX - rect.left) / rect.width),
    fy: share((clientY - rect.top) / rect.height),
  };
}

/**
 * Places remote pointers on this screen's copy of their anchor. Lookups are remembered, since
 * a pointer reports many times over the same element; a miss is retried after a short wait.
 */
export function createAnchorPlacer(): (anchor: CursorAnchor) => { x: number; y: number } | null {
  const found = new Map<string, { element: HTMLElement | null; at: number }>();
  return (anchor) => {
    const key = JSON.stringify(anchor.target);
    let entry = found.get(key);
    const stale = entry
      ? entry.element
        ? !entry.element.isConnected
        : Date.now() - entry.at > ANCHOR_MISS_MS
      : true;
    if (stale) {
      if (found.size > 100) found.clear();
      entry = { element: resolveTarget(anchor.target), at: Date.now() };
      found.set(key, entry);
    }
    const rect = entry?.element?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return null;
    return { x: rect.left + anchor.fx * rect.width, y: rect.top + anchor.fy * rect.height };
  };
}

function isScrollable(element: HTMLElement): boolean {
  if (element.scrollHeight <= element.clientHeight + 1 && element.scrollWidth <= element.clientWidth + 1) {
    return false;
  }
  const style = getComputedStyle(element);
  return /(auto|scroll)/.test(`${style.overflowY} ${style.overflowX}`);
}

function scrollables(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>("*")].filter(isScrollable);
}

/** A scrolled container, named by its order among the scrollable ones in its dialog or panel. */
export function describeScroller(node: EventTarget | null): UiTarget | null {
  if (!(node instanceof HTMLElement) || node.closest(CANVAS)) return null;
  const scope = scopeOf(node);
  const index = scrollables(scope.root).indexOf(node);
  if (index < 0) return null;
  return {
    scope: scope.key,
    tag: SCROLL_TAG,
    testid: null,
    label: null,
    text: null,
    icon: null,
    classes: null,
    index,
  };
}

/** This screen's copy of an element described on another screen. */
export function resolveTarget(target: UiTarget): HTMLElement | null {
  const root = findScope(target.scope);
  if (!root) return null;
  if (target.tag === SCROLL_TAG) return scrollables(root)[target.index] ?? null;
  if (target.tag === SCOPE_TAG) return root;
  return candidates(root, target)[target.index] ?? null;
}

/** Text in a field that is mirrored at all: never passwords, files or hidden inputs. */
export function typedValue(node: EventTarget | null): string | null {
  if (node instanceof HTMLTextAreaElement || node instanceof HTMLSelectElement) return node.value;
  if (node instanceof HTMLInputElement && TEXT_FIELD_TYPES.has(node.type)) return node.value;
  return null;
}

/** Sets a field the way typing would, so the page's own bindings see the change. */
export function applyValue(element: HTMLElement, value: string): void {
  if (element instanceof HTMLSelectElement) {
    if (element.value === value) return;
    element.value = value;
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }
  if (!(element instanceof HTMLInputElement) && !(element instanceof HTMLTextAreaElement)) return;
  if (element.value === value) return;
  const prototype = element instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function pointerInit(element: HTMLElement): MouseEventInit {
  const rect = element.getBoundingClientRect();
  return {
    bubbles: true,
    cancelable: true,
    composed: true,
    button: 0,
    clientX: rect.left + rect.width / 2,
    clientY: rect.top + rect.height / 2,
  };
}

/** A full press, so handlers bound to pointerdown or mousedown react as well as click ones. */
export function pressElement(element: HTMLElement): void {
  const init = pointerInit(element);
  element.dispatchEvent(new PointerEvent("pointerdown", { ...init, pointerType: "mouse" }));
  element.dispatchEvent(new MouseEvent("mousedown", init));
  element.dispatchEvent(new PointerEvent("pointerup", { ...init, pointerType: "mouse" }));
  element.dispatchEvent(new MouseEvent("mouseup", init));
  element.dispatchEvent(new MouseEvent("click", init));
}

/**
 * A key pressed in a dialog that changes it without typing: Escape (clears a search, closes),
 * or a shortcut letter or arrow outside a field. Typing itself is mirrored as field values.
 */
export function describeKey(event: KeyboardEvent): UiTarget | null {
  if (event.ctrlKey || event.metaKey || event.altKey || !(event.target instanceof HTMLElement)) {
    return null;
  }
  const typing = typedValue(event.target) !== null || event.target.isContentEditable;
  const shortcut = event.key.length === 1 || event.key.startsWith("Arrow");
  if (event.key !== "Escape" && (typing || !shortcut)) return null;
  // Focus can sit on the page or a dialog's backdrop (after a focused field disappears); while a
  // dialog is open, the key is still the dialog's.
  const dialog =
    event.target.closest<HTMLElement>('[role="dialog"]') ??
    [...document.querySelectorAll<HTMLElement>('[role="dialog"]')].at(-1);
  if (!dialog) return null;
  return describeControl(event.target) ?? {
    scope: `dialog:${dialogKey(dialog)}`,
    tag: SCOPE_TAG,
    testid: null,
    label: null,
    text: null,
    icon: null,
    classes: null,
    index: 0,
  };
}

export function pressKey(element: HTMLElement, key: string): void {
  // Outside a dialog, Escape would reach the editor's own handlers and end following.
  if (!element.closest('[role="dialog"]')) return;
  const init = { key, bubbles: true, cancelable: true, composed: true };
  element.dispatchEvent(new KeyboardEvent("keydown", init));
  element.dispatchEvent(new KeyboardEvent("keyup", init));
}

function ancestry(element: HTMLElement | null): HTMLElement[] {
  const chain: HTMLElement[] = [];
  for (let node = element; node && node !== document.body; node = node.parentElement) {
    chain.push(node);
  }
  return chain;
}

/** Moves a replayed hover from one element to another, with enter and leave on each level. */
export function moveHover(from: HTMLElement | null, to: HTMLElement | null): void {
  const left = ancestry(from);
  const entered = ancestry(to);
  if (from) {
    const init = pointerInit(from);
    from.dispatchEvent(new PointerEvent("pointerout", { ...init, pointerType: "mouse" }));
    from.dispatchEvent(new MouseEvent("mouseout", init));
    for (const node of left.filter((item) => !entered.includes(item))) {
      node.dispatchEvent(new PointerEvent("pointerleave", { ...init, bubbles: false }));
      node.dispatchEvent(new MouseEvent("mouseleave", { ...init, bubbles: false }));
    }
  }
  if (to) {
    const init = pointerInit(to);
    to.dispatchEvent(new PointerEvent("pointerover", { ...init, pointerType: "mouse" }));
    to.dispatchEvent(new MouseEvent("mouseover", init));
    for (const node of entered.filter((item) => !left.includes(item)).reverse()) {
      node.dispatchEvent(new PointerEvent("pointerenter", { ...init, bubbles: false }));
      node.dispatchEvent(new MouseEvent("mouseenter", { ...init, bubbles: false }));
    }
  }
}

/** Scroll position as a share of the scrollable distance, so different heights still line up. */
export function scrollRatio(element: HTMLElement): { top: number; left: number } {
  const maxTop = element.scrollHeight - element.clientHeight;
  const maxLeft = element.scrollWidth - element.clientWidth;
  return {
    top: maxTop > 0 ? element.scrollTop / maxTop : 0,
    left: maxLeft > 0 ? element.scrollLeft / maxLeft : 0,
  };
}

export function applyScroll(element: HTMLElement, ratio: { top: number; left: number }): void {
  element.scrollTop = ratio.top * (element.scrollHeight - element.clientHeight);
  element.scrollLeft = ratio.left * (element.scrollWidth - element.clientWidth);
}

/** What a hovering person reads: an open tooltip, or the title of the element under them. */
export function hoverHint(node: EventTarget | null): string | null {
  const tooltip = [...document.querySelectorAll<HTMLElement>('[role="tooltip"]')]
    .map((element) => (element.textContent ?? "").replace(/\s+/g, " ").trim())
    .find((text) => text.length > 0);
  if (tooltip) return tooltip.slice(0, 120);
  const titled = node instanceof Element ? node.closest<HTMLElement>("[title]") : null;
  const title = titled?.getAttribute("title")?.trim();
  return title ? title.slice(0, 120) : null;
}
