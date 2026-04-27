import { onMounted, onUnmounted } from "vue";

export const DISMISS_OVERLAYS_EVENT = "heym:dismiss-overlays";

/**
 * Dispatches a global event to close all open overlays (dialogs, history, portal, command palette, etc.).
 * Used by ESC (web) and back button (mobile).
 */
export function dismissAllOverlays(): void {
  window.dispatchEvent(new CustomEvent(DISMISS_OVERLAYS_EVENT));
}

/**
 * Call when opening an overlay so that mobile back button will close it instead of navigating away.
 */
export function pushOverlayState(): void {
  history.pushState({ overlay: true }, "", window.location.href);
}

/**
 * Sets up global ESC (web) and popstate (mobile back) handlers to dismiss all overlays.
 * Overlay components should use onDismissOverlays() to react.
 */
export function useOverlayBackHandler(): void {
  function handleKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      if (document.body.dataset.heymOverlayEscapeTrap === "true") {
        return;
      }
      if (document.body.dataset.heymLightboxOpen === "true") {
        return;
      }
      const t = event.target;
      const inNodePanel =
        t instanceof HTMLElement &&
        Boolean(t.closest(".node-panel")) &&
        (t instanceof HTMLInputElement ||
          t instanceof HTMLTextAreaElement ||
          t instanceof HTMLSelectElement ||
          t.isContentEditable);
      if (inNodePanel) {
        return;
      }
      const inExpressionOutputQuery =
        t instanceof HTMLElement &&
        Boolean(t.closest("[data-heym-expression-query-trap]"));
      if (inExpressionOutputQuery) {
        return;
      }
      const inDocsSidebar = t instanceof HTMLElement && Boolean(t.closest(".docs-sidebar"));
      const sidebarInputHasText =
        t instanceof HTMLInputElement && inDocsSidebar && t.value.length > 0;
      if (sidebarInputHasText) {
        return;
      }
      dismissAllOverlays();
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function handlePopState(): void {
    if (document.body.dataset.heymIgnoreNextOverlayDismiss === "true") {
      delete document.body.dataset.heymIgnoreNextOverlayDismiss;
      return;
    }
    dismissAllOverlays();
  }

  onMounted(() => {
    window.addEventListener("keydown", handleKeyDown, true);
    window.addEventListener("popstate", handlePopState);
  });

  onUnmounted(() => {
    window.removeEventListener("keydown", handleKeyDown, true);
    window.removeEventListener("popstate", handlePopState);
  });
}

/**
 * Subscribe to the global dismiss-overlays event.
 * Use in views and overlay components to close when ESC or mobile back is pressed.
 */
export function onDismissOverlays(callback: () => void): () => void {
  const handler = (): void => callback();

  window.addEventListener(DISMISS_OVERLAYS_EVENT, handler);
  return () => window.removeEventListener(DISMISS_OVERLAYS_EVENT, handler);
}
