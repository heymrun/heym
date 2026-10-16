import type { DecisionQuestion } from "@/types/workflow";

/** One question in the wire shape the decision endpoint expects. */
function wireQuestion(question: DecisionQuestion): Record<string, unknown> {
  const entry: Record<string, unknown> = {
    type: question.type,
    instructions: question.instructions ?? "",
  };
  if (question.type === "noul") {
    const criteria: Record<string, string> = {};
    if (question.criteriaTrue) criteria.true = question.criteriaTrue;
    if (question.criteriaFalse) criteria.false = question.criteriaFalse;
    if (Object.keys(criteria).length > 0) entry.criteria = criteria;
  } else if (question.type === "choice") {
    entry.criteria = Object.fromEntries(
      (question.options ?? []).map((option) => [option.key, option.description || null]),
    );
  } else if (question.type === "score") {
    entry.criteria = question.levels ?? [];
  }
  // A box takes instructions only.
  return entry;
}

/**
 * The request body the form describes, as pretty JSON, used to seed the custom body
 * editor. Images are not part of it: their data only exists at run time.
 */
export function buildDecisionSeedBody(
  model: string | undefined,
  state: string | undefined,
  questions: DecisionQuestion[],
): string {
  const wireQuestions: Record<string, unknown> = {};
  for (const question of questions) {
    const id = (question.id ?? "").trim();
    if (!id) continue;
    wireQuestions[id] = wireQuestion(question);
  }
  return JSON.stringify(
    {
      model: model || "jev-latest",
      state: state || "$input.text",
      questions: wireQuestions,
    },
    null,
    2,
  );
}
