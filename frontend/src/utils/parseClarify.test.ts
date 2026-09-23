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
