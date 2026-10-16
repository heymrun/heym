import { describe, expect, it } from "vitest";

import type { DecisionQuestion } from "@/types/workflow";

import { buildDecisionSeedBody } from "./decisionSeedBody";

function seed(questions: DecisionQuestion[]): Record<string, unknown> {
  return JSON.parse(buildDecisionSeedBody("jev-1.14.0", "$input", questions)) as Record<
    string,
    unknown
  >;
}

describe("buildDecisionSeedBody", () => {
  it("falls back to the default model and state", () => {
    const body = JSON.parse(buildDecisionSeedBody("", "", [])) as Record<string, unknown>;
    expect(body).toEqual({ model: "jev-latest", state: "$input.text", questions: {} });
  });

  it("sends a box with instructions only, whatever else the row carries", () => {
    const body = seed([
      {
        id: "dog",
        type: "box",
        instructions: "the dog in `photo`",
        criteriaTrue: "left over",
        levels: ["left", "over"],
      },
    ]);
    expect(body.questions).toEqual({
      dog: { type: "box", instructions: "the dog in `photo`" },
    });
  });

  it("keeps score levels as an ordered array", () => {
    const body = seed([
      { id: "frustration", type: "score", instructions: "How upset?", levels: ["Calm", "Angry"] },
    ]);
    expect(body.questions).toEqual({
      frustration: { type: "score", instructions: "How upset?", criteria: ["Calm", "Angry"] },
    });
  });

  it("maps choice options and noul criteria", () => {
    const body = seed([
      {
        id: "team",
        type: "choice",
        instructions: "Which team?",
        options: [
          { key: "billing", description: "Payments" },
          { key: "other", description: "" },
        ],
      },
      { id: "is_dog", type: "noul", instructions: "Dog in `photo`?", criteriaTrue: "A dog" },
    ]);
    expect(body.questions).toEqual({
      team: { type: "choice", instructions: "Which team?", criteria: { billing: "Payments", other: null } },
      is_dog: { type: "noul", instructions: "Dog in `photo`?", criteria: { true: "A dog" } },
    });
  });

  it("skips rows without an id", () => {
    const body = seed([{ id: "  ", type: "noul", instructions: "Is it?" }]);
    expect(body.questions).toEqual({});
  });
});
