import type { Component } from "vue";

/**
 * One widget header action. The inline icon row (sm+) and the collapsed 3-dot menu
 * (small screens) render the same list, so the two stay in sync.
 */
export interface WidgetAction {
  key: string;
  icon: Component;
  label: string;
  danger?: boolean;
  disabled?: () => boolean;
  run: () => void;
}
