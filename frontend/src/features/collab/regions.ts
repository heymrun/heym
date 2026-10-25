import type { CursorPoint, CursorRegion } from "@/features/collab/types";

/** A dialog's title, which names the same dialog on every screen. */
export function dialogKey(dialog: HTMLElement): string {
  const labelId = dialog.getAttribute("aria-labelledby");
  const label = labelId
    ? document.getElementById(labelId)?.textContent
    : dialog.getAttribute("aria-label");
  return (label ?? "").trim().slice(0, 80) || "dialog";
}

/** The region under a pointer: a marked editor area, or the dialog it is in. */
export function pointAt(target: EventTarget | null, clientX: number, clientY: number): CursorPoint | null {
  if (!(target instanceof Element)) return null;
  const marked = target.closest<HTMLElement>("[data-collab-region]");
  const dialog = target.closest<HTMLElement>('[role="dialog"]');
  // The innermost of the two wins, so a marked panel inside a dialog keeps its own region.
  const useDialog = dialog !== null && (marked === null || !dialog.contains(marked));
  const element = useDialog ? dialog : marked;
  if (!element) return null;
  const region = useDialog ? "dialog" : (element.dataset.collabRegion as CursorRegion);
  if (region === "canvas") return null;
  const rect = element.getBoundingClientRect();
  const fromLeft = clientX - rect.left;
  const anchor = fromLeft <= rect.width / 2 ? "start" : "end";
  return {
    region,
    anchor,
    x: anchor === "start" ? fromLeft : rect.right - clientX,
    y: clientY - rect.top,
    key: useDialog ? dialogKey(element) : null,
  };
}

/** This screen's copy of the region a remote pointer is in, if it is open here. */
export function regionElement(point: CursorPoint): HTMLElement | null {
  if (point.region === "dialog") {
    const dialogs = [...document.querySelectorAll<HTMLElement>('[role="dialog"]')];
    return dialogs.find((dialog) => dialogKey(dialog) === point.key) ?? null;
  }
  return document.querySelector<HTMLElement>(`[data-collab-region="${point.region}"]`);
}
