/**
 * The app-wide Ctrl/Cmd+click convention: open the target in a new browser tab.
 * Plain click stays in the same tab.
 */
export function isOpenInNewTab(event?: MouseEvent | KeyboardEvent | null): boolean {
  if (!event) return false;
  return event.ctrlKey || event.metaKey;
}

/**
 * Command palette: open in a new browser tab on Ctrl/Cmd+click or Ctrl/Cmd+Enter.
 * Plain click and plain Enter stay in the same tab.
 */
export function isPaletteOpenInNewTab(event?: MouseEvent | KeyboardEvent | null): boolean {
  if (!event) return false;
  if (event instanceof KeyboardEvent) {
    return event.key === "Enter" && isOpenInNewTab(event);
  }
  return isOpenInNewTab(event);
}
