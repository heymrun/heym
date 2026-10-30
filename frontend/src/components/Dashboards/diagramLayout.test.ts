import { describe, expect, it } from "vitest";

import { dependencyPaths, entityLayout, entityScene, ganttLayout, relationPath, taskTime } from "@/components/Dashboards/diagramLayout";
import { chartTypeExample } from "@/lib/chartTypeExamples";

interface Point { x: number; y: number }
interface Rect { x: number; y: number; width: number; height: number }

function crossesRect(a: Point, b: Point, rect: Rect): boolean {
  if (a.x === b.x) return a.x > rect.x && a.x < rect.x + rect.width &&
    Math.max(a.y, b.y) > rect.y && Math.min(a.y, b.y) < rect.y + rect.height;
  return a.y > rect.y && a.y < rect.y + rect.height &&
    Math.max(a.x, b.x) > rect.x && Math.min(a.x, b.x) < rect.x + rect.width;
}

describe("diagram layouts", () => {
  it("attaches Gantt arrows at bar edges without crossing overlapping or intervening tasks", () => {
    const tasks = ganttLayout([
      { id: "plan", label: "Planning", start: "2026-10-01", end: "2026-10-04" },
      { id: "design", label: "Design", start: "2026-10-04", end: "2026-10-12", dependencies: ["plan"] },
      { id: "backend", label: "Backend", start: "2026-10-08", end: "2026-10-20", dependencies: ["design"] },
      { id: "frontend", label: "Frontend", start: "2026-10-09", end: "2026-10-24", dependencies: ["design"] },
    ], { width: 600, height: 320 }).tasks;
    for (const edge of dependencyPaths(tasks)) {
      const target = edge.points.at(-1)!;
      const approach = edge.points.at(-2)!;
      expect(approach.x).toBeLessThan(target.x);
      expect(approach.y).toBe(target.y);
      for (let index = 1; index < edge.points.length; index++) {
        for (const task of tasks) {
          expect(crossesRect(edge.points[index - 1], edge.points[index], { ...task, height: 24 }), `${edge.key} crosses ${task.id}`).toBe(false);
        }
      }
    }
  });

  it("aligns UTC date-only and offset timestamps and draws task dependencies", () => {
    expect(taskTime("2026-10-01")).toBe(taskTime("2026-10-01T02:00:00+02:00"));
    const layout = ganttLayout(chartTypeExample("gantt").payload.tasks!);
    expect(layout.tasks[1].x).toBeGreaterThan(layout.tasks[0].x);
    expect(layout.tasks[0].completion).toBe(100);
    expect(dependencyPaths(layout.tasks)).toHaveLength(2);
    expect(layout.ticks.length).toBeGreaterThanOrEqual(2);
  });

  it("handles milestones, invalid rows and missing dependency ids without NaN geometry", () => {
    const layout = ganttLayout([
      { id: "a", label: "Milestone", start: "2026-10-01", end: "2026-10-01", dependencies: ["missing"] },
      { id: "bad", label: "Bad", start: "bad", end: "bad" },
    ]);
    expect(layout.tasks).toHaveLength(1);
    expect(layout.tasks[0].width).toBeGreaterThan(0);
    expect(dependencyPaths(layout.tasks)).toEqual([]);
    expect(ganttLayout([])).toMatchObject({ tasks: [], ticks: [] });
  });

  it("anchors database links to fields and labels the relationship cardinality", () => {
    const graph = chartTypeExample("erDiagram").payload;
    const entities = entityLayout(graph.entities!, graph.relations!);
    const path = relationPath(graph.relations![0], entities);
    expect(path?.label).toBe("1 : N");
    expect(path?.path).not.toContain("NaN");
    expect(relationPath({ source: "missing", target: "orders" }, entities)).toBeNull();
    expect(relationPath({ source: "orders", target: "orders", cardinality: "one-to-one" }, entities)?.label).toBe("1 : 1");
  });

  it("keeps disconnected entities and fields in separate rows without overlap", () => {
    const entities = entityLayout(Array.from({ length: 5 }, (_, i) => ({ id: String(i), label: String(i), fields: [{ name: "id" }] })), []);
    expect(entities).toHaveLength(5);
    expect(entities[3].y).toBeGreaterThan(entities[0].y + entities[0].height);
  });

  it("fits Gantt geometry to width and height and reduces date ticks in narrow widgets", () => {
    const tasks = chartTypeExample("gantt").payload.tasks!;
    const narrow = ganttLayout(tasks, { width: 300, height: 160 });
    const large = ganttLayout(tasks, { width: 1000, height: 500 });
    expect(narrow.width).toBe(300);
    expect(narrow.height).toBe(160);
    expect(large.width).toBe(1000);
    expect(large.height).toBe(500);
    expect(narrow.ticks.length).toBeLessThan(large.ticks.length);
    expect(large.tasks[0].y).toBeGreaterThan(100);
    for (const layout of [narrow, large]) {
      for (const task of layout.tasks) {
        expect(task.x + task.width).toBeLessThanOrEqual(layout.width - 20);
        expect(task.y + 24).toBeLessThan(layout.height);
      }
    }
    const busy = ganttLayout(Array.from({ length: 30 }, (_, i) => ({ ...tasks[0], id: String(i) })), { width: 300, height: 160 });
    expect(busy.height).toBeGreaterThan(160);
    expect(busy.tasks[1].y - busy.tasks[0].y).toBeGreaterThanOrEqual(32);
  });

  it("uses a different entity arrangement for tall and wide widgets", () => {
    const entities = Array.from({ length: 4 }, (_, i) => ({ id: String(i), label: `Table ${i}`, fields: [{ name: "id" }] }));
    const wide = entityScene(entities, [], { width: 1000, height: 200 });
    const tall = entityScene(entities, [], { width: 300, height: 700 });
    expect(new Set(wide.entities.map((entity) => entity.y)).size).toBe(1);
    expect(new Set(tall.entities.map((entity) => entity.y)).size).toBeGreaterThan(1);
  });

  it("keeps wrapped relationship labels outside cards and inside the scene bounds", () => {
    const entities = Array.from({ length: 4 }, (_, i) => ({ id: String(i), label: `Table ${i}`, fields: [{ name: "id" }, { name: "parent_id" }] }));
    const relations = [
      { source: "0", target: "1", sourceField: "id", targetField: "parent_id", label: "A long relationship description" },
      { source: "0", target: "3", label: "contains" },
      { source: "3", target: "0", label: "belongs to" },
      { source: "1", target: "1", label: "self reference" },
    ];
    for (const viewport of [{ width: 400, height: 180 }, { width: 500, height: 500 }, { width: 1000, height: 300 }]) {
      const scene = entityScene(entities, relations, viewport);
      for (const path of scene.relations) {
        expect(path.lines.length).toBeLessThanOrEqual(4);
        expect(path.x - path.labelWidth / 2).toBeGreaterThanOrEqual(0);
        expect(path.y - path.labelHeight / 2).toBeGreaterThanOrEqual(0);
        expect(path.x + path.labelWidth / 2).toBeLessThan(scene.width);
        expect(path.y + path.labelHeight / 2).toBeLessThan(scene.height);
        const caption = { x: path.x - path.labelWidth / 2, y: path.y - path.labelHeight / 2, width: path.labelWidth, height: path.labelHeight };
        for (const connection of scene.relations) {
          for (let index = 1; index < connection.points.length; index++) {
            expect(crossesRect(connection.points[index - 1], connection.points[index], caption), `${path.label} caption cuts ${connection.label}`).toBe(false);
          }
        }
        for (const entity of scene.entities) {
          const overlaps = path.x - path.labelWidth / 2 < entity.x + entity.width &&
            path.x + path.labelWidth / 2 > entity.x && path.y - path.labelHeight / 2 < entity.y + entity.height &&
            path.y + path.labelHeight / 2 > entity.y;
          expect(overlaps, `${path.label} overlaps ${entity.id}`).toBe(false);
        }
      }
    }
  });
});
