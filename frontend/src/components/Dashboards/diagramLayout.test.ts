import { describe, expect, it } from "vitest";

import { dependencyPaths, entityLayout, ganttLayout, relationPath, taskTime } from "@/components/Dashboards/diagramLayout";
import { chartTypeExample } from "@/lib/chartTypeExamples";

describe("diagram layouts", () => {
  it("aligns UTC date-only and offset timestamps and draws task dependencies", () => {
    expect(taskTime("2026-10-01")).toBe(taskTime("2026-10-01T02:00:00+02:00"));
    const layout = ganttLayout(chartTypeExample("gantt").payload.tasks!);
    expect(layout.tasks[1].x).toBeGreaterThan(layout.tasks[0].x);
    expect(layout.tasks[0].completion).toBe(100);
    expect(dependencyPaths(layout.tasks)).toHaveLength(2);
    expect(layout.ticks).toHaveLength(5);
  });

  it("handles milestones, invalid rows and missing dependency ids without NaN geometry", () => {
    const layout = ganttLayout([
      { id: "a", label: "Milestone", start: "2026-10-01", end: "2026-10-01", dependencies: ["missing"] },
      { id: "bad", label: "Bad", start: "bad", end: "bad" },
    ]);
    expect(layout.tasks).toHaveLength(1);
    expect(layout.tasks[0].width).toBeGreaterThan(0);
    expect(dependencyPaths(layout.tasks)).toEqual([]);
    expect(ganttLayout([])).toEqual({ tasks: [], ticks: [] });
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
});
