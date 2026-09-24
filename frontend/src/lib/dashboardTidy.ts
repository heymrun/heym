import type { DashboardWidget, WidgetLayout } from "@/types/dashboard";

const TIDY_ROW_HEIGHT = 5; // grid row units per widget

// Randomly split N widgets into rows of 2 or 3 (with an occasional trailing 1),
// producing variations like 2-2-2, 2-3-3, or 3-3-1 on each press.
function buildRowSizes(count: number, random: () => number): number[] {
  const rows: number[] = [];
  let remaining = count;
  while (remaining > 0) {
    if (remaining <= 2) {
      rows.push(remaining);
      break;
    }
    const size = random() < 0.5 ? 2 : 3;
    rows.push(size);
    remaining -= size;
  }
  return rows;
}

/** New layouts that arrange the widgets, in position order, into a tidy 12-column grid. */
export function tidyLayouts(
  widgets: DashboardWidget[],
  random: () => number = Math.random,
): { id: string; layout: WidgetLayout }[] {
  const ordered = [...widgets].sort((a, b) => a.position - b.position);
  const updates: { id: string; layout: WidgetLayout }[] = [];
  let index = 0;
  let y = 0;
  for (const size of buildRowSizes(ordered.length, random)) {
    const w = Math.floor(12 / size);
    for (let col = 0; col < size; col++) {
      const widget = ordered[index];
      if (widget) {
        updates.push({ id: widget.id, layout: { x: col * w, y, w, h: TIDY_ROW_HEIGHT } });
      }
      index += 1;
    }
    y += TIDY_ROW_HEIGHT;
  }
  return updates;
}
