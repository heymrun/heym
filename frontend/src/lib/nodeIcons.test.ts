import { describe, expect, it } from "vitest";

import { NODE_DEFINITIONS } from "@/types/node";

import { nodeIconColorClass, nodeIcons } from "./nodeIcons";

describe("nodeIcons", () => {
  it("has an icon and color class for every node definition", () => {
    for (const type of Object.keys(NODE_DEFINITIONS) as Array<keyof typeof NODE_DEFINITIONS>) {
      expect(nodeIcons[type]).toBeTruthy();
      expect(nodeIconColorClass[type]).toBeTruthy();
    }
  });
});
