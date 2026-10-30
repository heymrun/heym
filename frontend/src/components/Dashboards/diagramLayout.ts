import type { DiagramEntity, DiagramRelation, GanttTask } from "@/types/dashboard";

export const TASK_HEIGHT = 44;
export const TIMELINE_LEFT = 160;
export const TIMELINE_WIDTH = 640;

export interface ScheduledTask extends GanttTask {
  x: number;
  y: number;
  width: number;
  completion: number;
}

/** UTC parsing also keeps date-only previews consistent with the backend. */
export function taskTime(value: string): number {
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/.test(value);
  return Date.parse(value.length === 10 ? `${value}T00:00:00Z` : zoned ? value : `${value}Z`);
}

export function ganttLayout(tasks: GanttTask[]): {
  tasks: ScheduledTask[];
  ticks: { x: number; label: string }[];
} {
  const valid = tasks.filter((task) => Number.isFinite(taskTime(task.start)) &&
    Number.isFinite(taskTime(task.end)) && taskTime(task.end) >= taskTime(task.start));
  if (!valid.length) return { tasks: [], ticks: [] };
  const start = Math.min(...valid.map((task) => taskTime(task.start)));
  const end = Math.max(...valid.map((task) => taskTime(task.end)));
  const span = Math.max(end - start, 86400000);
  const formatter = new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "2-digit", timeZone: "UTC" });
  return {
    tasks: valid.map((task, index) => ({
      ...task,
      x: TIMELINE_LEFT + (taskTime(task.start) - start) / span * TIMELINE_WIDTH,
      y: 56 + index * TASK_HEIGHT,
      width: Math.max(4, (taskTime(task.end) - taskTime(task.start)) / span * TIMELINE_WIDTH),
      completion: Math.max(0, Math.min(100, task.progress ?? 0)),
    })),
    ticks: Array.from({ length: 5 }, (_, index) => ({
      x: TIMELINE_LEFT + index / 4 * TIMELINE_WIDTH,
      label: formatter.format(new Date(start + index / 4 * span)),
    })),
  };
}

export function dependencyPaths(tasks: ScheduledTask[]): { key: string; path: string }[] {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  return tasks.flatMap((task) => (task.dependencies ?? []).flatMap((id) => {
    const source = byId.get(id);
    if (!source || source === task) return [];
    const x = source.x + source.width;
    return [{ key: `${id}-${task.id}`, path: `M ${x} ${source.y + 12} H ${x + 12} V ${task.y + 12} H ${task.x}` }];
  }));
}

export interface PositionedEntity extends DiagramEntity {
  x: number;
  y: number;
  height: number;
}

/** Connected entities occupy adjacent columns; disconnected tables start a new row. */
export function entityLayout(entities: DiagramEntity[], relations: DiagramRelation[]): PositionedEntity[] {
  const ordered: DiagramEntity[] = [];
  const byId = new Map(entities.map((entity) => [entity.id, entity]));
  const seen = new Set<string>();
  for (const entity of entities) {
    const queue = [entity.id];
    while (queue.length) {
      const id = queue.shift()!;
      const next = byId.get(id);
      if (seen.has(id) || !next) continue;
      seen.add(id);
      ordered.push(next);
      for (const relation of relations) {
        if (relation.source === id && !seen.has(relation.target)) queue.push(relation.target);
        if (relation.target === id && !seen.has(relation.source)) queue.push(relation.source);
      }
    }
  }
  const columns = Math.max(1, Math.min(3, ordered.length));
  const result: PositionedEntity[] = [];
  let y = 36;
  for (let index = 0; index < ordered.length; index += columns) {
    const row = ordered.slice(index, index + columns);
    const height = Math.max(...row.map((entity) => 52 + (entity.fields?.length ?? 0) * 28));
    row.forEach((entity, column) => result.push({ ...entity, x: 36 + column * 360, y, height: 52 + (entity.fields?.length ?? 0) * 28 }));
    y += height + 100;
  }
  return result;
}

export interface RelationPath {
  path: string;
  x: number;
  y: number;
  label: string;
}

export function relationPath(relation: DiagramRelation, entities: PositionedEntity[]): RelationPath | null {
  const source = entities.find((entity) => entity.id === relation.source);
  const target = entities.find((entity) => entity.id === relation.target);
  if (!source || !target) return null;
  const anchorY = (entity: PositionedEntity, field?: string | null): number => {
    const index = entity.fields?.findIndex((item) => item.name === field) ?? -1;
    return entity.y + (index < 0 ? 24 : 58 + index * 28);
  };
  const forward = target.x > source.x;
  const x1 = source.x + (forward || source === target ? 260 : 0);
  const x2 = target.x + (forward ? 0 : 260);
  const y1 = anchorY(source, relation.sourceField);
  const y2 = anchorY(target, relation.targetField);
  const bend = source === target ? x1 + 60 : source.y === target.y ? (x1 + x2) / 2 : Math.max(x1, x2) + 40;
  const cardinality = { "one-to-one": "1 : 1", "one-to-many": "1 : N", "many-to-one": "N : 1", "many-to-many": "N : N" }[relation.cardinality ?? "one-to-many"];
  return {
    path: source === target && y1 === y2
      ? `M ${x1} ${y1} H ${bend} V ${y1 - 24} H ${x1}`
      : `M ${x1} ${y1} H ${bend} V ${y2} H ${x2}`,
    x: bend,
    y: (y1 + y2) / 2 - 8,
    label: relation.label ? `${relation.label} (${cardinality})` : cardinality,
  };
}
