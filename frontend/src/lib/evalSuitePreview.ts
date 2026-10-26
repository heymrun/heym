import type { EvalSuitePreview } from "@/types/chat";

/** An `eval_suite_saved` stream event as a link card, or null for anything else. */
export function parseEvalSuiteSaved(payload: Record<string, unknown>): EvalSuitePreview | null {
  const { type, suite_id: id, suite_name: name, suite_type: suiteType, suite_url: url } = payload;
  if (type !== "eval_suite_saved") return null;
  if (typeof id !== "string" || typeof name !== "string" || typeof url !== "string") return null;
  if (suiteType !== "prompt" && suiteType !== "agent") return null;
  // The card links inside Heym only, like the workflow card's `/workflows/<id>`.
  if (!url.startsWith("/evals?")) return null;
  return { id, name, suiteType, url };
}

/** The suites of one reply: a suite saved again replaces its earlier card. */
export function mergeEvalSuite(
  suites: EvalSuitePreview[],
  suite: EvalSuitePreview,
): EvalSuitePreview[] {
  if (!suites.some((existing) => existing.id === suite.id)) return [...suites, suite];
  return suites.map((existing) => (existing.id === suite.id ? suite : existing));
}
