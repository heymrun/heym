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

/**
 * The widgets whose grid position differs from the saved one. A drag or a resize moves the
 * widget the user holds and pushes others aside; saving only the held widget left the others
 * at their old place, so the saved layouts overlapped and the drag was undone on reload.
 */
export function movedLayouts(
  items: readonly (WidgetLayout & { i: string })[],
  widgets: readonly Pick<DashboardWidget, "id" | "layout">[],
): { id: string; layout: WidgetLayout }[] {
  const saved = new Map(widgets.map((widget) => [widget.id, widget.layout]));
  return items
    .filter((item) => {
      const before = saved.get(item.i);
      return (
        before !== undefined &&
        (before.x !== item.x || before.y !== item.y || before.w !== item.w || before.h !== item.h)
      );
    })
    .map((item) => ({ id: item.i, layout: { x: item.x, y: item.y, w: item.w, h: item.h } }));
}
