/** True when the event target is (or is inside) a field that accepts keyboard text input. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT" ||
    target.isContentEditable ||
    target.closest("input, textarea, select, [contenteditable='true'], [contenteditable='']") !== null
  );
}

/** True when the user has a non-empty text selection (e.g. output panels, dialogs). */
export function hasActiveTextSelection(): boolean {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) {
    return false;
  }
  return selection.toString().length > 0;
}

/** Prefer native copy/cut when focus is in a text field or text is selected in the UI. */
export function shouldUseNativeTextClipboard(event: KeyboardEvent): boolean {
  return isTypingTarget(event.target) || hasActiveTextSelection();
}
