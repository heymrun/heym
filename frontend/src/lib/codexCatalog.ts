/** Codex CLI model and reasoning-effort catalog (learn.chatgpt.com/docs/models). */

export const CODEX_MODEL_SUGGESTIONS = [
  "gpt-5.6-sol",
  "gpt-5.6-terra",
  "gpt-5.6-luna",
  "gpt-5.6",
  "gpt-5.5",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.3-codex-spark",
] as const;

export type CodexModelSuggestion = (typeof CODEX_MODEL_SUGGESTIONS)[number];

export const CODEX_REASONING_EFFORT_OPTIONS = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra High" },
  { value: "max", label: "Max" },
  { value: "ultra", label: "Ultra" },
] as const;

export type CodexReasoningEffort = (typeof CODEX_REASONING_EFFORT_OPTIONS)[number]["value"];
