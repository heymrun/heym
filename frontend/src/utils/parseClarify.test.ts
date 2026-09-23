import { describe, expect, it } from "vitest";

import type { ClarifyAnswer, ClarifyQuestion } from "@/types/clarify";

import { extractClarifyBlock, serializeAnswers } from "./parseClarify";

function clarifyMessage(payload: unknown): string {
  return `Before I build it:\n\n\`\`\`heym-clarify\n${JSON.stringify(payload)}\n\`\`\``;
}

const credentialQuestion: ClarifyQuestion = {
  id: "google_auth",
  text: "Which credential should the Google request use?",
  type: "single",
  prefillLabel: "Header",
  options: [
    { label: "google", prefill: "x-goog-api-key" },
    { label: "burak31" },
    { label: "No credential" },
  ],
};

function answer(selected: string[], prefill?: string): ClarifyAnswer {
  return { id: "google_auth", text: credentialQuestion.text, selected, other: "", prefill };
}

describe("extractClarifyBlock", () => {
  it("normalizes string options into labelled options", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [{ id: "trigger", text: "Trigger?", type: "single", options: ["Webhook", "Manual"] }],
      }),
    );

    expect(questions?.[0].options).toEqual([{ label: "Webhook" }, { label: "Manual" }]);
  });

  it("keeps editable prefills and their label on single-choice questions", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [
          {
            id: "google_auth",
            text: "Which credential?",
            type: "single",
            prefillLabel: "Header",
            options: [{ label: "google", prefill: "x-goog-api-key" }, "No credential"],
          },
        ],
      }),
    );

    expect(questions?.[0].prefillLabel).toBe("Header");
    expect(questions?.[0].options).toEqual([
      { label: "google", prefill: "x-goog-api-key" },
      { label: "No credential" },
    ]);
  });

  it("drops prefills on multi-choice questions", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [
          { id: "outputs", text: "Outputs?", type: "multi", options: [{ label: "Email", prefill: "x" }] },
        ],
      }),
    );

    expect(questions?.[0].options).toEqual([{ label: "Email" }]);
  });

  it("rejects an option object without a label", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [{ id: "q", text: "Pick", type: "single", options: [{ prefill: "x" }] }],
      }),
    );

    expect(questions).toBeNull();
  });
});

describe("serializeAnswers", () => {
  it("sends the edited prefill under the question's label", () => {
    const text = serializeAnswers([credentialQuestion], [answer(["google"], "x-goog-api-key")]);

    expect(text).toBe(
      '[Plan answers]\n- Which credential should the Google request use? → google (Header: "x-goog-api-key")',
    );
  });

  it("sends only the label when the prefill was cleared", () => {
    const text = serializeAnswers([credentialQuestion], [answer(["google"], "  ")]);

    expect(text).toContain("→ google");
    expect(text).not.toContain("Header");
  });

  it("ignores a leftover prefill when the chosen option has none", () => {
    const text = serializeAnswers([credentialQuestion], [answer(["No credential"], "x-goog-api-key")]);

    expect(text).toContain("→ No credential");
    expect(text).not.toContain("x-goog-api-key");
  });

  it("falls back to a generic label when the question names none", () => {
    const question: ClarifyQuestion = { ...credentialQuestion, prefillLabel: undefined };

    const text = serializeAnswers([question], [answer(["google"], "Authorization")]);

    expect(text).toContain('→ google (Value: "Authorization")');
  });
});

const createQuestion: ClarifyQuestion = {
  id: "github",
  text: "Which GitHub credential should I use?",
  type: "single",
  options: [
    { label: "github-work" },
    { label: "Create a new credential", create: { type: "github", name: "github-personal" } },
    { label: "Continue without" },
  ],
};

