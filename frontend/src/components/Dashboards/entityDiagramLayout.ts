import type { DiagramEntity, DiagramRelation } from "@/types/dashboard";
import type { DiagramSize } from "./diagramLayout";

const CARD_WIDTH = 240;
const HEADER_HEIGHT = 36;
const FIELD_HEIGHT = 26;
const COLUMN_GAP = 112;
const ROW_GAP = 96;
const PADDING = 32;

export interface PositionedEntity extends DiagramEntity {
  x: number;
  y: number;
  width: number;
  height: number;
  row: number;
  rowBottom: number;
  gap: number;
  rowGap: number;
}

export interface DiagramPoint { x: number; y: number }

export interface RelationPath {
  path: string;
  points: DiagramPoint[];
  x: number;
  y: number;
  label: string;
  lines: string[];
  labelWidth: number;
  labelHeight: number;
}

export interface EntityScene extends DiagramSize {
  entities: PositionedEntity[];
  relations: RelationPath[];
}

function orderedEntities(entities: DiagramEntity[], relations: DiagramRelation[]): DiagramEntity[] {
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
  return ordered;
}

function arrange(ordered: DiagramEntity[], columns: number, viewport: DiagramSize): PositionedEntity[] {
  const padding = viewport.width < 600 ? 16 : PADDING;
  const gap = Math.max(64, Math.min(COLUMN_GAP, viewport.width * 0.16));
  const rowGap = ROW_GAP;
  const cardWidth = Math.max(180, Math.min(CARD_WIDTH, (viewport.width - padding * 2 - gap * (columns - 1)) / columns));
  const result: PositionedEntity[] = [];
  let y = padding;
  for (let index = 0; index < ordered.length; index += columns) {
    const row = ordered.slice(index, index + columns);
    const heights = row.map((entity) => HEADER_HEIGHT + 12 + (entity.fields?.length ?? 0) * FIELD_HEIGHT);
    const rowBottom = y + Math.max(...heights);
    row.forEach((entity, column) => result.push({
      ...entity, x: padding + column * (cardWidth + gap), y,
      width: cardWidth, height: heights[column], row: index / columns, rowBottom, gap, rowGap,
    }));
    y = rowBottom + rowGap;
  }
  return result;
}

function wrapLabel(text: string, width: number): string[] {
  const limit = Math.max(5, Math.floor(width / 7.5));
  const words = text.trim().split(/\s+/);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (line && (line + " " + word).length > limit) {
      lines.push(line);
      line = "";
    }
    line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  return lines.slice(0, 3).map((value, index) =>
    value.length > limit || (index === 2 && lines.length > 3) ? `${value.slice(0, limit - 1)}…` : value,
  );
}

/** Route between cards through column/row gutters, keeping captions out of entity bodies. */
export function relationPath(relation: DiagramRelation, entities: PositionedEntity[], lane = 0): RelationPath | null {
  const source = entities.find((entity) => entity.id === relation.source);
  const target = entities.find((entity) => entity.id === relation.target);
  if (!source || !target) return null;
  const anchorY = (entity: PositionedEntity, field?: string | null): number => {
    const index = entity.fields?.findIndex((item) => item.name === field) ?? -1;
    return entity.y + (index < 0 ? HEADER_HEIGHT / 2 : HEADER_HEIGHT + 12 + index * FIELD_HEIGHT);
  };
  const y1 = anchorY(source, relation.sourceField);
  const y2 = anchorY(target, relation.targetField);
  const forward = target.x > source.x;
  const gap = source.gap;
  const adjacent = source.row === target.row && Math.abs(Math.abs(source.x - target.x) - source.width - gap) < 1;
  const cardinality = { "one-to-one": "1 : 1", "one-to-many": "1 : N", "many-to-one": "N : 1", "many-to-many": "N : N" }[relation.cardinality ?? "one-to-many"];
  const lines = [...(relation.label ? wrapLabel(relation.label, gap - 12) : []), cardinality];
  const labelWidth = gap - 12;
  const labelHeight = lines.length * 14 + 8;
  const points: DiagramPoint[] = [];
  let x: number;
  let y: number;
  if (adjacent) {
    const x1 = source.x + (forward ? source.width : 0);
    const x2 = target.x + (forward ? 0 : target.width);
    x = (x1 + x2) / 2;
    y = Math.min(y1, y2) - labelHeight / 2 - 10;
    points.push({ x: x1, y: y1 }, { x, y: y1 }, { x, y: y2 }, { x: x2, y: y2 });
  } else {
    const x1 = source.x + source.width;
    const x2 = target.x + target.width;
    const offset = 16 + (lane % 4) * 4;
    const lane1 = x1 + offset;
    const lane2 = x2 + offset;
    const routeY = source === target || source.row === target.row || source.y < target.y ? source.rowBottom + 12 : target.rowBottom + 12;
    points.push({ x: x1, y: y1 }, { x: lane1, y: y1 }, { x: lane1, y: routeY },
      { x: lane2, y: routeY }, { x: lane2, y: y2 }, { x: x2, y: y2 });
    x = lane1 === lane2 ? lane1 - labelWidth / 2 - 8 : (lane1 + lane2) / 2;
    y = routeY + labelHeight / 2 + 8;
  }
  return {
    path: points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" "), points, x, y,
    label: relation.label ? `${relation.label} (${cardinality})` : cardinality,
    lines, labelWidth, labelHeight,
  };
}

