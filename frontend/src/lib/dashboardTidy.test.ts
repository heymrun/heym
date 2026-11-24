import { describe, expect, it } from "vitest";

import { movedLayouts } from "@/lib/dashboardTidy";

const saved = [
  { id: "alpha", layout: { x: 0, y: 0, w: 6, h: 4 } },
  { id: "beta", layout: { x: 6, y: 0, w: 6, h: 4 } },
  { id: "gamma", layout: { x: 0, y: 4, w: 12, h: 4 } },
];

describe("movedLayouts", () => {
  it("lists the dragged widget and the widgets it pushed aside", () => {
    const grid = [
      { i: "alpha", x: 0, y: 4, w: 6, h: 4 },
      { i: "beta", x: 6, y: 4, w: 6, h: 4 },
      { i: "gamma", x: 0, y: 0, w: 12, h: 4 },
    ];
    expect(movedLayouts(grid, saved)).toEqual([
      { id: "alpha", layout: { x: 0, y: 4, w: 6, h: 4 } },
      { id: "beta", layout: { x: 6, y: 4, w: 6, h: 4 } },
      { id: "gamma", layout: { x: 0, y: 0, w: 12, h: 4 } },
    ]);
  });

  it("leaves out widgets that did not move, and items no widget owns", () => {
    const grid = [
      { i: "alpha", x: 0, y: 0, w: 6, h: 4 },
      { i: "beta", x: 6, y: 0, w: 6, h: 5 },
      { i: "gamma", x: 0, y: 4, w: 12, h: 4 },
      { i: "removed", x: 0, y: 9, w: 3, h: 3 },
    ];
    expect(movedLayouts(grid, saved)).toEqual([{ id: "beta", layout: { x: 6, y: 0, w: 6, h: 5 } }]);
  });
});