describe("credential create options", () => {
  it("keeps a create option with a known type and a name", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [
          {
            id: "github",
            text: "Which GitHub credential?",
            type: "single",
            options: [
              "github-work",
              { label: "Create a new credential", create: { type: "github", name: " github-personal " } },
            ],
          },
        ],
      }),
    );

    expect(questions?.[0].options?.[1]).toEqual({
      label: "Create a new credential",
      create: { type: "github", name: "github-personal" },
    });
  });

  it("falls back to a plain label for an unknown type, a blank name or an inherited key", () => {
    for (const create of [
      { type: "not-a-type", name: "x" },
      { type: "github", name: "  " },
      { type: "toString", name: "x" },
      "github",
    ]) {
      const questions = extractClarifyBlock(
        clarifyMessage({
          questions: [{ id: "q", text: "Pick", type: "single", options: [{ label: "Create", create }] }],
        }),
      );

      expect(questions?.[0].options).toEqual([{ label: "Create" }]);
    }
  });

  it("drops create options on multi-choice questions", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [
          {
            id: "q",
            text: "Pick",
            type: "multi",
            options: [{ label: "Create", create: { type: "github", name: "gh" } }],
          },
        ],
      }),
    );

    expect(questions?.[0].options).toEqual([{ label: "Create" }]);
  });

  it("sends the created credential's saved name and type", () => {
    const text = serializeAnswers(
      [createQuestion],
      [
        {
          id: "github",
          text: createQuestion.text,
          selected: ["Create a new credential"],
          other: "",
          credential: { type: "github", name: "gh-renamed" },
        },
      ],
    );

    expect(text).toBe(
      '[Plan answers]\n- Which GitHub credential should I use? → Created credential "gh-renamed" (github)',
    );
  });
});

const SHEET_ID = "5f0c2e8a-3b1d-4c7e-9a2f-6d8b1e4c3a90";

describe("credential edit options", () => {
  it("keeps an edit option with a credential id", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({
        questions: [
          {
            id: "sheet",
            text: "Which credential should I open?",
            type: "single",
            options: [{ label: "Update sheet", edit: { id: SHEET_ID } }, "Cancel"],
          },
        ],
      }),
    );

    expect(questions?.[0].options).toEqual([
      { label: "Update sheet", edit: { id: SHEET_ID } },
      { label: "Cancel" },
    ]);
  });

  it("falls back to a plain label when the id is not a credential id", () => {
    for (const edit of [{ id: "sheet" }, { id: 42 }, "5f0c2e8a"]) {
      const questions = extractClarifyBlock(
        clarifyMessage({
          questions: [{ id: "q", text: "Pick", type: "single", options: [{ label: "Update", edit }] }],
        }),
      );

      expect(questions?.[0].options).toEqual([{ label: "Update" }]);
    }
  });

  it("sends the updated credential's name and type", () => {
    const question: ClarifyQuestion = {
      id: "sheet",
      text: "Which credential should I open?",
      type: "single",
      options: [{ label: "Update sheet", edit: { id: SHEET_ID } }],
    };

    const text = serializeAnswers(
      [question],
      [
        {
          id: "sheet",
          text: question.text,
          selected: ["Update sheet"],
          other: "",
          credential: { type: "google_sheets", name: "sheet" },
        },
      ],
    );

    expect(text).toBe(
      '[Plan answers]\n- Which credential should I open? → Updated credential "sheet" (google_sheets)',
    );
  });
});

describe("optional questions", () => {
  it("keeps the optional flag", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({ questions: [{ id: "f", text: "Any label filter?", type: "text", optional: true }] }),
    );

    expect(questions?.[0].optional).toBe(true);
  });

  it("rejects a non-boolean optional flag", () => {
    const questions = extractClarifyBlock(
      clarifyMessage({ questions: [{ id: "f", text: "Filter?", type: "text", optional: "yes" }] }),
    );

    expect(questions).toBeNull();
  });

  it("marks a skipped optional question", () => {
    const question: ClarifyQuestion = { id: "f", text: "Any label filter?", type: "text", optional: true };

    const text = serializeAnswers([question], [{ id: "f", text: question.text, selected: [], other: "" }]);

    expect(text).toBe("[Plan answers]\n- Any label filter? → (skipped)");
  });
});