interface CaptionRect { left: number; right: number; top: number; bottom: number }

function captionRect(path: RelationPath, y: number): CaptionRect {
  return { left: path.x - path.labelWidth / 2 - 4, right: path.x + path.labelWidth / 2 + 4,
    top: y - path.labelHeight / 2 - 4, bottom: y + path.labelHeight / 2 + 4 };
}

function placeCaptions(paths: RelationPath[], entities: PositionedEntity[]): RelationPath[] {
  const segments = paths.flatMap((path) => path.points.slice(1).map((point, index) => ({ a: path.points[index], b: point })));
  const occupied: CaptionRect[] = entities.map((entity) => ({ left: entity.x, right: entity.x + entity.width, top: entity.y, bottom: entity.y + entity.height }));
  return paths.map((path) => {
    const intersects = (y: number): boolean => {
      const box = captionRect(path, y);
      return occupied.some((rect) => box.left < rect.right && box.right > rect.left && box.top < rect.bottom && box.bottom > rect.top) ||
        segments.some(({ a, b }) => a.x === b.x
          ? a.x > box.left && a.x < box.right && Math.max(a.y, b.y) > box.top && Math.min(a.y, b.y) < box.bottom
          : a.y > box.top && a.y < box.bottom && Math.max(a.x, b.x) > box.left && Math.min(a.x, b.x) < box.right);
    };
    const offsets = [0, ...Array.from({ length: 20 }, (_, index) => [-(index + 1) * 14, (index + 1) * 14]).flat()];
    const offset = offsets.find((value) => !intersects(path.y + value));
    const y = offset === undefined
      ? Math.min(0, ...occupied.map((rect) => rect.top), ...segments.flatMap(({ a, b }) => [a.y, b.y])) - path.labelHeight / 2 - 12
      : path.y + offset;
    occupied.push(captionRect(path, y));
    return { ...path, y };
  });
}

function sceneFor(ordered: DiagramEntity[], relations: DiagramRelation[], columns: number, viewport: DiagramSize): EntityScene {
  const arranged = arrange(ordered, columns, viewport);
  const routes = relations.map((relation, index) => relationPath(relation, arranged, index))
    .filter((path) => path !== null);
  const connections = placeCaptions(routes, arranged);
  const top = Math.min(0, ...connections.map((path) => path.y - path.labelHeight / 2 - 8));
  const entities = arranged.map((entity) => ({ ...entity, y: entity.y - top, rowBottom: entity.rowBottom - top }));
  const paths = connections.map((path) => {
    const points = path.points.map((point) => ({ ...point, y: point.y - top }));
    return { ...path, points, y: path.y - top,
      path: points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" "),
    };
  });
  const width = Math.max(1, ...entities.map((entity) => entity.x + entity.width),
    ...paths.flatMap((path) => [...path.points.map((point) => point.x), path.x + path.labelWidth / 2])) + PADDING;
  const height = Math.max(1, ...entities.map((entity) => entity.y + entity.height),
    ...paths.flatMap((path) => [...path.points.map((point) => point.y), path.y + path.labelHeight / 2])) + PADDING;
  return { entities, relations: paths, width, height };
}

/** Pick the row/column arrangement with the most legible fit for this widget's aspect ratio. */
export function entityScene(entities: DiagramEntity[], relations: DiagramRelation[], viewport: DiagramSize = { width: 640, height: 240 }): EntityScene {
  const ordered = orderedEntities(entities, relations);
  const candidates = Array.from({ length: Math.max(1, Math.min(4, ordered.length)) }, (_, i) => sceneFor(ordered, relations, i + 1, viewport));
  const score = (scene: EntityScene): number => {
    const scale = Math.min(viewport.width / scene.width, viewport.height / scene.height, 1.2);
    const coverage = scene.width * scene.height * scale * scale / Math.max(1, viewport.width * viewport.height);
    const fieldFont = scene.entities.some((entity) => entity.width < 220) ? 12 : 14;
    return scale * (fieldFont / 14) * (0.9 + 0.1 * coverage);
  };
  return candidates.reduce((best, candidate) => score(candidate) > score(best) ? candidate : best);
}

export function entityLayout(entities: DiagramEntity[], relations: DiagramRelation[], viewport?: DiagramSize): PositionedEntity[] {
  return entityScene(entities, relations, viewport).entities;
}
