import { describe, expect, it } from "vitest";

import { getDecisionExpressionFields } from "@/lib/decisionExpressionFields";
import type { NodeData } from "@/types/workflow";

function keys(data: Partial<NodeData>): string[] {
  return getDecisionExpressionFields({ label: "decision", ...data }).map((field) => field.key);
}

describe("getDecisionExpressionFields", () => {
  it("offers only the body while the custom body is on", () => {
    expect(
      keys({
        customBodyEnabled: true,
        imagesEnabled: true,
        images: [{ name: "photo", source: "" }],
      }),
    ).toEqual(["customBody"]);
  });

  it("lists image sources after the state while images are on", () => {
    const fields = getDecisionExpressionFields({
      label: "decision",
      imagesEnabled: true,
      images: [
        { name: "photo", source: "$input.body.url" },
        { name: "", source: "" },
      ],
    });
    expect(fields).toEqual([
      { key: "state", label: "State" },
      { key: "img:0:source", label: "photo - image" },
      { key: "img:1:source", label: "image 2 - image" },
    ]);
  });

  it("leaves image sources out while images are off", () => {
    expect(keys({ imagesEnabled: false, images: [{ name: "photo", source: "" }] })).toEqual([
      "state",
    ]);
  });

  it("gives a box its instructions only, even when it carries old criteria", () => {
    expect(
      keys({
        questions: [
          {
            id: "dog",
            type: "box",
            instructions: "the dog in `photo`",
            levels: ["left", "over"],
          },
        ],
      }),
    ).toEqual(["state", "q:0:instructions"]);
  });

  it("keeps score levels and noul criteria", () => {
    expect(
      keys({
        questions: [
          { id: "s", type: "score", instructions: "How?", levels: ["a", "b"] },
          { id: "n", type: "noul", instructions: "Is it?" },
        ],
      }),
    ).toEqual([
      "state",
      "q:0:instructions",
      "q:0:level:0",
      "q:0:level:1",
      "q:1:instructions",
      "q:1:criteriaTrue",
      "q:1:criteriaFalse",
    ]);
  });
});
