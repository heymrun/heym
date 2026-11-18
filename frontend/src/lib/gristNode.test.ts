import { readFile } from "node:fs/promises";

import { describe, expect, it } from "vitest";

import { NODE_DEFINITIONS } from "@/types/node";

describe("Grist node defaults", () => {
  it("starts with an empty gristRecordIds so placeholder is displayed and single ID is used", () => {
    expect(NODE_DEFINITIONS.grist.defaultData.gristRecordIds).toBe("");
  });

  it("initializes gristRecordIds as empty string in WorkflowCanvas default node data", async () => {
    const source = await readFile(
      new URL("../components/Canvas/WorkflowCanvas.vue", import.meta.url),
      "utf8",
    );
    expect(source).toMatch(/grist:\s*\{[\s\S]*?gristRecordIds:\s*""[\s\S]*?\},/);
  });
});
