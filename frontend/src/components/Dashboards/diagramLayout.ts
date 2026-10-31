import type { GanttTask } from "@/types/dashboard";

export { entityLayout, entityScene, relationPath } from "./entityDiagramLayout";
export type { PositionedEntity, RelationPath } from "./entityDiagramLayout";

export interface DiagramSize {
  width: number;
  height: number;
}

export interface ScheduledTask extends GanttTask {
  x: number;
  y: number;
  width: number;
  completion: number;
  displayLabel: string;
}

export interface GanttLayout extends DiagramSize {
  tasks: ScheduledTask[];
  ticks: { x: number; label: string }[];
  axisY: number;
  gridTop: number;
  gridBottom: number;
}

/** UTC parsing also keeps date-only previews consistent with the backend. */
export function taskTime(value: string): number {
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/.test(value);
  return Date.parse(value.length === 10 ? `${value}T00:00:00Z` : zoned ? value : `${value}Z`);
}

export function truncateDiagramText(value: string, width: number, fontSize = 12): string {
  const limit = Math.max(1, Math.floor(width / (fontSize * 0.62)));
  return value.length > limit ? `${value.slice(0, Math.max(1, limit - 1))}…` : value;
}

/** Recompute pixel geometry for both dimensions; long schedules scroll at a readable row size. */
export function ganttLayout(tasks: GanttTask[], viewport: DiagramSize = { width: 840, height: 240 }): GanttLayout {
  const width = Math.max(1, viewport.width);
  const valid = tasks.filter((task) => Number.isFinite(taskTime(task.start)) &&
    Number.isFinite(taskTime(task.end)) && taskTime(task.end) >= taskTime(task.start));
  const rowHeight = Math.max(32, Math.min(56, (viewport.height - 48) / Math.max(1, valid.length)));
  const height = Math.max(viewport.height, 48 + rowHeight * valid.length);
  const top = Math.max(8, (height - (40 + rowHeight * valid.length)) / 2);
  const labelWidth = Math.min(160, Math.max(72, width * 0.24), width * 0.45);
  const timelineLeft = labelWidth + Math.min(16, width * 0.07);
  const timelineWidth = Math.max(1, width - timelineLeft - Math.min(32, Math.max(16, width * 0.12)));
  const base: GanttLayout = { width, height, tasks: [], ticks: [], axisY: top + 12, gridTop: top + 24, gridBottom: height - top };
  if (!valid.length) return base;
  const start = Math.min(...valid.map((task) => taskTime(task.start)));
  const end = Math.max(...valid.map((task) => taskTime(task.end)));
  const span = Math.max(end - start, 86400000);
  const tickCount = Math.max(1, Math.min(6, Math.floor(timelineWidth / 95) + 1));
  const formatter = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "UTC" });
  return {
    ...base,
    tasks: valid.map((task, index) => ({
      ...task,
      x: timelineLeft + (taskTime(task.start) - start) / span * timelineWidth,
      y: top + 32 + index * rowHeight + (rowHeight - 24) / 2,
      width: Math.max(Math.min(4, timelineWidth), (taskTime(task.end) - taskTime(task.start)) / span * timelineWidth),
      completion: Math.max(0, Math.min(100, task.progress ?? 0)),
      displayLabel: truncateDiagramText(task.label, labelWidth - 12),
    })),
    ticks: Array.from({ length: tickCount }, (_, index) => ({
      x: timelineLeft + index / Math.max(1, tickCount - 1) * timelineWidth,
      label: formatter.format(new Date(start + index / Math.max(1, tickCount - 1) * span)),
    })),
  };
}

export interface DependencyPath {
  key: string;
  path: string;
  points: { x: number; y: number }[];
}

/** Approach every successor from the left, routing overlapping dates around the task rows. */
export function dependencyPaths(tasks: ScheduledTask[]): DependencyPath[] {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const right = Math.max(0, ...tasks.map((task) => task.x + task.width));
  return tasks.flatMap((task) => [...new Set(task.dependencies ?? [])].flatMap((id) => {
    const source = byId.get(id);
    if (!source || source === task) return [];
    const x = source.x + source.width;
    const points = [{ x, y: source.y + 12 }];
    if (x + 12 <= task.x && Math.abs(task.y - source.y) <= 56) {
      const lane = (x + task.x) / 2;
      points.push({ x: lane, y: source.y + 12 }, { x: lane, y: task.y + 12 });
    } else {
      const lane = Math.abs(task.y - source.y) <= 56.1 ? x + 8 : right + 10;
      const rowGap = task.y > source.y ? task.y - 4 : task.y + 28;
      points.push({ x: lane, y: source.y + 12 }, { x: lane, y: rowGap },
        { x: task.x - 8, y: rowGap }, { x: task.x - 8, y: task.y + 12 });
    }
    points.push({ x: task.x, y: task.y + 12 });
    return [{ key: `${id}-${task.id}`, points,
      path: points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" "),
    }];
  }));
}
